"""
EMA Voice Agent - Main Entry Point
LiveKit-based voice agent for EMA Production.
"""

import asyncio
import os
import json
import uuid
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Annotated, Optional

import httpx
import structlog
from dotenv import load_dotenv
from sim_orchestrator import SimAiOrchestrator, OrchestratorResponse

load_dotenv()

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.dev.ConsoleRenderer()
    ]
)
logger = structlog.get_logger()

EMA_API_URL = os.getenv("EMA_API_URL", "https://api.samantha.cx")
EMA_WEBHOOK_SECRET = os.getenv("EMA_WEBHOOK_SECRET", "")
LIVEKIT_URL = os.getenv("LIVEKIT_URL", "")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "")


def check_credentials():
    missing = []
    if not LIVEKIT_URL:
        missing.append("LIVEKIT_URL")
    if not LIVEKIT_API_KEY:
        missing.append("LIVEKIT_API_KEY")
    if not LIVEKIT_API_SECRET:
        missing.append("LIVEKIT_API_SECRET")
    return len(missing) == 0, missing


class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health" or self.path == "/":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            has_creds, missing = check_credentials()
            response = {"status": "standby" if not has_creds else "ready", "service": "ema-voice-agent", "missing_credentials": missing}
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def run_standby_server(port=10000):
    print("=" * 60)
    print("EMA Voice Agent - STANDBY MODE")
    print("Set: LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET")
    print(f"Health check: http://0.0.0.0:{port}/health")
    print("=" * 60)
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()


class EMAVoiceAgent:
    def __init__(self, session_id, call_sid=None):
        self.session_id = session_id
        self.call_sid = call_sid or session_id
        self.started_at = datetime.utcnow()
        self.turn_index = 0
        self.prompts = self._load_prompts()
        self.http_client = httpx.AsyncClient(timeout=10.0)
        self.orchestrator = SimAiOrchestrator(session_id)
        self.last_orchestrator_response: Optional[OrchestratorResponse] = None

    def _load_prompts(self):
        prompts = {}
        prompts_dir = Path(__file__).parent.parent / "prompts"
        if prompts_dir.exists():
            for f in prompts_dir.glob("*.md"):
                prompts[f.stem] = f.read_text(encoding="utf-8")
        if not prompts:
            prompts["welcome"] = "You are EMA, Emergency Maintenance Assistant."
        return prompts

    def get_system_prompt(self):
        return (
            self.prompts.get("ema-system-prompt") or
            self.prompts.get("welcome-agent") or
            "You are EMA, Emergency Maintenance Assistant."
        )

    async def send_webhook(self, event_type, data):
        payload = {"event_type": event_type, "session_id": self.session_id, "timestamp": datetime.utcnow().isoformat(), "data": data}
        async def _send():
            try:
                await self.http_client.post(f"{EMA_API_URL}/webhooks/livekit/{event_type.replace('_', '-')}", json=payload, headers={"X-Webhook-Secret": EMA_WEBHOOK_SECRET})
            except Exception as e:
                logger.error("webhook_failed", event_type=event_type, error=str(e))
        asyncio.create_task(_send())

    async def on_call_started(self, metadata=None):
        await self.send_webhook("call_initiated", {"metadata": metadata or {}})

    async def on_user_speech(self, text):
        await self.send_webhook("utterance", {"speaker": "tenant", "text": text})

    async def on_agent_speech(self, text):
        await self.send_webhook("utterance", {"speaker": "agent", "text": text})
        self.turn_index += 1

    async def on_call_ended(self):
        duration = (datetime.utcnow() - self.started_at).total_seconds()
        await self.send_webhook("call_ended", {"duration_seconds": duration})
        await self.http_client.aclose()

    # ============ FUNCTION CALLING TOOLS ============

    async def create_maintenance_ticket(self, issue_type: str, description: str, urgency: str, location: str) -> str:
        ticket_ref = f"TKT-{uuid.uuid4().hex[:8].upper()}"
        payload = {
            "ticket_ref": ticket_ref,
            "session_id": self.session_id,
            "call_sid": self.call_sid,
            "issue_type": issue_type,
            "description": description,
            "urgency": urgency,
            "location": location,
            "created_at": datetime.utcnow().isoformat()
        }
        try:
            resp = await self.http_client.post(
                f"{EMA_API_URL}/webhooks/voice-agent/create-ticket",
                json=payload,
                headers={"X-Webhook-Secret": EMA_WEBHOOK_SECRET}
            )
            if resp.status_code == 200 or resp.status_code == 201:
                logger.info("ticket_created", ticket_ref=ticket_ref, issue_type=issue_type)
                return f"I have created ticket {ticket_ref} for your {urgency} {issue_type} issue."
            else:
                logger.warning("ticket_create_api_error", status=resp.status_code)
                return f"I have logged your {urgency} {issue_type} issue. Reference: {ticket_ref}."
        except Exception as e:
            logger.error("ticket_create_failed", error=str(e))
            return f"I have noted your {urgency} {issue_type} issue. We will follow up shortly."

    async def find_available_vendor(self, service_type: str) -> str:
        try:
            resp = await self.http_client.get(
                f"{EMA_API_URL}/webhooks/voice-agent/find-vendor",
                params={"service_type": service_type, "session_id": self.session_id},
                headers={"X-Webhook-Secret": EMA_WEBHOOK_SECRET}
            )
            if resp.status_code == 200:
                data = resp.json()
                vendor_name = data.get("vendor_name", "a qualified technician")
                eta = data.get("eta", "within 2 hours")
                logger.info("vendor_found", service_type=service_type, vendor=vendor_name)
                return f"I found {vendor_name} for {service_type}. They can be there {eta}."
            else:
                logger.warning("vendor_api_error", status=resp.status_code)
                return f"I am arranging a {service_type} technician. They will call you within 2 hours."
        except Exception as e:
            logger.error("vendor_lookup_failed", error=str(e))
            return f"I am dispatching a {service_type} technician who will contact you shortly."

    async def escalate_to_manager(self, reason: str, urgency: str, summary: str) -> str:
        payload = {
            "session_id": self.session_id,
            "call_sid": self.call_sid,
            "reason": reason,
            "urgency": urgency,
            "summary": summary,
            "escalated_at": datetime.utcnow().isoformat()
        }
        try:
            resp = await self.http_client.post(
                f"{EMA_API_URL}/webhooks/voice-agent/escalate",
                json=payload,
                headers={"X-Webhook-Secret": EMA_WEBHOOK_SECRET}
            )
            logger.info("escalation_sent", reason=reason, urgency=urgency)
            if urgency == "emergency":
                return "I am notifying the property manager right now. They will call you back immediately."
            else:
                return "I have notified the property manager. They will reach out to you shortly."
        except Exception as e:
            logger.error("escalation_failed", error=str(e))
            return "I am escalating this to the property manager now."


# Module-level entrypoint (required for multiprocessing pickle)
async def entrypoint(ctx):
    from livekit.agents import AutoSubscribe, llm
    from livekit.plugins import deepgram, openai, silero
    from livekit import agents

    ema = EMAVoiceAgent(ctx.room.name, ctx.room.metadata)
    await ema.on_call_started({})

    # ============ FUNCTION CONTEXT WITH TOOLS ============
    fnc_ctx = llm.FunctionContext()

    @fnc_ctx.ai_callable(
        description="Create a maintenance ticket when you have gathered the issue details. Use after understanding what is wrong, where it is, and how urgent."
    )
    async def create_ticket(
        issue_type: Annotated[str, llm.TypeInfo(description="Type of issue: plumbing, electrical, hvac, appliance, locksmith, structural, pest, or other")],
        description: Annotated[str, llm.TypeInfo(description="Brief description of the problem as reported by tenant")],
        urgency: Annotated[str, llm.TypeInfo(description="Urgency level: emergency, urgent, or routine")],
        location: Annotated[str, llm.TypeInfo(description="Where in the unit: kitchen, bathroom, bedroom, living room, etc.")]
    ) -> str:
        return await ema.create_maintenance_ticket(issue_type, description, urgency, location)

    @fnc_ctx.ai_callable(
        description="Find an available vendor or technician for a specific service type. Use when you need to dispatch help."
    )
    async def find_vendor(
        service_type: Annotated[str, llm.TypeInfo(description="Service needed: plumbing, electrical, hvac, appliance, locksmith, or general")]
    ) -> str:
        return await ema.find_available_vendor(service_type)

    @fnc_ctx.ai_callable(
        description="Escalate to property manager for safety emergencies, complex situations, or when tenant requests to speak with management."
    )
    async def escalate(
        reason: Annotated[str, llm.TypeInfo(description="Why escalating: safety, complexity, tenant_request, or other")],
        urgency: Annotated[str, llm.TypeInfo(description="How urgent: emergency, high, or normal")],
        summary: Annotated[str, llm.TypeInfo(description="Brief summary of the situation for the property manager")]
    ) -> str:
        return await ema.escalate_to_manager(reason, urgency, summary)

    # ============ AGENT SETUP ============
    stt = deepgram.STT(model="nova-2", language="en-US")
    llm_inst = openai.LLM(model="gpt-4o-mini")
    tts = openai.TTS(voice="nova")

    assistant = agents.VoicePipelineAgent(
        vad=silero.VAD.load(),
        stt=stt,
        llm=llm_inst,
        tts=tts,
        fnc_ctx=fnc_ctx,
        chat_ctx=llm.ChatContext().append(role="system", text=ema.get_system_prompt())
    )

    @assistant.on("user_speech_committed")
    def on_user(msg):
        asyncio.create_task(ema.on_user_speech(msg.content))

    @assistant.on("agent_speech_committed")
    def on_agent(msg):
        asyncio.create_task(ema.on_agent_speech(msg.content))

    @assistant.on("function_calls_collected")
    def on_function_calls(calls):
        logger.info("function_calls", calls=[c.name for c in calls])

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    participant = await ctx.wait_for_participant()
    assistant.start(ctx.room, participant)
    await assistant.say("Hi, Ema here with emergency maintenance. If anyone is in danger, hang up and call 9-1-1. Otherwise, what is happening?", allow_interruptions=True)
    await assistant.wait_for_close()
    await ema.on_call_ended()


# Module-level request handler (required for multiprocessing pickle)
async def request_handler(req):
    await req.accept(entrypoint)


def run_livekit_agent():
    from livekit.agents import WorkerOptions, cli
    print("EMA Voice Agent - ACTIVE MODE (with Function Calling)")
    print(f"LiveKit URL: {LIVEKIT_URL}")
    print("Tools: create_ticket, find_vendor, escalate")
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, request_fnc=request_handler))


if __name__ == "__main__":
    has_creds, missing = check_credentials()
    if has_creds:
        run_livekit_agent()
    else:
        logger.warning("missing_credentials", missing=missing)
        run_standby_server()

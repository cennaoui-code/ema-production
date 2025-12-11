"""
EMA Voice Agent - Main Entry Point
LiveKit-based voice agent for EMA Production.
"""

import asyncio
import os
import json
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import httpx
import structlog
from dotenv import load_dotenv

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
        self.http_client = httpx.AsyncClient(timeout=5.0)

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
        return self.prompts.get("welcome", "You are EMA.")

    async def send_webhook(self, event_type, data):
        payload = {"event_type": event_type, "session_id": self.session_id, "timestamp": datetime.utcnow().isoformat(), "data": data}
        async def _send():
            try:
                await self.http_client.post(f"{EMA_API_URL}/webhooks/livekit/{event_type.replace('_', '-')}", json=payload, headers={"X-Webhook-Secret": EMA_WEBHOOK_SECRET})
            except:
                pass
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


# Module-level entrypoint (required for multiprocessing pickle)
async def entrypoint(ctx):
    from livekit.agents import AutoSubscribe, llm
    from livekit.plugins import deepgram, openai, silero
    from livekit import agents

    ema = EMAVoiceAgent(ctx.room.name, ctx.room.metadata)
    await ema.on_call_started({})
    
    stt = deepgram.STT(model="nova-2", language="en-US")
    llm_inst = openai.LLM(model="gpt-4o-mini")
    tts = openai.TTS(voice="nova")
    
    assistant = agents.VoicePipelineAgent(
        vad=silero.VAD.load(), 
        stt=stt, 
        llm=llm_inst, 
        tts=tts,
        chat_ctx=llm.ChatContext().append(role="system", text=ema.get_system_prompt())
    )

    @assistant.on("user_speech_committed")
    def on_user(msg):
        asyncio.create_task(ema.on_user_speech(msg.content))

    @assistant.on("agent_speech_committed")
    def on_agent(msg):
        asyncio.create_task(ema.on_agent_speech(msg.content))

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    participant = await ctx.wait_for_participant()
    assistant.start(ctx.room, participant)
    await assistant.say("Hello, this is EMA. How can I help?", allow_interruptions=True)
    await assistant.wait_for_close()
    await ema.on_call_ended()


# Module-level request handler (required for multiprocessing pickle)
async def request_handler(req):
    await req.accept(entrypoint)


def run_livekit_agent():
    from livekit.agents import WorkerOptions, cli
    print("EMA Voice Agent - ACTIVE MODE")
    print(f"LiveKit URL: {LIVEKIT_URL}")
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, request_fnc=request_handler))


if __name__ == "__main__":
    has_creds, missing = check_credentials()
    if has_creds:
        run_livekit_agent()
    else:
        logger.warning("missing_credentials", missing=missing)
        run_standby_server()

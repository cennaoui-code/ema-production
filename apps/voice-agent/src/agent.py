"""
EMA Voice Agent - Main Entry Point

This is the LiveKit-based voice agent for EMA Production.
It handles emergency maintenance calls for property management.

Run with:
    python src/agent.py dev     # Local development
    python src/agent.py start   # Production
"""

import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
import structlog
from dotenv import load_dotenv
from livekit import agents
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    JobRequest,
    WorkerOptions,
    cli,
    llm,
)
from livekit.plugins import deepgram, openai, silero

# Load environment variables
load_dotenv()

# Configure logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.dev.ConsoleRenderer()
    ]
)
logger = structlog.get_logger()

# Configuration
EMA_API_URL = os.getenv("EMA_API_URL", "https://api.samantha.cx")
EMA_WEBHOOK_SECRET = os.getenv("EMA_WEBHOOK_SECRET", "")


class EMAVoiceAgent:
    """
    Emergency Maintenance AI Voice Agent

    Handles voice conversations for:
    - Emergency intake and triage
    - Non-emergency maintenance requests
    - Dispatch coordination
    """

    def __init__(self, session_id: str, call_sid: Optional[str] = None):
        self.session_id = session_id
        self.call_sid = call_sid or session_id
        self.started_at = datetime.utcnow()
        self.turn_index = 0
        self.current_stage = "welcome"
        self.prompts = self._load_prompts()
        self.http_client = httpx.AsyncClient(timeout=5.0)

        logger.info("agent_initialized",
                   session_id=session_id,
                   prompts_loaded=len(self.prompts))

    def _load_prompts(self) -> dict:
        """Load agent prompts from prompts/ directory"""
        prompts = {}
        prompts_dir = Path(__file__).parent.parent / "prompts"

        if prompts_dir.exists():
            for prompt_file in prompts_dir.glob("*.md"):
                name = prompt_file.stem
                content = prompt_file.read_text(encoding="utf-8")
                prompts[name] = content

        # Default prompts if none loaded
        if not prompts:
            prompts["welcome"] = self._default_welcome_prompt()

        return prompts

    def _default_welcome_prompt(self) -> str:
        """Default prompt if no prompts are loaded"""
        return """You are EMA (Emergency Maintenance Assistant), a helpful AI voice agent
for property management emergency maintenance.

Your role:
1. Greet callers warmly
2. Determine if they have an emergency or non-emergency issue
3. Collect details about the problem
4. Classify the urgency
5. Provide next steps

Be conversational, empathetic, and efficient. Keep responses concise for voice.

Current session: {session_id}
"""

    def get_system_prompt(self) -> str:
        """Get the system prompt for the current stage"""
        # Map stages to prompt files
        stage_map = {
            "welcome": "welcome",
            "emergency_triage": "emergency-triage",
            "location": "location-detail-input-agent",
            "dispatch": "dispatch-router-agent",
        }

        prompt_key = stage_map.get(self.current_stage, "welcome")
        base_prompt = self.prompts.get(prompt_key, self._default_welcome_prompt())

        # Add session context
        context = f"""

---
Session Context:
- Session ID: {self.session_id}
- Call SID: {self.call_sid}
- Current Stage: {self.current_stage}
- Turn: {self.turn_index}
"""
        return base_prompt + context

    async def send_webhook(self, event_type: str, data: dict):
        """
        Send webhook to EMA API

        CRITICAL: This is fire-and-forget to avoid adding latency!
        We create a task and don't await it.
        """
        payload = {
            "event_type": event_type,
            "session_id": self.session_id,
            "call_sid": self.call_sid,
            "timestamp": datetime.utcnow().isoformat(),
            "data": data
        }

        async def _send():
            try:
                await self.http_client.post(
                    f"{EMA_API_URL}/webhooks/livekit/{event_type.replace('_', '-')}",
                    json=payload,
                    headers={"X-Webhook-Secret": EMA_WEBHOOK_SECRET}
                )
                logger.debug("webhook_sent", event_type=event_type)
            except Exception as e:
                logger.error("webhook_failed", event_type=event_type, error=str(e))

        # Fire and forget - don't block the conversation
        asyncio.create_task(_send())

    async def on_call_started(self, metadata: dict = None):
        """Called when a new call starts"""
        logger.info("call_started", session_id=self.session_id)
        await self.send_webhook("call_initiated", {
            "metadata": metadata or {},
            "started_at": self.started_at.isoformat()
        })

    async def on_user_speech(self, text: str):
        """Called when user speech is transcribed"""
        logger.info("user_speech", text=text[:100], turn=self.turn_index)
        await self.send_webhook("utterance", {
            "speaker": "tenant",
            "text": text,
            "turn_index": self.turn_index,
            "stage": self.current_stage
        })

    async def on_agent_speech(self, text: str):
        """Called when agent responds"""
        logger.info("agent_speech", text=text[:100], turn=self.turn_index)
        await self.send_webhook("utterance", {
            "speaker": "agent",
            "text": text,
            "turn_index": self.turn_index,
            "stage": self.current_stage
        })
        self.turn_index += 1

    async def on_call_ended(self):
        """Called when call ends"""
        duration = (datetime.utcnow() - self.started_at).total_seconds()
        logger.info("call_ended",
                   session_id=self.session_id,
                   duration=duration,
                   turns=self.turn_index)

        await self.send_webhook("call_ended", {
            "duration_seconds": duration,
            "total_turns": self.turn_index,
            "final_stage": self.current_stage
        })

        # Cleanup
        await self.http_client.aclose()


async def entrypoint(ctx: JobContext):
    """
    Main agent entry point - called for each new call/session
    """
    logger.info("new_session", room=ctx.room.name)

    # Initialize EMA agent
    ema = EMAVoiceAgent(
        session_id=ctx.room.name,
        call_sid=ctx.room.metadata
    )

    # Notify call started
    await ema.on_call_started({"room_metadata": ctx.room.metadata})

    # Configure Speech-to-Text (Deepgram)
    stt = deepgram.STT(
        model="nova-2",
        language="en-US",
        smart_format=True,
        punctuate=True,
    )

    # Configure Language Model (OpenAI)
    llm_instance = openai.LLM(
        model="gpt-4o-mini",  # Fast and cost-effective
        temperature=0.7,
    )

    # Configure Text-to-Speech (OpenAI)
    tts = openai.TTS(
        voice="nova",  # Natural, friendly voice
    )

    # Create voice pipeline
    assistant = agents.VoicePipelineAgent(
        vad=silero.VAD.load(),  # Voice Activity Detection
        stt=stt,
        llm=llm_instance,
        tts=tts,
        chat_ctx=llm.ChatContext().append(
            role="system",
            text=ema.get_system_prompt()
        ),
    )

    # Wire up events
    @assistant.on("user_speech_committed")
    def handle_user_speech(msg):
        asyncio.create_task(ema.on_user_speech(msg.content))

    @assistant.on("agent_speech_committed")
    def handle_agent_speech(msg):
        asyncio.create_task(ema.on_agent_speech(msg.content))

    # Connect to room
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Wait for participant
    participant = await ctx.wait_for_participant()
    logger.info("participant_joined", identity=participant.identity)

    # Start agent
    assistant.start(ctx.room, participant)

    # Initial greeting
    await assistant.say(
        "Hello, this is EMA, your Emergency Maintenance Assistant. "
        "How can I help you today?",
        allow_interruptions=True
    )

    # Run until call ends
    await assistant.wait_for_close()

    # Cleanup
    await ema.on_call_ended()
    logger.info("session_complete", room=ctx.room.name)


async def request_handler(request: JobRequest):
    """Handle incoming job requests (calls)"""
    logger.info("job_request", room=request.room.name)
    # Accept all calls for now
    # Future: Add workspace routing, call screening, etc.
    await request.accept(entrypoint)


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            request_fnc=request_handler,
        )
    )

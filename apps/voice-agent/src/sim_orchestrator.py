"""
Sim.ai Orchestrator - Workflow Decision Engine for EMA Voice Agent

This module integrates with Sim.ai to handle:
- Conversation routing (which agent/prompt to use next)
- State management (tracking issue details across turns)
- Tool decisions (when to create ticket, dispatch vendor, escalate)
- Emergency detection and escalation

The voice agent uses OpenAI for response generation, while Sim.ai
handles the workflow orchestration logic.
"""

import os
import json
import httpx
import structlog
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum

logger = structlog.get_logger()

# Sim.ai Configuration
SIMAI_API_URL = os.getenv("SIMAI_API_URL", "https://sim.ai/api")
SIMAI_API_KEY = os.getenv("SIMAI_API_KEY", "")
SIMAI_WORKFLOW_ID = os.getenv("SIMAI_WORKFLOW_ID", "")  # EMA Triage workflow ID


class ConversationStage(Enum):
    """Stages of the EMA conversation flow"""
    WELCOME = "welcome"
    TRIAGE = "triage"
    EMERGENCY_CHECK = "emergency_check"
    ISSUE_DETAILS = "issue_details"
    LOCATION = "location"
    URGENCY = "urgency"
    DISPATCH = "dispatch"
    ESCALATION = "escalation"
    CLOSING = "closing"


@dataclass
class ConversationState:
    """Tracks the state of the current conversation"""
    session_id: str
    stage: ConversationStage = ConversationStage.WELCOME

    # Issue details (collected through conversation)
    issue_type: Optional[str] = None
    issue_subtype: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    urgency: Optional[str] = None  # emergency, urgent, routine

    # Emergency flags
    is_emergency: bool = False
    emergency_type: Optional[str] = None  # gas, fire, flood, etc.
    safety_concern: bool = False

    # Tenant context (loaded from EMA API)
    tenant_name: Optional[str] = None
    tenant_phone: Optional[str] = None
    property_address: Optional[str] = None
    unit_number: Optional[str] = None
    property_manager: Optional[str] = None

    # Conversation history
    turns: List[Dict[str, str]] = field(default_factory=list)

    # Tools to execute
    pending_tools: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "stage": self.stage.value,
            "issue_type": self.issue_type,
            "issue_subtype": self.issue_subtype,
            "description": self.description,
            "location": self.location,
            "urgency": self.urgency,
            "is_emergency": self.is_emergency,
            "emergency_type": self.emergency_type,
            "safety_concern": self.safety_concern,
            "tenant_name": self.tenant_name,
            "property_address": self.property_address,
            "turn_count": len(self.turns),
        }


@dataclass
class OrchestratorResponse:
    """Response from Sim.ai orchestrator"""
    next_stage: ConversationStage
    prompt_name: str  # Which prompt to use for response
    tools_to_call: List[str]  # Tools the agent should invoke
    state_updates: Dict[str, Any]  # State fields to update
    should_escalate: bool = False
    escalation_reason: Optional[str] = None
    response_hint: Optional[str] = None  # Optional hint for LLM


class SimAiOrchestrator:
    """
    Orchestrates EMA conversation flow using Sim.ai workflows.

    For each user turn:
    1. Sends conversation context to Sim.ai
    2. Receives routing decision (next stage, tools, state updates)
    3. Updates local state
    4. Returns prompt and tool decisions to voice agent
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.state = ConversationState(session_id=session_id)
        self.http_client = httpx.AsyncClient(timeout=5.0)
        self._simai_enabled = bool(SIMAI_API_KEY and SIMAI_WORKFLOW_ID)

        if not self._simai_enabled:
            logger.warning("simai_not_configured",
                          message="Sim.ai not configured - using fallback routing")

    async def process_turn(
        self,
        user_text: str,
        agent_text: Optional[str] = None
    ) -> OrchestratorResponse:
        """
        Process a conversation turn and get routing decision.

        Args:
            user_text: What the user said
            agent_text: What the agent last said (if any)

        Returns:
            OrchestratorResponse with routing decisions
        """
        # Add to conversation history
        if agent_text:
            self.state.turns.append({"role": "agent", "text": agent_text})
        self.state.turns.append({"role": "user", "text": user_text})

        if self._simai_enabled:
            return await self._call_simai(user_text)
        else:
            return self._fallback_routing(user_text)

    async def _call_simai(self, user_text: str) -> OrchestratorResponse:
        """Call Sim.ai workflow API for routing decision"""
        try:
            payload = {
                "user_text": user_text,
                "state": self.state.to_dict(),
                "conversation_history": self.state.turns[-10:],  # Last 10 turns
            }

            resp = await self.http_client.post(
                f"{SIMAI_API_URL}/workflows/{SIMAI_WORKFLOW_ID}/execute",
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-API-Key": SIMAI_API_KEY,
                }
            )

            if resp.status_code == 200:
                data = resp.json()
                return self._parse_simai_response(data)
            else:
                logger.error("simai_api_error", status=resp.status_code)
                return self._fallback_routing(user_text)

        except Exception as e:
            logger.error("simai_call_failed", error=str(e))
            return self._fallback_routing(user_text)

    def _parse_simai_response(self, data: Dict[str, Any]) -> OrchestratorResponse:
        """Parse Sim.ai workflow response"""
        # Expected Sim.ai response format:
        # {
        #   "next_stage": "issue_details",
        #   "prompt": "damage-severity-input-agent",
        #   "tools": ["create_ticket"],
        #   "state_updates": {"issue_type": "plumbing", "urgency": "urgent"},
        #   "escalate": false
        # }

        next_stage = ConversationStage(data.get("next_stage", "triage"))

        # Apply state updates
        for key, value in data.get("state_updates", {}).items():
            if hasattr(self.state, key):
                setattr(self.state, key, value)

        return OrchestratorResponse(
            next_stage=next_stage,
            prompt_name=data.get("prompt", "ema-system-prompt"),
            tools_to_call=data.get("tools", []),
            state_updates=data.get("state_updates", {}),
            should_escalate=data.get("escalate", False),
            escalation_reason=data.get("escalation_reason"),
            response_hint=data.get("hint"),
        )

    def _fallback_routing(self, user_text: str) -> OrchestratorResponse:
        """
        Fallback routing when Sim.ai is not available.
        Uses simple keyword-based routing.
        """
        text_lower = user_text.lower()

        # Emergency detection
        emergency_keywords = [
            "fire", "smoke", "gas", "leak", "flood", "flooding",
            "burst", "sparks", "burning", "carbon monoxide", "co detector",
            "no heat", "freezing", "break in", "broken into", "intruder"
        ]

        is_emergency = any(kw in text_lower for kw in emergency_keywords)

        if is_emergency:
            self.state.is_emergency = True
            self.state.urgency = "emergency"

            # Detect emergency type
            if "fire" in text_lower or "smoke" in text_lower or "burning" in text_lower:
                self.state.emergency_type = "fire"
            elif "gas" in text_lower:
                self.state.emergency_type = "gas"
            elif "flood" in text_lower or "burst" in text_lower:
                self.state.emergency_type = "flood"
            elif "break" in text_lower or "intruder" in text_lower:
                self.state.emergency_type = "security"

            return OrchestratorResponse(
                next_stage=ConversationStage.ESCALATION,
                prompt_name="triage-emergency-escalation-agent",
                tools_to_call=["escalate"],
                state_updates={"is_emergency": True, "urgency": "emergency"},
                should_escalate=True,
                escalation_reason=f"Emergency detected: {self.state.emergency_type}",
            )

        # Issue type detection
        issue_keywords = {
            "plumbing": ["pipe", "leak", "water", "drain", "toilet", "faucet", "sink", "shower"],
            "electrical": ["power", "outlet", "light", "electric", "circuit", "breaker"],
            "hvac": ["heat", "ac", "air conditioning", "thermostat", "cold", "hot", "furnace"],
            "appliance": ["refrigerator", "fridge", "stove", "oven", "washer", "dryer", "dishwasher"],
            "locksmith": ["lock", "key", "door", "locked out"],
            "pest": ["bug", "roach", "mouse", "rat", "pest", "insect", "ant"],
            "structural": ["ceiling", "wall", "floor", "crack", "hole", "damage"],
        }

        detected_type = None
        for issue_type, keywords in issue_keywords.items():
            if any(kw in text_lower for kw in keywords):
                detected_type = issue_type
                break

        if detected_type:
            self.state.issue_type = detected_type

        # Determine next stage based on what we know
        if not self.state.issue_type:
            return OrchestratorResponse(
                next_stage=ConversationStage.TRIAGE,
                prompt_name="intake-router-agent",
                tools_to_call=[],
                state_updates={},
            )
        elif not self.state.location:
            return OrchestratorResponse(
                next_stage=ConversationStage.LOCATION,
                prompt_name="location-detail-input-agent",
                tools_to_call=[],
                state_updates={"issue_type": self.state.issue_type},
            )
        elif not self.state.urgency:
            return OrchestratorResponse(
                next_stage=ConversationStage.URGENCY,
                prompt_name="habitability-impact-input-agent",
                tools_to_call=[],
                state_updates={},
            )
        else:
            # Have enough info - dispatch
            return OrchestratorResponse(
                next_stage=ConversationStage.DISPATCH,
                prompt_name="dispatch-router-agent",
                tools_to_call=["create_ticket", "find_vendor"],
                state_updates={},
            )

    def get_current_prompt_name(self) -> str:
        """Get the prompt name for current stage"""
        stage_prompts = {
            ConversationStage.WELCOME: "ema-system-prompt",
            ConversationStage.TRIAGE: "intake-router-agent",
            ConversationStage.EMERGENCY_CHECK: "triage-emergency-type-agent-input",
            ConversationStage.ISSUE_DETAILS: "damage-severity-input-agent",
            ConversationStage.LOCATION: "location-detail-input-agent",
            ConversationStage.URGENCY: "habitability-impact-input-agent",
            ConversationStage.DISPATCH: "dispatch-router-agent",
            ConversationStage.ESCALATION: "triage-emergency-escalation-agent",
            ConversationStage.CLOSING: "tenant-call-agent",
        }
        return stage_prompts.get(self.state.stage, "ema-system-prompt")

    def get_context_for_llm(self) -> str:
        """
        Build context string for the LLM based on current state.
        This augments the system prompt with conversation-specific context.
        """
        context_parts = []

        if self.state.tenant_name:
            context_parts.append(f"Tenant Name: {self.state.tenant_name}")
        if self.state.property_address:
            context_parts.append(f"Property: {self.state.property_address}")
        if self.state.unit_number:
            context_parts.append(f"Unit: {self.state.unit_number}")
        if self.state.issue_type:
            context_parts.append(f"Issue Type: {self.state.issue_type}")
        if self.state.location:
            context_parts.append(f"Location in unit: {self.state.location}")
        if self.state.urgency:
            context_parts.append(f"Urgency: {self.state.urgency}")
        if self.state.is_emergency:
            context_parts.append(f"⚠️ EMERGENCY: {self.state.emergency_type}")

        if context_parts:
            return "\n\n## Current Context\n" + "\n".join(context_parts)
        return ""

    async def close(self):
        """Clean up resources"""
        await self.http_client.aclose()

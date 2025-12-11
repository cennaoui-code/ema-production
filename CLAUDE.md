# EMA Production - Agent Instructions

> **STOP! READ THIS ENTIRE FILE BEFORE DOING ANY WORK**

---

## 🚨 CRITICAL: REPOSITORY IDENTIFICATION

### You are in: `ema-production`

| Question | Answer |
|----------|--------|
| Is this the live system? | **NO** |
| Does this serve customers? | **NO** |
| Can I break production? | **NO** - This is isolated |
| What is this for? | Building future voice infrastructure |

### The TWO EMA Repositories

```
┌────────────────────────────────────────────────────────────────┐
│                                                                 │
│   cennaoui-code/ema                                            │
│   ════════════════                                             │
│   • LIVE production system                                      │
│   • Voiceflow-based voice AI                                   │
│   • NestJS API + React dashboard                               │
│   • PostgreSQL database                                         │
│   • Currently serving design partners                          │
│   • DO NOT break this                                          │
│                                                                 │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│   cennaoui-code/ema-production  ← YOU ARE HERE                 │
│   ════════════════════════════                                 │
│   • Future production system                                    │
│   • LiveKit-based voice AI (self-hosted)                       │
│   • Python voice agent + Sim.ai workflow UI                    │
│   • Connects to ema repo via webhooks                          │
│   • Safe to experiment and break                               │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

---

## 🎯 PROJECT GOALS

### Why This Exists

1. **Scale beyond Voiceflow's 15 concurrent call limit**
2. **Reduce latency from 6+ seconds to <2 seconds**
3. **Own our voice AI infrastructure**
4. **White-label workflow builder for property managers**

### Architecture

```
PHONE CALL
    │
    ▼
┌─────────────────────────┐
│  LiveKit Cloud (SIP)    │  ← Handles telephony
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│  EMA Voice Agent        │  ← This repo: apps/voice-agent/
│  (Python + LiveKit SDK) │
│                         │
│  • Deepgram STT         │
│  • GPT-4 / Claude LLM   │
│  • OpenAI TTS           │
└───────────┬─────────────┘
            │
            │ Async webhooks (fire-and-forget)
            ▼
┌─────────────────────────┐
│  EMA API                │  ← Other repo: cennaoui-code/ema
│  (NestJS)               │
│                         │
│  POST /webhooks/livekit/│
│    - call-initiated     │
│    - utterance          │
│    - call-ended         │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│  PostgreSQL Database    │  ← Stores Run + RunEvent
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│  EMA Dashboard (React)  │  ← Other repo: cennaoui-code/ema
│  Real-time via SSE      │
└─────────────────────────┘
```

---

## 📁 CODEBASE STRUCTURE

```
ema-production/
│
├── CLAUDE.md                    # THIS FILE - Read first!
├── README.md                    # Project overview
│
├── .claude/                     # Agent system (if needed)
│
├── docs/
│   ├── ARCHITECTURE.md          # Detailed system design
│   ├── MIGRATION-PLAN.md        # How we migrate from Voiceflow
│   └── INTEGRATION.md           # API webhook specifications
│
├── apps/
│   │
│   ├── voice-agent/             # MAIN FOCUS: LiveKit voice AI
│   │   ├── src/
│   │   │   ├── agent.py         # Main agent entry point
│   │   │   ├── prompts.py       # Prompt loading/management
│   │   │   ├── webhooks.py      # Async webhook sender
│   │   │   └── config.py        # Configuration
│   │   │
│   │   ├── prompts/             # Agent prompts (from Voiceflow)
│   │   │   ├── welcome.md
│   │   │   ├── emergency-triage.md
│   │   │   ├── dispatch.md
│   │   │   └── ...
│   │   │
│   │   ├── requirements.txt     # Python dependencies
│   │   ├── .env.example         # Environment template
│   │   └── Dockerfile           # Container build
│   │
│   └── workflow-ui/             # FUTURE: Sim.ai fork
│       └── (to be added)
│
├── tools/
│   └── vf-parser/               # Voiceflow .vf export parser
│       └── parse-voiceflow.js   # Extracts prompts from VF export
│
└── infrastructure/
    ├── render.yaml              # Render Blueprint
    └── docker-compose.yml       # Local dev environment
```

---

## 🔧 WORKING ON THIS CODEBASE

### Current Priority: Voice Agent

The main focus is `apps/voice-agent/`. This is a Python application using:

- **LiveKit Agents SDK** - Voice pipeline framework
- **Deepgram** - Speech-to-text
- **OpenAI GPT-4** - Language model
- **OpenAI TTS** - Text-to-speech

### Key Files to Understand

1. `apps/voice-agent/src/agent.py` - Main entry point
2. `apps/voice-agent/prompts/` - Agent prompts from Voiceflow
3. `tools/vf-parser/` - Tool to extract prompts from Voiceflow exports

### Development Workflow

```bash
# 1. Setup
cd apps/voice-agent
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Add your API keys

# 3. Run locally
python src/agent.py dev

# 4. Test with LiveKit CLI
lk room create test-room
lk join test-room --identity user
```

---

## 🔗 INTEGRATION WITH EMA (MAIN REPO)

### Webhook Endpoints

The voice agent sends events to the EMA API. These endpoints need to be created in `cennaoui-code/ema`:

```
POST /webhooks/livekit/call-initiated
{
  "session_id": "room-123",
  "call_sid": "CA...",
  "timestamp": "2024-01-01T00:00:00Z",
  "metadata": { ... }
}

POST /webhooks/livekit/utterance
{
  "session_id": "room-123",
  "speaker": "tenant" | "agent",
  "text": "My pipe is leaking",
  "turn_index": 0,
  "timestamp": "2024-01-01T00:00:00Z"
}

POST /webhooks/livekit/call-ended
{
  "session_id": "room-123",
  "duration_seconds": 120,
  "total_turns": 15,
  "timestamp": "2024-01-01T00:00:00Z"
}
```

### Fire-and-Forget Pattern

**CRITICAL**: Webhooks must be async/fire-and-forget to avoid adding latency:

```python
# GOOD - Fire and forget
asyncio.create_task(send_webhook(...))

# BAD - Blocks the conversation
await send_webhook(...)
```

---

## ⚠️ RULES FOR AGENTS

### DO:
- ✅ Work freely in this repo - it's safe to experiment
- ✅ Create new files and structures as needed
- ✅ Test locally before pushing
- ✅ Document everything clearly
- ✅ Keep prompts in markdown files for easy editing

### DON'T:
- ❌ Confuse this with `cennaoui-code/ema`
- ❌ Make changes to the EMA repo from here
- ❌ Add synchronous/blocking webhook calls
- ❌ Hardcode API keys (use .env)
- ❌ Skip documentation

---

## 📊 CURRENT STATUS

### Completed
- [x] Repository structure created
- [x] Documentation written
- [x] Voiceflow parser tool created

### In Progress
- [ ] Voice agent base code
- [ ] Prompt loading from parsed Voiceflow
- [ ] Webhook integration

### Pending
- [ ] LiveKit Cloud setup
- [ ] Render deployment
- [ ] SIP/telephony configuration
- [ ] Sim.ai fork and white-labeling

---

## 🆘 GETTING HELP

- **LiveKit Docs**: https://docs.livekit.io/agents/
- **Deepgram Docs**: https://developers.deepgram.com/
- **EMA API**: See `cennaoui-code/ema` repo

---

## 📝 CHANGELOG

| Date | Change |
|------|--------|
| 2024-12-11 | Initial repository structure created |

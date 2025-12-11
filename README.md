# EMA Production

> **PRODUCTION VOICE AI INFRASTRUCTURE** for Emergency Maintenance AI

---

## ⚠️ IMPORTANT: THIS IS NOT THE CURRENT EMA SYSTEM

| Repository | Purpose | Status |
|------------|---------|--------|
| `cennaoui-code/ema` | Current system (Voiceflow-based) | **ACTIVE** - Serving design partners |
| `cennaoui-code/ema-production` | **THIS REPO** - Future production system (LiveKit-based) | **IN DEVELOPMENT** |

**DO NOT** confuse these repositories:
- **ema** = Web dashboard + API + Voiceflow integration (LIVE)
- **ema-production** = Self-hosted voice AI infrastructure (BUILDING)

---

## What is EMA Production?

EMA Production is the **self-hosted voice AI infrastructure** that will replace Voiceflow when we need to scale beyond 15 concurrent calls.

### Why We're Building This

| Problem with Voiceflow | Solution in EMA Production |
|------------------------|---------------------------|
| 15 concurrent call limit | **Unlimited** (self-hosted LiveKit) |
| 6+ second latency | **<2 second latency** (async webhooks) |
| No code access | **Full control** over agent logic |
| Vendor lock-in | **Open source** stack |

### Tech Stack

```
┌─────────────────────────────────────────────────────────┐
│                    EMA PRODUCTION                        │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────────────┐      ┌──────────────────┐        │
│  │   VOICE AGENT    │      │   WORKFLOW UI    │        │
│  │   (LiveKit)      │      │   (Sim.ai fork)  │        │
│  │                  │      │                  │        │
│  │  • Python        │      │  • React/Next.js │        │
│  │  • STT: Deepgram │      │  • White-labeled │        │
│  │  • LLM: GPT-4    │      │  • For PMs       │        │
│  │  • TTS: OpenAI   │      │                  │        │
│  └────────┬─────────┘      └──────────────────┘        │
│           │                                              │
│           │ Webhooks (async, fire-and-forget)           │
│           ▼                                              │
│  ┌──────────────────────────────────────────┐          │
│  │         EMA API (existing repo)           │          │
│  │         cennaoui-code/ema                 │          │
│  └──────────────────────────────────────────┘          │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

---

## Repository Structure

```
ema-production/
├── README.md                 # You are here
├── CLAUDE.md                 # Agent instructions (CRITICAL)
├── docs/
│   ├── ARCHITECTURE.md       # System design
│   ├── MIGRATION-PLAN.md     # Voiceflow → LiveKit migration
│   └── INTEGRATION.md        # How this connects to ema repo
│
├── apps/
│   ├── voice-agent/          # LiveKit-based voice AI
│   │   ├── src/              # Python agent code
│   │   ├── prompts/          # Agent prompts (from Voiceflow)
│   │   └── requirements.txt
│   │
│   └── workflow-ui/          # Sim.ai fork (future)
│       └── src/              # React/Next.js
│
├── tools/
│   └── vf-parser/            # Voiceflow export parser
│
└── infrastructure/
    ├── render.yaml           # Render deployment config
    └── docker-compose.yml    # Local development
```

---

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 20+
- LiveKit Cloud account (free tier)
- OpenAI API key
- Deepgram API key

### Setup

```bash
# Clone this repo
git clone https://github.com/cennaoui-code/ema-production.git
cd ema-production

# Setup voice agent
cd apps/voice-agent
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API keys

# Run locally
python src/agent.py dev
```

---

## Integration with EMA (Current System)

This repo **does not replace** the current EMA system. It **extends** it:

```
Phone Call → LiveKit (this repo) → Webhooks → EMA API (ema repo) → Database → Dashboard
```

The voice agent sends events to the existing EMA API:
- `POST /webhooks/livekit/call-initiated`
- `POST /webhooks/livekit/utterance`
- `POST /webhooks/livekit/call-ended`

---

## Development Status

- [ ] Voice Agent (LiveKit)
  - [ ] Basic call handling
  - [ ] STT/TTS pipeline
  - [ ] Agent prompts loaded
  - [ ] Webhook integration
  - [ ] Multi-tenant support

- [ ] Workflow UI (Sim.ai)
  - [ ] Fork and setup
  - [ ] White-label branding
  - [ ] Connect to voice agent

- [ ] Infrastructure
  - [ ] Render deployment
  - [ ] SIP/telephony setup
  - [ ] Production monitoring

---

## For AI Agents (Claude, etc.)

**READ `.claude/CLAUDE.md` FIRST** - It contains all instructions for working on this codebase.

Key points:
1. This is **NOT** the live production system
2. The live system is in `cennaoui-code/ema`
3. This repo is for building the **future** infrastructure
4. Integration happens via webhooks to the EMA API

---

## License

Proprietary - EMA Inc.

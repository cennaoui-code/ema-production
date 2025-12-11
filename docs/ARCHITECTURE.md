# EMA Production Architecture

## System Overview

EMA Production is a self-hosted voice AI infrastructure that will replace Voiceflow for handling emergency maintenance calls at scale.

## Component Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              PHONE NETWORK                                   │
│                                                                              │
│  Tenant calls → PSTN → SIP Trunk → LiveKit Cloud                           │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  │ WebRTC/SIP
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           LIVEKIT CLOUD                                      │
│                                                                              │
│  • SIP Gateway (converts phone calls to WebRTC)                             │
│  • Media servers (handles audio streams)                                     │
│  • Room management (session isolation)                                       │
│  • Free tier: 5000 participant-minutes/month                                │
│                                                                              │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  │ LiveKit SDK
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     EMA VOICE AGENT (This Repo)                              │
│                     apps/voice-agent/                                        │
│                                                                              │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                     │
│  │   DEEPGRAM  │    │   GPT-4o    │    │  OPENAI TTS │                     │
│  │     STT     │───▶│    LLM      │───▶│             │                     │
│  │             │    │             │    │             │                     │
│  │  Audio→Text │    │ Text→Text   │    │ Text→Audio  │                     │
│  └─────────────┘    └─────────────┘    └─────────────┘                     │
│         │                  │                  │                              │
│         │                  │                  │                              │
│         ▼                  ▼                  ▼                              │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │                    VOICE PIPELINE                             │          │
│  │                                                               │          │
│  │  • VAD (Voice Activity Detection) - Silero                   │          │
│  │  • Turn management                                            │          │
│  │  • Interruption handling                                      │          │
│  │  • Prompt management (loaded from prompts/)                  │          │
│  │  • Session state                                              │          │
│  └──────────────────────────────────────────────────────────────┘          │
│                                  │                                           │
│                                  │ Async webhooks (fire-and-forget)         │
│                                  ▼                                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  │ HTTP POST
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        EMA API (Other Repo)                                  │
│                        cennaoui-code/ema                                     │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────┐       │
│  │  /webhooks/livekit/*                                            │       │
│  │                                                                  │       │
│  │  • call-initiated  → Creates Run record                         │       │
│  │  • utterance       → Creates RunEvent record                    │       │
│  │  • call-ended      → Updates Run status                         │       │
│  └─────────────────────────────────────────────────────────────────┘       │
│                                  │                                           │
│                                  ▼                                           │
│  ┌─────────────────────────────────────────────────────────────────┐       │
│  │  PostgreSQL Database                                            │       │
│  │                                                                  │       │
│  │  Run { id, callSid, status, workspaceId, ... }                 │       │
│  │  RunEvent { id, runId, eventType, text, speaker, ... }         │       │
│  └─────────────────────────────────────────────────────────────────┘       │
│                                  │                                           │
│                                  │ SSE (Server-Sent Events)                 │
│                                  ▼                                           │
│  ┌─────────────────────────────────────────────────────────────────┐       │
│  │  EMA Dashboard (React)                                          │       │
│  │                                                                  │       │
│  │  Real-time timeline updates                                     │       │
│  └─────────────────────────────────────────────────────────────────┘       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Voice Pipeline Detail

```
┌─────────────────────────────────────────────────────────────────┐
│                     VOICE PIPELINE                               │
│                                                                  │
│   Audio In                                                       │
│      │                                                           │
│      ▼                                                           │
│   ┌─────────────────┐                                           │
│   │      VAD        │  Voice Activity Detection                 │
│   │    (Silero)     │  Detects speech start/end                 │
│   └────────┬────────┘                                           │
│            │                                                     │
│            ▼                                                     │
│   ┌─────────────────┐                                           │
│   │      STT        │  Speech-to-Text                           │
│   │   (Deepgram)    │  Streaming transcription                  │
│   │                 │  - Model: nova-2                          │
│   │                 │  - Smart formatting                       │
│   │                 │  - Punctuation                            │
│   └────────┬────────┘                                           │
│            │                                                     │
│            │  "My pipe is leaking"                              │
│            ▼                                                     │
│   ┌─────────────────┐                                           │
│   │      LLM        │  Language Model                           │
│   │    (GPT-4o)     │  - System prompt from prompts/            │
│   │                 │  - Conversation history                   │
│   │                 │  - Function calling (tools)               │
│   └────────┬────────┘                                           │
│            │                                                     │
│            │  "I understand you have a leak..."                 │
│            ▼                                                     │
│   ┌─────────────────┐                                           │
│   │      TTS        │  Text-to-Speech                           │
│   │  (OpenAI TTS)   │  - Voice: nova                            │
│   │                 │  - Streaming output                       │
│   └────────┬────────┘                                           │
│            │                                                     │
│            ▼                                                     │
│       Audio Out                                                  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Latency Comparison

### Current (Voiceflow)
```
User speaks → STT (500ms) → VF Processing (500ms) →
API Call 1 (1000ms) → API Call 2 (1000ms) → API Call 3 (1000ms) →
LLM (500ms) → TTS (500ms) → User hears

TOTAL: ~5500ms (6 seconds)
```

### New (EMA Production)
```
User speaks → STT (500ms) → LLM (500ms) → TTS (500ms) → User hears
                              │
                              └─── Async webhook (0ms added)
                                   (fire-and-forget)

TOTAL: ~1500ms (1.5 seconds)
```

**Key insight**: The 6-second latency was caused by **synchronous API calls** in Voiceflow. By making webhooks async (fire-and-forget), we eliminate this overhead.

## Multi-Tenant Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    WORKSPACE ISOLATION                           │
│                                                                  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │  Workspace A    │  │  Workspace B    │  │  Workspace C    │ │
│  │  (PM Company 1) │  │  (PM Company 2) │  │  (PM Company 3) │ │
│  │                 │  │                 │  │                 │ │
│  │  Phone: +1...   │  │  Phone: +1...   │  │  Phone: +1...   │ │
│  │  Properties: 50 │  │  Properties: 200│  │  Properties: 30 │ │
│  │  Vendors: 10    │  │  Vendors: 25    │  │  Vendors: 8     │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘ │
│           │                    │                    │           │
│           └────────────────────┴────────────────────┘           │
│                                │                                 │
│                                ▼                                 │
│                    ┌───────────────────┐                        │
│                    │   PHONE ROUTER    │                        │
│                    │                   │                        │
│                    │  Incoming call    │                        │
│                    │  → Lookup phone # │                        │
│                    │  → Get workspace  │                        │
│                    │  → Load prompts   │                        │
│                    │  → Start session  │                        │
│                    └───────────────────┘                        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Deployment Architecture (Render)

```
┌─────────────────────────────────────────────────────────────────┐
│                         RENDER                                   │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  ema-voice-agent (Background Worker)                     │   │
│  │                                                          │   │
│  │  • Docker container                                      │   │
│  │  • Always-on (not serverless)                           │   │
│  │  • Connects to LiveKit Cloud                            │   │
│  │  • Environment: LIVEKIT_URL, API keys                   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              │ Internal network                  │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  ema-api (Web Service) - from cennaoui-code/ema         │   │
│  │                                                          │   │
│  │  • NestJS                                                │   │
│  │  • Receives webhooks from voice agent                   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  PostgreSQL                                              │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                      LIVEKIT CLOUD                               │
│                                                                  │
│  • SIP Gateway (phone number provisioning)                      │
│  • Media servers                                                 │
│  • Free tier: 5000 participant-minutes                          │
│  • Scales automatically                                          │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Cost Analysis

### Per-Call Costs (estimated)

| Component | Cost | Notes |
|-----------|------|-------|
| LiveKit | $0.002/min | First 5000 min free |
| Deepgram | $0.0043/min | Nova-2 model |
| OpenAI GPT-4o-mini | ~$0.01/call | ~500 tokens/call |
| OpenAI TTS | $0.015/1K chars | ~200 chars/response |
| **Total** | **~$0.03/call** | 2-minute average call |

### Monthly Costs by Scale

| Calls/Month | LiveKit | Deepgram | OpenAI | Total |
|-------------|---------|----------|--------|-------|
| 100 | $0 (free) | $0.86 | $2.50 | ~$3 |
| 1,000 | $4 | $8.60 | $25 | ~$38 |
| 10,000 | $40 | $86 | $250 | ~$376 |

**Note**: These are pay-per-use costs. No monthly minimums.

## Security Considerations

1. **API Key Management**
   - All keys in environment variables
   - Never commit to git
   - Rotate regularly

2. **Webhook Authentication**
   - X-Webhook-Secret header
   - Verify on EMA API side

3. **Call Recording**
   - Opt-in only
   - Encrypted storage
   - Retention policies

4. **PII Handling**
   - Minimal logging of user speech
   - No storage of full transcripts by default
   - GDPR/CCPA compliance

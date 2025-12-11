# EMA Production ↔ EMA API Integration

This document describes how EMA Production (voice agent) integrates with the existing EMA API.

## Overview

```
EMA Production (this repo)          EMA (existing repo)
─────────────────────────          ─────────────────────

┌──────────────────────┐           ┌──────────────────────┐
│   Voice Agent        │           │      EMA API         │
│   (LiveKit)          │──────────▶│      (NestJS)        │
│                      │  webhooks │                      │
└──────────────────────┘           └──────────────────────┘
                                            │
                                            ▼
                                   ┌──────────────────────┐
                                   │     PostgreSQL       │
                                   │  (Run, RunEvent)     │
                                   └──────────────────────┘
```

## Webhook Endpoints

The voice agent sends events to the EMA API. These endpoints need to be created in `cennaoui-code/ema`.

### 1. Call Initiated

**Endpoint:** `POST /webhooks/livekit/call-initiated`

**When:** New call starts

**Payload:**
```json
{
  "event_type": "call_initiated",
  "session_id": "livekit-room-abc123",
  "call_sid": "optional-sip-call-id",
  "timestamp": "2024-12-11T10:30:00.000Z",
  "data": {
    "metadata": {},
    "started_at": "2024-12-11T10:30:00.000Z"
  }
}
```

**EMA API Action:**
- Create new `Run` record
- Set `voiceflowSessionId` = `session_id` (for backward compatibility)
- Set `status` = "running"

### 2. Utterance

**Endpoint:** `POST /webhooks/livekit/utterance`

**When:** User speaks OR agent responds

**Payload:**
```json
{
  "event_type": "utterance",
  "session_id": "livekit-room-abc123",
  "call_sid": "optional-sip-call-id",
  "timestamp": "2024-12-11T10:30:15.000Z",
  "data": {
    "speaker": "tenant",
    "text": "My pipe is leaking in the kitchen",
    "turn_index": 0,
    "stage": "welcome"
  }
}
```

**Speaker values:**
- `"tenant"` - Caller/resident
- `"agent"` - AI agent

**EMA API Action:**
- Find `Run` by `session_id` or `call_sid`
- Create `RunEvent` with:
  - `eventType`: `TENANT_UTTERANCE` or `AGENT_UTTERANCE`
  - `text`: The utterance
  - `speaker`: tenant/agent
  - `workspaceId`: From run

### 3. Call Ended

**Endpoint:** `POST /webhooks/livekit/call-ended`

**When:** Call terminates

**Payload:**
```json
{
  "event_type": "call_ended",
  "session_id": "livekit-room-abc123",
  "call_sid": "optional-sip-call-id",
  "timestamp": "2024-12-11T10:35:00.000Z",
  "data": {
    "duration_seconds": 300,
    "total_turns": 12,
    "final_stage": "dispatch"
  }
}
```

**EMA API Action:**
- Find `Run` by `session_id`
- Update `status` = "completed"
- Store duration in metadata

---

## Authentication

All webhooks include a secret header:

```
X-Webhook-Secret: <EMA_WEBHOOK_SECRET>
```

The EMA API should:
1. Check this header exists
2. Verify it matches the configured secret
3. Reject requests with invalid/missing secret

---

## Implementation in EMA API

### New Controller: `apps/api/src/webhooks/livekit-webhook.controller.ts`

```typescript
import { Controller, Post, Body, Headers, UnauthorizedException, Logger } from '@nestjs/common';
import { PrismaService } from '../prisma.service';
import { RunsEventsService } from '../runs/runs-events.service';

@Controller('webhooks/livekit')
export class LivekitWebhookController {
  private readonly logger = new Logger(LivekitWebhookController.name);

  constructor(
    private readonly prisma: PrismaService,
    private readonly runsEventsService: RunsEventsService,
  ) {}

  private validateSecret(secret: string) {
    const expected = process.env.LIVEKIT_WEBHOOK_SECRET;
    if (!expected || secret !== expected) {
      throw new UnauthorizedException('Invalid webhook secret');
    }
  }

  @Post('call-initiated')
  async handleCallInitiated(
    @Body() body: any,
    @Headers('x-webhook-secret') secret: string,
  ) {
    this.validateSecret(secret);
    this.logger.log('LiveKit call initiated', { session: body.session_id });

    // Create Run record
    const run = await this.prisma.run.create({
      data: {
        voiceflowSessionId: body.session_id,
        callSid: body.call_sid,
        status: 'running',
        source: 'livekit',
        // workspaceId: determine from phone number lookup
      }
    });

    return { success: true, runId: run.id };
  }

  @Post('utterance')
  async handleUtterance(
    @Body() body: any,
    @Headers('x-webhook-secret') secret: string,
  ) {
    this.validateSecret(secret);

    const { session_id, data } = body;
    const { speaker, text, turn_index } = data;

    // Find run
    const run = await this.prisma.run.findFirst({
      where: {
        OR: [
          { voiceflowSessionId: session_id },
          { callSid: body.call_sid }
        ]
      }
    });

    if (!run) {
      this.logger.warn('No run found for utterance', { session_id });
      return { success: false, error: 'Run not found' };
    }

    // Create event
    const eventType = speaker === 'tenant' ? 'TENANT_UTTERANCE' : 'AGENT_UTTERANCE';

    const event = await this.prisma.runEvent.create({
      data: {
        runId: run.id,
        eventType,
        text,
        speaker,
        workspaceId: run.workspaceId,
        metadata: { turn_index, source: 'livekit' }
      }
    });

    // Emit for real-time updates
    this.runsEventsService.emitRunEventCreated(event);

    return { success: true, eventId: event.id };
  }

  @Post('call-ended')
  async handleCallEnded(
    @Body() body: any,
    @Headers('x-webhook-secret') secret: string,
  ) {
    this.validateSecret(secret);

    const { session_id, data } = body;

    const run = await this.prisma.run.findFirst({
      where: { voiceflowSessionId: session_id }
    });

    if (run) {
      await this.prisma.run.update({
        where: { id: run.id },
        data: {
          status: 'completed',
          metadata: {
            ...run.metadata,
            duration_seconds: data.duration_seconds,
            total_turns: data.total_turns,
          }
        }
      });
    }

    return { success: true };
  }
}
```

### Register in WebhooksModule

```typescript
// apps/api/src/webhooks/webhooks.module.ts

import { LivekitWebhookController } from './livekit-webhook.controller';

@Module({
  controllers: [
    // ... existing controllers
    LivekitWebhookController,
  ],
})
export class WebhooksModule {}
```

---

## Testing Integration

### 1. Test webhook endpoint

```bash
curl -X POST https://api.samantha.cx/webhooks/livekit/call-initiated \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: your-secret" \
  -d '{
    "event_type": "call_initiated",
    "session_id": "test-123",
    "timestamp": "2024-12-11T10:00:00Z",
    "data": {}
  }'
```

### 2. Verify in database

```sql
SELECT * FROM "Run" WHERE "voiceflowSessionId" = 'test-123';
```

### 3. Check dashboard

The new run should appear in the EMA dashboard with real-time updates.

---

## Environment Variables

### EMA Production (voice agent)

```env
EMA_API_URL=https://api.samantha.cx
EMA_WEBHOOK_SECRET=your-shared-secret
```

### EMA API

```env
LIVEKIT_WEBHOOK_SECRET=your-shared-secret
```

Both must use the same secret value.

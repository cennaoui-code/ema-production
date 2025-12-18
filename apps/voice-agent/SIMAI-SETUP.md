# Sim.ai Cloud Setup Guide

This guide explains how to configure Sim.ai Cloud for the EMA Voice Agent workflow orchestration.

## Overview

The EMA Voice Agent uses Sim.ai to handle:
- Conversation routing (which prompt/agent to use)
- Emergency detection and escalation
- Issue classification
- Tool invocation decisions (create_ticket, find_vendor, escalate)

## Step 1: Create Sim.ai Account

1. Go to https://sim.ai
2. Sign up for an account
3. Create a new workspace for EMA

## Step 2: Generate API Key

1. Click on your profile (top right)
2. Go to **Settings** > **API Keys**
3. Click **Create API Key**
4. Copy the key (starts with `sim_...`)

## Step 3: Import/Create the EMA Triage Workflow

### Option A: Build from Scratch in Sim Studio

1. Go to **Workflows** > **New Workflow**
2. Name it "EMA Triage Workflow"
3. Add these nodes:
   - **API Trigger** - receives voice agent requests
   - **Agent: Emergency Detector** - checks for emergencies
   - **Agent: Issue Classifier** - classifies issue type
   - **Agent: Urgency Assessor** - determines urgency
   - **Function: Router** - routes to next stage

4. Connect the nodes as shown in `workflows/ema-triage-workflow.json`

### Option B: Use the Workflow Spec

The file `src/workflows/ema-triage-workflow.json` contains the full workflow specification with:
- Node configurations
- Agent prompts
- Routing logic

Use this as a reference when building in Sim Studio.

## Step 4: Deploy the Workflow

1. Click **Deploy** in Sim Studio
2. Copy the **Workflow ID** from the URL (e.g., `wf_abc123xyz`)

## Step 5: Configure Voice Agent

Add these environment variables to your Render service:

```bash
SIMAI_API_KEY=sim_your_api_key_here
SIMAI_WORKFLOW_ID=wf_your_workflow_id_here
```

Or in `.env`:

```env
SIMAI_API_KEY=sim_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SIMAI_WORKFLOW_ID=wf_xxxxxxxxxxxxxxxxxxxx
```

## Step 6: Test the Integration

The voice agent will automatically use Sim.ai when these env vars are set.

Test flow:
1. Call the voice agent
2. Say "I have a gas leak in my apartment"
3. Verify Sim.ai routes to emergency escalation

## Workflow Nodes

### 1. Emergency Detector
- Model: gpt-4o-mini
- Detects: fire, gas, flood, no heat, break-in, etc.
- Output: `{ is_emergency, emergency_type, confidence }`

### 2. Issue Classifier
- Model: gpt-4o-mini
- Categories: plumbing, electrical, hvac, appliance, locksmith, pest, structural
- Output: `{ issue_type, issue_subtype, needs_clarification }`

### 3. Urgency Assessor
- Model: gpt-4o-mini
- Levels: emergency, urgent, routine
- Output: `{ urgency, affects_habitability, time_sensitive }`

### 4. Router (Function)
- JavaScript function
- Routes based on emergency status, issue type, and collected info
- Output: `{ next_stage, prompt, tools, state_updates }`

## API Request Format

```json
POST https://sim.ai/api/workflows/{workflowId}/execute
Headers:
  Content-Type: application/json
  X-API-Key: sim_xxxxx

Body:
{
  "user_text": "I have water leaking from my ceiling",
  "state": {
    "session_id": "call_123",
    "stage": "triage",
    "issue_type": null,
    "urgency": null,
    "is_emergency": false
  },
  "conversation_history": [
    {"role": "agent", "text": "How can I help you today?"},
    {"role": "user", "text": "I have water leaking from my ceiling"}
  ]
}
```

## API Response Format

```json
{
  "next_stage": "issue_details",
  "prompt": "damage-severity-input-agent",
  "tools": [],
  "state_updates": {
    "issue_type": "plumbing"
  },
  "escalate": false
}
```

## Fallback Behavior

If Sim.ai is not configured (no API key), the voice agent uses built-in fallback routing:
- Keyword-based emergency detection
- Simple issue classification
- Basic routing logic

This ensures the agent works even without Sim.ai, but with reduced intelligence.

## Troubleshooting

### API Key Invalid
- Check the key in Settings > API Keys
- Ensure no extra whitespace

### Workflow Not Found
- Verify the workflow is deployed
- Check the workflow ID matches

### Timeout Errors
- Sim.ai has a 5-second timeout
- Check your workflow complexity

### Rate Limits
- Default: 100 requests/minute
- Contact support for higher limits

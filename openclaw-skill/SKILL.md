---
name: aimp-meeting
description: "Schedule meetings by negotiating with other AI agents via email using the AIMP protocol. Supports Hub mode (one Agent serves a family/team) and standalone mode. Handles multi-party time/location coordination automatically."
emoji: "📅"
metadata:
  openclaw:
    requires:
      bins: ["python3"]
    primaryEnv: "ANTHROPIC_API_KEY"
    os: ["darwin", "linux"]
---

# AIMP Meeting Scheduler

You are a meeting coordination assistant powered by AIMP (AI Meeting Protocol). You help users schedule meetings via email negotiation — automatically or with minimal human input.

**Two deployment modes** (auto-detected from config):
- **Hub mode** (recommended): One Agent serves multiple people (family/team). Internal members get instant scheduling via "god view"; external contacts use standard email negotiation.
- **Standalone mode**: Classic 1-person-1-Agent setup (backward compatible).

## Installation

```bash
export OPENCLAW_ENV=true
python3 {baseDir}/scripts/install.py
```

## First-Time Setup

If `~/.aimp/config.yaml` does not exist, run the interactive wizard:

```bash
python3 {baseDir}/scripts/setup_config.py --interactive
```

The wizard will ask:
1. **Mode**: Hub (recommended for family/team) or Standalone
2. **Hub mode**: Hub name, Hub agent email + password, then each member's name/email/preferences
3. **Standalone mode**: Agent email, owner name/email, meeting preferences

Alternatively, collect info from the user in chat and run non-interactively (standalone only):

```bash
python3 {baseDir}/scripts/setup_config.py \
  --agent-email "<email>" \
  --imap-server "<server>" \
  --smtp-server "<server>" \
  --password "<password>" \
  --owner-name "<name>" \
  --owner-email "<email>" \
  --preferred-times "<time1>,<time2>" \
  --preferred-locations "<loc1>,<loc2>"
```

Output: `{"type": "config_created", "path": "...", "mode": "hub|standalone", ...}`

## Scheduling a Meeting

When the user says "schedule a meeting with Bob and Carol about Q1 review":

1. Extract **topic** and **participants** (names if in members/contacts, or raw email addresses).
2. Run:

```bash
python3 {baseDir}/scripts/initiate.py \
  --config ~/.aimp/config.yaml \
  --topic "<topic>" \
  --participants "<Name1>,<Name2>"
```

**Hub mode — specify who is asking** (when you know the initiator's member ID):
```bash
python3 {baseDir}/scripts/initiate.py \
  --config ~/.aimp/config.yaml \
  --topic "<topic>" \
  --participants "<Name1>,<Name2>" \
  --initiator "<member_id>"
```

**What happens depends on participants:**
- **All participants are Hub members** → Instant result. Hub reads everyone's preferences, finds optimal slot in one LLM call. Emits `consensus` or `escalation` immediately.
- **Has external contacts** → Hub sends AIMP/natural-language email and enters async negotiation. Poll for replies.

## Polling for Updates

Run every 60 seconds while there are active sessions with external contacts:

```bash
python3 {baseDir}/scripts/poll.py --config ~/.aimp/config.yaml
```

Handle each JSON event:

| Event | What to do |
|-------|------------|
| `consensus` | Tell the user: meeting confirmed, show time/location/participants. |
| `hub_member_notify` | Relay `message` field to the user in chat. |
| `escalation` | Agent needs human input. Show `reason` + `options`, ask user to decide. |
| `reply_sent` | Negotiation reply sent. Log silently. |
| `error` | Show error; suggest checking email/LLM config. |

## Handling Escalation

When `escalation` arrives, ask the user directly. When they respond:

```bash
python3 {baseDir}/scripts/respond.py \
  --config ~/.aimp/config.yaml \
  --session-id "<session_id>" \
  --response "<user's response text>"
```

## Checking Status

```bash
python3 {baseDir}/scripts/status.py --config ~/.aimp/config.yaml
python3 {baseDir}/scripts/status.py --config ~/.aimp/config.yaml --session-id "<id>"
```

## LLM Configuration

AIMP supports three LLM backends (configured in `config.yaml`):

| Provider | config.yaml snippet |
|----------|---------------------|
| Anthropic (default) | `provider: anthropic`, `api_key_env: ANTHROPIC_API_KEY` |
| OpenAI | `provider: openai`, `api_key_env: OPENAI_API_KEY` |
| Local Ollama | `provider: local`, `model: llama3`, `base_url: http://localhost:11434/v1` |

The local Ollama option is especially useful for Hub mode deployed on an always-on machine — zero API costs.

## Important Rules

- Always parse script output as JSON. Each line is a separate JSON object.
- Never expose raw JSON to the user. Translate events into natural language.
- When an escalation comes in, always ask the user immediately — don't delay.
- Hub internal meetings (all participants are Hub members) resolve **instantly** — no polling needed after `initiate.py`.
- Keep polling only when there are `negotiating` sessions with external contacts.
- Stop polling when all sessions are `confirmed` or `escalated`.
- If a script fails, show the error and suggest the user check their email/LLM configuration.

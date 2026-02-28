# AIMP — AI Meeting Protocol

![Status](https://img.shields.io/badge/Status-Alpha-orange)
![OpenClaw](https://img.shields.io/badge/OpenClaw-Compatible-blue)
![License](https://img.shields.io/badge/License-MIT-purple)

> AI Agents negotiate meeting times and content over email — no app installation required for the other party.

**Hub Mode** — One Hub email address serves your whole team. Internal scheduling is resolved in a single LLM call. External contacts still go through standard AIMP email negotiation.

**The Room** — Async content negotiation (documents, budgets, decisions) with a deadline. Anyone can participate by replying to email.

**Fallback compatibility** — If the other party has no Agent, Hub sends human-readable email and parses their free-text reply via LLM.

[中文文档](README_zh.md)

---

## Quick Start (OpenClaw)

### 1. Register Skill

```bash
git clone https://github.com/wanqianwin-jpg/aimp.git
cp -r aimp/openclaw-skill ~/.openclaw/skills/aimp-meeting
# Restart OpenClaw
```

### 2. Setup

Tell OpenClaw:
> "Help me set up AIMP"

The Agent will guide you through: creating a Hub email, installing dependencies, generating `~/.aimp/config.yaml`, and starting the Hub process.

### 3. Use

> "Schedule a meeting with Bob next Friday afternoon"

> "Start a negotiation room with Alice and Carol for the Q3 budget, deadline in 3 days. Initial proposal: R&D $60k, Marketing $25k, Ops $15k"

---

## Architecture

```
New user ──[AIMP-INVITE:code]──→ ┐
Member   ──natural language──→  ├─ HubAgent (1 email address) ──→ External contacts / Agents
                                 ↓
                     Notify all participants
```

**Phase 1 — Scheduling:**

| Stage | Actor | Subject pattern |
|-------|-------|-----------------|
| Self-registration | New user | `[AIMP-INVITE:code]` |
| Meeting request | Member | (any) |
| AIMP negotiation | Hub ↔ Externals | `[AIMP:session_id]` |

**Phase 2 — Room (content negotiation):**

| Stage | Actor | Subject pattern |
|-------|-------|-----------------|
| Create room | Member → Hub | (any) |
| CFP / Amendments | Hub ↔ Participants | `[AIMP:Room:room_id]` |
| Meeting minutes + veto | Hub ↔ Participants | `[AIMP:Room:room_id]` |

**Round Protocol** — Hub does not reply to each email immediately. It waits for the round to complete, then sends one aggregated summary.

| Round | Who must reply |
|-------|---------------|
| Round 1 | All non-initiators (initiator already spoke via initial proposal) |
| Round 2+ | All participants including initiator |

**Store-First** — Every incoming email is persisted to SQLite before LLM processing. A mid-round crash loses nothing.

---

## Configuration

```yaml
mode: hub
hub:
  name: "Family Hub"
  email: "hub@example.com"
  imap_server: "imap.gmail.com"
  smtp_server: "smtp.gmail.com"
  password: "$HUB_PASSWORD"

members:
  alice:
    name: "Alice"
    email: "alice@example.com"
    role: "admin"           # admin | member
  bob:
    name: "Bob"
    email: "bob@example.com"
    role: "member"

contacts:                   # External (no Hub required)
  Dave:
    human_email: "dave@example.com"
    has_agent: false

invite_codes:
  - code: "welcome-2026"
    expires: "2026-12-31"
    max_uses: 3
    used: 0                 # auto-updated

trusted_users: {}           # auto-populated via invite flow

llm:
  provider: "anthropic"
  model: "claude-sonnet-4-6"
  api_key_env: "ANTHROPIC_API_KEY"
  # or: provider: local, base_url: http://localhost:11434/v1, model: llama3
```

---

## Running Manually

```bash
# Install dependencies
pip install -r requirements.txt

# Config wizard
python3 openclaw-skill/scripts/setup_config.py --interactive

# Run Hub
python3 hub_agent.py ~/.aimp/config.yaml

# Phase 2 in-memory demo (no real email or LLM needed)
python3 run_room_demo.py

# Tests
python -m pytest tests/ -v   # 87 tests
```

---

## Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1 | ✅ Complete | Email negotiation, human fallback, OpenClaw Skill |
| Phase 2 | ✅ Complete | Hub Mode + The Room (async content negotiation) |
| Phase 3 | ✅ Complete | Transport abstraction (`BaseTransport`) |
| Phase 4 | ✅ Complete | Store-First + Round Protocol (reliable processing) |
| Phase 5 | 🗓 Planned | Multi-transport: Telegram / Slack |

---

## License

MIT

# AIMP/0.1 Protocol Specification

## Overview

AIMP (AI Meeting Protocol) enables AI agents to negotiate meeting schedules via email. Each agent represents a human participant and autonomously proposes, counter-proposes, accepts, or escalates meeting options.

## Email Format

- **Subject**: `[AIMP:<session_id>] v<version> <topic>`
- **Body**: Human-readable summary (plain text)
- **Attachment**: `protocol.json` — structured protocol data
- **Headers**: `References` and `In-Reply-To` for threading

## protocol.json

```json
{
  "protocol": "AIMP/0.1",
  "session_id": "meeting-001",
  "version": 3,
  "from": "alice-agent@example.com",
  "topic": "Q1 Review",
  "participants": ["alice-agent@example.com", "bob-agent@example.com"],
  "proposals": {
    "time": {
      "options": ["2026-03-01T10:00", "2026-03-02T14:00"],
      "votes": {
        "alice-agent@example.com": "2026-03-01T10:00",
        "bob-agent@example.com": null
      }
    },
    "location": {
      "options": ["Zoom", "Office 3F"],
      "votes": { ... }
    }
  },
  "status": "negotiating",
  "history": [
    {"version": 1, "from": "alice-agent@example.com", "action": "propose", "summary": "..."}
  ]
}
```

## Action Types

| Action    | Meaning                        |
|-----------|--------------------------------|
| `propose` | Initiate a meeting proposal    |
| `accept`  | Accept all current proposals   |
| `counter` | Reject some, propose alternatives |
| `confirm` | All items resolved unanimously |
| `escalate`| Hand off to human              |

## Consensus Rules

- Each item (time, location) is independently voted
- An item is resolved when ALL participants vote for the SAME option
- All items resolved → send `confirm`
- After 5 rounds without resolution → `escalate`

## Degradation

If a contact has no agent (`has_agent: false`), the system sends a natural language email. Human replies are parsed by LLM to extract votes.

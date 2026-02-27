# AIMP — Implementation Guide

> Goal: AI Agents negotiate meeting schedules via email. Supports Hub mode (one Agent serves many) and Standalone mode (one Agent per person).
> Constraints: No hash chains, no DID, no permission budget, no signatures, no payments. Only the "runnable" minimum closed loop.

-----

## Current Status

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1 | ✅ Complete | Email-based meeting time/location negotiation |
| Phase 2 | ✅ Implemented | "The Room" — async content negotiation with deadline |

Phase 1 is fully implemented in `lib/` + `agent.py` + `hub_agent.py`. All modules are runnable.

Phase 2 is implemented in the same Hub (`hub_agent.py`) via delegation to `RoomNegotiator`. No separate agent required. Run `python run_room_demo.py` to see the full flow.

-----

## I. Architecture

### Standalone Mode

```
Alice (Human) ──Preferences──→ Agent-A ──Email──→ ┐
Bob   (Human) ──Preferences──→ Agent-B ──Email──→ ├─ Shared Email Thread
Carol (Human) ──Preferences──→ Agent-C ──Email──→ ┘
                   ↑                           │
                   └── Result Notification (Email/Terminal) ←──┘
```

### Hub Mode (recommended) — "Hub Skill" paradigm

```
New user ──[AIMP-INVITE:code]──→ ┐
Member   ──"schedule meeting"──→ ├─ HubAgent (1 email address) ──→ External contacts / Agents
                                 │
                         (internal: direct LLM scheduling)
                                 ↓
                     Notifies all participants
```

Hub is a **single deployable skill** — users only interact via email. No agent required on the user's side.

**Full email lifecycle:**

| Stage | Actor | Action | Email subject pattern |
|-------|-------|--------|----------------------|
| 0. Registration | Admin | Create invite codes in config.yaml | — |
| 1. Self-registration | New user | Email Hub with invite code | `[AIMP-INVITE:code]` |
| 1. Reply | Hub | Validates code, registers user, welcome email + hub-card JSON | — |
| 2. Meeting request | Member | Natural-language meeting request | (any) |
| 2. If incomplete | Hub | Reply asking for missing info (topic / participants / availability) | — |
| 3. Invitations sent | Hub | LLM-parsed → auto-dispatch `initiate_meeting()` | `[AIMP:session_id]` |
| 3. Initiator vote | Hub | Sends initiator a vote invitation (they are also a voter) | `[AIMP:session_id]` |
| 4. Voting | All | Reply with time/location preferences | `[AIMP:session_id]` |
| 5. Consensus | Hub | Notifies all participants of confirmed time/location | — |

**God-view design note:** Config `preferences` are used as *hints* to generate initial candidate time/location options only. Actual per-meeting votes always come from each participant's individual email reply. Static config cannot represent real-time availability.

**Key Design: Fallback Compatibility**

If the recipient does not have an Agent, send a natural language email to the human's email address and parse the human's free-text reply using an LLM. This makes it usable by a single person from day one.

-----

## II. File Structure

```
aimp/
├── lib/                          # Core libraries (canonical implementations)
│   ├── __init__.py
│   ├── transport.py              # BaseTransport ABC + EmailTransport (wraps EmailClient)
│   │                             #   Agents program against BaseTransport; swap email↔Telegram/Slack
│   ├── email_client.py           # IMAP/SMTP wrapper with OAuth2 & SSL support
│   │                             #   Phase 2: send_cfp_email, fetch_phase2_emails
│   │                             #   ParsedEmail: +phase, +deadline, +room_id fields
│   ├── protocol.py               # AIMP/0.1 protocol data model
│   │                             #   Phase 1: AIMPSession, ProposalItem
│   │                             #   Phase 2: AIMPRoom, Artifact
│   ├── negotiator.py             # LLM decision engine (Negotiator, HubNegotiator)
│   ├── session_store.py          # SQLite persistence
│   │                             #   Phase 1: sessions + sent_messages tables
│   │                             #   Phase 2: rooms table (save_room/load_room/load_open_rooms)
│   └── output.py                 # JSON stdout event emission (for OpenClaw)
├── agent.py                      # Standalone Agent (AIMPAgent)
├── hub_agent.py                  # Hub Agent (AIMPHubAgent extends AIMPAgent)
│                                 #   Phase 1: scheduling, invite codes, member whitelist
│                                 #   Phase 2: RoomNegotiator, initiate_room, _handle_room_email,
│                                 #            _finalize_room, _check_deadlines, veto flow
│                                 #   create_agent() factory: auto-detects mode from config
├── hub_prompts.py                # Phase 1 LLM prompt templates (scheduling)
├── room_prompts.py               # Phase 2 LLM prompt templates (content negotiation)
│                                 #   parse_amendment, aggregate_amendments, generate_minutes
├── run_demo.py                   # Phase 1: 3-Agent Standalone Demo
├── run_room_demo.py              # Phase 2: Room negotiation demo (in-memory, no real email)
├── openclaw-skill/
│   ├── SKILL.md                  # OpenClaw runbook (hub + standalone)
│   └── scripts/
│       ├── initiate.py           # Uses create_agent(), supports --initiator for hub
│       ├── poll.py               # Uses create_agent()
│       ├── respond.py            # Hub-aware config loading
│       ├── status.py
│       └── setup_config.py       # Hub wizard + standalone wizard
├── config/
│   ├── agent_a.yaml
│   ├── agent_b.yaml
│   └── agent_c.yaml
├── docs/
│   ├── VISION_ARTICLE.md         # Conceptual article: async AI time paradigm
│   ├── PHASE2_ROOM_ARCHITECTURE.md  # Phase 2 design doc
│   ├── STYLE_GUIDE.md
│   └── MAINTENANCE_CHECKLIST.md
└── references/
    └── config-example.yaml       # Both mode config examples
```

Root-level `email_client.py`, `negotiator.py`, `protocol.py` are legacy copies — use `lib/` versions.

-----

## III. Configuration Format

Auto-detected from file: `members:` field → Hub mode; `owner:` field → Standalone mode.

### Hub Mode Config

```yaml
mode: hub
hub:
  name: "Family Hub"
  email: "family-hub@gmail.com"
  imap_server: "imap.gmail.com"
  smtp_server: "smtp.gmail.com"
  imap_port: 993
  smtp_port: 465
  password: "$HUB_PASSWORD"

members:
  alice:
    name: "Alice"
    email: "alice@gmail.com"     # whitelist identity + notification
    role: "admin"                # admin can manage config; member can only use
    preferences:
      preferred_times: ["weekday mornings"]
      blocked_times: ["Friday afternoons"]
      preferred_locations: ["Zoom"]
      auto_accept: true
  bob:
    name: "Bob"
    email: "bob@gmail.com"
    role: "member"
    preferences:
      preferred_times: ["afternoon 14:00-17:00"]
      preferred_locations: ["Tencent Meeting"]
      auto_accept: true

contacts:                        # External (outside Hub)
  Dave:
    human_email: "dave@gmail.com"
    has_agent: false

# Invite code self-registration system
invite_codes:
  - code: "welcome-2026"
    expires: "2026-12-31"
    max_uses: 3
    used: 0              # auto-updated by Hub, do not edit manually

trusted_users: {}        # auto-populated when users register via invite code

llm:
  provider: "local"              # Ollama (free, always-on machine)
  model: "llama3"
  base_url: "http://localhost:11434/v1"
```

### Standalone Mode Config (backward compatible)

```yaml
agent:
  name: "Alice's Assistant"
  email: "alice-agent@example.com"
  imap_server: "imap.example.com"
  smtp_server: "smtp.example.com"
  password: "$AGENT_PASSWORD"

owner:
  name: "Alice"
  email: "alice@gmail.com"

preferences:
  preferred_times: ["weekday mornings 9:00-12:00"]
  blocked_times: ["Friday afternoons"]
  preferred_locations: ["Zoom"]
  auto_accept: true

contacts:
  Bob:
    agent_email: "bob-agent@example.com"
    human_email: "bob@gmail.com"
    has_agent: true

llm:
  provider: "anthropic"
  model: "claude-sonnet-4-6"
  api_key_env: "ANTHROPIC_API_KEY"
```

-----

## IV. Protocol Format (AIMP/0.1)

### 4.1 Email Specification

- **Subject**: `[AIMP:<session_id>] v<version> <Brief Description>`
  - Example: `[AIMP:meeting-001] v1 Q1 Review Meeting Time Negotiation`
- **Body**: Plain text, human-readable summary
- **JSON Attachment**: `protocol.json`, structured protocol data
- **References Header**: References the Message-ID of the previous email in the thread

### 4.2 protocol.json Structure

```json
{
  "protocol": "AIMP/0.1",
  "session_id": "meeting-001",
  "version": 3,
  "from": "alice-agent@example.com",
  "action": "propose",
  "participants": [
    "alice-agent@example.com",
    "bob-agent@example.com",
    "carol-agent@example.com"
  ],
  "topic": "Q1 Review Meeting",
  "proposals": {
    "time": {
      "options": ["2026-03-01T10:00", "2026-03-02T14:00"],
      "votes": {
        "alice-agent@example.com": "2026-03-01T10:00",
        "bob-agent@example.com": null,
        "carol-agent@example.com": null
      }
    },
    "location": {
      "options": ["Zoom", "Office 3F", "Tencent Meeting"],
      "votes": {
        "alice-agent@example.com": "Zoom",
        "bob-agent@example.com": null,
        "carol-agent@example.com": null
      }
    }
  },
  "status": "negotiating",
  "history": [
    {"version": 1, "from": "alice-agent@example.com", "action": "propose", "summary": "Initiated meeting proposal"},
    {"version": 2, "from": "bob-agent@example.com", "action": "counter", "summary": "Suggested in-person instead"},
    {"version": 3, "from": "carol-agent@example.com", "action": "accept", "summary": "Agreed to Time A and in-person"}
  ]
}
```

### 4.3 Action Types

|action    |Meaning    |Trigger Condition         |
|----------|------|-------------|
|`propose` |Initiate Proposal  |Human requests a meeting      |
|`accept`  |Accept Proposal|All items match preferences    |
|`counter` |Counter Proposal   |Partial match, propose alternatives  |
|`confirm` |Final Confirmation  |All participants accepted|
|`escalate`|Escalate to Human  |Cannot decide automatically (outside preferences) |

### 4.4 Consensus Rules

- Each topic (time/location) is voted on independently
- If an option receives votes from all participants → Topic is resolved
- All topics resolved → Send `confirm`
- More than 5 rounds without consensus → `escalate` to all humans

-----

## V. Core Module Reference

### 5.1 lib/session_store.py — SQLite Persistence

Two tables: `sessions` (JSON-serialized `AIMPSession`) and `sent_messages` (email threading).

```python
class SessionStore:
    def save(self, session: AIMPSession)
    def load(self, session_id: str) -> AIMPSession
    def load_active(self) -> list[AIMPSession]      # status == "negotiating"
    def delete(self, session_id: str)
    def save_message_id(self, session_id, msg_id)
    def load_message_ids(self, session_id) -> list[str]
```

### 5.2 lib/transport.py — Transport Abstraction

Agents program against `BaseTransport`; the concrete implementation is `EmailTransport` (wraps `EmailClient`). Future transports (Telegram, Slack, …) only need to implement the same ABC.

```python
class BaseTransport(ABC):
    def my_address(self) -> str                          # own address (e.g. email)
    def fetch_aimp_emails(self, since_minutes=60)        # Phase 1 inbox
    def fetch_all_unread_emails(self, since_minutes=60)  # Hub: all unread
    def fetch_phase2_emails(self, since_minutes=60)      # Phase 2 Room inbox
    def send_aimp_email(self, to, session_id, version, subject_suffix,
                        body_text, protocol_json, references=None, in_reply_to=None) -> str
    def send_cfp_email(self, to, room_id, topic, deadline_iso,
                       initial_proposal, resolution_rules, body_text, references=None) -> str
    def send_human_email(self, to, subject, body)

class EmailTransport(BaseTransport):
    """Delegates every call to EmailClient. Drop-in replacement for future transports."""
```

### 5.3 lib/email_client.py — IMAP/SMTP Wrapper (internal)

`EmailClient` is no longer used directly by agents — it is wrapped by `EmailTransport`. Helpers remain importable from here:

```python
# Helpers
def is_aimp_email(parsed: ParsedEmail) -> bool
def extract_protocol_json(parsed: ParsedEmail) -> Optional[dict]
```

### 5.4 lib/protocol.py — Session State

```python
class AIMPSession:
    session_id: str
    topic: str
    participants: list[str]
    initiator: str
    _version: int
    proposals: dict[str, ProposalItem]  # {"time": ..., "location": ...}
    history: list[HistoryEntry]
    status: str  # "negotiating" | "confirmed" | "escalated"
    created_at: float

    def apply_vote(self, voter, item, choice)
    def add_option(self, item, option)
    def check_consensus(self) -> dict   # {item: resolved_value | None}
    def is_fully_resolved(self) -> bool
    def bump_version(self)
    def to_json(self) / from_json(cls, data)
```

### 5.5 lib/negotiator.py — LLM Decision Engine

```python
class Negotiator:
    def decide(self, session: AIMPSession) -> tuple[str, dict]
        # Returns: ("accept"|"counter"|"escalate", {votes, new_options, reason})

    def parse_human_reply(self, reply_body, session) -> tuple[str, dict]
        # NLU: free-text → structured votes

    def generate_human_readable_summary(self, session, action) -> str
    def generate_human_email_body(self, session) -> str  # for non-Agent recipients

class HubNegotiator:
    def find_optimal_slot(self, topic, member_prefs: dict) -> dict
        # God-view: aggregates all member preferences, returns consensus or candidates
```

### 5.6 lib/protocol.py — Phase 2 Data Structures

```python
@dataclass
class Artifact:
    name: str            # e.g. "budget_v1.txt"
    content_type: str    # "text/plain" | "application/pdf"
    body_text: str       # text content
    author: str          # submitter email
    timestamp: float

@dataclass
class AIMPRoom:
    room_id: str
    topic: str
    deadline: float                          # Unix timestamp
    participants: list[str]
    initiator: str
    artifacts: dict[str, Artifact]           # {name: Artifact}
    transcript: list[HistoryEntry]           # discussion log
    status: str                              # "open" → "locked" → "finalized"
    resolution_rules: str                    # "majority" | "consensus" | "initiator_decides"
    accepted_by: list[str]                   # emails that sent ACCEPT

    def is_past_deadline(self) -> bool
    def all_accepted(self) -> bool
    def add_to_transcript(self, from_agent, action, summary)
    def to_json(self) / from_json(cls, data)
```

### 5.7 agent.py — AIMPAgent

```python
class AIMPAgent:
    def __init__(self, config_path, notify_mode="email", db_path=None)
        # notify_mode: "email" (notify owner via email) | "stdout" (emit JSON for OpenClaw)

    def run(self, poll_interval=30)     # Main loop
    def poll(self) -> list[dict]        # One cycle: fetch emails, handle each
    def handle_email(self, parsed)      # Routes to _handle_aimp_email or _handle_human_email
    def initiate_meeting(self, topic, participant_names) -> str  # Returns session_id

# Key attribute: self.transport (EmailTransport) — all I/O goes through this
```

Session state is persisted to SQLite via `SessionStore` (not in-memory dict).

### 5.8 hub_agent.py — AIMPHubAgent

```python
class AIMPHubAgent(AIMPAgent):
    # Core identity + scheduling:
    def identify_sender(from_email) -> Optional[str]   # email → member_id (whitelist check)
    def initiate_meeting(topic, participant_names, initiator_member_id) -> str
        # Detects internal vs external participants
        # Internal only → _initiate_internal_meeting() (LLM god-view, no email)
        # Has externals → _initiate_hybrid_meeting() (merge prefs → AIMP email)

    # Stage-2 processor — the core command handler:
    def handle_member_command(from_email, body) -> list[dict]
        # 1. LLM parse → {action, topic, participants, initiator_times, initiator_locs, missing}
        # 2. Completeness check → reply email listing missing required fields
        # 3. Contact resolution → reply email asking for unknown contact emails
        # 4. Store initiator's stated availability as temporary preferences
        # 5. Auto-dispatch initiate_meeting()
        # 6. Send initiator a vote request email (they are also a voter)

    # Stage-2 helpers:
    def _parse_member_request(member_name, body) -> dict
    def _find_participant_contact(name) -> Optional[dict]  # members → contacts → raw email
    def _send_initiator_vote_request(from_email, member_name, session)
        # session.ensure_participant(from_email) → send [AIMP:session_id] vote invitation
    def _reply_unknown_sender(from_email)
        # Template: "register first via [AIMP-INVITE:code]"

    # Invite code self-registration:
    def _check_invite_email(parsed) -> Optional[list[dict]]   # detects [AIMP-INVITE:code] in subject
    def _handle_invite_request(from_email, sender_name, code) -> list[dict]
        # validate → register → welcome email with hub-card JSON block
    def _validate_invite_code(code) -> Optional[dict]         # checks expiry + usage limit
    def _register_trusted_user(email, name, via_code)         # adds to members + _email_to_member
    def _consume_invite_code(code)
    def _persist_config()   # writes invite_codes + trusted_users back to config.yaml

    # Hub card embedded in welcome email:
    # {"aimp_hub": {"name", "email", "protocol", "capabilities", "registered_members",
    #               "usage": {"schedule_meeting": {required_fields, example}},
    #               "session_threading": {"pattern": "[AIMP:{session_id}]"}}}

class HubNegotiator:
    def find_optimal_slot(topic, member_prefs) -> dict
        # God-view: one LLM call aggregates all prefs → returns candidate options
        # consensus=true: fills time+location; false: returns options list
    def generate_member_notify_body(topic, result, ...) -> str

def create_agent(config_path, **kwargs) -> AIMPAgent | AIMPHubAgent
    # Factory: "members:" in config → AIMPHubAgent; "owner:" → AIMPAgent
```

**`ParsedEmail` additions:**
```python
@dataclass
class ParsedEmail:
    ...
    sender_name: Optional[str] = None   # Display name from From: header ("Alice Wang" from "Alice Wang <alice@...>")
```

-----

## VI. Fallback Compatibility Design

### 6.1 Identify Sender (Agent vs Human)

```python
def is_aimp_email(email) -> bool:
    return "[AIMP:" in email.subject and any(a["filename"] == "protocol.json" for a in email.attachments)
```

On reply: Has `[AIMP:]` prefix + `protocol.json` attachment → Agent Mode; otherwise → Human Mode.

### 6.2 Email Template for Humans

```
Subject: [AIMP:session-001] Meeting Invitation: Q1 Review

Hi Bob,

Alice would like to schedule a Q1 review meeting with you and Carol.

Does any of the following times work for you?
A. March 1st, Monday, 10:00 AM
B. March 2nd, Tuesday, 2:00 PM

Location preferences?
1. Zoom
2. Office 3F
3. Tencent Meeting

Just reply to this email directly, e.g., "A and 1" or "Monday morning is fine, Zoom".

—— Alice's AI Assistant
```

### 6.3 Parsing Human Reply

LLM NLU converts free-text to structured votes, then applies them to session as normal.

-----

## VII. Demo Script run_demo.py

Starts 3 standalone Agents in threads. Agent-A automatically initiates a meeting proposal.

```
Usage:
  1. Fill config/agent_a.yaml, agent_b.yaml, agent_c.yaml
  2. Set env var ANTHROPIC_API_KEY
  3. python run_demo.py
```

-----

## VIII. Preparation Checklist

1.  **3 Email Accounts** (Gmail/Outlook/Any IMAP supported), enable IMAP and App Password.
2.  **LLM API Key** (Anthropic or OpenAI) or local Ollama.
3.  **Python 3.10+**.
4.  **Dependencies**: `pip install -r requirements.txt` (pyyaml, anthropic/openai, imaplib/smtplib are stdlib).

-----

## IX. Phase 2 — "The Room" (✅ Implemented)

Phase 2 extends AIMP from scheduling (time/location) to **content negotiation** (documents, budgets, proposals) within a deadline-bounded async window. It is implemented as an extension of the existing Hub — no separate agent required.

### Core Concept

| | Phase 1 | Phase 2 |
|---|---|---|
| What's negotiated | Time slot + location | Any content (docs, budgets, decisions) |
| Convergence trigger | Unanimous vote | All send ACCEPT, or deadline reached |
| Hub role | Scheduler | Room Manager |
| Output | Confirmed meeting time | Meeting minutes |
| Status machine | negotiating → confirmed | open → locked → finalized |

### Architecture Decision: Hub Extension (Not Separate Agent)

Phase 2 logic lives in the same Hub email account via **delegation** to `RoomNegotiator`. Hub's `poll()` fetches `[AIMP:Room:]` emails first (before Phase 1 processing), then checks for expired deadlines.

### How to Use

**Member initiates a Room** (email to Hub):
```
Subject: (anything)
Body: 帮我发起一个协商室，和 Bob、Carol 讨论 Q3 预算方案，截止 3 天后。
      初始提案：研发$60k，市场$25k，运营$15k
```

**Participants reply with actions:**
- `ACCEPT` — agrees with current proposal
- `AMEND + text` — proposes changes
- `PROPOSE + text` — submits a new draft
- `REJECT + reason` — blocks proposal

**When finalized** (all ACCEPT or deadline), Hub sends meeting minutes to all participants. Participants can reply `CONFIRM` or `REJECT <reason>` for the veto flow.

### Key Files

| File | Role |
|------|------|
| `lib/protocol.py` | `Artifact` + `AIMPRoom` dataclasses |
| `lib/session_store.py` | `rooms` table: `save_room`/`load_room`/`load_open_rooms` |
| `lib/email_client.py` | `send_cfp_email`, `fetch_phase2_emails`, Phase 2 headers |
| `room_prompts.py` | LLM templates: parse_amendment, aggregate, generate_minutes |
| `hub_agent.py` | `RoomNegotiator` class + all room lifecycle methods |
| `run_room_demo.py` | Integration demo (in-memory, no real email/LLM) |

### Run the Demo

```bash
python run_room_demo.py
```

-----

## X. Promotion Strategy

1. **Use it yourself first**. Run your Agent, send normal emails to everyone to schedule meetings. They don't need to install anything.
2. **When someone gets curious**, give them the README link, they can run it in 5 mins.
3. **Fallback compatibility is the lifeline** — never require the other party to install the Agent to use it.
4. **Demo GIF > 10k words**. Record a 30s demo, put it at the top of README.

# AIMP — Implementation Guide

> Goal: AI Agents negotiate meeting schedules and content via email. Hub mode only (one Agent serves many).
> Constraints: No hash chains, no DID, no signatures, no payments. Only the "runnable" minimum closed loop.

---

## Current Status

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1 | ✅ Complete | Email-based meeting time/location negotiation |
| Phase 2 | ✅ Implemented | "The Room" — async content negotiation with deadline |
| Phase 3 | ✅ Refactored | Transport abstraction — `BaseTransport` ABC + `EmailTransport` |
| Phase 4 | ✅ Implemented | Store-First + Round Protocol — reliable processing, round-gated replies |
| Phase 5 | 🗓 Planned | Multi-transport — Telegram / Slack via `BaseTransport` |

---

## I. Architecture

```
New user ──[AIMP-INVITE:code]──→ ┐
Member   ──"schedule meeting"──→ ├─ HubAgent (1 email address) ──→ External contacts / Agents
                                 ↓
                     Notifies all participants
```

Hub is a **single deployable skill** — users interact via email only. No agent required on the user's side.

**Email lifecycle (Phase 1 — scheduling):**

| Stage | Actor | Subject pattern |
|-------|-------|-----------------|
| Self-registration | New user | `[AIMP-INVITE:code]` |
| Meeting request | Member | (any) |
| AIMP negotiation | Hub ↔ Externals | `[AIMP:session_id]` |
| Consensus notify | Hub → All | — |

**Phase 2 — Room negotiation:**

| Stage | Actor | Subject pattern |
|-------|-------|-----------------|
| Create room | Member → Hub | (any) |
| CFP / amendments | Hub ↔ Participants | `[AIMP:Room:room_id]` |
| Meeting minutes | Hub → All | `[AIMP:Room:room_id]` |
| Veto flow | Participants → Hub | `[AIMP:Room:room_id]` |

**Fallback compatibility:** If a recipient has no Agent, Hub sends human-readable email and parses free-text reply via LLM.

---

## II. File Structure

```
aimp/
├── lib/
│   ├── transport.py         # BaseTransport ABC + EmailTransport
│   ├── email_client.py      # IMAP/SMTP wrapper; ParsedEmail; is_aimp_email; extract_protocol_json
│   ├── protocol.py          # AIMPSession + AIMPRoom + Artifact; round fields (Phase 4)
│   ├── negotiator.py        # Negotiator base (LLM decisions)
│   ├── hub_negotiator.py    # HubNegotiator — member vote aggregation LLM helper
│   ├── room_negotiator.py   # RoomNegotiator — Phase 2 content negotiation LLM helper
│   ├── session_store.py     # SQLite: sessions, sent_messages, rooms, pending_emails
│   └── output.py            # JSON stdout event emission
├── handlers/
│   ├── __init__.py
│   ├── session_handler.py   # SessionMixin — Phase 1 scheduling methods
│   ├── room_handler.py      # RoomMixin — Phase 2 room lifecycle methods
│   ├── command_handler.py   # CommandMixin — member command parsing & dispatch
│   └── registration_handler.py  # RegistrationMixin — invite code self-registration
├── agent.py               # AIMPAgent base class
├── hub_agent.py           # Thin orchestrator (~520 lines): AIMPHubAgent + create_agent() factory
├── hub_prompts.py         # Phase 1 LLM prompt templates
├── room_prompts.py        # Phase 2 LLM prompt templates
├── run_room_demo.py       # Phase 2 in-memory demo (no real email/LLM)
├── config/                # Hub config yaml files
├── openclaw-skill/        # OpenClaw runbook + scripts
├── docs/
└── references/
```

---

## III. Configuration

`create_agent()` is Hub-only — raises `ValueError` if config lacks `members:` or `mode: hub`.

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
    role: "admin"

contacts:
  Dave:
    human_email: "dave@example.com"
    has_agent: false

invite_codes:
  - code: "welcome-2026"
    expires: "2026-12-31"
    max_uses: 3
    used: 0

trusted_users: {}

llm:
  provider: "anthropic"
  model: "claude-sonnet-4-6"
  api_key_env: "ANTHROPIC_API_KEY"
```

---

## IV. Protocol (AIMP/0.1)

**Subject:** `[AIMP:<session_id>] v<version> <topic>`
**Body:** Plain text summary
**Attachment:** `protocol.json`

```json
{
  "protocol": "AIMP/0.1",
  "session_id": "meeting-001",
  "version": 2,
  "from": "hub@example.com",
  "action": "counter",
  "participants": ["hub@example.com", "bob@example.com"],
  "topic": "Q1 Review",
  "proposals": {
    "time": {
      "options": ["2026-03-01T10:00", "2026-03-02T14:00"],
      "votes": {"hub@example.com": "2026-03-01T10:00", "bob@example.com": null}
    },
    "location": {
      "options": ["Zoom", "Office 3F"],
      "votes": {"hub@example.com": "Zoom", "bob@example.com": null}
    }
  },
  "status": "negotiating",
  "current_round": 1,
  "round_respondents": [],
  "history": [...]
}
```

**Actions:** `propose` · `counter` · `accept` · `confirm` · `escalate`

**Consensus:** each topic resolves independently; all resolved → `confirm`; >5 rounds → `escalate`

---

## V. Round Protocol (Phase 4)

Hub does not reply to each email immediately. It waits for the round to complete, then sends one aggregated reply.

| Round | Who must reply | Rationale |
|-------|---------------|-----------|
| Round 1 | All non-initiators | Initiator already spoke in Round 0 (initial proposal / CFP) |
| Round 2+ | All participants (incl. initiator) | Everyone re-votes on each new Hub summary |

**Store-First:** every incoming email is saved to `pending_emails` before any LLM processing. If the process crashes mid-round, emails survive in the DB for reprocessing.

This applies equally to Phase 1 (session) and Phase 2 (room).

---

## VI. Core Module Reference

### lib/session_store.py

Four SQLite tables: `sessions`, `sent_messages`, `rooms`, `pending_emails`.

```python
# Session CRUD
store.save(session) / load(session_id) / load_active() / delete(session_id)
store.save_message_id(session_id, msg_id) / load_message_ids(session_id)

# Room CRUD
store.save_room(room) / load_room(room_id) / load_open_rooms()

# Store-First (Phase 4)
store.save_pending_email(from_addr, subject, body,
                         protocol_json=None, session_id=None, room_id=None) -> int
store.load_pending_for_session(session_id) -> list[dict]
store.load_pending_for_room(room_id) -> list[dict]
store.mark_processed(email_id)
```

### lib/protocol.py

```python
class AIMPSession:
    # fields: session_id, topic, participants, initiator, _version,
    #         proposals, history, status, created_at, current_round, round_respondents
    def apply_vote(voter, item, choice)
    def check_consensus() -> dict        # {item: value | None}
    def is_fully_resolved() -> bool
    def is_stalled() -> bool             # round_count >= MAX_ROUNDS (5)
    def record_round_reply(from_email)
    def is_round_complete() -> bool
    def advance_round()

class AIMPRoom:
    # fields: room_id, topic, deadline, participants, initiator, artifacts,
    #         transcript, status, resolution_rules, accepted_by,
    #         current_round, round_respondents
    def is_past_deadline() -> bool
    def all_accepted() -> bool
    def add_to_transcript(from_agent, action, summary)
    def record_round_reply(from_email)
    def is_round_complete() -> bool
    def advance_round()
```

### lib/transport.py

```python
class BaseTransport(ABC):
    def fetch_aimp_emails(since_minutes=60)        # Phase 1
    def fetch_phase2_emails(since_minutes=60)      # Phase 2
    def fetch_all_unread_emails(since_minutes=60)  # member commands
    def send_aimp_email(to, session_id, version, subject_suffix,
                        body_text, protocol_json, references=None) -> str
    def send_cfp_email(to, room_id, topic, deadline_iso,
                       initial_proposal, resolution_rules, body_text) -> str
    def send_human_email(to, subject, body)
```

### hub_agent.py

`AIMPHubAgent` is now a thin orchestrator that inherits all behaviour from four mixins:

```python
class AIMPHubAgent(SessionMixin, RoomMixin, CommandMixin, RegistrationMixin, AIMPAgent):
    # Owns: __init__, poll, identify_sender, _notify_members, _handle_human_email,
    #       _notify_owner_confirmed, _load_internal_members,
    #       _parse_deadline, _ts_to_iso, _email_to_name

    # Poll (Phase 4 store-first + round-gated):
    def poll() -> list[dict]
        # Phase 2: fetch_phase2_emails → save_pending → record_round_reply
        #          → if round_complete: _process_room_round → mark_processed
        # Phase 1: fetch_aimp_emails   → save_pending → record_round_reply
        #          → if round_complete: _process_session_round → mark_processed
        # Commands: fetch_all_unread → save_pending → handle_member_command

def create_agent(config_path, **kwargs) -> AIMPHubAgent
    # Raises ValueError if config is not Hub mode
```

**Mixin responsibilities:**

| Mixin | File | Methods |
|-------|------|---------|
| `SessionMixin` | `handlers/session_handler.py` | `initiate_meeting`, `_initiate_internal_meeting`, `_initiate_hybrid_meeting`, `_apply_votes_from_protocol`, `_send_session_reply`, `_process_session_round` |
| `RoomMixin` | `handlers/room_handler.py` | `initiate_room`, `_handle_room_email`, `_apply_room_action`, `_send_room_reply`, `_process_room_round`, `_finalize_room`, `_check_deadlines`, `_handle_room_confirm`, `_handle_room_reject`, `_broadcast_room_status` |
| `CommandMixin` | `handlers/command_handler.py` | `handle_member_command`, `_handle_create_room_command`, `_parse_member_request`, `_find_participant_contact`, `_send_initiator_vote_request`, `_is_auto_reply`, `_reply_unknown_sender` |
| `RegistrationMixin` | `handlers/registration_handler.py` | `_check_invite_email`, `_handle_invite_request`, `_validate_invite_code`, `_register_trusted_user`, `_consume_invite_code`, `_persist_config` |

**Import rule:** mixins import from `lib/` and prompt files only — never from `hub_agent` or each other. Cross-mixin calls go through `self` (Python MRO resolves them automatically).

### lib/hub_negotiator.py

```python
class HubNegotiator:
    def find_optimal_slot(topic, member_replies) -> dict
    def generate_member_notify_body(topic, result, initiator_name, participant_names) -> str
```

### lib/room_negotiator.py

```python
class RoomNegotiator:
    def parse_amendment(member_name, body, current_artifacts) -> dict
    def aggregate_amendments(room) -> dict
    def generate_meeting_minutes(room) -> str
```

---

## VII. Phase 2 — "The Room"

Extends AIMP from scheduling to **content negotiation** (documents, budgets, decisions) within a deadline-bounded window.

| | Phase 1 | Phase 2 |
|---|---|---|
| What | Time + location | Any content |
| Convergence | Unanimous vote | All ACCEPT or deadline |
| Output | Confirmed time | Meeting minutes |
| Status | negotiating → confirmed | open → finalized |

**Participant actions:** `ACCEPT` · `AMEND <text>` · `PROPOSE <text>` · `REJECT <reason>`

**After finalization:** participants reply `CONFIRM` or `REJECT <reason>` (veto flow → initiator decides).

```bash
python run_room_demo.py   # in-memory demo
```

---

## VIII. Setup

1. **1 email account** for the Hub (Gmail/Outlook, IMAP enabled, App Password)
2. **LLM**: Anthropic API key, or local Ollama
3. **Python 3.10+** · `pip install -r requirements.txt`
4. **Run:** `python hub_agent.py config/hub.yaml`
5. **Tests:** `python -m pytest tests/ -v`  (87 tests)

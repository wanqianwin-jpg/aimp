# AIMP — Implementation Guide (Chinese Version)

> **目标**：AI Agent 通过邮件协商会议时间。仅支持 Hub 模式（一个 Agent 服务多人）。
> **约束**：不做哈希链、不做 DID、不做签名、不做支付。只做「能跑通」的最小闭环。

---

## 当前状态 (Current Status)

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1 | ✅ Complete | 基于邮件的会议时间/地点协商 |
| Phase 2 | ✅ Implemented | "The Room" — 带截止日期的异步内容协商 |
| Phase 3 | ✅ Refactored | 传输层抽象 — `BaseTransport` ABC + `EmailTransport` |
| Phase 4 | ✅ Implemented | Store-First + 轮次协议 — 可靠邮件处理 + 轮次门控回复 |
| Phase 5 | 🗓 Planned | 多传输层 — 通过 `BaseTransport` 接入 Telegram / Slack 等 |

---

## I. 架构 (Architecture)

```
New user ──[AIMP-INVITE:code]──→ ┐
Member   ──"schedule meeting"──→ ├─ HubAgent (1 email address) ──→ External contacts / Agents
                                 ↓
                     Notifies all participants
```

Hub 是一个**单点部署的 Skill** —— 用户只需通过邮件交互。用户侧不需要部署 Agent。

**邮件生命周期 (Phase 1 — 调度):**

| Stage | Actor | Subject pattern |
|-------|-------|-----------------|
| 自助注册 | New user | `[AIMP-INVITE:code]` |
| 会议请求 | Member | (任意自然语言) |
| AIMP 协商 | Hub ↔ Externals | `[AIMP:session_id]` |
| 共识通知 | Hub → All | — |

**Phase 2 — Room 协商:**

| Stage | Actor | Subject pattern |
|-------|-------|-----------------|
| Create room | Member → Hub | (任意自然语言) |
| CFP / Amendments | Hub ↔ Participants | `[AIMP:Room:room_id]` |
| Meeting minutes | Hub → All | `[AIMP:Room:room_id]` |
| Veto flow | Participants → Hub | `[AIMP:Room:room_id]` |

**降级兼容 (Fallback compatibility):** 如果收件人没有 Agent，Hub 发送人类可读邮件并用 LLM 解析回复。

---

## II. 文件结构 (File Structure)

```
aimp/
├── lib/
│   ├── transport.py       # BaseTransport ABC + EmailTransport
│   ├── email_client.py    # IMAP/SMTP wrapper; ParsedEmail; is_aimp_email; extract_protocol_json
│   ├── protocol.py        # AIMPSession + AIMPRoom + Artifact; round fields (Phase 4)
│   ├── negotiator.py      # Negotiator (LLM decisions) + HubNegotiator
│   ├── session_store.py   # SQLite: sessions, sent_messages, rooms, pending_emails
│   └── output.py          # JSON stdout event emission
├── agent.py               # AIMPAgent base class
├── hub_agent.py           # AIMPHubAgent: Phase 1-4 logic + create_agent() factory
├── hub_prompts.py         # Phase 1 LLM prompt templates
├── room_prompts.py        # Phase 2 LLM prompt templates
├── run_room_demo.py       # Phase 2 in-memory demo (no real email/LLM)
├── config/                # Hub config yaml files
├── openclaw-skill/        # OpenClaw runbook + scripts
├── docs/
└── references/
```

---

## III. 配置 (Configuration)

`create_agent()` 仅支持 Hub 模式 —— 如果配置缺少 `members:` 或 `mode: hub` 将抛出 `ValueError`。

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

## IV. 协议 (Protocol AIMP/0.1)

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

**Consensus:** 每个议题独立解决；所有解决 → `confirm`；>5 轮 → `escalate`。

---

## V. 轮次协议 (Round Protocol - Phase 4)

Hub 不会立即回复每封邮件。它会等待当前轮次完成，然后发送一封汇总回复。

| Round | Who must reply | Rationale |
|-------|---------------|-----------|
| Round 1 | 所有非发起人 | 发起人已经在 Round 0 发言（初始提案 / CFP） |
| Round 2+ | 所有参与者（含发起人） | 每个人都要对新的 Hub 汇总进行重新投票 |

**Store-First (存储优先):** 每封收到的邮件在开始任何 LLM 处理之前，都会先持久化到本地 SQLite 数据库 (`pending_emails`)。如果进程崩溃，邮件会保留在 DB 中等待重处理。

这同样适用于 Phase 1 (session) 和 Phase 2 (room)。

---

## VI. 核心模块参考 (Core Module Reference)

### lib/session_store.py

四个 SQLite 表：`sessions`, `sent_messages`, `rooms`, `pending_emails`。

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

```python
class AIMPHubAgent(AIMPAgent):
    # Poll (Phase 4 store-first + round-gated):
    def poll() -> list[dict]
        # Phase 2: fetch_phase2_emails → save_pending → record_round_reply
        #          → if round_complete: _process_room_round → mark_processed
        # Phase 1: fetch_aimp_emails   → save_pending → record_round_reply
        #          → if round_complete: _process_session_round → mark_processed
        # Commands: fetch_all_unread → save_pending → handle_member_command

    # Round processors:
    def _process_session_round(session, pending) -> list[dict]
    def _process_room_round(room, pending) -> list[dict]

    # Scheduling:
    def initiate_meeting(topic, participant_names, initiator_member_id) -> str
    def handle_member_command(from_email, body) -> list[dict]

    # Room lifecycle:
    def initiate_room(topic, participants, deadline, initial_proposal, initiator) -> str
    def _handle_room_email(parsed) -> list[dict]   # still used for non-round-gated paths
    def _finalize_room(room)
    def _check_deadlines()

    # Registration:
    def _check_invite_email(parsed) -> Optional[list[dict]]
    def identify_sender(from_email) -> Optional[str]

def create_agent(config_path, **kwargs) -> AIMPHubAgent
    # Raises ValueError if config is not Hub mode
```

---

## VII. Phase 2 — "The Room"

将 AIMP 从调度扩展到 **内容协商**（文档、预算、决策），在一个有截止日期的窗口内进行。

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

---

## IX. 降级兼容设计 (Fallback Details)

### 判断发件方（Agent vs 人类）

```python
def is_aimp_email(email) -> bool:
    return "[AIMP:" in email.subject and any(a["filename"] == "protocol.json" for a in email.attachments)
```

收到回复时：有 `[AIMP:]` 前缀 + `protocol.json` 附件 → Agent 模式；否则 → 人类模式。

### 给人类发的邀请邮件模板

```
Subject: [AIMP:session-001] 会议邀请：Q1 复盘会

Hi Bob，

Alice 想约你和 Carol 开个 Q1 复盘会。

以下时间你方便吗？
A. 3月1日 周一 上午10:00
B. 3月2日 周二 下午2:00

地点偏好？
1. Zoom
2. 线下会议室

直接回复这封邮件就行，比如「A 和 1」或「周一上午可以，Zoom 开会」。

—— Alice's AI Assistant
```

### 解析人类回复

LLM 自然语言理解将自由文本转为结构化投票，再正常 apply 到 session 中。

---

## X. 邀请码注册流程 (Invite Code Details)

### 管理员准备

在 config.yaml 的 `invite_codes` 下加一条：

```yaml
invite_codes:
  - code: "my-secret-code"
    expires: "2026-12-31"
    max_uses: 5
    used: 0
```

告知新用户：「给 Hub 邮箱发邮件，主题写 `[AIMP-INVITE:my-secret-code]` 即可注册。」

### 新用户注册

1. 发邮件给 Hub，主题：`[AIMP-INVITE:my-secret-code]`（正文随意）
2. Hub 验证邀请码（检查过期时间 + 使用次数）
3. 注册成功 → Hub 回复欢迎邮件，包含：
   - 用法说明（自然语言示例）
   - hub-card JSON 块（AI Agent 可读的能力声明）
4. 之后直接发邮件约会议，无需再提邀请码

### hub-card（AI Agent 可读）

```json
{
  "aimp_hub": {
    "version": "1.0",
    "name": "Hub 名称",
    "email": "hub@example.com",
    "protocol": "AIMP/email",
    ...
  }
}
```

# AIMP — 架构与实现指南（中文版）

> **目标**：AI Agent 通过邮件协商会议时间。支持 Hub 模式（一个 Agent 服务多人）和 Standalone 模式（每人一个 Agent）。
> **约束**：不做哈希链、不做 DID、不做权限预算、不做签名、不做支付。只做「能跑通」的最小闭环。

-----

## 当前状态

| 阶段 | 状态 | 说明 |
|------|------|------|
| Phase 1 | ✅ 已完成 | 基于邮件的会议时间/地点协商 |
| Phase 2 | ✅ 已实现 | "The Room" — 带截止日期的异步内容协商 |

Phase 1 已完整实现于 `lib/` + `agent.py` + `hub_agent.py`。所有模块均可运行。

Phase 2 已在同一个 Hub (`hub_agent.py`) 中通过委托给 `RoomNegotiator` 实现。无需单独的 Agent。运行 `python run_room_demo.py` 即可查看完整流程。

-----

## 一、整体架构

### Standalone 模式

```
Alice (人) ──偏好配置──→ Agent-A ──邮件──→ ┐
Bob   (人) ──偏好配置──→ Agent-B ──邮件──→ ├─ 共享邮件线程
Carol (人) ──偏好配置──→ Agent-C ──邮件──→ ┘
                 ↑                           │
                 └── 结果通知（邮件/终端） ←──┘
```

### Hub 模式（推荐）— "Hub Skill" 范式

```
新用户 ──[AIMP-INVITE:code]──→ ┐
成员   ──"schedule meeting"──→ ├─ HubAgent (1 个邮箱地址) ──→ 外部联系人 / Agents
                                 │
                         (内部：直接 LLM 调度)
                                 ↓
                     通知所有参与者
```

Hub 是一个**单点部署的 Skill** —— 用户只需通过邮件交互。用户侧不需要部署 Agent。

**完整邮件生命周期：**

| 阶段 | 操作方 | 动作 | 邮件主题模式 |
|-------|-------|--------|----------------------|
| 0. 注册 | 管理员 | 在 config.yaml 中创建邀请码 | — |
| 1. 自助注册 | 新用户 | 给 Hub 发邮件，主题含邀请码 | `[AIMP-INVITE:code]` |
| 1. 回复 | Hub | 校验邀请码，注册用户，发欢迎邮件 + hub-card JSON | — |
| 2. 会议请求 | 成员 | 自然语言会议请求 | (任意) |
| 2. 信息不全 | Hub | 回复要求补充信息 (主题 / 参与者 / 可用性) | — |
| 3. 发出邀请 | Hub | LLM 解析 → 自动派发 `initiate_meeting()` | `[AIMP:session_id]` |
| 3. 发起者投票 | Hub | 给发起者发送投票邀请 (他们也是投票方) | `[AIMP:session_id]` |
| 4. 投票 | 所有人 | 回复时间/地点偏好 | `[AIMP:session_id]` |
| 5. 达成共识 | Hub | 通知所有参与者确认的时间/地点 | — |

**上帝视角设计说明：** 配置中的 `preferences` 仅作为生成初始候选时间/地点选项的 *提示*。实际的每次会议投票始终来自每个参与者的个人邮件回复。静态配置无法代表实时可用性。

**关键设计：降级兼容**

如果收件人没有 Agent，则向该人的电子邮箱发送自然语言邮件，并使用 LLM 解析该人的自由文本回复。这使得 AIMP 从第一天起就可以被单个人使用。

-----

## 二、文件结构

```
aimp/
├── lib/                          # 核心库 (规范实现)
│   ├── __init__.py
│   ├── transport.py              # BaseTransport ABC + EmailTransport（包装 EmailClient）
│   │                             #   Agent 面向 BaseTransport 编程；可替换为 Telegram/Slack 等
│   ├── email_client.py           # IMAP/SMTP 封装，支持 OAuth2 & SSL
│   │                             #   Phase 2: send_cfp_email, fetch_phase2_emails
│   │                             #   ParsedEmail: 新增 phase, deadline, room_id 字段
│   ├── protocol.py               # AIMP/0.1 协议数据模型
│   │                             #   Phase 1: AIMPSession, ProposalItem
│   │                             #   Phase 2: AIMPRoom, Artifact
│   ├── negotiator.py             # LLM 决策引擎 (Negotiator, HubNegotiator)
│   ├── session_store.py          # SQLite 持久化
│   │                             #   Phase 1: sessions + sent_messages 表
│   │                             #   Phase 2: rooms 表 (save_room/load_room/load_open_rooms)
│   └── output.py                 # JSON stdout 事件发射 (供 OpenClaw 使用)
├── agent.py                      # 独立 Agent (AIMPAgent)
├── hub_agent.py                  # Hub Agent (AIMPHubAgent 继承自 AIMPAgent)
│                                 #   Phase 1: 调度、邀请码、成员白名单
│                                 #   Phase 2: RoomNegotiator, initiate_room, _handle_room_email,
│                                 #            _finalize_room, _check_deadlines, veto flow
│                                 #   create_agent() 工厂：根据配置自动检测模式
├── hub_prompts.py                # Phase 1 LLM 提示词模板 (调度)
├── room_prompts.py               # Phase 2 LLM 提示词模板 (内容协商)
│                                 #   parse_amendment, aggregate_amendments, generate_minutes
├── run_demo.py                   # Phase 1: 3-Agent 独立演示
├── run_room_demo.py              # Phase 2: 房间协商演示 (内存模拟，无真实邮件)
├── openclaw-skill/
│   ├── SKILL.md                  # OpenClaw 运行指南 (hub + standalone)
│   └── scripts/
│       ├── initiate.py           # 使用 create_agent(), hub 模式支持 --initiator
│       ├── poll.py               # 使用 create_agent()
│       ├── respond.py            # 支持 Hub 的配置加载
│       ├── status.py
│       └── setup_config.py       # Hub 向导 + Standalone 向导
├── config/
│   ├── agent_a.yaml
│   ├── agent_b.yaml
│   └── agent_c.yaml
├── docs/
│   ├── VISION_ARTICLE.md         # 概念文章：异步 AI 时间范式
│   ├── PHASE2_ROOM_ARCHITECTURE.md  # Phase 2 设计文档
│   ├── STYLE_GUIDE.md
│   └── MAINTENANCE_CHECKLIST.md
└── references/
    └── config-example.yaml       # 两种模式的配置示例
```

根目录下的 `email_client.py`、`negotiator.py`、`protocol.py` 是旧版备份 —— 请使用 `lib/` 下的版本。

-----

## 三、配置文件格式

自动检测：有 `members:` 字段 → Hub 模式；有 `owner:` 字段 → Standalone 模式。

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
    email: "alice@gmail.com"     # 白名单身份 + 通知
    role: "admin"                # 管理员可以管理配置；成员只能使用
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

contacts:                        # 外部 (Hub 之外)
  Dave:
    human_email: "dave@gmail.com"
    has_agent: false

# 邀请码自助注册系统
invite_codes:
  - code: "welcome-2026"
    expires: "2026-12-31"
    max_uses: 3
    used: 0              # 由 Hub 自动更新，请勿手动编辑

trusted_users: {}        # 当用户通过邀请码注册时自动填充

llm:
  provider: "local"              # Ollama (免费，常驻机器)
  model: "llama3"
  base_url: "http://localhost:11434/v1"
```

### Standalone 模式配置 (向后兼容)

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
  model: "claude-3-5-sonnet-20240620"
  api_key_env: "ANTHROPIC_API_KEY"
```

-----

## 四、协议格式 (AIMP/0.1)

### 4.1 邮件规范

- **Subject**: `[AIMP:<session_id>] v<version> <简要描述>`
  - 示例: `[AIMP:meeting-001] v1 Q1 复盘会议时间协商`
- **Body**: 纯文本，人类可读的摘要
- **JSON 附件**: `protocol.json`，结构化协议数据
- **References Header**: 引用线程中前一封邮件的 Message-ID

### 4.2 protocol.json 结构

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

### 4.3 Action 类型

|action    |含义    |触发条件         |
|----------|------|-------------|
|`propose` |发起提案  |人类请求会议      |
|`accept`  |接受提案|所有项目都匹配偏好    |
|`counter` |反向提案   |部分匹配，提出替代方案  |
|`confirm` |最终确认  |所有参与者都接受|
|`escalate`|升级到人类  |无法自动决策 (超出偏好范围) |

### 4.4 共识规则

- 每个议题 (时间/地点) 独立投票
- 如果一个选项收到所有参与者的投票 → 议题已解决
- 所有议题均已解决 → 发送 `confirm`
- 超过 5 轮未达成共识 → `escalate` 给所有人类

-----

## 五、核心模块说明

### 5.1 lib/session_store.py — SQLite 持久化

两张表：`sessions`（序列化的 `AIMPSession`）和 `sent_messages`（邮件线索）。

```python
class SessionStore:
    def save(self, session: AIMPSession)
    def load(self, session_id: str) -> AIMPSession
    def load_active(self) -> list[AIMPSession]      # status == "negotiating"
    def delete(self, session_id: str)
    def save_message_id(self, session_id, msg_id)
    def load_message_ids(self, session_id) -> list[str]
```

### 5.2 lib/transport.py — 传输层抽象

Agent 面向 `BaseTransport` 编程，`EmailTransport` 是具体实现（委托给 `EmailClient`）。未来只需实现同一 ABC 即可接入 Telegram、Slack 等传输介质。

```python
class BaseTransport(ABC):
    def my_address(self) -> str                          # 本传输层地址（如邮件地址）
    def fetch_aimp_emails(self, since_minutes=60)        # Phase 1 收件
    def fetch_all_unread_emails(self, since_minutes=60)  # Hub：全部未读
    def fetch_phase2_emails(self, since_minutes=60)      # Phase 2 Room 收件
    def send_aimp_email(self, to, session_id, version, subject_suffix,
                        body_text, protocol_json, references=None, in_reply_to=None) -> str
    def send_cfp_email(self, to, room_id, topic, deadline_iso,
                       initial_proposal, resolution_rules, body_text, references=None) -> str
    def send_human_email(self, to, subject, body)

class EmailTransport(BaseTransport):
    """将每个调用委托给 EmailClient。可直接替换为其他传输实现。"""
```

### 5.3 lib/email_client.py — IMAP/SMTP 封装（内部）

`EmailClient` 不再被 Agent 直接使用，由 `EmailTransport` 包装。辅助函数仍可从此处导入：

```python
def is_aimp_email(parsed: ParsedEmail) -> bool
def extract_protocol_json(parsed: ParsedEmail) -> Optional[dict]
```

### 5.4 lib/protocol.py — 会话状态管理

```python
class AIMPSession:
    session_id: str
    topic: str
    participants: list[str]
    initiator: str
    proposals: dict[str, ProposalItem]   # {"time": ..., "location": ...}
    status: str   # "negotiating" | "confirmed" | "escalated"

    def apply_vote(self, voter, item, choice)
    def ensure_participant(self, email: str)   # 动态添加新投票方（如发起者后加入）
    def add_option(self, item, option)
    def check_consensus(self) -> dict          # {item: resolved_value | None}
    def is_fully_resolved(self) -> bool
    def bump_version(self)
    def to_json(self) / from_json(cls, data)
```

**关键：`ensure_participant(email)`** 会动态将新参与者加入所有已有提案的投票槽，使发起者可以在会议创建后再加入投票。

### 5.5 lib/negotiator.py — LLM 决策引擎

```python
class Negotiator:
    def decide(self, session: AIMPSession) -> tuple[str, dict]
        # 返回：("accept"|"counter"|"escalate", {votes, new_options, reason})

    def parse_human_reply(self, reply_body, session) -> tuple[str, dict]
        # 自然语言理解：自由文本 → 结构化投票

    def generate_human_readable_summary(self, session, action) -> str
    def generate_human_email_body(self, session) -> str    # 给非 Agent 接收者用

class HubNegotiator:
    def find_optimal_slot(self, topic, member_prefs: dict) -> dict
        # 在收集到所有成员的真实投票回复后调用，汇总求共识
        # member_prefs 应来自本次会议的实际回复，不是 config 静态偏好
        # consensus=true: 填入 time+location；false: 返回 options 列表
    def generate_member_notify_body(self, topic, result, ...) -> str
```

### 5.6 lib/protocol.py — Phase 2 数据结构

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

### 5.7 agent.py — AIMPAgent（Standalone 模式）

```python
class AIMPAgent:
    def __init__(self, config_path, notify_mode="email", db_path=None)
        # notify_mode: "email"（通知主人）| "stdout"（输出 JSON 给 OpenClaw）

    def run(self, poll_interval=30)
    def poll(self) -> list[dict]               # 一次轮询：收邮件 → 逐条处理
    def handle_email(self, parsed)             # 路由到 _handle_aimp_email 或 _handle_human_email
    def initiate_meeting(self, topic, participant_names) -> str  # 返回 session_id

# 关键属性：self.transport (EmailTransport) — 所有 I/O 通过此接口
```

会话状态通过 `SessionStore` 持久化到 SQLite（不是内存字典）。

### 5.8 hub_agent.py — AIMPHubAgent（Hub 模式）

```python
class AIMPHubAgent(AIMPAgent):

    # 身份识别与会议发起：
    def identify_sender(from_email) -> Optional[str]   # email → member_id（白名单检查）
    def initiate_meeting(topic, participant_names, initiator_member_id) -> str
        # 识别内部/外部参与者
        # 纯内部 → _initiate_internal_meeting()（LLM 上帝视角，不发邮件）
        # 有外部 → _initiate_hybrid_meeting()（合并偏好 → AIMP 邮件）

    # Stage-2 处理器 — 核心指令处理：
    def handle_member_command(from_email, body) -> list[dict]
        # 完整处理流程请参见「八、Stage-2 指令处理流程」
        # 包含：LLM解析 -> 完整性校验 -> 联系人解析 -> 临时偏好存储 -> 派发 initiate_meeting -> 发起者投票邀请

    # Stage-2 helper 方法：
    def _parse_member_request(member_name, body) -> dict
    def _find_participant_contact(name) -> Optional[dict]   # 按序查：members → contacts → 裸邮箱
    def _send_initiator_vote_request(from_email, member_name, session)
        # ensure_participant(from_email) → 发 [AIMP:session_id] 投票邀请邮件
    def _reply_unknown_sender(from_email)
        # 模板回复：「请先通过 [AIMP-INVITE:code] 注册」

    # 邀请码自助注册：
    def _check_invite_email(parsed) -> Optional[list[dict]]   # 检测主题中的 [AIMP-INVITE:code]
    def _handle_invite_request(from_email, sender_name, code) -> list[dict]
        # 流程详情请参见「七、邀请码注册流程」
        # 校验 → 注册 → 发欢迎邮件
    def _validate_invite_code(code) -> Optional[dict]          # 检查过期时间 + 使用次数
    def _register_trusted_user(email, name, via_code)          # 加入 members + _email_to_member
    def _consume_invite_code(code)
    def _persist_config()   # 将 invite_codes + trusted_users 写回 config.yaml

    # hub-card（嵌入欢迎邮件正文的 JSON 块，供 AI Agent 读取）：
    # 结构详情请参见「七、邀请码注册流程」中的 hub-card 部分

def create_agent(config_path, **kwargs) -> AIMPAgent | AIMPHubAgent
    # 工厂函数：config 有 "members:" → AIMPHubAgent；有 "owner:" → AIMPAgent
```

-----

## 六、降级兼容设计

### 6.1 判断发件方（Agent vs 人类）

```python
def is_aimp_email(email) -> bool:
    return "[AIMP:" in email.subject and any(a["filename"] == "protocol.json" for a in email.attachments)
```

收到回复时：有 `[AIMP:]` 前缀 + `protocol.json` 附件 → Agent 模式；否则 → 人类模式。

### 6.2 给人类发的邀请邮件模板

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

### 6.3 解析人类回复

LLM 自然语言理解将自由文本转为结构化投票，再正常 apply 到 session 中。

-----

## 七、邀请码注册流程

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
    "capabilities": ["schedule_meeting"],
    "registered_members": ["Alice", "Bob"],
    "usage": {
      "schedule_meeting": {
        "how": "发邮件给 Hub，用自然语言描述需求。",
        "required_fields": ["topic", "participants"],
        "optional_fields": ["preferred_times", "preferred_locations"],
        "example": "正文：帮我约 Bob 和 Carol 本周五下午讨论季度计划，线上或北京办公室均可"
      }
    },
    "session_threading": {
      "pattern": "[AIMP:{session_id}]",
      "note": "回复投票邀请时，保持主题中的 [AIMP:xxx] 标记不变。"
    }
  }
}
```

-----

## 八、Stage-2 指令处理流程

成员发来约会邮件后，`handle_member_command` 的完整处理链：

```
收到邮件
    │
    ▼
identify_sender()  ──  陌生人 → _reply_unknown_sender()（注册引导）
    │
    ▼（已知成员）
_parse_member_request()  ──  LLM 解析
    │
    ├── action=unclear → 回复「没明白，请说明主题/参与者/时间」
    │
    ├── missing=[topic|participants] → 回邮件「请补充：xxx」
    │
    ├── 联系人找不到邮箱 → 回邮件「请提供 xxx 的邮箱」
    │
    └── 所有信息齐全
            │
            ▼
      存储发起者临时偏好
            │
            ▼
      initiate_meeting()  ──  发出所有参与者的投票邀请
            │
            ▼
      _send_initiator_vote_request()  ──  给发起者发投票邀请
      （ensure_participant → [AIMP:session_id] 主题邮件）
```

-----

## 九、演示脚本 run_demo.py

启动 3 个 Standalone Agent 线程，Agent-A 自动发起会议提议。

```
用法：
  1. 填写 config/agent_a.yaml, agent_b.yaml, agent_c.yaml
  2. 设置环境变量 ANTHROPIC_API_KEY
  3. python run_demo.py
```

-----

## 十、准备清单

1. **1 个邮箱账号**（Hub 模式）或 **3 个**（Standalone 演示），支持 IMAP，开启应用专用密码
2. **LLM API Key**（Anthropic 或 OpenAI）或本地 Ollama
3. **Python 3.10+**
4. **依赖**：`pip install -r requirements.txt`（pyyaml、anthropic/openai；imaplib/smtplib 是标准库）

-----

## 十一、Phase 2 — "The Room" (✅ 已实现)

Phase 2 将 AIMP 从调度（时间/地点）扩展为**内容协商**（文档、预算、提案），在带截止日期的异步窗口内完成。它作为现有 Hub 的扩展实现——无需单独的 Agent。

### 核心概念

| | Phase 1 | Phase 2 |
|---|---|---|
| 协商对象 | 时间段 + 地点 | 任意内容（文档、预算、决策） |
| 收敛触发条件 | 全体一致投票 | 所有人发 ACCEPT，或截止日期到达 |
| Hub 角色 | 调度员 | 房间管理员 |
| 输出 | 确认的会议时间 | 会议纪要 |
| 状态机 | negotiating → confirmed | open → locked → finalized |

### 架构决策：Hub 扩展 (非独立 Agent)

Phase 2 逻辑通过委托给 `RoomNegotiator` 驻留在同一个 Hub 邮箱账号中。Hub 的 `poll()` 会优先收取 `[AIMP:Room:]` 邮件（在 Phase 1 处理之前），然后检查过期的截止日期。

### 如何使用

**成员发起 Room** (发邮件给 Hub):
```
Subject: (任意)
Body: 帮我发起一个协商室，和 Bob、Carol 讨论 Q3 预算方案，截止 3 天后。
      初始提案：研发$60k，市场$25k，运营$15k
```

**参与者回复动作**:
- `ACCEPT` — 同意当前提案
- `AMEND + text` — 提出修改意见
- `PROPOSE + text` — 提交新草案
- `REJECT + reason` — 否决提案

**当最终确认时** (所有 ACCEPT 或截止)，Hub 发送会议纪要给所有参与者。参与者可以回复 `CONFIRM` 或 `REJECT <reason>` 进入否决流程。

### 关键文件

| 文件 | 作用 |
|------|------|
| `lib/protocol.py` | `Artifact` + `AIMPRoom` 数据类 |
| `lib/session_store.py` | `rooms` 表: `save_room`/`load_room`/`load_open_rooms` |
| `lib/email_client.py` | `send_cfp_email`, `fetch_phase2_emails`, Phase 2 邮件头 |
| `room_prompts.py` | LLM 模板: parse_amendment, aggregate, generate_minutes |
| `hub_agent.py` | `RoomNegotiator` 类 + 所有 room 生命周期方法 |
| `run_room_demo.py` | 集成演示 (内存模拟，无真实邮件/LLM) |

### 运行演示

```bash
python run_room_demo.py
```

-----

## 十二、推广策略

1. **先自己用**。你的 Hub 跑着，给所有人发普通邮件约会议。对方什么都不需要安装。
2. **有人好奇时**，发他 README 链接，5 分钟能跑起来。
3. **降级兼容是生命线**——永远不要求对方也装了 Agent 才能用。
4. **Demo GIF > 万字文档**。录一个 30 秒演示，放在 README 顶部。

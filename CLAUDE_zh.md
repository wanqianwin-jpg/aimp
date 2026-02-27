# AIMP — 架构与实现指南（中文版）

> **目标**：AI Agent 通过邮件协商会议时间。支持 Hub 模式（一个 Agent 服务多人）和 Standalone 模式（每人一个 Agent）。
> **约束**：不做哈希链、不做 DID、不做权限预算、不做签名、不做支付。只做「能跑通」的最小闭环。

-----

## 当前状态

| 阶段 | 状态 | 说明 |
|------|------|------|
| Phase 1 | ✅ 已完成 | 基于邮件的会议时间/地点协商 |
| Phase 2 | 🗂️ 规划中 | "The Room" — 带截止日期的异步内容协商 |

Phase 1 已完整实现于 `lib/` + `agent.py` + `hub_agent.py`，所有模块可运行。

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
新用户 ──[AIMP-INVITE:邀请码]──→ ┐
成员   ──「帮我约 Bob 开会」──→  ├─ HubAgent（1个邮箱）──邮件──→ 外部联系人 / 外部 Agent
                                └─（内部成员：无邮件，直接 LLM 调度）
                                           ↓
                                   通知所有参与者
```

Hub 是一个**单点部署的 Skill**——用户只需通过邮件交互，自己不需要部署任何 Agent。

**完整邮件生命周期：**

| 阶段 | 操作方 | 动作 | 邮件主题模式 |
|------|--------|------|-------------|
| 0. 准备 | 管理员 | 在 config.yaml 创建邀请码 | — |
| 1. 注册 | 新用户 | 发邮件给 Hub，主题含邀请码 | `[AIMP-INVITE:邀请码]` |
| 1. 回复 | Hub | 校验邀请码，注册用户，发欢迎邮件 + hub-card JSON | — |
| 2. 发起请求 | 成员 | 自然语言约会邮件 | （任意） |
| 2. 信息不全 | Hub | 回邮件要求补充（主题/参与者/时间偏好） | — |
| 3. 发出邀请 | Hub | LLM 解析 → 自动调用 `initiate_meeting()` | `[AIMP:session_id]` |
| 3. 发起者投票 | Hub | 给发起者发投票邀请（他也是投票方） | `[AIMP:session_id]` |
| 4. 投票 | 所有人 | 回邮件提交时间/地点偏好 | `[AIMP:session_id]` |
| 5. 确认 | Hub | 达成共识，通知所有参与者 | — |

**Hub 集中协调（非「上帝视角」）：**
config 中的 `preferences` 是历史偏好记录，**不代表本次会议的真实可用时间**。
Hub 内部会议的正确流程：Hub 并行给所有成员发「请告知可用时间」邮件，收集每人对本次会议的真实回复，再汇总求共识。没有预生成选项，没有假设。

-----

## 二、文件结构

```
aimp/
├── lib/                          # 核心库（正式实现）
│   ├── __init__.py
│   ├── email_client.py           # IMAP/SMTP 封装，支持 OAuth2 & SSL
│   ├── protocol.py               # AIMP/0.1 协议数据模型（AIMPSession、ProposalItem）
│   ├── negotiator.py             # LLM 决策引擎（Negotiator、HubNegotiator）
│   ├── session_store.py          # SQLite 持久化（sessions + message_ids 两张表）
│   └── output.py                 # JSON stdout 事件输出（供 OpenClaw 解析）
├── agent.py                      # Standalone Agent（AIMPAgent）
├── hub_agent.py                  # Hub Agent（AIMPHubAgent 继承 AIMPAgent）
│                                 #   - 邮箱白名单身份识别
│                                 #   - 内部成员上帝视角调度
│                                 #   - 邀请码自助注册系统
│                                 #   - Stage-2 LLM 请求解析与派发
│                                 #   - create_agent() 工厂函数：自动检测模式
├── run_demo.py                   # 3-Agent Standalone 演示脚本
├── openclaw-skill/
│   ├── SKILL.md                  # OpenClaw 操作手册（Hub + Standalone）
│   └── scripts/
│       ├── initiate.py           # 使用 create_agent()，Hub 模式支持 --initiator
│       ├── poll.py               # 使用 create_agent()
│       ├── respond.py            # Hub 感知的配置加载
│       ├── status.py
│       └── setup_config.py       # Hub 向导 + Standalone 向导
├── config/
│   ├── agent_a.yaml
│   ├── agent_b.yaml
│   └── agent_c.yaml
├── docs/
│   ├── VISION_ARTICLE.md         # 概念文章：异步 AI 时代范式
│   ├── PHASE2_ROOM_ARCHITECTURE.md  # Phase 2 设计文档
│   ├── STYLE_GUIDE.md
│   └── MAINTENANCE_CHECKLIST.md
└── openclaw-skill/references/
    └── config-example.yaml       # 两种模式的配置示例
```

根目录下的 `email_client.py`、`negotiator.py`、`protocol.py` 是旧版备份——请使用 `lib/` 下的版本。

-----

## 三、配置文件格式

自动检测：有 `members:` 字段 → Hub 模式；有 `owner:` 字段 → Standalone 模式。

### Hub 模式配置

```yaml
mode: hub
hub:
  name: "家庭 Hub"
  email: "family-hub@gmail.com"
  imap_server: "imap.gmail.com"
  smtp_server: "smtp.gmail.com"
  imap_port: 993
  smtp_port: 465
  password: "$HUB_PASSWORD"

members:
  alice:
    name: "Alice"
    email: "alice@gmail.com"     # 白名单身份认证 + 接收通知
    role: "admin"                # admin 可管理配置；member 只能使用
    preferences:
      preferred_times: ["工作日上午"]
      blocked_times: ["周五下午"]
      preferred_locations: ["Zoom"]
  bob:
    name: "Bob"
    email: "bob@gmail.com"
    role: "member"
    preferences:
      preferred_times: ["下午 14:00-17:00"]
      preferred_locations: ["腾讯会议"]

contacts:                        # 外部联系人（Hub 外部）
  Dave:
    human_email: "dave@gmail.com"
    has_agent: false

# 邀请码自助注册系统
invite_codes:
  - code: "welcome-2026"
    expires: "2026-12-31"
    max_uses: 3
    used: 0              # Hub 自动更新，请勿手动修改

trusted_users: {}        # 用户通过邀请码注册后自动填入

llm:
  provider: "anthropic"
  model: "claude-sonnet-4-6"
  api_key_env: "ANTHROPIC_API_KEY"
```

### Standalone 模式配置（向后兼容）

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
  preferred_times: ["工作日上午 9:00-12:00"]
  blocked_times: ["周五下午"]
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

## 四、协议格式（AIMP/0.1）

### 4.1 邮件规范

- **Subject**: `[AIMP:<session_id>] v<version> <简要描述>`
  - 例：`[AIMP:meeting-001] v1 Q1 复盘会时间协商`
- **邮件正文**：纯文本，人类可读摘要
- **JSON 附件**：`protocol.json`，结构化协议数据
- **References 头**：引用线程中前一封邮件的 Message-ID

### 4.2 特殊邮件主题模式

| 模式 | 含义 |
|------|------|
| `[AIMP:xxx]` | AIMP 协议邮件（会议协商） |
| `[AIMP-INVITE:code]` | 邀请码注册申请（不被协议收件人过滤） |

### 4.3 protocol.json 结构

```json
{
  "protocol": "AIMP/0.1",
  "session_id": "meeting-001",
  "version": 3,
  "from": "alice-agent@example.com",
  "action": "propose",
  "participants": ["alice-agent@...", "bob-agent@..."],
  "topic": "Q1 复盘会",
  "proposals": {
    "time": {
      "options": ["2026-03-01T10:00", "2026-03-02T14:00"],
      "votes": {"alice-agent@...": "2026-03-01T10:00", "bob-agent@...": null}
    },
    "location": {
      "options": ["Zoom", "线下会议室"],
      "votes": {"alice-agent@...": "Zoom", "bob-agent@...": null}
    }
  },
  "status": "negotiating"
}
```

### 4.4 action 类型

| action | 含义 | 触发条件 |
|--------|------|---------|
| `propose` | 发起提议 | 人类要求约会议 |
| `accept` | 接受当前提议 | 所有项目都匹配偏好 |
| `counter` | 反提议 | 部分匹配，提出替代方案 |
| `confirm` | 最终确认 | 所有参与者都 accept |
| `escalate` | 交给人类 | 超出偏好范围，无法自动决策 |

### 4.5 共识规则

- 每个议题（time/location）独立投票
- 某选项获得所有参与者投票 → 该议题 resolved
- 所有议题 resolved → 发 `confirm`
- 超过 5 轮未达成 → `escalate` 给所有人类

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

### 5.2 lib/email_client.py — IMAP/SMTP 封装

```python
@dataclass
class ParsedEmail:
    message_id: str
    subject: str
    sender: str
    recipients: list[str]
    body: str
    attachments: list[dict]
    references: list[str]
    session_id: Optional[str] = None    # 从 [AIMP:xxx] 提取
    raw_date: Optional[str] = None
    sender_name: Optional[str] = None   # From 头中的显示名（如 "Alice Wang"）

class EmailClient:
    def fetch_aimp_emails(self, since_minutes=60) -> list[ParsedEmail]
        # IMAP SEARCH: UNSEEN SUBJECT "[AIMP:"，解析后标记已读

    def fetch_all_unread_emails(self, since_minutes=60) -> list[ParsedEmail]
        # 获取所有未读邮件（Hub poll 使用，用于收取成员指令）

    def send_aimp_email(self, to, session_id, version, subject_suffix,
                        body_text, protocol_json, references=None) -> str
        # 多部分邮件：text/plain 正文 + protocol.json 附件，返回 Message-ID

    def send_human_email(self, to, subject, body)
        # 纯文本邮件，用于降级模式或通知

def is_aimp_email(parsed: ParsedEmail) -> bool
def extract_protocol_json(parsed: ParsedEmail) -> Optional[dict]
```

### 5.3 lib/protocol.py — 会话状态管理

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

### 5.4 lib/negotiator.py — LLM 决策引擎

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

### 5.5 agent.py — AIMPAgent（Standalone 模式）

```python
class AIMPAgent:
    def __init__(self, config_path, notify_mode="email", db_path=None)
        # notify_mode: "email"（通知主人）| "stdout"（输出 JSON 给 OpenClaw）

    def run(self, poll_interval=30)
    def poll(self) -> list[dict]               # 一次轮询：收邮件 → 逐条处理
    def handle_email(self, parsed)             # 路由到 _handle_aimp_email 或 _handle_human_email
    def initiate_meeting(self, topic, participant_names) -> str  # 返回 session_id
```

会话状态通过 `SessionStore` 持久化到 SQLite（不是内存字典）。

### 5.6 hub_agent.py — AIMPHubAgent（Hub 模式）

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
        # 1. LLM 解析 → {action, topic, participants, initiator_times, initiator_locs, missing}
        # 2. 完整性校验 → 缺字段则回邮件要求补充
        # 3. 联系人解析 → 找不到邮箱则回邮件要求提供
        # 4. 将发起者声明的可用时间存为临时偏好
        # 5. 自动派发 initiate_meeting()
        # 6. 给发起者发投票邀请（他也是投票方之一）

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
        # 校验 → 注册 → 发欢迎邮件（含 hub-card JSON 块）
    def _validate_invite_code(code) -> Optional[dict]          # 检查过期时间 + 使用次数
    def _register_trusted_user(email, name, via_code)          # 加入 members + _email_to_member
    def _consume_invite_code(code)
    def _persist_config()   # 将 invite_codes + trusted_users 写回 config.yaml

    # hub-card（嵌入欢迎邮件正文的 JSON 块，供 AI Agent 读取）：
    # {"aimp_hub": {"name", "email", "protocol", "capabilities",
    #               "registered_members", "usage": {"schedule_meeting": {...}},
    #               "session_threading": {"pattern": "[AIMP:{session_id}]"}}}

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

## 十一、Phase 2 路线图 — "The Room"

Phase 2 将 AIMP 从调度（时间/地点）扩展为**内容协商**（文档、预算、提案），在带截止日期的异步窗口内完成。

| | Phase 1 | Phase 2 |
|---|---|---|
| 协商对象 | 时间段 + 地点 | 任意内容（文档、预算、决策） |
| 收敛触发条件 | 全体一致投票 | 所有人发 ACCEPT，或截止日期到达 |
| Hub 角色 | 调度员 | 房间管理员 |
| 输出 | 确认的会议时间 | 会议纪要 |

**协议扩展：**
- `AIMPRoom` 继承 `AIMPSession`：新增 `deadline: float`、`artifacts: dict`、`status: open→locked→finalized`
- 新 action 类型：`PROPOSE`、`AMEND`、`ACCEPT`、`REJECT`
- 新邮件头：`X-AIMP-Phase: 2`、`X-AIMP-Deadline: <ISO8601>`

-----

## 十二、推广策略

1. **先自己用**。你的 Hub 跑着，给所有人发普通邮件约会议。对方什么都不需要安装。
2. **有人好奇时**，发他 README 链接，5 分钟能跑起来。
3. **降级兼容是生命线**——永远不要求对方也装了 Agent 才能用。
4. **Demo GIF > 万字文档**。录一个 30 秒演示，放在 README 顶部。

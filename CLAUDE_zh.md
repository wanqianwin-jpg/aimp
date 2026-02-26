# AIMP 架构与实现指南

> **目标**：3 个 AI Agent 分别代表 3 个人，通过邮件协商一次会议，最终达成共识。
> **约束**：不做哈希链、不做 DID、不做权限预算、不做签名、不做支付。只做”能跑通”的最小闭环。

-----

## 一、整体架构

```
Alice (人) ──偏好配置──→ Agent-A ──邮件──→ ┐
Bob   (人) ──偏好配置──→ Agent-B ──邮件──→ ├─ 共享邮件线程
Carol (人) ──偏好配置──→ Agent-C ──邮件──→ ┘
                 ↑                           │
                 └── 结果通知（邮件/终端） ←──┘
```

**核心流程**：

1. Alice 告诉自己的 Agent：“帮我约 Bob 和 Carol 开个 Q1 复盘会”
2. Agent-A 发起邮件线程，Agent-B/C 自动回复
3. 多轮协商后达成共识
4. 各 Agent 通知各自主人最终结果

**关键设计：降级兼容**

对方如果没装 Agent，就给对方的人类邮箱发自然语言邮件，用 LLM 解析人类的自由文本回复。这样从第一天起就单人可用。

-----

## 二、文件结构

```
aimp/
├── agent.py              # Agent 主循环
├── email_client.py       # IMAP/SMTP 收发封装
├── protocol.py           # AIMP 协议解析/生成
├── negotiator.py         # 协商决策逻辑（调 LLM）
├── config/
│   ├── agent_a.yaml      # Agent-A 配置（邮箱、偏好、通讯录）
│   ├── agent_b.yaml
│   └── agent_c.yaml
├── run_demo.py           # 一键启动 3 个 Agent 的演示脚本
└── README.md
```

-----

## 三、配置文件格式

每个 Agent 一个 YAML 配置：

```yaml
# config/agent_a.yaml
agent:
  name: "Alice's Assistant"
  email: "alice-agent@example.com"
  imap_server: "imap.example.com"
  smtp_server: "smtp.example.com"
  password: "xxx"  # 或环境变量引用

owner:
  name: "Alice"
  email: "alice@gmail.com"  # 人类邮箱，用于通知

preferences:
  preferred_times:
    - "weekday mornings 9:00-12:00"
    - "2026-03-01"
  blocked_times:
    - "2026-03-03"
    - "Friday afternoons"
  preferred_locations:
    - "Zoom"
    - "腾讯会议"
  auto_accept: true  # 完全匹配偏好时自动接受

contacts:
  Bob:
    agent_email: "bob-agent@example.com"    # 如果有 Agent
    human_email: "bob@gmail.com"            # 没有 Agent 时降级
    has_agent: true
  Carol:
    agent_email: "carol-agent@example.com"
    human_email: "carol@gmail.com"
    has_agent: true

llm:
  provider: "anthropic"   # 或 "openai"
  model: "claude-sonnet-4-5-20250514"
  api_key_env: "ANTHROPIC_API_KEY"  # 从环境变量读取
```

-----

## 四、协议格式（AIMP/0.1）

### 4.1 邮件规范

- **Subject**: `[AIMP:<session_id>] v<version> <简要描述>`
  - 例：`[AIMP:meeting-001] v1 Q1复盘会时间协商`
- **邮件正文**：纯文本，人类可读的摘要
- **JSON 附件**：`protocol.json`，结构化协议数据
- **References 头**：引用线程中前一封邮件的 Message-ID

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
  "topic": "Q1 复盘会",
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
      "options": ["Zoom", "Office 3F", "腾讯会议"],
      "votes": {
        "alice-agent@example.com": "Zoom",
        "bob-agent@example.com": null,
        "carol-agent@example.com": null
      }
    }
  },
  "status": "negotiating",
  "history": [
    {"version": 1, "from": "alice-agent@example.com", "action": "propose", "summary": "发起会议提议"},
    {"version": 2, "from": "bob-agent@example.com", "action": "counter", "summary": "建议改为线下"},
    {"version": 3, "from": "carol-agent@example.com", "action": "accept", "summary": "同意时间A和线下"}
  ]
}
```

### 4.3 action 类型

|action    |含义    |触发条件         |
|----------|------|-------------|
|`propose` |发起提议  |人类要求约会议      |
|`accept`  |接受当前提议|所有项目都匹配偏好    |
|`counter` |反提议   |部分匹配，提出替代方案  |
|`confirm` |最终确认  |所有参与者都 accept|
|`escalate`|交给人类  |超出偏好范围无法自动决策 |

### 4.4 共识达成规则

- 每个议题（time/location）独立投票
- 某选项获得所有参与者投票 → 该议题 resolved
- 所有议题 resolved → 发 `confirm`
- 超过 5 轮未达成 → `escalate` 给所有人类

-----

## 五、核心模块实现说明

### 5.1 email_client.py

封装 IMAP/SMTP，提供以下方法：

```python
class EmailClient:
    def __init__(self, imap_server, smtp_server, email, password): ...
    
    def fetch_aimp_emails(self, since_minutes=5) -> list[Email]:
        """搜索 Subject 含 [AIMP: 的未读邮件，返回解析后的列表"""
        # IMAP SEARCH: UNSEEN SUBJECT "[AIMP:"
        # 解析邮件正文和 JSON 附件
        ...
    
    def send_aimp_email(self, to: list[str], session_id: str, 
                         version: int, body_text: str, 
                         protocol_json: dict, 
                         references: list[str] = None): 
        """发送 AIMP 协议邮件"""
        # 构造 multipart 邮件：text/plain + application/json 附件
        # 设置 Subject: [AIMP:{session_id}] v{version}
        # 设置 References 头
        ...
    
    def send_human_email(self, to: str, subject: str, body: str):
        """给人类发普通邮件（降级模式或通知）"""
        ...
```

### 5.2 protocol.py

协议数据的解析和状态管理：

```python
class AIMPSession:
    def __init__(self, session_id: str, topic: str, participants: list[str]): ...
    
    @classmethod
    def from_json(cls, data: dict) -> "AIMPSession": 
        """从 protocol.json 解析"""
        ...
    
    def to_json(self) -> dict:
        """导出为 protocol.json"""
        ...
    
    def apply_vote(self, voter: str, item: str, choice: str):
        """记录投票"""
        ...
    
    def add_option(self, item: str, option: str):
        """添加新选项（counter 时用）"""
        ...
    
    def check_consensus(self) -> dict:
        """检查各议题是否达成共识，返回 {item: resolved_value | None}"""
        ...
    
    def is_fully_resolved(self) -> bool:
        """所有议题是否都已达成共识"""
        ...
    
    @property
    def version(self) -> int: ...
    
    def next_version(self) -> int:
        return self.version + 1
```

### 5.3 negotiator.py

调用 LLM 做决策，这是核心智能部分：

```python
class Negotiator:
    def __init__(self, preferences: dict, llm_client): ...
    
    def decide(self, session: AIMPSession) -> tuple[str, dict]:
        """
        输入：当前会话状态
        输出：(action, details)
        
        决策逻辑：
        1. 把 session 状态 + 自己的偏好 发给 LLM
        2. 让 LLM 判断：
           - 提议完全匹配偏好 → ("accept", {votes: {...}})
           - 部分匹配 → ("counter", {votes: {...}, new_options: {...}})
           - 完全无法匹配 → ("escalate", {reason: "..."})
        3. 返回结果
        """
        ...
    
    def parse_human_reply(self, email_body: str, session: AIMPSession) -> tuple[str, dict]:
        """
        用 LLM 解析人类的自由文本回复，提取投票意向。
        用于降级模式（对方没有 Agent）。
        """
        ...
    
    def generate_human_readable_summary(self, session: AIMPSession) -> str:
        """生成邮件正文的人类可读摘要"""
        ...
```

**给 LLM 的 Prompt 模板（关键）：**

```
你是一个会议协调助手。你的主人是 {owner_name}。

主人的偏好：
- 偏好时间：{preferred_times}
- 屏蔽时间：{blocked_times}
- 偏好地点：{preferred_locations}

当前协商状态：
{session_json}

请判断当前提议是否匹配主人偏好，返回 JSON：
{
  "action": "accept" | "counter" | "escalate",
  "votes": {"time": "选择的时间或null", "location": "选择的地点或null"},
  "new_options": {"time": ["新提议时间"], "location": ["新提议地点"]},  // counter时才有
  "reason": "简短说明"
}
```

### 5.4 agent.py — 主循环

```python
class AIMPAgent:
    def __init__(self, config_path: str):
        self.config = load_yaml(config_path)
        self.email = EmailClient(...)
        self.negotiator = Negotiator(self.config["preferences"], llm)
        self.sessions = {}  # session_id -> AIMPSession
    
    def run(self, poll_interval=30):
        """主循环"""
        while True:
            self.poll()
            time.sleep(poll_interval)
    
    def poll(self):
        emails = self.email.fetch_aimp_emails()
        for email in emails:
            self.handle_email(email)
    
    def handle_email(self, email):
        # 1. 解析 protocol.json
        session_data = extract_protocol_json(email)
        
        if session_data:
            # 对方是 Agent，走协议模式
            session = AIMPSession.from_json(session_data)
        else:
            # 对方是人类，走降级模式
            action, details = self.negotiator.parse_human_reply(
                email.body, self.sessions.get(email.session_id)
            )
            session = self.sessions[email.session_id]
            session.apply_vote(email.sender, ...)
        
        self.sessions[session.session_id] = session
        
        # 2. 检查是否已达成共识
        if session.is_fully_resolved():
            self.send_confirm(session)
            self.notify_owner(session)
            return
        
        # 3. 决策
        action, details = self.negotiator.decide(session)
        
        if action == "escalate":
            self.notify_owner_for_decision(session, details["reason"])
        else:
            # accept 或 counter
            session.apply_vote(self.config["agent"]["email"], ...)
            if details.get("new_options"):
                for item, opts in details["new_options"].items():
                    for opt in opts:
                        session.add_option(item, opt)
            self.send_reply(session, action)
    
    def initiate_meeting(self, topic: str, participant_names: list[str]):
        """人类发起会议请求时调用"""
        session_id = f"meeting-{int(time.time())}"
        participants = []
        for name in participant_names:
            contact = self.config["contacts"][name]
            if contact["has_agent"]:
                participants.append(contact["agent_email"])
            else:
                participants.append(contact["human_email"])
        
        session = AIMPSession(session_id, topic, participants)
        # 根据偏好生成初始提议
        # ...
        self.sessions[session_id] = session
        
        for participant in participants:
            contact = self.find_contact_by_email(participant)
            if contact and contact["has_agent"]:
                self.email.send_aimp_email(...)
            else:
                # 降级：给人类发自然语言邮件
                body = self.negotiator.generate_human_email(session)
                self.email.send_human_email(participant, f"会议邀请: {topic}", body)
    
    def send_reply(self, session, action):
        summary = self.negotiator.generate_human_readable_summary(session)
        self.email.send_aimp_email(
            to=session.participants,
            session_id=session.session_id,
            version=session.next_version(),
            body_text=summary,
            protocol_json=session.to_json()
        )
    
    def notify_owner(self, session):
        """通知主人最终结果"""
        consensus = session.check_consensus()
        body = f"会议已确定！\n主题：{session.topic}\n时间：{consensus['time']}\n地点：{consensus['location']}"
        self.email.send_human_email(self.config["owner"]["email"], f"会议确认: {session.topic}", body)
```

-----

## 六、降级兼容详细设计

### 6.1 判断对方是 Agent 还是人

```python
def is_aimp_email(email) -> bool:
    """检查邮件是否为 AIMP 协议邮件"""
    return (
        "[AIMP:" in email.subject
        and any(a.filename == "protocol.json" for a in email.attachments)
    )
```

收到回复时：有 `[AIMP:]` 前缀 + JSON 附件 → Agent 模式；否则 → 人类模式。

### 6.2 给人类发的邮件模板

```
Subject: 会议邀请：Q1 复盘会

Hi Bob，

Alice 想约你和 Carol 开个 Q1 复盘会。

以下时间你方便吗？
A. 3月1日 周一 上午10:00
B. 3月2日 周二 下午2:00

地点偏好？
1. Zoom
2. Office 3F
3. 腾讯会议

直接回复这封邮件告诉我就行，比如 "A和1" 或者 "周一上午可以，Zoom 开会"。

—— Alice's AI Assistant
```

### 6.3 解析人类回复

用 LLM 做自然语言理解：

```
用户回复了这封会议邀请邮件，内容是：
"{reply_body}"

原始选项：
时间：A. 3月1日 10:00, B. 3月2日 14:00
地点：1. Zoom, 2. Office 3F, 3. 腾讯会议

请提取用户的选择，返回 JSON：
{"time": "2026-03-01T10:00" 或 null, "location": "Zoom" 或 null, "unclear": "无法理解的部分"}
```

-----

## 七、演示脚本 run_demo.py

```python
"""
一键演示：3 个 Agent 协商会议

用法：
  1. 填写 config/agent_a.yaml, agent_b.yaml, agent_c.yaml
  2. 设置环境变量 ANTHROPIC_API_KEY
  3. python run_demo.py

流程：
  - 启动 3 个 Agent（3 个线程）
  - Agent-A 自动发起会议提议
  - 观察邮件交互过程
  - 达成共识后各 Agent 通知主人
"""
import threading
import time

def run_agent(config_path, initiate=None):
    agent = AIMPAgent(config_path)
    if initiate:
        topic, participants = initiate
        agent.initiate_meeting(topic, participants)
    agent.run(poll_interval=15)  # 演示用 15 秒轮询

# 启动 3 个 Agent
threads = [
    threading.Thread(target=run_agent, args=("config/agent_a.yaml",), 
                     kwargs={"initiate": ("Q1 复盘会", ["Bob", "Carol"])}),
    threading.Thread(target=run_agent, args=("config/agent_b.yaml",)),
    threading.Thread(target=run_agent, args=("config/agent_c.yaml",)),
]

for t in threads:
    t.daemon = True
    t.start()

print("3 个 Agent 已启动，观察邮箱中的协商过程...")
print("按 Ctrl+C 退出")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("演示结束")
```

-----

## 八、准备清单

施工前需要准备：

1.  **获取源码**：
    *   Gitee (推荐): `git clone https://gitee.com/wanqianwin/aimp.git`
    *   GitHub: `git clone https://github.com/wanqianwin-jpg/aimp.git`
2.  **3 个邮箱账号**（Gmail/Outlook/任何支持 IMAP 的），开启 IMAP 访问和应用专用密码
3.  **一个 LLM API Key**（Anthropic 或 OpenAI）
4.  **Python 3.10+**
5.  **依赖**：`imaplib`（标准库）、`smtplib`（标准库）、`pyyaml`、`anthropic`（或 `openai`）

-----

## 九、施工优先级

按以下顺序实现，每一步都可独立验证：

|步骤|模块                   |验证方式              |
|--|---------------------|------------------|
|1 |`email_client.py`    |能收发邮件             |
|2 |`protocol.py`        |能正确序列化/反序列化 JSON  |
|3 |`negotiator.py`      |给定偏好和提议，LLM 返回正确决策|
|4 |`agent.py` 单 Agent   |能收到邮件并自动回复        |
|5 |`run_demo.py` 3 Agent|完整协商流程跑通          |
|6 |降级模式                 |对人类发邮件，解析人类回复     |

-----

## 十、推广策略（写在方案里给自己看）

1. **第一步只需要你自己用**。你的 Agent 跑着，给所有人发普通邮件约会议。对方不需要装任何东西。
1. **当有人好奇时**，给他 README 链接，5 分钟能跑起来。
1. **降级兼容是生命线**——永远不要要求对方也装了 Agent 才能用。
1. **Demo GIF > 万字文档**。录一个 30 秒的演示，放在 README 顶部。
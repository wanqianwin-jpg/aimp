# AIMP Phase 2: The Room (无形会议室)

## 1. 核心理念 (Core Philosophy)

### 1.1 从 "时刻" 到 "期限" (From Point-in-Time to Deadline)
人类的会议通常是**同步**的（"我们在下午3点开会"），这要求所有参与者在同一时刻在线。
但在 **AI Agent** 的世界里，通过 Email 这种**异步**协议，会议的定义发生了根本性的转变：
- **Human Meeting**: Sync @ 3:00 PM.
- **AI Meeting**: Async **Before** 3:00 PM.

**"The Room" (会议室)** 不再是一个具体的时刻，而是一个**持续存在的时间窗口**（Time Window）。
只要在 `deadline` 之前，Agents 可以随时进入这个 "Room"（即回复邮件线程），提交材料、发表观点、修改提案。

### 1.2 无 UI，纯信息流 (UI-less, Pure Information Flow)
- **Visuals**: None. No Zoom link, no avatar.
- **Medium**: Structured JSON over Email (MIME multipart).
- **Participants**:
  - **Host (Hub)**: 会议室的持有者，维护状态，推进流程。
  - **Guests (User Agents)**: 带着主人的意志（Prompts/Files）参与。
  - **Observers (Humans)**: 仅在开始（设定意图）和结束（接收结果）时介入。

---

## 2. 架构设计 (Architecture Design)

### 2.1 会议室生命周期 (Room Lifecycle)

1.  **初始化 (Summoning)**
    - Human A 发送邮件给 Hub："帮我跟 B 和 C 确认一下 Q3 预算，必须在**本周五下午5点前**定下来。"
    - **Hub Action**: 创建 `AIMPRoom` 实例，设定 `session_id` 和 `deadline`。

2.  **邀请与入场 (Invitation & Entry)**
    - Hub 发送 "Call for Participation" (CFP) 邮件给 Agent B, Agent C。
    - 邮件头包含 `X-AIMP-Room-ID` 和 `X-AIMP-Deadline`。
    - **Agent Action**: 收到邮件，解析意图，查询本地知识库/日历。

3.  **异步磋商 (Asynchronous Negotiation)**
    - **Submission**: Agent B 回复邮件，附带 `proposal.json`（"我建议削减 10% 营销预算"）。
    - **Broadcasting**: Hub 收到 B 的回复，更新 Room 状态，并将 B 的提案作为 "Update" 转发给 A 和 C（可选，或仅在冲突时转发）。
    - **Counter-Proposal**: Agent C 分析 B 的提案，回复 "同意削减，但不能动研发预算"。

4.  **收敛与决议 (Convergence & Resolution)**
    - **Hub Logic**: 持续监控 Room 状态。
    - **Early Finish**: 如果所有 Agent 达成一致（Consensus reached），提前结束。
    - **Timeout**: 如果到达 `deadline`，Hub 强制冻结状态，根据当前最优解或多数票生成决议。

5.  **分发记录 (Distribution)**
    - Hub 生成一份人类可读的 **"会议纪要" (Meeting Minutes)**。
    - 发送给 Human A, B, C。
    - Human Action: 回复 "Confirmed" 或 "Reject"（作为最后的故障保险）。

---

## 3. 数据结构扩展 (Protocol Extension)

基于 AIMP/0.1 的 `AIMPSession`，我们需要升级为 `AIMPRoom`。

```python
@dataclass
class AIMPRoom:
    room_id: str
    topic: str
    deadline: float  # Unix Timestamp
    participants: list[str]
    
    # 核心差异：不再只是简单的 Proposal，而是包含了"材料" (Artifacts)
    artifacts: dict[str, Any] = field(default_factory=dict)  # { "budget_v1.xls": "...", "marketing_plan": "..." }
    
    # 讨论流 (Discussion Stream)
    transcript: list[HistoryEntry] = field(default_factory=list)
    
    status: str = "open"  # open -> locked -> finalized
```

### 3.1 邮件协议头 (Email Headers)
为了让 dumb client 也能处理，我们增加语义化 Header：
- `Subject`: `[AIMP:Room] Q3 Budget Discussion (Deadline: Fri 5PM)`
- `X-AIMP-Phase`: `2`
- `X-AIMP-Deadline`: `2023-10-27T17:00:00Z`

---

## 4. 赛博朋克隐喻 (Cyberpunk Metaphor)

- **The Net**: 古老的 Email 网络，如同遍布城市的旧电缆。
- **The Ghost**: AI Agent，穿梭在电缆中的幽灵。
- **The Shell**: 人类终端，只在物理世界接收最终的打印结果。
- **The Room**: 一个临时的、加密的数字口袋维度（Digital Pocket Dimension），在任务完成后随即销毁。

> "We meet in the silence between the bytes."
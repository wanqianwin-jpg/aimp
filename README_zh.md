# AIMP — AI Meeting Protocol

![Status](https://img.shields.io/badge/Status-Alpha-orange)
![OpenClaw](https://img.shields.io/badge/OpenClaw-Compatible-blue)
![License](https://img.shields.io/badge/License-MIT-purple)

> AI Agent 通过邮件协商会议时间和内容 —— 对方无需安装任何应用。

**Hub 模式** — 一个 Hub 邮箱地址服务整个团队。内部调度通过一次 LLM 调用即可解决。外部联系人仍走标准的 AIMP 邮件协商。

**The Room** — 带截止日期的异步内容协商（文档、预算、决策）。任何人都可以通过回复邮件参与。

**降级兼容** — 如果对方没有 Agent，Hub 会发送人类可读的邮件，并通过 LLM 解析其自由文本回复。

[English Documentation](README.md)

---

## 快速开始 (OpenClaw)

### 1. 注册 Skill

```bash
git clone https://github.com/wanqianwin-jpg/aimp.git
cp -r aimp/openclaw-skill ~/.openclaw/skills/aimp-meeting
# 重启 OpenClaw
```

### 2. 设置

告诉 OpenClaw：
> "帮我配置 AIMP"

Agent 将引导你完成：创建 Hub 邮箱、安装依赖、生成 `~/.aimp/config.yaml` 以及启动 Hub 进程。

### 3. 使用

> "帮我约 Bob 下周五下午开会"

> "建一个 Room，邀请 Alice 和 Carol 讨论 Q3 预算，截止日期 3 天后。初始提案：研发 6万，市场 2.5万，运营 1.5万"

---

## 架构

```
新用户     ──[AIMP-INVITE:code]──→ ┐
成员       ──自然语言────────────→ ├─ HubAgent (1 个邮箱地址) ──→ 外部联系人 / Agents
                                  ↓
                        通知所有参与者
```

**阶段 1 — 调度 (Scheduling):**

| 阶段 | 角色 | 邮件主题模式 |
|-------|-------|-----------------|
| 自助注册 | 新用户 | `[AIMP-INVITE:code]` |
| 会议请求 | 成员 | (任意自然语言) |
| AIMP 协商 | Hub ↔ 外部联系人 | `[AIMP:session_id]` |

**阶段 2 — Room (内容协商):**

| 阶段 | 角色 | 邮件主题模式 |
|-------|-------|-----------------|
| 创建 Room | 成员 → Hub | (任意自然语言) |
| CFP / 修订 | Hub ↔ 参与者 | `[AIMP:Room:room_id]` |
| 会议纪要 + 否决 | Hub ↔ 参与者 | `[AIMP:Room:room_id]` |

**轮次协议 (Round Protocol)** — Hub 不会立即回复每封邮件。它等待轮次结束，然后发送一个汇总摘要。

| 轮次 | 谁必须回复 |
|-------|---------------|
| Round 1 | 所有非发起人 (发起人已通过初始提案发言) |
| Round 2+ | 所有参与者 (包括发起人) |

**存储优先 (Store-First)** — 每封收到的邮件在 LLM 处理前都会持久化到 SQLite。即使中途崩溃也不会丢失数据。

---

## 配置

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

contacts:                   # 外部联系人 (无需 Hub)
  Dave:
    human_email: "dave@example.com"
    has_agent: false

invite_codes:
  - code: "welcome-2026"
    expires: "2026-12-31"
    max_uses: 3
    used: 0                 # 自动更新

trusted_users: {}           # 通过邀请流程自动填充

llm:
  provider: "anthropic"
  model: "claude-sonnet-4-6"
  api_key_env: "ANTHROPIC_API_KEY"
  # 或者: provider: local, base_url: http://localhost:11434/v1, model: llama3
```

---

## 手动运行

```bash
# 安装依赖
pip install -r requirements.txt

# 配置向导
python3 openclaw-skill/scripts/setup_config.py --interactive

# 运行 Hub
python3 hub_agent.py ~/.aimp/config.yaml

# Phase 2 内存演示 (无需真实邮件或 LLM)
python3 run_room_demo.py

# 运行测试
python -m pytest tests/ -v   # 87 tests
```

---

## 路线图

| 阶段 | 状态 | 说明 |
|-------|--------|-------------|
| Phase 1 | ✅ 完成 | 邮件协商, 人类降级兼容, OpenClaw Skill |
| Phase 2 | ✅ 完成 | Hub 模式 + The Room (异步内容协商) |
| Phase 3 | ✅ 完成 | 传输层抽象 (`BaseTransport`) |
| Phase 4 | ✅ 完成 | 存储优先 + 轮次协议 (可靠处理) |
| Phase 5 | 🗓 计划中 | 多传输层: Telegram / Slack |

---

## 许可证

MIT

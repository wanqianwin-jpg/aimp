# AIMP — AI Meeting Protocol

![Status](https://img.shields.io/badge/Status-Alpha-orange)
![OpenClaw](https://img.shields.io/badge/OpenClaw-Compatible-blue)
![AI-Native](https://img.shields.io/badge/AI-Native-green)
![License](https://img.shields.io/badge/License-MIT-purple)

> **AIMP (AI Meeting Protocol)** —— 赛博朋克时代的会议协商协议。
>
> 当 **古旧的设施 (Email)** 与 **前沿科技 (LLM)** 碰撞，诞生了这个全新的 **AI-Native** 工具。
> 它不只是一个协议，更是 **OpenClaw (龙虾人)** 的强力 **义体 (Cyberware)**。
>
> *   **赛博融合**：利用古老的电子邮件网络作为神经网络的突触，无需对方安装任何 App。
> *   **义体增强**：为你的 Agent 装上“外交官”义体，让它在后台自动与其他 Agent 或人类进行谈判。
>
> **Hub 模式**（v0.2.0 新增）：一个 Agent 服务全家或整个团队。内部成员之间开会，Hub 直接读取所有人偏好，一次 LLM 调用出结果，无需邮件往返。外部联系人仍走标准邮件协商。
>
> **The Room**（v0.2.0 新增）：带截止日期的异步内容协商。适用于文档、预算和复杂决策。
>
> **降级兼容**：对方如果没有 Agent，会自动发自然语言邮件并用 LLM 解析回复。

[English Documentation](README.md)

## 🚀 安装为 OpenClaw Skill

### 第 1 步 —— 注册 Skill

将 `openclaw-skill/` 目录复制到你的 OpenClaw skills 文件夹，然后重启 OpenClaw：

```bash
# 选项 A: 一键克隆并注册
git clone https://github.com/wanqianwin-jpg/aimp.git
cp -r aimp/openclaw-skill ~/.openclaw/skills/aimp-meeting
# 重启 OpenClaw —— Skill 现在可以使用了

# 选项 B (国内镜像)
git clone https://gitee.com/wanqianwin/aimp.git
cp -r aimp/openclaw-skill ~/.openclaw/skills/aimp-meeting
```

> **对于自动执行此操作的 Agent**：克隆仓库，将 `openclaw-skill/` 复制到 `~/.openclaw/skills/aimp-meeting/`，然后告诉用户重启 OpenClaw 并说“帮我配置 AIMP”。

### 第 2 步 —— 首次设置（重启后在 OpenClaw 内部进行）

告诉 OpenClaw：
> "帮我配置 AIMP" / "set up AIMP meeting skill"

Agent 将引导你完成：
1. 准备一个专用的 Hub 邮箱地址（QQ / 163 / Gmail —— 不要用你的私人邮箱）
2. 安装 Python 依赖
3. 生成 `~/.aimp/config.yaml`
4. 配置 LLM（Anthropic / OpenAI / 本地 Ollama）
5. 启动 Hub 后台进程

### 第 3 步 —— 开始使用

设置完成后，直接自然地告诉 OpenClaw：
> "帮我约 Bob 下周五下午开会" / "Schedule a meeting with Bob next Friday"

> 💡 **运行机制**：AIMP 在后台运行一个持久的 Hub 进程（独立于 OpenClaw 会话）。Hub 监控专用邮箱并自动处理所有协商 —— 对方无需安装任何软件。

-----

## 🛠️ 手动开发与测试

如果你是开发者，想手动运行或调试：

### 1. 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 生成配置
```bash
python3 openclaw-skill/scripts/setup_config.py --interactive
```

### 3. 运行 Agent

**独立模式**（原有）：
```bash
python3 agent.py ~/.aimp/config.yaml --notify stdout
```

**Hub 模式**（配置文件含 `members:` 字段时自动启用）：
```bash
python3 hub_agent.py ~/.aimp/config.yaml --notify stdout
```

-----

## 📥 获取源码 (Download)

> **提示**: 请直接参照上方 "安装为 OpenClaw Skill" 中的步骤，其中包含了从 GitHub 或 Gitee 克隆代码的完整命令。

## 整体架构

```
aimp/
├── lib/                          # 核心库
│   ├── email_client.py           # IMAP/SMTP 封装
│   ├── protocol.py               # AIMP/0.1 协议数据模型
│   ├── negotiator.py             # LLM 协商决策引擎
│   ├── session_store.py          # SQLite 会话持久化
│   └── output.py                 # JSON 结构化输出
├── agent.py                      # 独立 Agent（1 人 1 Agent）
├── hub_agent.py                  # Hub Agent（1 个 Agent 服务多人） ← 新增
├── run_demo.py                   # 3-Agent 独立演示
├── config/                       # 演示用配置
│
├── openclaw-skill/               # OpenClaw Skill 发布目录
│   ├── SKILL.md                  # Skill 定义 + 运行指南
│   ├── scripts/
│   │   ├── initiate.py           # 发起会议（自动检测 hub/standalone）
│   │   ├── poll.py               # 单次轮询
│   │   ├── respond.py            # 注入主人回复
│   │   ├── status.py             # 查询状态
│   │   └── setup_config.py       # 配置生成向导（支持两种模式）
│   └── references/
│       ├── protocol-spec.md      # 协议规范
│       └── config-example.yaml   # 配置示例（两种模式）
│
└── requirements.txt
```

## 部署模式

| | Hub 模式 | 独立模式 |
|---|---|---|
| **谁来部署** | 1 人（Host） | 每人各自部署 |
| **谁可以使用** | 所有列出的成员 | 仅限所有者 |
| **内部调度** | 即时（1 次 LLM，无邮件） | 多轮邮件协商 |
| **外部联系人** | 标准邮件协商 | 标准邮件协商 |
| **LLM 成本** | 共享，1 个 Key | 每人一个 |
| **配置字段** | `members:` + `hub:` | `owner:` + `agent:` |

**Hub 模式配置片段：**
```yaml
mode: hub
hub:
  name: "Family Hub"
  email: "family-hub@gmail.com"
members:
  alice:
    email: "alice@gmail.com"
    role: "admin"
    preferences:
      preferred_times: ["weekday mornings"]
      preferred_locations: ["Zoom"]
  bob:
    email: "bob@gmail.com"
    role: "member"
    preferences:
      preferred_times: ["afternoon 14:00-17:00"]
      preferred_locations: ["Tencent Meeting"]
llm:
  provider: "local"        # Ollama — 免费，跑在自己机器上
  model: "llama3"
  base_url: "http://localhost:11434/v1"
```

## 项目路线图 (Roadmap)

- [x] **v0.1 (MVP)**
    - 基础邮件协商协议
    - 人类降级兼容（自然语言解析）
    - OpenClaw Skill 集成
    - 多源下载支持（GitHub/Gitee）
- [x] **v0.2 (Hub 模式)**
    - [x] **Hub 模式**：一个 Agent 服务家庭/团队多人
    - [x] **上帝视角调度**：内部成员之间 1 次 LLM 即出结果，零邮件往返
    - [x] **自动身份识别**：基于白名单的发件人身份识别
    - [x] **本地 LLM 支持**（Ollama/LM Studio）：无需 API Key
    - [x] **混合模式**：Hub 处理内部快速路径 + 外部邮件协商
- [ ] **v1.0 (Release)**
    - [ ] 日历集成（Google Calendar / Outlook）
    - [ ] 多语言支持 (i18n)
    - [ ] 企业级部署指南
    - [ ] Docker Compose Hub 部署方案

## 协议说明

邮件 Subject: `[AIMP:<session_id>] v<version> <topic>`

| action   | 含义         | 触发条件 |
|----------|--------------|-------------------|
| propose  | 发起提议     | 人类要求发起会议 |
| accept   | 接受提议     | 所有项目都匹配偏好 |
| counter  | 反提议       | 部分匹配，提出替代方案 |
| confirm  | 最终确认     | 所有参与者都接受 |
| escalate | 升级给人类   | 无法自动做出决策 |

如果 5 轮后仍未达成共识，将自动升级为人工干预。

## 降级兼容

当联系人没有 Agent 时（`has_agent: false`），会自动发送自然语言邮件，并使用 LLM 解析人类的自由文本回复。

## 环境变量

| 变量 | 说明 |
|------|------|
| `ANTHROPIC_API_KEY` | Anthropic API 密钥 |
| `AIMP_AGENT_EMAIL` | Agent 邮箱 |
| `AIMP_AGENT_PASSWORD` | Agent 邮箱密码 |
| `AIMP_IMAP_SERVER` | IMAP 服务器 |
| `AIMP_SMTP_SERVER` | SMTP 服务器 |
| `AIMP_POLL_INTERVAL` | 轮询间隔（秒，默认 15） |

## 🤖 AI 工具使用声明

本项目自豪地采用先进的 AI 工具进行开发。我们信仰透明度以及 AI 原生软件工程的未来。

- **IDE**: Trae (由 Gemini-3-Pro / Claude-4.6-Sonnet 驱动)
- **CLI**: Claude Code (Claude 4.6 Sonnet)
- **模型**: Gemini 3 Pro

关于具体的使用场景和责任声明，请参阅 [AI_USAGE.md](AI_USAGE.md)。

## 📄 许可证

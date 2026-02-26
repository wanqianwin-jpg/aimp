# AIMP — AI Meeting Protocol

![Status](https://img.shields.io/badge/Status-Alpha-orange)
![OpenClaw](https://img.shields.io/badge/OpenClaw-Compatible-blue)
![AI-Native](https://img.shields.io/badge/AI-Native-green)
![License](https://img.shields.io/badge/License-MIT-purple)

> **AIMP (AI Meeting Protocol)** 是一个极简的 AI Agent 会议协商协议。
> Agent 通过邮件协商会议时间和地点，自动达成共识。
>
> **Hub 模式**（v0.2 新增）：一个 Agent 服务全家或整个团队。内部成员之间开会，Hub 直接读取所有人偏好，一次 LLM 调用出结果，无需邮件往返。外部联系人仍走标准邮件协商。
>
> **降级兼容**：对方如果没有 Agent，会自动发自然语言邮件并用 LLM 解析回复。

[English Documentation](README.md)

## 🚀 如何使用 (OpenClaw Skill)

AIMP 完美适配 **OpenClaw (龙虾人)**。如果您正在使用龙虾人，只需复制并粘贴以下指令给它，剩下的交给它处理：

> **[龙虾人用户专用指令]**
> “请帮我从 `https://gitee.com/wanqianwin/aimp` (国内) 或 `https://github.com/wanqianwin-jpg/aimp` (国际) 安装 AIMP 会议 Skill。
> 1. 克隆仓库并运行 `export OPENCLAW_ENV=true && python3 openclaw-skill/scripts/install.py`。
> 2. 运行 `python3 openclaw-skill/scripts/setup_config.py --interactive` 帮我配置邮箱。
> 3. 完成后，我们发起一个测试会议！”

### 🐳 Docker & 容器化友好支持
智能安装脚本 (`install.py`) 会自动检测容器环境。如果检测到 `OPENCLAW_ENV` 或 `DOCKER_ENV` 环境变量，它将自动切换到 `requirements_minimal.txt`，以实现快速、轻量且无权限障碍的安装。

### 1. 手动安装 Skill

将本仓库作为 Skill 添加到你的 OpenClaw：

```bash
# 假设你已经安装了 OpenClaw
openclaw skill add aimp-meeting https://gitee.com/wanqianwin/aimp
```

### 2. 让 OpenClaw 帮你配置

在 OpenClaw 中输入：
> "Help me setup AIMP meeting agent"

OpenClaw 会引导你输入邮箱信息、偏好设置，并自动完成配置。

> **💡 关于 LLM 配置的说明**：
> AIMP 作为一个**背景运行的独立代理 (Background Agent)**，它需要持续监控邮件并在无人看管时做出决策（例如判断哪个会议时间更合适）。因此，它需要自己的 LLM 访问权限。
> *   **好消息**：如果你在 OpenClaw 中已经配置了 `ANTHROPIC_API_KEY` 或 `OPENAI_API_KEY`，配置脚本会自动检测并复用它们，无需重复输入。

### 3. 发起会议

直接告诉 OpenClaw：
> "Schedule a meeting with bob@example.com about Project X review"

OpenClaw 会：
1.  自动发起邮件协商。
2.  定期检查回复。
3.  如果对方是人类，自动解析自然语言回复。
4.  达成共识后通知你。

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

请选择最适合您的下载源：

### 选项 1: Gitee 码云 (国内推荐 - 极速)
- **HTTPS**: `git clone https://gitee.com/wanqianwin/aimp.git`
- **SSH**: `git clone git@gitee.com:wanqianwin/aimp.git`

### 选项 2: GitHub (国际源)
- **HTTPS**: `git clone https://github.com/wanqianwin-jpg/aimp.git`
- **SSH**: `git clone git@github.com:wanqianwin-jpg/aimp.git`

> **提示**: 如果您在中国大陆，为了更快的下载速度，强烈推荐使用 **Gitee** 镜像。

## 💻 操作系统指南
- **macOS / Linux**: 打开终端 (Terminal) 并运行上面的 `git clone` 命令。
- **Windows**: 打开 PowerShell 或命令提示符 (cmd) 并运行命令。

## 一、整体架构

```
aimp/
├── lib/                          # 核心库
│   ├── email_client.py           # IMAP/SMTP 收发封装
│   ├── protocol.py               # AIMP/0.1 协议数据模型
│   ├── negotiator.py             # LLM 协商决策引擎
│   ├── session_store.py          # SQLite 会话持久化
│   └── output.py                 # JSON 结构化输出
├── agent.py                      # 独立 Agent（1 人 1 Agent）
├── hub_agent.py                  # Hub Agent（1 个 Agent 服务多人） ← 新增
├── run_demo.py                   # 3 Agent 独立演示
├── config/                       # 演示用配置
│
├── openclaw-skill/               # OpenClaw Skill 发布目录
│   ├── SKILL.md                  # Skill 定义 + runbook（含 Hub 模式说明）
│   ├── scripts/
│   │   ├── initiate.py           # 发起会议（自动检测 hub/standalone）
│   │   ├── poll.py               # 单次轮询
│   │   ├── respond.py            # 注入主人回复
│   │   ├── status.py             # 查询状态
│   │   └── setup_config.py       # 配置生成（hub/standalone 均支持）
│   └── references/
│       ├── protocol-spec.md      # 协议规范
│       └── config-example.yaml   # 配置示例（两种模式）
│
└── requirements.txt
```

## 两种部署模式对比

| | Hub 模式 | 独立模式 |
|---|---|---|
| **谁来部署** | 1 人（Host）搞定，其他人开箱即用 | 每人各自部署 |
| **内部调度** | 即时出结果（1 次 LLM，无邮件） | 多轮邮件协商 |
| **外部联系人** | 标准邮件协商 | 标准邮件协商 |
| **LLM 成本** | 共享，1 个 key | 每人一个 |
| **配置标志** | `members:` + `hub:` | `owner:` + `agent:` |

**Hub 模式配置片段：**
```yaml
mode: hub
hub:
  name: "家庭助理"
  email: "family-hub@gmail.com"
members:
  alice:
    email: "alice@gmail.com"
    role: "admin"
    preferences:
      preferred_times: ["工作日上午"]
      preferred_locations: ["Zoom"]
  bob:
    email: "bob@gmail.com"
    role: "member"
    preferences:
      preferred_times: ["下午 14:00-17:00"]
      preferred_locations: ["腾讯会议"]
llm:
  provider: "local"         # Ollama — 免费，跑在自己机器上
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
    - [x] **自动身份识别**：发件人邮箱白名单，无需用户记标签
    - [x] **本地 LLM 支持**（Ollama/LM Studio）：无需 API Key
    - [x] **混合模式**：内部成员快速调度 + 外部联系人邮件协商
- [ ] **v1.0 (Release)**
    - [ ] 日历集成（Google Calendar / Outlook）
    - [ ] 多语言支持（i18n）
    - [ ] 企业级部署指南
    - [ ] Docker Compose Hub 部署方案

## 协议说明

邮件 Subject: `[AIMP:<session_id>] v<version> <topic>`

| action   | 含义         | 触发条件 |
|----------|--------------|----------|
| propose  | 发起提议     | 人类要求约会议 |
| accept   | 接受当前提议 | 所有项目都匹配偏好 |
| counter  | 反提议       | 部分匹配，提出替代方案 |
| confirm  | 最终确认     | 所有参与者都 accept |
| escalate | 升级给人类   | 超出偏好范围无法自动决策 |

超过 5 轮未达成共识，自动通知人类介入。

## 两种通知模式

| 模式 | 用途 | escalation 方式 |
|------|------|-----------------|
| `email` | 独立运行 | 发邮件给主人 |
| `stdout` | OpenClaw Skill | 输出 JSON 事件，由 OpenClaw 转发到 IM |

## 降级兼容

联系人没有 Agent 时（`has_agent: false`），自动发自然语言邮件，用 LLM 解析人类的自由文本回复。

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

- **IDE**: Trae (由 Gemini-1.5-Pro / Claude-3.5-Sonnet 驱动)
- **CLI**: Claude Code (Claude 3.7 Sonnet)
- **模型**: Gemini 1.5 Pro

关于具体的使用场景和责任声明，请参阅 [AI_USAGE.md](AI_USAGE.md)。

## 📄 许可证

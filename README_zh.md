# AIMP — AI Meeting Protocol

> **AIMP (AI Meeting Protocol)** 是一个极简的 AI Agent 会议协商协议。
> 3 个 Agent 分别代表 3 个人，通过邮件协商一次会议，最终达成共识。
> 支持降级兼容：对方如果没有 Agent，会自动发自然语言邮件并解析回复。

[English Documentation](README.md)

## 🚀 如何使用 (OpenClaw Skill)

本项目设计为 **OpenClaw Skill**，建议通过 OpenClaw 直接使用。

### 1. 安装 Skill

将本仓库作为 Skill 添加到你的 OpenClaw：

```bash
# 假设你已经安装了 OpenClaw
openclaw skill add aimp-meeting https://gitee.com/wanqianwin/aimp
```

### 2. 让 OpenClaw 帮你配置

在 OpenClaw 中输入：
> "Help me setup AIMP meeting agent"

OpenClaw 会引导你输入邮箱信息、偏好设置，并自动完成配置。

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
```bash
python3 agent.py ~/.aimp/config.yaml --notify stdout
```

-----

## 📥 获取源码 (Download)

请根据您所在的网络环境选择最快的仓库地址。

### 选项 1: Gitee 码云 (国内推荐 - 极速)
- **HTTPS**: `git clone https://gitee.com/wanqianwin/aimp.git`
- **SSH**: `git clone git@gitee.com:wanqianwin/aimp.git`

### 选项 2: GitHub (国际源)
- **HTTPS**: `git clone https://github.com/wanqianwin-jpg/aimp.git`
- **SSH**: `git clone git@github.com:wanqianwin-jpg/aimp.git`

> **提示**: 国内用户请优先使用 **Gitee** 镜像，以获得最佳下载体验。

### 💻 操作系统说明
- **macOS / Linux**: 打开终端 (Terminal) 运行上述命令。
- **Windows**: 打开 PowerShell 或 命令提示符 (cmd) 运行命令。

## 一、整体架构

```
aimp/
├── lib/                          # 核心库
│   ├── email_client.py           # IMAP/SMTP 收发封装
│   ├── protocol.py               # AIMP/0.1 协议数据模型
│   ├── negotiator.py             # LLM 协商决策引擎
│   ├── session_store.py          # SQLite 会话持久化
│   └── output.py                 # JSON 结构化输出
├── agent.py                      # Agent 主循环（支持 email/stdout 通知模式）
├── run_demo.py                   # 3 Agent 独立演示
├── config/                       # 演示用配置
│
├── openclaw-skill/               # OpenClaw Skill 发布目录
│   ├── SKILL.md                  # Skill 定义 + runbook
│   ├── scripts/
│   │   ├── initiate.py           # 发起会议
│   │   ├── poll.py               # 单次轮询
│   │   ├── respond.py            # 注入主人回复
│   │   ├── status.py             # 查询状态
│   │   └── setup_config.py       # 配置生成
│   └── references/
│       ├── protocol-spec.md      # 协议规范
│       └── config-example.yaml   # 配置示例
│
└── requirements.txt
```

## 项目路线图 (Roadmap)

- [x] **v0.1 (MVP)**
    - 基础邮件协商协议
    - 人类降级兼容 (自然语言解析)
    - OpenClaw Skill 集成
    - 多源下载支持 (GitHub/Gitee)
- [ ] **v0.2 (Stability)**
    - [ ] 支持更多 IM 集成 (via OpenClaw)
    - [ ] 改进冲突解决逻辑
    - [ ] Docker 支持
- [ ] **v1.0 (Release)**
    - [ ] 多语言支持 (i18n)
    - [ ] 日历集成 (Google Calendar / Outlook)
    - [ ] 企业级部署指南

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

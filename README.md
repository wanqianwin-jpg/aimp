# AIMP — AI Meeting Protocol

AI Agent 通过邮件自动协商会议时间和地点，达成共识后通过 IM 通知主人。

支持两种使用方式：
1. **OpenClaw Skill** — 安装到 OpenClaw，通过 WhatsApp/Telegram/Slack 等 IM 交互
2. **独立运行** — 3 个 Agent 线程直接跑，邮件通知

## OpenClaw Skill 安装

```bash
# 复制 skill 到 OpenClaw 目录
cp -r openclaw-skill ~/.openclaw/skills/aimp-meeting

# 设置环境变量
export ANTHROPIC_API_KEY="sk-ant-..."
export AIMP_AGENT_EMAIL="your-agent@gmail.com"
export AIMP_AGENT_PASSWORD="gmail-app-password"
export AIMP_IMAP_SERVER="imap.gmail.com"
export AIMP_SMTP_SERVER="smtp.gmail.com"
```

然后在 OpenClaw 中对话：
- "帮我约 Bob 和 Carol 开 Q1 复盘会"
- "我的会议什么状态了？"
- Agent 需要你决策时会直接在 IM 里问你

## 独立运行（演示模式）

```bash
pip install -r requirements.txt

# 编辑 config/ 目录下的 3 个 YAML 配置
export ANTHROPIC_API_KEY="sk-ant-..."
export AGENT_A_PASSWORD="..." AGENT_B_PASSWORD="..." AGENT_C_PASSWORD="..."

python run_demo.py
```

## 文件结构

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

## 协议说明

邮件 Subject: `[AIMP:<session_id>] v<version> <topic>`

| action   | 含义         |
|----------|------------|
| propose  | 发起提议       |
| accept   | 接受当前提议     |
| counter  | 反提议        |
| confirm  | 最终确认       |
| escalate | 升级给人类      |

超过 5 轮未达成共识，自动通知人类介入。

## 两种通知模式

| 模式 | 用途 | escalation 方式 |
|------|------|----------------|
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

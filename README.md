# AIMP — AI Meeting Protocol

![Status](https://img.shields.io/badge/Status-Alpha-orange)
![OpenClaw](https://img.shields.io/badge/OpenClaw-Compatible-blue)
![AI-Native](https://img.shields.io/badge/AI-Native-green)
![License](https://img.shields.io/badge/License-MIT-purple)

> **AIMP (AI Meeting Protocol)** is a minimalist AI Agent meeting negotiation protocol.
> Three Agents, representing three individuals, negotiate a meeting via email and reach a consensus.
> **Fallback Compatibility**: If the recipient does not have an Agent, AIMP automatically sends a natural language email and parses the reply using an LLM.

[中文文档](README_zh.md)

## 📥 Get Source Code

Choose the repository that best suits your location for optimal download speed.

### Option 1: GitHub (International Recommended)
- **HTTPS**: `git clone https://github.com/wanqianwin-jpg/aimp.git`
- **SSH**: `git clone git@github.com:wanqianwin-jpg/aimp.git`

### Option 2: Gitee (China Recommended - Faster)
- **HTTPS**: `git clone https://gitee.com/wanqianwin/aimp.git`
- **SSH**: `git clone git@gitee.com:wanqianwin/aimp.git`

> **Note**: If you are in mainland China and experience slow connection to GitHub, please use the **Gitee** mirror.

### 💻 OS-Specific Instructions
- **macOS / Linux**: Open Terminal and run the `git clone` command above.
- **Windows**: Open PowerShell or Command Prompt (cmd) and run the command.

## 🚀 How to Use (OpenClaw Skill)

This project is designed as an **OpenClaw Skill** and is recommended to be used directly via OpenClaw.

### 1. Install Skill

Add this repository as a Skill to your OpenClaw:

```bash
# Assuming you have OpenClaw installed
openclaw skill add aimp-meeting https://github.com/wanqianwin-jpg/aimp
```

### 2. Let OpenClaw Configure for You

Type in OpenClaw:
> "Help me setup AIMP meeting agent"

OpenClaw will guide you through entering your email info, preferences, and automatically complete the configuration.

### 3. Schedule a Meeting

Tell OpenClaw directly:
> "Schedule a meeting with bob@example.com about Project X review"

OpenClaw will:
1.  Automatically initiate email negotiation.
2.  Periodically check for replies.
3.  If the recipient is human, automatically parse the natural language reply.
4.  Notify you after consensus is reached.

-----

## 🛠️ Manual Development & Testing

If you are a developer and want to run or debug manually:

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Generate Configuration
```bash
python3 openclaw-skill/scripts/setup_config.py --interactive
```

### 3. Run Agent
```bash
python3 agent.py ~/.aimp/config.yaml --notify stdout
```

-----

## Architecture

```
aimp/
├── lib/                          # Core Library
│   ├── email_client.py           # IMAP/SMTP Wrapper
│   ├── protocol.py               # AIMP/0.1 Protocol Data Model
│   ├── negotiator.py             # LLM Negotiation Decision Engine
│   ├── session_store.py          # SQLite Session Persistence
│   └── output.py                 # JSON Structured Output
├── agent.py                      # Agent Main Loop (Supports email/stdout notification modes)
├── run_demo.py                   # 3-Agent Independent Demo
├── config/                       # Demo Configuration
│
├── openclaw-skill/               # OpenClaw Skill Distribution Directory
│   ├── SKILL.md                  # Skill Definition + Runbook
│   ├── scripts/
│   │   ├── initiate.py           # Initiate Meeting
│   │   ├── poll.py               # Single Poll
│   │   ├── respond.py            # Inject Owner Reply
│   │   ├── status.py             # Query Status
│   │   └── setup_config.py       # Configuration Generation
│   └── references/
│       ├── protocol-spec.md      # Protocol Specification
│       └── config-example.yaml   # Configuration Example
│
└── requirements.txt
```

## Roadmap

- [x] **v0.1 (MVP)**
    - Basic Email Negotiation Protocol
    - Human Fallback (Natural Language Parsing)
    - OpenClaw Skill Integration
    - Multi-source Download (GitHub/Gitee)
- [ ] **v0.2 (Stability)**
    - [ ] Support more IM integrations (via OpenClaw)
    - [ ] Improved conflict resolution logic
    - [ ] Docker support
- [ ] **v1.0 (Release)**
    - [ ] Multi-language support (i18n)
    - [ ] Calendar integration (Google Calendar / Outlook)
    - [ ] Enterprise deployment guide

## Protocol Specification

Email Subject: `[AIMP:<session_id>] v<version> <topic>`

| action   | Meaning      | Trigger Condition |
|----------|--------------|-------------------|
| propose  | Initiate Proposal | Human requests a meeting |
| accept   | Accept Proposal   | All items match preferences |
| counter  | Counter Proposal  | Partial match, propose alternatives |
| confirm  | Final Confirmation| All participants accept |
| escalate | Escalate to Human | Cannot decide automatically |

If consensus is not reached after 5 rounds, it automatically escalates to human intervention.

## Fallback Compatibility

When a contact does not have an Agent (`has_agent: false`), a natural language email is automatically sent, and the human's free-text reply is parsed using an LLM.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API Key |
| `AIMP_AGENT_EMAIL` | Agent Email |
| `AIMP_AGENT_PASSWORD` | Agent Email Password |
| `AIMP_IMAP_SERVER` | IMAP Server |
| `AIMP_SMTP_SERVER` | SMTP Server |
| `AIMP_POLL_INTERVAL` | Poll Interval (seconds, default 15) |

## 🤖 AI Tool Usage Declaration

This project proudly leverages advanced AI tools for development. We believe in transparency and the future of AI-native software engineering.

- **IDE**: Trae (Powered by Gemini-1.5-Pro / Claude-3.5-Sonnet)
- **CLI**: Claude Code (Claude 3.7 Sonnet)
- **Model**: Gemini 1.5 Pro

For detailed usage scenarios and responsibility declaration, please refer to [AI_USAGE.md](AI_USAGE.md).

## 📄 License

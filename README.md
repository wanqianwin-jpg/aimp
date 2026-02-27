# AIMP — AI Meeting Protocol

![Status](https://img.shields.io/badge/Status-Alpha-orange)
![OpenClaw](https://img.shields.io/badge/OpenClaw-Compatible-blue)
![AI-Native](https://img.shields.io/badge/AI-Native-green)
![License](https://img.shields.io/badge/License-MIT-purple)

> **AIMP (AI Meeting Protocol)** —— A meeting negotiation protocol with a Cyberpunk aesthetic.
>
> Where **Ancient Infrastructure (Email)** meets **New Technology (LLM)**, forging a new **AI-Native** tool.
> It's not just a protocol; it's a powerful **Cyberware (Skill)** for **OpenClaw**.
>
> *   **Cyber-Fusion**: Utilizing the ancient email network as synapses, requiring no installation from the other party.
> *   **Cyberware Enhancement**: Install a "Diplomat" implant for your Agent, allowing it to negotiate with other Agents or humans in the background.
>
> **Hub Mode** (v0.2.0): One Agent serves a whole family or team. Internal members get instant scheduling via "god view" — no email rounds needed. External contacts still use standard email negotiation.
>
> **The Room** (v0.2.0): Async content negotiation with deadlines. Perfect for documents, budgets, and complex decisions.
>
> **Fallback Compatibility**: If the recipient does not have an Agent, AIMP automatically sends a natural language email and parses the reply using an LLM.

[中文文档](README_zh.md)

##  Install as OpenClaw Skill

### Step 1 — Register the Skill

Copy the `openclaw-skill/` directory into your OpenClaw skills folder, then restart OpenClaw:

```bash
# Option A: clone and register in one go
git clone https://github.com/wanqianwin-jpg/aimp.git
cp -r aimp/openclaw-skill ~/.openclaw/skills/aimp-meeting
# restart OpenClaw — the skill is now available

# Option B (China mirror)
git clone https://gitee.com/wanqianwin/aimp.git
cp -r aimp/openclaw-skill ~/.openclaw/skills/aimp-meeting
```

> **For agents doing this automatically**: clone the repo, copy `openclaw-skill/` to `~/.openclaw/skills/aimp-meeting/`, then tell the user to restart OpenClaw and say "set up AIMP".

### Step 2 — First-time Setup (inside OpenClaw after restart)

Tell OpenClaw:
> "帮我配置 AIMP" / "set up AIMP meeting skill"

The agent will walk you through:
1. Preparing a dedicated Hub email address (QQ / 163 / Gmail — not your personal email)
2. Installing Python dependencies
3. Generating `~/.aimp/config.yaml`
4. Configuring the LLM (Anthropic / OpenAI / local Ollama)
5. Starting the Hub background process

### Step 3 — Use It

Once set up, just tell OpenClaw naturally:
> "帮我约 Bob 下周五下午开会" / "Schedule a meeting with Bob next Friday"

> 💡 **How it works**: AIMP runs a persistent Hub process in the background (independent of OpenClaw sessions). The Hub monitors a dedicated email address and handles all negotiation automatically — no installation required on the other party's side.

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

**Standalone mode** (original):
```bash
python3 agent.py ~/.aimp/config.yaml --notify stdout
```

**Hub mode** (auto-detected from config):
```bash
python3 hub_agent.py ~/.aimp/config.yaml --notify stdout
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
├── agent.py                      # Standalone Agent (1 person, 1 Agent)
├── hub_agent.py                  # Hub Agent (1 Agent serves multiple people) ← NEW
├── run_demo.py                   # 3-Agent Independent Demo
├── config/                       # Demo Configuration
│
├── openclaw-skill/               # OpenClaw Skill Distribution Directory
│   ├── SKILL.md                  # Skill Definition + Runbook
│   ├── scripts/
│   │   ├── initiate.py           # Initiate Meeting (hub/standalone auto-detect)
│   │   ├── poll.py               # Single Poll
│   │   ├── respond.py            # Inject Owner Reply
│   │   ├── status.py             # Query Status
│   │   └── setup_config.py       # Configuration Generation (hub/standalone wizard)
│   └── references/
│       ├── protocol-spec.md      # Protocol Specification
│       └── config-example.yaml   # Configuration Example (both modes)
│
└── requirements.txt
```

## Deployment Modes

| | Hub Mode | Standalone Mode |
|---|---|---|
| **Who deploys** | 1 person (the Host) | Each person separately |
| **Who can use it** | All listed members | Just the owner |
| **Internal scheduling** | Instant (1 LLM call, no email) | Multi-round email negotiation |
| **External contacts** | Standard email negotiation | Standard email negotiation |
| **LLM cost** | Shared, 1 key | Per person |
| **Config field** | `members:` + `hub:` | `owner:` + `agent:` |

**Hub mode config snippet:**
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
  provider: "local"        # Ollama — free, runs on your own machine
  model: "llama3"
  base_url: "http://localhost:11434/v1"
```

## Roadmap

- [x] **v0.1 (MVP)**
    - Basic Email Negotiation Protocol
    - Human Fallback (Natural Language Parsing)
    - OpenClaw Skill Integration
    - Multi-source Download (GitHub/Gitee)
- [x] **v0.2 (Hub Mode)**
    - [x] **Hub Mode**: One Agent serves multiple people (family/team)
    - [x] **God-view scheduling**: Internal members — 1 LLM call, instant result, no email rounds
    - [x] **Auto identity recognition**: Whitelist-based sender identification
    - [x] **Local LLM support** (Ollama/LM Studio): No API key needed
    - [x] **Hybrid mode**: Hub handles internal fast-path + external email negotiation
- [ ] **v1.0 (Release)**
    - [ ] Calendar integration (Google Calendar / Outlook)
    - [ ] Multi-language support (i18n)
    - [ ] Enterprise deployment guide
    - [ ] Docker Compose for Hub deployment

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

- **IDE**: Trae (Powered by Gemini-3-Pro / Claude-4.6-Sonnet)
- **CLI**: Claude Code (Claude 4.6 Sonnet)
- **Model**: Gemini 3 Pro

For detailed usage scenarios and responsibility declaration, please refer to [AI_USAGE.md](AI_USAGE.md).

## 📄 License

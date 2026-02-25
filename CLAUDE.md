# AIMP MVP — Implementation Guide

> Goal: 3 AI Agents representing 3 individuals negotiate a meeting via email and reach a consensus.
> Constraints: No hash chains, no DID, no permission budget, no signatures, no payments. Only the "runnable" minimum closed loop.

-----

## I. Architecture

```
Alice (Human) ──Preferences──→ Agent-A ──Email──→ ┐
Bob   (Human) ──Preferences──→ Agent-B ──Email──→ ├─ Shared Email Thread
Carol (Human) ──Preferences──→ Agent-C ──Email──→ ┘
                   ↑                           │
                   └── Result Notification (Email/Terminal) ←──┘
```

Core Workflow:

1. Alice tells her Agent: "Schedule a Q1 review meeting with Bob and Carol"
2. Agent-A initiates an email thread, Agent-B/C reply automatically
3. Consensus is reached after multiple rounds of negotiation
4. Each Agent notifies its owner of the final result

**Key Design: Fallback Compatibility**

If the recipient does not have an Agent, send a natural language email to the human's email address and parse the human's free-text reply using an LLM. This makes it usable by a single person from day one.

-----

## II. File Structure

```
aimp/
├── agent.py              # Agent Main Loop
├── email_client.py       # IMAP/SMTP Wrapper
├── protocol.py           # AIMP Protocol Parsing/Generation
├── negotiator.py         # Negotiation Decision Logic (Calls LLM)
├── config/
│   ├── agent_a.yaml      # Agent-A Config (Email, Preferences, Contacts)
│   ├── agent_b.yaml
│   └── agent_c.yaml
├── run_demo.py           # Demo Script to Launch 3 Agents
└── README.md
```

-----

## III. Configuration Format

One YAML config per Agent:

```yaml
# config/agent_a.yaml
agent:
  name: "Alice's Assistant"
  email: "alice-agent@example.com"
  imap_server: "imap.example.com"
  smtp_server: "smtp.example.com"
  password: "xxx"  # Or reference environment variable

owner:
  name: "Alice"
  email: "alice@gmail.com"  # Human email for notifications

preferences:
  preferred_times:
    - "weekday mornings 9:00-12:00"
    - "2026-03-01"
  blocked_times:
    - "2026-03-03"
    - "Friday afternoons"
  preferred_locations:
    - "Zoom"
    - "Tencent Meeting"
  auto_accept: true  # Automatically accept if preferences match perfectly

contacts:
  Bob:
    agent_email: "bob-agent@example.com"    # If they have an Agent
    human_email: "bob@gmail.com"            # Fallback if no Agent
    has_agent: true
  Carol:
    agent_email: "carol-agent@example.com"
    human_email: "carol@gmail.com"
    has_agent: true

llm:
  provider: "anthropic"   # Or "openai"
  model: "claude-sonnet-4-5-20250514"
  api_key_env: "ANTHROPIC_API_KEY"  # Read from environment variable
```

-----

## IV. Protocol Format (AIMP/0.1)

### 4.1 Email Specification

- **Subject**: `[AIMP:<session_id>] v<version> <Brief Description>`
  - Example: `[AIMP:meeting-001] v1 Q1 Review Meeting Time Negotiation`
- **Body**: Plain text, human-readable summary
- **JSON Attachment**: `protocol.json`, structured protocol data
- **References Header**: References the Message-ID of the previous email in the thread

### 4.2 protocol.json Structure

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
  "topic": "Q1 Review Meeting",
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
      "options": ["Zoom", "Office 3F", "Tencent Meeting"],
      "votes": {
        "alice-agent@example.com": "Zoom",
        "bob-agent@example.com": null,
        "carol-agent@example.com": null
      }
    }
  },
  "status": "negotiating",
  "history": [
    {"version": 1, "from": "alice-agent@example.com", "action": "propose", "summary": "Initiated meeting proposal"},
    {"version": 2, "from": "bob-agent@example.com", "action": "counter", "summary": "Suggested in-person instead"},
    {"version": 3, "from": "carol-agent@example.com", "action": "accept", "summary": "Agreed to Time A and in-person"}
  ]
}
```

### 4.3 Action Types

|action    |Meaning    |Trigger Condition         |
|----------|------|-------------|
|`propose` |Initiate Proposal  |Human requests a meeting      |
|`accept`  |Accept Proposal|All items match preferences    |
|`counter` |Counter Proposal   |Partial match, propose alternatives  |
|`confirm` |Final Confirmation  |All participants accepted|
|`escalate`|Escalate to Human  |Cannot decide automatically (outside preferences) |

### 4.4 Consensus Rules

- Each topic (time/location) is voted on independently
- If an option receives votes from all participants → Topic is resolved
- All topics resolved → Send `confirm`
- More than 5 rounds without consensus → `escalate` to all humans

-----

## V. Core Module Implementation

### 5.1 email_client.py

Wraps IMAP/SMTP, provides:

```python
class EmailClient:
    def __init__(self, imap_server, smtp_server, email, password): ...
    
    def fetch_aimp_emails(self, since_minutes=5) -> list[Email]:
        """Search unread emails with Subject containing [AIMP:, return parsed list"""
        # IMAP SEARCH: UNSEEN SUBJECT "[AIMP:"
        # Parse body and JSON attachment
        ...
    
    def send_aimp_email(self, to: list[str], session_id: str, 
                         version: int, body_text: str, 
                         protocol_json: dict, 
                         references: list[str] = None): 
        """Send AIMP protocol email"""
        # Construct multipart email: text/plain + application/json attachment
        # Set Subject: [AIMP:{session_id}] v{version}
        # Set References header
        ...
    
    def send_human_email(self, to: str, subject: str, body: str):
        """Send normal email to human (fallback or notification)"""
        ...
```

### 5.2 protocol.py

Protocol data parsing and state management:

```python
class AIMPSession:
    def __init__(self, session_id: str, topic: str, participants: list[str]): ...
    
    @classmethod
    def from_json(cls, data: dict) -> "AIMPSession": 
        """Parse from protocol.json"""
        ...
    
    def to_json(self) -> dict:
        """Export to protocol.json"""
        ...
    
    def apply_vote(self, voter: str, item: str, choice: str):
        """Record vote"""
        ...
    
    def add_option(self, item: str, option: str):
        """Add new option (for counter)"""
        ...
    
    def check_consensus(self) -> dict:
        """Check if consensus reached for each topic, return {item: resolved_value | None}"""
        ...
    
    def is_fully_resolved(self) -> bool:
        """Are all topics resolved?"""
        ...
    
    @property
    def version(self) -> int: ...
    
    def next_version(self) -> int:
        return self.version + 1
```

### 5.3 negotiator.py

Calls LLM for decision making (Core Intelligence):

```python
class Negotiator:
    def __init__(self, preferences: dict, llm_client): ...
    
    def decide(self, session: AIMPSession) -> tuple[str, dict]:
        """
        Input: Current session state
        Output: (action, details)
        
        Logic:
        1. Send session state + own preferences to LLM
        2. Let LLM decide:
           - Completely matches preferences → ("accept", {votes: {...}})
           - Partially matches → ("counter", {votes: {...}, new_options: {...}})
           - Cannot match → ("escalate", {reason: "..."})
        3. Return result
        """
        ...
    
    def parse_human_reply(self, email_body: str, session: AIMPSession) -> tuple[str, dict]:
        """
        Use LLM to parse human free-text reply, extract voting intent.
        Used for fallback mode (when recipient has no Agent).
        """
        ...
    
    def generate_human_readable_summary(self, session: AIMPSession) -> str:
        """Generate human-readable summary for email body"""
        ...
```

**LLM Prompt Template (Critical):**

```
You are a meeting coordination assistant. Your owner is {owner_name}.

Owner's Preferences:
- Preferred Times: {preferred_times}
- Blocked Times: {blocked_times}
- Preferred Locations: {preferred_locations}

Current Negotiation State:
{session_json}

Please judge if the current proposal matches the owner's preferences, return JSON:
{
  "action": "accept" | "counter" | "escalate",
  "votes": {"time": "selected time or null", "location": "selected location or null"},
  "new_options": {"time": ["new proposed time"], "location": ["new proposed location"]},  // only for counter
  "reason": "brief explanation"
}
```

### 5.4 agent.py — Main Loop

```python
class AIMPAgent:
    def __init__(self, config_path: str):
        self.config = load_yaml(config_path)
        self.email = EmailClient(...)
        self.negotiator = Negotiator(self.config["preferences"], llm)
        self.sessions = {}  # session_id -> AIMPSession
    
    def run(self, poll_interval=30):
        """Main Loop"""
        while True:
            self.poll()
            time.sleep(poll_interval)
    
    def poll(self):
        emails = self.email.fetch_aimp_emails()
        for email in emails:
            self.handle_email(email)
    
    def handle_email(self, email):
        # 1. Parse protocol.json
        session_data = extract_protocol_json(email)
        
        if session_data:
            # Sender is Agent, use protocol mode
            session = AIMPSession.from_json(session_data)
        else:
            # Sender is Human, use fallback mode
            action, details = self.negotiator.parse_human_reply(
                email.body, self.sessions.get(email.session_id)
            )
            session = self.sessions[email.session_id]
            session.apply_vote(email.sender, ...)
        
        self.sessions[session.session_id] = session
        
        # 2. Check for Consensus
        if session.is_fully_resolved():
            self.send_confirm(session)
            self.notify_owner(session)
            return
        
        # 3. Make Decision
        action, details = self.negotiator.decide(session)
        
        if action == "escalate":
            self.notify_owner_for_decision(session, details["reason"])
        else:
            # accept or counter
            session.apply_vote(self.config["agent"]["email"], ...)
            if details.get("new_options"):
                for item, opts in details["new_options"].items():
                    for opt in opts:
                        session.add_option(item, opt)
            self.send_reply(session, action)
    
    def initiate_meeting(self, topic: str, participant_names: list[str]):
        """Called when human requests a meeting"""
        session_id = f"meeting-{int(time.time())}"
        participants = []
        for name in participant_names:
            contact = self.config["contacts"][name]
            if contact["has_agent"]:
                participants.append(contact["agent_email"])
            else:
                participants.append(contact["human_email"])
        
        session = AIMPSession(session_id, topic, participants)
        # Generate initial proposal based on preferences
        # ...
        self.sessions[session_id] = session
        
        for participant in participants:
            contact = self.find_contact_by_email(participant)
            if contact and contact["has_agent"]:
                self.email.send_aimp_email(...)
            else:
                # Fallback: Send natural language email to human
                body = self.negotiator.generate_human_email(session)
                self.email.send_human_email(participant, f"Meeting Invitation: {topic}", body)
    
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
        """Notify owner of final result"""
        consensus = session.check_consensus()
        body = f"Meeting Confirmed!\nTopic: {session.topic}\nTime: {consensus['time']}\nLocation: {consensus['location']}"
        self.email.send_human_email(self.config["owner"]["email"], f"Meeting Confirmed: {session.topic}", body)
```

-----

## VI. Fallback Compatibility Design

### 6.1 Identify Sender (Agent vs Human)

```python
def is_aimp_email(email) -> bool:
    """Check if email is AIMP protocol email"""
    return (
        "[AIMP:" in email.subject
        and any(a.filename == "protocol.json" for a in email.attachments)
    )
```

On reply: Has `[AIMP:]` prefix + JSON attachment → Agent Mode; otherwise → Human Mode.

### 6.2 Email Template for Humans

```
Subject: Meeting Invitation: Q1 Review

Hi Bob,

Alice would like to schedule a Q1 review meeting with you and Carol.

Does any of the following times work for you?
A. March 1st, Monday, 10:00 AM
B. March 2nd, Tuesday, 2:00 PM

Location preferences?
1. Zoom
2. Office 3F
3. Tencent Meeting

Just reply to this email directly, e.g., "A and 1" or "Monday morning is fine, Zoom".

—— Alice's AI Assistant
```

### 6.3 Parsing Human Reply

Use LLM for NLU:

```
User replied to the meeting invitation email:
"{reply_body}"

Original Options:
Time: A. Mar 1 10:00, B. Mar 2 14:00
Location: 1. Zoom, 2. Office 3F, 3. Tencent Meeting

Please extract the user's choice, return JSON:
{"time": "2026-03-01T10:00" or null, "location": "Zoom" or null, "unclear": "part that is unclear"}
```

-----

## VII. Demo Script run_demo.py

```python
"""
One-click Demo: 3 Agents Negotiating

Usage:
  1. Fill config/agent_a.yaml, agent_b.yaml, agent_c.yaml
  2. Set env var ANTHROPIC_API_KEY
  3. python run_demo.py

Flow:
  - Start 3 Agents (3 threads)
  - Agent-A automatically initiates meeting proposal
  - Observe email interaction
  - Notify owners after consensus
"""
import threading
import time

def run_agent(config_path, initiate=None):
    agent = AIMPAgent(config_path)
    if initiate:
        topic, participants = initiate
        agent.initiate_meeting(topic, participants)
    agent.run(poll_interval=15)  # 15s poll for demo

# Start 3 Agents
threads = [
    threading.Thread(target=run_agent, args=("config/agent_a.yaml",), 
                     kwargs={"initiate": ("Q1 Review", ["Bob", "Carol"])}),
    threading.Thread(target=run_agent, args=("config/agent_b.yaml",)),
    threading.Thread(target=run_agent, args=("config/agent_c.yaml",)),
]

for t in threads:
    t.daemon = True
    t.start()

print("3 Agents started, observing email negotiation...")
print("Press Ctrl+C to exit")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("Demo Ended")
```

-----

## VIII. Preparation Checklist

Before construction:

1. **3 Email Accounts** (Gmail/Outlook/Any IMAP supported), enable IMAP and App Password
1. **One LLM API Key** (Anthropic or OpenAI)
1. **Python 3.10+**
1. **Dependencies**: `imaplib` (stdlib), `smtplib` (stdlib), `pyyaml`, `anthropic` (or `openai`)

-----

## IX. Implementation Priority

Implement in this order, verify each step:

|Step|Module                 |Verification          |
|--|---------------------|------------------|
|1 |`email_client.py`    |Can send/receive emails             |
|2 |`protocol.py`        |Correctly serialize/deserialize JSON  |
|3 |`negotiator.py`      |Given preferences and proposal, LLM returns correct decision|
|4 |`agent.py` Single Agent   |Can receive email and auto-reply        |
|5 |`run_demo.py` 3 Agents|Complete negotiation flow works          |
|6 |Fallback Mode             |Send email to human, parse reply     |

-----

## X. Promotion Strategy (Note to self)

1. **Step 1: Use it yourself**. Run your Agent, send normal emails to everyone to schedule meetings. They don't need to install anything.
2. **When someone gets curious**, give them the README link, they can run it in 5 mins.
3. **Fallback compatibility is the lifeline** — never require the other party to install the Agent to use it.
4. **Demo GIF > 10k words**. Record a 30s demo, put it at the top of README.

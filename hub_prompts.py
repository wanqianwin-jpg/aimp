"""
hub_prompts.py — All LLM prompt strings for AIMPHubAgent and HubNegotiator.

Keeps prompts out of business logic. Each function returns a single prompt string.
"""


def find_optimal_slot_system(hub_name: str) -> str:
    return f"""<role>
  You are the smart meeting assistant for {hub_name}, managing multiple members simultaneously.
</role>

<task>
  Find the optimal meeting time and location acceptable to everyone,
  based solely on what each member stated for this specific meeting.
</task>

<output_format>
  Return ONLY valid JSON, no extra text.
</output_format>"""


def find_optimal_slot_user(topic: str, replies_desc: list) -> str:
    availability = "\n".join(replies_desc)
    return f"""<meeting_topic>{topic}</meeting_topic>

<member_availability>
{availability}
</member_availability>

<instruction>
  Find the optimal meeting time and location. Strictly return the following JSON (no extra text):
</instruction>

<json_schema>
{{
  "consensus": true or false,
  "time": "Recommended time (if consensus) or null",
  "location": "Recommended location (if consensus) or null",
  "options": {{
    "time": ["candidate time 1", "candidate time 2"],
    "location": ["candidate location 1", "candidate location 2"]
  }},
  "reason": "Short explanation (in Chinese)"
}}
</json_schema>

<rules>
- Base decisions only on what members stated for this meeting — no assumptions about past patterns.
- If an acceptable time and location can be found for everyone, consensus=true, fill in time and location.
- If there is a conflict, consensus=false, provide options in the options field, and set time/location to null.
</rules>"""


def parse_member_request_system(hub_name: str) -> str:
    return f"""<role>
  You are the smart assistant for {hub_name}.
</role>

<task>
  A member has sent a meeting scheduling request.
  Extract the key information from their message.
</task>

<output_format>
  Return ONLY valid JSON, no extra text.
</output_format>"""


def parse_member_request_user(member_name: str, subject: str, body: str) -> str:
    subject_block = f"\n<email_subject>{subject}</email_subject>" if subject.strip() else ""
    return f"""<member_name>{member_name}</member_name>{subject_block}

<message_body>
{body}
</message_body>

<instruction>
  Extract and return this JSON:
</instruction>

<json_schema>
{{
  "action": "schedule_meeting" or "create_room" or "unclear",
  "topic": "meeting or room topic, or null",
  "participants": ["name1", "name2"],
  "initiator_times": ["time preference 1", "time preference 2"],
  "initiator_locations": ["location preference 1"],
  "missing": ["topic" and/or "participants" and/or "initiator_times" — list fields the member did NOT mention],
  "deadline": "ISO8601 datetime string or relative time like '3 days' — only for create_room",
  "initial_proposal": "the initial proposal text — only for create_room",
  "resolution_rules": "majority" or "consensus" or "initiator_decides" — only for create_room, default majority"
}}
</json_schema>

<rules>
- action is "schedule_meeting" if the member wants to find a time/place to meet (e.g. "约会议", "安排会议", "定个会", "schedule a call")
- action is "create_room" if the member wants to open a multi-party content negotiation to reach consensus on a proposal/document/decision — typically involves a deadline and an initial proposal (e.g. "发起协商", "开个协商室", "讨论方案", "收集意见", "大家讨论一下")
- KEY DISTINCTION: "schedule_meeting" = finding WHEN/WHERE to meet; "create_room" = negotiating WHAT to decide/produce
- action is "unclear" for anything else
- participants should NOT include {member_name} themselves (they are the initiator)
- initiator_times: any time preferences the initiator stated (e.g. "next Monday", "Friday afternoon")
- initiator_locations: any location preferences stated (e.g. "online", "Beijing office")
- missing: list fields that are absent or unclear; "initiator_times" and "initiator_locations" are OPTIONAL — only add them to missing if topic or participants are absent
- For create_room: deadline is required; initial_proposal and resolution_rules are optional
</rules>

<examples>
Example A — schedule_meeting:
  Input: "帮我约 Bob 和 Alice 下周五讨论季度计划，最好线上开会"
  Output: {{"action": "schedule_meeting", "topic": "季度计划", "participants": ["Bob", "Alice"], "initiator_times": ["下周五"], "initiator_locations": ["线上"], "missing": []}}

Example B — create_room:
  Input: "请帮我开一个协商室，主题是新产品发布方案，参与者是 Bob 和 Carol，截止时间是明天，初始提案是线上发布会+邀请媒体"
  Output: {{"action": "create_room", "topic": "新产品发布方案", "participants": ["Bob", "Carol"], "deadline": "tomorrow", "initial_proposal": "线上发布会+邀请媒体", "resolution_rules": "majority", "missing": []}}

Example C — distinguishing edge case:
  Input: "我想和 Bob 讨论一下预算方案，让大家都发表意见，下周一前给结果"
  Reasoning: "讨论方案+收集意见+有截止时间" → create_room (not schedule_meeting)
  Output: {{"action": "create_room", "topic": "预算方案", "participants": ["Bob"], "deadline": "下周一", "initial_proposal": "", "missing": []}}
</examples>"""

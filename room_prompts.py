"""
room_prompts.py — All LLM prompt strings for Phase 2 Room negotiation.

Keeps prompts out of business logic. Each function returns a single prompt string.
"""
import time
from datetime import datetime, timezone


def parse_amendment_system(hub_name: str) -> str:
    return f"""<role>
  You are the smart meeting assistant for {hub_name}, managing a content negotiation room.
</role>

<task>
  A participant has sent a reply to a content negotiation. Extract the structured
  intent (action and content changes) from their message.
</task>

<output_format>
  Return ONLY valid JSON, no extra text.
</output_format>"""


def parse_amendment_user(member_name: str, body: str, current_artifacts: dict) -> str:
    artifacts_desc = ""
    if current_artifacts:
        parts = []
        for name, art in current_artifacts.items():
            preview = art.get("body_text", "")[:300] if isinstance(art, dict) else str(art)[:300]
            parts.append(f"  [{name}]: {preview}")
        artifacts_desc = "\n".join(parts)
    else:
        artifacts_desc = "  (none yet — this is the initial proposal round)"

    return f"""<participant_name>{member_name}</participant_name>

<current_proposal_artifacts>
{artifacts_desc}
</current_proposal_artifacts>

<participant_message>
{body}
</participant_message>

<instruction>
  Analyze the participant's message and return this JSON:
</instruction>

<json_schema>
{{
  "action": "PROPOSE" or "AMEND" or "ACCEPT" or "REJECT",
  "changes": "Brief description of what they want to add/change/remove (or empty string)",
  "reason": "Their stated reason or motivation (or empty string)",
  "new_content": "The proposed new/amended text if they provided one (or null)"
}}
</json_schema>

<rules>
- PROPOSE: participant is submitting a first draft or new document
- AMEND: participant wants to modify the existing proposal
- ACCEPT: participant agrees with the current state of the proposal
- REJECT: participant disagrees and wants to block or restart
- Extract changes and reason verbatim where possible
- If the message is ambiguous, pick the closest action
</rules>"""


def aggregate_amendments_system(hub_name: str) -> str:
    return f"""<role>
  You are the smart meeting assistant for {hub_name}.
</role>

<task>
  Summarize a content negotiation discussion and identify the current best
  consolidated proposal that reflects all amendments so far.
</task>

<output_format>
  Return ONLY valid JSON, no extra text.
</output_format>"""


def aggregate_amendments_user(topic: str, transcript: list, deadline: float) -> str:
    try:
        deadline_str = datetime.fromtimestamp(deadline, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"
        )
    except Exception:
        deadline_str = str(deadline)

    transcript_text = ""
    for entry in transcript:
        if isinstance(entry, dict):
            transcript_text += (
                f"  [{entry.get('version', '?')}] {entry.get('from', '?')} "
                f"({entry.get('action', '?')}): {entry.get('summary', '')}\n"
            )
        else:
            transcript_text += f"  {entry}\n"

    return f"""<room_topic>{topic}</room_topic>

<deadline>{deadline_str}</deadline>

<discussion_transcript>
{transcript_text or "  (empty — no entries yet)"}
</discussion_transcript>

<instruction>
  Based on the discussion, produce a consolidated view. Return this JSON:
</instruction>

<json_schema>
{{
  "current_proposal": "The best current merged proposal text incorporating all accepted amendments",
  "conflicts": ["List of unresolved conflicts or objections, if any"],
  "ready_to_finalize": true or false,
  "summary": "One-sentence summary of where the negotiation stands"
}}
</json_schema>

<rules>
- ready_to_finalize = true only if there are no blocking conflicts
- current_proposal should be a coherent, complete version of the proposal
- If participants are still in conflict, describe each conflict point clearly
</rules>"""


def generate_minutes_system(hub_name: str) -> str:
    return f"""<role>
  You are the smart meeting assistant for {hub_name}.
</role>

<task>
  Generate a human-readable meeting minutes document (in Markdown) from a
  completed content negotiation room's transcript and final resolution.
</task>

<output_format>
  Return ONLY the Markdown document text, no JSON wrapper.
</output_format>"""


def generate_minutes_user(
    topic: str,
    transcript: list,
    resolution: str,
    participants: list[str],
) -> str:
    transcript_text = ""
    for entry in transcript:
        if isinstance(entry, dict):
            ts = entry.get("version", "")
            actor = entry.get("from", "unknown")
            action = entry.get("action", "")
            summary = entry.get("summary", "")
            transcript_text += f"- **[{ts}]** `{actor}` — **{action}**: {summary}\n"
        else:
            transcript_text += f"- {entry}\n"

    participants_str = "\n".join(f"  - {p}" for p in participants)

    return f"""<topic>{topic}</topic>

<participants>
{participants_str}
</participants>

<discussion_transcript>
{transcript_text or "  (no discussion recorded)"}
</discussion_transcript>

<final_resolution>
{resolution}
</final_resolution>

<instruction>
  Write a professional meeting minutes document in Markdown. Include:
  1. Title with topic and date
  2. Participants list
  3. Discussion summary (key proposals, amendments, and objections)
  4. Final resolution / agreed outcome
  5. Next steps (if any can be inferred)

  Use clear headings. Be concise but complete. Write in the same language as
  the topic and transcript (Chinese or English).
</instruction>"""

"""lib/room_negotiator.py — RoomNegotiator: Phase 2 LLM helpers for content negotiation."""
from __future__ import annotations
import logging

from lib.negotiator import make_llm_client, call_llm, extract_json
from lib.protocol import AIMPRoom
from room_prompts import (
    parse_amendment_system,
    parse_amendment_user,
    aggregate_amendments_system,
    aggregate_amendments_user,
    generate_minutes_system,
    generate_minutes_user,
)

logger = logging.getLogger(__name__)


class RoomNegotiator:
    """
    LLM helper for Phase 2 content negotiation rooms. /
    Phase 2 内容协商 Room 的 LLM 工具。
    """

    def __init__(self, hub_name: str, hub_email: str, llm_config: dict):
        self.hub_name = hub_name
        self.hub_email = hub_email
        self.client, self.model, self.provider = make_llm_client(llm_config)

    def parse_amendment(self, member_name: str, body: str, current_artifacts: dict) -> dict:
        """
        Parse a participant's reply into a structured amendment action. /
        将参与者的回复解析为结构化的修正动作。

        Returns: {action: PROPOSE/AMEND/ACCEPT/REJECT, changes: str, reason: str, new_content: str|None}
        """
        system = parse_amendment_system(self.hub_name)
        user = parse_amendment_user(member_name, body, current_artifacts)
        try:
            raw = call_llm(self.client, self.model, self.provider, system, user)
            result = extract_json(raw)
            logger.debug(f"RoomNegotiator.parse_amendment result: {result}")
            return result
        except Exception as e:
            logger.error(f"parse_amendment LLM failed: {e}")
            return {
                "action": "AMEND",
                "changes": body[:200],
                "reason": f"LLM parse failed: {e}",
                "new_content": None,
            }

    def aggregate_amendments(self, room: AIMPRoom) -> dict:
        """
        Aggregate all amendments and return the current consolidated proposal. /
        汇总所有修正，返回当前最优提案。

        Returns: {current_proposal: str, conflicts: list, ready_to_finalize: bool, summary: str}
        """
        transcript_dicts = [h.to_dict() for h in room.transcript]
        system = aggregate_amendments_system(self.hub_name)
        user = aggregate_amendments_user(room.topic, transcript_dicts, room.deadline)
        try:
            raw = call_llm(self.client, self.model, self.provider, system, user)
            result = extract_json(raw)
            logger.debug(f"RoomNegotiator.aggregate_amendments result: {result}")
            return result
        except Exception as e:
            logger.error(f"aggregate_amendments LLM failed: {e}")
            return {
                "current_proposal": "(LLM aggregation failed)",
                "conflicts": [str(e)],
                "ready_to_finalize": False,
                "summary": "Aggregation error",
            }

    def generate_meeting_minutes(self, room: AIMPRoom) -> str:
        """
        Generate Markdown meeting minutes from the room's transcript. /
        从 Room 讨论记录生成 Markdown 格式会议纪要。

        Returns: Markdown string
        """
        transcript_dicts = [h.to_dict() for h in room.transcript]
        # Build resolution summary from latest aggregation
        agg = self.aggregate_amendments(room)
        resolution = agg.get("current_proposal", "(no proposal)")

        system = generate_minutes_system(self.hub_name)
        user = generate_minutes_user(room.topic, transcript_dicts, resolution, room.participants)
        try:
            raw = call_llm(self.client, self.model, self.provider, system, user)
            logger.debug(f"RoomNegotiator.generate_meeting_minutes: generated {len(raw)} chars")
            return raw.strip()
        except Exception as e:
            logger.error(f"generate_meeting_minutes LLM failed: {e}")
            lines = [
                f"# Meeting Minutes: {room.topic}",
                "",
                f"**Room ID:** {room.room_id}",
                f"**Participants:** {', '.join(room.participants)}",
                f"**Status:** {room.status}",
                "",
                "## Final Resolution",
                "",
                resolution,
                "",
                "## Discussion Log",
                "",
            ]
            for entry in room.transcript:
                lines.append(
                    f"- [{entry.version}] {entry.from_agent} ({entry.action}): {entry.summary}"
                )
            return "\n".join(lines)

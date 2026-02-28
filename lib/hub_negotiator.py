"""lib/hub_negotiator.py — HubNegotiator: Hub-side LLM helper for aggregating member votes."""
from __future__ import annotations
import logging

from lib.negotiator import make_llm_client, call_llm, extract_json
from hub_prompts import find_optimal_slot_system, find_optimal_slot_user

logger = logging.getLogger(__name__)


class HubNegotiator:
    """
    Hub-side LLM helper for aggregating member vote replies and finding consensus.
    Used AFTER votes are collected — not for pre-generating options from static config.
    / Hub 侧 LLM 工具：汇总成员投票回复、寻找共识。
      在收到真实投票后调用——不用于从静态 config 偏好预生成选项。
    """
    def __init__(self, hub_name: str, hub_email: str, llm_config: dict):
        self.hub_name = hub_name
        self.hub_email = hub_email
        self.client, self.model, self.provider = make_llm_client(llm_config)

    def find_optimal_slot(
        self,
        topic: str,
        member_replies: dict[str, dict],
    ) -> dict:
        """
        Aggregate THIS meeting's availability replies and find the optimal consensus slot.
        Call this AFTER all members have replied to the availability request for this session.
        Data must come from members' actual replies for this specific meeting — never from
        stored profiles or historical data.
        / 汇总本次会议收集到的可用时间回复，找出最优共识时间/地点。
          所有成员回复本次可用时间后调用。
          数据必须来自成员对本次会议的实际回复——禁止使用存档资料或历史数据。

        Args:
            topic: Meeting topic / 会议主题
            member_replies: {member_id: {"name":..., "available_times":..., "preferred_locations":...}}
                            All fields reflect what each member stated for THIS meeting only.

        Returns:
            {
              "consensus": True/False,
              "time": "...",          # If consensus reached / 如果有共识
              "location": "...",      # If consensus reached / 如果有共识
              "options": {"time": [...], "location": [...]},  # Candidates / 候选列表
              "reason": "...",
            }
        """
        replies_desc = []
        for mid, p in member_replies.items():
            replies_desc.append(
                f"- {p.get('name', mid)}: Available Times={p.get('available_times', [])}, "
                f"Preferred Locations={p.get('preferred_locations', [])}"
            )

        system = find_optimal_slot_system(self.hub_name)
        user = find_optimal_slot_user(topic, replies_desc)
        try:
            raw = call_llm(self.client, self.model, self.provider, system, user)
            result = extract_json(raw)
            logger.debug(f"HubNegotiator.find_optimal_slot result: {result}")
            return result
        except Exception as e:
            logger.error(f"Hub LLM scheduling failed: {e} / Hub LLM 调度失败: {e}")
            return {
                "consensus": False,
                "time": None,
                "location": None,
                "options": {"time": [], "location": []},
                "reason": f"LLM call failed: {e} / LLM 调用失败: {e}",
            }

    def generate_member_notify_body(
        self,
        topic: str,
        result: dict,
        initiator_name: str,
        participant_names: list[str],
    ) -> str:
        """生成通知 member 的消息正文"""
        if result.get("consensus"):
            return (
                f"✅ 会议已安排好！\n\n"
                f"主题：{topic}\n"
                f"时间：{result['time']}\n"
                f"地点：{result['location']}\n\n"
                f"参与者：{', '.join(participant_names)}\n"
                f"（由 {self.hub_name} 自动协调）"
            )
        else:
            opts = result.get("options", {})
            t_opts = "\n".join(f"  - {t}" for t in opts.get("time", []))
            l_opts = "\n".join(f"  - {l}" for l in opts.get("location", []))
            return (
                f"⚠️ 无法自动找到所有人都接受的时间，需要你决策。\n\n"
                f"主题：{topic}\n"
                f"原因：{result.get('reason', '')}\n\n"
                f"候选时间：\n{t_opts or '  （无）'}\n\n"
                f"候选地点：\n{l_opts or '  （无）'}\n\n"
                f"请回复你的偏好。"
            )

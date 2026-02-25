"""
negotiator.py — 调用 LLM 做协商决策
"""
from __future__ import annotations
import json
import logging
from typing import Optional

from lib.protocol import AIMPSession

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────
# LLM Client 工厂
# ──────────────────────────────────────────────────────
def make_llm_client(llm_config: dict):
    provider = llm_config.get("provider", "anthropic")
    api_key_env = llm_config.get("api_key_env", "ANTHROPIC_API_KEY")
    import os
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise ValueError(f"环境变量 {api_key_env} 未设置")

    if provider == "anthropic":
        import anthropic
        return anthropic.Anthropic(api_key=api_key), llm_config.get("model", "claude-sonnet-4-5-20250514"), "anthropic"
    elif provider == "openai":
        import openai
        return openai.OpenAI(api_key=api_key), llm_config.get("model", "gpt-4o"), "openai"
    else:
        raise ValueError(f"不支持的 LLM provider: {provider}")


def call_llm(client, model: str, provider: str, system: str, user: str) -> str:
    """统一调用接口，返回文本"""
    if provider == "anthropic":
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text
    elif provider == "openai":
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content
    raise ValueError(f"未知 provider: {provider}")


def extract_json(text: str) -> dict:
    """从 LLM 回复中提取 JSON 块"""
    import re
    # 优先提取 ```json ... ``` 块
    m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if m:
        return json.loads(m.group(1))
    # 否则尝试直接解析
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        return json.loads(text[start:end])
    raise ValueError(f"无法从 LLM 回复中提取 JSON:\n{text}")


# ──────────────────────────────────────────────────────
# Negotiator
# ──────────────────────────────────────────────────────
class Negotiator:
    def __init__(self, owner_name: str, agent_email: str, preferences: dict, llm_config: dict):
        self.owner_name = owner_name
        self.agent_email = agent_email
        self.preferences = preferences
        self.client, self.model, self.provider = make_llm_client(llm_config)

    # ── 核心决策 ──────────────────────────────────────

    def decide(self, session: AIMPSession) -> tuple[str, dict]:
        """
        输入当前会话状态，输出 (action, details)
        action: accept | counter | escalate
        details: {"votes": {...}, "new_options": {...}, "reason": "..."}
        """
        system = self._system_prompt()
        user = self._decide_prompt(session)

        try:
            raw = call_llm(self.client, self.model, self.provider, system, user)
            result = extract_json(raw)
            logger.debug(f"LLM decide 原始结果: {result}")
        except Exception as e:
            logger.error(f"LLM 决策失败，降级为 escalate: {e}")
            return "escalate", {"reason": f"LLM 调用失败: {e}"}

        action = result.get("action", "escalate")
        if action not in ("accept", "counter", "escalate"):
            action = "escalate"

        details = {
            "votes": result.get("votes", {}),
            "new_options": result.get("new_options", {}),
            "reason": result.get("reason", ""),
        }
        return action, details

    def parse_human_reply(self, reply_body: str, session: AIMPSession) -> tuple[str, dict]:
        """
        用 LLM 解析人类自由文本回复，提取投票意向。
        返回 (action, details)
        """
        consensus = session.check_consensus()
        options_desc = []
        for item_name, proposal in session.proposals.items():
            opts = ", ".join(f"{chr(65+i)}. {o}" for i, o in enumerate(proposal.options))
            options_desc.append(f"{item_name}: {opts}")

        system = "你是一个会议协调助手，负责解析人类对会议邀请的回复。"
        user = f"""用户回复了这封会议邀请邮件，内容是：
\"{reply_body}\"

原始选项：
{chr(10).join(options_desc)}

请提取用户的选择，严格返回如下 JSON（不要多余文字）：
{{
  "votes": {{"time": "精确的时间字符串或null", "location": "精确的地点字符串或null"}},
  "unclear": "无法理解的部分，如果全部清楚则为null",
  "action": "accept 或 counter 或 escalate"
}}
"""
        try:
            raw = call_llm(self.client, self.model, self.provider, system, user)
            result = extract_json(raw)
        except Exception as e:
            logger.error(f"解析人类回复失败: {e}")
            return "escalate", {"reason": f"无法解析人类回复: {e}"}

        action = result.get("action", "counter")
        votes = result.get("votes", {})
        # 过滤掉 null 值
        votes = {k: v for k, v in votes.items() if v is not None}
        return action, {"votes": votes, "reason": result.get("unclear", "")}

    def generate_human_readable_summary(self, session: AIMPSession, action: str, reason: str = "") -> str:
        """生成邮件正文的人类可读摘要"""
        consensus = session.check_consensus()
        lines = []
        lines.append(f"主题：{session.topic}")
        lines.append(f"当前状态：{action}（第 {session.version} 版）")
        lines.append("")

        for item_name, proposal in session.proposals.items():
            resolved = consensus.get(item_name)
            if resolved:
                lines.append(f"✓ {item_name}：已确认 → {resolved}")
            else:
                opts = "\n".join(f"  {chr(65+i)}. {o}" for i, o in enumerate(proposal.options))
                lines.append(f"? {item_name} 选项：\n{opts}")
                vote_summary = ", ".join(
                    f"{e.split('@')[0]}→{v or '未投'}"
                    for e, v in proposal.votes.items()
                )
                lines.append(f"  当前投票：{vote_summary}")

        if reason:
            lines.append(f"\n备注：{reason}")

        return "\n".join(lines)

    def generate_human_email_body(self, session: AIMPSession) -> str:
        """给人类（非 Agent）发送的会议邀请邮件正文"""
        options_blocks = []
        for item_name, proposal in session.proposals.items():
            opts = "\n".join(f"{chr(65+i)}. {o}" for i, o in enumerate(proposal.options))
            if item_name == "time":
                options_blocks.append(f"以下时间你方便吗？\n{opts}")
            elif item_name == "location":
                options_blocks.append(f"地点偏好？\n{opts}")
            else:
                options_blocks.append(f"{item_name}？\n{opts}")

        body = f"""Hi，

{self.owner_name} 想邀请你参加：{session.topic}

{chr(10).join(options_blocks)}

---
请直接回复这封邮件告诉我就行。
例如："A 和 1" 或者 "周一上午可以，Zoom 开会"。
(我是 {self.owner_name} 的 AI 助理，我会自动处理您的回复)
"""
        return body

    def generate_confirm_summary(self, session: AIMPSession) -> str:
        """达成共识后生成确认摘要"""
        consensus = session.check_consensus()
        lines = [
            f"会议已确定！",
            f"主题：{session.topic}",
        ]
        for item, val in consensus.items():
            lines.append(f"{item}：{val}")
        return "\n".join(lines)

    # ── 内部 Prompt ───────────────────────────────────

    def _system_prompt(self) -> str:
        prefs = self.preferences
        return f"""你是一个会议协调助手。你的主人是 {self.owner_name}。

主人的偏好：
- 偏好时间：{prefs.get('preferred_times', [])}
- 屏蔽时间：{prefs.get('blocked_times', [])}
- 偏好地点：{prefs.get('preferred_locations', [])}
- 自动接受（完全匹配时）：{prefs.get('auto_accept', True)}

你需要代表主人参与会议时间和地点的协商。
"""

    def _decide_prompt(self, session: AIMPSession) -> str:
        session_json = json.dumps(session.to_json(), ensure_ascii=False, indent=2)
        return f"""当前协商状态（JSON）：
{session_json}

请判断当前提议是否匹配主人偏好，严格返回如下 JSON（不要多余文字）：
{{
  "action": "accept" 或 "counter" 或 "escalate",
  "votes": {{"time": "选择的时间字符串或null", "location": "选择的地点字符串或null"}},
  "new_options": {{"time": ["新提议时间列表"], "location": ["新提议地点列表"]}},
  "reason": "简短说明（中文）"
}}

规则：
- 如果当前选项中有完全符合偏好的，选择它，action=accept，votes 填入选择。
- 如果部分符合但想提议替代方案，action=counter，votes 填已匹配的，new_options 填新方案。
- 如果完全无法判断或超出范围，action=escalate。
- new_options 仅在 counter 时才有内容，其他时候为空对象。
"""

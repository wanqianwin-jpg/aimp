"""
negotiator.py — Call LLM for negotiation decisions / 调用 LLM 做协商决策
"""
from __future__ import annotations
import json
import logging
from typing import Optional

from lib.protocol import AIMPSession

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────
# LLM Client Factory / LLM 客户端工厂
# ──────────────────────────────────────────────────────
def make_llm_client(llm_config: dict):
    """
    Create LLM client based on configuration / 根据配置创建 LLM 客户端
    Args:
        llm_config: LLM configuration dictionary / LLM 配置字典
    Returns:
        (client, model, provider)
    """
    provider = llm_config.get("provider", "anthropic")
    api_key_env = llm_config.get("api_key_env", "ANTHROPIC_API_KEY")
    base_url = llm_config.get("base_url")  # For Ollama/LM Studio support / 用于支持 Ollama/LM Studio
    import os
    
    # Local models usually don't need an API Key / 本地模型通常不需要 API Key
    api_key = os.environ.get(api_key_env, "sk-no-key-needed")
    
    if provider == "anthropic":
        import anthropic
        return anthropic.Anthropic(api_key=api_key), llm_config.get("model", "claude-sonnet-4-5-20250514"), "anthropic"
    elif provider == "openai" or provider == "local":
        import openai
        # If local provider with base_url, connect to local API / 如果是 local provider 且提供了 base_url，则连接本地 API
        client = openai.OpenAI(api_key=api_key, base_url=base_url)
        model = llm_config.get("model", "gpt-4o")
        return client, model, "openai"
    else:
        raise ValueError(f"Unsupported LLM provider: {provider} / 不支持的 LLM provider: {provider}")


def call_llm(client, model: str, provider: str, system: str, user: str) -> str:
    """Unified calling interface, returns text / 统一调用接口，返回文本"""
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
    raise ValueError(f"Unknown provider: {provider} / 未知 provider: {provider}")


def extract_json(text: str) -> dict:
    """Extract JSON block from LLM response / 从 LLM 回复中提取 JSON 块"""
    import re
    # Priority: extract ```json ... ``` block / 优先提取 ```json ... ``` 块
    m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if m:
        return json.loads(m.group(1))
    # Otherwise try direct parsing / 否则尝试直接解析
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        return json.loads(text[start:end])
    raise ValueError(f"Could not extract JSON from LLM response / 无法从 LLM 回复中提取 JSON:\n{text}")


# ──────────────────────────────────────────────────────
# Negotiator
# ──────────────────────────────────────────────────────
class Negotiator:
    def __init__(self, owner_name: str, agent_email: str, preferences: dict, llm_config: dict):
        """
        Initialize Negotiator / 初始化 Negotiator
        Args:
            owner_name: Owner's name / 主人姓名
            agent_email: Agent's email address / Agent 邮箱地址
            preferences: Owner's meeting preferences / 主人会议偏好
            llm_config: LLM configuration / LLM 配置
        """
        self.owner_name = owner_name
        self.agent_email = agent_email
        self.preferences = preferences
        self.client, self.model, self.provider = make_llm_client(llm_config)

    # ── Core Decision / 核心决策 ──────────────────────────────────────

    def decide(self, session: AIMPSession) -> tuple[str, dict]:
        """
        Input current session state, output (action, details) /
        输入当前会话状态，输出 (action, details)
        action: accept | counter | escalate
        details: {"votes": {...}, "new_options": {...}, "reason": "..."}
        """
        system = self._system_prompt()
        user = self._decide_prompt(session)

        try:
            raw = call_llm(self.client, self.model, self.provider, system, user)
            result = extract_json(raw)
            logger.debug(f"LLM decide raw result / LLM decide 原始结果: {result}")
        except Exception as e:
            logger.error(f"LLM decision failed, falling back to escalate / LLM 决策失败，降级为 escalate: {e}")
            return "escalate", {"reason": f"LLM call failed / LLM 调用失败: {e}"}

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
        Parse human free-text reply using LLM to extract voting intentions. /
        用 LLM 解析人类自由文本回复，提取投票意向。
        Returns (action, details)
        """
        consensus = session.check_consensus()
        options_desc = []
        for item_name, proposal in session.proposals.items():
            opts = ", ".join(f"{chr(65+i)}. {o}" for i, o in enumerate(proposal.options))
            options_desc.append(f"{item_name}: {opts}")

        system = "You are a meeting coordination assistant responsible for parsing human replies to meeting invitations. / 你是一个会议协调助手，负责解析人类对会议邀请的回复。"
        user = f"""The user replied to this meeting invitation email with the following content: / 用户回复了这封会议邀请邮件，内容是：
\"{reply_body}\"

Original Options: / 原始选项：
{chr(10).join(options_desc)}

Please extract the user's choices and return strictly as JSON (no extra text): / 请提取用户的选择，严格返回如下 JSON（不要多余文字）：
{{
  "votes": {{"time": "exact time string or null / 精确的时间字符串或null", "location": "exact location string or null / 精确的地点字符串或null"}},
  "unclear": "unclear parts, null if everything is clear / 无法理解的部分，如果全部清楚则为null",
  "action": "accept | counter | escalate"
}}
"""
        try:
            raw = call_llm(self.client, self.model, self.provider, system, user)
            result = extract_json(raw)
        except Exception as e:
            logger.error(f"Failed to parse human reply / 解析人类回复失败: {e}")
            return "escalate", {"reason": f"Could not parse human reply / 无法解析人类回复: {e}"}

        action = result.get("action", "counter")
        votes = result.get("votes", {})
        # Filter out null values / 过滤掉 null 值
        votes = {k: v for k, v in votes.items() if v is not None}
        return action, {"votes": votes, "reason": result.get("unclear", "")}

    def generate_human_readable_summary(self, session: AIMPSession, action: str, reason: str = "") -> str:
        """Generate human-readable summary for email body / 生成邮件正文的人类可读摘要"""
        consensus = session.check_consensus()
        lines = []
        lines.append(f"Subject / 主题：{session.topic}")
        lines.append(f"Current Status / 当前状态：{action} (v{session.version})")
        lines.append("")

        for item_name, proposal in session.proposals.items():
            resolved = consensus.get(item_name)
            if resolved:
                lines.append(f"✓ {item_name}: Confirmed / 已确认 → {resolved}")
            else:
                opts = "\n".join(f"  {chr(65+i)}. {o}" for i, o in enumerate(proposal.options))
                lines.append(f"? {item_name} Options / 选项：\n{opts}")
                vote_summary = ", ".join(
                    f"{e.split('@')[0]}→{v or 'None / 未投'}"
                    for e, v in proposal.votes.items()
                )
                lines.append(f"  Current Votes / 当前投票：{vote_summary}")

        if reason:
            lines.append(f"\nNotes / 备注：{reason}")

        return "\n".join(lines)

    def generate_human_email_body(self, session: AIMPSession) -> str:
        """Meeting invitation email body for human participants / 给人类（非 Agent）发送的会议邀请邮件正文"""
        options_blocks = []
        for item_name, proposal in session.proposals.items():
            opts = "\n".join(f"{chr(65+i)}. {o}" for i, o in enumerate(proposal.options))
            if item_name == "time":
                options_blocks.append(f"Are the following times convenient for you? / 以下时间你方便吗？\n{opts}")
            elif item_name == "location":
                options_blocks.append(f"Location preference? / 地点偏好？\n{opts}")
            else:
                options_blocks.append(f"{item_name}?\n{opts}")

        body = f"""Hi,

{self.owner_name} would like to invite you to a meeting: {session.topic}
{self.owner_name} 想邀请你参加一个会议：{session.topic}

{chr(10).join(options_blocks)}

---
How to reply / 如何回复：

Just reply to this email in natural language. Examples:
直接回复这封邮件即可，用自然语言就行。举例：

  "Tuesday 10am works, Zoom is fine."
  "周二上午可以，Zoom 开会。"
  "A and 1"

I am {self.owner_name}'s AI meeting assistant. I will read your reply and coordinate automatically.
我是 {self.owner_name} 的 AI 会议助手，我会自动读取你的回复并协调。

If you also have an AI assistant, it can reply on your behalf using the AIMP protocol (attach protocol.json).
如果你也有 AI 助手，它可以用 AIMP 协议代你回复（附带 protocol.json）。
"""
        return body

    def generate_confirm_summary(self, session: AIMPSession) -> str:
        """Generate confirmation summary after consensus / 达成共识后生成确认摘要"""
        consensus = session.check_consensus()
        lines = [
            f"Meeting Confirmed! / 会议已确定！",
            f"Subject / 主题：{session.topic}",
        ]
        for item, val in consensus.items():
            lines.append(f"{item}: {val} / {item}：{val}")
        return "\n".join(lines)

    # ── Internal Prompts / 内部 Prompt ───────────────────────────────────

    def _system_prompt(self) -> str:
        prefs = self.preferences
        return f"""You are a meeting coordination assistant. Your owner is {self.owner_name}. / 你是一个会议协调助手。你的主人是 {self.owner_name}。

Owner's Preferences: / 主人的偏好：
- Preferred Times / 偏好时间：{prefs.get('preferred_times', [])}
- Blocked Times / 屏蔽时间：{prefs.get('blocked_times', [])}
- Preferred Locations / 偏好地点：{prefs.get('preferred_locations', [])}
- Auto Accept (on exact match) / 自动接受（完全匹配时）：{prefs.get('auto_accept', True)}

You need to negotiate meeting times and locations on behalf of your owner. / 你需要代表主人参与会议时间和地点的协商。
"""

    def _decide_prompt(self, session: AIMPSession) -> str:
        session_json = json.dumps(session.to_json(), ensure_ascii=False, indent=2)
        return f"""Current Negotiation Status (JSON) / 当前协商状态（JSON）：
{session_json}

Please determine if the current proposal matches the owner's preferences and return strictly as JSON (no extra text): / 请判断当前提议是否匹配主人偏好，严格返回如下 JSON（不要多余文字）：
{{
  "action": "accept" | "counter" | "escalate",
  "votes": {{"time": "selected time string or null / 选择的时间字符串或null", "location": "selected location string or null / 选择的地点字符串或null"}},
  "new_options": {{"time": ["new time list / 新提议时间列表"], "location": ["new location list / 新提议地点列表"]}},
  "reason": "short explanation (in English and Chinese) / 简短说明（双语）"
}}

Rules: / 规则：
- If any current option perfectly matches preferences, select it, set action=accept, and fill in votes. / 如果当前选项中有完全符合偏好的，选择它，action=accept，votes 填入选择。
- If partially matching but you want to propose alternatives, set action=counter, fill in matched votes, and provide new_options. / 如果部分符合但想提议替代方案，action=counter，votes 填已匹配的，new_options 填新方案。
- If completely unable to determine or out of scope, set action=escalate. / 如果完全无法判断或超出范围，action=escalate。
- new_options should only contain data during a 'counter' action, otherwise it should be an empty object. / new_options 仅在 counter 时才有内容，其他时候为空对象。
"""

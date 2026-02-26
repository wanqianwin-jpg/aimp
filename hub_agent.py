"""
hub_agent.py — AIMP Hub Mode / AIMP Hub 模式

A Hub instance serves multiple Humans (members). / 一个 Hub 实例服务多个 Human（members）。

Key advantages / 核心优势：
  - Identity Recognition: Automatically identifies which member is sending commands via a whitelist of sender emails / 身份识别：通过发件人邮箱白名单自动识别是哪个 member 在发指令
  - God's View: Meetings between Hub members read everyone's preferences directly, results in 1 LLM call, no email negotiation needed / 上帝视角：Hub 内部成员之间开会，直接读取所有人偏好，1 次 LLM 调用出结果，无需邮件协商
  - External Transparency: Hub still follows standard AIMP email negotiation with external people/agents / 对外透明：Hub 与外部人/外部 Agent 之间仍走标准 AIMP 邮件协商

Configuration format (two types, auto-detected) / 配置格式（两种，自动检测）：
  hub mode: Top level has "mode: hub" or "hub:" + "members:" fields / hub 模式：顶层有 "mode: hub" 或者顶层有 "hub:" + "members:" 字段
  standalone mode: Top level has "owner:" field -> degrades to standard AIMPAgent / standalone 模式：顶层有 "owner:" 字段 → 退化为标准 AIMPAgent
"""
from __future__ import annotations
import logging
import sys
import time
import os
import uuid
from typing import Optional

import yaml

from lib.email_client import EmailClient, ParsedEmail, is_aimp_email, extract_protocol_json
from lib.protocol import AIMPSession
from lib.negotiator import Negotiator, make_llm_client, call_llm, extract_json
from lib.session_store import SessionStore
from lib.output import emit_event
from agent import AIMPAgent

logger = logging.getLogger(__name__)


def load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ──────────────────────────────────────────────────────
# Hub Negotiator: Supports multi-user preference aggregation / 支持多用户偏好汇总
# ──────────────────────────────────────────────────────

class HubNegotiator:
    """
    Extended Negotiator supporting "God's View" — / 扩展版 Negotiator，支持"上帝视角"——
    One LLM call aggregates all members' preferences to find the optimal intersection. /
    一次 LLM 调用汇总所有 members 的偏好，直接找出最优交集。
    """
    def __init__(self, hub_name: str, hub_email: str, llm_config: dict):
        self.hub_name = hub_name
        self.hub_email = hub_email
        self.client, self.model, self.provider = make_llm_client(llm_config)

    def find_optimal_slot(
        self,
        topic: str,
        member_prefs: dict[str, dict],
    ) -> dict:
        """
        Aggregate all participant preferences and find the optimal time/location. /
        汇总所有参与者偏好，找出最优时间/地点。

        Args:
            topic: Meeting topic / 会议主题
            member_prefs: {member_id: {"name":..., "preferred_times":..., "blocked_times":..., "preferred_locations":...}}

        Returns:
            {
              "consensus": True/False,
              "time": "...",          # If consensus reached / 如果有共识
              "location": "...",      # If consensus reached / 如果有共识
              "options": {"time": [...], "location": [...]},  # Candidates / 候选列表
              "reason": "...",
            }
        """
        prefs_desc = []
        for mid, p in member_prefs.items():
            prefs_desc.append(
                f"- {p.get('name', mid)}: Preferred Times={p.get('preferred_times', [])}, "
                f"Blocked Times={p.get('blocked_times', [])}, Preferred Locations={p.get('preferred_locations', [])}"
            )

        system = (
            f"You are the smart meeting assistant for {self.hub_name}, managing multiple members simultaneously. "
            "Your task is to find the optimal meeting time and location acceptable to everyone."
        )
        user = f"""Meeting Topic: {topic}

Preferences of all participants:
{chr(10).join(prefs_desc)}

Please help find the optimal meeting time and location for everyone. Strictly return the following JSON (no extra text):
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

Rules:
- If an acceptable time and location can be found for everyone, consensus=true, fill in time and location.
- If there is a conflict, consensus=false, provide options in the options field, and set time/location to null.
- Strictly forbidden to schedule during anyone's blocked times.
"""
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


# ──────────────────────────────────────────────────────
# AIMPHubAgent
# ──────────────────────────────────────────────────────

class AIMPHubAgent(AIMPAgent):
    """
    Hub 模式 Agent。继承 AIMPAgent，覆写关键行为：
      1. 接收来自 member 的 IM/邮件指令时，先识别身份
      2. Hub 内成员之间的会议直接走内部调度（无邮件）
      3. 跟外部人/外部 Agent 协商时走标准邮件流程（复用父类）
    """

    def __init__(self, config_path: str, notify_mode: str = "email", db_path: str = None):
        config = load_yaml(config_path)

        # 将 hub config 适配成父类期望的 standalone config 格式
        hub_cfg = config.get("hub", {})
        adapted = {
            "agent": {
                "name": hub_cfg.get("name", "Hub Assistant"),
                "email": hub_cfg["email"],
                "imap_server": hub_cfg["imap_server"],
                "smtp_server": hub_cfg["smtp_server"],
                "imap_port": hub_cfg.get("imap_port", 993),
                "smtp_port": hub_cfg.get("smtp_port", 465),
                "password": hub_cfg.get("password", ""),
                "auth_type": hub_cfg.get("auth_type", "basic"),
                "oauth_params": hub_cfg.get("oauth_params", {}),
            },
            # 父类需要 owner，Hub 模式用 admin member 顶替
            "owner": self._get_admin_owner(config),
            "preferences": {},  # Hub 本身无偏好，由 members 各自有
            "contacts": config.get("contacts", {}),
            "llm": config.get("llm", {}),
        }

        # 写临时适配 config（父类 __init__ 要读文件）
        import tempfile, json
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            yaml.dump(adapted, f, allow_unicode=True)
            self._adapted_config_path = f.name

        super().__init__(self._adapted_config_path, notify_mode=notify_mode, db_path=db_path)

        # Hub 额外属性
        self._raw_config = config
        self.members: dict[str, dict] = config.get("members", {})
        self.hub_email: str = hub_cfg["email"]
        self.hub_name: str = hub_cfg.get("name", "Hub Assistant")

        # 邮箱 → member_id 的反向索引（用于身份识别）
        self._email_to_member: dict[str, str] = {}
        for mid, m in self.members.items():
            if m.get("email"):
                self._email_to_member[m["email"].lower()] = mid

        # Hub 专用 Negotiator
        self.hub_negotiator = HubNegotiator(
            hub_name=self.hub_name,
            hub_email=self.hub_email,
            llm_config=config.get("llm", {}),
        )

    def _get_admin_owner(self, config: dict) -> dict:
        """从 members 中找 admin 作为 owner，找不到就用第一个"""
        members = config.get("members", {})
        for mid, m in members.items():
            if m.get("role") == "admin":
                return {"name": m.get("name", mid), "email": m.get("email", "")}
        # fallback: 第一个 member
        if members:
            first_id = next(iter(members))
            m = members[first_id]
            return {"name": m.get("name", first_id), "email": m.get("email", "")}
        return {"name": "Hub Admin", "email": ""}

    def __del__(self):
        # 清理临时 config 文件
        try:
            if hasattr(self, "_adapted_config_path") and os.path.exists(self._adapted_config_path):
                os.unlink(self._adapted_config_path)
        except Exception:
            pass

    # ── 身份识别 ──────────────────────────────────────

    def identify_sender(self, from_email: str) -> Optional[str]:
        """
        从发件人邮箱识别 member_id。
        未在白名单中 → 返回 None（陌生人，拒绝服务）。
        """
        return self._email_to_member.get(from_email.lower())

    # ── 发起会议（Hub 版覆写） ─────────────────────────

    def initiate_meeting(
        self,
        topic: str,
        participant_names: list[str],
        initiator_member_id: Optional[str] = None,
    ) -> str:
        """
        Hub 版发起会议：
          - 先检查 participant_names 中哪些是 Hub 内 members，哪些是外部联系人
          - Hub 内部成员之间：直接上帝视角调度，不发邮件
          - 有外部参与者：走标准 AIMP 邮件协商（复用父类逻辑）
        """
        # ── 分类参与者 ────────────────────────────────
        internal_ids: list[str] = []   # Hub 内 member_id
        external_names: list[str] = [] # 外部联系人名 or 邮箱

        # 把 initiator 也算进去（如果提供了）
        if initiator_member_id and initiator_member_id in self.members:
            internal_ids.append(initiator_member_id)

        for name in participant_names:
            name = name.strip()
            # 先查 members
            matched_mid = None
            for mid, m in self.members.items():
                if m.get("name", "").lower() == name.lower() or mid.lower() == name.lower():
                    matched_mid = mid
                    break
            if matched_mid:
                if matched_mid not in internal_ids:
                    internal_ids.append(matched_mid)
            else:
                external_names.append(name)

        logger.info(
            f"Hub initiate_meeting: topic={topic}, "
            f"internal={internal_ids}, external={external_names}"
        )

        # ── 情形 A：纯内部会议（所有参与者都在 Hub 内） ──
        if not external_names:
            return self._initiate_internal_meeting(topic, internal_ids, initiator_member_id)

        # ── 情形 B：有外部参与者 → 混合模式 ─────────────
        # 内部成员合并偏好后以 Hub 名义对外发起协商
        return self._initiate_hybrid_meeting(topic, internal_ids, external_names, initiator_member_id)

    # ── 纯内部会议 ────────────────────────────────────

    def _initiate_internal_meeting(
        self,
        topic: str,
        member_ids: list[str],
        initiator_id: Optional[str] = None,
    ) -> str:
        """上帝视角调度：直接读所有人偏好，1 次 LLM 出结果，不发邮件"""
        session_id = f"hub-internal-{int(time.time())}-{uuid.uuid4().hex[:6]}"

        # 收集所有参与者的偏好
        member_prefs: dict[str, dict] = {}
        for mid in member_ids:
            m = self.members.get(mid, {})
            prefs = m.get("preferences", {})
            member_prefs[mid] = {
                "name": m.get("name", mid),
                "preferred_times": prefs.get("preferred_times", []),
                "blocked_times": prefs.get("blocked_times", []),
                "preferred_locations": prefs.get("preferred_locations", []),
            }

        # 上帝视角 LLM 调度
        result = self.hub_negotiator.find_optimal_slot(topic, member_prefs)

        # 构建 session（用于持久化和状态查询）
        participants = [self.hub_email]  # Hub 邮箱作为唯一 agent
        session = AIMPSession(
            session_id=session_id,
            topic=topic,
            participants=participants,
            initiator=self.hub_email,
        )

        participant_names = [self.members[mid].get("name", mid) for mid in member_ids]

        if result.get("consensus"):
            # 直接确认
            if result.get("time"):
                session.add_option("time", result["time"])
                session.apply_vote(self.hub_email, "time", result["time"])
            if result.get("location"):
                session.add_option("location", result["location"])
                session.apply_vote(self.hub_email, "location", result["location"])

            session.status = "confirmed"
            session.bump_version()
            session.add_history(
                from_agent=self.hub_email,
                action="confirm",
                summary=f"Hub 内部调度完成：{result.get('reason', '')}",
            )
            self.store.save(session)

            logger.info(f"[{session_id}] Hub 内部会议直接确认：{result}")

            # 通知所有参与 members
            notify_body = self.hub_negotiator.generate_member_notify_body(
                topic, result, initiator_id or "", participant_names
            )
            self._notify_members(member_ids, topic, notify_body, session_id)

            if self.notify_mode == "stdout":
                emit_event(
                    "consensus",
                    session_id=session_id,
                    topic=topic,
                    time=result.get("time"),
                    location=result.get("location"),
                    rounds=1,
                    mode="hub_internal",
                    participants=participant_names,
                )
        else:
            # 无法自动达成共识 → 通知所有 members 让他们决策
            session.status = "escalated"
            session.bump_version()
            session.add_history(
                from_agent=self.hub_email,
                action="escalate",
                summary=f"Hub 内部调度冲突：{result.get('reason', '')}",
            )
            self.store.save(session)

            logger.warning(f"[{session_id}] Hub 内部会议冲突，需要人工决策")

            notify_body = self.hub_negotiator.generate_member_notify_body(
                topic, result, initiator_id or "", participant_names
            )
            self._notify_members(member_ids, topic, notify_body, session_id)

            if self.notify_mode == "stdout":
                emit_event(
                    "escalation",
                    session_id=session_id,
                    topic=topic,
                    reason=result.get("reason", "偏好冲突"),
                    mode="hub_internal",
                    participants=participant_names,
                    options=result.get("options", {}),
                )

        return session_id

    # ── 混合模式会议（内部 + 外部） ────────────────────

    def _initiate_hybrid_meeting(
        self,
        topic: str,
        internal_ids: list[str],
        external_names: list[str],
        initiator_id: Optional[str] = None,
    ) -> str:
        """
        内部成员合并偏好 → 以 Hub 名义发起外部邮件协商。
        内部成员的偏好被合并成 Hub 的统一立场，对外只有 1 个声音。
        """
        # 合并内部偏好：取偏好时间/地点的交集（用 LLM 预算出 Hub 的立场）
        combined_prefs = self._merge_internal_prefs(internal_ids)

        # 临时为父类注入合并后的偏好（父类 initiate_meeting 会用 self.config 里的 preferences）
        self._raw_config["preferences"] = combined_prefs

        # 覆写父类 negotiator 的偏好（父类 _send_reply 等会用到）
        self.negotiator.preferences = combined_prefs

        # Call standard parent logic (email AIMP/humans) / 调用父类标准逻辑（向外部联系人发 AIMP/人类邮件）
        session_id = super().initiate_meeting(topic, external_names)

        # 记录这个 session 的内部参与者（用于后续确认后通知）
        self.store.save_message_id(session_id, f"__hub_internal_members__{','.join(internal_ids)}")

        logger.info(
            f"[{session_id}] Hub 混合会议已发起：内部={internal_ids}, 外部={external_names}"
        )
        return session_id

    def _merge_internal_prefs(self, member_ids: list[str]) -> dict:
        """
        简单合并：取所有人偏好时间的并集，取偏好地点的并集，
        取所有人屏蔽时间的并集（任何人屏蔽的都算屏蔽）。
        """
        all_preferred_times = []
        all_blocked_times = []
        all_preferred_locs = []

        for mid in member_ids:
            m = self.members.get(mid, {})
            prefs = m.get("preferences", {})
            all_preferred_times.extend(prefs.get("preferred_times", []))
            all_blocked_times.extend(prefs.get("blocked_times", []))
            all_preferred_locs.extend(prefs.get("preferred_locations", []))

        # 去重，保序
        def dedup(lst):
            seen = set()
            return [x for x in lst if not (x in seen or seen.add(x))]

        return {
            "preferred_times": dedup(all_preferred_times),
            "blocked_times": dedup(all_blocked_times),
            "preferred_locations": dedup(all_preferred_locs),
            "auto_accept": True,
        }

    # ── 通知 members ──────────────────────────────────

    def _notify_members(
        self,
        member_ids: list[str],
        topic: str,
        body: str,
        session_id: str,
    ):
        """向 Hub 内的 members 发通知（邮件或 stdout）"""
        if self.notify_mode == "stdout":
            for mid in member_ids:
                m = self.members.get(mid, {})
                emit_event(
                    "hub_member_notify",
                    session_id=session_id,
                    member_id=mid,
                    member_name=m.get("name", mid),
                    topic=topic,
                    message=body,
                )
        else:
            for mid in member_ids:
                m = self.members.get(mid, {})
                member_email = m.get("email")
                if not member_email:
                    logger.warning(f"member {mid} 没有配置邮箱，跳过通知")
                    continue
                self.email_client.send_human_email(
                    to=member_email,
                    subject=f"[{self.hub_name}] 会议通知：{topic}",
                    body=body,
                )
                logger.info(f"已通知 member {mid} ({member_email})")

    # ── Received member email command / 收到 member 邮件指令 ──────────────────────────

    def handle_member_command(self, from_email: str, body: str) -> list[dict]:
        """
        Process commands sent by members via email (e.g., "help me book a meeting with Bob tomorrow"). /
        处理 member 通过邮件发来的指令（如"帮我约 Bob 明天开会"）。
        Identify identity first, then decide on actions. / 先识别身份，再决策动作。
        """
        member_id = self.identify_sender(from_email)
        if not member_id:
            logger.warning(f"Unknown sender {from_email}, service refused / 陌生发件人 {from_email}，拒绝服务")
            if self.notify_mode == "email":
                self.email_client.send_human_email(
                    to=from_email,
                    subject="Access Denied / 无权使用此服务",
                    body=f"Sorry, {from_email} is not in the whitelist and cannot use this meeting assistant service. / 抱歉，{from_email} 未在白名单中，无法使用本会议助手服务。",
                )
            return [{"type": "rejected", "from": from_email, "reason": "not_in_whitelist"}]

        logger.info(f"Identified member: {member_id} ({from_email}) / 识别到 member: {member_id} ({from_email})")
        # LLM can be used here to parse the body and extract topic/participants / 此处可以进一步用 LLM 解析 body，提取 topic 和 participants
        # Currently returned as an escalation event for processing by OpenClaw / 目前作为 escalation 事件返回，由 OpenClaw 处理
        return [{
            "type": "member_command",
            "member_id": member_id,
            "member_name": self.members[member_id].get("name", member_id),
            "body": body,
        }]

    # ── Override Notify Owner (Notify all admin members) / 覆写通知主人（通知所有 admin members） ─────────

    def _notify_owner_confirmed(self, session: AIMPSession):
        """Notify all admin members (or all members) / 通知所有 admin members（或所有 members）"""
        consensus = session.check_consensus()

        admin_ids = [
            mid for mid, m in self.members.items()
            if m.get("role") == "admin"
        ]
        if not admin_ids:
            admin_ids = list(self.members.keys())

        # Try to restore participants from hub internal info attached to session / 尝试从 session 附带的 hub 内部信息恢复参与者
        internal_member_ids = self._load_internal_members(session.session_id)
        notify_ids = internal_member_ids if internal_member_ids else admin_ids

        if self.notify_mode == "stdout":
            emit_event(
                "consensus",
                session_id=session.session_id,
                topic=session.topic,
                **consensus,
                rounds=session.round_count(),
            )
        else:
            lines = [
                "Great news! The meeting has been successfully negotiated and confirmed. / 好消息！会议已成功协商确定。",
                "",
                f"Topic: {session.topic} / 主题：{session.topic}",
            ]
            for item, val in consensus.items():
                if val:
                    lines.append(f"{item}: {val} / {item}：{val}")
            lines.append(f"\nNegotiation completed in {session.round_count()} rounds. / 协商经过 {session.round_count()} 轮完成。")
            body = "\n".join(lines)

            self._notify_members(
                notify_ids,
                session.topic,
                body,
                session.session_id,
            )

    def _load_internal_members(self, session_id: str) -> list[str]:
        """Restore internal Hub member list from store / 从 store 中恢复 hub 内部成员列表"""
        refs = self.store.load_message_ids(session_id)
        for ref in refs:
            if ref.startswith("__hub_internal_members__"):
                ids = ref.replace("__hub_internal_members__", "").split(",")
                return [i for i in ids if i]
        return []


# ──────────────────────────────────────────────────────
# Factory Function: Automatically returns correct Agent type based on config /
# 工厂函数：根据 config 自动返回正确的 Agent 类型
# ──────────────────────────────────────────────────────

def create_agent(config_path: str, notify_mode: str = "email", db_path: str = None):
    """
    Automatically select Agent type based on configuration file: / 根据配置文件自动选择 Agent 类型：
      - Has "hub:" + "members:" -> AIMPHubAgent (Hub mode) / 有 "hub:" + "members:" → AIMPHubAgent（Hub 模式）
      - Has "owner:" -> AIMPAgent (Standalone mode, backward compatible) / 有 "owner:" → AIMPAgent（独立模式，向后兼容）
    """
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    if "members" in cfg or (cfg.get("mode") == "hub"):
        logger.info("Hub mode configuration detected, using AIMPHubAgent / 检测到 Hub 模式配置，使用 AIMPHubAgent")
        return AIMPHubAgent(config_path, notify_mode=notify_mode, db_path=db_path)
    else:
        logger.info("Standalone mode configuration detected, using AIMPAgent / 检测到独立模式配置，使用 AIMPAgent")
        return AIMPAgent(config_path, notify_mode=notify_mode, db_path=db_path)


# ── Entry Point (Run Hub Agent standalone) / 入口（独立运行 Hub Agent）──────────────────────────

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stdout,
    )
    if len(sys.argv) < 2:
        print("Usage: python hub_agent.py <config_path> [poll_interval] [--notify stdout|email]")
        print("用法: python hub_agent.py <config_path> [poll_interval] [--notify stdout|email]")
        sys.exit(1)

    config_path = sys.argv[1]
    poll_interval = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 30
    notify_mode = "email"
    if "--notify" in sys.argv:
        idx = sys.argv.index("--notify")
        if idx + 1 < len(sys.argv):
            notify_mode = sys.argv[idx + 1]

    agent = create_agent(config_path, notify_mode=notify_mode)
    agent.run(poll_interval=poll_interval)


if __name__ == "__main__":
    main()

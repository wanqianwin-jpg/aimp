"""
hub_agent.py — AIMP Hub Mode / AIMP Hub 模式

A Hub instance serves multiple Humans (members). / 一个 Hub 实例服务多个 Human（members）。

Key advantages / 核心优势：
  - Identity Recognition: Automatically identifies which member is sending commands via email whitelist / 身份识别：通过发件人邮箱白名单自动识别是哪个 member 在发指令
  - Hub-coordinated scheduling: Hub sends parallel availability requests to all members and aggregates real replies — no static config assumptions / 集中协调调度：Hub 并行征询所有成员的真实可用时间并汇总——不依赖静态 config 偏好
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

from lib.email_client import ParsedEmail, is_aimp_email, extract_protocol_json
from lib.protocol import AIMPSession, AIMPRoom, Artifact
from lib.negotiator import Negotiator, make_llm_client, call_llm, extract_json
from lib.session_store import SessionStore
from lib.output import emit_event
from agent import AIMPAgent
from hub_prompts import (
    find_optimal_slot_system,
    find_optimal_slot_user,
    parse_member_request_system,
    parse_member_request_user,
)
from room_prompts import (
    parse_amendment_system,
    parse_amendment_user,
    aggregate_amendments_system,
    aggregate_amendments_user,
    generate_minutes_system,
    generate_minutes_user,
)

logger = logging.getLogger(__name__)


def load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ──────────────────────────────────────────────────────
# Hub Negotiator: Supports multi-user preference aggregation / 支持多用户偏好汇总
# ──────────────────────────────────────────────────────

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


# ──────────────────────────────────────────────────────
# Room Negotiator: Phase 2 LLM helpers / Phase 2 LLM 工具
# ──────────────────────────────────────────────────────

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


# ──────────────────────────────────────────────────────
# AIMPHubAgent
# ──────────────────────────────────────────────────────

class AIMPHubAgent(AIMPAgent):
    """
    Hub 模式 Agent。继承 AIMPAgent，覆写关键行为：
      1. 接收来自 member 的邮件指令时，先识别身份
      2. Hub 内成员之间的会议：Hub 集中征询所有成员的真实可用时间，汇总回复
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

        # 邀请码和信任用户（自助注册系统）
        self._config_path = config_path
        self.invite_codes: list[dict] = config.get("invite_codes", [])
        self.trusted_users: dict = config.get("trusted_users", {})
        # 把已注册的 trusted_users 合并进 members 和 _email_to_member
        for key, u in self.trusted_users.items():
            if u.get("email"):
                member_id = f"trusted_{key}"
                self.members[member_id] = {
                    "name": u.get("name", key),
                    "email": u["email"],
                    "role": "trusted",
                    "preferences": {},
                }
                self._email_to_member[u["email"].lower()] = member_id

        # Throttle: remember unknown senders we've already replied to (email → timestamp)
        self._replied_senders: dict[str, float] = {}

        # Validate config at startup — fail fast with a clear error
        self._validate_config(config)

        # Hub 专用 Negotiator
        self.hub_negotiator = HubNegotiator(
            hub_name=self.hub_name,
            hub_email=self.hub_email,
            llm_config=config.get("llm", {}),
        )

        # Phase 2 Room Negotiator
        self.room_negotiator = RoomNegotiator(
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

    def _validate_config(self, config: dict):
        """Fail fast if the Hub config is missing required fields."""
        hub_cfg = config.get("hub", {})
        for field in ("email", "imap_server", "smtp_server"):
            if not hub_cfg.get(field):
                raise ValueError(f"Hub config missing required field: hub.{field}")

        if not config.get("members"):
            raise ValueError("Hub config must have at least one member under 'members:'")

        for mid, m in config.get("members", {}).items():
            if not m.get("email"):
                logger.warning(f"Member '{mid}' has no email — they won't receive notifications")

        llm_cfg = config.get("llm", {})
        for field in ("provider", "model"):
            if not llm_cfg.get(field):
                raise ValueError(f"Hub config missing required field: llm.{field}")

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

    # ── Hub 集中协调会议（纯内部成员） ───────────────────

    def _initiate_internal_meeting(
        self,
        topic: str,
        member_ids: list[str],
        initiator_id: Optional[str] = None,
    ) -> str:
        """
        Hub-coordinated scheduling: Hub sends parallel availability requests to all
        members and aggregates their replies. No pre-generated options, no assumptions
        from static config preferences — members state their actual availability for
        THIS specific meeting in their reply.
        / Hub 集中协调：Hub 并行给所有成员发可用时间征询邮件，汇总真实回复。
          不预生成选项，不依赖 config 静态偏好——成员在回复中说明本次会议的实际可用时间。
        """
        session_id = f"hub-internal-{int(time.time())}-{uuid.uuid4().hex[:6]}"

        # Build session with all member emails as participants
        member_emails = [
            self.members[mid]["email"]
            for mid in member_ids
            if self.members.get(mid, {}).get("email")
        ]
        session = AIMPSession(
            session_id=session_id,
            topic=topic,
            participants=[self.hub_email] + member_emails,
            initiator=self.hub_email,
        )
        session.bump_version()
        session.add_history(
            from_agent=self.hub_email,
            action="propose",
            summary=f"Hub 发起集中协调，等待所有成员回复可用时间",
        )
        self.store.save(session)

        participant_names = [self.members[mid].get("name", mid) for mid in member_ids]
        logger.info(f"[{session_id}] Hub 内部会议已发起，等待成员回复：{participant_names}")

        # Send open-ended availability request to every member
        if self.notify_mode == "email":
            availability_body = (
                f"请回复告诉我你对这次会议的时间和地点安排：\n\n"
                f"  1. 时间：你什么时候方便？\n"
                f"     （例：下周一下午、3月5日上午10点之后、周三周四都可以）\n\n"
                f"  2. 地点：你偏好哪种开会方式？\n"
                f"     （例：Zoom、腾讯会议、北京办公室、线上均可）\n\n"
                f"直接回复这封邮件即可，不限格式。\n"
                f"所有人回复后，{self.hub_name} 会自动汇总并告知大家最终安排。\n"
            )
            for mid in member_ids:
                m = self.members.get(mid, {})
                member_email = m.get("email")
                if not member_email:
                    logger.warning(f"Member {mid} has no email, skipping availability request")
                    continue
                member_name = m.get("name", mid)
                personal_note = (
                    f"你好 {member_name}，\n\n"
                    f"{self.hub_name} 正在协调会议「{topic}」的时间，你是参与者之一。\n\n"
                )
                self.transport.send_human_email(
                    to=member_email,
                    subject=f"[AIMP:{session_id}] [请告知可用时间] {topic}",
                    body=personal_note + availability_body,
                )
                logger.info(f"[{session_id}] 已发送可用时间征询给 {member_name} ({member_email})")
        else:
            emit_event(
                "internal_availability_requested",
                session_id=session_id,
                topic=topic,
                mode="hub_coordinated",
                participants=participant_names,
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
        Unified flow: Hub sends standard invitations to external contacts (AIMP or human),
        and open-ended availability requests to internal members — all in the same session.
        External participants who reply are auto-registered as Hub members.
        / 统一流程：Hub 给外部联系人发标准邀请（AIMP 或人类邮件），
          给内部成员发可用时间征询——共用同一个 session。
          外部参与者回复时自动注册为 Hub 成员。
        """
        # 父类 initiate_meeting 给外部联系人发邀请（AIMP Agent 走协议，人类走 human_email）
        # 不注入任何偏好——让外部方自由提议，我们收集所有人的真实意见后再汇总
        session_id = super().initiate_meeting(topic, external_names)

        # 同时给内部成员发可用时间征询，加入同一 session
        session = self.store.load(session_id)
        if session and self.notify_mode == "email":
            availability_body = (
                f"请回复告诉我你对这次会议的时间和地点安排：\n\n"
                f"  1. 时间：你什么时候方便？\n"
                f"     （例：下周一下午、3月5日上午10点之后、周三周四都可以）\n\n"
                f"  2. 地点：你偏好哪种开会方式？\n"
                f"     （例：Zoom、腾讯会议、北京办公室、线上均可）\n\n"
                f"直接回复这封邮件即可，不限格式。\n"
                f"所有人回复后，{self.hub_name} 会自动汇总并告知大家最终安排。\n"
            )
            for mid in internal_ids:
                m = self.members.get(mid, {})
                member_email = m.get("email")
                if not member_email:
                    continue
                member_name = m.get("name", mid)
                session.ensure_participant(member_email)
                personal_note = (
                    f"你好 {member_name}，\n\n"
                    f"{self.hub_name} 正在协调会议「{topic}」，你是内部参与者之一。\n\n"
                )
                self.transport.send_human_email(
                    to=member_email,
                    subject=f"[AIMP:{session_id}] [请告知可用时间] {topic}",
                    body=personal_note + availability_body,
                )
                logger.info(f"[{session_id}] 已发送可用时间征询给内部成员 {member_name} ({member_email})")
            self.store.save(session)

        logger.info(f"[{session_id}] Hub 混合会议已发起：内部={internal_ids}, 外部={external_names}")
        return session_id

    # ── Hub Poll 覆写：额外收取成员指令邮件 ──────────────

    def poll(self):
        """
        Hub 版 poll：
          0. Phase 2 FIRST: 先处理 [AIMP:Room:] 邮件（标记已读，避免父类重复处理）
          1. 父类 poll() 处理 AIMP 协议邮件（含人类回复）
          2. 收取所有未读邮件，处理成员直接发来的指令
          3. 检查 deadline 已过的 Room
        """
        events = []

        # ── Phase 2: Room emails FIRST (mark read before parent poll sees them) ──
        try:
            room_emails = self.transport.fetch_phase2_emails(since_minutes=60)
            for parsed in room_emails:
                if parsed.sender == self.agent_email:
                    continue
                try:
                    evts = self._handle_room_email(parsed)
                    events.extend(evts)
                except Exception as e:
                    logger.error(f"Failed to process Room email [{parsed.subject}]: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Phase 2 room email fetch failed: {e}", exc_info=True)

        # ── Phase 1 + member commands ────────────────────────────────────────
        events.extend(super().poll())

        # 收取非 AIMP 邮件（成员指令等）
        try:
            all_emails = self.transport.fetch_all_unread_emails(since_minutes=60)
            for parsed in all_emails:
                # 跳过自己发的
                if parsed.sender == self.agent_email:
                    continue
                # 已经有 [AIMP:] 的邮件在父类 poll 里处理过了（已标记已读），这里不会重复
                # 检查是否是 Hub 成员
                member_id = self.identify_sender(parsed.sender)
                if member_id:
                    evts = self.handle_member_command(
                        parsed.sender, parsed.body, subject=parsed.subject or ""
                    )
                    events.extend(evts)
                else:
                    # Skip bounce/auto-reply addresses entirely
                    if self._is_auto_reply(parsed.sender, parsed.subject or ""):
                        logger.debug(f"Skipping auto-reply/bounce from: {parsed.sender}")
                        continue
                    # Unknown sender — check for invite registration request first
                    invite_evts = self._check_invite_email(parsed)
                    if invite_evts is not None:
                        events.extend(invite_evts)
                    else:
                        # Not an invite email → send registration guidance (throttled)
                        self._reply_unknown_sender(parsed.sender)
                        logger.debug(f"Sent registration guidance to unknown sender: {parsed.sender}")
        except Exception as e:
            logger.error(f"Hub member email fetch failed: {e}", exc_info=True)

        # ── Phase 2: deadline check ──────────────────────────────────────────
        try:
            self._check_deadlines()
        except Exception as e:
            logger.error(f"Deadline check failed: {e}", exc_info=True)

        return events

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
                self.transport.send_human_email(
                    to=member_email,
                    subject=f"[AIMP:{session_id}] [{self.hub_name}] {topic}",
                    body=body,
                )
                logger.info(f"已通知 member {mid} ({member_email})")

    # ── Auto-register Hub-invited participants on first reply ──────────────

    def _handle_human_email(self, parsed: ParsedEmail) -> list[dict]:
        """
        Override parent: (a) intercept Phase 2 Room veto replies, (b) auto-register
        Hub-invited participants on first reply.
        / 覆写父类：(a) 拦截 Phase 2 Room 的 veto 回复；(b) Hub 邀请过的参与者首次回复时自动注册。
        """
        sender = parsed.sender

        # ── Phase 2 veto detection ────────────────────────────────────────────
        if parsed.room_id:
            room = self.store.load_room(parsed.room_id)
            if room and room.status == "finalized":
                body_stripped = parsed.body.strip()
                body_upper = body_stripped.upper()
                if body_upper.startswith("CONFIRM"):
                    return self._handle_room_confirm(room, sender)
                elif body_upper.startswith("REJECT"):
                    reason = body_stripped[6:].strip()
                    return self._handle_room_reject(room, sender, reason)
            # Room email that isn't a veto — fall through to standard handling
            # (e.g. an AMEND reply after finalization should be ignored gracefully)

        # ── Auto-register Hub-invited participants on first reply ─────────────
        session_id = parsed.session_id
        if (
            session_id
            and not self.identify_sender(sender)
            and not self._is_auto_reply(sender, parsed.subject or "")
        ):
            session = self.store.load(session_id)
            if session and sender.lower() in [p.lower() for p in session.participants]:
                name = parsed.sender_name or sender.split("@")[0].capitalize()
                self._register_trusted_user(sender, name, via_code=None)
                logger.info(f"[{session_id}] Auto-registered Hub-invited participant: {name} ({sender})")
                if self.notify_mode == "email":
                    self.transport.send_human_email(
                        to=sender,
                        subject=f"[{self.hub_name}] 欢迎！你已自动注册",
                        body=(
                            f"你好 {name}！\n\n"
                            f"你通过回复会议邀请自动注册为 {self.hub_name} 成员。\n"
                            f"以后可以直接发邮件给我约会议，不需要邀请码。\n\n"
                            f"用法示例：\n"
                            f"  「帮我约 Bob 明天下午聊项目」\n\n"
                            f"— {self.hub_name}"
                        ),
                    )

        return super()._handle_human_email(parsed)

    # ── Received member email command / 收到 member 邮件指令 ──────────────────────────

    def handle_member_command(self, from_email: str, body: str, subject: str = "") -> list[dict]:
        """
        Stage-2 processor: Parse member's natural-language meeting request via LLM,
        validate completeness, resolve contacts, auto-dispatch initiate_meeting(),
        and send the initiator a vote request email (they're also a voter).
        / 第二阶段处理器：LLM 解析成员的自然语言请求，校验完整性，解析联系人，
          自动派发 initiate_meeting()，并给发起者发投票邀请（他也是投票方之一）。
        """
        member_id = self.identify_sender(from_email)
        if not member_id:
            logger.warning(f"Unknown sender {from_email}, service refused")
            if self.notify_mode == "email":
                self._reply_unknown_sender(from_email)
            return [{"type": "rejected", "from": from_email, "reason": "not_in_whitelist"}]

        member_name = self.members[member_id].get("name", member_id)
        logger.info(f"Member command from {member_name} ({from_email})")

        # ── LLM parse ──────────────────────────────────────────────────────
        parsed = self._parse_member_request(member_name, body, subject=subject)
        action = parsed.get("action", "unclear")

        if action == "create_room":
            return self._handle_create_room_command(
                from_email, member_id, member_name, parsed
            )

        if action != "schedule_meeting":
            # Didn't understand the request — reply with guidance
            if self.notify_mode == "email":
                self.transport.send_human_email(
                    to=from_email,
                    subject=f"[{self.hub_name}] 收到你的消息，但我没明白",
                    body=(
                        f"你好 {member_name}，\n\n"
                        f"我收到了你的邮件，但无法识别具体需求。\n\n"
                        f"如果你想约会议，请告诉我：\n"
                        f"  1. 会议主题\n"
                        f"  2. 参与者姓名\n"
                        f"  3. 你方便的时间 / 地点（可选，但推荐提供）\n\n"
                        f"如果你想发起内容协商（如文档、方案、预算），请说明：\n"
                        f"  1. 协商主题\n"
                        f"  2. 参与者\n"
                        f"  3. 截止时间\n"
                        f"  4. 初始提案内容（可选）\n\n"
                        f"例如：「帮我约 Bob 和 Carol 本周五下午讨论季度计划，线上或北京办公室均可」\n\n"
                        f"— {self.hub_name}"
                    ),
                )
            return [{"type": "member_command_unclear", "member_id": member_id, "body": body}]

        # ── Completeness check ─────────────────────────────────────────────
        topic = parsed.get("topic", "").strip()
        participant_names: list[str] = parsed.get("participants") or []
        missing: list[str] = parsed.get("missing") or []

        # Always require topic and at least one participant
        if not topic:
            missing.append("topic")
        if not participant_names:
            missing.append("participants")

        if missing:
            missing_cn = {"topic": "会议主题", "participants": "参与者", "initiator_times": "你的时间偏好", "initiator_locations": "你的地点偏好"}
            missing_str = "、".join(missing_cn.get(m, m) for m in missing)
            if self.notify_mode == "email":
                self.transport.send_human_email(
                    to=from_email,
                    subject=f"[{self.hub_name}] 需要补充信息",
                    body=(
                        f"你好 {member_name}，\n\n"
                        f"收到你的约会请求！不过还需要以下信息：\n\n"
                        f"  缺少：{missing_str}\n\n"
                        f"请补充后重新发邮件给我。\n\n"
                        f"— {self.hub_name}"
                    ),
                )
            return [{"type": "member_info_requested", "member_id": member_id, "missing": missing}]

        # ── Resolve participant contacts ────────────────────────────────────
        unknown_names = [n for n in participant_names if not self._find_participant_contact(n)]
        if unknown_names:
            unknown_str = "、".join(unknown_names)
            if self.notify_mode == "email":
                self.transport.send_human_email(
                    to=from_email,
                    subject=f"[{self.hub_name}] 找不到联系人邮箱",
                    body=(
                        f"你好 {member_name}，\n\n"
                        f"以下参与者没有邮箱记录，无法发出邀请：\n\n"
                        f"  {unknown_str}\n\n"
                        f"请在邮件中直接提供他们的邮箱地址，或让管理员将其加入通讯录。\n\n"
                        f"— {self.hub_name}"
                    ),
                )
            return [{"type": "member_info_requested", "member_id": member_id, "missing": ["contact_emails"], "unknown": unknown_names}]

        # ── Auto-dispatch ──────────────────────────────────────────────────
        try:
            session_id = self.initiate_meeting(topic, participant_names, initiator_member_id=member_id)
        except Exception as e:
            logger.error(f"initiate_meeting failed: {e}", exc_info=True)
            if self.notify_mode == "email":
                self.transport.send_human_email(
                    to=from_email,
                    subject=f"[{self.hub_name}] 发起会议失败",
                    body=f"你好 {member_name}，\n\n发起会议时遇到问题，请稍后重试。\n\n错误：{e}\n\n— {self.hub_name}",
                )
            return [{"type": "meeting_initiation_failed", "member_id": member_id, "error": str(e)}]

        # ── Send initiator a vote request (they are also a voter) ──────────
        # For internal meetings _initiate_internal_meeting already sent vote
        # invitations to all members including the initiator — skip to avoid duplicate.
        if self.notify_mode == "email":
            try:
                session = self.store.load(session_id)
                if session:
                    already_invited = from_email.lower() in [
                        p.lower() for p in session.participants
                    ]
                    if not already_invited:
                        self._send_initiator_vote_request(from_email, member_name, session)
            except Exception as e:
                logger.warning(f"Could not send initiator vote request: {e}")

        logger.info(f"Meeting [{session_id}] initiated by {member_name} on topic '{topic}'")
        return [{
            "type": "meeting_initiated",
            "session_id": session_id,
            "member_id": member_id,
            "topic": topic,
            "participants": participant_names,
        }]

    # ── Phase 2: create_room command handler ──────────────────────────────

    def _handle_create_room_command(
        self,
        from_email: str,
        member_id: str,
        member_name: str,
        parsed_request: dict,
    ) -> list[dict]:
        """
        Handle a 'create_room' command from a member: validate, create AIMPRoom,
        send CFP emails to participants.
        / 处理成员的 create_room 指令：校验、创建 AIMPRoom、发 CFP 邮件给参与者。
        """
        topic = (parsed_request.get("topic") or "").strip()
        participant_names: list[str] = parsed_request.get("participants") or []
        deadline_str: str = (parsed_request.get("deadline") or "").strip()
        initial_proposal: str = (parsed_request.get("initial_proposal") or "").strip()
        resolution_rules: str = (parsed_request.get("resolution_rules") or "majority").strip()

        # Validate required fields
        missing = []
        if not topic:
            missing.append("topic")
        if not participant_names:
            missing.append("participants")
        if not deadline_str:
            missing.append("deadline")

        if missing:
            missing_cn = {"topic": "协商主题", "participants": "参与者", "deadline": "截止时间"}
            missing_str = "、".join(missing_cn.get(m, m) for m in missing)
            if self.notify_mode == "email":
                self.transport.send_human_email(
                    to=from_email,
                    subject=f"[{self.hub_name}] 创建协商室需要更多信息",
                    body=(
                        f"你好 {member_name}，\n\n"
                        f"要创建内容协商室，还需要以下信息：\n\n"
                        f"  缺少：{missing_str}\n\n"
                        f"请补充后重新发邮件给我。\n\n"
                        f"— {self.hub_name}"
                    ),
                )
            return [{"type": "member_info_requested", "member_id": member_id, "missing": missing}]

        # Resolve deadline to Unix timestamp
        deadline_ts = self._parse_deadline(deadline_str)
        deadline_iso = self._ts_to_iso(deadline_ts)

        # Resolve participant contacts
        unknown_names = [n for n in participant_names if not self._find_participant_contact(n)]
        if unknown_names:
            unknown_str = "、".join(unknown_names)
            if self.notify_mode == "email":
                self.transport.send_human_email(
                    to=from_email,
                    subject=f"[{self.hub_name}] 找不到联系人邮箱",
                    body=(
                        f"你好 {member_name}，\n\n"
                        f"以下参与者没有邮箱记录，无法发出协商邀请：\n\n"
                        f"  {unknown_str}\n\n"
                        f"请在邮件中直接提供他们的邮箱地址，或让管理员将其加入通讯录。\n\n"
                        f"— {self.hub_name}"
                    ),
                )
            return [{"type": "member_info_requested", "member_id": member_id, "missing": ["contact_emails"], "unknown": unknown_names}]

        # Build participant email list
        participant_emails = [from_email]
        for name in participant_names:
            contact = self._find_participant_contact(name)
            if contact and contact["email"] not in participant_emails:
                participant_emails.append(contact["email"])

        try:
            room_id = self.initiate_room(
                topic=topic,
                participants=participant_emails,
                deadline=deadline_ts,
                initial_proposal=initial_proposal,
                initiator=from_email,
                resolution_rules=resolution_rules,
            )
        except Exception as e:
            logger.error(f"initiate_room failed: {e}", exc_info=True)
            if self.notify_mode == "email":
                self.transport.send_human_email(
                    to=from_email,
                    subject=f"[{self.hub_name}] 创建协商室失败",
                    body=f"你好 {member_name}，\n\n创建协商室时遇到问题，请稍后重试。\n\n错误：{e}\n\n— {self.hub_name}",
                )
            return [{"type": "room_creation_failed", "member_id": member_id, "error": str(e)}]

        logger.info(f"Room [{room_id}] created by {member_name} on topic '{topic}'")
        return [{
            "type": "room_created",
            "room_id": room_id,
            "member_id": member_id,
            "topic": topic,
            "participants": participant_emails,
            "deadline": deadline_iso,
        }]

    # ── Phase 2: Room lifecycle ────────────────────────────────────────────

    def initiate_room(
        self,
        topic: str,
        participants: list[str],
        deadline: float,
        initial_proposal: str,
        initiator: str,
        resolution_rules: str = "majority",
    ) -> str:
        """
        Create an AIMPRoom and send CFP emails to all participants. /
        创建 AIMPRoom 并向所有参与者发送 CFP 邮件。

        Returns: room_id
        """
        room_id = f"room-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        deadline_iso = self._ts_to_iso(deadline)

        room = AIMPRoom(
            room_id=room_id,
            topic=topic,
            deadline=deadline,
            participants=participants,
            initiator=initiator,
            resolution_rules=resolution_rules,
        )

        # If initial_proposal is provided, add it as the first artifact
        if initial_proposal:
            artifact = Artifact(
                name="initial_proposal.txt",
                content_type="text/plain",
                body_text=initial_proposal,
                author=initiator,
                timestamp=time.time(),
            )
            room.artifacts["initial_proposal.txt"] = artifact
            room.add_to_transcript(
                from_agent=initiator,
                action="PROPOSE",
                summary=f"Initial proposal submitted: {initial_proposal[:100]}{'...' if len(initial_proposal) > 100 else ''}",
            )

        self.store.save_room(room)

        if self.notify_mode == "email":
            initiator_name = self._email_to_name(initiator)
            cfp_body = (
                f"你好！\n\n"
                f"{initiator_name} 邀请你参与内容协商：\n\n"
                f"  主题：{topic}\n"
                f"  截止时间：{deadline_iso}\n"
                f"  决议规则：{resolution_rules}\n\n"
            )
            if initial_proposal:
                cfp_body += (
                    f"初始提案内容：\n"
                    f"───────────────\n"
                    f"{initial_proposal}\n"
                    f"───────────────\n\n"
                )
            cfp_body += (
                f"请回复此邮件表达你的意见：\n"
                f"  - 发送 ACCEPT 表示接受当前提案\n"
                f"  - 发送 AMEND + 修改建议 表示提出修改\n"
                f"  - 发送 PROPOSE + 内容 提交新提案\n"
                f"  - 发送 REJECT + 原因 表示反对\n\n"
                f"协商将在截止时间 {deadline_iso} 自动结束并生成会议纪要。\n\n"
                f"— {self.hub_name}"
            )

            # Send to all participants (including initiator)
            self.transport.send_cfp_email(
                to=participants,
                room_id=room_id,
                topic=topic,
                deadline_iso=deadline_iso,
                initial_proposal=initial_proposal,
                resolution_rules=resolution_rules,
                body_text=cfp_body,
            )
            logger.info(f"[{room_id}] CFP sent to {participants}")
        else:
            emit_event(
                "room_created",
                room_id=room_id,
                topic=topic,
                participants=participants,
                deadline=deadline_iso,
            )

        return room_id

    def _handle_room_email(self, parsed: ParsedEmail) -> list[dict]:
        """
        Process a Phase 2 Room email from a participant. /
        处理来自参与者的 Phase 2 Room 邮件。

        Flow: load room → parse amendment → add to transcript → check convergence.
        """
        room_id = parsed.room_id
        if not room_id:
            return []

        room = self.store.load_room(room_id)
        if not room:
            logger.warning(f"Received Room email for unknown room_id={room_id}")
            return []

        if room.status != "open":
            logger.info(f"[{room_id}] Room is {room.status}, ignoring late reply from {parsed.sender}")
            return []

        # Verify sender is a participant
        sender = parsed.sender
        if sender.lower() not in [p.lower() for p in room.participants]:
            logger.warning(f"[{room_id}] Ignoring reply from non-participant {sender}")
            return []

        # Parse the amendment using LLM
        sender_name = self._email_to_name(sender)
        artifacts_dict = {name: a.to_dict() for name, a in room.artifacts.items()}
        amendment = self.room_negotiator.parse_amendment(sender_name, parsed.body, artifacts_dict)

        action = amendment.get("action", "AMEND").upper()
        changes = amendment.get("changes", "")
        reason = amendment.get("reason", "")
        new_content = amendment.get("new_content")

        # Update accepted_by list
        if action == "ACCEPT":
            if sender not in room.accepted_by:
                room.accepted_by.append(sender)
        elif action in ("PROPOSE", "AMEND") and new_content:
            # Add/update artifact
            artifact_name = f"proposal_{sender.split('@')[0]}_{int(time.time())}.txt"
            room.artifacts[artifact_name] = Artifact(
                name=artifact_name,
                content_type="text/plain",
                body_text=new_content,
                author=sender,
                timestamp=time.time(),
            )

        # Record in transcript
        summary = changes or reason or parsed.body[:100]
        room.add_to_transcript(
            from_agent=sender,
            action=action,
            summary=f"{sender_name}: {summary}",
        )
        self.store.save_room(room)

        logger.info(f"[{room_id}] Received {action} from {sender_name}")

        # Check convergence
        if room.all_accepted():
            logger.info(f"[{room_id}] All participants accepted — finalizing room")
            self._finalize_room(room)
            return [{"type": "room_finalized", "room_id": room_id, "trigger": "all_accepted"}]

        events = [{"type": "room_amendment_received", "room_id": room_id, "action": action, "sender": sender}]

        # Broadcast status update to all participants
        if self.notify_mode == "email":
            self._broadcast_room_status(room, latest_action=action, latest_sender=sender_name)

        return events

    def _finalize_room(self, room: AIMPRoom) -> None:
        """
        Finalize the room: generate meeting minutes, update status, notify all participants. /
        结束 Room：生成会议纪要、更新状态、通知所有参与者。
        """
        room.status = "finalized"
        room.add_to_transcript(
            from_agent=self.hub_email,
            action="FINALIZED",
            summary=f"Room finalized. Trigger: {'all_accepted' if room.all_accepted() else 'deadline_expired'}",
        )

        # Generate meeting minutes
        minutes = self.room_negotiator.generate_meeting_minutes(room)
        self.store.save_room(room)

        if self.notify_mode == "email":
            deadline_iso = self._ts_to_iso(room.deadline)
            body = (
                f"📋 **会议纪要** — {room.topic}\n\n"
                f"协商已结束（截止时间：{deadline_iso}）。\n\n"
                f"{'─' * 40}\n\n"
                f"{minutes}\n\n"
                f"{'─' * 40}\n\n"
                f"如需确认或否决此纪要，请回复：\n"
                f"  - CONFIRM  （接受纪要）\n"
                f"  - REJECT <原因>  （否决纪要，发起方将重新决定）\n\n"
                f"— {self.hub_name}"
            )
            for participant in room.participants:
                self.transport.send_human_email(
                    to=participant,
                    subject=f"[AIMP:Room:{room.room_id}] [会议纪要] {room.topic}",
                    body=body,
                )
            logger.info(f"[{room.room_id}] Meeting minutes sent to {room.participants}")
        else:
            emit_event(
                "room_finalized",
                room_id=room.room_id,
                topic=room.topic,
                minutes=minutes,
                participants=room.participants,
            )

    def _check_deadlines(self) -> None:
        """
        Check all open rooms and finalize any that have passed their deadline. /
        检查所有开放的 Room，对已过截止时间的 Room 执行收尾。
        """
        open_rooms = self.store.load_open_rooms()
        for room in open_rooms:
            if room.is_past_deadline():
                logger.info(f"[{room.room_id}] Deadline passed — finalizing room '{room.topic}'")
                try:
                    self._finalize_room(room)
                except Exception as e:
                    logger.error(f"[{room.room_id}] Failed to finalize room: {e}", exc_info=True)

    def _handle_room_confirm(self, room: AIMPRoom, sender: str) -> list[dict]:
        """
        Handle a CONFIRM veto reply for a finalized room. /
        处理已收尾 Room 的 CONFIRM veto 回复。
        """
        if sender not in room.accepted_by:
            room.accepted_by.append(sender)
        room.add_to_transcript(
            from_agent=sender,
            action="CONFIRM",
            summary=f"{self._email_to_name(sender)} confirmed the meeting minutes.",
        )
        self.store.save_room(room)

        logger.info(f"[{room.room_id}] CONFIRM from {sender}")
        if self.notify_mode == "email":
            self.transport.send_human_email(
                to=sender,
                subject=f"[{self.hub_name}] 确认收到",
                body=(
                    f"你好！\n\n"
                    f"已收到你对「{room.topic}」会议纪要的确认。\n\n"
                    f"— {self.hub_name}"
                ),
            )
        return [{"type": "room_confirmed", "room_id": room.room_id, "sender": sender}]

    def _handle_room_reject(self, room: AIMPRoom, sender: str, reason: str) -> list[dict]:
        """
        Handle a REJECT veto reply: escalate to initiator for final decision. /
        处理 REJECT veto 回复：升级给发起人做最终决定。
        """
        room.add_to_transcript(
            from_agent=sender,
            action="REJECT",
            summary=f"{self._email_to_name(sender)} rejected the minutes. Reason: {reason}",
        )
        self.store.save_room(room)

        logger.info(f"[{room.room_id}] REJECT from {sender}: {reason}")
        if self.notify_mode == "email":
            self.transport.send_human_email(
                to=room.initiator,
                subject=f"[{self.hub_name}] [需要决策] {room.topic} 纪要被否决",
                body=(
                    f"你好！\n\n"
                    f"参与者 {self._email_to_name(sender)} 否决了「{room.topic}」的会议纪要。\n\n"
                    f"否决原因：{reason or '（未提供原因）'}\n\n"
                    f"作为发起人，请你决定后续处理方式：\n"
                    f"  1. 重新开启协商（回复 REOPEN）\n"
                    f"  2. 坚持当前纪要（回复 KEEP）\n\n"
                    f"— {self.hub_name}"
                ),
            )
            self.transport.send_human_email(
                to=sender,
                subject=f"[{self.hub_name}] 否决已记录",
                body=(
                    f"你好！\n\n"
                    f"已将你对「{room.topic}」纪要的否决意见转达给发起人，请等待后续通知。\n\n"
                    f"— {self.hub_name}"
                ),
            )
        return [{"type": "room_rejected", "room_id": room.room_id, "sender": sender, "reason": reason}]

    def _broadcast_room_status(self, room: AIMPRoom, latest_action: str, latest_sender: str):
        """
        Send a brief status update to all participants after receiving an amendment. /
        收到修正后向所有参与者发送简短状态更新。
        """
        accepted_count = len(room.accepted_by)
        total = len(room.participants)
        deadline_iso = self._ts_to_iso(room.deadline)

        body = (
            f"[协商室更新] {room.topic}\n\n"
            f"{latest_sender} 发送了 {latest_action}。\n\n"
            f"进度：{accepted_count}/{total} 人已 ACCEPT\n"
            f"截止时间：{deadline_iso}\n\n"
            f"回复 ACCEPT 同意当前提案，或继续发送 AMEND / PROPOSE 修改意见。\n\n"
            f"— {self.hub_name}"
        )
        for participant in room.participants:
            try:
                self.transport.send_human_email(
                    to=participant,
                    subject=f"[AIMP:Room:{room.room_id}] [更新] {room.topic}",
                    body=body,
                )
            except Exception as e:
                logger.warning(f"Failed to send status update to {participant}: {e}")

    # ── Deadline / ISO helpers ─────────────────────────────────────────────

    def _parse_deadline(self, deadline_str: str) -> float:
        """
        Parse a deadline string to Unix timestamp. Supports ISO8601 and relative
        expressions like '3 days', '1 week', '24 hours'.
        / 将截止时间字符串解析为 Unix 时间戳。支持 ISO8601 和相对表达。
        """
        import re as _re
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td

        # Try ISO8601 first
        try:
            parsed = _dt.fromisoformat(deadline_str.replace("Z", "+00:00"))
            return parsed.timestamp()
        except (ValueError, AttributeError):
            pass

        # Relative: "3 days", "2 weeks", "48 hours", "1 month"
        m = _re.search(r"(\d+)\s*(day|week|hour|month)", deadline_str.lower())
        if m:
            n = int(m.group(1))
            unit = m.group(2)
            delta_map = {"day": 1, "week": 7, "hour": 1 / 24, "month": 30}
            days = n * delta_map.get(unit, 1)
            return time.time() + days * 86400

        # Default: 7 days from now
        logger.warning(f"Could not parse deadline '{deadline_str}', defaulting to 7 days")
        return time.time() + 7 * 86400

    def _ts_to_iso(self, ts: float) -> str:
        """Convert Unix timestamp to ISO8601 string / Unix 时间戳转 ISO8601 字符串"""
        from datetime import datetime as _dt, timezone as _tz
        return _dt.fromtimestamp(ts, tz=_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _email_to_name(self, email: str) -> str:
        """Resolve an email to a display name / 将邮箱解析为显示名称"""
        member_id = self.identify_sender(email)
        if member_id:
            return self.members[member_id].get("name", member_id)
        return email.split("@")[0].capitalize()

    # ── Stage-2 helper methods ─────────────────────────────────────────────

    def _parse_member_request(self, member_name: str, body: str, subject: str = "") -> dict:
        """
        Use LLM to parse a member's natural-language meeting request.
        Returns dict: {action, topic, participants, initiator_times, initiator_locations, missing}
        """
        system = parse_member_request_system(self.hub_name)
        user = parse_member_request_user(member_name, subject, body)
        try:
            raw = call_llm(
                self.hub_negotiator.client,
                self.hub_negotiator.model,
                self.hub_negotiator.provider,
                system,
                user,
            )
            result = extract_json(raw)
            logger.debug(f"_parse_member_request result: {result}")
            return result
        except Exception as e:
            logger.error(f"_parse_member_request LLM failed: {e}")
            return {"action": "unclear", "topic": None, "participants": [], "missing": ["topic", "participants"]}

    def _find_participant_contact(self, name: str) -> Optional[dict]:
        """
        Resolve a participant name to contact info.
        Checks (in order): Hub members, contacts config, raw email address.
        Returns {"email": ..., "has_agent": bool, "name": ...} or None.
        """
        # 1. Check Hub members by name
        for mid, m in self.members.items():
            if m.get("name", "").lower() == name.lower() or mid.lower() == name.lower():
                return {"email": m.get("email", ""), "has_agent": False, "name": m.get("name", name)}

        # 2. Check contacts config
        contacts = self._raw_config.get("contacts", {})
        if name in contacts:
            c = contacts[name]
            if c.get("has_agent"):
                return {"email": c["agent_email"], "has_agent": True, "name": name}
            elif c.get("human_email"):
                return {"email": c["human_email"], "has_agent": False, "name": name}

        # 3. Raw email address
        if "@" in name:
            return {"email": name, "has_agent": False, "name": name}

        return None

    def _send_initiator_vote_request(self, from_email: str, member_name: str, session):
        """
        Send the meeting initiator a vote invitation email — they are also a voter.
        Uses ensure_participant() to dynamically add them if not already in session.
        """
        try:
            session.ensure_participant(from_email)
            body = self.negotiator.generate_human_email_body(session)
            # Prepend a personal note
            personal_note = (
                f"你好 {member_name}，\n\n"
                f"你发起的会议「{session.topic}」已经开始协商。\n"
                f"作为发起者，你也需要提交你的时间和地点偏好：\n\n"
            )
            self.transport.send_human_email(
                to=from_email,
                subject=f"[AIMP:{session.session_id}] [请投票] {session.topic}",
                body=personal_note + body,
            )
            logger.info(f"Sent initiator vote request to {from_email} for session {session.session_id}")
        except Exception as e:
            logger.warning(f"_send_initiator_vote_request failed for {from_email}: {e}")

    # ── Auto-reply / spam protection ──────────────────────────────────────

    _AUTO_REPLY_LOCALS = frozenset({
        "no-reply", "noreply", "no_reply", "mailer-daemon", "mailer_daemon",
        "postmaster", "bounce", "bounces", "do-not-reply", "donotreply",
        "auto-reply", "autoreply", "notifications", "notification",
    })
    _AUTO_REPLY_SUBJECT_PREFIXES = (
        "out of office", "automatic reply", "auto reply", "autoreply",
        "undeliverable", "delivery status notification", "delivery failure",
        "mail delivery failed", "returned mail", "failure notice",
    )

    def _is_auto_reply(self, from_email: str, subject: str) -> bool:
        """Return True if this looks like a bounce, auto-reply, or mailing-list email."""
        local = from_email.lower().split("@")[0]
        if local in self._AUTO_REPLY_LOCALS:
            return True
        if any(p in local for p in ("no-reply", "noreply", "mailer-daemon", "do-not-reply")):
            return True
        if subject and subject.lower().strip().startswith(self._AUTO_REPLY_SUBJECT_PREFIXES):
            return True
        return False

    def _reply_unknown_sender(self, from_email: str):
        """
        Send registration guidance to an unknown sender (not a member, no invite code).
        Throttled: only replies to the same address once per 24 hours.
        """
        if self.notify_mode != "email":
            return
        # Throttle: skip if we've replied to this address within the last 24 h
        now = time.time()
        last = self._replied_senders.get(from_email.lower(), 0.0)
        if now - last < 86400:
            logger.debug(f"Already replied to unknown sender {from_email} recently, skipping")
            return
        self._replied_senders[from_email.lower()] = now

        self.transport.send_human_email(
            to=from_email,
            subject=f"[{self.hub_name}] 你好！如何使用本服务",
            body=(
                f"你好！\n\n"
                f"感谢你联系 {self.hub_name} 会议助手。\n\n"
                f"目前你的邮箱尚未注册，需要通过邀请码才能使用本服务。\n\n"
                f"注册步骤：\n"
                f"  1. 向 {self.hub_name} 管理员申请一个邀请码\n"
                f"  2. 给本邮件地址发一封邮件，主题格式为：\n"
                f"       [AIMP-INVITE:你的邀请码]\n"
                f"     例如：[AIMP-INVITE:welcome-2026]\n"
                f"  3. 注册成功后，你会收到确认邮件，之后就可以直接发邮件约会议了\n\n"
                f"如有问题，请联系 {self.hub_name} 管理员。\n\n"
                f"— {self.hub_name}"
            ),
        )
        logger.debug(f"Sent unknown-sender registration guidance to {from_email}")

    # ── 邀请码自助注册系统 ──────────────────────────────

    def _check_invite_email(self, parsed: ParsedEmail) -> Optional[list[dict]]:
        """
        Check if email contains an invite code (subject pattern: [AIMP-INVITE:CODE]).
        Returns event list if handled, None if not an invite email.
        """
        import re
        m = re.search(r'\[AIMP-INVITE:([^\]]+)\]', parsed.subject, re.IGNORECASE)
        if not m:
            return None
        code = m.group(1).strip()
        return self._handle_invite_request(parsed.sender, parsed.sender_name, code)

    def _handle_invite_request(self, from_email: str, sender_name: Optional[str], code: str) -> list[dict]:
        """Validate invite code, register user, send welcome reply."""
        # Already a known member or trusted user?
        if self.identify_sender(from_email):
            self.transport.send_human_email(
                to=from_email,
                subject=f"[{self.hub_name}] 你已经注册过了",
                body=(
                    f"你好！\n\n"
                    f"你的邮箱 {from_email} 已经在 {self.hub_name} 中注册，无需重复注册。\n\n"
                    f"直接发邮件给我就可以约会议，例如：\n"
                    f"  「帮我约 Bob 明天下午聊项目」\n\n"
                    f"— {self.hub_name}"
                ),
            )
            return []

        valid_code = self._validate_invite_code(code)
        if not valid_code:
            self.transport.send_human_email(
                to=from_email,
                subject=f"[{self.hub_name}] 邀请码无效",
                body=(
                    f"你好！\n\n"
                    f"邀请码「{code}」无效、已过期或已达使用上限。\n\n"
                    f"请向 {self.hub_name} 管理员申请新的邀请码。\n\n"
                    f"— {self.hub_name}"
                ),
            )
            return [{"type": "invite_rejected", "from": from_email, "code": code}]

        # Use display name from From header, or fall back to email prefix
        name = sender_name or from_email.split("@")[0].capitalize()

        self._register_trusted_user(from_email, name, code)
        self._consume_invite_code(code)

        import json as _json
        # Build hub-card for AI agent discovery
        hub_card = {
            "aimp_hub": {
                "version": "1.0",
                "name": self.hub_name,
                "email": self.hub_email,
                "protocol": "AIMP/email",
                "capabilities": ["schedule_meeting"],
                "registered_members": [
                    self.members[mid].get("name", mid)
                    for mid in self.members
                    if self.members[mid].get("role") != "trusted"
                ],
                "usage": {
                    "schedule_meeting": {
                        "how": f"Send email to {self.hub_email} with a natural-language request.",
                        "required_fields": ["topic", "participants"],
                        "optional_fields": ["preferred_times", "preferred_locations"],
                        "example": f"Subject: (anything)\nBody: Help me schedule a meeting with Bob and Carol next Friday to discuss Q2 plan. I prefer mornings."
                    }
                },
                "session_threading": {
                    "pattern": "[AIMP:{session_id}]",
                    "note": "Keep [AIMP:xxx] in subject when replying to vote invitations."
                }
            }
        }
        hub_card_json = _json.dumps(hub_card, ensure_ascii=False, indent=2)

        self.transport.send_human_email(
            to=from_email,
            subject=f"[{self.hub_name}] 注册成功！欢迎使用",
            body=(
                f"你好 {name}！\n\n"
                f"你已成功注册 {self.hub_name}，以后直接发邮件给我就可以约会议。\n\n"
                f"用法示例：\n"
                f"  「帮我约 Bob 明天下午聊项目」\n"
                f"  \"Schedule a meeting with Carol about the report\"\n\n"
                f"我会自动协调所有人的时间，完成后通知你。\n\n"
                f"---\n"
                f"[AI Agent 可读能力声明 / Hub Capability Card for AI Agents]\n\n"
                f"```json\n{hub_card_json}\n```\n\n"
                f"— {self.hub_name}"
            ),
        )

        logger.info(f"Registered trusted user: {name} ({from_email}) via invite code {code}")
        return [{"type": "invite_accepted", "from": from_email, "name": name}]

    def _validate_invite_code(self, code: str) -> Optional[dict]:
        """Return the code dict if valid, None otherwise."""
        from datetime import date
        for ic in self.invite_codes:
            if ic.get("code") != code:
                continue
            if ic.get("expires"):
                try:
                    if date.today() > date.fromisoformat(str(ic["expires"])):
                        logger.info(f"Invite code '{code}' has expired")
                        return None
                except (ValueError, TypeError):
                    pass
            max_uses = ic.get("max_uses", 0)
            if max_uses > 0 and ic.get("used", 0) >= max_uses:
                logger.info(f"Invite code '{code}' has reached limit ({max_uses})")
                return None
            return ic
        logger.info(f"Invite code '{code}' not found")
        return None

    def _register_trusted_user(self, email: str, name: str, via_code: Optional[str] = None):
        """Add user to trusted_users and live member index, then persist."""
        from datetime import date
        import re
        key = re.sub(r'[^a-zA-Z0-9]', '_', email)
        user_record = {
            "name": name,
            "email": email,
            "registered": date.today().isoformat(),
            "via_code": via_code,
        }
        self.trusted_users[key] = user_record
        member_id = f"trusted_{key}"
        self.members[member_id] = {
            "name": name,
            "email": email,
            "role": "trusted",
            "preferences": {},
        }
        self._email_to_member[email.lower()] = member_id
        self._persist_config()

    def _consume_invite_code(self, code: str):
        """Increment usage counter for an invite code and persist."""
        for ic in self.invite_codes:
            if ic.get("code") == code:
                ic["used"] = ic.get("used", 0) + 1
                break
        self._persist_config()

    def _persist_config(self):
        """Write invite_codes and trusted_users back to the original config.yaml."""
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            raw["invite_codes"] = self.invite_codes
            raw["trusted_users"] = self.trusted_users
            with open(self._config_path, "w", encoding="utf-8") as f:
                yaml.dump(raw, f, allow_unicode=True, sort_keys=False)
            logger.debug("Config persisted with updated invite_codes/trusted_users")
        except Exception as e:
            logger.error(f"Failed to persist config: {e}", exc_info=True)

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

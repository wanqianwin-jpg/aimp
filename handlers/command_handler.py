"""handlers/command_handler.py — CommandMixin: Member command parsing and dispatch."""
from __future__ import annotations
import logging
import time
from typing import Optional

from lib.negotiator import call_llm, extract_json
from hub_prompts import parse_member_request_system, parse_member_request_user

logger = logging.getLogger(__name__)


class CommandMixin:
    """Mixin providing member command handling methods for AIMPHubAgent."""

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
        topic = (parsed.get("topic") or "").strip()
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

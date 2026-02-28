"""handlers/session_handler.py — SessionMixin: Phase 1 session scheduling methods."""
from __future__ import annotations
import json
import logging
import time
import uuid
from typing import Optional

from lib.email_client import extract_protocol_json
from lib.output import emit_event
from lib.protocol import AIMPSession

logger = logging.getLogger(__name__)


class SessionMixin:
    """Mixin providing Phase 1 meeting scheduling methods for AIMPHubAgent."""

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

    # ── Round Processing: Phase 1 ─────────────────────────────────────────

    def _apply_votes_from_protocol(self, session: AIMPSession, proto: dict, from_addr: str):
        """Apply votes embedded in an incoming protocol JSON to the session. /
        将来自 protocol JSON 的投票应用到 session。"""
        for item, item_data in proto.get("proposals", {}).items():
            for opt in item_data.get("options", []):
                if opt:
                    session.add_option(item, opt)
            voter_choice = item_data.get("votes", {}).get(from_addr)
            if voter_choice:
                try:
                    session.apply_vote(from_addr, item, voter_choice)
                except (ValueError, KeyError):
                    pass

    def _send_session_reply(self, session: AIMPSession, body: str, subject_suffix: str):
        """Send an AIMP email to all session participants. /
        向所有 session 参与者发送 AIMP 邮件。"""
        recipients = [p for p in session.participants if p != self.agent_email]
        refs = self.store.load_message_ids(session.session_id)
        msg_id = self.transport.send_aimp_email(
            to=recipients,
            session_id=session.session_id,
            version=session.version,
            subject_suffix=subject_suffix,
            body_text=body,
            protocol_json=session.to_json(),
            references=refs,
        )
        self.store.save_message_id(session.session_id, msg_id)

    def _process_session_round(self, session: AIMPSession, pending: list[dict]) -> list[dict]:
        """Process all pending emails for a completed session round. /
        处理 session 中一轮已完成的所有待处理邮件。"""
        events = []
        for e in pending:
            proto = json.loads(e["protocol_json"]) if e["protocol_json"] else None
            if proto:
                self._apply_votes_from_protocol(session, proto, e["from_addr"])
            else:
                _, details = self.negotiator.parse_human_reply(e["body"], session)
                for item, choice in details.get("votes", {}).items():
                    if choice:
                        try:
                            session.apply_vote(e["from_addr"], item, choice)
                        except (ValueError, KeyError):
                            session.add_option(item, choice)
                            session.apply_vote(e["from_addr"], item, choice)

        session.advance_round()

        if session.is_fully_resolved():
            session.status = "confirmed"
            session.bump_version()
            session.add_history(self.agent_email, "confirm", "所有议题达成共识")
            body = self.negotiator.generate_confirm_summary(session)
            self._send_session_reply(session, body, f"{session.topic} [已确认]")
            events.append({"event": "consensus", "session_id": session.session_id,
                           **session.check_consensus()})
        elif session.is_stalled():
            session.status = "escalated"
            body = self.negotiator.generate_human_readable_summary(session, "escalate")
            self._send_session_reply(session, body, session.topic)
            events.append({"event": "escalation", "session_id": session.session_id})
        else:
            session.bump_version()
            session.add_history(self.agent_email, "counter", f"第 {session.current_round} 轮汇总")
            body = self.negotiator.generate_human_readable_summary(session, "counter")
            self._send_session_reply(session, body, session.topic)
            events.append({"event": "reply_sent", "session_id": session.session_id,
                           "round": session.current_round})

        self.store.save(session)
        return events

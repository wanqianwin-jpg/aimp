"""handlers/room_handler.py — RoomMixin: Phase 2 Room lifecycle methods."""
from __future__ import annotations
import logging
import time
import uuid

from lib.output import emit_event
from lib.protocol import AIMPRoom, Artifact

logger = logging.getLogger(__name__)


class RoomMixin:
    """Mixin providing Phase 2 Room lifecycle methods for AIMPHubAgent."""

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

        # Safety net: Hub's own address must never be a participant (would cause IMAP loopback)
        hub_email = self.agent_email.lower()
        if hub_email in [p.lower() for p in participants]:
            logger.warning(
                f"[{room_id}] Hub self-address {self.agent_email} removed from participants list"
            )
            participants = [p for p in participants if p.lower() != hub_email]

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

    def _handle_room_email(self, parsed) -> list[dict]:
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

    def _apply_room_action(self, room: AIMPRoom, sender: str, action_data: dict):
        """Apply a parsed room action to the room state. /
        将解析好的 Room 动作应用到 Room 状态。"""
        action = action_data.get("action", "AMEND").upper()
        changes = action_data.get("changes", "")
        reason = action_data.get("reason", "")
        new_content = action_data.get("new_content")

        if action == "ACCEPT":
            if sender not in room.accepted_by:
                room.accepted_by.append(sender)
        elif action in ("PROPOSE", "AMEND") and new_content:
            artifact_name = f"proposal_{sender.split('@')[0]}_{int(time.time())}.txt"
            room.artifacts[artifact_name] = Artifact(
                name=artifact_name,
                content_type="text/plain",
                body_text=new_content,
                author=sender,
                timestamp=time.time(),
            )

        summary = changes or reason or ""
        sender_name = self._email_to_name(sender)
        room.add_to_transcript(
            from_agent=sender,
            action=action,
            summary=f"{sender_name}: {summary}",
        )

    def _send_room_reply(self, room: AIMPRoom, aggregate: dict):
        """Broadcast aggregated round summary to all room participants. /
        向所有参与者广播本轮汇总。"""
        if self.notify_mode != "email":
            return
        current_proposal = aggregate.get("current_proposal", "")
        summary_text = aggregate.get("summary", "")
        accepted_count = len(room.accepted_by)
        total = len(room.participants)
        deadline_iso = self._ts_to_iso(room.deadline)

        body = (
            f"[协商室更新] {room.topic}\n\n"
            f"第 {room.current_round} 轮汇总：\n\n"
            f"{current_proposal}\n\n"
            f"{'─' * 40}\n\n"
            f"{summary_text}\n\n"
            f"进度：{accepted_count}/{total} 人已 ACCEPT\n"
            f"截止时间：{deadline_iso}\n\n"
            f"回复 ACCEPT 同意当前提案，或继续发送 AMEND / PROPOSE 修改意见。\n\n"
            f"— {self.hub_name}"
        )
        for participant in room.participants:
            self.transport.send_human_email(
                to=participant,
                subject=f"[AIMP:Room:{room.room_id}] [第 {room.current_round} 轮] {room.topic}",
                body=body,
            )

    def _process_room_round(self, room: AIMPRoom, pending: list[dict]) -> list[dict]:
        """Process all pending emails for a completed room round. /
        处理 Room 中一轮已完成的所有待处理邮件。"""
        events = []
        for e in pending:
            sender = e["from_addr"]
            if sender.lower() not in [p.lower() for p in room.participants]:
                continue
            action_data = self.room_negotiator.parse_amendment(
                self._email_to_name(sender), e["body"],
                {name: a.to_dict() for name, a in room.artifacts.items()}
            )
            self._apply_room_action(room, sender, action_data)

        room.advance_round()

        if room.all_accepted() or room.is_past_deadline():
            evts = self._finalize_room(room)
            if evts:
                events.extend(evts)
            else:
                trigger = "all_accepted" if room.all_accepted() else "deadline_expired"
                events.append({"type": "room_finalized", "room_id": room.room_id, "trigger": trigger})
        else:
            aggregate = self.room_negotiator.aggregate_amendments(room)
            room.add_to_transcript(self.agent_email, "aggregate",
                                   f"第 {room.current_round} 轮汇总")
            self._send_room_reply(room, aggregate)
            events.append({"event": "room_round", "room_id": room.room_id,
                           "round": room.current_round})

        self.store.save_room(room)
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

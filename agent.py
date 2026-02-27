"""
agent.py — AIMP Agent Main Loop / AIMP Agent 主循环

Supports two notification modes: / 支持两种通知模式:
  - "email" (default) — Escalations/confirmations are sent to the owner via email / 升级/确认通过邮件发给主人
  - "stdout" — Outputs JSON events to stdout (for parsing by OpenClaw agents) / 输出 JSON 事件到 stdout（供 OpenClaw agent 解析）
"""
from __future__ import annotations
import logging
import sys
import time
import os
from typing import Optional

import yaml

from lib.email_client import ParsedEmail, is_aimp_email, extract_protocol_json
from lib.transport import EmailTransport, BaseTransport
from lib.protocol import AIMPSession
from lib.negotiator import Negotiator
from lib.session_store import SessionStore
from lib.output import emit_event

logger = logging.getLogger(__name__)


def load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class AIMPAgent:
    def __init__(self, config_path: str, notify_mode: str = "email",
                 db_path: str = None):
        """
        Args:
            config_path: Path to YAML configuration file / YAML 配置文件路径
            notify_mode: "email" or "stdout"
            db_path: SQLite path, default is ~/.aimp/sessions.db / SQLite 路径，默认 ~/.aimp/sessions.db
        """
        self.config = load_yaml(config_path)
        agent_cfg = self.config["agent"]
        self.agent_email: str = agent_cfg["email"]
        self.agent_name: str = agent_cfg["name"]
        self.notify_mode: str = notify_mode

        # Transport / 传输层
        smtp_port = agent_cfg.get("smtp_port", 465)
        self.transport = EmailTransport(
            email_addr=agent_cfg["email"],
            imap_server=agent_cfg["imap_server"],
            smtp_server=agent_cfg["smtp_server"],
            password=self._resolve_password(agent_cfg),
            imap_port=agent_cfg.get("imap_port", 993),
            smtp_port=smtp_port,
            auth_type=agent_cfg.get("auth_type", "basic"),
            oauth_params=agent_cfg.get("oauth_params", {}),
            # Port 587 always means STARTTLS (Outlook/Office365); 465 means SSL
            smtp_use_starttls=agent_cfg.get("smtp_use_starttls", smtp_port == 587),
        )

        # LLM Negotiator / LLM 协商器
        self.negotiator = Negotiator(
            owner_name=self.config["owner"]["name"],
            agent_email=self.agent_email,
            preferences=self.config.get("preferences", {}),
            llm_config=self.config.get("llm", {}),
        )

        # Persistence Storage / 持久化存储
        self.store = SessionStore(db_path or "~/.aimp/sessions.db")

    # ── Password Resolution / 密码解析 ──────────────────────────────────────

    def _resolve_password(self, agent_cfg: dict) -> str:
        pwd = agent_cfg.get("password", "")
        if pwd.startswith("$"):
            env_var = pwd[1:]
            val = os.environ.get(env_var)
            if not val:
                raise ValueError(f"Environment variable {env_var} not set / 环境变量 {env_var} 未设置")
            return val
        return pwd

    # ── Main Loop / 主循环 ────────────────────────────────────────

    def run(self, poll_interval: int = 30):
        logger.info(f"Agent [{self.agent_name}] started, polling interval {poll_interval}s / Agent [{self.agent_name}] 启动，轮询间隔 {poll_interval}s")
        while True:
            try:
                self.poll()
            except Exception as e:
                logger.error(f"poll exception: {e} / poll 异常: {e}", exc_info=True)
            time.sleep(poll_interval)

    def poll(self):
        """Execute one poll cycle and return the list of occurred events / 执行一次轮询，返回发生的事件列表"""
        events = []
        emails = self.transport.fetch_aimp_emails(since_minutes=60)
        for parsed in emails:
            try:
                evts = self.handle_email(parsed)
                events.extend(evts)
            except Exception as e:
                logger.error(f"Failed to process email [{parsed.subject}]: {e} / 处理邮件失败 [{parsed.subject}]: {e}", exc_info=True)
        return events

    # ── Email Processing / 邮件处理 ──────────────────────────────────────

    def handle_email(self, parsed: ParsedEmail) -> list[dict]:
        """Process an email and return a list of events / 处理一封邮件，返回事件列表"""
        # Ignore emails sent by self / 忽略自己发的邮件
        if parsed.sender == self.agent_email:
            return []

        logger.info(f"Received email: [{parsed.subject}] from={parsed.sender} / 收到邮件: [{parsed.subject}] from={parsed.sender}")

        if is_aimp_email(parsed):
            return self._handle_aimp_email(parsed)
        else:
            return self._handle_human_email(parsed)

    def _handle_aimp_email(self, parsed: ParsedEmail) -> list[dict]:
        """Process AIMP protocol email from another Agent / 处理来自其他 Agent 的 AIMP 协议邮件"""
        events = []
        data = extract_protocol_json(parsed)
        if not data:
            logger.warning("AIMP email but protocol.json could not be parsed, ignoring / AIMP 邮件但无法解析 protocol.json，忽略")
            return events

        session = AIMPSession.from_json(data)
        session_id = session.session_id

        # Save to persistence storage / 保存到持久化存储
        self.store.save(session)

        # If the other party has sent confirm, notify the owner and finish / 如果对方已经发 confirm，通知主人并结束
        last_action = session.history[-1].action if session.history else ""
        if last_action == "confirm" or session.status == "confirmed":
            logger.info(f"[{session_id}] Session confirmed, notifying owner / 会话已确认，通知主人")
            self._notify_owner_confirmed(session)
            events.append(self._make_consensus_event(session))
            return events

        # Stall detection / 超轮检测
        if session.is_stalled() and last_action not in ("confirm", "escalate"):
            logger.warning(f"[{session_id}] Exceeded {session.round_count()} rounds, escalating to human / 超过 {session.round_count()} 轮，升级给人类")
            self._escalate_to_owner(session, reason="Too many negotiation rounds, human decision needed / 协商轮数过多，需要人类决策")
            events.append(self._make_escalation_event(session, "Too many negotiation rounds, human decision needed / 协商轮数过多，需要人类决策"))
            return events

        # Fully resolved consensus reached -> send confirm / 已完全达成共识 → 发 confirm
        if session.is_fully_resolved():
            self._send_confirm(session, parsed)
            events.append(self._make_consensus_event(session))
            return events

        # Call LLM for decision / 调用 LLM 决策
        action, details = self.negotiator.decide(session)
        logger.info(f"[{session_id}] LLM Decision: action={action}, reason={details.get('reason','')} / LLM 决策: action={action}, reason={details.get('reason','')}")

        if action == "escalate":
            self._escalate_to_owner(session, details.get("reason", ""))
            events.append(self._make_escalation_event(session, details.get("reason", "")))
            return events

        # Apply votes / 应用投票
        votes = details.get("votes", {})
        for item, choice in votes.items():
            if choice:
                try:
                    session.apply_vote(self.agent_email, item, choice)
                except ValueError as e:
                    logger.warning(f"Vote failed: {e} / 投票失败: {e}")

        # Add new options (counter) / 添加新选项（counter）
        new_opts = details.get("new_options", {})
        for item, opts in new_opts.items():
            for opt in (opts or []):
                session.add_option(item, opt)

        # Check consensus again / 再次检查共识
        if session.is_fully_resolved():
            self._send_confirm(session, parsed)
            events.append(self._make_consensus_event(session))
            return events

        # Send reply / 发送回复
        self._send_reply(session, action, parsed, details.get("reason", ""))
        events.append({
            "type": "reply_sent",
            "session_id": session.session_id,
            "action": action,
            "version": session.version,
        })
        return events

    def _handle_human_email(self, parsed: ParsedEmail) -> list[dict]:
        """Process email from human (non-Agent) (Degradation Mode) / 处理人类（非 Agent）发来的邮件（降级模式）"""
        events = []
        session_id = parsed.session_id
        if not session_id:
            logger.info(f"No session_id, ignoring human email / 无 session_id，忽略人类邮件")
            return events

        session = self.store.load(session_id)
        if not session:
            logger.info(f"No corresponding session found for session_id={session_id}, ignoring human email / 无对应会话 session_id={session_id}，忽略人类邮件")
            return events

        action, details = self.negotiator.parse_human_reply(parsed.body, session)
        logger.info(f"[{session_id}] Parsing human reply: action={action} / 解析人类回复: action={action}")

        votes = details.get("votes", {})
        for item, choice in votes.items():
            if choice:
                try:
                    session.apply_vote(parsed.sender, item, choice)
                except ValueError as e:
                    logger.warning(f"Human vote failed: {e} / 人类投票失败: {e}")

        if session.is_fully_resolved():
            self._send_confirm(session, parsed)
            events.append(self._make_consensus_event(session))
            return events

        if action == "escalate":
            self._escalate_to_owner(session, details.get("reason", "Human reply could not be parsed / 人类回复无法解析"))
            events.append(self._make_escalation_event(session, details.get("reason", "")))
            return events

        self._send_reply(session, action, parsed, details.get("reason", ""))
        events.append({
            "type": "reply_sent",
            "session_id": session.session_id,
            "action": action,
            "version": session.version,
        })
        return events

    # ── Sending Operations / 发送操作 ──────────────────────────────────────

    def _send_reply(self, session: AIMPSession, action: str,
                    received: Optional[ParsedEmail], reason: str = ""):
        """Send accept or counter reply / 发送 accept 或 counter 回复"""
        session.bump_version()
        session.add_history(
            from_agent=self.agent_email,
            action=action,
            summary=reason or action,
        )

        summary = self.negotiator.generate_human_readable_summary(session, action, reason)
        protocol_data = session.to_json()

        recipients = [p for p in session.participants if p != self.agent_email]

        refs = self.store.load_message_ids(session.session_id)
        in_reply_to = received.message_id if received else None
        if in_reply_to and in_reply_to not in refs:
            refs.append(in_reply_to)

        msg_id = self.transport.send_aimp_email(
            to=recipients,
            session_id=session.session_id,
            version=session.version,
            subject_suffix=session.topic,
            body_text=summary,
            protocol_json=protocol_data,
            references=refs,
            in_reply_to=in_reply_to,
        )
        self.store.save_message_id(session.session_id, msg_id)
        self.store.save(session)
        logger.info(f"[{session.session_id}] Sent {action} reply v{session.version} / 已发送 {action} 回复 v{session.version}")

    def _send_confirm(self, session: AIMPSession, received: Optional[ParsedEmail] = None):
        """Send final confirmation email / 发送最终确认邮件"""
        session.status = "confirmed"
        session.bump_version()
        session.add_history(
            from_agent=self.agent_email,
            action="confirm",
            summary="All issues have reached consensus / 所有议题已达成共识",
        )

        summary = self.negotiator.generate_confirm_summary(session)
        recipients = [p for p in session.participants if p != self.agent_email]

        refs = self.store.load_message_ids(session.session_id)
        in_reply_to = received.message_id if received else None
        if in_reply_to and in_reply_to not in refs:
            refs.append(in_reply_to)

        msg_id = self.transport.send_aimp_email(
            to=recipients,
            session_id=session.session_id,
            version=session.version,
            subject_suffix=f"{session.topic} [Confirmed / 已确认]",
            body_text=summary,
            protocol_json=session.to_json(),
            references=refs,
            in_reply_to=in_reply_to,
        )
        self.store.save_message_id(session.session_id, msg_id)
        self.store.save(session)
        logger.info(f"[{session.session_id}] Meeting confirmed! / 会议已确认！")

        self._notify_owner_confirmed(session)

    def _escalate_to_owner(self, session: AIMPSession, reason: str):
        """Negotiation failed, escalate to owner / 协商失败，升级给主人"""
        session.status = "escalated"
        self.store.save(session)

        if self.notify_mode == "stdout":
            emit_event(
                "escalation",
                session_id=session.session_id,
                topic=session.topic,
                reason=reason,
                summary=self.negotiator.generate_human_readable_summary(
                    session, "escalate", reason
                ),
                current_proposals={
                    item: {"options": p.options, "votes": p.votes}
                    for item, p in session.proposals.items()
                },
            )
        else:
            owner_email = self.config["owner"]["email"]
            body = f"""Meeting negotiation requires your intervention! / 会议协商需要您的介入！

Topic: {session.topic} / 主题：{session.topic}
Reason: {reason} / 原因：{reason}

Current Negotiation Status / 当前协商状态：
{self.negotiator.generate_human_readable_summary(session, 'escalate', reason)}

Please reply to the relevant participants to confirm the final time and location. / 请直接回复相关参与者确定最终时间和地点。
"""
            self.transport.send_human_email(
                to=owner_email,
                subject=f"[AIMP:{session.session_id}] [Decision Required / 需要决策] {session.topic}",
                body=body,
            )
        logger.info(f"[{session.session_id}] Escalated to owner / 已升级给主人 (mode={self.notify_mode})")

    def _notify_owner_confirmed(self, session: AIMPSession):
        """Notify owner that the meeting is confirmed / 通知主人会议已确认"""
        consensus = session.check_consensus()

        if self.notify_mode == "stdout":
            emit_event(
                "consensus",
                session_id=session.session_id,
                topic=session.topic,
                **consensus,
                rounds=session.round_count(),
            )
        else:
            owner_email = self.config["owner"]["email"]
            lines = [
                "Great news! The meeting has been successfully negotiated and confirmed. / 好消息！会议已成功协商确定。",
                "",
                f"Topic: {session.topic} / 主题：{session.topic}",
            ]
            for item, val in consensus.items():
                lines.append(f"{item}: {val} / {item}：{val}")
            lines.append(f"\nNegotiation completed in {session.round_count()} rounds. / 协商经过 {session.round_count()} 轮完成。")
            body = "\n".join(lines)

            self.transport.send_human_email(
                to=owner_email,
                subject=f"Meeting Confirmed: {session.topic} / 会议确认：{session.topic}",
                body=body,
            )
        logger.info(f"Owner notified / 已通知主人 (mode={self.notify_mode})")

    # ── Event Construction / 事件构造 ──────────────────────────────────────

    def _make_consensus_event(self, session: AIMPSession) -> dict:
        """Construct consensus event data / 构造共识达成事件数据"""
        consensus = session.check_consensus()
        return {
            "type": "consensus",
            "session_id": session.session_id,
            "topic": session.topic,
            "rounds": session.round_count(),
            **consensus,
        }

    def _make_escalation_event(self, session: AIMPSession, reason: str) -> dict:
        """Construct escalation event data / 构造升级事件数据"""
        return {
            "type": "escalation",
            "session_id": session.session_id,
            "topic": session.topic,
            "reason": reason,
            "current_proposals": {
                item: {"options": p.options, "votes": p.votes}
                for item, p in session.proposals.items()
            },
        }

    # ── Initiate Meeting / 发起会议 ──────────────────────────────────────

    def initiate_meeting(self, topic: str, participant_names: list[str]) -> str:
        """Called when human initiates a meeting request, returns session_id / 人类发起会议请求时调用，返回 session_id"""
        import uuid
        session_id = f"meeting-{int(time.time())}-{uuid.uuid4().hex[:6]}"

        contacts = self.config.get("contacts", {})
        participants = [self.agent_email]
        to_agents: list[str] = []
        to_humans: list[str] = []

        for name in participant_names:
            if name not in contacts:
                # If email address is provided, treat it directly as human participant (no pre-config needed) / 如果输入的是邮箱地址，直接作为人类参与者处理（无需预先配置联系人）
                if "@" in name:
                    participants.append(name)
                    to_humans.append(name)
                    logger.info(f"Added temporary contact: {name} / 添加临时联系人: {name}")
                else:
                    logger.warning(f"Contact {name} not in address book, skipping / 联系人 {name} 不在通讯录中，跳过")
                continue
            contact = contacts[name]
            if contact.get("has_agent"):
                addr = contact["agent_email"]
                participants.append(addr)
                to_agents.append(addr)
            else:
                addr = contact["human_email"]
                participants.append(addr)
                to_humans.append(addr)

        session = AIMPSession(
            session_id=session_id,
            topic=topic,
            participants=participants,
            initiator=self.agent_email,
        )

        prefs = self.config.get("preferences", {})
        for t in prefs.get("preferred_times", []):
            session.add_option("time", t)
        for loc in prefs.get("preferred_locations", []):
            session.add_option("location", loc)

        preferred_times = prefs.get("preferred_times", [])
        preferred_locs = prefs.get("preferred_locations", [])
        if preferred_times:
            session.apply_vote(self.agent_email, "time", preferred_times[0])
        if preferred_locs:
            session.apply_vote(self.agent_email, "location", preferred_locs[0])

        session.bump_version()
        session.add_history(
            from_agent=self.agent_email,
            action="propose",
            summary=f"Initiated meeting proposal: {topic} / 发起会议提议：{topic}",
        )
        self.store.save(session)

        summary = self.negotiator.generate_human_readable_summary(session, "propose")
        protocol_data = session.to_json()

        if to_agents:
            msg_id = self.transport.send_aimp_email(
                to=to_agents,
                session_id=session_id,
                version=session.version,
                subject_suffix=topic,
                body_text=summary,
                protocol_json=protocol_data,
            )
            self.store.save_message_id(session_id, msg_id)
            logger.info(f"[{session_id}] Initiated meeting proposal to Agents: {to_agents} / 已发起会议提议给 Agents: {to_agents}")

        for human_addr in to_humans:
            body = self.negotiator.generate_human_email_body(session)
            self.transport.send_human_email(
                to=human_addr,
                subject=f"[AIMP:{session_id}] Meeting Invitation: {topic} / 会议邀请：{topic}",
                body=body,
            )
            logger.info(f"[{session_id}] Sent fallback email to human: {human_addr} / 已发降级邮件给人类: {human_addr}")

        if self.notify_mode == "stdout":
            emit_event(
                "initiated",
                session_id=session_id,
                topic=topic,
                participants=participants,
            )

        return session_id


# ── Entry Point (Standalone mode) / 入口（独立运行模式）────────────────────────────

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stdout,
    )
    if len(sys.argv) < 2:
        print("Usage: python agent.py <config_path> [poll_interval] [--notify stdout|email]")
        print("用法: python agent.py <config_path> [poll_interval] [--notify stdout|email]")
        sys.exit(1)

    config_path = sys.argv[1]
    poll_interval = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 30
    notify_mode = "email"
    if "--notify" in sys.argv:
        idx = sys.argv.index("--notify")
        if idx + 1 < len(sys.argv):
            notify_mode = sys.argv[idx + 1]

    agent = AIMPAgent(config_path, notify_mode=notify_mode)
    agent.run(poll_interval=poll_interval)


if __name__ == "__main__":
    main()

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
import json
import logging
import sys
import time
import os
from typing import Optional

import yaml

from lib.email_client import ParsedEmail, is_aimp_email, extract_protocol_json
from lib.protocol import AIMPSession
from lib.output import emit_event
from agent import AIMPAgent
from lib.hub_negotiator import HubNegotiator
from lib.room_negotiator import RoomNegotiator
from handlers.session_handler import SessionMixin
from handlers.room_handler import RoomMixin
from handlers.command_handler import CommandMixin
from handlers.registration_handler import RegistrationMixin

logger = logging.getLogger(__name__)


def load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ──────────────────────────────────────────────────────
# AIMPHubAgent
# ──────────────────────────────────────────────────────

class AIMPHubAgent(SessionMixin, RoomMixin, CommandMixin, RegistrationMixin, AIMPAgent):
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

    # ── Hub Poll 覆写：额外收取成员指令邮件 ──────────────

    def poll(self):
        """
        Hub 版 poll（Store-First + Round-Gated）：
          1. Phase 2: 先入库，等本轮所有参与者回复后统一处理
          2. Phase 1: 先入库，等本轮所有参与者回复后统一处理
          3. 成员指令：即时处理，仍先存库作审计
          4. 检查 deadline 已过的 Room
        """
        events = []

        # ── Phase 2: Room 邮件 ──────────────────────────────────────────────
        try:
            for parsed in self.transport.fetch_phase2_emails(since_minutes=60):
                if parsed.sender == self.agent_email or not parsed.room_id:
                    continue
                room = self.store.load_room(parsed.room_id)
                if not room:
                    continue
                self.store.save_pending_email(
                    from_addr=parsed.sender, subject=parsed.subject,
                    body=parsed.body, room_id=parsed.room_id,
                )
                room.record_round_reply(parsed.sender)
                self.store.save_room(room)
                if room.is_round_complete():
                    pending = self.store.load_pending_for_room(parsed.room_id)
                    evts = self._process_room_round(room, pending)
                    events.extend(evts)
                    for e in pending:
                        self.store.mark_processed(e["id"])
        except Exception as e:
            logger.error(f"Phase 2 room poll failed: {e}", exc_info=True)

        # ── Phase 1: AIMP session 邮件 ─────────────────────────────────────
        try:
            for parsed in self.transport.fetch_aimp_emails(since_minutes=60):
                if parsed.sender == self.agent_email or not parsed.session_id:
                    continue
                session = self.store.load(parsed.session_id)
                if not session:
                    continue
                proto = extract_protocol_json(parsed)
                proto_json = json.dumps(proto) if proto else None
                self.store.save_pending_email(
                    from_addr=parsed.sender, subject=parsed.subject,
                    body=parsed.body, protocol_json=proto_json,
                    session_id=parsed.session_id,
                )
                session.record_round_reply(parsed.sender)
                self.store.save(session)
                if session.is_round_complete():
                    pending = self.store.load_pending_for_session(parsed.session_id)
                    evts = self._process_session_round(session, pending)
                    events.extend(evts)
                    for e in pending:
                        self.store.mark_processed(e["id"])
        except Exception as e:
            logger.error(f"Phase 1 session poll failed: {e}", exc_info=True)

        # ── 成员指令：即时处理，仍先存库作审计 ──────────────────────────────
        try:
            for parsed in self.transport.fetch_all_unread_emails(since_minutes=60):
                if parsed.sender == self.agent_email:
                    continue
                subj = parsed.subject or ""
                if "[AIMP:Room:" in subj or is_aimp_email(parsed):
                    continue  # 已由 Phase 1 / Phase 2 处理（有 protocol.json 或 Room 邮件）

                # 人类对 session 邮件的回复（有 [AIMP:] 但无 protocol.json）→ 作为人工投票入库
                if "[AIMP:" in subj and parsed.session_id:
                    session = self.store.load(parsed.session_id)
                    if session and session.status == "negotiating":
                        self.store.save_pending_email(
                            from_addr=parsed.sender, subject=parsed.subject,
                            body=parsed.body, session_id=parsed.session_id,
                        )
                        session.record_round_reply(parsed.sender)
                        self.store.save(session)
                        if session.is_round_complete():
                            pending = self.store.load_pending_for_session(parsed.session_id)
                            evts = self._process_session_round(session, pending)
                            events.extend(evts)
                            for e in pending:
                                self.store.mark_processed(e["id"])
                    continue

                self.store.save_pending_email(
                    from_addr=parsed.sender, subject=parsed.subject, body=parsed.body,
                )
                member_id = self.identify_sender(parsed.sender)
                if member_id:
                    evts = self.handle_member_command(
                        parsed.sender, parsed.body, subject=parsed.subject or ""
                    )
                    events.extend(evts)
                elif self._is_auto_reply(parsed.sender, parsed.subject or ""):
                    logger.debug(f"Skipping auto-reply/bounce from: {parsed.sender}")
                    continue
                else:
                    invite_evts = self._check_invite_email(parsed)
                    if invite_evts is not None:
                        events.extend(invite_evts)
                    else:
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


# ──────────────────────────────────────────────────────
# Factory Function: Automatically returns correct Agent type based on config /
# 工厂函数：根据 config 自动返回正确的 Agent 类型
# ──────────────────────────────────────────────────────

def create_agent(config_path: str, notify_mode: str = "email", db_path: str = None) -> "AIMPHubAgent":
    """
    Return an AIMPHubAgent for the given Hub config file. /
    返回指定 Hub 配置文件对应的 AIMPHubAgent。

    Raises ValueError if the config is not a Hub config (missing "members:" field). /
    若配置文件不是 Hub 模式（缺少 members: 字段）则抛出 ValueError。
    """
    with open(os.path.expanduser(config_path), "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    if "members" not in cfg and cfg.get("mode") != "hub":
        raise ValueError(
            f"配置文件 {config_path} 不是 Hub 模式（缺少 members: 字段）"
        )

    logger.info("Hub mode configuration detected, using AIMPHubAgent / 检测到 Hub 模式配置，使用 AIMPHubAgent")
    return AIMPHubAgent(config_path, notify_mode=notify_mode, db_path=db_path)


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

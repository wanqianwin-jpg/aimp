"""handlers/registration_handler.py — RegistrationMixin: Invite code self-registration."""
from __future__ import annotations
import logging
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


class RegistrationMixin:
    """Mixin providing invite-code self-registration methods for AIMPHubAgent."""

    # ── 邀请码自助注册系统 ──────────────────────────────

    def _check_invite_email(self, parsed) -> Optional[list[dict]]:
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

"""
Unit tests for AIMPHubAgent — core paths only.

Strategy: bypass __init__ via object.__new__(), manually set the minimum
attributes each method under test actually reads.
"""
import sys
import os
import unittest
from unittest.mock import MagicMock, patch
from datetime import date, timedelta

# Resolve import paths
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hub_agent import AIMPHubAgent
from agent import AIMPAgent
from lib.email_client import ParsedEmail
from lib.protocol import AIMPSession


# ── Fixture factory ──────────────────────────────────────────────────────────

def make_hub(**overrides) -> AIMPHubAgent:
    """Create a minimal AIMPHubAgent without touching files or network."""
    hub = object.__new__(AIMPHubAgent)
    hub.hub_name = "TestHub"
    hub.hub_email = "hub@test.com"
    hub.notify_mode = "email"
    hub.members = {}
    hub._raw_config = {"contacts": {}}
    hub.invite_codes = []
    hub.trusted_users = {}
    hub._email_to_member = {}
    hub._replied_senders = {}
    hub.email_client = MagicMock()
    hub.store = MagicMock()
    hub.negotiator = MagicMock()
    hub.hub_negotiator = MagicMock()
    hub.hub_negotiator.model = "claude-test"
    hub.hub_negotiator.provider = "anthropic"
    hub.hub_negotiator.client = MagicMock()
    for k, v in overrides.items():
        setattr(hub, k, v)
    return hub


def make_parsed(
    sender="alice@example.com",
    subject="Hello",
    body="Some body",
    session_id=None,
    sender_name=None,
) -> ParsedEmail:
    return ParsedEmail(
        message_id="<test@x>",
        subject=subject,
        sender=sender,
        sender_name=sender_name,
        recipients=[],
        body=body,
        attachments=[],
        references=[],
        session_id=session_id,
    )


# ── _validate_config ─────────────────────────────────────────────────────────

class TestValidateConfig(unittest.TestCase):
    def setUp(self):
        self.hub = make_hub()

    def _valid(self):
        return {
            "hub": {
                "email": "hub@x.com",
                "imap_server": "imap.x.com",
                "smtp_server": "smtp.x.com",
            },
            "members": {"alice": {"email": "alice@x.com"}},
            "llm": {"provider": "anthropic", "model": "claude-test"},
        }

    def test_valid_passes(self):
        self.hub._validate_config(self._valid())  # must not raise

    def test_missing_hub_email(self):
        cfg = self._valid()
        del cfg["hub"]["email"]
        with self.assertRaises(ValueError):
            self.hub._validate_config(cfg)

    def test_missing_imap_server(self):
        cfg = self._valid()
        del cfg["hub"]["imap_server"]
        with self.assertRaises(ValueError):
            self.hub._validate_config(cfg)

    def test_missing_smtp_server(self):
        cfg = self._valid()
        del cfg["hub"]["smtp_server"]
        with self.assertRaises(ValueError):
            self.hub._validate_config(cfg)

    def test_empty_members(self):
        cfg = self._valid()
        cfg["members"] = {}
        with self.assertRaises(ValueError):
            self.hub._validate_config(cfg)

    def test_missing_llm_provider(self):
        cfg = self._valid()
        del cfg["llm"]["provider"]
        with self.assertRaises(ValueError):
            self.hub._validate_config(cfg)

    def test_missing_llm_model(self):
        cfg = self._valid()
        del cfg["llm"]["model"]
        with self.assertRaises(ValueError):
            self.hub._validate_config(cfg)


# ── _is_auto_reply ───────────────────────────────────────────────────────────

class TestIsAutoReply(unittest.TestCase):
    def setUp(self):
        self.hub = make_hub()

    # Sender-local-part patterns
    def test_noreply(self):
        self.assertTrue(self.hub._is_auto_reply("noreply@example.com", "Hi"))

    def test_no_reply(self):
        self.assertTrue(self.hub._is_auto_reply("no-reply@example.com", "Hi"))

    def test_mailer_daemon(self):
        self.assertTrue(self.hub._is_auto_reply("mailer-daemon@example.com", "bounce"))

    def test_postmaster(self):
        self.assertTrue(self.hub._is_auto_reply("postmaster@example.com", "delivery"))

    def test_bounce(self):
        self.assertTrue(self.hub._is_auto_reply("bounce@example.com", ""))

    def test_notifications_local(self):
        self.assertTrue(self.hub._is_auto_reply("notifications@service.io", ""))

    # Normal senders
    def test_normal_sender(self):
        self.assertFalse(self.hub._is_auto_reply("alice@example.com", "Re: Meeting"))

    def test_sender_containing_name(self):
        # "notify" is not in the frozenset, should not match
        self.assertFalse(self.hub._is_auto_reply("notify-user@example.com", "Hello"))

    # Subject patterns
    def test_out_of_office(self):
        self.assertTrue(self.hub._is_auto_reply("alice@example.com", "Out of office: back Monday"))

    def test_automatic_reply(self):
        self.assertTrue(self.hub._is_auto_reply("alice@example.com", "Automatic Reply: Meeting invite"))

    def test_auto_reply_subject(self):
        self.assertTrue(self.hub._is_auto_reply("alice@example.com", "AutoReply: I'm on leave"))

    def test_undeliverable(self):
        self.assertTrue(self.hub._is_auto_reply("mail@server.com", "Undeliverable: your message"))

    def test_normal_subject(self):
        self.assertFalse(self.hub._is_auto_reply("alice@example.com", "Re: Let's meet Tuesday"))


# ── _validate_invite_code ────────────────────────────────────────────────────

class TestValidateInviteCode(unittest.TestCase):
    def setUp(self):
        future = (date.today() + timedelta(days=30)).isoformat()
        past = (date.today() - timedelta(days=1)).isoformat()
        self.hub = make_hub(
            invite_codes=[
                {"code": "valid-unlimited", "expires": future},
                {"code": "valid-with-limit", "expires": future, "max_uses": 5, "used": 3},
                {"code": "expired", "expires": past},
                {"code": "at-limit", "max_uses": 3, "used": 3},
                {"code": "exactly-full", "max_uses": 1, "used": 1},
                {"code": "no-expiry-no-limit"},
            ]
        )

    def test_not_found_returns_none(self):
        self.assertIsNone(self.hub._validate_invite_code("nonexistent"))

    def test_expired_returns_none(self):
        self.assertIsNone(self.hub._validate_invite_code("expired"))

    def test_at_limit_returns_none(self):
        self.assertIsNone(self.hub._validate_invite_code("at-limit"))

    def test_exactly_full_returns_none(self):
        self.assertIsNone(self.hub._validate_invite_code("exactly-full"))

    def test_valid_unlimited_returns_dict(self):
        result = self.hub._validate_invite_code("valid-unlimited")
        self.assertIsNotNone(result)
        self.assertEqual(result["code"], "valid-unlimited")

    def test_valid_with_remaining_uses(self):
        result = self.hub._validate_invite_code("valid-with-limit")
        self.assertIsNotNone(result)

    def test_no_expiry_no_limit(self):
        result = self.hub._validate_invite_code("no-expiry-no-limit")
        self.assertIsNotNone(result)


# ── _find_participant_contact ─────────────────────────────────────────────────

class TestFindParticipantContact(unittest.TestCase):
    def setUp(self):
        self.hub = make_hub(
            members={
                "alice": {"name": "Alice", "email": "alice@hub.com"},
                "bob_id": {"name": "Bob", "email": "bob@hub.com"},
            },
            _raw_config={
                "contacts": {
                    "Carol": {"has_agent": True, "agent_email": "carol-agent@aimp.io"},
                    "Dave": {"human_email": "dave@personal.com"},
                }
            },
        )

    def test_hub_member_by_display_name(self):
        result = self.hub._find_participant_contact("Alice")
        self.assertIsNotNone(result)
        self.assertEqual(result["email"], "alice@hub.com")
        self.assertFalse(result["has_agent"])

    def test_hub_member_case_insensitive(self):
        result = self.hub._find_participant_contact("alice")
        self.assertEqual(result["email"], "alice@hub.com")

    def test_hub_member_by_member_id(self):
        result = self.hub._find_participant_contact("bob_id")
        self.assertEqual(result["email"], "bob@hub.com")

    def test_contact_with_aimp_agent(self):
        result = self.hub._find_participant_contact("Carol")
        self.assertIsNotNone(result)
        self.assertEqual(result["email"], "carol-agent@aimp.io")
        self.assertTrue(result["has_agent"])

    def test_contact_human_only(self):
        result = self.hub._find_participant_contact("Dave")
        self.assertIsNotNone(result)
        self.assertEqual(result["email"], "dave@personal.com")
        self.assertFalse(result["has_agent"])

    def test_bare_email_address(self):
        result = self.hub._find_participant_contact("eve@external.org")
        self.assertIsNotNone(result)
        self.assertEqual(result["email"], "eve@external.org")
        self.assertFalse(result["has_agent"])

    def test_unknown_name_returns_none(self):
        self.assertIsNone(self.hub._find_participant_contact("Nobody Known"))


# ── _check_invite_email ───────────────────────────────────────────────────────

class TestCheckInviteEmail(unittest.TestCase):
    def setUp(self):
        future = (date.today() + timedelta(days=30)).isoformat()
        self.hub = make_hub(
            invite_codes=[{"code": "open2026", "expires": future}],
        )
        # Stranger not yet registered
        self.hub.identify_sender = MagicMock(return_value=None)
        # Suppress file writes
        self.hub._persist_config = MagicMock()

    def test_no_invite_pattern_returns_none(self):
        parsed = make_parsed(subject="Hello World")
        self.assertIsNone(self.hub._check_invite_email(parsed))

    def test_valid_invite_code_accepted(self):
        parsed = make_parsed(
            sender="stranger@out.com",
            sender_name="Stranger",
            subject="[AIMP-INVITE:open2026] Register me",
        )
        result = self.hub._check_invite_email(parsed)
        self.assertIsNotNone(result)
        self.assertEqual(result[0]["type"], "invite_accepted")
        # Welcome email sent
        self.hub.email_client.send_human_email.assert_called()

    def test_invalid_code_rejected(self):
        parsed = make_parsed(subject="[AIMP-INVITE:badcode] Register me")
        result = self.hub._check_invite_email(parsed)
        self.assertIsNotNone(result)
        self.assertEqual(result[0]["type"], "invite_rejected")

    def test_already_registered_returns_empty_list(self):
        self.hub.identify_sender = MagicMock(return_value="alice")
        parsed = make_parsed(
            sender="alice@hub.com",
            subject="[AIMP-INVITE:open2026]",
        )
        result = self.hub._check_invite_email(parsed)
        self.assertEqual(result, [])

    def test_case_insensitive_pattern(self):
        parsed = make_parsed(subject="[aimp-invite:open2026] hey")
        result = self.hub._check_invite_email(parsed)
        # Should still detect the invite
        self.assertIsNotNone(result)


# ── _parse_member_request ─────────────────────────────────────────────────────

class TestParseMemberRequest(unittest.TestCase):
    def setUp(self):
        self.hub = make_hub(hub_name="TestHub")

    def test_successful_parse(self):
        expected = {
            "action": "schedule_meeting",
            "topic": "Q2 Review",
            "participants": ["Bob"],
            "missing": [],
        }
        with patch("hub_agent.call_llm", return_value='{"action":"schedule_meeting"}'), \
             patch("hub_agent.extract_json", return_value=expected):
            result = self.hub._parse_member_request("Alice", "Schedule Q2 with Bob")
        self.assertEqual(result["action"], "schedule_meeting")
        self.assertEqual(result["topic"], "Q2 Review")
        self.assertEqual(result["participants"], ["Bob"])

    def test_subject_included_in_prompt_when_present(self):
        with patch("hub_agent.call_llm", return_value="{}") as mock_llm, \
             patch("hub_agent.extract_json", return_value={"action": "unclear", "topic": None, "participants": [], "missing": []}):
            self.hub._parse_member_request("Alice", "body text", subject="Budget meeting")
        # The user prompt (5th arg) should contain the subject
        user_prompt = mock_llm.call_args[0][4]
        self.assertIn("Budget meeting", user_prompt)

    def test_subject_omitted_when_empty(self):
        with patch("hub_agent.call_llm", return_value="{}") as mock_llm, \
             patch("hub_agent.extract_json", return_value={"action": "unclear", "topic": None, "participants": [], "missing": []}):
            self.hub._parse_member_request("Alice", "body text", subject="")
        user_prompt = mock_llm.call_args[0][4]
        self.assertNotIn("Email subject:", user_prompt)

    def test_llm_failure_returns_fallback(self):
        with patch("hub_agent.call_llm", side_effect=Exception("API timeout")):
            result = self.hub._parse_member_request("Alice", "unclear stuff")
        self.assertEqual(result["action"], "unclear")
        self.assertIn("topic", result["missing"])
        self.assertIn("participants", result["missing"])


# ── _handle_human_email (Hub auto-registration) ───────────────────────────────

class TestHandleHumanEmailAutoRegistration(unittest.TestCase):
    def _make_session(self, participants):
        session = MagicMock(spec=AIMPSession)
        session.participants = list(participants)
        return session

    def setUp(self):
        self.hub = make_hub()

    def test_invited_participant_auto_registered_on_first_reply(self):
        """Sender in session.participants + not a member → auto-register."""
        self.hub.identify_sender = MagicMock(return_value=None)
        session = self._make_session(["hub@test.com", "stranger@out.com"])
        self.hub.store.load = MagicMock(return_value=session)

        parsed = make_parsed(
            sender="stranger@out.com",
            sender_name="Stranger Sam",
            subject="[AIMP:sess-1] vote",
            session_id="sess-1",
        )
        with patch.object(self.hub, "_register_trusted_user") as mock_reg, \
             patch.object(AIMPAgent, "_handle_human_email", return_value=[]):
            self.hub._handle_human_email(parsed)

        mock_reg.assert_called_once_with("stranger@out.com", "Stranger Sam", via_code=None)

    def test_non_participant_not_registered(self):
        """Sender not in session.participants → no registration."""
        self.hub.identify_sender = MagicMock(return_value=None)
        session = self._make_session(["hub@test.com", "alice@hub.com"])
        self.hub.store.load = MagicMock(return_value=session)

        parsed = make_parsed(
            sender="random@out.com",
            subject="[AIMP:sess-1] hi",
            session_id="sess-1",
        )
        with patch.object(self.hub, "_register_trusted_user") as mock_reg, \
             patch.object(AIMPAgent, "_handle_human_email", return_value=[]):
            self.hub._handle_human_email(parsed)

        mock_reg.assert_not_called()

    def test_known_member_not_re_registered(self):
        """identify_sender returns a member_id → skip registration."""
        self.hub.identify_sender = MagicMock(return_value="alice")
        session = self._make_session(["hub@test.com", "alice@hub.com"])
        self.hub.store.load = MagicMock(return_value=session)

        parsed = make_parsed(
            sender="alice@hub.com",
            subject="[AIMP:sess-1] reply",
            session_id="sess-1",
        )
        with patch.object(self.hub, "_register_trusted_user") as mock_reg, \
             patch.object(AIMPAgent, "_handle_human_email", return_value=[]):
            self.hub._handle_human_email(parsed)

        mock_reg.assert_not_called()

    def test_auto_reply_sender_not_registered(self):
        """Bounce/auto-reply address → skip registration even if in session."""
        self.hub.identify_sender = MagicMock(return_value=None)
        session = self._make_session(["hub@test.com", "noreply@service.com"])
        self.hub.store.load = MagicMock(return_value=session)

        parsed = make_parsed(
            sender="noreply@service.com",
            subject="[AIMP:sess-1] Automatic Reply: on leave",
            session_id="sess-1",
        )
        with patch.object(self.hub, "_register_trusted_user") as mock_reg, \
             patch.object(AIMPAgent, "_handle_human_email", return_value=[]):
            self.hub._handle_human_email(parsed)

        mock_reg.assert_not_called()

    def test_no_session_id_not_registered(self):
        """No session_id in email → cannot verify invitation → no registration."""
        self.hub.identify_sender = MagicMock(return_value=None)

        parsed = make_parsed(sender="stranger@out.com", session_id=None)
        with patch.object(self.hub, "_register_trusted_user") as mock_reg, \
             patch.object(AIMPAgent, "_handle_human_email", return_value=[]):
            self.hub._handle_human_email(parsed)

        mock_reg.assert_not_called()

    def test_parent_handle_always_called(self):
        """super()._handle_human_email must be called regardless of registration."""
        self.hub.identify_sender = MagicMock(return_value=None)
        session = self._make_session(["hub@test.com", "stranger@out.com"])
        self.hub.store.load = MagicMock(return_value=session)

        parsed = make_parsed(
            sender="stranger@out.com",
            session_id="sess-1",
        )
        with patch.object(self.hub, "_register_trusted_user"), \
             patch.object(AIMPAgent, "_handle_human_email", return_value=["evt"]) as mock_parent:
            result = self.hub._handle_human_email(parsed)

        mock_parent.assert_called_once_with(parsed)
        self.assertEqual(result, ["evt"])


if __name__ == "__main__":
    unittest.main()

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

import time

from hub_agent import AIMPHubAgent, RoomNegotiator
from agent import AIMPAgent
from lib.email_client import ParsedEmail
from lib.protocol import AIMPSession, AIMPRoom, Artifact
from lib.session_store import SessionStore


# ── Fixture factory ──────────────────────────────────────────────────────────

def make_hub(**overrides) -> AIMPHubAgent:
    """Create a minimal AIMPHubAgent without touching files or network."""
    hub = object.__new__(AIMPHubAgent)
    hub.hub_name = "TestHub"
    hub.hub_email = "hub@test.com"
    hub.agent_email = "hub@test.com"
    hub.notify_mode = "email"
    hub.members = {}
    hub._raw_config = {"contacts": {}}
    hub.invite_codes = []
    hub.trusted_users = {}
    hub._email_to_member = {}
    hub._replied_senders = {}
    hub.transport = MagicMock()
    hub.store = MagicMock()
    hub.store.save_pending_email = MagicMock(return_value=1)
    hub.store.load_pending_for_session = MagicMock(return_value=[])
    hub.store.load_pending_for_room = MagicMock(return_value=[])
    hub.store.mark_processed = MagicMock()
    hub.negotiator = MagicMock()
    hub.hub_negotiator = MagicMock()
    hub.hub_negotiator.model = "claude-test"
    hub.hub_negotiator.provider = "anthropic"
    hub.hub_negotiator.client = MagicMock()
    hub.room_negotiator = MagicMock()
    for k, v in overrides.items():
        setattr(hub, k, v)
    return hub


def make_parsed(
    sender="alice@example.com",
    subject="Hello",
    body="Some body",
    session_id=None,
    sender_name=None,
    room_id=None,
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
        room_id=room_id,
    )


def make_room(
    room_id="room-001",
    topic="Q3 Budget",
    participants=None,
    status="open",
    deadline_offset=3600,
) -> AIMPRoom:
    """Create a minimal AIMPRoom for testing."""
    if participants is None:
        participants = ["alice@example.com", "bob@example.com"]
    return AIMPRoom(
        room_id=room_id,
        topic=topic,
        deadline=time.time() + deadline_offset,
        participants=participants,
        initiator="alice@example.com",
        status=status,
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
        self.hub.transport.send_human_email.assert_called()

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


# ── Phase 2: initiate_room ────────────────────────────────────────────────────

class TestInitiateRoom(unittest.TestCase):
    def setUp(self):
        self.hub = make_hub(
            members={
                "alice": {"name": "Alice", "email": "alice@example.com"},
                "bob": {"name": "Bob", "email": "bob@example.com"},
            },
            _email_to_member={
                "alice@example.com": "alice",
                "bob@example.com": "bob",
            },
        )

    def test_initiate_room_creates_and_saves_room(self):
        """initiate_room should persist an AIMPRoom and send CFP emails."""
        deadline = time.time() + 86400
        room_id = self.hub.initiate_room(
            topic="Q3 Budget",
            participants=["alice@example.com", "bob@example.com"],
            deadline=deadline,
            initial_proposal="Total: $100k",
            initiator="alice@example.com",
        )

        self.assertTrue(room_id.startswith("room-"))
        self.hub.store.save_room.assert_called_once()
        saved_room = self.hub.store.save_room.call_args[0][0]
        self.assertEqual(saved_room.topic, "Q3 Budget")
        self.assertIn("alice@example.com", saved_room.participants)
        self.assertEqual(saved_room.status, "open")
        self.assertEqual(saved_room.resolution_rules, "majority")

    def test_initiate_room_sends_cfp_email(self):
        """initiate_room should call send_cfp_email with correct params."""
        deadline = time.time() + 86400
        self.hub.initiate_room(
            topic="Budget",
            participants=["alice@example.com", "bob@example.com"],
            deadline=deadline,
            initial_proposal="Draft",
            initiator="alice@example.com",
        )
        self.hub.transport.send_cfp_email.assert_called_once()
        call_kwargs = self.hub.transport.send_cfp_email.call_args
        self.assertIn("alice@example.com", call_kwargs[1]["to"] if call_kwargs[1] else call_kwargs[0][0])

    def test_initiate_room_with_initial_proposal_adds_artifact(self):
        """A non-empty initial_proposal should be stored as an artifact."""
        deadline = time.time() + 86400
        self.hub.initiate_room(
            topic="Proposal",
            participants=["alice@example.com"],
            deadline=deadline,
            initial_proposal="My initial proposal",
            initiator="alice@example.com",
        )
        saved_room: AIMPRoom = self.hub.store.save_room.call_args[0][0]
        self.assertTrue(len(saved_room.artifacts) > 0)
        self.assertEqual(len(saved_room.transcript), 1)
        self.assertEqual(saved_room.transcript[0].action, "PROPOSE")

    def test_initiate_room_no_proposal_no_artifact(self):
        """Empty initial_proposal should not add any artifacts."""
        self.hub.initiate_room(
            topic="Bare Room",
            participants=["alice@example.com"],
            deadline=time.time() + 3600,
            initial_proposal="",
            initiator="alice@example.com",
        )
        saved_room: AIMPRoom = self.hub.store.save_room.call_args[0][0]
        self.assertEqual(len(saved_room.artifacts), 0)
        self.assertEqual(len(saved_room.transcript), 0)

    def test_initiate_room_stdout_mode(self):
        """In stdout mode, no CFP email is sent; an event is emitted."""
        hub = make_hub(notify_mode="stdout")
        with patch("hub_agent.emit_event") as mock_emit:
            room_id = hub.initiate_room(
                topic="T",
                participants=["a@b.com"],
                deadline=time.time() + 3600,
                initial_proposal="",
                initiator="a@b.com",
            )
        hub.transport.send_cfp_email.assert_not_called()
        mock_emit.assert_called_once()
        self.assertEqual(mock_emit.call_args[0][0], "room_created")


# ── Phase 2: _handle_room_email ───────────────────────────────────────────────

class TestHandleRoomEmail(unittest.TestCase):
    def setUp(self):
        self.hub = make_hub(
            members={
                "alice": {"name": "Alice", "email": "alice@example.com"},
                "bob": {"name": "Bob", "email": "bob@example.com"},
            },
            _email_to_member={
                "alice@example.com": "alice",
                "bob@example.com": "bob",
            },
        )
        self.room = make_room(
            participants=["alice@example.com", "bob@example.com"]
        )
        self.hub.store.load_room.return_value = self.room

    def test_amend_action_adds_to_transcript(self):
        """AMEND reply should append to transcript and save room."""
        self.hub.room_negotiator.parse_amendment.return_value = {
            "action": "AMEND",
            "changes": "Increase budget to $120k",
            "reason": "Market rates increased",
            "new_content": "Total: $120k",
        }
        parsed = make_parsed(
            sender="bob@example.com",
            subject="[AIMP:Room:room-001] Q3 Budget",
            body="I think we need more budget",
            room_id="room-001",
        )
        events = self.hub._handle_room_email(parsed)

        self.hub.store.save_room.assert_called()
        saved_room: AIMPRoom = self.hub.store.save_room.call_args[0][0]
        self.assertEqual(len(saved_room.transcript), 1)
        self.assertEqual(saved_room.transcript[0].action, "AMEND")
        self.assertEqual(events[0]["type"], "room_amendment_received")
        self.assertEqual(events[0]["action"], "AMEND")

    def test_accept_updates_accepted_by(self):
        """ACCEPT reply should add sender to accepted_by."""
        self.hub.room_negotiator.parse_amendment.return_value = {
            "action": "ACCEPT",
            "changes": "",
            "reason": "Looks good",
            "new_content": None,
        }
        parsed = make_parsed(
            sender="bob@example.com",
            room_id="room-001",
            body="ACCEPT",
        )
        self.hub._handle_room_email(parsed)

        saved_room: AIMPRoom = self.hub.store.save_room.call_args[0][0]
        self.assertIn("bob@example.com", saved_room.accepted_by)

    def test_all_accepted_triggers_finalize(self):
        """When all participants accept, _finalize_room should be called."""
        self.hub.room_negotiator.parse_amendment.return_value = {
            "action": "ACCEPT",
            "changes": "",
            "reason": "",
            "new_content": None,
        }
        # Pre-fill alice as already accepted
        self.room.accepted_by = ["alice@example.com"]

        parsed = make_parsed(
            sender="bob@example.com",
            room_id="room-001",
            body="ACCEPT",
        )
        with patch.object(self.hub, "_finalize_room") as mock_finalize:
            events = self.hub._handle_room_email(parsed)

        mock_finalize.assert_called_once()
        self.assertEqual(events[0]["type"], "room_finalized")
        self.assertEqual(events[0]["trigger"], "all_accepted")

    def test_unknown_room_returns_empty(self):
        """If room_id is not found in store, return empty list."""
        self.hub.store.load_room.return_value = None
        parsed = make_parsed(room_id="nonexistent")
        events = self.hub._handle_room_email(parsed)
        self.assertEqual(events, [])

    def test_non_participant_ignored(self):
        """Replies from non-participants are ignored."""
        self.hub.room_negotiator.parse_amendment.return_value = {
            "action": "AMEND", "changes": "", "reason": "", "new_content": None
        }
        parsed = make_parsed(
            sender="stranger@out.com",
            room_id="room-001",
            body="I want to change things",
        )
        events = self.hub._handle_room_email(parsed)
        self.assertEqual(events, [])
        self.hub.store.save_room.assert_not_called()

    def test_finalized_room_ignores_late_reply(self):
        """After finalization, late replies are ignored."""
        self.room.status = "finalized"
        parsed = make_parsed(sender="bob@example.com", room_id="room-001", body="AMEND")
        events = self.hub._handle_room_email(parsed)
        self.assertEqual(events, [])


# ── Phase 2: _finalize_room ───────────────────────────────────────────────────

class TestFinalizeRoom(unittest.TestCase):
    def setUp(self):
        self.hub = make_hub()
        self.room = make_room(participants=["alice@example.com", "bob@example.com"])
        self.hub.room_negotiator.generate_meeting_minutes.return_value = "# Minutes\n\nResolution: approved"

    def test_finalize_sets_status(self):
        """_finalize_room should set room.status to 'finalized'."""
        self.hub._finalize_room(self.room)
        self.assertEqual(self.room.status, "finalized")
        self.hub.store.save_room.assert_called()

    def test_finalize_sends_minutes_to_all_participants(self):
        """_finalize_room should email all participants."""
        self.hub._finalize_room(self.room)
        calls = self.hub.transport.send_human_email.call_args_list
        recipients = [c[1]["to"] if c[1] else c[0][0] for c in calls]
        self.assertIn("alice@example.com", recipients)
        self.assertIn("bob@example.com", recipients)

    def test_finalize_stdout_mode_emits_event(self):
        """In stdout mode, _finalize_room emits a room_finalized event."""
        hub = make_hub(notify_mode="stdout")
        hub.room_negotiator = MagicMock()
        hub.room_negotiator.generate_meeting_minutes.return_value = "# Minutes"
        with patch("hub_agent.emit_event") as mock_emit:
            hub._finalize_room(self.room)
        mock_emit.assert_called_once()
        self.assertEqual(mock_emit.call_args[0][0], "room_finalized")

    def test_finalize_adds_finalized_transcript_entry(self):
        """_finalize_room should append a FINALIZED entry to the transcript."""
        self.hub._finalize_room(self.room)
        actions = [e.action for e in self.room.transcript]
        self.assertIn("FINALIZED", actions)


# ── Phase 2: _check_deadlines ────────────────────────────────────────────────

class TestCheckDeadlines(unittest.TestCase):
    def setUp(self):
        self.hub = make_hub()

    def test_past_deadline_room_is_finalized(self):
        """Room with deadline in the past should be finalized."""
        expired_room = make_room(deadline_offset=-1)  # already past
        self.hub.store.load_open_rooms.return_value = [expired_room]

        with patch.object(self.hub, "_finalize_room") as mock_fin:
            self.hub._check_deadlines()

        mock_fin.assert_called_once_with(expired_room)

    def test_future_deadline_room_not_touched(self):
        """Room with future deadline should not be finalized."""
        active_room = make_room(deadline_offset=3600)
        self.hub.store.load_open_rooms.return_value = [active_room]

        with patch.object(self.hub, "_finalize_room") as mock_fin:
            self.hub._check_deadlines()

        mock_fin.assert_not_called()

    def test_check_deadlines_handles_empty_list(self):
        """No open rooms → no error, no finalization."""
        self.hub.store.load_open_rooms.return_value = []
        self.hub._check_deadlines()  # must not raise


# ── Phase 2: RoomNegotiator.generate_meeting_minutes ─────────────────────────

class TestRoomNegotiatorGenerateMinutes(unittest.TestCase):
    def setUp(self):
        llm_config = {"provider": "anthropic", "model": "claude-test"}
        with patch("hub_agent.make_llm_client", return_value=(MagicMock(), "claude-test", "anthropic")):
            self.rn = RoomNegotiator("TestHub", "hub@test.com", llm_config)

    def test_generate_minutes_returns_llm_output(self):
        room = make_room()
        room.add_to_transcript("alice@example.com", "PROPOSE", "Proposal A")
        room.add_to_transcript("bob@example.com", "ACCEPT", "Looks good")

        with patch("hub_agent.call_llm", side_effect=["# Minutes content", "# Minutes content"]):
            minutes = self.rn.generate_meeting_minutes(room)

        self.assertIsInstance(minutes, str)
        self.assertTrue(len(minutes) > 0)

    def test_generate_minutes_fallback_on_llm_error(self):
        """If LLM fails, a fallback Markdown document is generated."""
        room = make_room()
        room.add_to_transcript("a@b.com", "ACCEPT", "ok")

        with patch("hub_agent.call_llm", side_effect=Exception("LLM timeout")):
            minutes = self.rn.generate_meeting_minutes(room)

        self.assertIn("Q3 Budget", minutes)
        self.assertIn("room-001", minutes)


# ── Phase 2: _handle_room_confirm / _handle_room_reject ──────────────────────

class TestRoomVetoFlow(unittest.TestCase):
    def setUp(self):
        self.hub = make_hub()
        self.room = make_room(status="finalized")
        self.hub.store.load_room.return_value = self.room

    def test_confirm_adds_to_accepted_by(self):
        """CONFIRM veto reply adds sender to accepted_by."""
        events = self.hub._handle_room_confirm(self.room, "bob@example.com")
        self.assertIn("bob@example.com", self.room.accepted_by)
        self.assertEqual(events[0]["type"], "room_confirmed")

    def test_reject_escalates_to_initiator(self):
        """REJECT veto reply sends escalation email to initiator."""
        events = self.hub._handle_room_reject(self.room, "bob@example.com", "Wrong numbers")
        self.assertEqual(events[0]["type"], "room_rejected")
        self.assertEqual(events[0]["reason"], "Wrong numbers")
        # Escalation email to initiator
        calls = self.hub.transport.send_human_email.call_args_list
        recipients = [c[1]["to"] if c[1] else c[0][0] for c in calls]
        self.assertIn(self.room.initiator, recipients)

    def test_handle_human_email_routes_confirm(self):
        """_handle_human_email routes CONFIRM body for Room email to _handle_room_confirm."""
        parsed = make_parsed(
            sender="bob@example.com",
            body="CONFIRM",
            room_id="room-001",
        )
        with patch.object(self.hub, "_handle_room_confirm", return_value=[{"type": "room_confirmed"}]) as mock_confirm:
            result = self.hub._handle_human_email(parsed)
        mock_confirm.assert_called_once()
        self.assertEqual(result[0]["type"], "room_confirmed")

    def test_handle_human_email_routes_reject(self):
        """_handle_human_email routes REJECT body for Room email to _handle_room_reject."""
        parsed = make_parsed(
            sender="bob@example.com",
            body="REJECT numbers are wrong",
            room_id="room-001",
        )
        with patch.object(self.hub, "_handle_room_reject", return_value=[{"type": "room_rejected"}]) as mock_reject:
            result = self.hub._handle_human_email(parsed)
        mock_reject.assert_called_once()
        # Verify reason is extracted from body
        _, kwargs = mock_reject.call_args
        self.assertIn("numbers are wrong", mock_reject.call_args[0][2])


# ── Phase 2: _parse_deadline helper ──────────────────────────────────────────

class TestParseDeadline(unittest.TestCase):
    def setUp(self):
        self.hub = make_hub()

    def test_iso_datetime(self):
        ts = self.hub._parse_deadline("2030-01-01T00:00:00Z")
        self.assertGreater(ts, time.time())

    def test_relative_days(self):
        ts = self.hub._parse_deadline("3 days")
        self.assertAlmostEqual(ts, time.time() + 3 * 86400, delta=5)

    def test_relative_weeks(self):
        ts = self.hub._parse_deadline("2 weeks")
        self.assertAlmostEqual(ts, time.time() + 14 * 86400, delta=5)

    def test_relative_hours(self):
        ts = self.hub._parse_deadline("48 hours")
        self.assertAlmostEqual(ts, time.time() + 48 * 3600, delta=5)

    def test_unparseable_defaults_to_7_days(self):
        ts = self.hub._parse_deadline("sometime next year maybe")
        self.assertAlmostEqual(ts, time.time() + 7 * 86400, delta=5)


# ── Phase 2: _handle_create_room_command ─────────────────────────────────────

class TestHandleCreateRoomCommand(unittest.TestCase):
    def setUp(self):
        self.hub = make_hub(
            members={"alice": {"name": "Alice", "email": "alice@example.com"},
                     "bob": {"name": "Bob", "email": "bob@example.com"}},
            _email_to_member={"alice@example.com": "alice", "bob@example.com": "bob"},
            _raw_config={"contacts": {}},
        )

    def test_missing_deadline_returns_info_requested(self):
        """Missing deadline → info request sent back."""
        parsed_req = {
            "action": "create_room",
            "topic": "Q3 Budget",
            "participants": ["Bob"],
            "deadline": "",
        }
        events = self.hub._handle_create_room_command(
            "alice@example.com", "alice", "Alice", parsed_req
        )
        self.assertEqual(events[0]["type"], "member_info_requested")
        self.assertIn("deadline", events[0]["missing"])

    def test_unknown_participant_returns_info_requested(self):
        """Unknown participant name → contact resolution failure."""
        parsed_req = {
            "action": "create_room",
            "topic": "Topic",
            "participants": ["UnknownPerson"],
            "deadline": "3 days",
        }
        events = self.hub._handle_create_room_command(
            "alice@example.com", "alice", "Alice", parsed_req
        )
        self.assertEqual(events[0]["type"], "member_info_requested")

    def test_valid_request_dispatches_initiate_room(self):
        """Valid create_room request triggers initiate_room."""
        parsed_req = {
            "action": "create_room",
            "topic": "Q3 Budget",
            "participants": ["Bob"],
            "deadline": "7 days",
            "initial_proposal": "Total: $100k",
            "resolution_rules": "majority",
        }
        with patch.object(self.hub, "initiate_room", return_value="room-123") as mock_init:
            events = self.hub._handle_create_room_command(
                "alice@example.com", "alice", "Alice", parsed_req
            )
        mock_init.assert_called_once()
        self.assertEqual(events[0]["type"], "room_created")
        self.assertEqual(events[0]["room_id"], "room-123")


# ── Phase 4: TestRoundGating ──────────────────────────────────────────────────

class TestRoundGating(unittest.TestCase):
    """Tests for store-first + round-gated poll() logic."""

    def _make_session(self, participants=None, initiator="hub@test.com"):
        if participants is None:
            participants = ["hub@test.com", "alice@example.com", "bob@example.com"]
        s = AIMPSession(
            session_id="sess-rg",
            topic="Round Gating Test",
            participants=participants,
            initiator=initiator,
        )
        return s

    def setUp(self):
        self.hub = make_hub()
        self.hub.agent_email = "hub@test.com"

    # ── test_session_email_stored_before_processing ──────────────────────────

    def test_session_email_stored_before_processing(self):
        """save_pending_email must be called before is_round_complete is checked."""
        session = self._make_session()
        # Only alice replies — round not complete (bob hasn't replied)
        self.hub.store.load.return_value = session
        self.hub.store.save = MagicMock()

        parsed = make_parsed(
            sender="alice@example.com",
            subject="[AIMP:sess-rg] vote",
            session_id="sess-rg",
        )
        # Provide a real AIMP email (no protocol.json attachment → not is_aimp_email)
        self.hub.transport.fetch_aimp_emails.return_value = [parsed]
        self.hub.transport.fetch_phase2_emails.return_value = []
        self.hub.transport.fetch_all_unread_emails.return_value = []

        self.hub.poll()

        # save_pending_email must have been called
        self.hub.store.save_pending_email.assert_called()
        # _process_session_round NOT triggered (round incomplete)
        self.hub.store.load_pending_for_session.assert_not_called()

    # ── test_session_round_not_complete_no_reply ─────────────────────────────

    def test_session_round_not_complete_no_reply(self):
        """When only one of two non-initiators replies, no round processing occurs."""
        session = self._make_session(
            participants=["hub@test.com", "alice@example.com", "bob@example.com"]
        )
        self.hub.store.load.return_value = session
        self.hub.store.save = MagicMock()

        parsed = make_parsed(
            sender="alice@example.com",
            session_id="sess-rg",
        )
        self.hub.transport.fetch_aimp_emails.return_value = [parsed]
        self.hub.transport.fetch_phase2_emails.return_value = []
        self.hub.transport.fetch_all_unread_emails.return_value = []

        self.hub.poll()

        self.hub.store.load_pending_for_session.assert_not_called()

    # ── test_session_round_complete_triggers_process ─────────────────────────

    def test_session_round_complete_triggers_process(self):
        """When all non-initiators reply, _process_session_round is triggered."""
        session = self._make_session(
            participants=["hub@test.com", "alice@example.com"],
            initiator="hub@test.com",
        )
        # Pre-fill alice as already recorded (round 1 needs only non-initiators)
        self.hub.store.load.return_value = session
        self.hub.store.save = MagicMock()
        self.hub.store.load_pending_for_session.return_value = [
            {"id": 1, "from_addr": "alice@example.com",
             "subject": "vote", "body": "accept", "protocol_json": None}
        ]

        parsed = make_parsed(sender="alice@example.com", session_id="sess-rg")
        self.hub.transport.fetch_aimp_emails.return_value = [parsed]
        self.hub.transport.fetch_phase2_emails.return_value = []
        self.hub.transport.fetch_all_unread_emails.return_value = []

        with patch.object(self.hub, "_process_session_round", return_value=[]) as mock_proc:
            self.hub.poll()

        mock_proc.assert_called_once()
        self.hub.store.mark_processed.assert_called_once_with(1)

    # ── test_room_round_not_complete_waits ───────────────────────────────────

    def test_room_round_not_complete_waits(self):
        """When only one room participant replies, no round processing occurs."""
        room = make_room(participants=["alice@example.com", "bob@example.com"])
        self.hub.store.load_room.return_value = room
        self.hub.store.save_room = MagicMock()

        parsed = make_parsed(
            sender="alice@example.com",
            subject="[AIMP:Room:room-001]",
            room_id="room-001",
        )
        self.hub.transport.fetch_phase2_emails.return_value = [parsed]
        self.hub.transport.fetch_aimp_emails.return_value = []
        self.hub.transport.fetch_all_unread_emails.return_value = []

        self.hub.poll()

        self.hub.store.load_pending_for_room.assert_not_called()

    # ── test_room_round_complete_triggers_process ────────────────────────────

    def test_room_round_complete_triggers_process(self):
        """When all room non-initiators reply, _process_room_round is triggered."""
        # initiator = alice, only bob needs to reply (round 1 = odd)
        room = make_room(
            participants=["alice@example.com", "bob@example.com"],
        )
        room.initiator = "alice@example.com"
        self.hub.store.load_room.return_value = room
        self.hub.store.save_room = MagicMock()
        self.hub.store.load_pending_for_room.return_value = [
            {"id": 2, "from_addr": "bob@example.com",
             "subject": "amend", "body": "AMEND something", "protocol_json": None}
        ]

        parsed = make_parsed(
            sender="bob@example.com",
            subject="[AIMP:Room:room-001]",
            room_id="room-001",
        )
        self.hub.transport.fetch_phase2_emails.return_value = [parsed]
        self.hub.transport.fetch_aimp_emails.return_value = []
        self.hub.transport.fetch_all_unread_emails.return_value = []

        with patch.object(self.hub, "_process_room_round", return_value=[]) as mock_proc:
            self.hub.poll()

        mock_proc.assert_called_once()
        self.hub.store.mark_processed.assert_called_once_with(2)

    # ── test_pending_email_marked_after_processing ───────────────────────────

    def test_pending_email_marked_after_processing(self):
        """After successful round processing, all pending emails are marked processed."""
        session = self._make_session(
            participants=["hub@test.com", "alice@example.com"],
            initiator="hub@test.com",
        )
        pending = [
            {"id": 10, "from_addr": "alice@example.com",
             "subject": "vote", "body": "ok", "protocol_json": None},
        ]
        self.hub.store.load.return_value = session
        self.hub.store.save = MagicMock()
        self.hub.store.load_pending_for_session.return_value = pending

        parsed = make_parsed(sender="alice@example.com", session_id="sess-rg")
        self.hub.transport.fetch_aimp_emails.return_value = [parsed]
        self.hub.transport.fetch_phase2_emails.return_value = []
        self.hub.transport.fetch_all_unread_emails.return_value = []

        with patch.object(self.hub, "_process_session_round", return_value=[]):
            self.hub.poll()

        self.hub.store.mark_processed.assert_called_once_with(10)


if __name__ == "__main__":
    unittest.main()

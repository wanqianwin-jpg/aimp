"""
transport.py — BaseTransport ABC + EmailTransport

Defines the transport interface that agents program against.
EmailTransport wraps EmailClient; future implementations can wrap
Telegram, Slack, etc. without changing any agent logic.
"""
from __future__ import annotations
from abc import ABC, abstractmethod

from lib.email_client import EmailClient, ParsedEmail


class BaseTransport(ABC):
    """Abstract transport interface — all agent I/O goes through this."""

    @abstractmethod
    def my_address(self) -> str:
        """Return this transport's own address (e.g. email address)."""
        ...

    # ── Fetch ─────────────────────────────────────────────────────────────────

    @abstractmethod
    def fetch_aimp_emails(self, since_minutes: int = 60) -> list[ParsedEmail]:
        """Phase 1: fetch unread AIMP emails (subject contains [AIMP:)."""
        ...

    @abstractmethod
    def fetch_all_unread_emails(self, since_minutes: int = 60) -> list[ParsedEmail]:
        """Hub: fetch ALL unread emails (no subject filter)."""
        ...

    @abstractmethod
    def fetch_phase2_emails(self, since_minutes: int = 60) -> list[ParsedEmail]:
        """Phase 2: fetch unread Room emails (subject contains [AIMP:Room:)."""
        ...

    # ── Send ──────────────────────────────────────────────────────────────────

    @abstractmethod
    def send_aimp_email(
        self,
        to: list[str],
        session_id: str,
        version: int,
        subject_suffix: str,
        body_text: str,
        protocol_json: dict,
        references: list[str] = None,
        in_reply_to: str = None,
    ) -> str:
        """Phase 1: send AIMP protocol email; return Message-ID."""
        ...

    @abstractmethod
    def send_cfp_email(
        self,
        to: list[str],
        room_id: str,
        topic: str,
        deadline_iso: str,
        initial_proposal: str,
        resolution_rules: str,
        body_text: str,
        references: list[str] = None,
    ) -> str:
        """Phase 2: send Call-for-Proposals email; return Message-ID."""
        ...

    @abstractmethod
    def send_human_email(self, to: str, subject: str, body: str):
        """Send plain-text email to a human (fallback or owner notification)."""
        ...


class EmailTransport(BaseTransport):
    """Concrete transport that delegates to EmailClient."""

    def __init__(
        self,
        email_addr: str,
        imap_server: str,
        smtp_server: str,
        password: str = None,
        imap_port: int = 993,
        smtp_port: int = 465,
        auth_type: str = "basic",
        oauth_params: dict = None,
        smtp_use_starttls: bool = False,
    ):
        self._client = EmailClient(
            imap_server=imap_server,
            smtp_server=smtp_server,
            email_addr=email_addr,
            password=password,
            imap_port=imap_port,
            smtp_port=smtp_port,
            auth_type=auth_type,
            oauth_params=oauth_params or {},
            smtp_use_starttls=smtp_use_starttls,
        )
        self._email_addr = email_addr

    def my_address(self) -> str:
        return self._email_addr

    def fetch_aimp_emails(self, since_minutes: int = 60) -> list[ParsedEmail]:
        return self._client.fetch_aimp_emails(since_minutes)

    def fetch_all_unread_emails(self, since_minutes: int = 60) -> list[ParsedEmail]:
        return self._client.fetch_all_unread_emails(since_minutes)

    def fetch_phase2_emails(self, since_minutes: int = 60) -> list[ParsedEmail]:
        return self._client.fetch_phase2_emails(since_minutes)

    def send_aimp_email(
        self,
        to: list[str],
        session_id: str,
        version: int,
        subject_suffix: str,
        body_text: str,
        protocol_json: dict,
        references: list[str] = None,
        in_reply_to: str = None,
    ) -> str:
        return self._client.send_aimp_email(
            to=to,
            session_id=session_id,
            version=version,
            subject_suffix=subject_suffix,
            body_text=body_text,
            protocol_json=protocol_json,
            references=references,
            in_reply_to=in_reply_to,
        )

    def send_cfp_email(
        self,
        to: list[str],
        room_id: str,
        topic: str,
        deadline_iso: str,
        initial_proposal: str,
        resolution_rules: str,
        body_text: str,
        references: list[str] = None,
    ) -> str:
        return self._client.send_cfp_email(
            to=to,
            room_id=room_id,
            topic=topic,
            deadline_iso=deadline_iso,
            initial_proposal=initial_proposal,
            resolution_rules=resolution_rules,
            body_text=body_text,
            references=references,
        )

    def send_human_email(self, to: str, subject: str, body: str):
        return self._client.send_human_email(to=to, subject=subject, body=body)

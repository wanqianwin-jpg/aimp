"""
email_client.py — IMAP/SMTP client wrapper / IMAP/SMTP 收发封装
"""
import imaplib
import smtplib
import email
import json
import time
import logging
import base64
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.header import decode_header
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


@dataclass
class ParsedEmail:
    message_id: str
    subject: str
    sender: str
    recipients: list[str]
    body: str
    attachments: list[dict]  # [{"filename": ..., "content": ...}]
    references: list[str]
    session_id: Optional[str] = None
    raw_date: Optional[str] = None


def _decode_str(s) -> str:
    if s is None:
        return ""
    parts = decode_header(s)
    result = []
    for part, encoding in parts:
        if isinstance(part, bytes):
            result.append(part.decode(encoding or "utf-8", errors="replace"))
        else:
            result.append(part)
    return "".join(result)


def _extract_session_id(subject: str) -> Optional[str]:
    """Extract session_id from Subject / 从 Subject 中提取 session_id"""
    import re
    m = re.search(r"\[AIMP:([^\]]+)\]", subject)
    return m.group(1) if m else None


class EmailClient:
    def __init__(self, imap_server: str, smtp_server: str, email_addr: str, password: str = None,
                 imap_port: int = 993, smtp_port: int = 465, timeout: int = 15,
                 auth_type: str = "basic", oauth_params: dict = None,
                 smtp_use_starttls: bool = False):
        self.imap_server = imap_server
        self.smtp_server = smtp_server
        self.email_addr = email_addr
        self.password = password
        self.imap_port = imap_port
        self.smtp_port = smtp_port
        self.timeout = timeout
        self.auth_type = auth_type
        self.oauth_params = oauth_params or {}
        # True → SMTP+STARTTLS (port 587, required by Outlook/Office365)
        # False → SMTP_SSL (port 465, used by Gmail/QQ/163)
        self.smtp_use_starttls = smtp_use_starttls

        # OAuth2 token management / OAuth2 令牌管理
        self.access_token = self.oauth_params.get("access_token")
        self.token_expiry = self.oauth_params.get("expires_at", 0)
        # Default token_uri is Google; Outlook users must override via oauth_params
        self.token_uri = self.oauth_params.get(
            "token_uri", "https://oauth2.googleapis.com/token"
        )

    def _generate_xoauth2_bytes(self, token: str) -> bytes:
        """Return base64-encoded XOAUTH2 string as bytes (RFC-compliant).
        Format: base64("user=<email>\\x01auth=Bearer <token>\\x01\\x01")
        Both imaplib.authenticate() and smtplib.auth() expect a bytes-returning callable.
        """
        raw = f"user={self.email_addr}\x01auth=Bearer {token}\x01\x01"
        return base64.b64encode(raw.encode("ascii"))

    def _refresh_access_token(self):
        """Refresh OAuth2 Access Token / 刷新 OAuth2 Access Token"""
        if not self.oauth_params.get("refresh_token"):
            raise ValueError("No refresh token provided for OAuth2")
        
        logger.info("Refreshing OAuth2 access token...")
        data = {
            "client_id": self.oauth_params.get("client_id"),
            "client_secret": self.oauth_params.get("client_secret"),
            "refresh_token": self.oauth_params.get("refresh_token"),
            "grant_type": "refresh_token",
        }
        
        try:
            resp = requests.post(self.token_uri, data=data, timeout=10)
            resp.raise_for_status()
            tokens = resp.json()
            self.access_token = tokens["access_token"]
            self.token_expiry = time.time() + tokens.get("expires_in", 3600)
            logger.info("OAuth2 access token refreshed successfully")
        except Exception as e:
            logger.error(f"Failed to refresh OAuth2 token: {e}")
            raise

    def _ensure_valid_token(self):
        """Ensure Access Token is valid, refresh if expired / 确保 Access Token 有效，过期则刷新"""
        if self.auth_type != "oauth2":
            return
        
        # Simple check: if no token or token expires in less than 60 seconds
        # 简单判断：如果没有token或token即将在60秒内过期
        if not self.access_token or time.time() >= self.token_expiry - 60:
            self._refresh_access_token()

    # ──────────────────────────────────────────────
    # IMAP
    # ──────────────────────────────────────────────

    def _imap_connect(self) -> imaplib.IMAP4_SSL:
        try:
            conn = imaplib.IMAP4_SSL(self.imap_server, self.imap_port, timeout=self.timeout)
            if self.auth_type == "oauth2":
                self._ensure_valid_token()
                conn.authenticate("XOAUTH2", lambda x: self._generate_xoauth2_bytes(self.access_token))
            else:
                conn.login(self.email_addr, self.password)
            return conn
        except imaplib.IMAP4.error as e:
            logger.error(f"IMAP Login failed: {e}")
            raise
        except TimeoutError:
            logger.error(f"IMAP Connection timed out to {self.imap_server}")
            raise
        except Exception as e:
            logger.error(f"IMAP Connection error: {e}")
            raise

    def fetch_aimp_emails(self, since_minutes: int = 60) -> list[ParsedEmail]:
        """
        Search for unread AIMP emails and return parsed list /
        搜索含 [AIMP: 的未读邮件，返回解析后的列表
        """
        results = []
        try:
            conn = self._imap_connect()
            conn.select("INBOX")

            # Calculate search date (IMAP DATE is day-precision, use since_minutes for internal filtering)
            # 计算搜索日期（IMAP DATE 格式只精确到天，用 since_minutes 做内存过滤）
            since_dt = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
            date_str = since_dt.strftime("%d-%b-%Y")

            # Filter by UNSEEN and subject prefix / 同时过滤 UNSEEN 和包含 [AIMP: 的 subject
            status, uids = conn.search(None, f'(UNSEEN SUBJECT "[AIMP:" SINCE {date_str})')
            if status != "OK":
                return results

            uid_list = uids[0].split()
            for uid in uid_list:
                try:
                    status, data = conn.fetch(uid, "(RFC822)")
                    if status != "OK":
                        continue
                    raw = data[0][1]
                    msg = email.message_from_bytes(raw)
                    parsed = self._parse_email(msg)

                    # Precise filtering by since_minutes / 按 since_minutes 精确过滤
                    if parsed:
                        results.append(parsed)
                        # Mark as seen / 标记为已读
                        conn.store(uid, "+FLAGS", "\\Seen")
                except Exception as e:
                    logger.warning(f"Failed to parse email uid={uid}: {e} / 解析邮件 uid={uid} 失败: {e}")

            conn.logout()
        except Exception as e:
            logger.error(f"IMAP connection failed: {e} / IMAP 连接失败: {e}")
        return results

    def _parse_email(self, msg) -> Optional[ParsedEmail]:
        subject = _decode_str(msg.get("Subject", ""))
        sender = _decode_str(msg.get("From", ""))
        # Extract pure email address / 提取纯邮件地址
        import re
        sender_match = re.search(r"[\w.+\-]+@[\w.\-]+", sender)
        sender_addr = sender_match.group(0) if sender_match else sender

        message_id = msg.get("Message-ID", "").strip()
        references_raw = msg.get("References", "") or ""
        references = [r.strip() for r in references_raw.split() if r.strip()]

        body = ""
        attachments = []

        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                cd = part.get("Content-Disposition", "")
                if ct == "text/plain" and "attachment" not in cd:
                    payload = part.get_payload(decode=True)
                    if payload:
                        body = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                elif part.get_filename():
                    fname = _decode_str(part.get_filename())
                    payload = part.get_payload(decode=True)
                    attachments.append({"filename": fname, "content": payload})
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")

        # Parse recipients / 解析 recipients
        to_raw = _decode_str(msg.get("To", ""))
        import re
        recipients = re.findall(r"[\w.+\-]+@[\w.\-]+", to_raw)

        session_id = _extract_session_id(subject)

        return ParsedEmail(
            message_id=message_id,
            subject=subject,
            sender=sender_addr,
            recipients=recipients,
            body=body,
            attachments=attachments,
            references=references,
            session_id=session_id,
            raw_date=msg.get("Date", ""),
        )

    # ──────────────────────────────────────────────
    # SMTP
    # ──────────────────────────────────────────────

    def _smtp_connect(self):
        try:
            if self.smtp_use_starttls:
                # STARTTLS mode (port 587): required by Outlook/Office365
                conn = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=self.timeout)
                conn.ehlo()
                conn.starttls()
                conn.ehlo()
            else:
                # SSL mode (port 465): Gmail, QQ, 163, etc.
                conn = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, timeout=self.timeout)

            if self.auth_type == "oauth2":
                self._ensure_valid_token()
                # smtplib.auth() calls the initializer and passes the encoded challenge;
                # our callback must return bytes to be base64-encoded by the library.
                conn.auth("XOAUTH2", lambda challenge=None: self._generate_xoauth2_bytes(self.access_token))
            else:
                conn.login(self.email_addr, self.password)
            return conn
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP Authentication failed: {e}")
            raise
        except TimeoutError:
            logger.error(f"SMTP Connection timed out to {self.smtp_server}")
            raise
        except Exception as e:
            logger.error(f"SMTP Connection error: {e}")
            raise

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
        """Send AIMP protocol email and return Message-ID / 发送 AIMP 协议邮件，返回 Message-ID"""
        subject = f"[AIMP:{session_id}] v{version} {subject_suffix}"
        msg = MIMEMultipart("mixed")
        msg["From"] = self.email_addr
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject

        # Generate unique Message-ID / 生成唯一 Message-ID
        msg_id = f"<aimp-{session_id}-v{version}-{int(time.time())}@{self.email_addr.split('@')[1]}>"
        msg["Message-ID"] = msg_id

        if references:
            msg["References"] = " ".join(references)
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to

        # Body / 正文
        msg.attach(MIMEText(body_text, "plain", "utf-8"))

        # JSON attachment / JSON 附件
        json_bytes = json.dumps(protocol_json, ensure_ascii=False, indent=2).encode("utf-8")
        attachment = MIMEApplication(json_bytes, _subtype="json")
        attachment.add_header("Content-Disposition", "attachment", filename="protocol.json")
        msg.attach(attachment)

        self._smtp_send(to, msg)
        logger.info(f"AIMP email sent: {subject} -> {to} / 已发送 AIMP 邮件: {subject} -> {to}")
        return msg_id

    def send_human_email(self, to: str, subject: str, body: str):
        """Send plain email to humans / 给人类发普通邮件（降级模式或通知）"""
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = self.email_addr
        msg["To"] = to
        msg["Subject"] = subject
        msg_id = f"<human-{int(time.time())}@{self.email_addr.split('@')[1]}>"
        msg["Message-ID"] = msg_id
        self._smtp_send([to], msg)
        logger.info(f"Human email sent: {subject} -> {to} / 已发送人类邮件: {subject} -> {to}")

    def _smtp_send(self, to: list[str], msg):
        conn = None
        try:
            conn = self._smtp_connect()
            conn.sendmail(self.email_addr, to, msg.as_string())
        except Exception as e:
            logger.error(f"SMTP sending failed: {e} / SMTP 发送失败: {e}")
            raise
        finally:
            if conn:
                try:
                    conn.quit()
                except Exception:
                    pass


def is_aimp_email(parsed: ParsedEmail) -> bool:
    """Check if email is an AIMP protocol email / 检查邮件是否为 AIMP 协议邮件"""
    has_prefix = "[AIMP:" in parsed.subject
    has_json = any(a["filename"] == "protocol.json" for a in parsed.attachments)
    return has_prefix and has_json


def extract_protocol_json(parsed: ParsedEmail) -> Optional[dict]:
    """Extract protocol.json from attachments / 从附件中提取 protocol.json"""
    for a in parsed.attachments:
        if a["filename"] == "protocol.json":
            try:
                return json.loads(a["content"].decode("utf-8"))
            except Exception as e:
                logger.warning(f"Failed to parse protocol.json: {e} / 解析 protocol.json 失败: {e}")
    return None

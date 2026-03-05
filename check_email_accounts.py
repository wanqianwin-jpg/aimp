import sys
import os
sys.path.insert(0, '/Users/qianwan/ai-zoom/aimp')
from lib.email_client import EmailClient

accounts = [
    {
        "name": "wan2008 (163)",
        "email": "tcwanqian2008@163.com",
        "pwd": "ESVpKB9u4BNBP48Y",
        "imap": "imap.163.com",
        "smtp": "smtp.163.com"
    },
    {
        "name": "wan1 (QQ)",
        "email": "63883465@qq.com",
        "pwd": "ohbohxsqjdbfcahg",
        "imap": "imap.qq.com",
        "smtp": "smtp.qq.com"
    }
]

for acc in accounts:
    print(f"\n--- Checking INBOX for {acc['name']} ---")
    client = EmailClient(
        imap_server=acc['imap'], smtp_server=acc['smtp'],
        email_addr=acc['email'], password=acc['pwd'],
        imap_port=993, smtp_port=465
    )
    
    try:
        conn = client._imap_connect()
        status, _ = conn.select("INBOX")
        if status != "OK":
            print("  Failed to select INBOX")
            continue
        status, uids = conn.search(None, f'FROM "wanqian200@qq.com"')
        uid_list = uids[0].split()
        if not uid_list:
            print("  No emails from Hub (wanqian200@qq.com)")
        else:
            print(f"  Found {len(uid_list)} total emails. Fetching last 2...")
            for uid in uid_list[-2:]:
                _, data = conn.fetch(uid, "(RFC822)")
                raw = data[0][1]
                import email
                msg = email.message_from_bytes(raw)
                parsed = client._parse_email(msg)
                print(f"  [From: {parsed.sender}] [Subject: {parsed.subject}]")
                print(f"  Body (first 100 chars): {parsed.body[:100].strip().replace(chr(10), ' ')}")
        conn.logout()
    except Exception as e:
        print(f"  IMAP Failed: {e}")

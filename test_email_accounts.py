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

hub_email = "wanqian200@qq.com"

for acc in accounts:
    print(f"\n--- Testing {acc['name']} ---")
    client = EmailClient(
        imap_server=acc['imap'], smtp_server=acc['smtp'],
        email_addr=acc['email'], password=acc['pwd'],
        imap_port=993, smtp_port=465
    )
    
    print("Testing IMAP...")
    try:
        conn = client._imap_connect()
        conn.select("INBOX")
        print("  IMAP OK")
        conn.logout()
    except Exception as e:
        print(f"  IMAP Failed: {e}")
        continue
        
    print("Testing SMTP & Sending to Hub...")
    try:
        client.send_human_email(
            to=hub_email,
            subject=f"Test message from {acc['name']}",
            body=f"Hello Hub, I am {acc['name']}. Please schedule a meeting."
        )
        print("  SMTP Send OK")
    except Exception as e:
        print(f"  SMTP Send Failed: {e}")

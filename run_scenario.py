import sys
import os
import time
import requests
import json
import email
from email.header import decode_header
sys.path.insert(0, '/Users/qianwan/ai-zoom/aimp')
from lib.email_client import EmailClient

HUB_EMAIL = "wanqian200@qq.com"

# ==========================================
# 1. Initiator (wan1 QQ) sends request
# ==========================================
print("1. 发起人 (wan1 QQ) 发起会议邀约...")

client1 = EmailClient(
    imap_server='imap.qq.com', smtp_server='smtp.qq.com',
    email_addr='63883465@qq.com', password='ohbohxsqjdbfcahg',
    imap_port=993, smtp_port=465
)

try:
    client1.send_human_email(
        to=HUB_EMAIL,
        subject="发起产品发布会议",
        body="请帮我约 wan@agentmail.to 和 tcwanqian2008@163.com 下周三开会，讨论产品A的发布方案，在 Zoom 进行。"
    )
    print("  -> 请求已发送给 Hub")
except Exception as e:
    print("  -> 请求发送失败:", e)
    sys.exit(1)

print("等待 Hub 处理并发送邀约 (约 40 秒)...")
time.sleep(40)

# ==========================================
# 2. 另外两个邮箱查收邮件并回复
# ==========================================
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

def decode_str(s):
    if not s: return ""
    parts = decode_header(s)
    res = []
    for p, enc in parts:
        if isinstance(p, bytes):
            res.append(p.decode(enc or 'utf-8', errors='replace'))
        else:
            res.append(p)
    return "".join(res)

for acc in accounts:
    print(f"\n2. 检查 {acc['name']} 的收件箱...")
    client = EmailClient(
        imap_server=acc['imap'], smtp_server=acc['smtp'],
        email_addr=acc['email'], password=acc['pwd'],
        imap_port=993, smtp_port=465
    )
    
    try:
        conn = client._imap_connect()
        status, _ = conn.select("INBOX")
        if status != "OK":
            print("  -> IMAP Failed to select INBOX")
            continue
        status, uids = conn.search(None, f'FROM "{HUB_EMAIL}" UNSEEN')
        uid_list = uids[0].split()
        if not uid_list:
            print("  -> 未找到 Hub 发来的新邀约。")
            conn.logout()
            continue
            
        latest_uid = uid_list[-1]
        _, data = conn.fetch(latest_uid, "(RFC822)")
        raw = data[0][1]
        msg = email.message_from_bytes(raw)
        
        subject = decode_str(msg.get("Subject", ""))
        message_id = msg.get("Message-ID", "").strip()
        print(f"  -> 收到 Hub 邀约: {subject}")
        
        # 标记为已读
        conn.store(latest_uid, "+FLAGS", "\\Seen")
        conn.logout()
        
        print(f"  -> {acc['name']} 正在回复有时间...")
        reply_subject = f"Re: {subject}"
        reply_body = "下周三下周四我都有时间，听你们的安排。"
        
        client.send_human_email(
            to=HUB_EMAIL,
            subject=reply_subject,
            body=reply_body
        )
        print("  -> 回复成功")
        
    except Exception as e:
        print(f"  -> 发生错误: {e}")

print("\n3. 等待 Hub 汇总共识并发送确认邮件 (约 45 秒)...")

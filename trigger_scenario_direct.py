import sys
import os
import time
sys.path.insert(0, '/Users/qianwan/ai-zoom/aimp')
from hub_agent import AIMPHubAgent
import logging

logging.basicConfig(level=logging.INFO)

print("1. 模拟管理员 (wan1) 发出约会请求，绕过 QQ 邮箱的未读状态被吃掉的问题...")
agent = AIMPHubAgent('/Users/qianwan/.aimp/config.yaml')

events = agent.handle_member_command(
    from_email="63883465@qq.com",
    subject="发起产品发布会议",
    body="请帮我约 wan@agentmail.to 和 tcwanqian2008@163.com 下周三开会，讨论产品A的发布方案，在 Zoom 进行。"
)
print("Hub 返回的处理结果:", events)

print("\n等待 15 秒让邮件发出...")
time.sleep(15)

print("\n2. 我们现在去检查 wan1 (QQ) 是不是收到了 Hub 的协商邮件，并回复它！")
from lib.email_client import EmailClient
import email
from email.header import decode_header

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

hub_email = "wanqian200@qq.com"

client1 = EmailClient(
    imap_server='imap.qq.com', smtp_server='smtp.qq.com',
    email_addr='63883465@qq.com', password='ohbohxsqjdbfcahg',
    imap_port=993, smtp_port=465
)
try:
    conn = client1._imap_connect()
    conn.select('INBOX')
    status, uids = conn.search(None, f'FROM "{hub_email}"')
    if uids[0]:
        latest_uid = uids[0].split()[-1]
        _, data = conn.fetch(latest_uid, "(RFC822)")
        msg = email.message_from_bytes(data[0][1])
        subj = decode_str(msg.get("Subject"))
        print(f"  -> wan1 收到了来自 Hub 的邮件: {subj}")
        
        # 提取 session_id 回复
        reply_subj = f"Re: {subj}"
        print(f"  -> wan1 回复: 下周三周四都有时间")
        client1.send_human_email(hub_email, reply_subj, "下周三周四都有时间")
    else:
        print("  -> wan1 没收到邮件！")
    conn.logout()
except Exception as e:
    print(e)

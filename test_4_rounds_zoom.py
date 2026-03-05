import time
import sqlite3
import json
import sys
import os
import requests

sys.path.insert(0, '/Users/qianwan/ai-zoom/aimp')
from lib.email_client import EmailClient

HUB_EMAIL = 'wanqian200@qq.com'
AGENTMAIL_API_KEY = "am_us_c8e54d6d98e2c590c0c182abb98ded6d01da1bf5959cf5be278b288768ff5cbc"

print("清理先前的数据库...")
os.system("pkill -f 'hub_agent.py'")
os.system("pkill -f 'test_4_rounds_zoom.py'")
time.sleep(2)
os.system("rm -f /Users/qianwan/.aimp/sessions.db* /Users/qianwan/.aimp/hub.log")
os.system('export HUB_PASSWORD="jggsdndyqrsocibe" && export DASHSCOPE_API_KEY="sk-53f52ec4226f4317ac87ac3cf1b96c43" && nohup python3 -u -c "import socket; socket.setdefaulttimeout(30); import runpy; runpy.run_path(\'/Users/qianwan/ai-zoom/aimp/hub_agent.py\', run_name=\'__main__\')" /Users/qianwan/.aimp/config.yaml 10 > /Users/qianwan/.aimp/hub.log 2>&1 & echo $! > /Users/qianwan/.aimp/hub.pid')
print("重启了 Hub，轮询间隔设置为 10 秒。等待 5 秒加速测试...")
time.sleep(5)

print("清理服务器上的星标...")
def unflag_recent():
    import imaplib, ssl
    ctx = ssl.create_default_context()
    conn = imaplib.IMAP4_SSL('imap.qq.com', 993, ssl_context=ctx)
    conn.login('wanqian200@qq.com', 'jggsdndyqrsocibe')
    conn.select('INBOX')
    s, u = conn.uid('SEARCH', None, 'FLAGGED')
    if s == 'OK' and u[0]:
        for uid in u[0].split():
            conn.uid('STORE', uid, '-FLAGS', '\\Flagged')
    conn.logout()

try:
    unflag_recent()
except Exception as e:
    pass

def send_from_Admin_Initiator(subject, text):
    url = "https://api.agentmail.to/v0/inboxes/wan@agentmail.to/messages/send"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {AGENTMAIL_API_KEY}"}
    data = {"to": HUB_EMAIL, "subject": subject, "text": text}
    requests.post(url, headers=headers, json=data)

def send_from_GuestA_wan1(subject, text):
    client = EmailClient(
        imap_server='imap.qq.com', smtp_server='smtp.qq.com',
        email_addr='63883465@qq.com', password='ohbohxsqjdbfcahg',
        imap_port=993, smtp_port=465
    )
    client.send_human_email(to=HUB_EMAIL, subject=subject, body=text)

def send_from_GuestB_wan2008(subject, text):
    client = EmailClient(
        imap_server='imap.163.com', smtp_server='smtp.163.com',
        email_addr='tcwanqian2008@163.com', password='ESVpKB9u4BNBP48Y',
        imap_port=993, smtp_port=465
    )
    client.send_human_email(to=HUB_EMAIL, subject=subject, body=text)

print("==============================")
print("剧本开始: Admin 发起 Zoom 会议邀约")
print("==============================")
send_from_Admin_Initiator("新产品发布 Zoom 会议", "请帮我约 wan1@qq 和 wan2008@163 (也就是63883465@qq.com, tcwanqian2008@163.com) 下周开会，需要多轮协商。主题是新产品发布 Zoom 会议。")

print("等待 Hub 创建 Session... (最多等 60 秒)")
session_id = None
for i in range(12):
    time.sleep(5)
    if os.path.exists("/Users/qianwan/.aimp/sessions.db"):
        try:
            conn = sqlite3.connect("/Users/qianwan/.aimp/sessions.db")
            row = conn.execute("SELECT session_id, status FROM sessions ORDER BY updated_at DESC LIMIT 1").fetchone()
            if row and row[1] == 'negotiating':
                session_id = row[0]
                break
        except:
            pass

if not session_id:
    print("未发现新的会话，请检查配置")
    sys.exit(1)

subject_prefix = f"Re: [AIMP:{session_id}]"

print(f"\n=> 成功拿到 Session ID: {session_id}")

print(f"==============================")
print(f"Round 1: 故意错开时间")
print(f"==============================")
print("Admin: 我只有周一、周二有空。")
print("GuestA (wan1): 我这两天休假，只有下周三有空。")
print("GuestB (wan2008): 我下周三不行，只有下周四或者周五。")
send_from_Admin_Initiator(subject_prefix, "我推荐下周一或者周二。")
send_from_GuestA_wan1(subject_prefix, "下周一周二我在休假，只有下周三有空。")
send_from_GuestB_wan2008(subject_prefix, "下周三不行，我只能下周四或周五。")

print("等待 Hub 处理 Round 1...")
time.sleep(30) 

print(f"\n==============================")
print(f"Round 2: 周末调休的冲突")
print(f"==============================")
print("Admin: 既然这样，本周六加上班可以吗？")
print("GuestA (wan1): 周六勉强可以。")
print("GuestB (wan2008): 坚决不接受周末开会，我只能工作日。")
send_from_Admin_Initiator(subject_prefix, "好吧，既然大家都不行，那我本周六加上班可以吗？")
send_from_GuestA_wan1(subject_prefix, "周六勉强可以。")
send_from_GuestB_wan2008(subject_prefix, "坚决不接受周末开会，我只能工作日。")

print("等待 Hub 处理 Round 2...")
time.sleep(30)

print(f"\n==============================")
print(f"Round 3: 寻找最终解")
print(f"==============================")
print("Admin: 那这周四周五呢？大家能调出时间吗？")
print("GuestA (wan1): 我可以把这周四推掉，这周四OK。")
print("GuestB (wan2008): 我就是周四可以，既然你们都ok了，那就周四吧。")
send_from_Admin_Initiator(subject_prefix, "那这周四周五呢？大家能调出时间吗？")
send_from_GuestA_wan1(subject_prefix, "我可以把这周四的事情推掉，周四OK。")
send_from_GuestB_wan2008(subject_prefix, "周四本来就可以，所以我这边没问题，同意周四。")

print("等待 Hub 处理 Round 3, 期望达成共识并结束会话 !!")
for i in range(12):
    time.sleep(5)
    try:
        conn = sqlite3.connect("/Users/qianwan/.aimp/sessions.db")
        row = conn.execute("SELECT status, data FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if row:
            if row[0] == 'finalized' or row[0] == 'completed':
                print("\n✅ 测试成功！状态变为了: ", row[0])
                data = json.loads(row[1])
                print("最终会话数据:")
                print(json.dumps(data, indent=2, ensure_ascii=False))
                sys.exit(0)
            else:
                data = json.loads(row[1])
                print(f"仍在协商中... 当前轮次: {data.get('metrics',{}).get('rounds', 0)}")
    except Exception as e:
        print("db check error:", e)

print("超时未完成。")

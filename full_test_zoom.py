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
os.system("pkill -f 'run_4_rounds.py'")
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

def send_from_agentmail(subject, text):
    url = "https://api.agentmail.to/v0/inboxes/wan@agentmail.to/messages/send"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {AGENTMAIL_API_KEY}"}
    data = {"to": HUB_EMAIL, "subject": subject, "text": text}
    requests.post(url, headers=headers, json=data)

def send_from_wan1(subject, text):
    client = EmailClient(
        imap_server='imap.qq.com', smtp_server='smtp.qq.com',
        email_addr='63883465@qq.com', password='ohbohxsqjdbfcahg',
        imap_port=993, smtp_port=465
    )
    client.send_human_email(to=HUB_EMAIL, subject=subject, body=text)

def send_from_wan2008(subject, text):
    client = EmailClient(
        imap_server='imap.163.com', smtp_server='smtp.163.com',
        email_addr='tcwanqian2008@163.com', password='ESVpKB9u4BNBP48Y',
        imap_port=993, smtp_port=465
    )
    client.send_human_email(to=HUB_EMAIL, subject=subject, body=text)

print("Step 1: Admin sends meeting request to Hub")
send_from_agentmail("发起zoom会议邀约", "我是管理员，请帮我约 63883465@qq.com 和 tcwanqian2008@163.com 下周三开个会，这是一个zoom会议，确认大家有没有时间。")

print("等待 Hub 创建 Session... (最多等 60 秒)")
session_id = None
for i in range(12):
    time.sleep(5)
    if os.path.exists("/Users/qianwan/.aimp/sessions.db"):
        try:
            conn = sqlite3.connect("/Users/qianwan/.aimp/sessions.db")
            row = conn.execute("SELECT session_id, status, data FROM sessions ORDER BY updated_at DESC LIMIT 1").fetchone()
            if row and row[1] == 'negotiating':
                session_id = row[0]
                break
        except:
            pass
if not session_id:
    print("未发现新的会话，请检查配置或日志")
    sys.exit(1)

subject_prefix = f"Re: [AIMP:{session_id}]"
print(f"\n=> 成功拿到 Session ID: {session_id}")
print("等待30秒确保Hub发出通知给另外两个邮箱...")
time.sleep(30)

print("Step 2: Guests and Admin reply with available times (Next Wed/Thu)")
send_from_wan1(subject_prefix, "我下周三、周四都有空")
send_from_wan2008(subject_prefix, "我下周三或者周四都可以")
send_from_agentmail(subject_prefix, "下周三周四我都行")

print("等待 Hub 处理...")
for i in range(15):
    time.sleep(10)
    print(f"检查状态 (轮询 {i+1}/15)...")
    try:
        conn = sqlite3.connect("/Users/qianwan/.aimp/sessions.db")
        row = conn.execute("SELECT status, data FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if row:
            status = row[0]
            data = json.loads(row[1])
            print(f"Current Status: {status}")
            if status in ('finalized', 'completed'):
                print("会话已完成！")
                print(json.dumps(data, indent=2, ensure_ascii=False))
                sys.exit(0)
    except Exception as e:
        print("检查失败:", e)

print("超时，最终状态：")
conn = sqlite3.connect("/Users/qianwan/.aimp/sessions.db")
row = conn.execute("SELECT status, data FROM sessions WHERE session_id=?", (session_id,)).fetchone()
if row:
    print(row[0])
    print(json.dumps(json.loads(row[1]), indent=2, ensure_ascii=False))

import time
import sqlite3
import json
import sys
import sys
import os

sys.path.insert(0, '/Users/qianwan/ai-zoom/aimp')
from lib.email_client import EmailClient
import requests

HUB_EMAIL = 'wanqian200@qq.com'
AGENTMAIL_API_KEY = "am_us_c8e54d6d98e2c590c0c182abb98ded6d01da1bf5959cf5be278b288768ff5cbc"

print("清理先前的数据库...")
os.system("pkill -f 'hub_agent.py'")
time.sleep(1)
os.system("rm -f /Users/qianwan/.aimp/sessions.db* /Users/qianwan/.aimp/hub.log")
os.system('export HUB_PASSWORD="jggsdndyqrsocibe" && export DASHSCOPE_API_KEY="sk-53f52ec4226f4317ac87ac3cf1b96c43" && nohup python3 -u -c "import socket; socket.setdefaulttimeout(30); import runpy; runpy.run_path(\'/Users/qianwan/ai-zoom/aimp/hub_agent.py\', run_name=\'__main__\')" /Users/qianwan/.aimp/config.yaml 10 > /Users/qianwan/.aimp/hub.log 2>&1 & echo $! > /Users/qianwan/.aimp/hub.pid')
print("重启了 Hub，轮询间隔设置为 10 秒。等待 5 秒加速测试...")
time.sleep(5)

print("清理服务器上的星标，确保 Hub 能看到新发送的（或残留的）测试邮件...")
def unflag_recent():
    import imaplib, ssl
    ctx = ssl.create_default_context()
    conn = imaplib.IMAP4_SSL('imap.qq.com', 993, ssl_context=ctx)
    conn.login('wanqian200@qq.com', 'jggsdndyqrsocibe')
    conn.select('INBOX')
    # Unflag last 20 messages to be sure
    s, u = conn.uid('SEARCH', None, 'FLAGGED')
    if s == 'OK' and u[0]:
        for uid in u[0].split():
            conn.uid('STORE', uid, '-FLAGS', '\\Flagged')
    conn.logout()

try:
    unflag_recent()
except Exception as e:
    print(f"Unflag failed (skipped): {e}")

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


print("==============================")
print("开始多轮测试: P1 (wan1 QQ)")
print("==============================")

send_from_wan1("发起头脑风暴会议", "请帮我约 wan@agentmail.to 和 tcwanqian2008@163.com 下周开会，需要多轮协商才能定下时间。主题是年度总结。")

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
send_from_wan1(subject_prefix, "我只能选下周一")
send_from_wan2008(subject_prefix, "我只能选下周二")
send_from_agentmail(subject_prefix, "我只有下周三有空")

print("等待 Hub 处理 Round 1...")
time.sleep(30) # 给 Hub 多一点时间调用大模型

print(f"\n==============================")
print(f"Round 2: 再次冲突")
print(f"==============================")
send_from_wan1(subject_prefix, "既然大家都不行，那我下周四或者周五")
send_from_wan2008(subject_prefix, "周四周五我在出差啊，完全不行")
send_from_agentmail(subject_prefix, "周四我可以，周五不行")

print("等待 Hub 处理 Round 2...")
time.sleep(30)

print(f"\n==============================")
print(f"Round 3: 部分达成共识")
print(f"==============================")
send_from_wan1(subject_prefix, "周末大家加班可以吗？比如周六")
send_from_wan2008(subject_prefix, "周六勉强可以接受吧")
send_from_agentmail(subject_prefix, "我不接受加班，我只能工作日")

print("等待 Hub 处理 Round 3...")
time.sleep(30)


print(f"\n==============================")
print(f"Round 4: 最终妥协达成")
print(f"==============================")
send_from_wan1(subject_prefix, "好吧，那就下周三吧，我推掉别的事情")
send_from_wan2008(subject_prefix, "下周三我也ok了，没问题")
send_from_agentmail(subject_prefix, "下周三很好，我同意")

print("等待 Hub 处理 Round 4, 期望达成共识并结束会话 !!")
for i in range(12):
    time.sleep(5)
    try:
        conn = sqlite3.connect("/Users/qianwan/.aimp/sessions.db")
        row = conn.execute("SELECT status, data FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if row:
            if row[0] == 'finalized' or row[0] == 'completed':
                print("\\n✅ 测试成功！状态变为了: ", row[0])
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

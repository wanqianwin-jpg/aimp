import time
import sqlite3
import json
import sys
import os
import requests

sys.path.insert(0, '/Users/qianwan/ai-zoom/aimp')
from lib.email_client import EmailClient

HUB_EMAIL = '63883465@qq.com'
AGENTMAIL_API_KEY = "am_us_c8e54d6d98e2c590c0c182abb98ded6d01da1bf5959cf5be278b288768ff5cbc"

print("清理先前的数据库...")
os.system("pkill -f 'hub_agent.py'")
time.sleep(2)
os.system("rm -f /Users/qianwan/.aimp/rooms.db* /Users/qianwan/.aimp/sessions.db* /Users/qianwan/.aimp/hub.log")
os.system('export HUB_PASSWORD="ohbohxsqjdbfcahg" && export DASHSCOPE_API_KEY="sk-53f52ec4226f4317ac87ac3cf1b96c43" && nohup python3 -u -c "import socket; socket.setdefaulttimeout(30); import runpy; runpy.run_path(\'/Users/qianwan/ai-zoom/aimp/hub_agent.py\', run_name=\'__main__\')" /Users/qianwan/.aimp/config.yaml 10 > /Users/qianwan/.aimp/hub.log 2>&1 & echo $! > /Users/qianwan/.aimp/hub.pid')
print("重启了 Hub (使用 63883465@qq.com 邮箱)，轮询间隔设置为 10 秒。等待 5 秒加速测试...")
time.sleep(5)

print("Skipping unflag_recent as it breaks the inbox limit...")

def send_from_Admin_Initiator(subject, text):
    url = "https://api.agentmail.to/v0/inboxes/wan@agentmail.to/messages/send"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {AGENTMAIL_API_KEY}"}
    data = {"to": HUB_EMAIL, "subject": subject, "text": text}
    requests.post(url, headers=headers, json=data)

def send_from_GuestA_wan2008(subject, text):
    client = EmailClient(
        imap_server='imap.163.com', smtp_server='smtp.163.com',
        email_addr='tcwanqian2008@163.com', password='ESVpKB9u4BNBP48Y',
        imap_port=993, smtp_port=465
    )
    client.send_human_email(to=HUB_EMAIL, subject=subject, body=text)

def send_from_GuestB_hub(subject, text):
    client = EmailClient(
        imap_server='imap.qq.com', smtp_server='smtp.qq.com',
        email_addr='63883465@qq.com', password='ohbohxsqjdbfcahg',
        imap_port=993, smtp_port=465
    )
    client.send_human_email(to=HUB_EMAIL, subject=subject, body=text)

print("==============================")
print("剧本开始: Admin 发起 内容协商(开会) 邀约")
print("==============================")
send_from_Admin_Initiator("内容协商请求：新产品发布方案", "请帮我发起一个内容协商室(不要约会议，是开启内容协商)，主题是新产品发布方案。参与者是 tcwanqian2008@163.com 和 63883465@qq.com。截止时间是明天。初始提案是：我们在下周举办线上发布会，邀请媒体参加。")

print("等待 Hub 创建 Room... (最多等 60 秒)")
room_id = None
for i in range(12):
    time.sleep(5)
    if os.path.exists("/Users/qianwan/.aimp/rooms.db"):
        try:
            conn = sqlite3.connect("/Users/qianwan/.aimp/rooms.db")
            row = conn.execute("SELECT room_id, status FROM rooms ORDER BY updated_at DESC LIMIT 1").fetchone()
            if row and row[1] == 'open':
                room_id = row[0]
                break
        except:
            pass

if not room_id:
    print("未发现新的会话 (rooms.db未生成或无匹配状态)。尝试从 sessions.db 查询看是不是发起错误了...")
    try:
        conn = sqlite3.connect("/Users/qianwan/.aimp/sessions.db")
        row = conn.execute("SELECT session_id, status FROM sessions ORDER BY updated_at DESC LIMIT 1").fetchone()
        if row:
            print("注意：Hub 解析成了 schedule_meeting 而不是 create_room！", row)
    except:
        pass
    sys.exit(1)

subject_prefix = f"[AIMP:Room:{room_id}] Re: 新产品发布方案"

print(f"\n=> 成功拿到 Room ID: {room_id}")

print(f"==============================")
print(f"Round 1: 提出各自修正意见")
print(f"==============================")
print("Admin: 我补充一下，要有抽奖环节。")
print("GuestA: 我建议加上线下体验，在北京办公室。")
print("GuestB: 考虑到成本，我不同意线下体验，建议纯线上，赞成抽奖。")
send_from_Admin_Initiator(subject_prefix, "我本人补充一下：流程中需要有用户抽奖环节。")
send_from_GuestA_wan2008(subject_prefix, "我建议加上线下体验，考虑在北京办公室设立体验区。")
send_from_GuestB_hub(subject_prefix, "考虑到成本，我不同意线下体验，建议维持纯线上模式，我赞成加抽奖环节。")

print("等待 Hub 聚合 Round 1... 这需要 Hub 解析所有人内容并生成 summary")
time.sleep(45) 

print(f"\n==============================")
print(f"Round 2: 达成最终决定")
print(f"==============================")
print("Admin: 好的，那纯线上 + 抽奖。")
print("GuestA: 行，放弃线下体验，同意现在的。")
print("GuestB: 同意。")
send_from_Admin_Initiator(subject_prefix, "好的，既然大家觉得线下成本高，那就接受纯线上+抽奖方案，我完全同意。")
send_from_GuestA_wan2008(subject_prefix, "行吧，放弃线下体验，我同意现在的综合方案。")
send_from_GuestB_hub(subject_prefix, "同意当前方案。")

print("等待 Hub 聚合 Round 2, 期望达成共识并出局...")
for i in range(12):
    time.sleep(5)
    try:
        conn = sqlite3.connect("/Users/qianwan/.aimp/rooms.db")
        row = conn.execute("SELECT status, transcript, resolution FROM rooms WHERE room_id=?", (room_id,)).fetchone()
        if row:
            if row[0] == 'finalized' or row[0] == 'completed':
                print("\n✅ 测试成功！状态变为了: ", row[0])
                print("最终方案:")
                print(row[2])
                sys.exit(0)
            else:
                transcript = json.loads(row[1])
                print(f"仍在协商中... 当前记录数量: {len(transcript)} (状态: {row[0]})")
    except Exception as e:
        print("db check error:", e)

print("超时未完成。状态：")
try:
    conn = sqlite3.connect("/Users/qianwan/.aimp/rooms.db")
    row = conn.execute("SELECT status, resolution FROM rooms WHERE room_id=?", (room_id,)).fetchone()
    print(row)
except:
    pass

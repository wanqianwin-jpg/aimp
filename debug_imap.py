#!/usr/bin/env python3
"""
临时诊断脚本：检查 AgentMail IMAP 实际状态
用法: python3 debug_imap.py
"""
import imaplib
import sys

IMAP_SERVER = input("IMAP 服务器地址: ").strip()
IMAP_PORT   = int(input("IMAP 端口 [993]: ").strip() or "993")
EMAIL       = input("邮箱地址: ").strip()
PASSWORD    = input("密码/授权码: ").strip()

print("\n--- 连接中 ---")
try:
    conn = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
except Exception as e:
    print(f"❌ 连接失败: {e}")
    sys.exit(1)

print("✅ TCP 连接成功")

try:
    conn.login(EMAIL, PASSWORD)
    print("✅ 登录成功")
except Exception as e:
    print(f"❌ 登录失败: {e}")
    sys.exit(1)

print("\n--- 所有可用文件夹 ---")
status, folders = conn.list()
for f in folders:
    print(" ", f.decode() if isinstance(f, bytes) else f)

print("\n--- 尝试 SELECT INBOX ---")
status, data = conn.select("INBOX")
print(f"  状态: {status}, 邮件数: {data[0].decode() if data[0] else 0}")

print("\n--- SEARCH ALL (忽略已读/未读) ---")
status, uids = conn.search(None, "ALL")
all_uids = uids[0].split() if uids[0] else []
print(f"  找到 {len(all_uids)} 封邮件")

if all_uids:
    print("\n--- 最近 3 封邮件的 Subject / From ---")
    for uid in all_uids[-3:]:
        _, data = conn.fetch(uid, "(BODY[HEADER.FIELDS (FROM SUBJECT DATE FLAGS)])")
        if data and data[0]:
            raw = data[0][1].decode(errors="replace") if isinstance(data[0][1], bytes) else str(data[0][1])
            print(f"\n  UID {uid.decode()}:")
            for line in raw.strip().splitlines():
                print(f"    {line}")

print("\n--- SEARCH UNSEEN ---")
status, uids = conn.search(None, "UNSEEN")
unseen_uids = uids[0].split() if uids[0] else []
print(f"  未读邮件数: {len(unseen_uids)}")

conn.logout()
print("\n完成。")

import socket
import smtplib
import ssl
try:
    context = ssl.create_default_context()
    conn = smtplib.SMTP_SSL("smtp.qq.com", 465, context=context, timeout=15)
    conn.set_debuglevel(1)
    conn.login("wanqian200@qq.com", "jggsdndyqrsocibe")
    print("Login successful.")
    conn.quit()
except Exception as e:
    print(f"Error: {e}")

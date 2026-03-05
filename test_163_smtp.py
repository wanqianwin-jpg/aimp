import smtplib, ssl
try:
    ctx = ssl.create_default_context()
    conn2 = smtplib.SMTP_SSL("smtp.163.com", 465, context=ctx, timeout=5)
    conn2.login("tcwanqian2008@163.com", "ESVpKB9u4BNBP48Y")
    print("SMTP Login: OK")
    conn2.quit()
except Exception as e:
    print("SMTP Error:", e)

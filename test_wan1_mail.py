import imaplib, ssl, smtplib
try:
    ctx = ssl.create_default_context()
    conn = imaplib.IMAP4_SSL('imap.qq.com', 993, ssl_context=ctx)
    print("IMAP Login:", conn.login('63883465@qq.com', 'ohbohxsqjdbfcahg'))
    print("IMAP Select:", conn.select('INBOX'))
    conn.logout()
except Exception as e:
    print("IMAP Error:", e)

try:
    conn2 = smtplib.SMTP_SSL("smtp.qq.com", 465, context=ctx, timeout=5)
    conn2.login("63883465@qq.com", "ohbohxsqjdbfcahg")
    print("SMTP Login: OK")
    conn2.quit()
except Exception as e:
    print("SMTP Error:", e)

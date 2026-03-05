import imaplib, ssl
ctx = ssl.create_default_context()
conn = imaplib.IMAP4_SSL('imap.163.com', 993, ssl_context=ctx)
print("Login:", conn.login('tcwanqian2008@163.com', 'ESVpKB9u4BNBP48Y'))
print("Select INBOX:", conn.select('INBOX'))
conn.logout()

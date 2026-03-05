import imaplib, ssl

def mark_all_as_flagged(email, password):
    print(f"Marking all emails in {email} as Flagged AND Seen...")
    ctx = ssl.create_default_context()
    conn = imaplib.IMAP4_SSL('imap.qq.com', 993, ssl_context=ctx)
    conn.login(email, password)
    conn.select('INBOX')
    
    status, uids = conn.search(None, 'ALL')
    if status == 'OK' and uids[0]:
        uid_list = uids[0].split()
        for i in range(0, len(uid_list), 100):
            batch = b','.join(uid_list[i:i+100])
            conn.store(batch, '+FLAGS', '\\Flagged')
            conn.store(batch, '+FLAGS', '\\Seen')
        print(f"Marked {len(uid_list)} emails.")
    conn.logout()

mark_all_as_flagged('63883465@qq.com', 'ohbohxsqjdbfcahg')

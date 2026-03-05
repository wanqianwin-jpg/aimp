import requests
AGENTMAIL_API_KEY = "am_us_c8e54d6d98e2c590c0c182abb98ded6d01da1bf5959cf5be278b288768ff5cbc"
url = "https://api.agentmail.to/v0/inboxes/wan2@agentmail.to/messages/send"
headers = {"Content-Type": "application/json", "Authorization": f"Bearer {AGENTMAIL_API_KEY}"}
data = {"to": "63883465@qq.com", "subject": "Test from wan2", "text": "Hello"}
r = requests.post(url, headers=headers, json=data)
print(r.status_code, r.text)

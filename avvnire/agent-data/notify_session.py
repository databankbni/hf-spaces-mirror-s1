#!/usr/bin/env python3
"""Notification helper - writes to chat_sessions.db, best-effort iLink push."""
import sys, os, json, sqlite3, ssl, urllib.request, datetime

DB_PATH = "/opt/data/chat_sessions.db"

def notify(message):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Write to DB
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("CREATE TABLE IF NOT EXISTS sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, openid TEXT, role TEXT, content TEXT, timestamp TEXT)")
        conn.execute("INSERT INTO sessions (openid, role, content, timestamp) VALUES (?, ?, ?, ?)",
                     ("cron_notifier", "assistant", message, ts))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"DB error: {e}", file=sys.stderr)
    # Best-effort iLink
    try:
        token_file = "/tmp/last_context_token"
        from_file = "/tmp/last_from_user"
        token = open(token_file).read().strip() if os.path.exists(token_file) else ""
        from_user = open(from_file).read().strip() if os.path.exists(from_file) else ""
        if token and from_user:
            import struct, secrets, base64 as b64
            ILINK_BASE = "https://ilinkai.weixin.qq.com"
            ILINK_TOKEN = os.environ.get("ILINK_TOKEN", "")
            ILINK_APP_ID = "bot"
            ILINK_APP_CLIENT_VERSION = 14
            uin = b64.b64encode(str(struct.unpack(">I", secrets.token_bytes(4))[0]).encode()).decode()
            body = json.dumps({"content": message, "bot_type": 3, "to_user": from_user, "context_token": token})
            req = urllib.request.Request(f"{ILINK_BASE}/cgi-bin/message/sendmessage",
                data=body.encode(),
                headers={"Content-Type": "application/json", "AuthorizationType": "ilink_bot_token",
                         "Content-Length": str(len(body.encode())), "X-WECHAT-UIN": uin,
                         "iLink-App-Id": ILINK_APP_ID, "iLink-App-ClientVersion": str(ILINK_APP_CLIENT_VERSION),
                         "Authorization": f"Bearer {ILINK_TOKEN}"})
            sctx = ssl.create_default_context()
            sctx.check_hostname = False
            sctx.verify_mode = ssl.CERT_NONE
            urllib.request.urlopen(req, context=sctx, timeout=10)
    except Exception:
        pass

if __name__ == "__main__":
    msg = sys.argv[1] if len(sys.argv) > 1 else "(no message)"
    notify(msg)
    print("NOTIFIED")

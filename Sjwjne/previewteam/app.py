import sqlite3
from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)
DOMAIN_NAME = "tempgm2.abrdns.com"

# SQLITE DATABASE SETUP
def init_db():
    conn = sqlite3.connect('tempmail.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            temp_email TEXT,
            sender TEXT,
            subject TEXT,
            body TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TempGM Mail</title>
    <style>
        * { box-sizing: border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f0f2f5; margin: 0; padding: 20px; }
        .card { max-width: 700px; margin: auto; background: white; padding: 25px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }
        h1 { text-align: center; color: #1e293b; margin-top: 0; }
        .subtitle { text-align: center; color: #64748b; margin-bottom: 20px; font-size: 14px; }
        .email-display { background: #eef2ff; border: 2px dashed #4f46e5; padding: 15px; text-align: center; font-size: 18px; font-weight: bold; color: #4338ca; border-radius: 8px; margin-bottom: 20px; word-break: break-all; }
        .btn-group { display: flex; gap: 8px; justify-content: center; flex-wrap: wrap; margin-bottom: 25px; }
        button { padding: 10px 16px; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; font-weight: 600; transition: 0.2s; }
        .btn-primary { background: #4f46e5; color: white; }
        .btn-success { background: #10b981; color: white; }
        .btn-secondary { background: #e2e8f0; color: #334155; }
        .btn-danger { background: #ef4444; color: white; }
        .inbox { border-top: 2px solid #f1f5f9; padding-top: 20px; }
        .mail-card { background: #f8fafc; border: 1px solid #e2e8f0; padding: 15px; border-radius: 8px; margin-bottom: 12px; }
        .mail-header { font-weight: bold; color: #0f172a; margin-bottom: 4px; font-size: 14px; }
        .mail-body { background: white; padding: 12px; border-radius: 6px; border: 1px solid #e2e8f0; margin-top: 8px; white-space: pre-wrap; color: #334155; font-size: 13px; line-height: 1.5; }
        .status { text-align: center; color: #10b981; font-size: 13px; margin-bottom: 15px; font-weight: 600; background: #ecfdf5; padding: 8px; border-radius: 6px; }
    </style>
</head>
<body>
    <div class="card">
        <h1>TempGM Generator</h1>
        <div class="subtitle">100% Free Custom Temporary Email Service</div>
        
        <div class="email-display" id="email-address">Loading saved email...</div>
        
        <div class="btn-group">
            <button class="btn-primary" onclick="generateNewMail()">Change Email</button>
            <button class="btn-success" onclick="copyEmail()">Copy Email</button>
            <button class="btn-secondary" onclick="fetchMails()">Refresh Inbox</button>
            <button class="btn-danger" onclick="wipeMails()">Wipe All Messages</button>
        </div>

        <div class="inbox">
            <h3>Inbox</h3>
            <div id="status" class="status">Listening for new emails...</div>
            <div id="mail-list">No emails received yet.</div>
        </div>
    </div>

    <script>
        let currentEmail = "";

        function initEmail() {
            let saved = localStorage.getItem("temp_email_address");
            if (saved && saved.endsWith("@" + "{{ domain }}")) {
                currentEmail = saved;
            } else {
                generateNewMail();
                return;
            }
            document.getElementById("email-address").innerText = currentEmail;
            fetchMails();
        }

        function generateNewMail() {
            let rand = Math.random().toString(36).substring(2, 9);
            currentEmail = rand + "@" + "{{ domain }}";
            localStorage.setItem("temp_email_address", currentEmail);
            document.getElementById("email-address").innerText = currentEmail;
            document.getElementById("mail-list").innerHTML = "Inbox is empty.";
            fetchMails();
        }

        function copyEmail() {
            navigator.clipboard.writeText(currentEmail);
            alert("Copied: " + currentEmail);
        }

        async function fetchMails() {
            if (!currentEmail) return;
            try {
                let res = await fetch("/get-inbox?email=" + encodeURIComponent(currentEmail));
                let resData = await res.json();
                
                let listDiv = document.getElementById("mail-list");
                if (resData.mails.length === 0) {
                    listDiv.innerHTML = "No emails received yet.";
                } else {
                    listDiv.innerHTML = "";
                    resData.mails.forEach(m => {
                        listDiv.innerHTML += `
                            <div class="mail-card">
                                <div class="mail-header">From: ${m.from}</div>
                                <div class="mail-header">Subject: ${m.subject}</div>
                                <div class="mail-header" style="font-size:11px; color:#888;">Received: ${m.time}</div>
                                <div class="mail-body">${m.body}</div>
                            </div>
                        `;
                    });
                }
            } catch (e) {
                console.error(e);
            }
        }

        async function wipeMails() {
            if (!confirm("Are you sure you want to delete all messages for this email?")) return;
            await fetch("/wipe-inbox?email=" + encodeURIComponent(currentEmail), { method: "POST" });
            fetchMails();
        }

        initEmail();
        setInterval(fetchMails, 4000); // Check inbox every 4 seconds
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE, domain=DOMAIN_NAME)

# YEH ENDPOINT GMAIL SE DIRECT EMAILS RECEIVE KAREGA (WEBHOOK)
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    if not data:
        return jsonify({"status": "error"}), 400

    to_email = data.get('to', '').lower()
    from_email = data.get('from', 'Unknown')
    subject = data.get('subject', 'No Subject')
    body = data.get('body', '')

    conn = sqlite3.connect('tempmail.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO emails (temp_email, sender, subject, body)
        VALUES (?, ?, ?, ?)
    ''', (to_email, from_email, subject, body))
    conn.commit()
    conn.close()

    return jsonify({"status": "success"}), 200

@app.route('/get-inbox')
def get_inbox():
    target_email = request.args.get('email', '').lower().strip()
    if not target_email:
        return jsonify({"mails": []})

    conn = sqlite3.connect('tempmail.db')
    cursor = conn.cursor()
    # SQL LIKE operator se extract karega
    cursor.execute('''
        SELECT id, sender, subject, body, timestamp FROM emails 
        WHERE temp_email LIKE ? ORDER BY id DESC
    ''', (f'%{target_email}%',))
    rows = cursor.fetchall()
    conn.close()

    messages = []
    for r in rows:
        messages.append({
            "id": r[0],
            "from": r[1],
            "subject": r[2],
            "body": r[3],
            "time": r[4]
        })

    return jsonify({"mails": messages})

@app.route('/wipe-inbox', methods=['POST'])
def wipe_inbox():
    target_email = request.args.get('email', '').lower().strip()
    if target_email:
        conn = sqlite3.connect('tempmail.db')
        cursor = conn.cursor()
        cursor.execute('DELETE FROM emails WHERE temp_email LIKE ?', (f'%{target_email}%',))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7860)
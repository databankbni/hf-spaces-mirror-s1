#!/usr/bin/env python3
"""
Hermes Agent - Full Web UI for HuggingFace Spaces
Complete agent interface with chat, file management, code execution,
tool visualization, skills system, and WeChat integration.
"""

import os, sys, json, time, ssl, threading, subprocess, base64, struct, secrets, hashlib, re
import security  # security module
import urllib.request, urllib.error, urllib.parse
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime

# Set timezone to Beijing time
os.environ["TZ"] = "Asia/Shanghai"
try:
    time.tzset()
except:
    pass

# ── Config ──────────────────────────────────────────────────────────────
PORT = int(os.environ.get("PORT", 7860))
HERMES_HOME = os.environ.get("HERMES_HOME", "/opt/data")

# ── SQLite Session Store (30-day rolling) ─────────────────────────────
import sqlite3, threading as _threading

DB_PATH = os.path.join(HERMES_HOME, "chat_sessions.db")
SOUL_PATH = "/app/soul.json"
PROFILE_PATH = "/app/profile.json"

def load_soul():
    try:
        with open(SOUL_PATH, "r") as f:
            return json.load(f)
    except:
        return {"system_prompt": "You are Hermes Agent.", "model": "agnes-2.0-flash", "max_tokens": max_tokens, "search_enabled": True, "search_prefix": "Based on results:"}

def load_profile():
    try:
        with open(PROFILE_PATH, "r") as f:
            return json.load(f)
    except:
        return {"user_name": "", "timezone": "Asia/Shanghai", "language": "zh-CN", "preferences": {"auto_search": True}}
_db_lock = _threading.Lock()

def load_skills_summary():
    """Scan /app/skills/ for SKILL.md files, extract name+description from frontmatter."""
    import glob
    skills = []
    for skill_md in glob.glob("/app/skills/**/SKILL.md", recursive=True):
        try:
            with open(skill_md, "r") as f:
                content = f.read(2000)
            name_m = re.search(r"name:\s*(.+)", content)
            desc_m = re.search(r"description:\s*(.+)", content)
            if name_m and desc_m:
                name = name_m.group(1).strip().strip('"').strip("'")
                desc = desc_m.group(1).strip().strip('"').strip("'")
                if len(desc) > 100:
                    desc = desc[:100] + "..."
                skills.append("- " + name + ": " + desc)
        except:
            pass
    if skills:
        return "\n".join(skills)
    return ""

def load_skill_content(skill_name):
    """Load full content of a specific skill by name."""
    import glob
    for skill_md in glob.glob("/app/skills/**/SKILL.md", recursive=True):
        try:
            with open(skill_md, "r") as f:
                content = f.read()
            name_m = re.search(r"name:\s*(.+)", content)
            if name_m and name_m.group(1).strip() == skill_name:
                return content
        except:
            pass
    return ""

def _init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        openid TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT,
        timestamp REAL NOT NULL
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sessions_openid ON sessions(openid)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sessions_ts ON sessions(timestamp)")
    conn.commit()
    conn.close()

def _save_to_db(openid, role, content):
    try:
        with _db_lock:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("INSERT INTO sessions(openid, role, content, timestamp) VALUES (?, ?, ?, ?)",
                         (openid, role, content, time.time()))
            # 清理30天前数据
            conn.execute("DELETE FROM sessions WHERE timestamp < ?", (time.time() - 30*86400,))
            conn.commit()
            conn.close()
            try:
                from data_sync import immediate_sync
                immediate_sync()
            except:
                pass
    except Exception:
        pass

_init_db()

ILINK_BASE = "https://ilinkai.weixin.qq.com"
ILINK_APP_ID = "bot"
CHANNEL_VERSION = "2.2.0"
ILINK_APP_CLIENT_VERSION = (2 << 16) | (2 << 8) | 0

# ── Auth ───────────────────────────────────────────────────────
SITE_PASSWORD = os.environ.get("SITE_PASSWORD", "80699436")
SITE_PASSWORD_HASH = hashlib.sha256(SITE_PASSWORD.encode()).hexdigest()
AUTHORIZED_OPENIDS = set()
AUTHORIZED_FILE = os.path.join(HERMES_HOME, "authorized_openids.txt")
if os.path.exists(AUTHORIZED_FILE):
    with open(AUTHORIZED_FILE, "r") as f:
        for line in f:
            oid = line.strip()
            if oid:
                AUTHORIZED_OPENIDS.add(oid)
print(f"[AUTH] Loaded {len(AUTHORIZED_OPENIDS)} authorized openids")
poll_weixin_error = ""

EP_GET_BOT_QR = "ilink/bot/get_bot_qrcode"
EP_GET_QR_STATUS = "ilink/bot/get_qrcode_status"
EP_GET_UPDATES = "ilink/bot/getupdates"
EP_SEND_MESSAGE = "ilink/bot/sendmessage"

ITEM_TEXT = 1
MSG_TYPE_BOT = 2
MSG_STATE_FINISH = 2

ilink_token = os.environ.get("ILINK_TOKEN", "")  # Token from env only
poll_weixin_processed = 0
last_poll_result = {}
ilink_base = ILINK_BASE
processed_ids = set()
sync_buf = ""
chat_history = {}
gateway_process = None

# ── Logging ─────────────────────────────────────────────────────────────
def log(tag, msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{tag}] {msg}", flush=True)

def _global_excepthook(exc_type, exc_value, exc_tb):
    try:
        import traceback as _tb
        log("HOOK", f"Unhandled exception: {exc_value}")
        _tb.print_exception(exc_type, exc_value, exc_tb)
    except:
        pass

sys.excepthook = _global_excepthook

# ── Bootstrap config ────────────────────────────────────────────────────
def bootstrap_config():
    os.makedirs(HERMES_HOME, exist_ok=True)
    for d in ["hindsight", "skills", "sessions", "cron", "logs"]:
        os.makedirs(os.path.join(HERMES_HOME, d), exist_ok=True)

    # hindsight config
    hc_path = os.path.join(HERMES_HOME, "hindsight", "config.json")
    if not os.path.exists(hc_path):
        hsk = os.environ.get("HINDSIGHT_API_KEY", "")
        hc = {
            "mode": "cloud", "apiUrl": "https://api.hindsight.vectorize.io",
            "apiKey": hsk, "timeout": 120, "idle_timeout": 300,
            "retain_tags": [], "retain_source": "hermes-agent",
            "retain_user_prefix": "User", "retain_assistant_prefix": "Assistant",
            "banks": {"hermes": {"bankId": "hermes", "budget": "mid", "enabled": True}},
            "max_observations_per_scope": 300,
            "enable_auto_consolidation": True,
            "consolidation_max_memories_per_round": 100
        }
        with open(hc_path, "w") as f:
            json.dump(hc, f, indent=2)
        log("CONFIG", "Written hindsight config")

    # .env
    env_path = os.path.join(HERMES_HOME, ".env")
    if not os.path.exists(env_path):
        lines = [
            f"OPENROUTER_API_KEY={os.environ.get('OPENROUTER_API_KEY', '')}",
            f"HINDSIGHT_API_KEY={os.environ.get('HINDSIGHT_API_KEY', '')}",
        ]
        with open(env_path, "w") as f:
            f.write("\n".join(lines) + "\n")
        log("CONFIG", "Written .env")

    # Sync skills
    skills_src = "/opt/hermes/skills"
    skills_dst = os.path.join(HERMES_HOME, "skills")
    if os.path.exists(skills_src):
        import shutil
        for skill_name in os.listdir(skills_src):
            src = os.path.join(skills_src, skill_name)
            dst = os.path.join(skills_dst, skill_name)
            if os.path.isdir(src) and not os.path.exists(dst):
                shutil.copytree(src, dst)
        log("CONFIG", "Skills synced")

    # Start data sync
    try:
        from data_sync import start_sync
        import security
        start_sync()
    except Exception as e:
        log("CONFIG", "Data sync error: " + str(e))

    # Start memory cleanup (LFU eviction)
    try:
        from memory_cleanup import start_cleanup
        start_cleanup()
    except Exception as e:
        log("CONFIG", "Memory cleanup error: " + str(e))

# ── Hermes CLI ──────────────────────────────────────────────────────────
def find_hermes_cli():
    candidates = ["hermes", "/opt/data/.local/bin/hermes", "/opt/hermes/.venv/bin/hermes"]
    env = {**os.environ, "HERMES_HOME": HERMES_HOME}
    for c in candidates:
        try:
            r = subprocess.run([c, "--version"], capture_output=True, text=True, timeout=10, env=env)
            if r.returncode == 0:
                return c
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None

def call_hermes_chat(message, history=None):
    try:
        cli = find_hermes_cli()
        if not cli:
            return call_llm_fallback(message, history)
        cmd = cli.split() + ["chat", "-q", "--no-stream", "--message", message]
        env = {**os.environ, "HERMES_HOME": HERMES_HOME}
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env, cwd=HERMES_HOME)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
        return call_llm_fallback(message, history)
    except subprocess.TimeoutExpired:
        return "处理超时，请稍后再试"
    except Exception as e:
        log("HERMES", f"Error: {e}")
        return call_llm_fallback(message, history)

def _do_web_search(query, max_results=5):
    """DuckDuckGo search - returns formatted results"""
    try:
        from web_search import search_duckduckgo
        results = search_duckduckgo(query, max_results=max_results)
        if not results:
            return "No results found"
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r.get('title','')}\n   {r.get('url','')}\n   {r.get('snippet','')}")
        return "\n\n".join(lines)
    except Exception as e:
        return f"Search error: {e}"

WEB_SEARCH_PATTERNS = [
    r'(?:搜索|查一下|搜一下|search|查找|查询)[\s:：]*(.+)',
]

def _maybe_web_search(message):
    """Detect search intent and execute search"""
    msg = message.strip()
    if msg.startswith(("/search", "/搜索", "/s ")):
        query = msg.split(" ", 1)[1] if " " in msg else ""
        if query:
            return _do_web_search(query)
    for pat in WEB_SEARCH_PATTERNS:
        m = re.match(pat, msg, re.IGNORECASE)
        if m:
            return _do_web_search(m.group(1).strip())
    return None


def call_llm_fallback(message, history=None):
    """Agnes AI LLM with web search"""
    api_key = os.environ.get("AGNES_API_KEY", "")
    if not api_key:
        return "未配置 Agnes API Key"
    model = os.environ.get("HERMES_MODEL", "agnes-2.0-flash")
    from datetime import datetime
    date_str = datetime.now().strftime("%Y年%m月%d日")
    search_query = message + " " + date_str
    search_context = ""
    try:
        from web_search import search_duckduckgo
        results = search_duckduckgo(search_query, max_results=5)
        if results:
            sl = []
            for i, r in enumerate(results, 1):
                sl.append("[" + str(i) + "] " + r["title"] + " | " + r["snippet"])
            search_context = "\n\n" + date_str + "的网络搜索结果如下，请务必基于这些结果回答，不要说你无法访问互联网：\n" + "\n".join(sl)
    except Exception as e:
        log("SEARCH", "Search failed: " + str(e))
    soul = load_soul()
    profile = load_profile()
    model = os.environ.get("HERMES_MODEL", soul.get("model", "agnes-2.0-flash"))
    max_tokens = soul.get("max_tokens", 4096)
    sys_content = soul.get("system_prompt", "You are Hermes Agent. Reply in Chinese.")
    skills_summary = load_skills_summary()
    if skills_summary:
        sys_content += "\n\nYou have the following skills available:\n" + skills_summary + "\nWhen a user question matches a skill, mention which skill applies and follow its methodology."
    uname = profile.get("user_name", "")
    if uname:
        sys_content += "\nUser: " + uname + "."
    if search_context:
        sys_content += search_context
    messages = [{"role": "system", "content": sys_content}]
    if history:
        for h in history[-10:]:
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": message})
    try:
        api_url = "https://apihub.agnes-ai.com/v1/chat/completions"
        ctx = ssl.create_default_context()
        payload = {"model": model, "messages": messages, "max_tokens": 4096}
        req = urllib.request.Request(api_url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"})
        with urllib.request.urlopen(req, context=ctx, timeout=120) as resp:
            data = json.loads(resp.read().decode())
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"调用失败: {e}"

def _random_uin():
    value = struct.unpack(">I", secrets.token_bytes(4))[0]
    return base64.b64encode(str(value).encode()).decode()

def _ilink_headers(body_str, token=""):
    h = {"Content-Type": "application/json", "AuthorizationType": "ilink_bot_token",
         "Content-Length": str(len(body_str.encode())), "X-WECHAT-UIN": _random_uin(),
         "iLink-App-Id": ILINK_APP_ID, "iLink-App-ClientVersion": str(ILINK_APP_CLIENT_VERSION)}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h

def ilink_get(endpoint, token=""):
    url = f"{ilink_base.rstrip('/')}/{endpoint}"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    hdrs = {"iLink-App-Id": ILINK_APP_ID, "iLink-App-ClientVersion": str(ILINK_APP_CLIENT_VERSION)}
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=hdrs, method="GET")
    resp = urllib.request.urlopen(req, timeout=15, context=ctx)
    return json.loads(resp.read())

def ilink_post(endpoint, payload, token=""):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    url = f"{ilink_base.rstrip('/')}/{endpoint}"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, data=body.encode(), headers=_ilink_headers(body, token), method="POST")
    resp = urllib.request.urlopen(req, timeout=30, context=ctx)
    return json.loads(resp.read())

def poll_weixin():
    global sync_buf, ilink_token, ilink_base, poll_weixin_error, poll_weixin_processed
    log("WEIXIN", "Polling started")
    while True:
        if not ilink_token:
            time.sleep(5)
            continue
        try:
            result = ilink_post(EP_GET_UPDATES,
                {"get_updates_buf": sync_buf, "base_info": {"channel_version": CHANNEL_VERSION}},
                ilink_token)
            last_poll_result = result  # save result for debug
            log("WEIXIN", f"API result: errcode={result.get('errcode')}, msgs_count={len(result.get('msgs', []))}, keys={list(result.keys())}")
            errcode = result.get("errcode")
            if errcode is not None and errcode != 0:
                poll_weixin_error = f"API error: code={errcode}, msg={result.get('errmsg', '')}"
                log("WEIXIN", poll_weixin_error)
                time.sleep(5)
                continue
            new_buf = result.get("get_updates_buf", "")
            if new_buf:
                sync_buf = new_buf
            new_base = result.get("baseurl", "")
            if new_base:
                ilink_base = new_base
            msgs = result.get("msgs", []) or []
            for msg in msgs:
                msg_id = str(msg.get("msgid", msg.get("id", "")))
                if msg_id and msg_id in processed_ids:
                    continue
                if msg_id:
                    processed_ids.add(msg_id)
                if len(processed_ids) > 1000:
                    processed_ids.clear()
                text = ""
                for item in (msg.get("item_list", []) or []):
                    if item.get("type") == ITEM_TEXT:
                        text = item.get("text_item", {}).get("text", "")
                        break
                if not text:
                    text = msg.get("content", "")
                if not text:
                    continue
                from_user = msg.get("from_user_id", "")
                if from_user:
                    AUTHORIZED_OPENIDS.add(from_user)
                    try:
                        with open(AUTHORIZED_FILE, "a") as f:
                            f.write(from_user + "\n")
                        log("AUTH", f"New user: {from_user}")
                    except Exception as e:
                        log("AUTH", f"Store error: {e}")
                log("WEIXIN", f"Received: {text[:60]}")
                history = chat_history.get(from_user, [])
                reply = call_hermes_chat(text, history)
                history.append({"role": "user", "content": text})
                history.append({"role": "assistant", "content": reply})
                if len(history) > 20:
                    history = history[-20:]
                chat_history[from_user] = history
                # 持久化到 DB（保存最后一条对话）
                if from_user and reply:
                    _save_to_db(from_user, "user", text)
                    _save_to_db(from_user, "assistant", reply)
                try:
                    ct = msg.get("context_token", "")
                    sm = {"from_user_id": "", "to_user_id": from_user,
                          "client_id": f"hermes-{int(time.time())}",
                          "message_type": MSG_TYPE_BOT, "message_state": MSG_STATE_FINISH,
                          "item_list": [{"type": ITEM_TEXT, "text_item": {"text": reply}}]}
                    if ct:
                        sm["context_token"] = ct
                    ilink_post(EP_SEND_MESSAGE,
                        {"msg": sm, "base_info": {"channel_version": CHANNEL_VERSION}},
                        ilink_token)
                    log("WEIXIN", f"Reply sent: {reply[:60]}")
                except Exception as e:
                    log("WEIXIN", f"Send error: {e}")
                poll_weixin_processed += 1
        except Exception as e:
            poll_weixin_error = str(e)
            log("WEIXIN", f"Poll error: {e}")
        time.sleep(2)

# ── QR Code state ─────────────────────────────────────────────────────
qr_state = {"qrcode_value": "", "qrcode_url": "", "status": "none", "token": "", "account_id": "", "base_url": ""}

def poll_qr():
    global ilink_token, ilink_base
    qv = qr_state.get("qrcode_value", "")
    if not qv:
        return
    deadline = time.time() + 480
    while time.time() < deadline and qr_state["status"] in ("wait", "scaned"):
        try:
            r = ilink_get(f"{EP_GET_QR_STATUS}?qrcode={qv}", "")
            s = str(r.get("status", "wait"))
            if s == "scaned":
                qr_state["status"] = "scaned"
            elif s == "confirmed":
                qr_state["status"] = "confirmed"
                qr_state["token"] = str(r.get("bot_token", ""))
                qr_state["account_id"] = str(r.get("ilink_bot_id", ""))
                qr_state["base_url"] = str(r.get("baseurl", ILINK_BASE))
                ilink_token = qr_state["token"]
                ilink_base = qr_state["base_url"]
                _persist_token(ilink_token, ilink_base)
                # 更新 Space Secret（持久化，下次重启生效）
                _update_space_secret("ILINK_TOKEN", ilink_token)
                _update_space_secret("ILINK_BASE", ilink_base)
                log("QR", f"Authorized! Account: {qr_state['account_id']}")
                break
            elif s == "expired":
                qr_state["status"] = "expired"
                break
        except Exception as e:
            log("QR", f"poll error: {e}")
        time.sleep(2)

def _persist_token(token, base_url):
    # Token 只存环境变量，不存文件（Space 公开，避免泄露）
    log("TOKEN", "Token updated in memory only")

def _update_space_secret(key, value):
    """更新 Space Secret（持久化到 HF Space 环境变量）"""
    try:
        hf_token = os.environ.get("HF_TOKEN", "")
        if not hf_token:
            log("SECRET", "HF_TOKEN not set, skip space secret update")
            return
        huggingface_hub.add_space_secret(
            repo_id="avvnire/agent-data",
            key=key,
            value=value,
            token=hf_token,
        )
        log("SECRET", f"Updated space secret: {key}")
    except Exception as e:
        log("SECRET", f"Failed to update space secret {key}: {e}")
def _load_persisted_token():
    # Token 只从环境变量读取，不读文件
    global ilink_token, ilink_base
    env_token = os.environ.get("ILINK_TOKEN", "")
    if env_token:
        ilink_token = env_token
        ilink_base = os.environ.get("ILINK_BASE", ILINK_BASE)
        log("TOKEN", "Loaded token from env var")
        return True
    return False

# ── HTML Template ─────────────────────────────────────────────────────
def get_login_html(error=""):
    """返回登录页面 HTML - 使用 cookie 认证绕过 HF 代理 POST 拦截"""
    err_html = '<div class="login-error">\u5bc6\u7801\u9519\u8bef\uff0c\u8bf7\u91cd\u8bd5</div>' if error else ""
    parts = [
        '<!DOCTYPE html>\n',
        '<html lang="zh-CN">\n',
        '<head>\n',
        '<meta charset="UTF-8">\n',
        '<meta name="viewport" content="width=device-width,initial-scale=1.0">\n',
        '<title>Hermes Agent - \u767b\u5f55</title>\n',
        '<style>\n',
        '*{box-sizing:border-box;margin:0;padding:0}\n',
        'body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#0f0f23;color:#e0e0e0;height:100vh;display:flex;align-items:center;justify-content:center}\n',
        '.login-box{background:#1a1a2e;border:1px solid #333;border-radius:16px;padding:40px;width:360px;text-align:center}\n',
        '.login-box h1{font-size:22px;background:linear-gradient(90deg,#60a5fa,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:8px}\n',
        '.login-box .subtitle{font-size:13px;color:#666;margin-bottom:28px}\n',
        '.login-error{background:#3d1515;border:1px solid #6b2020;color:#f87171;padding:10px;border-radius:8px;margin-bottom:16px;font-size:13px}\n',
        'input[type=password]{width:100%;background:#12122a;border:1px solid #333;border-radius:10px;padding:14px 16px;color:#e0e0e0;font-size:16px;text-align:center;letter-spacing:4px}\n',
        'input[type=password]:focus{outline:none;border-color:#60a5fa}\n',
        'input[type=password]::placeholder{color:#444;letter-spacing:1px}\n',
        'button{width:100%;background:linear-gradient(135deg,#3b82f6,#2563eb);color:#fff;border:none;border-radius:10px;padding:14px;font-size:16px;cursor:pointer;margin-top:16px;transition:opacity .2s}\n',
        'button:hover{opacity:.9}\n',
        '</style>\n',
        '</head>\n',
        '<body>\n',
        '<div class="login-box">\n',
        '<h1>\U0001F510 Hermes Agent</h1>\n',
        '<div class="subtitle">\u8bf7\u8f93\u5165\u8bbf\u95ee\u5bc6\u7801</div>\n',
        err_html, '\n',
        '<form id="loginForm" onsubmit="return doLogin()">\n',
        '<input type="password" id="pwd" placeholder="\u8f93\u5165\u5bc6\u7801" autofocus autocomplete="off">\n',
        '<button type="submit">\u767b \u5f55</button>\n',
        '</form>\n',
        '</div>\n',
        '<script>\n',
        'async function doLogin(){\n',
        'var pwd=document.getElementById("pwd").value;\n',
        'if(!pwd)return false;\n',
        'var buf=new TextEncoder().encode(pwd);\n',
        'var hash=await crypto.subtle.digest("SHA-256",buf);\n',
        'var hex=Array.from(new Uint8Array(hash)).map(b=>b.toString(16).padStart(2,"0")).join("");\n',
        'document.cookie="auth_token="+hex+"; Path=/; SameSite=Strict; Max-Age=86400";\n',
        'window.location.reload();\n',
        'return false;\n',
        '}\n',
        '</script>\n',
        '</body>\n',
        '</html>',
    ]
    return "".join(parts)

def get_html():
    # 尝试多个路径找 template.html
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "template.html"),
        "/app/template.html",
        "/src/template.html",
        os.path.join(os.getcwd(), "template.html"),
    ]
    for p in candidates:
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    return f.read()
        except Exception:
            continue
    # fallback: 返回内嵌的最小聊天界面
    return get_embedded_html()

def get_embedded_html():
    """内嵌的聊天界面（template.html 不可用时的 fallback）"""
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Hermes Agent</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#0f0f23;color:#e0e0e0;height:100vh;display:flex;flex-direction:column}
.header{background:#1a1a3e;padding:12px 20px;border-bottom:1px solid #333}
.header h1{font-size:18px;color:#60a5fa}
.messages{flex:1;overflow-y:auto;padding:20px;display:flex;flex-direction:column;gap:12px}
.message{max-width:80%;padding:12px 16px;border-radius:12px;font-size:14px;line-height:1.6}
.message.user{background:#3b82f6;color:#fff;align-self:flex-end}
.message.assistant{background:#1e1e3f;color:#e0e0e0;align-self:flex-start;border:1px solid #333}
.input-area{padding:16px;border-top:1px solid #333;display:flex;gap:8px}
textarea{flex:1;background:#1a1a2e;border:1px solid #333;border-radius:10px;padding:12px;color:#e0e0e0;resize:none;min-height:48px}
button{background:#3b82f6;color:#fff;border:none;border-radius:10px;padding:12px 20px;cursor:pointer}
</style>
</head>
<body>
<div class="header"><h1>🤖 Hermes Agent</h1></div>
<div class="messages" id="msgs"></div>
<div class="input-area">
<textarea id="txt" placeholder="输入消息..." rows="1"></textarea>
<button onclick="send()">发送</button>
</div>
<script>
var hist=[];
function addMsg(role,text){
    var d=document.createElement("div");
    d.className="message "+role;
    d.textContent=text;
    document.getElementById("msgs").appendChild(d);
    document.getElementById("msgs").scrollTop=999999;
}
async function send(){
    var t=document.getElementById("txt").value.trim();
    if(!t)return;
    addMsg("user",t);
    document.getElementById("txt").value="";
    try{
        var r=await fetch("/api/chat",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({message:t,history:hist})});
        var d=await r.json();
        var reply=d.response||"无响应";
        addMsg("assistant",reply);
        hist.push({role:"user",content:t},{role:"assistant",content:reply});
    }catch(e){addMsg("system","错误: "+e);}
}
document.getElementById("txt").addEventListener("keydown",function(e){if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();send();}});
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        global ilink_token, ilink_base
        # ── New API endpoints ──
        if self.path == "/api/env":
            if not self._check_auth():
                self.send_json({"error": "unauthorized"}, 401)
                return
            safe_keys = ["PORT", "HERMES_HOME", "SPACE_ID", "SPACE_HOST", "ILINK_BASE", "TZ", "LANG"]
            env = {}
            for k in sorted(os.environ.keys()):
                if k in safe_keys or (k.isupper() and not any(s in k for s in ["TOKEN","SECRET","KEY","PASSWORD","HF_API"])):
                    v = os.environ[k]
                    if len(v) > 200: v = v[:200] + "..."
                    env[k] = v
            self.send_json(env)
            return
        elif self.path == "/api/cron/status":
            if not self._check_auth():
                self.send_json({"error": "unauthorized"}, 401)
                return
            self.send_json({"wechat_auto_exists": os.path.exists("/app/wechat_auto.py"), "schedule": "每天 07:00", "type": "微信公众号推文生成"})
            return
        elif self.path == "/api/agent/search":
            query = body.get("query", body.get("q", ""))
            max_r = int(body.get("max_results", 5))
            if not query:
                self.send_json({"error": "Missing query"}, 400)
                return
            self.send_json({"query": query, "results": _do_web_search(query, max_r)})
            return

        elif self.path == "/api/space/rebuild":
            if not self._check_auth():
                self.send_json({"error": "unauthorized"}, 401)
                return
            try:
                hf_tok = os.environ.get("HF_TOKEN", "")
                if hf_tok:
                    import huggingface_hub
                    huggingface_hub.add_space_secret(repo_id="avvnire/agent-data", key="REBUILD_TRIGGER", value=str(time.time()), token=hf_tok)
                    self.send_json({"success": True, "message": "Space 重构已触发，约 30-60 秒后完成"})
                else:
                    self.send_json({"success": False, "error": "HF_TOKEN未设置"})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)})
            return
        elif self.path == "/api/history/clear":
            if not self._check_auth():
                self.send_json({"error": "unauthorized"}, 401)
                return
            try:
                conn = sqlite3.connect(DB_PATH)
                conn.execute("DELETE FROM sessions")
                conn.commit()
                conn.close()
                self.send_json({"ok": True, "message": "历史已清空"})
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)})
            return
        # ── Auth check: 非 API 路径需要认证 ──
        if self.path == "/api/space/restart":
            # 需要认证
            if not self._check_auth():
                self.send_json({"error": "unauthorized"}, 401)
                return
            try:
                import huggingface_hub
                hf_token = os.environ.get("HF_TOKEN", "")
                if not hf_token:
                    self.send_json({"error": "HF_TOKEN not set"}, 500)
                    return
                # 重启 Space（通过更新一个 secret 触发重建）
                result = huggingface_hub.add_space_secret(
                    repo_id="avvnire/agent-data",
                    key="RESTART_TRIGGER",
                    value=str(time.time()),
                    token=hf_token,
                )
                self.send_json({"ok": True, "message": "Space 重启中，约 30-60 秒后恢复"})
                log("RESTART", "Space restart triggered via API")
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
            return

        # ── 功能1+2+3：文件操作 / Shell / 任务 / 记忆 ──
        if self.path.startswith("/api/agent/"):
            if not self._check_auth():
                self.send_json({"error": "unauthorized"}, 401)
                return
            parsed = _urlparse(self.path)
            subpath = parsed.path
            params = _parse_qs(parsed.query)
            # Shell 执行（GET 方式，用于 cron 触发）
            if subpath == "/api/agent/shell/exec":
                cmd = params.get("cmd", [""])[0] if params else ""
                if not cmd:
                    self.send_json({"error": "Missing cmd"})
                    return
                import subprocess
                try:
                    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
                    self.send_json({"exit_code": r.returncode, "output": r.stdout[-2000:], "error": r.stderr[-500:] if r.stderr else ""})
                except subprocess.TimeoutExpired:
                    self.send_json({"error": "timeout"})
                except Exception as e:
                    self.send_json({"error": str(e)})
                return

            # 文件列表
            if subpath == "/api/agent/files/list":
                self.send_json(_handle_file_list(params))
                return
            # 读文件（GET）
            if subpath == "/api/agent/files/read":
                self.send_json(_handle_file_read(params))
                return
            # 获取请求体（POST 用）
            def _read_body():
                length = int(self.headers.get("Content-Length", 0))
                return json.loads(self.rfile.read(length)) if length else {}
            # 写文件（POST）
            if subpath == "/api/agent/files/write":
                self.send_json(_handle_file_write(_read_body()))
                return
            # Shell 执行（POST）
            if subpath == "/api/agent/shell/exec":
                self.send_json(_handle_shell_exec(_read_body()))
                return
            # 任务提交（POST）
            if subpath == "/api/agent/task/submit":
                self.send_json(_handle_task_submit(_read_body()))
                return
            # 任务状态
            if subpath == "/api/agent/task/status":
                self.send_json(_handle_task_status(params))
                return
            # 任务列表
            if subpath == "/api/agent/task/list":
                self.send_json(_handle_task_list())
                return
            # Agent 状态（记忆+笔记+任务）
            if subpath == "/api/agent/status":
                self.send_json(_handle_agent_status())
                return
            # 记住一件事（POST）
            if subpath == "/api/agent/search":
                query = params.get("q", [""])[0] if params else ""
                max_r = int(params.get("n", ["5"])[0]) if params else 5
                if not query:
                    self.send_json({"error": "Missing q parameter"})
                    return
                self.send_json({"query": query, "results": _do_web_search(query, max_r)})
                return
            if subpath == "/api/agent/remember":
                self.send_json(_handle_agent_remember(_read_body()))
                return
            self.send_json({"error": f"Unknown: {subpath}"}, 404)
            return

        if self.path == "/robots.txt":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(security.get_robots_txt().encode())
            return

        if not self.path.startswith("/api/"):
            try:
                ua = self.headers.get("User-Agent", "")
                bad = ["curl","wget","python-requests","scrapy","bot","crawler","spider","headless","selenium","phantomjs"]
                if (not ua or any(b in ua.lower() for b in bad)) and self.path not in ("/", "/index.html", "/manifest.json", "/service-worker.js", "/robots.txt") and not self.path.startswith("/assets/"):
                    self.send_response(403)
                    self.end_headers()
                    self.wfile.write(b"Forbidden")
                    return
            except:
                pass
            _public = self.path in ("/", "/index.html", "/manifest.json", "/service-worker.js", "/robots.txt") or self.path.startswith("/assets/")
            if not _public and not self._check_auth():
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(get_login_html().encode())
                return

        if self.path == "/api/debug/token":
            import threading, os as _os
            _wx_status = "polling" if ilink_token else "waiting_auth"
            _env_ilink = _os.environ.get("ILINK_TOKEN", "NOT_SET")
            _env_hf = _os.environ.get("HF_TOKEN", "NOT_SET")
            _env_all_keys = list(_os.environ.keys())
            _env_check = _os.environ.get("RESTART_TRIGGER", "NOT_SET")
            if ilink_token and poll_weixin_error:
                _wx_status = "error"
            self.send_json({
                "ilink_token": ilink_token,
                "ilink_base": ilink_base,
                "token_len": len(ilink_token),
                "poll_thread_alive": any("poll_weixin" in t.name for t in threading.enumerate()),
                "all_threads": [t.name for t in threading.enumerate()],
                "last_poll_result": {"errcode": last_poll_result.get("errcode"), "errmsg": last_poll_result.get("errmsg"), "msgs_count": len(last_poll_result.get("msgs", []))} if isinstance(last_poll_result, dict) else {},
                "poll_weixin_error": poll_weixin_error,
                "processed_messages": poll_weixin_processed,
                "weixin": _wx_status,
                "stage": "running",
                "hf_token_set": bool(_os.environ.get("HF_TOKEN", ""))
            })
        elif self.path == "/api/health":
            self.send_json({
                "status": "ok", "stage": "running",
                "time": datetime.now().isoformat(),
                "weixin": "polling" if ilink_token else "waiting_auth",
                "has_token": bool(ilink_token),
            })
        elif self.path == "/api/status":
            import subprocess as _sp
            try:
                uptime = _sp.run(["uptime"], capture_output=True, text=True, timeout=5).stdout.strip()
            except:
                uptime = "unknown"
            try:
                df = _sp.run(["df", "-h", "/opt/data"], capture_output=True, text=True, timeout=5).stdout.strip()
            except:
                df = "unknown"
            try:
                free = _sp.run(["free", "-m"], capture_output=True, text=True, timeout=5).stdout.strip()
            except:
                free = "unknown"
            self.send_json({"uptime": uptime, "disk": df, "memory": free})

        elif self.path == "/api/known_good/save":
            try:
                import huggingface_hub as _hf
                hf_tok = os.environ.get("HF_TOKEN", "")
                if not hf_tok:
                    self.send_json({"error": "HF_TOKEN not set"}, 500)
                    return
                api = _hf.HfApi(token=hf_tok)
                info = api.repo_info("avvnire/agent-data", repo_type="space")
                sha = info.sha
                if sha:
                    kf = "/opt/data/known_good_commit.txt"
                    os.makedirs(os.path.dirname(kf), exist_ok=True)
                    with open(kf, "w") as f:
                        f.write(sha)
                    api.create_branch(repo_id="avvnire/agent-data", repo_type="space", branch="known-good", revision=sha, exist_ok=True)
                    self.send_json({"ok": True, "message": "版本已固化: " + sha[:12]})
                else:
                    self.send_json({"error": "no sha"})
            except Exception as e:
                self.send_json({"error": str(e)})
            return

        elif self.path == "/api/known_good/restore":
            try:
                hf_tok = os.environ.get("HF_TOKEN", "")
                if not hf_tok:
                    self.send_json({"error": "HF_TOKEN not set"}, 500)
                    return
                kf = "/opt/data/known_good_commit.txt"
                if not os.path.exists(kf):
                    self.send_json({"error": "没有固化版本，请先在 Terminal 面板点击固化版本按钮"}, 400)
                    return
                with open(kf, "r") as f:
                    sha = f.read().strip()
                if not sha or len(sha) < 7:
                    self.send_json({"error": "固化版本数据无效"}, 400)
                    return
                import ssl as _ssl
                _ctx = _ssl.create_default_context()
                _ctx.check_hostname = False
                _ctx.verify_mode = _ssl.CERT_NONE
                # Use huggingface_hub create_branch which handles endpoint correctly
                try:
                    import huggingface_hub as _hf
                    _api = _hf.HfApi(token=hf_tok, endpoint="https://hf-mirror.com")
                    _api.create_branch(repo_id="avvnire/agent-data", repo_type="space", branch="main", revision=sha, exist_ok=True)
                except Exception:
                    # Fallback: use raw API with redirect handling
                    import http.client as _hc
                    _conn = _hc.HTTPSConnection("hf-mirror.com", context=_ctx)
                    _payload = json.dumps({"startingPoint": sha}).encode()
                    _conn.request("POST", "/api/spaces/avvnire/agent-data/branch/main",
                        body=_payload,
                        headers={"Authorization": "Bearer " + hf_tok, "Content-Type": "application/json"})
                    _resp = _conn.getresponse()
                    _body = _resp.read()
                    _conn.close()
                    if _resp.status >= 400:
                        self.send_json({"error": "API error " + str(_resp.status) + ": " + _body.decode()[:200]}, 500)
                        return
                self.send_json({"ok": True, "message": "版本恢复至: " + sha[:12] + "，Space 将自动重构，约30-60秒后生效"})
            except Exception as e:
                self.send_json({"error": str(e)})
            return

        elif self.path.startswith("/api/history"):
            openid = self.path.split("?openid=", 1)[1] if "?openid=" in self.path else ""
            conn = sqlite3.connect(DB_PATH)
            cutoff = time.time() - 30 * 86400
            rows = conn.execute(
                "SELECT role, content, timestamp FROM sessions "
                "WHERE openid = ? AND timestamp >= ? "
                "ORDER BY timestamp ASC", (openid, cutoff))
            history = [{"role": r[0], "content": r[1], "time": r[2]} for r in rows.fetchall()]
            conn.close()
            self.send_json({"history": history, "count": len(history)})
            return
        elif self.path == "/api/openids":
            openids = []
            if os.path.exists(AUTHORIZED_FILE):
                with open(AUTHORIZED_FILE, "r") as f:
                    openids = [l.strip() for l in f.readlines() if l.strip()]
            self.send_json({"openids": openids, "count": len(openids)})
        elif self.path == "/api/history":
            openid = self.path.split("?openid=", 1)[1] if "?" in self.path else ""
            conn = sqlite3.connect(DB_PATH)
            cutoff = time.time() - 30 * 86400
            rows = conn.execute(
                "SELECT role, content, timestamp FROM sessions "
                "WHERE openid = ? AND timestamp >= ? "
                "ORDER BY timestamp ASC", (openid, cutoff))
            history = [{"role": r[0], "content": r[1], "time": r[2]} for r in rows.fetchall()]
            conn.close()
            self.send_json({"history": history, "count": len(history)})
        elif self.path == "/api/qr/confirm":
            # 扫码确认后：保存 token + 更新 Space Secret + 触发重启
            if not self._check_auth():
                self.send_json({"error": "unauthorized"}, 401)
                return
            _token = qr_state.get("token", "")
            _base = qr_state.get("base_url", ILINK_BASE)
            if not _token:
                self.send_json({"error": "no token, 请先生成二维码并扫码"}, 400)
                return
            # 更新内存
            ilink_token = _token
            ilink_base = _base
            # 更新 Space Secret
            _update_space_secret("ILINK_TOKEN", ilink_token)
            _update_space_secret("ILINK_BASE", ilink_base)
            # 触发重启
            try:
                hf_token = os.environ.get("HF_TOKEN", "")
                if hf_token:
                        huggingface_hub.add_space_secret(
                        repo_id="avvnire/agent-data",
                        key="RESTART_TRIGGER",
                        value=str(time.time()),
                        token=hf_token,
                        )
                        self.send_json({"ok": True, "message": "授权成功！Space 正在重启，约 30-60 秒后恢复。重启后 token 永久生效。"})
                        log("QR", "Token saved + space restart triggered")
                else:
                    self.send_json({"ok": True, "warning": "Token 已保存到内存，但 HF_TOKEN 未设置，无法触发重启。请手动重启 Space。"})
            except Exception as e:
                self.send_json({"ok": True, "warning": f"Token 保存成功，但重启失败: {e}"})
            return

        elif self.path == "/api/qr/status":
            st = {"none": "等待生成二维码", "wait": "等待扫码...", "scaned": "已扫码，请在微信确认...", "confirmed": "授权成功！", "expired": "二维码已过期"}
            self.send_json({"status": qr_state["status"], "status_text": st.get(qr_state["status"], qr_state["status"])})
        elif self.path == "/manifest.json":
            self.send_response(200)
            self.send_header("Content-Type", "application/manifest+json; charset=utf-8")
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            try:
                with open("/app/manifest.json", "rb") as f:
                    self.wfile.write(f.read())
            except:
                self.wfile.write(b"{}")
            return
        elif self.path == "/service-worker.js":
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                with open("/app/service-worker.js", "rb") as f:
                    self.wfile.write(f.read())
            except:
                pass
            return
        elif self.path.startswith("/assets/"):
            _asset_path = self.path.split("?")[0]
            safe_path = "/app/" + _asset_path.lstrip("/")
            if os.path.isfile(safe_path):
                ct = "application/octet-stream"
                if safe_path.endswith(".png"): ct = "image/png"
                elif safe_path.endswith(".jpg"): ct = "image/jpeg"
                elif safe_path.endswith(".svg"): ct = "image/svg+xml"
                self.send_response(200)
                self.send_header("Content-Type", ct)
                self.send_header("Cache-Control", "public, max-age=31536000")
                self.end_headers()
                with open(safe_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404)
            return
        elif self.path == "/admin" or self.path == "/admin/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(get_html().encode())
            return
        elif self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            try:
                security.add_security_headers(self)
            except:
                pass
            self.end_headers()
            try:
                with open("/app/ziwei.html", "rb") as f:
                    self.wfile.write(f.read())
            except:
                self.wfile.write(get_html().encode())
            return
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            try:
                security.add_security_headers(self)
            except:
                pass
            self.end_headers()
            try:
                with open("/app/ziwei.html", "rb") as f:
                    self.wfile.write(f.read())
            except:
                self.wfile.write(get_html().encode())

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if self.path == "/api/chat":
            try:
                history = body.get("history", [])
                msg = body.get("message", "")
                search_result = _maybe_web_search(msg)
                if search_result is not None:
                    msg = msg + "\n\n[实时搜索结果]\n" + search_result + "\n\n请基于以上搜索结果回答用户问题。"
                response = call_hermes_chat(msg, history)
                self.send_json({"response": response})
            except Exception as e:
                log("CHAT", "Error: " + str(e))
                self.send_json({"response": "处理失败: " + str(e)}, status=500)

        elif self.path == "/api/qr/generate":
            try:
                qr_resp = ilink_get(f"{EP_GET_BOT_QR}?bot_type=3", "")
                qv = str(qr_resp.get("qrcode", ""))
                if not qv:
                    self.send_json({"error": "获取二维码失败", "raw": qr_resp})
                    return
                # 生成二维码图片（base64 PNG）
                import qrcode, io, base64 as _b64
                _url = f"https://liteapp.weixin.qq.com/q/7GiQu1?qrcode={qv}&bot_type=3"
                _qr = qrcode.make(_url)
                _buf = io.BytesIO()
                _qr.save(_buf, format="PNG")
                _img_b64 = _b64.b64encode(_buf.getvalue()).decode()
                qr_state["qrcode_value"] = qv
                qr_state["qrcode_url"] = _url
                qr_state["qrcode_img"] = _img_b64
                qr_state["status"] = "wait"
                threading.Thread(target=poll_qr, daemon=True).start()
                self.send_json({"qrcode": qv, "qrcode_url": _url, "qrcode_img": _img_b64})
            except Exception as e:
                self.send_json({"error": str(e)})
        elif self.path == "/api/agent/shell/exec":
            cmd = body.get("cmd", "")
            if not cmd:
                self.send_json({"error": "Missing cmd"})
                return
            import subprocess
            try:
                r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
                self.send_json({"exit_code": r.returncode, "stdout": r.stdout[-5000:], "stderr": r.stderr[-1000:] if r.stderr else ""})
            except subprocess.TimeoutExpired:
                self.send_json({"error": "Command timed out after 60s"})
            except Exception as e:
                self.send_json({"error": str(e)})
            return
        elif self.path == "/api/history/clear":
            try:
                conn = sqlite3.connect(DB_PATH)
                conn.execute("DELETE FROM sessions")
                conn.commit()
                conn.close()
                self.send_json({"ok": True})
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)})
            return
        elif self.path == "/api/space/rebuild":
            try:
                hf_tok = os.environ.get("HF_TOKEN", "")
                if hf_tok:
                    import huggingface_hub
                    huggingface_hub.add_space_secret(repo_id="avvnire/agent-data", key="REBUILD_TRIGGER", value=str(time.time()), token=hf_tok)
                    self.send_json({"success": True, "message": "Space 重构已触发"})
                else:
                    self.send_json({"success": False, "error": "HF_TOKEN未设置"})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)})
            return

        elif self.path == "/api/known_good/restore":
            try:
                hf_tok = os.environ.get("HF_TOKEN", "")
                if not hf_tok:
                    self.send_json({"error": "HF_TOKEN not set"}, 500)
                    return
                kf = "/opt/data/known_good_commit.txt"
                if not os.path.exists(kf):
                    self.send_json({"error": "没有固化版本，请先在 Terminal 面板点击固化版本按钮"}, 400)
                    return
                with open(kf, "r") as f:
                    sha = f.read().strip()
                if not sha or len(sha) < 7:
                    self.send_json({"error": "固化版本数据无效"}, 400)
                    return
                import ssl as _ssl
                _ctx = _ssl.create_default_context()
                _ctx.check_hostname = False
                _ctx.verify_mode = _ssl.CERT_NONE
                # Use huggingface_hub create_branch which handles endpoint correctly
                try:
                    import huggingface_hub as _hf
                    _api = _hf.HfApi(token=hf_tok, endpoint="https://hf-mirror.com")
                    _api.create_branch(repo_id="avvnire/agent-data", repo_type="space", branch="main", revision=sha, exist_ok=True)
                except Exception:
                    # Fallback: use raw API with redirect handling
                    import http.client as _hc
                    _conn = _hc.HTTPSConnection("hf-mirror.com", context=_ctx)
                    _payload = json.dumps({"startingPoint": sha}).encode()
                    _conn.request("POST", "/api/spaces/avvnire/agent-data/branch/main",
                        body=_payload,
                        headers={"Authorization": "Bearer " + hf_tok, "Content-Type": "application/json"})
                    _resp = _conn.getresponse()
                    _body = _resp.read()
                    _conn.close()
                    if _resp.status >= 400:
                        self.send_json({"error": "API error " + str(_resp.status) + ": " + _body.decode()[:200]}, 500)
                        return
                self.send_json({"ok": True, "message": "版本恢复至: " + sha[:12] + "，Space 将自动重构，约30-60秒后生效"})
            except Exception as e:
                self.send_json({"error": str(e)})
            return

        else:
            self.send_json({"error": "not found"}, 404)

    def _check_auth(self):
        """验证 cookie + 速率限制"""
        try:
            allowed, retry = security.check_rate_limit(self, self.path)
            if not allowed:
                self.send_json({"error": "rate_limited", "retry_after": retry}, 429)
                return False
        except Exception as e:
            log("AUTH", "Rate limit error: " + str(e))
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            part = part.strip()
            if part.startswith("auth_token="):
                token = part[len("auth_token="):]
                if token == SITE_PASSWORD_HASH:
                    return True
        return False

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        try:
            security.add_security_headers(self)
        except:
            pass
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def log_message(self, *a):
        pass

# ── Main ──────────────────────────────────────────────────────────────

# ══════════════════════════════════════════════════════════════
# Agent 增强功能：文件操作 + Shell 执行 + 多步骤任务 + 持久记忆
# ══════════════════════════════════════════════════════════════

import re as _re, subprocess as _subprocess, traceback as _traceback
from urllib.parse import urlparse as _urlparse, parse_qs as _parse_qs

# ── 安全配置 ────────────────────────────────────────────────────
SAFE_PATH_PREFIXES = ["/opt/data", "/app", "/tmp"]
SHELL_WHITELIST = [
    "ls", "cat", "head", "tail", "grep", "find", "wc", "du", "df",
    "ps", "top", "free", "uptime", "date", "whoami", "pwd",
    "pip list", "pip show", "python --version", "python3 --version",
    "mkdir", "touch", "cp", "mv", "rm", "chmod", "chown",
    "git status", "git log", "git diff",
]
AGENT_STATE_FILE = os.path.join(HERMES_HOME, "agent_state.json")
AGENT_NOTES_DIR = os.path.join(HERMES_HOME, "notes")

# ── 持久化工作记忆 ──────────────────────────────────────────────
def _load_agent_state():
    """加载 Agent 工作记忆"""
    try:
        if os.path.exists(AGENT_STATE_FILE):
            with open(AGENT_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"tasks": [], "notes": [], "last_actions": []}

def _save_agent_state(state):
    """保存 Agent 工作记忆"""
    try:
        os.makedirs(os.path.dirname(AGENT_STATE_FILE), exist_ok=True)
        with open(AGENT_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log("STATE", f"Failed to save state: {e}")

def _append_note(text, category="general"):
    """追加笔记到每日文件"""
    try:
        os.makedirs(AGENT_NOTES_DIR, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        note_file = os.path.join(AGENT_NOTES_DIR, f"{today}.md")
        timestamp = datetime.now().strftime("%H:%M:%S")
        with open(note_file, "a", encoding="utf-8") as f:
            f.write(f"\n## [{timestamp}] {category}\n{text}\n")
        log("NOTE", f"Appended to {note_file}")
    except Exception as e:
        log("NOTE", f"Failed to append note: {e}")

def _load_today_notes():
    """加载今天的笔记"""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        note_file = os.path.join(AGENT_NOTES_DIR, f"{today}.md")
        if os.path.exists(note_file):
            with open(note_file, "r", encoding="utf-8") as f:
                return f.read()
    except Exception:
        pass
    return ""

# ── 文件操作 ────────────────────────────────────────────────────
def _safe_path(path):
    """验证路径安全（防止目录遍历）"""
    if not path:
        return None
    real = os.path.realpath(path)
    for prefix in SAFE_PATH_PREFIXES:
        if real.startswith(os.path.realpath(prefix)):
            return real
    return None

def _handle_file_list(params):
    """列出目录内容"""
    path = params.get("path", ["/opt/data"])[0]
    safe = _safe_path(path)
    if not safe:
        return {"error": f"Path not allowed: {path}"}
    if not os.path.exists(safe):
        return {"error": f"Path not found: {safe}"}
    if os.path.isfile(safe):
        stat = os.stat(safe)
        return {
            "type": "file",
            "path": safe,
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        }
    items = []
    for item in sorted(os.listdir(safe)):
        full = os.path.join(safe, item)
        try:
            stat = os.stat(full)
            items.append({
                "name": item,
                "type": "dir" if os.path.isdir(full) else "file",
                "size": stat.st_size if os.path.isfile(full) else 0,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
        except Exception:
            pass
    return {"type": "dir", "path": safe, "items": items}

def _handle_file_read(params):
    """读取文件内容"""
    path = params.get("path", [None])[0]
    if not path:
        return {"error": "Missing path parameter"}
    safe = _safe_path(path)
    if not safe:
        return {"error": f"Path not allowed: {path}"}
    if not os.path.exists(safe):
        return {"error": f"File not found: {safe}"}
    if os.path.getsize(safe) > 1024 * 1024:  # 1MB limit
        return {"error": "File too large (>1MB)"}
    try:
        with open(safe, "r", encoding="utf-8", errors="replace") as f:
            file_content = f.read()
        return {"path": safe, "content": file_content, "size": len(file_content)}
    except Exception as e:
        return {"error": str(e)}

def _handle_file_write(body):
    """写入文件"""
    path = body.get("path", "")
    file_content = body.get("content", "")
    append = body.get("append", False)
    if not path:
        return {"error": "Missing path"}
    safe = _safe_path(path)
    if not safe:
        return {"error": f"Path not allowed: {path}"}
    try:
        os.makedirs(os.path.dirname(safe), exist_ok=True)
        mode = "a" if append else "w"
        with open(safe, mode, encoding="utf-8") as f:
            f.write(file_content)
        return {"ok": True, "path": safe, "size": len(file_content)}
    except Exception as e:
        return {"error": str(e)}

# ── Shell 执行 ──────────────────────────────────────────────────
def _is_shell_safe(cmd):
    """检查命令是否在白名单中"""
    cmd_stripped = cmd.strip()
    for pattern in SHELL_WHITELIST:
        if cmd_stripped.startswith(pattern):
            return True
    return False

def _handle_shell_exec(body):
    """执行 shell 命令（白名单限制）"""
    cmd = body.get("cmd", "")
    timeout = min(int(body.get("timeout", 30)), 120)
    if not cmd:
        return {"error": "Missing cmd"}
    if not _is_shell_safe(cmd):
        try:
            if not security.is_shell_safe(cmd):
                return {"error": "Command blocked by security policy", "cmd": cmd[:100]}
        except:
            pass
        return {
            "error": f"Command not in whitelist: {cmd}",
            "whitelist": SHELL_WHITELIST,
        }
    try:
        result = _subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": result.stdout[:5000],
            "stderr": result.stderr[:2000],
        }
    except _subprocess.TimeoutExpired:
        return {"error": f"Command timed out after {timeout}s"}
    except Exception as e:
        return {"error": str(e)}

# ── 多步骤任务处理 ──────────────────────────────────────────────
_task_store = {}  # task_id -> {status, steps, result, created}

def _handle_task_submit(body):
    """提交多步骤任务"""
    task_id = secrets.token_hex(8)
    description = body.get("description", "")
    if not description:
        return {"error": "Missing description"}
    _task_store[task_id] = {
        "id": task_id,
        "description": description,
        "status": "pending",
        "steps": [],
        "result": None,
        "created": time.time(),
        "updated": time.time(),
    }
    # 异步执行任务
    t = threading.Thread(target=_execute_task, args=(task_id, description), daemon=True)
    t.start()
    return {"task_id": task_id, "status": "pending"}

def _handle_task_status(params):
    """查询任务状态"""
    task_id = params.get("id", [None])[0]
    if not task_id or task_id not in _task_store:
        return {"error": f"Task not found: {task_id}"}
    task = _task_store[task_id]
    return {
        "id": task["id"],
        "description": task["description"],
        "status": task["status"],
        "steps": task["steps"],
        "result": task["result"],
        "elapsed": round(time.time() - task["created"], 1),
    }

def _handle_task_list():
    """列出所有任务"""
    tasks = []
    for tid, t in _task_store.items():
        tasks.append({
            "id": tid,
            "description": t["description"][:50],
            "status": t["status"],
            "elapsed": round(time.time() - t["created"], 1),
        })
    return {"tasks": sorted(tasks, key=lambda x: x["elapsed"])}

def _execute_task(task_id, description):
    """执行多步骤任务（在后台线程中运行）"""
    task = _task_store.get(task_id)
    if not task:
        return
    task["status"] = "running"
    task["updated"] = time.time()
    try:
        # 步骤1：理解任务
        _add_step(task, "理解任务", f"分析任务: {description}")
        
        # 步骤2：根据任务类型执行
        result = _dispatch_task(description, task)
        
        # 步骤3：汇总
        task["status"] = "completed"
        task["result"] = result
        _add_step(task, "完成", "任务执行完毕")
        
        # 保存到笔记
        _append_note(f"任务完成 [{task_id}]: {description}\n结果: {str(result)[:200]}", "task")
        
    except Exception as e:
        task["status"] = "failed"
        task["result"] = str(e)
        _add_step(task, "错误", str(e))
    finally:
        task["updated"] = time.time()

def _add_step(task, name, detail):
    task["steps"].append({
        "name": name,
        "detail": detail[:200],
        "time": datetime.now().strftime("%H:%M:%S"),
    })

def _dispatch_task(description, task):
    """根据任务描述分发执行"""
    desc_lower = description.lower()
    
    # 文件相关任务
    if "列出" in description or "list" in desc_lower or "目录" in description:
        path = _extract_path(description) or "/opt/data"
        _add_step(task, "执行", f"列出目录: {path}")
        return _handle_file_list({"path": [path]})
    
    # 读取文件
    if "读取" in description or "read" in desc_lower or "查看" in description:
        path = _extract_path(description)
        if path:
            _add_step(task, "执行", f"读取文件: {path}")
            return _handle_file_read({"path": [path]})
        return {"error": "无法确定要读取的文件路径"}
    
    # 执行命令
    if "执行" in description or "运行" in description or "exec" in desc_lower:
        cmd = _extract_command(description)
        if cmd:
            _add_step(task, "执行", f"运行命令: {cmd}")
            return _handle_shell_exec({"cmd": cmd})
        return {"error": "无法确定要执行的命令"}
    
    # 状态检查
    if "状态" in description or "status" in desc_lower:
        _add_step(task, "执行", "检查系统状态")
        return _handle_shell_exec({"cmd": "uptime && df -h /opt/data && free -m"})
    
    # 默认：用 LLM 处理
    _add_step(task, "执行", "使用 LLM 处理任务")
    return {"response": call_llm_fallback(description)}

def _extract_path(text):
    """从文本中提取文件路径"""
    m = _re.search(r'(/[a-zA-Z0-9_./-]+)', text)
    return m.group(1) if m else None

def _extract_command(text):
    """从文本中提取命令"""
    m = _re.search(r'[:：]\s*([a-z][a-z0-9 _-]+)', text)
    return m.group(1).strip() if m else None

# ── Agent 状态 API ──────────────────────────────────────────────
def _handle_agent_status():
    """返回 Agent 完整状态"""
    state = _load_agent_state()
    today_notes = _load_today_notes()
    return {
        "state": state,
        "today_notes": today_notes[:1000],
        "notes_dir": AGENT_NOTES_DIR,
        "notes_files": os.listdir(AGENT_NOTES_DIR) if os.path.exists(AGENT_NOTES_DIR) else [],
        "active_tasks": len([t for t in _task_store.values() if t["status"] in ("pending", "running")]),
        "completed_tasks": len([t for t in _task_store.values() if t["status"] == "completed"]),
    }

def _handle_agent_remember(body):
    """让 Agent 记住一件事"""
    text = body.get("text", "")
    category = body.get("category", "general")
    if not text:
        return {"error": "Missing text"}
    _append_note(text, category)
    state = _load_agent_state()
    state["notes"].append({"text": text[:100], "category": category, "time": time.time()})
    state["notes"] = state["notes"][-50:]  # 保留最近50条
    _save_agent_state(state)
    return {"ok": True, "message": "已记住"}


def main():
    log("MAIN", "=== Hermes Agent Web UI ===")
    log("MAIN", f"HERMES_HOME={HERMES_HOME} PORT={PORT}")
    bootstrap_config()
    cli = find_hermes_cli()
    log("MAIN", f"Hermes CLI: {cli or 'not found (using LLM fallback)'}")
    _load_persisted_token()
    def _safe_thread(fn, name):
        def wrapper():
            while True:
                try:
                    fn()
                    break
                except Exception as e:
                    log("THREAD", f"{name} crashed: {e}, restart in 5s...")
                    time.sleep(5)
        return wrapper
    threading.Thread(target=_safe_thread(poll_weixin, "poll_weixin"), daemon=True).start()
    ThreadingHTTPServer.daemon_threads = True
    while True:
        try:
            server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
            log("MAIN", f"Server running on port {PORT}")
            server.serve_forever()
        except KeyboardInterrupt:
            try: server.shutdown()
            except: pass
            break
        except Exception as e:
            log("MAIN", f"Server crashed: {e}, restarting in 3s...")
            time.sleep(3)



# ── 定时任务：每天 7:00 自动生成推文 ───────────────────────────────────
_auto_run_date = None
_auto_run_lock = False

def _auto_weixin_thread():
    global _auto_run_date, _auto_run_lock
    while True:
        try:
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            # 每天北京时间 07:00 触发
            if now.hour == 7 and now.minute < 5 and _auto_run_date != today and not _auto_run_lock:
                _auto_run_lock = True
                _auto_run_date = today
                log("CRON", "Auto wechat article generation triggered")
                try:
                    import subprocess
                    result = subprocess.run(
                        ["python3", "/app/wechat_auto.py"],
                        capture_output=True, text=True, timeout=600
                    )
                    log("CRON", f"Auto generation done. stdout: {result.stdout[-200:] if result.stdout else 'empty'}")
                    if result.returncode == 0:
                        # 通知成功
                        try:
                            out = result.stdout or ""
                            title = ""
                            media_id = ""
                            for line in out.splitlines():
                                if "[TOPIC]" in line:
                                    title = line.split("] ", 1)[-1] if "] " in line else ""
                                if "Draft OK:" in line:
                                    media_id = line.split("Draft OK:", 1)[-1].strip() if "Draft OK:" in line else ""
                            msg = "\u2705 \u63a8\u6587\u5df2\u751f\u6210\n\U0001F4D0 \u6807\u9898: " + (title or "\u672a\u77e5") + "\n\U0001F4E6 media_id: " + (media_id[:40] if media_id else "\u672a\u77e5") + "\n\U0001F4CD \u8349\u7a3f\u5df2\u4e0a\u4f20\u5fae\u4fe1\u516c\u4f17\u53f7\u540e\u53f0\u8349\u7a3f\u7bb1"
                            subprocess.run(["python3", "/app/notify_session.py", msg], capture_output=True, text=True, timeout=30)
                            log("CRON", "Notification sent")
                        except Exception as ne:
                            log("CRON", f"Notification error: {ne}")
                    else:
                        err_msg = result.stderr[-200:] if result.stderr else "unknown"
                        log("CRON", f"Error: {err_msg}")
                        try:
                            msg = "\u274c \u63a8\u6587\u751f\u6210\u5931\u8d25\n\u9519\u8bef: " + err_msg
                            subprocess.run(["python3", "/app/notify_session.py", msg], capture_output=True, text=True, timeout=30)
                        except:
                            pass
                except Exception as e:
                    log("CRON", f"Auto generation error: {e}")
                    try:
                        msg = "\u274c \u63a8\u6587\u751f\u6210\u5f02\u5e38\n\u9519\u8bef: " + str(e)
                        subprocess.run(["python3", "/app/notify_session.py", msg], capture_output=True, text=True, timeout=30)
                    except:
                        pass
                finally:
                    _auto_run_lock = False
        except Exception as e:
            log("CRON", f"Cron thread error: {e}")
        time.sleep(30)  # 每30秒检查一次

_auto_thread = threading.Thread(target=_auto_weixin_thread, daemon=True, name="auto_weixin")
_auto_thread.start()
log("CRON", "Auto wechat article timer started")

if __name__ == "__main__":
    main()

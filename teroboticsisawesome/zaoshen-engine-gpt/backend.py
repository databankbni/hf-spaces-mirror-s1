#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""造神引擎 SaaS —— 行銷作戰包、統一認領池與全自動發布後端(FastAPI)。
內容中心產生整套行銷圖文；官方或夥伴認領後，按預設目標與排程自動發布。
啟動:uvicorn backend:app --host 127.0.0.1 --port 8800
"""
import os, sqlite3, json, re, secrets, threading, time, io, zipfile, shutil, tempfile
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
import ai
import auth

ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "saas.db"
UPLOADS = ROOT / "data" / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)


# ---------- HF Space → Facebook Graph 連線強化(0721 修 ReadTimeout)----------
# HF Space 的 IPv6 出口常半死:requests 走 IPv6 會「連得上卻讀不到回應」→ ReadTimeout。
# 強制 DNS 只回 IPv4,讓所有對外連線走 IPv4。
try:
    import socket as _socket
    import urllib3.util.connection as _u3conn
    _u3conn.allowed_gai_family = lambda: _socket.AF_INET
    print("NETWORK force IPv4 for outbound (HF egress fix)", flush=True)
except Exception as _ipv4_exc:
    print(f"NETWORK IPv4-force skipped: {_ipv4_exc}", flush=True)

GRAPH = "https://graph.facebook.com/v23.0"


def public_media_url(name: str) -> str:
    """FB 可公開抓取的圖片網址(= 本 Space 對外網址 + /media/)。抓不到 host 回空字串。"""
    if not name:
        return ""
    host = os.environ.get("SPACE_HOST") or os.environ.get("ZAOSHEN_PUBLIC_HOST") or ""
    if not host:
        sid = os.environ.get("SPACE_ID", "")
        if sid and "/" in sid:
            host = sid.replace("/", "-") + ".hf.space"
    if not host:
        return ""
    if not host.startswith("http"):
        host = "https://" + host
    return f"{host.rstrip('/')}/media/{Path(name).name}"


def restore_space_database():
    """開機還原正式 SQLite:Cloud Run 走 GCS,HF Space 走私有 Dataset。"""
    bucket = os.environ.get("ZAOSHEN_GCS_BUCKET")
    if bucket:
        try:
            from google.cloud import storage
            blob = storage.Client().bucket(bucket).blob("saas.db")
            if blob.exists():
                DB.parent.mkdir(parents=True, exist_ok=True)
                blob.download_to_filename(str(DB))
                print("DATABASE restored from GCS", flush=True)
            else:
                print("DATABASE GCS empty; fresh start", flush=True)
        except Exception as exc:
            print(f"DATABASE GCS restore skipped: {exc}", flush=True)
        return
    repo = os.environ.get("ZAOSHEN_DATA_REPO")
    token = os.environ.get("HF_TOKEN")
    if not os.environ.get("SPACE_ID") or not repo or not token:
        return
    try:
        from huggingface_hub import hf_hub_download
        source = hf_hub_download(repo, "saas.db", repo_type="dataset", token=token)
        DB.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, DB)
        print("DATABASE restored from persistent Dataset", flush=True)
    except Exception as exc:
        print(f"DATABASE restore skipped: {exc}", flush=True)


restore_space_database()

KIND_LABEL = {"page": "粉專", "group": "社團", "kol_dm": "KOL私訊", "reply": "留言回覆範本"}
PHASE_LABEL = {"trend": "種趨勢", "reveal": "揭曉", "countdown": "倒數", "checkin": "打卡", "manual": "自由新增",
               "anchor": "官方主貼文", "kol": "邀約", "reply": "回覆庫", "grouppost": "社團貼文", "pitch": "私訊/投稿"}


def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c


def init_db():
    _is_prod = os.environ.get("SPACE_ID") or os.environ.get("ZAOSHEN_GCS_BUCKET")
    if _is_prod and (not os.environ.get("ZAOSHEN_BOOTSTRAP_PASSWORD") or not os.environ.get("SESSION_SECRET")):
        raise RuntimeError("正式環境必須設定 ZAOSHEN_BOOTSTRAP_PASSWORD 與 SESSION_SECRET，拒絕使用本機測試密碼啟動")
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS campaigns(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, hero TEXT, selling_points TEXT,
      when_where TEXT, audience TEXT, tone TEXT, incentive TEXT,
      copy_json TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS queue(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      campaign_id INTEGER,
      kind TEXT,            -- page/group/kol_dm/reply
      phase TEXT,           -- trend/reveal/countdown/checkin/kol/reply
      target_name TEXT,     -- 粉專 / 社團名 / KOL名
      target_url TEXT,
      scheduled_date TEXT,  -- 節拍排程日 YYYY-MM-DD
      body TEXT,
      image_hint TEXT,
      status TEXT DEFAULT 'draft',   -- draft/approved/sent/skipped
      created_at TEXT, approved_at TEXT, sent_at TEXT, note TEXT);
    CREATE TABLE IF NOT EXISTS delivery_jobs(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      queue_id INTEGER NOT NULL,
      method TEXT NOT NULL,
      state TEXT NOT NULL DEFAULT 'queued',
      worker_id TEXT,
      attempts INTEGER NOT NULL DEFAULT 0,
      requested_at TEXT NOT NULL,
      started_at TEXT, finished_at TEXT,
      external_id TEXT, external_url TEXT,
      screenshot_path TEXT, error TEXT,
      FOREIGN KEY(queue_id) REFERENCES queue(id));
    CREATE INDEX IF NOT EXISTS ix_delivery_jobs_state ON delivery_jobs(state, id);
    CREATE INDEX IF NOT EXISTS ix_queue_campaign_status ON queue(campaign_id, status);
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
      display_name TEXT NOT NULL, password_hash TEXT NOT NULL,
      role TEXT NOT NULL DEFAULT 'activity_partner', active INTEGER NOT NULL DEFAULT 1,
      must_change_password INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS activity_members(
      campaign_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
      member_role TEXT NOT NULL DEFAULT 'co_manager', active INTEGER NOT NULL DEFAULT 1,
      PRIMARY KEY(campaign_id,user_id));
    CREATE TABLE IF NOT EXISTS pairing_codes(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
      code_hash TEXT UNIQUE NOT NULL, expires_at TEXT NOT NULL, used_at TEXT, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS devices(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
      name TEXT NOT NULL, token_hash TEXT UNIQUE NOT NULL, rpa_version TEXT NOT NULL,
      os_version TEXT DEFAULT '', state TEXT NOT NULL DEFAULT 'offline', current_job TEXT DEFAULT '',
      last_error TEXT DEFAULT '', last_seen TEXT, created_at TEXT NOT NULL, revoked_at TEXT);
    CREATE TABLE IF NOT EXISTS audit_logs(
      id INTEGER PRIMARY KEY AUTOINCREMENT, actor_user_id INTEGER,
      action TEXT NOT NULL, entity_type TEXT DEFAULT '', entity_id TEXT DEFAULT '',
      detail_json TEXT DEFAULT '{}', created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS ix_devices_last_seen ON devices(last_seen);
    """)
    campaign_cols = {r[1] for r in c.execute("PRAGMA table_info(campaigns)")}
    if "contact_info" not in campaign_cols:
        c.execute("ALTER TABLE campaigns ADD COLUMN contact_info TEXT DEFAULT ''")
    if "package_created_at" not in campaign_cols:
        c.execute("ALTER TABLE campaigns ADD COLUMN package_created_at TEXT")
        c.execute("""UPDATE campaigns SET package_created_at=(
            SELECT min(q.created_at) FROM queue q
            WHERE q.campaign_id=campaigns.id AND q.source_queue_id IS NULL)
            WHERE EXISTS(SELECT 1 FROM queue q WHERE q.campaign_id=campaigns.id AND q.source_queue_id IS NULL)""")
    queue_cols = {r[1] for r in c.execute("PRAGMA table_info(queue)")}
    for column, ddl in (
        ("claim_limit", "INTEGER NOT NULL DEFAULT 3"),
        ("source_queue_id", "INTEGER"),
        ("claimed_by", "INTEGER"),
        ("claimed_at", "TEXT"),
    ):
        if column not in queue_cols:
            c.execute(f"ALTER TABLE queue ADD COLUMN {column} {ddl}")
    # 舊版認領資料若沒有帶到目標網址，從中央原稿補回，
    # 避免夥伴認領後還要自己搜尋發布位置。
    c.execute("""UPDATE queue
        SET target_url=(SELECT source.target_url FROM queue source WHERE source.id=queue.source_queue_id)
        WHERE source_queue_id IS NOT NULL AND trim(coalesce(target_url,''))=''
          AND trim(coalesce((SELECT source.target_url FROM queue source WHERE source.id=queue.source_queue_id),''))<>''""")
    # 把舊版「已認領但尚未建立工作」的資料接上新的認領即自動發布流程。
    c.execute("""INSERT INTO delivery_jobs(queue_id,method,state,requested_at)
        SELECT q.id,'local_rpa',
          'queued',coalesce(q.claimed_at,q.created_at,datetime('now'))
        FROM queue q JOIN users u ON u.id=q.claimed_by
        WHERE q.source_queue_id IS NOT NULL AND q.claimed_by IS NOT NULL AND q.status<>'sent'
          AND NOT EXISTS(SELECT 1 FROM delivery_jobs j WHERE j.queue_id=q.id)""")
    c.execute("""UPDATE queue SET status='approved',approved_at=coalesce(approved_at,claimed_at,created_at)
        WHERE source_queue_id IS NOT NULL AND claimed_by IS NOT NULL AND status='claimed'""")
    if os.environ.get("FB_PAGE_ID") and os.environ.get("FB_PAGE_TOKEN"):
        c.execute("""UPDATE delivery_jobs SET method='graph_api',state='queued',error=NULL,finished_at=NULL
            WHERE queue_id IN (SELECT id FROM queue WHERE kind='page' AND source_queue_id IS NOT NULL)
              AND state='needs_attention' AND error='等待設定粉專 Token'""")
    c.execute("""UPDATE delivery_jobs SET state='needs_attention',finished_at=?,
        error='文案還有未完成佔位符，請先修改或退回認領池'
        WHERE state='queued' AND queue_id IN (
          SELECT id FROM queue WHERE source_queue_id IS NOT NULL
            AND (body LIKE '%待填%' OR body LIKE '%您的名字%' OR body LIKE '%你的名字%'))""",
        (datetime.now().isoformat(timespec="seconds"),))
    c.execute("PRAGMA foreign_keys=ON")
    # 本機驗收帳號；正式部署必須用環境變數覆寫密碼。
    local_password = os.environ.get("ZAOSHEN_BOOTSTRAP_PASSWORD", "1234")
    seeds = [("wayne", "Wayne", "system_admin"), ("partnera", "夥伴 A", "activity_partner"),
             ("partnerb", "夥伴 B", "activity_partner"), ("partnerc", "夥伴 C", "activity_partner")]
    for username, display_name, role in seeds:
        existing = c.execute("SELECT id,must_change_password FROM users WHERE username=?", (username,)).fetchone()
        if not existing:
            c.execute("INSERT INTO users(username,display_name,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                      (username, display_name, auth.password_hash(local_password), role, datetime.now().isoformat(timespec="seconds")))
        elif existing["must_change_password"] and (os.environ.get("ZAOSHEN_BOOTSTRAP_PASSWORD") or not os.environ.get("SPACE_ID")):
            c.execute("UPDATE users SET password_hash=? WHERE id=?", (auth.password_hash(local_password), existing["id"]))
    campaign = c.execute("SELECT id FROM campaigns ORDER BY id LIMIT 1").fetchone()
    if campaign:
        c.execute("INSERT OR IGNORE INTO activity_members(campaign_id,user_id) SELECT ?,id FROM users WHERE role='activity_partner'",
                  (campaign["id"],))
    c.commit(); c.close()
init_db()

app = FastAPI(title="造神引擎GPT版 — 審核佇列")
_page_worker_started = False
_database_backup_started = False

PUBLIC_PATHS = {"/login", "/api/login", "/health"}

def current_user(request: Request):
    session = auth.read_session(request.cookies.get("zaoshen_session", ""))
    if not session:
        return None
    c = db(); row = c.execute("SELECT id,username,display_name,role,active,must_change_password FROM users WHERE id=?", (session["uid"],)).fetchone(); c.close()
    return dict(row) if row and row["active"] else None

@app.middleware("http")
async def require_login(request: Request, call_next):
    path = request.url.path
    if path in PUBLIC_PATHS or path == "/api/rpa/pair" or path.startswith("/static/brand/"):
        return await call_next(request)
    if path.startswith("/api/worker/"):
        return await call_next(request)
    user = current_user(request)
    if not user:
        if path.startswith("/api/"):
            return Response(json.dumps({"detail": "請先登入"}, ensure_ascii=False), 401, media_type="application/json")
        return RedirectResponse("/login?next=" + path, status_code=303)
    request.state.user = user
    return await call_next(request)

@app.get("/health")
def health():
    return {"ok": True, "live": auto_publish_enabled()}

@app.get("/login")
def login_page():
    return FileResponse(str(ROOT / "static" / "login.html"))


@app.get("/static/brand/{name}")
def brand_asset(name: str):
    safe = Path(name).name
    path = ROOT / "static" / "brand" / safe
    if safe != name or not path.is_file():
        raise HTTPException(404, "Brand asset not found")
    media = {".png": "image/png", ".svg": "image/svg+xml", ".css": "text/css", ".js": "text/javascript"}
    return FileResponse(str(path), media_type=media.get(path.suffix.lower(), "application/octet-stream"))

class LoginIn(BaseModel):
    username: str
    password: str

@app.post("/api/login")
def login(body: LoginIn, response: Response):
    c = db(); row = c.execute("SELECT * FROM users WHERE lower(username)=lower(?) AND active=1", (body.username.strip(),)).fetchone(); c.close()
    if not row or not auth.verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "帳號或密碼錯誤")
    response.set_cookie("zaoshen_session", auth.make_session(row["id"], row["role"]), httponly=True,
                        samesite="lax", secure=os.environ.get("ZAOSHEN_COOKIE_SECURE", "0") == "1", max_age=43200)
    return {"ok": True, "user": {"display_name": row["display_name"], "role": row["role"]}}

@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie("zaoshen_session")
    return {"ok": True}

@app.get("/api/me")
def me(request: Request):
    return request.state.user


@app.get("/media/{name}")
def media(name: str):
    safe = Path(name).name
    path = UPLOADS / safe
    if safe != name or not path.is_file():
        raise HTTPException(404, "找不到圖片")
    return FileResponse(str(path))


TAIPEI = ZoneInfo("Asia/Taipei")


def local_now():
    """所有使用者排程均是台灣時間；回傳無 offset 格式以相容既有 SQLite 資料。"""
    return datetime.now(TAIPEI).replace(tzinfo=None)


def now():
    return local_now().isoformat(timespec="seconds")


def auto_publish_enabled():
    """認領即授權的全自動模式；緊急時可以 ZAOSHEN_AUTO_PUBLISH=0 全站停止送出。"""
    return os.environ.get("ZAOSHEN_AUTO_PUBLISH", "1") == "1"


def device_from_request(request: Request):
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not token:
        raise HTTPException(401, "RPA 裝置尚未配對")
    c = db(); row = c.execute("""SELECT d.*,u.display_name,u.username FROM devices d
        JOIN users u ON u.id=d.user_id WHERE d.token_hash=? AND d.revoked_at IS NULL""",
        (auth.token_hash(token),)).fetchone(); c.close()
    if not row:
        raise HTTPException(401, "RPA 裝置憑證無效或已撤銷")
    return dict(row)


def audit(actor_user_id, action, entity_type="", entity_id="", detail=None):
    c = db(); c.execute("INSERT INTO audit_logs(actor_user_id,action,entity_type,entity_id,detail_json,created_at) VALUES(?,?,?,?,?,?)",
        (actor_user_id, action, entity_type, str(entity_id), json.dumps(detail or {}, ensure_ascii=False), now())); c.commit(); c.close()


@app.get("/team")
def team_page():
    return FileResponse(str(ROOT / "static" / "team.html"))


@app.get("/api/team")
def team_status(request: Request):
    c = db(); users = [dict(r) for r in c.execute("""SELECT id,username,display_name,role,active
        FROM users WHERE active=1 ORDER BY CASE role WHEN 'system_admin' THEN 0 ELSE 1 END,id""")]
    devices = [dict(r) for r in c.execute("""SELECT d.id,d.user_id,d.name,d.rpa_version,d.os_version,d.state,
        d.current_job,d.last_error,d.last_seen,d.created_at,u.display_name
        FROM devices d JOIN users u ON u.id=d.user_id WHERE d.revoked_at IS NULL ORDER BY u.id,d.id""")]
    logs = [dict(r) for r in c.execute("""SELECT a.action,a.entity_type,a.entity_id,a.detail_json,a.created_at,
        coalesce(u.display_name,'系統') actor FROM audit_logs a LEFT JOIN users u ON u.id=a.actor_user_id
        ORDER BY a.id DESC LIMIT 30""")]
    c.close(); cutoff = local_now() - timedelta(seconds=65)
    for d in devices:
        try: online = bool(d["last_seen"] and datetime.fromisoformat(d["last_seen"]) >= cutoff)
        except ValueError: online = False
        d["online"] = online
        d["display_state"] = d["state"] if online else "offline"
    return {"me": request.state.user, "users": users, "devices": devices, "audit_logs": logs,
            "heartbeat_timeout_seconds": 65, "minimum_rpa_version": "1.2.3", "generated_at": now()}


class ClaimTaskIn(BaseModel):
    target_name: str = ""
    target_url: str = ""
    scheduled_date: str = ""
    dispatch_method: str = "personal_rpa"  # page_token / personal_rpa


class GeneratePoolContentIn(BaseModel):
    campaign_id: int = 1
    channel: str = "page"
    target_id: int = 0
    direction: str = ""


@app.post("/api/task-pool/generate")
def generate_pool_content(body: GeneratePoolContentIn, request: Request):
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(503, "尚未設定 OPENAI_API_KEY")
    direction = body.direction.strip()
    if len(direction) < 4:
        raise HTTPException(400, "請輸入至少 4 個字的行銷方向")
    mapping = {
        "page": ("page", "manual", "粉專"),
        "grouppost": ("group", "grouppost", "社團"),
        "pitch": ("group", "pitch", "社團管理員"),
        "kol_dm": ("kol_dm", "kol", "KOL"),
    }
    if body.channel not in mapping:
        raise HTTPException(400, "不支援的發布渠道")
    kind, phase, default_target = mapping[body.channel]
    c = db(); campaign = c.execute("SELECT * FROM campaigns WHERE id=?", (body.campaign_id,)).fetchone()
    if not campaign:
        c.close(); raise HTTPException(404, "找不到活動")
    target_name, target_url = default_target, ""
    if kind != "page":
        cat = "kol" if kind == "kol_dm" else "group"
        target = c.execute("SELECT * FROM targets WHERE id=? AND cat=?", (body.target_id, cat)).fetchone()
        if not target:
            c.close(); raise HTTPException(400, "請從現有名單選擇正確的發布目標")
        target_name, target_url = target["name"], target["handle_url"]
    c.close()
    try:
        generated = ai.generate_partner_content(dict(campaign), direction, body.channel, target_name)
        image_bytes = ai.generate_image(generated["image_prompt"])
    except Exception as exc:
        raise HTTPException(502, f"AI 圖文生成失敗：{exc}")
    image_name = f"generated_{request.state.user['id']}_{secrets.token_hex(8)}.png"
    (UPLOADS / image_name).write_bytes(image_bytes)
    c = db(); cur = c.execute("""INSERT INTO queue(campaign_id,kind,phase,target_name,target_url,
        scheduled_date,body,image_hint,status,created_at,note)
        VALUES(?,?,?,?,?,'',?,?,'draft',?,?)""",
        (body.campaign_id, kind, phase, target_name, target_url, generated["body"], image_name,
         now(), f"AI 內容產生器｜方向：{direction}｜由 {request.state.user['display_name']} 產生"))
    qid = cur.lastrowid; c.commit(); c.close()
    audit(request.state.user["id"], "AI 產生新圖文", "queue", qid,
          {"channel": body.channel, "target_name": target_name, "direction": direction})
    return {"ok": True, "id": qid, "target_name": target_name,
            "body": generated["body"], "image_url": f"/media/{image_name}"}


@app.get("/api/task-pool")
def task_pool(request: Request, campaign_id: int = 0):
    c = db()
    rows = [dict(r) for r in c.execute("""SELECT q.*,c.name campaign_name,
        (SELECT count(*) FROM queue x WHERE x.source_queue_id=q.id) claimed_count,
        (SELECT count(*) FROM queue x WHERE x.source_queue_id=q.id AND x.claimed_by=?) my_claims
        FROM queue q JOIN campaigns c ON c.id=q.campaign_id
        WHERE q.status='approved' AND q.source_queue_id IS NULL AND q.kind<>'reply'
          AND NOT EXISTS (SELECT 1 FROM queue taken WHERE taken.source_queue_id=q.id)
          AND (?=0 OR q.campaign_id=?)
        ORDER BY q.scheduled_date,q.id""", (request.state.user["id"], campaign_id, campaign_id))]
    mine = [dict(r) for r in c.execute("""SELECT q.id,q.source_queue_id,q.kind,q.phase,q.target_name,
        q.target_url,q.scheduled_date,q.status,q.body,q.image_hint,c.name campaign_name,
        j.id job_id,j.state job_state,j.method job_method,j.external_url,j.error job_error
        FROM queue q JOIN campaigns c ON c.id=q.campaign_id
        LEFT JOIN delivery_jobs j ON j.id=(SELECT max(j2.id) FROM delivery_jobs j2 WHERE j2.queue_id=q.id)
        WHERE q.claimed_by=? ORDER BY q.claimed_at DESC LIMIT 50""", (request.state.user["id"],))]
    c.close()
    for r in rows:
        r["kind_label"] = KIND_LABEL.get(r["kind"], r["kind"])
        r["phase_label"] = PHASE_LABEL.get(r["phase"], r["phase"])
    return {"available": rows, "mine": mine, "me": request.state.user}


@app.post("/api/task-pool/{qid}/claim")
def claim_content_task(qid: int, body: ClaimTaskIn, request: Request):
    if body.dispatch_method not in ("page_token", "personal_rpa"):
        raise HTTPException(400, "請選擇粉專 Token 或個人 RPA")
    scheduled = body.scheduled_date.strip()
    if scheduled:
        try: datetime.fromisoformat(scheduled)
        except ValueError: raise HTTPException(400, "排程日期時間格式不正確")
    c = db(); c.execute("BEGIN IMMEDIATE")
    src = c.execute("SELECT * FROM queue WHERE id=? AND status='approved' AND source_queue_id IS NULL", (qid,)).fetchone()
    if not src:
        c.rollback(); c.close(); raise HTTPException(404, "這篇內容已不在可認領任務池")
    if c.execute("SELECT 1 FROM queue WHERE source_queue_id=?", (qid,)).fetchone():
        c.rollback(); c.close(); raise HTTPException(409, "這篇內容已被其他夥伴認領")
    # 一鍵認領：目標、網址、文案與時間都以中央任務為準，
    # 不把搜尋發布位置的工作丟回給夥伴。
    if body.dispatch_method == "page_token":
        clone_kind = "page"
        target_name = os.environ.get("FB_PAGE_NAME", "官方粉專（Token）")
        target_url = os.environ.get("FB_PAGE_URL", "")
    else:
        clone_kind = src["kind"]
        target_name = src["target_name"] or "個人 Facebook 動態"
        target_url = src["target_url"] or ("https://www.facebook.com/" if src["kind"] == "page" else "")
    source_schedule = (src["scheduled_date"] or "").strip()
    try:
        # 中央任務若已過期，認領後立即排隊；未來排程則照原計畫。
        task_schedule = source_schedule if source_schedule and datetime.fromisoformat(source_schedule) > local_now() else now()
    except ValueError:
        task_schedule = now()
    cur = c.execute("""INSERT INTO queue(campaign_id,kind,phase,target_name,target_url,scheduled_date,
        body,image_hint,status,created_at,approved_at,note,claim_limit,source_queue_id,claimed_by,claimed_at)
        VALUES(?,?,?,?,?,?,?,?, 'approved',?,?,?,?,?,?,?)""",
        (src["campaign_id"],clone_kind,src["phase"],target_name,target_url,
         task_schedule,src["body"],src["image_hint"],now(),now(),
         f"由 {request.state.user['display_name']} 從任務池認領",1,qid,request.state.user["id"],now()))
    clone_id = cur.lastrowid
    # 發布工具由認領當下明確選擇，不與文章類型綁死。
    has_page_api = bool(os.environ.get("FB_PAGE_ID") and os.environ.get("FB_PAGE_TOKEN"))
    method = "graph_api" if body.dispatch_method == "page_token" else "local_rpa"
    job_id = _queue_job(c, clone_id, method)
    if method == "graph_api" and not has_page_api:
        c.execute("UPDATE delivery_jobs SET state='needs_attention',finished_at=?,error=? WHERE id=?",
                  (now(), "等待設定粉專 Token", job_id))
    c.commit(); c.close()
    audit(request.state.user["id"], "認領發布任務", "queue", clone_id,
          {"source_queue_id": qid, "job_id": job_id, "scheduled_date": task_schedule,
           "dispatch_method": body.dispatch_method})
    return {"ok": True, "queue_id": clone_id, "job_id": job_id,
            "status": "approved", "scheduled_date": task_schedule, "method": method}


class MyClaimIn(BaseModel):
    target_name: str = ""
    target_url: str = ""
    scheduled_date: str = ""
    body: str = ""


def _save_my_claim(qid: int, body: MyClaimIn, request: Request, schedule: bool):
    scheduled = body.scheduled_date.strip()
    if scheduled:
        try: datetime.fromisoformat(scheduled)
        except ValueError: raise HTTPException(400, "排程日期時間格式不正確")
    if schedule and not scheduled:
        raise HTTPException(400, "請先設定發布日期與時間")
    if not body.body.strip():
        raise HTTPException(400, "貼文內容不可為空")
    c = db(); c.execute("BEGIN IMMEDIATE")
    row = c.execute("SELECT * FROM queue WHERE id=? AND claimed_by=? AND source_queue_id IS NOT NULL",
                    (qid, request.state.user["id"])).fetchone()
    if not row:
        c.rollback(); c.close(); raise HTTPException(404, "找不到你認領的這篇內容")
    active = c.execute("SELECT state FROM delivery_jobs WHERE queue_id=? ORDER BY id DESC LIMIT 1", (qid,)).fetchone()
    if active and active["state"] in ("running","succeeded"):
        c.rollback(); c.close(); raise HTTPException(409, "這篇已開始執行或已發布，不能再修改")
    new_status = "approved" if schedule else "claimed"
    c.execute("""UPDATE queue SET target_name=?,target_url=?,scheduled_date=?,body=?,status=?
                 WHERE id=?""", (body.target_name.strip() or row["target_name"], body.target_url.strip(),
                                  scheduled, body.body.strip(), new_status, qid))
    if active and active["state"] in ("failed", "needs_attention"):
        c.execute("UPDATE delivery_jobs SET state='queued',started_at=NULL,finished_at=NULL,error=NULL WHERE queue_id=?", (qid,))
    job_id = _queue_job(c, qid, _method_for(row["kind"])) if schedule else None
    c.commit(); c.close()
    audit(request.state.user["id"], "確認個人發布排程" if schedule else "修改個人認領版本",
          "queue", qid, {"job_id": job_id, "scheduled_date": scheduled})
    return {"ok": True, "queue_id": qid, "job_id": job_id, "status": new_status}


@app.post("/api/task-pool/mine/{qid}/save")
def save_my_claim(qid: int, body: MyClaimIn, request: Request):
    return _save_my_claim(qid, body, request, False)


@app.post("/api/task-pool/mine/{qid}/schedule")
def schedule_my_claim(qid: int, body: MyClaimIn, request: Request):
    return _save_my_claim(qid, body, request, True)


@app.post("/api/task-pool/mine/{qid}/return")
def return_my_claim(qid: int, request: Request):
    """尚未開始執行時可退回公共認領池；原始已核准文章不會被刪除。"""
    c = db(); c.execute("BEGIN IMMEDIATE")
    row = c.execute("SELECT * FROM queue WHERE id=? AND claimed_by=? AND source_queue_id IS NOT NULL",
                    (qid, request.state.user["id"])).fetchone()
    if not row:
        c.rollback(); c.close(); raise HTTPException(404, "找不到你認領的這篇內容")
    active = c.execute("SELECT state FROM delivery_jobs WHERE queue_id=? ORDER BY id DESC LIMIT 1", (qid,)).fetchone()
    if active and active["state"] in ("running", "succeeded"):
        c.rollback(); c.close(); raise HTTPException(409, "這篇已開始執行或已發布，不能退回")
    source_id = row["source_queue_id"]
    c.execute("DELETE FROM delivery_jobs WHERE queue_id=?", (qid,))
    c.execute("DELETE FROM queue WHERE id=?", (qid,))
    c.commit(); c.close()
    audit(request.state.user["id"], "退回公共認領池", "queue", source_id, {"returned_queue_id": qid})
    return {"ok": True, "source_queue_id": source_id}


@app.post("/api/team/pairing-code")
def create_pairing_code(request: Request):
    user = request.state.user; code = auth.random_code()
    expires = (datetime.now() + timedelta(minutes=10)).isoformat(timespec="seconds")
    c = db(); c.execute("UPDATE pairing_codes SET used_at=? WHERE user_id=? AND used_at IS NULL", (now(), user["id"]))
    c.execute("INSERT INTO pairing_codes(user_id,code_hash,expires_at,created_at) VALUES(?,?,?,?)",
              (user["id"], auth.token_hash(code), expires, now())); c.commit(); c.close()
    audit(user["id"], "建立 RPA 配對碼", "user", user["id"])
    return {"code": code, "expires_at": expires, "expires_in_seconds": 600}


class PairIn(BaseModel):
    code: str
    device_name: str = "Windows 電腦"
    rpa_version: str = "1.0.0"
    os_version: str = ""


@app.post("/api/rpa/pair")
def pair_device(body: PairIn):
    c = db(); c.execute("BEGIN IMMEDIATE")
    row = c.execute("""SELECT p.*,u.display_name FROM pairing_codes p JOIN users u ON u.id=p.user_id
        WHERE p.code_hash=? AND p.used_at IS NULL AND p.expires_at>=?""",
        (auth.token_hash(body.code.strip().upper()), now())).fetchone()
    if not row:
        c.rollback(); c.close(); raise HTTPException(400, "配對碼錯誤或已逾期")
    token = secrets.token_urlsafe(32)
    cur = c.execute("""INSERT INTO devices(user_id,name,token_hash,rpa_version,os_version,state,last_seen,created_at)
        VALUES(?,?,?,?,?,'idle',?,?)""", (row["user_id"], body.device_name[:80], auth.token_hash(token),
        body.rpa_version[:30], body.os_version[:120], now(), now()))
    c.execute("UPDATE pairing_codes SET used_at=? WHERE id=?", (now(), row["id"])); c.commit(); c.close()
    audit(row["user_id"], "RPA 裝置配對成功", "device", cur.lastrowid, {"device_name": body.device_name})
    return {"device_token": token, "device_id": cur.lastrowid, "display_name": row["display_name"]}


class HeartbeatIn(BaseModel):
    state: str = "idle"
    current_job: str = ""
    last_error: str = ""
    rpa_version: str = "1.0.0"
    os_version: str = ""


@app.post("/api/worker/heartbeat")
def worker_heartbeat(request: Request, body: HeartbeatIn):
    device = device_from_request(request)
    state = body.state if body.state in ("idle", "working", "attention", "updating") else "idle"
    c = db(); c.execute("""UPDATE devices SET state=?,current_job=?,last_error=?,rpa_version=?,os_version=?,last_seen=? WHERE id=?""",
        (state, body.current_job[:200], body.last_error[:500], body.rpa_version[:30], body.os_version[:120], now(), device["id"])); c.commit(); c.close()
    return {"ok": True, "server_time": now(), "minimum_rpa_version": "1.2.3", "live": auto_publish_enabled()}


@app.post("/api/team/devices/{device_id}/revoke")
def revoke_device(device_id: int, request: Request):
    user = request.state.user; c = db()
    row = c.execute("SELECT user_id FROM devices WHERE id=? AND revoked_at IS NULL", (device_id,)).fetchone()
    if not row or (user["role"] != "system_admin" and row["user_id"] != user["id"]):
        c.close(); raise HTTPException(403, "只能移除自己的裝置")
    c.execute("UPDATE devices SET revoked_at=?,state='offline' WHERE id=?", (now(), device_id)); c.commit(); c.close()
    audit(user["id"], "撤銷 RPA 裝置", "device", device_id)
    return {"ok": True}


@app.get("/api/rpa/download")
def download_rpa(request: Request):
    """正式安裝程式存在時直接下載；尚未打包時保留開發驗收 ZIP。"""
    installer = ROOT / "dist-installer" / "造神引擎RPA安裝程式-1.2.3.exe"
    if installer.is_file():
        audit(request.state.user["id"], "下載 RPA 安裝程式", "rpa", "1.2.3")
        return FileResponse(str(installer), media_type="application/vnd.microsoft.portable-executable",
                            filename=installer.name)
    buf = io.BytesIO()
    launcher = '@echo off\r\nchcp 65001 >nul\r\npython -m pip install -r requirements-rpa.txt\r\npython -m playwright install chromium\r\nstart "" pythonw rpa_control.py\r\n'
    guide = "造神引擎GPT版 RPA 1.0.0\n1. Windows 安裝 Python 3.10 以上。\n2. 雙擊 啟動造神引擎RPA.bat。\n3. 輸入網站顯示的一次性配對碼。\n4. Facebook 登入資料只保留在本機 runtime 資料夾。\n"
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(ROOT / "local_worker.py", "zaoshen_rpa.py")
        z.write(ROOT / "rpa_control.py", "rpa_control.py")
        z.writestr("啟動造神引擎RPA.bat", launcher)
        z.writestr("requirements-rpa.txt", "playwright\n")
        z.writestr("使用說明.txt", guide)
    audit(request.state.user["id"], "下載 RPA", "rpa", "1.0.0")
    return Response(buf.getvalue(), media_type="application/zip", headers={"Content-Disposition": "attachment; filename=zaoshen-rpa-1.0.0.zip"})


def _method_for(kind):
    has_page_api = bool(os.environ.get("FB_PAGE_ID") and os.environ.get("FB_PAGE_TOKEN"))
    return "graph_api" if kind == "page" and has_page_api else "local_rpa"


def _queue_job(c, qid, method):
    active = c.execute(
        "SELECT id FROM delivery_jobs WHERE queue_id=? AND state IN ('queued','running')", (qid,)
    ).fetchone()
    if active:
        return active["id"]
    cur = c.execute(
        "INSERT INTO delivery_jobs(queue_id,method,state,requested_at) VALUES(?,?,'queued',?)",
        (qid, method, now()))
    return cur.lastrowid


def page_worker_loop():
    """正式單人模式常駐執行器：核准後自動發布粉專工作。"""
    gap = max(5, int(os.environ.get("ZAOSHEN_PAGE_GAP_SECONDS", "20")))
    while True:
        try:
            result = run_next_page_job()
            time.sleep(gap if result.get("ran") else 3)
        except Exception as exc:
            print(f"page worker error: {exc}", flush=True)
            time.sleep(10)


def database_backup_loop():
    """SQLite 變更後製作一致性備份:Cloud Run 寫回 GCS,HF Space 寫回私有 Dataset。"""
    bucket = os.environ.get("ZAOSHEN_GCS_BUCKET")
    gcs_blob = None
    api = repo = None
    if bucket:
        from google.cloud import storage
        gcs_blob = storage.Client().bucket(bucket).blob("saas.db")
    else:
        from huggingface_hub import HfApi
        repo, token = os.environ.get("ZAOSHEN_DATA_REPO"), os.environ.get("HF_TOKEN")
        api = HfApi(token=token)
    last_signature = None
    while True:
        try:
            signature = (DB.stat().st_mtime_ns, DB.stat().st_size)
            if signature != last_signature:
                with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp:
                    temp_path = Path(temp.name)
                source = sqlite3.connect(DB)
                target = sqlite3.connect(temp_path)
                source.backup(target); target.close(); source.close()
                if gcs_blob is not None:
                    gcs_blob.upload_from_filename(str(temp_path))
                else:
                    api.upload_file(path_or_fileobj=str(temp_path), path_in_repo="saas.db",
                                    repo_id=repo, repo_type="dataset",
                                    commit_message="Persist production database")
                temp_path.unlink(missing_ok=True)
                last_signature = signature
        except Exception as exc:
            print(f"DATABASE backup error: {exc}", flush=True)
        time.sleep(30)


@app.on_event("startup")
def start_page_worker():
    global _page_worker_started, _database_backup_started
    _persist = os.environ.get("ZAOSHEN_GCS_BUCKET") or (
        os.environ.get("SPACE_ID") and os.environ.get("ZAOSHEN_DATA_REPO") and os.environ.get("HF_TOKEN"))
    if _persist and not _database_backup_started:
        threading.Thread(target=database_backup_loop, name="zaoshen-db-backup", daemon=True).start()
        _database_backup_started = True
    if auto_publish_enabled() and not _page_worker_started:
        threading.Thread(target=page_worker_loop, name="zaoshen-page-worker", daemon=True).start()
        _page_worker_started = True
        print("PAGE_WORKER live auto-publish enabled", flush=True)


# ---------------- 活動 ----------------
class CampaignIn(BaseModel):
    name: str = ""; hero: str = ""; selling_points: str = ""
    when_where: str = ""; audience: str = ""; tone: str = "真誠口語"; incentive: str = ""
    contact_info: str = ""


@app.get("/")
def index():
    return FileResponse(str(ROOT / "static" / "index.html"))


@app.get("/warroom")
def warroom():
    return FileResponse(str(ROOT / "static" / "warroom.html"))


@app.get("/audience")
def audience():
    return FileResponse(str(ROOT / "static" / "audience.html"))


@app.get("/manager")
def manager():
    return FileResponse(str(ROOT / "static" / "manager.html"))


@app.get("/page-token")
def page_token_page():
    return FileResponse(str(ROOT / "static" / "page_token.html"))


@app.get("/api/campaigns")
def list_campaigns():
    c = db(); rows = [dict(r) for r in c.execute("SELECT * FROM campaigns ORDER BY id DESC")]; c.close()
    for r in rows:
        r.pop("copy_json", None)
    return rows


@app.get("/api/campaigns/{cid}/suggestions")
def campaign_suggestions(cid: int):
    """依活動資料提供可直接選用的貼文靈感；不自動建立草稿或發佈。"""
    c = db(); row = c.execute("SELECT * FROM campaigns WHERE id=?", (cid,)).fetchone(); c.close()
    if not row:
        raise HTTPException(404, "找不到活動")
    camp = dict(row)
    name = camp.get("name") or "這場活動"
    hero = camp.get("hero") or "主辦單位"
    when_where = camp.get("when_where") or "請補上活動時間與地點"
    audience = camp.get("audience") or "喜歡週末活動的朋友"
    contact = camp.get("contact_info") or "請私訊粉專詢問"
    suggestions = [
        ("活動公告", "一眼看懂", "page", "manual", "正式公告時間地點與特色",
         f"週末下午，來一場不需要酒精也能很開心的派對。\n\n【{name}】\n{when_where}\n\n現場有咖啡、DJ／MC 與白天的音樂氛圍，免費入場。\n{contact}", "立即發布"),
        ("概念教育", "Coffee Rave 是什麼", "page", "manual", "降低陌生感，讓第一次聽到的人也懂",
         f"什麼是 Coffee Rave？\n\n簡單說，就是把咖啡、DJ 音樂與白天社交放在同一個空間。不用熬夜，也不一定要喝酒，一樣可以跟朋友聊天、聽音樂和跳舞。\n\n{name}｜{when_where}", "活動前 10–14 天"),
        ("在地故事", "為什麼在古坑", "page", "manual", "把地方特色與咖啡文化連在一起",
         f"為什麼這場清醒派對想在古坑發生？\n\n因為咖啡不只是一杯飲料，也可以成為人們認識一個地方的開始。這次我們想用音樂、人與古坑咖啡，一起做一個不一樣的週末下午。\n\n{when_where}", "活動前 7–10 天"),
        ("人物故事", "DJ／MC 介紹", "page", "manual", "讓演出者成為活動記憶點",
         f"這個下午會由誰帶你進入狀態？\n\n【演出者名稱】將在 {name} 帶來【曲風／演出特色】。接下來我們還會公開他／她的歌單線索。\n\n{when_where}", "活動前 7 天"),
        ("幕後花絮", "籌備現場", "page", "manual", "用短影片建立真實感",
         f"一場白天派對是怎麼慢慢成形的？\n\n從音響、咖啡、動線到歌單，這幾天我們正在為 {name} 把每個小細節放到位。這是今天的籌備現場，你最想先看哪一部分？", "活動前 5–7 天"),
        ("互動投票", "你想聽什麼", "page", "manual", "用留言收集歌單偏好",
         f"{name} 歌單調查：如果是週日下午，你想聽哪一種？\n\nA. House\nB. Disco\nC. Funk\nD. 你的私藏曲風\n\n留言告訴我們，也可以丟一首想聽的歌。", "活動前 5–7 天"),
        ("互動提問", "你是咖啡派還是音樂派", "page", "manual", "簡單問題降低留言門檻",
         "來 Coffee Rave 的第一理由是什麼？\n\n☕ 咖啡派：為了古坑咖啡\n🎶 音樂派：為了 DJ 和現場氛圍\n👥 社交派：為了跟朋友過不一樣的週末\n\n留一個 emoji 選邊站。", "活動前 5 天"),
        ("場景想像", "一個理想週日下午", "page", "manual", "先讓觀眾想像到場感受",
         f"想像一下：週日下午三點，手上是一杯咖啡，現場開始有音樂，不用趕行程，也不用等到深夜。\n\n這就是我們想在 {hero} 做的下午。\n{when_where}", "活動前 4–6 天"),
        ("朋友揪團", "標記你的週日隊友", "page", "manual", "鼓勵標記與分享",
         f"這篇交給你的週日隊友。\n\n標記一個會願意跟你一起在白天喝咖啡、聽 DJ、跳舞的人。{name} 免費入場，只差你們把時間留下來。\n\n{when_where}", "活動前 3–5 天"),
        ("實用資訊", "行前懶人包", "page", "manual", "把時間、地點、入場與注意事項集中說清楚",
         f"【{name} 行前懶人包】\n\n📍 時間地點：{when_where}\n🎟️ 入場：免費\n☕ 現場：古坑咖啡、DJ／MC\n👕 建議：穿輕鬆、適合活動的服裝\n💬 詢問：{contact}\n\n先儲存這篇，當天出門前再看一次。", "活動前 2–3 天"),
        ("常見問題", "我不會跳舞也可以嗎", "page", "manual", "先解除參加顧慮",
         f"「我不會跳舞，去 Coffee Rave 會不會很尷尬？」\n\n不會。你可以只喝咖啡、聽音樂、聊天，也可以站著跟節拍搖一搖。這裡不是舞蹈比賽，只是一個讓 {audience} 輕鬆見面的下午。", "活動前 2–4 天"),
        ("倒數提醒", "明天見", "page", "manual", "最後一次確認行程",
         f"明天見。\n\n{name}\n{when_where}\n\n免費入場，帶著你想一起過週日下午的人來就好。記得先把這篇傳給同行朋友。", "活動前 1 天"),
        ("當日提醒", "今天下午開跳", "page", "manual", "當天再次提供到場資訊",
         f"就是今天！\n\n{name} 下午見。\n{when_where}\n\n現場有咖啡、DJ／MC，免費入場。臨時想來也歡迎，把定位存好就出發。", "活動當大早上"),
        ("現場即時", "現場正在發生", "page", "manual", "用現場短影片邀請附近的人",
         f"現場已經開始了。\n\n咖啡在手上，音樂正在走，今天到 19:00 之前都可以加入。如果你剛好在古坑附近，現在過來 {hero} 找我們。", "活動進行中"),
        ("社團發文", "在地週末情報", "group", "grouppost", "以資訊口吻分享到雲林與咖啡社團",
         f"分享一個古坑週末活動：{name}\n\n{when_where}\n現場有古坑咖啡、DJ／MC，免費入場。適合喜歡咖啡、音樂或想找週日行程的朋友。\n\n如果本群不適合此類資訊，請管理員告知，謝謝。", "活動前 5–7 天"),
        ("社團私訊", "詢問管理員可否分享", "group", "pitch", "先徵求同意，不直接丟廣告",
         f"管理員您好，我們是 {hero}，近期會舉辦 {name}，內容與古坑咖啡、音樂及週末在地活動有關。想先詢問是否適合在貴群分享活動資訊？我們會遵守版規，若不適合也完全理解，謝謝。", "活動前 7–10 天"),
        ("KOL 邀約", "邀請體驗清醒派對", "kol_dm", "kol", "針對咖啡、音樂、旅遊創作者邀約",
         f"嗨【名字】你好，我們是 {hero}。看到你平常分享【咖啡／音樂／在地旅遊】，想邀請你來體驗 {name}。\n\n{when_where}\n\n這是一場白天、不以酒精為主的 Coffee Rave。若你有興趣，我們可以再提供完整資訊；不需要回覆壓力，謝謝。", "活動前 10–14 天"),
        ("活動回顧", "謝謝來到現場的人", "page", "manual", "活動後維持關係並收集照片",
         f"謝謝今天來到 {name} 的每一個人。\n\n有人為咖啡來，有人為音樂來，也有人只是臨時想試試不一樣的週日。如果你有拍到喜歡的畫面，歡迎標記 {hero} 或在留言裡分享。", "活動結束後 1–2 小時"),
        ("二次互動", "下次你想要什麼", "page", "manual", "用投票驗證下一場方向",
         f"{name} 結束了，但我們想先問下一題：如果再來一場，你最想增加什麼？\n\nA. 更長的 DJ set\nB. 咖啡體驗／試飲\nC. 主題服裝\nD. 在地品牌市集\n\n留言告訴我們，下一場會從你們的答案開始。", "活動後 1–2 天"),
    ]
    return {"campaign_id": cid, "suggestions": [
        {"id": i + 1, "category": x[0], "title": x[1], "kind": x[2], "phase": x[3],
         "reason": x[4], "body": x[5], "timing": x[6]}
        for i, x in enumerate(suggestions)
    ]}


@app.get("/api/dashboard")
def dashboard():
    c = db()
    campaigns = [dict(r) for r in c.execute("""
        SELECT c.id,c.name,c.hero,c.when_where,c.created_at,
          count(q.id) total,
          sum(CASE WHEN q.id IS NOT NULL AND q.status<>'skipped'
                    AND NOT EXISTS(SELECT 1 FROM queue x WHERE x.source_queue_id=q.id) THEN 1 ELSE 0 END) drafts,
          sum(CASE WHEN EXISTS(SELECT 1 FROM queue x WHERE x.source_queue_id=q.id AND x.status<>'sent') THEN 1 ELSE 0 END) approved,
          sum(CASE WHEN EXISTS(SELECT 1 FROM queue x WHERE x.source_queue_id=q.id AND x.status='sent') THEN 1 ELSE 0 END) sent
        FROM campaigns c LEFT JOIN queue q ON q.campaign_id=c.id AND q.source_queue_id IS NULL
        GROUP BY c.id ORDER BY c.id DESC""")]
    jobs = [dict(r) for r in c.execute("""
        SELECT j.*,q.target_name,q.kind,q.body,q.scheduled_date,c.name campaign_name
        FROM delivery_jobs j JOIN queue q ON q.id=j.queue_id
        JOIN campaigns c ON c.id=q.campaign_id ORDER BY j.id DESC LIMIT 100""")]
    c.close()
    return {"campaigns": campaigns, "jobs": jobs,
            "live": auto_publish_enabled()}


@app.get("/api/manager-overview")
def manager_overview(campaign_id: int = 0):
    """Read-only operational truth for the activity manager dashboard."""
    c = db()
    where = " WHERE q.campaign_id=?" if campaign_id else ""
    args = [campaign_id] if campaign_id else []
    campaigns = [dict(r) for r in c.execute("""
        SELECT c.id,c.name,c.hero,c.when_where,c.contact_info,c.created_at,
          count(q.id) total,
          sum(CASE WHEN q.status='draft' THEN 1 ELSE 0 END) drafts,
          sum(CASE WHEN q.status='approved' THEN 1 ELSE 0 END) approved,
          sum(CASE WHEN q.status='sent' THEN 1 ELSE 0 END) sent,
          sum(CASE WHEN q.status='skipped' THEN 1 ELSE 0 END) skipped,
          sum(CASE WHEN q.image_hint IS NOT NULL AND trim(q.image_hint)<>'' THEN 1 ELSE 0 END) with_images,
          sum(CASE WHEN (q.kind='page' OR (q.kind='group' AND q.phase='grouppost'))
                    AND (q.image_hint IS NULL OR trim(q.image_hint)='') THEN 1 ELSE 0 END) missing_required_images
        FROM campaigns c LEFT JOIN queue q ON q.campaign_id=c.id
        GROUP BY c.id ORDER BY c.id DESC""")]
    channels = [dict(r) for r in c.execute(f"""
        SELECT CASE
          WHEN q.kind='page' THEN 'page'
          WHEN q.kind='group' AND q.phase='grouppost' THEN 'group_post'
          WHEN q.kind='group' THEN 'group_pitch'
          WHEN q.kind='kol_dm' THEN 'kol_dm'
          ELSE 'reply' END channel,
          count(*) total,
          sum(CASE WHEN q.status='draft' THEN 1 ELSE 0 END) drafts,
          sum(CASE WHEN q.status='approved' THEN 1 ELSE 0 END) approved,
          sum(CASE WHEN q.status='sent' THEN 1 ELSE 0 END) sent
        FROM queue q{where} GROUP BY channel ORDER BY total DESC""", args)]
    schedule = [dict(r) for r in c.execute(f"""
        SELECT q.id,q.campaign_id,c.name campaign_name,q.kind,q.phase,q.target_name,
               q.scheduled_date,q.status,q.image_hint
        FROM queue q JOIN campaigns c ON c.id=q.campaign_id
        {where} {'AND' if where else 'WHERE'} trim(coalesce(q.scheduled_date,''))<>''
        ORDER BY q.scheduled_date,q.id LIMIT 30""", args)]
    blockers = [dict(r) for r in c.execute(f"""
        SELECT q.id,q.campaign_id,c.name campaign_name,q.kind,q.phase,q.target_name,
               q.scheduled_date,q.status,
               CASE
                 WHEN (q.kind='page' OR (q.kind='group' AND q.phase='grouppost'))
                      AND (q.image_hint IS NULL OR trim(q.image_hint)='') THEN '缺少發布圖片'
                 WHEN trim(coalesce(q.target_url,''))='' AND q.kind<>'page' AND q.kind<>'reply' THEN '缺少目標網址'
                 ELSE '' END blocker
        FROM queue q JOIN campaigns c ON c.id=q.campaign_id
        {where} {'AND' if where else 'WHERE'}
          ((q.kind='page' OR (q.kind='group' AND q.phase='grouppost'))
             AND (q.image_hint IS NULL OR trim(q.image_hint)=''))
          OR (trim(coalesce(q.target_url,''))='' AND q.kind NOT IN ('page','reply'))
        ORDER BY q.scheduled_date,q.id LIMIT 50""", args)]
    jobs = [dict(r) for r in c.execute("""
        SELECT j.id,j.queue_id,j.method,j.state,j.attempts,j.requested_at,j.started_at,j.finished_at,
               j.external_url,j.error,q.target_name,c.name campaign_name
        FROM delivery_jobs j JOIN queue q ON q.id=j.queue_id
        JOIN campaigns c ON c.id=q.campaign_id
        WHERE (?=0 OR q.campaign_id=?) ORDER BY j.id DESC LIMIT 30""", (campaign_id, campaign_id))]
    target_counts = {r["cat"]: r["n"] for r in c.execute("SELECT cat,count(*) n FROM targets GROUP BY cat")}
    c.close()
    return {
        "campaigns": campaigns,
        "channels": channels,
        "schedule": schedule,
        "blockers": blockers,
        "jobs": jobs,
        "targets": {"total": sum(target_counts.values()), **target_counts},
        "live": auto_publish_enabled(),
        "generated_at": now(),
    }


@app.get("/api/network")
def marketing_network(campaign_id: int = 1):
    """戰情神經網路資料；沒有同步到的成效一律回 null，不製造展示數字。"""
    c = db()
    campaign = c.execute("SELECT id,name,hero,when_where FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
    if not campaign:
        c.close(); raise HTTPException(404, "找不到活動")
    rows = [dict(r) for r in c.execute("""SELECT q.id,q.kind,q.phase,q.target_name,q.target_url,
        q.scheduled_date,q.body,q.image_hint,q.status,q.sent_at,
        q.claimed_by,u.display_name claimed_by_name,
        j.external_url,j.external_id,j.state job_state
        FROM queue q LEFT JOIN delivery_jobs j ON j.id=(
          SELECT j2.id FROM delivery_jobs j2 WHERE j2.queue_id=q.id
          ORDER BY CASE WHEN j2.state='succeeded' THEN 0 ELSE 1 END,j2.id DESC LIMIT 1)
        LEFT JOIN users u ON u.id=q.claimed_by
        WHERE q.campaign_id=? AND (q.claimed_by IS NULL OR q.status='sent') ORDER BY q.id""", (campaign_id,))]
    c.close()
    for r in rows:
        r["channel"] = ("page" if r["kind"] == "page" else
                        "group" if r["kind"] == "group" and r["phase"] == "grouppost" else
                        "dm" if r["kind"] in ("group", "kol_dm") else "reply")
        r["image_url"] = f"/media/{r['image_hint']}" if r.get("image_hint") else ""
        r["comment_count"] = None
        r["reaction_count"] = None
        r["share_count"] = None
        r["comments_synced"] = False
    return {"campaign": dict(campaign), "posts": rows,
            "channels": ["page", "group", "dm", "threads", "instagram", "reply"]}


@app.post("/api/campaigns")
def create_campaign(c_in: CampaignIn):
    c = db()
    cur = c.execute("""INSERT INTO campaigns(name,hero,selling_points,when_where,audience,tone,incentive,created_at)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (c_in.name, c_in.hero, c_in.selling_points, c_in.when_where,
                     c_in.audience, c_in.tone, c_in.incentive, datetime.now().isoformat(timespec="seconds")))
    c.commit(); cid = cur.lastrowid; c.close()
    return {"id": cid}


# ---------------- 自動擬稿(照節拍排進佇列) ----------------
class AutodraftIn(BaseModel):
    start_date: str = ""      # YYYY-MM-DD,種趨勢從哪天開始鋪;預設今天
    burst_date: str = ""      # YYYY-MM-DD,引爆日(倒數/打卡的錨);預設 start+14
    kol_count: int = 3
    expand_targets: bool = True   # True=把稿配到真實社團/KOL名單;False=只生粉專稿+通用KOL範本


class AppendContentIn(BaseModel):
    channel: str = "page"       # page/grouppost/pitch/kol_dm
    count: int = 1
    direction: str = ""
    start_date: str = ""


@app.get("/api/targets")
def list_targets():
    c = db()
    try:
        rows = [dict(r) for r in c.execute("SELECT * FROM targets ORDER BY cat, ref_no")]
    except sqlite3.OperationalError:
        rows = []
    c.close()
    return rows


def _fill_kol_name(body, name):
    """把 GPT 產的各種稱呼佔位([網紅名稱]/[網紅姓名]/[達人名]…)換成真實 KOL 名;不動寄件人自己的[你的名字]。"""
    return re.sub(r'[\[［〔【][^\]］〕】]*(網紅|KOL|創作者|達人)[^\]］〕】]*[\]］〕】]', name, body)


def _spread(n, d0, d1):
    """回 n 個平均分佈在 [d0, d1] 的日期。"""
    if n <= 0:
        return []
    if n == 1 or d1 <= d0:
        return [d0] * n
    span = (d1 - d0).days
    return [d0 + timedelta(days=round(i * span / (n - 1))) for i in range(n)]


def _d(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def _schedule_dates(start, burst):
    """把各階段貼文的排程日算出來(節拍:趨勢鋪前段、揭曉中段、倒數引爆前2天、打卡引爆日)。"""
    span = max((burst - start).days, 4)
    return {
        "trend":    [start + timedelta(days=int(span * f)) for f in (0.0, 0.15, 0.30)],
        "reveal":   [start + timedelta(days=int(span * f)) for f in (0.45, 0.60, 0.72)],
        "countdown":[burst - timedelta(days=2), burst - timedelta(days=1)],
        "checkin":  [burst],
        "kol":      [start + timedelta(days=1)],  # 邀約早點發
    }


@app.post("/api/campaigns/{cid}/autodraft")
def autodraft(cid: int, a: AutodraftIn):
    c = db(); row = c.execute("SELECT * FROM campaigns WHERE id=?", (cid,)).fetchone()
    if not row:
        c.close(); raise HTTPException(404, "找不到活動")
    if row["package_created_at"]:
        c.close(); raise HTTPException(409, "這個活動已經建立過整套行銷作戰包，不能重複產生；請使用「追加內容」")
    brief = dict(row)

    start = _d(a.start_date) if a.start_date else datetime.now().date()
    burst = _d(a.burst_date) if a.burst_date else start + timedelta(days=14)
    dates = _schedule_dates(start, burst)

    # 生文案(GPT)
    copy = ai.generate_campaign_copy(brief)
    if copy.get("error"):
        c.close(); raise HTTPException(502, f"AI 生文失敗:{copy.get('error')} / {str(copy.get('raw',''))[:200]}")
    kol_dms = ai.draft_kol_dms(brief, n=max(a.kol_count, 1))

    now = datetime.now().isoformat(timespec="seconds")
    inserted = []

    def _as_text(x):
        if isinstance(x, str):
            return x
        if isinstance(x, dict):
            for k in ("body", "text", "content", "post", "message"):
                if isinstance(x.get(k), str):
                    return x[k]
            return json.dumps(x, ensure_ascii=False)
        return str(x)

    def add(kind, phase, body, sched, target_name="粉專", target_url="", note=""):
        cur = c.execute("""INSERT INTO queue(campaign_id,kind,phase,target_name,target_url,scheduled_date,body,status,created_at,note)
                           VALUES(?,?,?,?,?,?,?, 'draft', ?, ?)""",
                        (cid, kind, phase, target_name, target_url,
                         sched.isoformat() if sched else "", _as_text(body), now, note))
        inserted.append(cur.lastrowid)

    for i, t in enumerate(copy.get("trend", [])):
        add("page", "trend", t, dates["trend"][min(i, len(dates["trend"]) - 1)])
    for i, t in enumerate(copy.get("reveal", [])):
        add("page", "reveal", t, dates["reveal"][min(i, len(dates["reveal"]) - 1)])
    for i, t in enumerate(copy.get("countdown", [])):
        add("page", "countdown", t, dates["countdown"][min(i, len(dates["countdown"]) - 1)])
    for t in copy.get("checkin", []):
        add("page", "checkin", t, dates["checkin"][0])
    # ---- 配到真實社團/KOL 名單(expand_targets) ----
    targets = []
    if a.expand_targets:
        try:
            targets = [dict(r) for r in c.execute("SELECT * FROM targets ORDER BY cat, ref_no")]
        except sqlite3.OperationalError:
            targets = []

    if targets:
        groups = [t for t in targets if t["cat"] == "group"]
        kols = [t for t in targets if t["cat"] == "kol"]
        # 社團貼文的內容池(揭曉+倒數輪替),私訊社團用 pitch 範本
        post_pool = (copy.get("reveal", []) + copy.get("countdown", [])) or copy.get("trend", []) or [""]
        pitch_tmpl = ai.draft_group_pitch(brief)

        POST_KEYS = ("可入社發文", "發文", "揪團", "心得", "景點", "探店", "口吻", "來拍")
        posties = [g for g in groups if any(k in (g.get("action") or "") for k in POST_KEYS)]
        pitchies = [g for g in groups if g not in posties]

        # 社團貼文:排在揭曉→引爆前一天
        pdates = _spread(len(posties), dates["reveal"][0], burst - timedelta(days=1))
        for i, g in enumerate(posties):
            body = _as_text(post_pool[i % len(post_pool)])
            add("group", "grouppost", body, pdates[i] if i < len(pdates) else dates["reveal"][0],
                target_name=f"{g['name']} · {g['channel']}", target_url=g["handle_url"],
                note=f"{g['verified']} {g.get('action','')}｜{g.get('note','')}｜建議改在地口吻")
        # 社團私訊/投稿:排在前段(公開前先私下鋪)
        qdates = _spread(len(pitchies), start, dates["reveal"][0])
        for i, g in enumerate(pitchies):
            body = pitch_tmpl.replace("〔對象名〕", g["name"])
            add("group", "pitch", body, qdates[i] if i < len(qdates) else start,
                target_name=f"{g['name']} · {g['channel']}", target_url=g["handle_url"],
                note=f"{g['verified']} {g.get('action','')}｜{g.get('note','')}")
        # KOL 私訊:每個 KOL 配一則(輪替角度範本,填真實名字),排早段
        kdates = _spread(len(kols), start + timedelta(days=1), dates["reveal"][0])
        for i, k in enumerate(kols):
            tmpl = kol_dms[i % len(kol_dms)] if kol_dms else {"body": ""}
            body = _fill_kol_name(_as_text(tmpl.get("body", "")), k["name"])
            add("kol_dm", "kol", body, kdates[i] if i < len(kdates) else start,
                target_name=f"{k['name']} · {k['channel']} {k.get('action','')}", target_url=k["handle_url"],
                note=f"{k['verified']}｜{k.get('note','')}")
    else:
        # 沒匯入名單 → 舊行為:通用 KOL 範本
        for dm in kol_dms:
            add("kol_dm", "kol", dm.get("body", ""), dates["kol"][0],
                target_name=f"KOL(〔待填實際對象〕· {dm.get('angle','')})")

    # 留言回覆範本存成參考(不排日期)
    for rt in copy.get("reply_templates", []):
        add("reply", "reply", f"情境:{rt.get('situation','')}\n回覆:{rt.get('reply','')}", None,
            target_name="留言回覆範本")

    c.execute("UPDATE campaigns SET copy_json=?,package_created_at=? WHERE id=?",
              (json.dumps(copy, ensure_ascii=False), now, cid))
    c.commit(); c.close()
    return {"inserted": len(inserted), "burst_date": burst.isoformat(), "start_date": start.isoformat()}


@app.post("/api/campaigns/{cid}/append-content")
def append_campaign_content(cid: int, body: AppendContentIn, request: Request):
    """作戰包建立後只追加指定渠道的數量，不重做或覆蓋原作戰包。"""
    mapping = {
        "page": ("page", "manual", "page"),
        "grouppost": ("group", "grouppost", "group"),
        "pitch": ("group", "pitch", "group"),
        "kol_dm": ("kol_dm", "kol", "kol"),
    }
    if body.channel not in mapping:
        raise HTTPException(400, "不支援的內容類型")
    if not 1 <= body.count <= 20:
        raise HTTPException(400, "每次可追加 1–20 篇")
    direction = body.direction.strip()
    if len(direction) < 4:
        raise HTTPException(400, "請輸入至少 4 個字的追加行銷方向")
    try:
        start = _d(body.start_date) if body.start_date else datetime.now().date()
    except ValueError:
        raise HTTPException(400, "開始日期格式不正確")

    c = db(); campaign = c.execute("SELECT * FROM campaigns WHERE id=?", (cid,)).fetchone()
    if not campaign:
        c.close(); raise HTTPException(404, "找不到活動")
    if not campaign["package_created_at"]:
        c.close(); raise HTTPException(400, "請先產生這個活動的第一套行銷作戰包")
    kind, phase, target_cat = mapping[body.channel]
    targets = [] if target_cat == "page" else [dict(r) for r in c.execute(
        "SELECT * FROM targets WHERE cat=? ORDER BY ref_no", (target_cat,))]
    c.close()
    if target_cat != "page" and not targets:
        raise HTTPException(400, "這個渠道還沒有可用的發布目標名單")

    made = []
    try:
        for i in range(body.count):
            target = targets[i % len(targets)] if targets else None
            target_name = target["name"] if target else "粉專"
            generated = ai.generate_partner_content(dict(campaign), direction, body.channel, target_name)
            image_name = ""
            if body.channel in ("page", "grouppost"):
                image_bytes = ai.generate_image(generated["image_prompt"])
                image_name = f"append_{request.state.user['id']}_{secrets.token_hex(8)}.png"
                (UPLOADS / image_name).write_bytes(image_bytes)
            made.append((target_name, target["handle_url"] if target else os.environ.get("FB_PAGE_URL", ""),
                         generated["body"], image_name, (start + timedelta(days=i)).isoformat()))
    except Exception as exc:
        raise HTTPException(502, f"AI 追加內容失敗：{exc}")

    c = db(); ids = []
    for target_name, target_url, copy_body, image_name, schedule in made:
        cur = c.execute("""INSERT INTO queue(campaign_id,kind,phase,target_name,target_url,scheduled_date,
            body,image_hint,status,created_at,note) VALUES(?,?,?,?,?,?,?,?, 'draft', ?, ?)""",
            (cid, kind, phase, target_name, target_url, schedule, copy_body, image_name, now(),
             f"作戰包追加｜{direction}"))
        ids.append(cur.lastrowid)
    c.commit(); c.close()
    audit(request.state.user["id"], "追加行銷內容", "campaign", cid,
          {"channel": body.channel, "count": len(ids), "direction": direction})
    return {"ok": True, "inserted": len(ids), "ids": ids}


# ---------------- 佇列:讀 / 審 / 送 ----------------
class ManualQueueIn(BaseModel):
    campaign_id: int
    suggestion_id: int = 0
    direction_title: str = ""
    kind: str = "page"
    phase: str = "manual"
    target_name: str = ""
    target_url: str = ""
    scheduled_date: str = ""
    body: str
    note: str = ""


@app.post("/api/queue")
def create_manual_item(item: ManualQueueIn, request: Request):
    """建立自由單篇內容；可不選建議題目，再由前端決定存稿或立即發佈。"""
    allowed = {
        ("page", "manual"),
        ("group", "grouppost"),
        ("group", "pitch"),
        ("kol_dm", "kol"),
    }
    if (item.kind, item.phase) not in allowed:
        raise HTTPException(400, "不支援的發佈渠道")
    body = item.body.strip()
    if not body:
        raise HTTPException(400, "請輸入貼文內容")
    if len(body) > 20000:
        raise HTTPException(400, "貼文內容不得超過 20,000 字")
    scheduled = item.scheduled_date.strip()
    if scheduled:
        try:
            datetime.fromisoformat(scheduled)
        except ValueError:
            raise HTTPException(400, "排程日期時間格式不正確")
    target_name = item.target_name.strip() or ("粉專" if item.kind == "page" else "待指定目標")
    c = db()
    campaign = c.execute("SELECT id FROM campaigns WHERE id=?", (item.campaign_id,)).fetchone()
    if not campaign:
        c.close(); raise HTTPException(404, "找不到活動")
    direction_title = item.direction_title.strip() or "自由新增"
    cur = c.execute("""INSERT INTO queue(
        campaign_id,kind,phase,target_name,target_url,scheduled_date,body,status,created_at,note
        ) VALUES(?,?,?,?,?,?,?,'draft',?,?)""",
        (item.campaign_id, item.kind, item.phase, target_name, item.target_url.strip(),
         scheduled, body, now(),
         f"行銷方向：{direction_title}｜{item.note.strip()}".rstrip("｜")))
    qid = cur.lastrowid
    c.commit(); c.close()
    audit(request.state.user["id"], "自由新增單篇草稿", "queue", qid,
          {"kind": item.kind, "scheduled_date": scheduled,
           "suggestion_id": item.suggestion_id, "direction_title": direction_title})
    return {"ok": True, "id": qid, "status": "draft"}


@app.get("/api/queue")
def list_queue(campaign_id: int = 0, status: str = "", kind: str = "", phase: str = ""):
    c = db()
    # 內容中心只管理「原始行銷內容」；認領後的個人執行副本不再重複顯示。
    q = """SELECT source.*,
        claimed.id claimed_queue_id,claimed.status claimed_status,claimed.claimed_at,
        u.display_name claimed_by_name,j.id job_id,j.state job_state
        FROM queue source
        LEFT JOIN queue claimed ON claimed.id=(
          SELECT c2.id FROM queue c2 WHERE c2.source_queue_id=source.id ORDER BY c2.id DESC LIMIT 1)
        LEFT JOIN users u ON u.id=claimed.claimed_by
        LEFT JOIN delivery_jobs j ON j.id=(
          SELECT j2.id FROM delivery_jobs j2 WHERE j2.queue_id=claimed.id ORDER BY j2.id DESC LIMIT 1)
        WHERE source.source_queue_id IS NULL"""
    p = []
    if campaign_id:
        q += " AND source.campaign_id=?"; p.append(campaign_id)
    if status:
        if status == "draft":
            q += " AND source.status='draft' AND claimed.id IS NULL"
        elif status == "approved":
            q += " AND source.status='approved' AND claimed.id IS NULL"
        elif status == "claimed":
            q += " AND claimed.id IS NOT NULL AND claimed.status<>'sent'"
        elif status == "sent":
            q += " AND claimed.status='sent'"
        elif status == "skipped":
            q += " AND source.status='skipped'"
    if kind:
        q += " AND source.kind=?"; p.append(kind)
    if phase:
        q += " AND source.phase=?"; p.append(phase)
    q += " ORDER BY (source.scheduled_date=''), source.scheduled_date, source.id"
    rows = [dict(r) for r in c.execute(q, p)]; c.close()
    for r in rows:
        r["kind_label"] = KIND_LABEL.get(r["kind"], r["kind"])
        r["phase_label"] = PHASE_LABEL.get(r["phase"], r["phase"])
        # 沿用舊前端的樣式名，但語意已改為內容分配進度。
        r["status"] = ("sent" if r.get("claimed_status") == "sent" else
                       "claimed" if r.get("claimed_queue_id") else
                       "skipped" if r.get("status") == "skipped" else r.get("status"))
    return rows


@app.get("/api/queue/{qid}")
def get_item(qid: int):
    c = db(); r = c.execute("SELECT * FROM queue WHERE id=?", (qid,)).fetchone(); c.close()
    if not r:
        raise HTTPException(404, "找不到")
    return dict(r)


class EditIn(BaseModel):
    body: str


class RegenerateIn(BaseModel):
    mode: str = "both"  # copy/image/both
    instruction: str = ""


@app.post("/api/queue/{qid}/regenerate")
def regenerate_item(qid: int, req: RegenerateIn):
    if req.mode not in ("copy", "image", "both"):
        raise HTTPException(400, "mode 必須是 copy、image 或 both")
    c = db(); row = c.execute("""SELECT q.*,c.name,c.hero,c.selling_points,c.when_where,c.audience,c.contact_info
        FROM queue q JOIN campaigns c ON c.id=q.campaign_id WHERE q.id=?""", (qid,)).fetchone()
    if not row:
        c.close(); raise HTTPException(404, "找不到稿件")
    if row["status"] != "draft":
        c.close(); raise HTTPException(400, "只有待審稿可以重做")
    item = dict(row); new_body = item["body"]; new_image = item["image_hint"] or ""
    source = None
    if item["phase"] == "trend":
        sources = [
            {"name": "Malay Mail", "title": "Clubbing without alcohol in broad daylight: What is ‘coffee rave’?",
             "url": "https://www.malaymail.com/news/life/2025/06/01/clubbing-without-alcohol-in-bright-daylight-what-is-coffee-rave-the-new-music-and-cafe-trend-brewing-in-kl/178549",
             "image": "news_malaymail_coffee_raves.png"},
            {"name": "Gallup", "title": "U.S. Drinking Rate at New Low as Alcohol Concerns Surge",
             "url": "https://news.gallup.com/poll/693362/drinking-rate-new-low-alcohol-concerns-surge.aspx",
             "image": "news_gallup_drinking_rate.png"},
        ]
        current = next((i for i, s in enumerate(sources) if s["image"] == new_image), -1)
        source = sources[(current + 1) % len(sources)]
    if req.mode in ("image", "both") and (item["kind"] == "page" or item["phase"] == "grouppost"):
        if source:
            new_image = source["image"]
            library = []
        else:
            library = sorted(p.name for p in UPLOADS.glob("legacy_edit_*.jpg"))
        if not source and not library:
            c.close(); raise HTTPException(400, "真實圖片素材庫是空的")
        if not source:
            try: idx = library.index(new_image)
            except ValueError: idx = -1
            new_image = library[(idx + 1) % len(library)]
    if req.mode in ("copy", "both"):
        try:
            new_body = ai.rewrite_post(item["body"], item["target_name"], item["phase"], item,
                                       req.instruction, source)
            # 活動資料已經存在時，AI 一鍵改寫後直接補齊常見佔位符。
            if (item.get("when_where") or "").strip():
                new_body = re.sub(r"[[［〔【](?:待填)?(?:活動)?日期時間[]］〕】]", item["when_where"], new_body)
                new_body = new_body.replace("〔待填〕舉行", item["when_where"] + " 舉行")
            if (item.get("hero") or "").strip():
                new_body = re.sub(r"[[［〔【](?:您的名字|你的名字|我的名字)[]］〕】]", item["hero"], new_body)
        except Exception as exc:
            c.close(); raise HTTPException(502, f"AI 重寫失敗：{exc}")
    c.execute("UPDATE queue SET body=?,image_hint=? WHERE id=?", (new_body, new_image, qid))
    c.commit(); c.close()
    return {"ok": True, "body": new_body, "image_url": f"/media/{new_image}" if new_image else ""}


@app.post("/api/queue/{qid}/image")
async def upload_queue_image(qid: int, request: Request, filename: str = "image.jpg"):
    ext = Path(filename).suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        raise HTTPException(400, "只支援 JPG、PNG、WEBP")
    body = await request.body()
    if not body or len(body) > 15 * 1024 * 1024:
        raise HTTPException(400, "圖片不可為空且不得超過 15MB")
    c = db(); row = c.execute("SELECT image_hint FROM queue WHERE id=?", (qid,)).fetchone()
    if not row:
        c.close(); raise HTTPException(404, "找不到稿件")
    name = f"queue_{qid}_{secrets.token_hex(5)}{ext}"
    (UPLOADS / name).write_bytes(body)
    old = row["image_hint"] or ""
    c.execute("UPDATE queue SET image_hint=? WHERE id=?", (name, qid)); c.commit(); c.close()
    if old and Path(old).name == old:
        try: (UPLOADS / old).unlink(missing_ok=True)
        except OSError: pass
    return {"ok": True, "image_url": f"/media/{name}"}


@app.post("/api/queue/{qid}/edit")
def edit_item(qid: int, e: EditIn):
    c = db(); c.execute("UPDATE queue SET body=? WHERE id=?", (e.body, qid)); c.commit(); c.close()
    return {"ok": True}


@app.post("/api/queue/{qid}/approve")
def approve_item(qid: int, dispatch: bool = False):
    c = db()
    item = c.execute("SELECT * FROM queue WHERE id=?", (qid,)).fetchone()
    if not item:
        c.close(); raise HTTPException(404, "找不到")
    if item["phase"] == "grouppost" and not (item["image_hint"] or "").strip():
        c.close(); raise HTTPException(400, "社團發文必須先附上圖片，才能送入認領池")
    if re.search(r"[[［〔【][^]］〕】]*(?:待填|您的名字|你的名字)[^]］〕】]*[]］〕】]", item["body"] or ""):
        c.close(); raise HTTPException(400, "文案還有〔待填〕或姓名佔位符，請直接修改或使用 AI 一鍵改寫後再核准")
    if item["phase"] in ("anchor", "reveal", "countdown", "checkin", "grouppost"):
        camp = c.execute("SELECT when_where,contact_info FROM campaigns WHERE id=?", (item["campaign_id"],)).fetchone()
        if not camp or not (camp["when_where"] or "").strip() or not (camp["contact_info"] or "").strip():
            c.close(); raise HTTPException(400, "揭曉／倒數／社團稿必須先設定活動時間地點與詢問方式")
    c.execute("UPDATE queue SET status='approved', approved_at=? WHERE id=?",
              (now(), qid))
    job_id = _queue_job(c, qid, _method_for(item["kind"])) if dispatch else None
    c.commit(); c.close()
    return {"ok": True, "job_id": job_id}


@app.post("/api/queue/{qid}/dispatch")
def dispatch_item(qid: int):
    c = db(); item = c.execute("SELECT * FROM queue WHERE id=?", (qid,)).fetchone()
    if not item:
        c.close(); raise HTTPException(404, "找不到")
    if item["status"] != "approved":
        c.close(); raise HTTPException(400, "必須先核准")
    if (item["kind"] == "page" or item["phase"] == "grouppost") and not (item["image_hint"] or "").strip():
        c.close(); raise HTTPException(400, "粉專／社團稿必須先附上圖片才能排入執行")
    jid = _queue_job(c, qid, _method_for(item["kind"]))
    c.commit(); c.close()
    return {"queued": True, "job_id": jid, "method": _method_for(item["kind"])}


@app.get("/api/jobs")
def list_jobs(state: str = ""):
    c = db(); sql = """SELECT j.*,q.target_name,q.target_url,q.kind,q.body,q.image_hint,q.scheduled_date
        FROM delivery_jobs j JOIN queue q ON q.id=j.queue_id"""
    args = []
    if state:
        sql += " WHERE j.state=?"; args.append(state)
    rows = [dict(r) for r in c.execute(sql + " ORDER BY j.id DESC", args)]
    c.close(); return rows


@app.delete("/api/queue/{qid}")
def delete_queue_item(qid: int, request: Request):
    """刪除未送出的自由稿或失敗認領；成功及執行中的工作禁止刪除。"""
    c = db()
    row = c.execute("SELECT * FROM queue WHERE id=?", (qid,)).fetchone()
    if not row:
        c.close(); raise HTTPException(404, "找不到這篇內容")
    source_id = row["source_queue_id"] or row["id"]
    source = c.execute("SELECT * FROM queue WHERE id=?", (source_id,)).fetchone()
    clones = c.execute("SELECT * FROM queue WHERE source_queue_id=?", (source_id,)).fetchall()
    family_ids = [source_id] + [x["id"] for x in clones]
    marks = ",".join("?" for _ in family_ids)
    jobs = c.execute(f"SELECT * FROM delivery_jobs WHERE queue_id IN ({marks})", family_ids).fetchall()
    if any(x["status"] == "sent" for x in [source, *clones]) or any(j["state"] == "succeeded" for j in jobs):
        c.close(); raise HTTPException(400, "已成功發布的內容不能在這裡刪除，請先到 Facebook 刪除原文")
    if any(j["state"] == "running" for j in jobs):
        c.close(); raise HTTPException(409, "這篇正在發布，暫時不能刪除")
    user = request.state.user
    owns_claim = any(x["claimed_by"] == user["id"] for x in clones)
    if user["role"] != "system_admin" and not owns_claim:
        c.close(); raise HTTPException(403, "只能刪除自己認領的失敗工作")

    # 一般中央稿只移除失敗的認領副本，讓原稿回到認領池；自由新增稿則整篇刪除。
    is_manual_source = source["phase"] == "manual"
    delete_ids = family_ids if is_manual_source or not clones else [x["id"] for x in clones]
    delete_marks = ",".join("?" for _ in delete_ids)
    c.execute(f"DELETE FROM delivery_jobs WHERE queue_id IN ({delete_marks})", delete_ids)
    c.execute(f"DELETE FROM queue WHERE id IN ({delete_marks})", delete_ids)
    c.commit(); c.close()
    audit(user["id"], "刪除未發布內容", "queue", qid,
          {"deleted_queue_ids": delete_ids, "kept_source": source_id not in delete_ids})
    return {"ok": True, "deleted": delete_ids, "source_returned_to_pool": source_id not in delete_ids}


@app.post("/api/jobs/run-page")
def run_next_page_job():
    """單人版：由面板觸發一筆粉專 API 任務；RPA 任務由 local_worker.py 領取。"""
    c = db(); job = c.execute("""SELECT j.*,q.body,q.phase FROM delivery_jobs j JOIN queue q ON q.id=j.queue_id
        WHERE j.state='queued' AND j.method='graph_api'
          AND (q.scheduled_date IS NULL OR q.scheduled_date='' OR q.scheduled_date<=?)
        ORDER BY CASE WHEN q.phase='anchor' THEN 0 ELSE 1 END,j.id LIMIT 1""", (now(),)).fetchone()
    if not job:
        c.close(); return {"ran": False}
    if re.search(r"[[［〔【][^]］〕】]*(?:待填|您的名字|你的名字)[^]］〕】]*[]］〕】]", job["body"] or ""):
        c.execute("UPDATE delivery_jobs SET state='needs_attention',finished_at=?,error=? WHERE id=?",
                  (now(), "文案還有未完成佔位符，請先修改或退回認領池", job["id"]))
        c.commit(); c.close(); return {"ran": True, "live": False, "job_id": job["id"]}
    c.execute("UPDATE delivery_jobs SET state='running',started_at=?,attempts=attempts+1 WHERE id=?", (now(), job["id"]))
    c.commit(); c.close()
    if not auto_publish_enabled():
        c = db(); c.execute("UPDATE delivery_jobs SET state='needs_attention',finished_at=?,error=? WHERE id=?",
                            (now(), "目前是安全模式；設定 ZAOSHEN_LIVE=1 才會真的發文", job["id"]))
        c.commit(); c.close(); return {"ran": True, "live": False, "job_id": job["id"]}
    # 沿用已驗證的送出流程
    try:
        return send_item(job["queue_id"], job_id=job["id"])
    except HTTPException as exc:
        c = db(); c.execute("UPDATE delivery_jobs SET state='failed',finished_at=?,error=? WHERE id=?",
                            (now(), str(exc.detail), job["id"])); c.commit(); c.close()
        raise


@app.post("/api/worker/claim")
def claim_rpa_job(request: Request):
    device = device_from_request(request); worker_id = f"device:{device['id']}"
    c = db(); c.execute("BEGIN IMMEDIATE")
    row = c.execute("""SELECT j.id job_id,j.queue_id,q.kind,q.phase,q.target_name,q.target_url,q.body,q.image_hint,q.scheduled_date
        FROM delivery_jobs j JOIN queue q ON q.id=j.queue_id
        WHERE j.state='queued' AND j.method='local_rpa'
          AND (q.claimed_by IS NULL OR q.claimed_by=?)
          AND (q.scheduled_date IS NULL OR q.scheduled_date='' OR q.scheduled_date<=?)
        ORDER BY j.id LIMIT 1""", (device["user_id"], now())).fetchone()
    if not row:
        c.commit(); c.close(); return {"job": None}
    if re.search(r"[[［〔【][^]］〕】]*(?:待填|您的名字|你的名字)[^]］〕】]*[]］〕】]", row["body"] or ""):
        c.execute("UPDATE delivery_jobs SET state='needs_attention',finished_at=?,error=? WHERE id=?",
                  (now(), "文案還有未完成佔位符，請先修改或退回認領池", row["job_id"]))
        c.commit(); c.close(); return {"job": None}
    c.execute("UPDATE delivery_jobs SET state='running',worker_id=?,started_at=?,attempts=attempts+1 WHERE id=?",
              (worker_id, now(), row["job_id"]))
    c.execute("UPDATE devices SET state='working',current_job=?,last_seen=? WHERE id=?",
              (f"工作 #{row['job_id']} · {row['target_name']}", now(), device["id"]))
    c.commit(); c.close(); return {"job": dict(row), "live": auto_publish_enabled()}


@app.get("/api/worker/media/{name}")
def worker_media(name: str, request: Request):
    """已配對 RPA 下載本次任務圖片，不公開使用者的裝置憑證。"""
    device_from_request(request)
    safe = Path(name).name
    path = UPLOADS / safe
    if safe != name or not path.is_file():
        raise HTTPException(404, "找不到任務圖片")
    return FileResponse(str(path))


class JobResult(BaseModel):
    state: str
    external_id: str = ""
    external_url: str = ""
    screenshot_path: str = ""
    error: str = ""


@app.post("/api/worker/jobs/{job_id}/result")
def finish_rpa_job(job_id: int, result: JobResult, request: Request):
    device = device_from_request(request)
    if result.state not in ("succeeded", "failed", "needs_attention"):
        raise HTTPException(400, "不支援的結果狀態")
    c = db(); job = c.execute("SELECT * FROM delivery_jobs WHERE id=?", (job_id,)).fetchone()
    if not job:
        c.close(); raise HTTPException(404, "找不到工作")
    c.execute("""UPDATE delivery_jobs SET state=?,finished_at=?,external_id=?,external_url=?,
                 screenshot_path=?,error=? WHERE id=?""",
              (result.state, now(), result.external_id, result.external_url,
               result.screenshot_path, result.error, job_id))
    if result.state == "succeeded":
        c.execute("UPDATE queue SET status='sent',sent_at=?,note=? WHERE id=?",
                  (now(), result.external_url or result.external_id, job["queue_id"]))
    c.execute("UPDATE devices SET state=?,current_job='',last_error=?,last_seen=? WHERE id=?",
              ("idle" if result.state == "succeeded" else "attention", result.error[:500], now(), device["id"]))
    c.commit(); c.close()
    audit(device["user_id"], f"RPA 工作 {result.state}", "job", job_id, {"error": result.error})
    return {"ok": True}


@app.post("/api/queue/{qid}/skip")
def skip_item(qid: int):
    c = db(); c.execute("UPDATE queue SET status='skipped' WHERE id=?", (qid,)); c.commit(); c.close()
    return {"ok": True}


@app.post("/api/queue/{qid}/send")
def send_item(qid: int, job_id: int = 0):
    """粉專:走 Graph API 直接發(仍須先 approved)。社團/KOL:回 manual,前端給複製鈕人工貼。"""
    c = db(); r = c.execute("SELECT * FROM queue WHERE id=?", (qid,)).fetchone()
    if not r:
        c.close(); raise HTTPException(404, "找不到")
    item = dict(r)
    if item["status"] != "approved":
        c.close(); raise HTTPException(400, "這篇還沒核准,先核准才能送")

    if item["kind"] == "page":
        pid, tok = os.environ.get("FB_PAGE_ID"), os.environ.get("FB_PAGE_TOKEN")
        if not pid or not tok:
            c.close(); raise HTTPException(400, "粉專 token 未設(FB_PAGE_ID/FB_PAGE_TOKEN)")
        import requests
        class TransientFacebookError(RuntimeError):
            pass

        def _finish(response, fallback):
            try:
                result = response.json()
            except ValueError:
                result = {}
            if response.status_code >= 500:
                raise TransientFacebookError(f"Facebook 暫時服務錯誤 HTTP {response.status_code}")
            if not response.ok or "error" in result:
                raise RuntimeError((result.get("error") or {}).get("message", fallback))
            return result

        def publish_once():
            """送出一次；只有連線層錯誤與 Facebook 5xx 交給外層安全重試。
            帶圖：優先用公開 URL 讓 FB 端自己抓圖（避開 HF→FB 大檔上傳逾時）；
            拿不到對外網址才退回 multipart 上傳。"""
            image_name = item.get("image_hint") or ""
            image_path = UPLOADS / Path(image_name).name if image_name else None
            if image_path and image_path.is_file():
                media_url = public_media_url(image_name)
                if media_url:
                    response = requests.post(
                        f"{GRAPH}/{pid}/photos",
                        data={"caption": item["body"], "url": media_url, "access_token": tok},
                        timeout=(10, 90))
                    return _finish(response, "圖片發佈失敗（URL 抓圖）")
                with image_path.open("rb") as fh:
                    response = requests.post(
                        f"{GRAPH}/{pid}/photos",
                        data={"caption": item["body"], "access_token": tok},
                        files={"source": fh}, timeout=(10, 150))
                return _finish(response, "圖片發佈失敗（上傳）")
            response = requests.post(
                f"{GRAPH}/{pid}/feed",
                data={"message": item["body"], "access_token": tok}, timeout=(10, 60))
            return _finish(response, "粉專發佈失敗")

        def find_existing_post():
            """POST 回應逾時時先查最近貼文；若 Facebook 已收到，就視為成功，避免重複發文。"""
            try:
                response = requests.get(
                    f"https://graph.facebook.com/v23.0/{pid}/feed",
                    params={"fields": "id,message,created_time", "limit": 10, "access_token": tok},
                    timeout=(10, 20))
                if not response.ok:
                    return None
                expected = (item["body"] or "").strip()
                head = expected[:60]
                for post in response.json().get("data", []):
                    msg = (post.get("message") or "").strip()
                    # 完全相等，或開頭 60 字相符（帶圖貼文的 caption 可能被 FB 稍作截斷）
                    if msg and (msg == expected or (head and msg.startswith(head))):
                        return {"id": post.get("id", ""), "recovered_after_timeout": True}
            except requests.exceptions.RequestException:
                pass
            return None

        MAX_ATTEMPTS = 4
        BACKOFF = {1: 3, 2: 8, 3: 15}
        last_err = ""
        try:
            retryable = (requests.exceptions.SSLError, requests.exceptions.Timeout,
                         requests.exceptions.ConnectionError, TransientFacebookError)
            for attempt in range(1, MAX_ATTEMPTS + 1):
                try:
                    res = publish_once()
                    break
                except retryable as ex:
                    last_err = f"{type(ex).__name__}: {ex}"
                    recovered = find_existing_post()
                    if recovered:
                        res = recovered
                        break
                    if attempt == MAX_ATTEMPTS:
                        raise
                    time.sleep(BACKOFF.get(attempt, 15))
        except Exception as ex:
            detail = f"FB 發文失敗（已自動重試 {MAX_ATTEMPTS} 次）：{last_err or ex}"
            c.close(); raise HTTPException(502, detail)
        post_id = res.get("post_id") or res.get("id", "")
        public_id = post_id.split("_", 1)[1] if "_" in post_id else post_id
        post_url = f"https://www.facebook.com/{pid}/posts/{public_id}" if public_id else ""
        c.execute("UPDATE queue SET status='sent', sent_at=?, note=? WHERE id=?",
                  (datetime.now().isoformat(timespec="seconds"), post_url or f"post_id={post_id}", qid))
        c.commit(); c.close()
        if job_id:
            c = db(); c.execute("UPDATE delivery_jobs SET state='succeeded',finished_at=?,external_id=?,external_url=? WHERE id=?",
                                (now(), post_id, post_url, job_id)); c.commit(); c.close()
        return {"sent": True, "via": "graph_api", "post_id": post_id, "post_url": post_url, "raw": res}
    else:
        # 社團/KOL/其他:人工貼。標記為已送(信任 Wayne 貼了)+回傳全文供複製。
        c.execute("UPDATE queue SET status='sent', sent_at=? WHERE id=?",
                  (datetime.now().isoformat(timespec="seconds"), qid))
        c.commit(); c.close()
        return {"sent": True, "via": "manual", "body": item["body"]}


class MarkSentIn(BaseModel):
    post_url: str = ""
    post_id: str = ""


@app.post("/api/queue/{qid}/mark-sent")
def mark_sent_external(qid: int, body: MarkSentIn):
    """本機粉專發文器發完後回報:此篇已由使用者電腦發出(HF 不自己連 FB)。
    只更新狀態,不做任何對外連線。需登入(全域中介層保護)。"""
    c = db(); r = c.execute("SELECT * FROM queue WHERE id=?", (qid,)).fetchone()
    if not r:
        c.close(); raise HTTPException(404, "找不到")
    note = body.post_url or (f"post_id={body.post_id}" if body.post_id else "已由本機發出")
    c.execute("UPDATE queue SET status='sent', sent_at=?, note=? WHERE id=?",
              (datetime.now().isoformat(timespec="seconds"), note, qid))
    c.execute("""UPDATE delivery_jobs SET state='succeeded', finished_at=?, external_id=?, external_url=?, error=NULL
                 WHERE queue_id=? AND state IN ('queued','running','failed','needs_attention')""",
              (now(), body.post_id, body.post_url, qid))
    c.commit(); c.close()
    return {"ok": True, "via": "local_page_poster"}


# ---------------- FB 狀態 ----------------
@app.get("/api/fb/status")
def fb_status():
    import requests
    pid, tok = os.environ.get("FB_PAGE_ID"), os.environ.get("FB_PAGE_TOKEN")
    if not pid or not tok:
        return {"connected": False, "msg": "尚未設定 FB_PAGE_ID / FB_PAGE_TOKEN"}
    try:
        response = requests.get(f"https://graph.facebook.com/v23.0/{pid}",
            params={"fields": "name", "access_token": tok}, timeout=30)
        d = response.json()
        if not response.ok or "error" in d:
            return {"connected": False, "msg": d["error"].get("message")}
        return {"connected": True, "page": d.get("name")}
    except Exception as e:
        return {"connected": False, "msg": str(e)}


@app.get("/api/fb/diag")
def fb_diag():
    """在 Space 內實測 HF→Facebook Graph 連線，找出 ReadTimeout 根因（IPv4/IPv6、DNS、耗時）。
    需登入（走全域中介層）。不回傳任何 token。"""
    import socket, time as _t
    import requests
    out = {
        "space_host": os.environ.get("SPACE_HOST") or os.environ.get("SPACE_ID", ""),
        "media_url_sample": public_media_url("sample.png"),
        "live_mode": auto_publish_enabled(),
        "has_page_token": bool(os.environ.get("FB_PAGE_TOKEN")),
        "checks": [],
    }
    try:
        import urllib3.util.connection as _u3
        out["forced_ipv4"] = _u3.allowed_gai_family() == socket.AF_INET
    except Exception:
        out["forced_ipv4"] = None
    # 每個 IP 家族的 TCP 連線耗時（IPv6 若半死會在這裡現形）
    for fam, label in [(socket.AF_INET, "IPv4"), (socket.AF_INET6, "IPv6")]:
        rec = {"family": label}
        try:
            infos = socket.getaddrinfo("graph.facebook.com", 443, fam, socket.SOCK_STREAM)
            ip = infos[0][4][0]; rec["ip"] = ip
            s = socket.socket(fam, socket.SOCK_STREAM); s.settimeout(8)
            t0 = _t.time(); s.connect((ip, 443)); rec["connect_s"] = round(_t.time() - t0, 3); s.close()
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"
        out["checks"].append(rec)
    # Proxy 環境變數(HF 可能強制走 proxy,會讓 POST 卡住)
    out["proxy_env"] = {k: os.environ.get(k) for k in
                        ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY", "no_proxy")
                        if os.environ.get(k)}
    # 實際 HTTPS GET（走強制 IPv4 的 requests）
    t0 = _t.time()
    try:
        r = requests.get(f"{GRAPH}/", timeout=(8, 20))
        out["https_get"] = {"status": r.status_code, "seconds": round(_t.time() - t0, 3)}
    except Exception as e:
        out["https_get"] = {"error": f"{type(e).__name__}: {e}", "seconds": round(_t.time() - t0, 3)}
    # 實際 HTTPS POST（測 POST 路徑是否被卡;打 root,FB 會快速拒絕,不會建立任何東西）
    t0 = _t.time()
    try:
        r = requests.post(f"{GRAPH}/", data={"probe": "1"}, timeout=(8, 25))
        out["https_post"] = {"status": r.status_code, "seconds": round(_t.time() - t0, 3)}
    except Exception as e:
        out["https_post"] = {"error": f"{type(e).__name__}: {e}", "seconds": round(_t.time() - t0, 3)}
    # 不帶 proxy 的 POST(繞過 HF proxy 直連)
    t0 = _t.time()
    try:
        r = requests.post(f"{GRAPH}/", data={"probe": "1"}, timeout=(8, 25),
                          proxies={"http": None, "https": None})
        out["https_post_noproxy"] = {"status": r.status_code, "seconds": round(_t.time() - t0, 3)}
    except Exception as e:
        out["https_post_noproxy"] = {"error": f"{type(e).__name__}: {e}", "seconds": round(_t.time() - t0, 3)}
    return out


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8800)

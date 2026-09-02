# -*- coding: utf-8 -*-
"""
==========================================================================================
 שומר הנתונים  ·  גרסה 5
 מריץ סקריפט פייתון פרטי על Hugging Face Space, עם אחסון ששורד restart
==========================================================================================

 מה חדש בגרסה 5 (לפי מה שביקשת):

 1) מדידת אחסון אמיתית ומדויקת.
    מה שראית - "0% בשימוש, 44040192.0 GB פנויים" - זה לא באג שלי, זה מה
    שהמערכת עצמה מחזירה. דלי אחסון (Storage Bucket) הוא לא דיסק אלא אחסון
    אובייקטים בסגנון S3 שמחובר לקונטיינר כ-volume. לאחסון אובייקטים אין
    "גודל דיסק", ולכן statvfs מחזיר מספר דמה ענק (אצלך 42 פטה-בייט).
    לכן כאן לא סומכים על statvfs בכלל: הקוד סורק את התיקייה בפועל ומחשב
    כמה נפח תופסים הקבצים שלך, ומשווה למכסת האחסון של החשבון.
    לפי התיעוד של HF: לחשבון חינמי יש 100GB אחסון פרטי. אם המכסה שלך
    שונה - שנה את STORAGE_QUOTA_GB ותקבל חישוב מדויק לפי המספר שלך.

 2) בדיקה אמיתית שהתיקייה /data באמת מחוברת כדלי.
    לא מספיק שהתיקייה קיימת. הקוד בודק: האם זו נקודת עגינה (mount) אמיתית,
    מה סוג מערכת הקבצים, האם אפשר לכתוב ולקרוא בחזרה, והכי חשוב - סמן
    שנשמר בעלייה הראשונה ונבדק בכל עלייה מחדש. אם הסמן שרד restart,
    זו הוכחה מעשית שהדלי באמת שומר. זה מוצג בממשק כ"מאומת".

 3) קובץ הפייתון תמיד נשאר ב-/data.
    הקוד שהדבקת נשמר בדיוק ב-/data/main.py (לא בתת-תיקייה), עם עותק
    שמור נוסף. שומר רץ כל חצי דקה ומוודא שהקובץ קיים - אם משהו מחק אותו,
    הוא משוחזר מיד. כשנגמר המקום: נמחקים *רק* קבצי אודיו, מהישן לחדש,
    ולעולם לא קבצי טקסט, ini, json, או קבצים בלי סיומת. אם למרות הכל אין
    מקום, הלוגים והזמניים עוברים לתיקייה חלופית - קובץ הפייתון נשאר.
    בעלייה, הדבר הראשון שקורה: בדיקה אם /data/main.py קיים, ואם כן -
    הרצה שלו מיד.

 4) קובץ הלוג נמחק כל 3 שעות ונוצר מחדש באותה שנייה.
    רק server.log. שום קובץ אחר לא נוגעים בו, והלוגים ממשיכים לזרום רצוף.

 ─────────────────────────────────────────────────────────────────────────────────────────
 נטפרי
 ─────────────────────────────────────────────────────────────────────────────────────────
 אין Gradio, אין WebSocket, אין SSE, אין CDN, אין פונט חיצוני, אין תלות חובה.
 כל דף נבנה בשרת ונשלח כ-HTML מוכן, כל פעולה היא טופס POST רגיל + redirect,
 והלוגים מתעדכנים בבקשה קצרה כל 2 שניות. עובד גם כשה-JavaScript חסום לגמרי.

 ─────────────────────────────────────────────────────────────────────────────────────────
 משתני סביבה (כולם אופציונליים)
 ─────────────────────────────────────────────────────────────────────────────────────────
   DATA_DIR           ברירת מחדל /data          תיקיית הדלי
   STORAGE_QUOTA_GB   ברירת מחדל 100            מכסת האחסון של החשבון, לחישוב מדויק
   LOG_RESET_HOURS    ברירת מחדל 3              כל כמה שעות למחוק את server.log
   APP_PORT           ברירת מחדל 7860
   CHILD_PORT         ברירת מחדל APP_PORT+1
   HF_TOKEN           רשות                      מפעיל גיבוי נוסף ל-dataset פרטי
   BACKUP_REPO        רשות                      ברירת מחדל <הספייס>-backup
   KEEP_AWAKE         ברירת מחדל 0 (הוסר הפינג הפנימי - ראה הערה)
==========================================================================================
"""

import base64
import hashlib
import hmac
import html
import http.client
import http.server
import io
import json
import os
import secrets
import shutil
import signal
import socket
import socketserver
import subprocess
import sys
import tarfile
import threading
import time
import traceback
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime

APP_NAME = "שומר הנתונים"
VERSION = "6.2"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GB = float(2 ** 30)
MB = float(2 ** 20)


# ==========================================================================================
# 1. בחירת תיקיית הנתונים  +  בדיקה אמיתית שהיא באמת מחוברת ושומרת
# ==========================================================================================

def _writable(path):
    """קיום התיקייה לא מספיק - בודקים כתיבה, קריאה חזרה, ומחיקה."""
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".dg_probe")
        token = secrets.token_hex(8)
        with open(probe, "w", encoding="utf-8") as f:
            f.write(token)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        with open(probe, "r", encoding="utf-8") as f:
            back = f.read()
        os.remove(probe)
        return back == token
    except Exception:
        return False


def read_mounts():
    out = []
    try:
        with open("/proc/mounts", "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                p = line.split()
                if len(p) >= 3:
                    out.append({"device": p[0], "point": p[1], "fstype": p[2],
                                "opts": p[3] if len(p) > 3 else ""})
    except Exception:
        pass
    return out


def mount_of(path):
    """מחזיר את רשומת העגינה שהנתיב נמצא תחתיה (הכי ספציפית)."""
    path = os.path.abspath(path)
    best = None
    for m in read_mounts():
        pt = m["point"]
        if path == pt or path.startswith(pt.rstrip("/") + "/"):
            if best is None or len(pt) > len(best["point"]):
                best = m
    return best


def resolve_data_dir():
    """
    1. DATA_DIR שהוגדר ידנית
    2. /data - כאן מתחבר דלי האחסון (Storage Bucket) או אחסון קבוע
    3. תיקייה מקומית ליד הקוד - זמנית, רק כגיבוי אחרון
    """
    env_dir = os.environ.get("DATA_DIR")
    if env_dir and _writable(env_dir):
        return os.path.abspath(env_dir)
    if _writable("/data"):
        return "/data"
    local = os.path.join(BASE_DIR, "data")
    _writable(local)
    return local


DATA_DIR = resolve_data_dir()

# תיקיית המערכת שלנו - מוסתרת בתוך הדלי כדי לא להתנגש בקבצים של הסקריפט שלך
STATE_DIR = os.path.join(DATA_DIR, ".dataguard")
os.makedirs(STATE_DIR, exist_ok=True)

# *** קובץ הפייתון שהדבקת - בדיוק כאן, ברמה הראשונה של הדלי ***
SCRIPT_FILE = os.path.join(DATA_DIR, "main.py")
SCRIPT_BAK = os.path.join(STATE_DIR, "main.py.bak")

AUTH_FILE = os.path.join(STATE_DIR, "auth.json")
CONF_FILE = os.path.join(STATE_DIR, "config.json")
SESS_FILE = os.path.join(STATE_DIR, "sessions.json")
MARKER_FILE = os.path.join(STATE_DIR, "storage_marker.json")
PID_FILE = os.path.join(STATE_DIR, "child.pid")
BOOT_FILE = os.path.join(STATE_DIR, "_boot.py")
SECRET_FILE = os.path.join(STATE_DIR, "secret.json")
SCRIPT_META = os.path.join(STATE_DIR, "script_meta.json")

# הקוד הגלוי, כשהוא מוצפן בדלי, חי רק כאן - בזיכרון הקונטיינר, לא באחסון הקבוע
RUNTIME_DIR = os.environ.get("RUNTIME_DIR") or "/tmp/.dg-runtime"


APP_PORT = int(os.environ.get("APP_PORT") or os.environ.get("PORT") or 7860)
CHILD_PORT = int(os.environ.get("CHILD_PORT") or (APP_PORT + 1))
LOG_RESET_HOURS = float(os.environ.get("LOG_RESET_HOURS") or 3)
QUOTA_GB_ENV = os.environ.get("STORAGE_QUOTA_GB")
DEFAULT_QUOTA_GB = 100.0          # מכסת אחסון פרטי בחשבון חינמי לפי התיעוד של HF
BACKUP_INTERVAL = int(os.environ.get("BACKUP_INTERVAL") or 3600)
# גיבוי אוטומטי חוזר ל-Hub כבוי כברירת מחדל. כתיבה תוכפתית ל-Hub דרך ה-API
# נראית כמו פעילות בוט אוטומטית מבחינת מדיניות HF, והיא חלק ממה שעלול היה
# לגרום להשעיה. גיבוי ידני (כפתור בלוח הבקרה) עדיין זמין כשמוגדר HF_TOKEN.
# כדי להחזיר גיבוי אוטומטי, הגדר AUTO_BACKUP=1 - אבל מומלץ להשאיר כבוי.
AUTO_BACKUP = (os.environ.get("AUTO_BACKUP", "0") not in ("0", "false", "no"))
KEEP_AWAKE = (os.environ.get("KEEP_AWAKE", "0") not in ("0", "false", "no"))

# ------------------------------------------------------------------------------------------
# שמירה על ערנות ונתיב בריאות  (גרסה 6.2)
# ------------------------------------------------------------------------------------------
# אין יותר פינג עצמי פנימי - הוא הוסר כי תעבורה מלאכותית של הקונטיינר אל עצמו
# נראית כמו פעילות בוט מבחינת HF. אם צריך למנוע שינה אחרי 48 שעות, מפנים שירות
# ניטור חיצוני (UptimeRobot / cron-job.org) לנתיב /__ping - זו דרך לגיטימית לגמרי.
#
#   PUBLIC_PING      1 (ברירת מחדל) = הנתיב /__ping פתוח ומחזיר "OK" בטקסט פשוט,
#                    בשביל ניטור חיצוני. אין בו שום מידע רגיש. אפשר לכבות עם 0.
#   SCAN_MINUTES     כל כמה דקות נסרק האחסון.
PUBLIC_PING = (os.environ.get("PUBLIC_PING", "1") not in ("0", "false", "no"))
SCAN_MINUTES = float(os.environ.get("SCAN_MINUTES") or 15)

SPACE_HOST = os.environ.get("SPACE_HOST") or ""
SPACE_ID = os.environ.get("SPACE_ID") or ""
PUBLIC_URL = (os.environ.get("PUBLIC_URL")
              or (f"https://{SPACE_HOST}" if SPACE_HOST else f"http://127.0.0.1:{APP_PORT}"))

HF_TOKEN = (os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
            or os.environ.get("HF_BACKUP_TOKEN") or "").strip()
BACKUP_REPO = (os.environ.get("BACKUP_REPO") or (f"{SPACE_ID}-backup" if SPACE_ID else "")).strip()

MAX_LOGIN_FAILS = 8
LOCKOUT_HOURS = 2
SESSION_DAYS = 30

# ------------------------------------------------------------------------------------------
# הגדרות אבטחה (גרסה 6)
# ------------------------------------------------------------------------------------------
#  MASK_STATUS        כבוי כברירת מחדל בגרסה 6.2. כשהיה פעיל, כל תשובה יצאה
#                     כ-200 - כולל שגיאות ו"אין הרשאה". זה בדיוק הדפוס של פרוקסי
#                     מתחמק, וככל הנראה חלק ממה שגרם ל-HF לסמן את המרחב. שרת רגיל
#                     מחזיר 404 על דף שלא קיים ו-401 על חוסר הרשאה, וזה מה שקורה
#                     עכשיו. הנתיבים החשאיים ממילא מגינים על הפאנל. MASK_STATUS=1 מחזיר.
#  MASK_PROXY_STATUS  כבוי. אם היה פעיל, גם תשובות הסקריפט שלך היו יוצאות כ-200.
#  CODE_KEY           אם מוגדר - קוד הפייתון נשמר בדלי מוצפן. שמור אותו ב-Secrets של
#                     הספייס, לא בדלי. בלעדיו הכל נשאר כמו קודם (טקסט רגיל).
#  SETUP_TOKEN        אם מוגדר - חובה להקליד אותו כדי לקבוע סיסמה במערכת לא מוגדרת.
#  BIND_SESSION       1 = עוגיית התחברות תקפה רק מאותו דפדפן שבו נוצרה.
MASK_STATUS = (os.environ.get("MASK_STATUS", "0") not in ("0", "false", "no"))
MASK_PROXY_STATUS = (os.environ.get("MASK_PROXY_STATUS", "0") not in ("0", "false", "no"))
BIND_SESSION = (os.environ.get("BIND_SESSION", "1") not in ("0", "false", "no"))
IP_LOGIN_FAILS = int(os.environ.get("IP_LOGIN_FAILS") or 5)
MIN_PASSWORD = int(os.environ.get("MIN_PASSWORD") or 10)
MAX_SESSIONS = int(os.environ.get("MAX_SESSIONS") or 5)
SETUP_WINDOW_MIN = float(os.environ.get("SETUP_WINDOW_MIN") or 15)
RL_ADMIN_HITS = int(os.environ.get("RL_ADMIN_HITS") or 60)
RL_GLOBAL_HITS = int(os.environ.get("RL_GLOBAL_HITS") or 600)
RL_WINDOW = float(os.environ.get("RL_WINDOW") or 60)
MAX_FORM_BYTES = int(os.environ.get("MAX_FORM_BYTES") or 12 * 1024 * 1024)
MAX_PROXY_BODY = int(os.environ.get("MAX_PROXY_BODY") or 100 * 1024 * 1024)

BOOT_TS = time.time()
BOOT_SETUP_TOKEN = secrets.token_urlsafe(24)

# קבצי אודיו - *רק* אלה נמחקים כשנגמר המקום
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".mp4", ".ogg", ".oga", ".opus", ".webm", ".aac",
             ".flac", ".amr", ".3gp", ".3gpp", ".wma", ".aiff", ".aif", ".caf", ".mkv",
             ".avi", ".mov", ".wmv", ".alaw", ".ulaw", ".pcm", ".gsm"}
# לעולם לא נוגעים באלה, בשום מצב
NEVER_DELETE_EXT = {".py", ".txt", ".ini", ".json", ".csv", ".cfg", ".conf", ".env",
                    ".md", ".yml", ".yaml", ".db", ".sqlite", ".pem", ".key"}


# ==========================================================================================
# 2. לוגים  ·  נמחקים כל 3 שעות ונוצרים מחדש מיד
# ==========================================================================================

_log_buf = deque(maxlen=3000)
_log_seq = 0
_log_lock = threading.Lock()
_log_state = {"dir": "", "path": "", "started": 0.0, "resets": 0, "fallback": False}


def pick_log_dir():
    """הלוגים יושבים בדלי. אם אין מקום או אין הרשאה - עוברים לתיקייה חלופית,
    בלי לגעת בקובץ הפייתון שנשאר בדלי."""
    for cand, fallback in ((os.path.join(STATE_DIR, "logs"), False),
                           ("/tmp/dataguard-logs", True),
                           (os.path.join(BASE_DIR, "logs"), True)):
        if _writable(cand):
            _log_state["fallback"] = fallback
            return cand
    _log_state["fallback"] = True
    return "/tmp"


def open_log_file(reason=""):
    d = pick_log_dir()
    _log_state["dir"] = d
    _log_state["path"] = os.path.join(d, "server.log")
    _log_state["started"] = time.time()
    try:
        with open(_log_state["path"], "a", encoding="utf-8") as f:
            f.write(f"\n===== server.log נפתח {datetime.now():%d/%m/%Y %H:%M:%S} {reason} =====\n")
    except Exception:
        pass


def reset_log_file():
    """מוחק את server.log בלבד ויוצר אותו מחדש באותה שנייה. שום קובץ אחר לא נוגעים בו."""
    path = _log_state.get("path")
    try:
        if path and os.path.exists(path):
            size = os.path.getsize(path)
            os.remove(path)
        else:
            size = 0
        _log_state["resets"] += 1
        open_log_file(f"(איפוס מחזורי #{_log_state['resets']})")
        log(f"🧽 server.log נמחק ונוצר מחדש ({size/MB:.1f} MB פונו). הלוגים ממשיכים לזרום.")
        return True
    except Exception as e:
        log(f"⚠️ איפוס הלוג נכשל: {e}")
        return False


def log(msg, tag="sys"):
    global _log_seq
    stamp = datetime.now().strftime("%H:%M:%S")
    text = str(msg).rstrip("\n")
    for line in text.split("\n"):
        with _log_lock:
            _log_seq += 1
            _log_buf.append({"i": _log_seq, "t": stamp, "g": tag, "m": line})
        try:
            sys.__stdout__.write(f"[{stamp}] {line}\n")
            sys.__stdout__.flush()
        except Exception:
            pass
    try:
        with open(_log_state["path"], "a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {text}\n")
    except Exception:
        try:
            open_log_file("(מעבר לתיקייה חלופית)")
        except Exception:
            pass


def logs_since(n):
    with _log_lock:
        return [x for x in _log_buf if x["i"] > n], _log_seq


open_log_file("(עליית השרת)")


# ==========================================================================================
# 3. קריאה וכתיבה בטוחה של קבצים
# ==========================================================================================

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return json.loads(json.dumps(default))


def write_text(path, text, retry_after_purge=True):
    """כתיבה אטומית. אם נגמר המקום - מפנים אודיו ומנסים שוב."""
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp, path)
        return True
    except OSError as e:
        try:
            os.remove(tmp)
        except Exception:
            pass
        if retry_after_purge and getattr(e, "errno", None) in (28, 122):   # ENOSPC / EDQUOT
            need = max(len(text.encode("utf-8")) * 4, int(200 * MB))
            freed, n = purge_audio(need, reason="כתיבה נכשלה מחוסר מקום")
            if freed > 0:
                return write_text(path, text, retry_after_purge=False)
        log(f"⚠️ כשל בכתיבת {os.path.basename(path)}: {e}")
        return False
    except Exception as e:
        log(f"⚠️ כשל בכתיבת {os.path.basename(path)}: {e}")
        return False


def save_json(path, data):
    return write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


DEFAULT_CONF = {
    "script_name": "main",
    "pip_packages": "",
    "autostart": True,
    "keepalive": True,
    "updated": 0,
}


# ==========================================================================================
# 4. מדידת אחסון אמיתית  ·  דלי אחסון הוא לא דיסק
# ==========================================================================================
#
# למה statvfs שיקר: דלי אחסון (Storage Bucket) הוא אחסון אובייקטים בסגנון S3
# שמחובר לקונטיינר כ-volume דרך FUSE. לאחסון אובייקטים אין קיבולת קבועה,
# ולכן מערכת הקבצים מדווחת מספר דמה ענק (אצלך 44,040,192 GB = 42 פטה-בייט).
# המספר האמיתי היחיד שיש הוא: כמה תופסים הקבצים שלך בפועל, מול מכסת החשבון.
# לכן כאן סורקים את התיקייה ומחשבים בעצמנו.

FAKE_FS_THRESHOLD = 4 * 2 ** 40      # מעל 4TB - סימן מובהק שהמספר הוא דמה
FUSE_TYPES = ("fuse", "s3fs", "goofys", "juicefs", "gcsfuse", "rclone", "9p", "nfs")

STORAGE = {
    "dir": DATA_DIR,
    "is_mount": False,
    "fstype": "",
    "device": "",
    "readonly": False,
    "kind": "ephemeral",
    "kind_he": "זמני",
    "fs_total": 0, "fs_free": 0, "fs_used": 0, "fs_reliable": False,
    "used_bytes": 0, "files": 0, "dirs": 0, "scan_partial": False,
    "scan_ts": 0.0, "scan_secs": 0.0, "scanning": False,
    "audio_bytes": 0, "audio_files": 0,
    "quota_bytes": 0, "quota_source": "",
    "boots": 0, "first_seen": 0.0, "verified": False,
    "write_ok": False,
    "last_purge": 0.0, "purged_total": 0,
}
_scan_lock = threading.Lock()


def fs_stats(path):
    try:
        st = os.statvfs(path)
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        return total, free, total - (st.f_bfree * st.f_frsize)
    except Exception:
        return 0, 0, 0


def scan_dir(path, budget=25.0, max_files=500_000):
    """מחשב את הנפח האמיתי של התיקייה. עם תקציב זמן, כי דלי מרוחק יכול להיות איטי."""
    total = files = dirs = 0
    audio_bytes = audio_files = 0
    partial = False
    t0 = time.time()
    stack = [path]
    while stack:
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except Exception:
            continue
        dirs += 1
        for e in entries:
            if time.time() - t0 > budget or files > max_files:
                partial = True
                stack = []
                break
            try:
                if e.is_symlink():
                    continue
                if e.is_dir(follow_symlinks=False):
                    stack.append(e.path)
                    continue
                sz = e.stat(follow_symlinks=False).st_size
                total += sz
                files += 1
                if os.path.splitext(e.name)[1].lower() in AUDIO_EXT:
                    audio_bytes += sz
                    audio_files += 1
            except Exception:
                continue
    return {"total": total, "files": files, "dirs": dirs, "partial": partial,
            "audio_bytes": audio_bytes, "audio_files": audio_files,
            "secs": time.time() - t0}


def refresh_storage(deep=True):
    """מרענן את כל תמונת האחסון. נקרא בעלייה, כל 10 דקות, ולפי בקשה מהממשק."""
    with _scan_lock:
        STORAGE["scanning"] = True
    try:
        m = mount_of(DATA_DIR)
        STORAGE["is_mount"] = os.path.ismount(DATA_DIR)
        STORAGE["fstype"] = (m or {}).get("fstype", "")
        STORAGE["device"] = (m or {}).get("device", "")
        STORAGE["readonly"] = "ro," in ((m or {}).get("opts", "") + ",")
        STORAGE["write_ok"] = _writable(DATA_DIR)

        total, free, used = fs_stats(DATA_DIR)
        STORAGE["fs_total"], STORAGE["fs_free"], STORAGE["fs_used"] = total, free, used
        looks_fake = (total <= 0) or (total > FAKE_FS_THRESHOLD)
        is_fuse = any(t in STORAGE["fstype"].lower() for t in FUSE_TYPES)
        STORAGE["fs_reliable"] = not looks_fake

        # סוג האחסון
        if STORAGE["is_mount"] and (is_fuse or looks_fake):
            STORAGE["kind"], STORAGE["kind_he"] = "bucket", "דלי אחסון"
        elif STORAGE["is_mount"]:
            STORAGE["kind"], STORAGE["kind_he"] = "volume", "אחסון קבוע"
        else:
            STORAGE["kind"], STORAGE["kind_he"] = "ephemeral", "זמני (לא מחובר)"

        # המכסה: קודם מה שהגדרת, אחרת גודל אמיתי אם הוא אמין, אחרת ברירת המחדל של HF
        if QUOTA_GB_ENV:
            try:
                STORAGE["quota_bytes"] = float(QUOTA_GB_ENV) * GB
                STORAGE["quota_source"] = "STORAGE_QUOTA_GB"
            except Exception:
                STORAGE["quota_bytes"] = DEFAULT_QUOTA_GB * GB
                STORAGE["quota_source"] = "ברירת מחדל"
        elif STORAGE["fs_reliable"]:
            STORAGE["quota_bytes"] = float(total)
            STORAGE["quota_source"] = "מערכת הקבצים"
        else:
            STORAGE["quota_bytes"] = DEFAULT_QUOTA_GB * GB
            STORAGE["quota_source"] = "מכסת חשבון חינמי ב-HF (100GB)"

        if deep:
            r = scan_dir(DATA_DIR)
            STORAGE.update({
                "used_bytes": r["total"], "files": r["files"], "dirs": r["dirs"],
                "scan_partial": r["partial"], "scan_secs": r["secs"], "scan_ts": time.time(),
                "audio_bytes": r["audio_bytes"], "audio_files": r["audio_files"],
            })
    except Exception:
        log("refresh_storage: " + traceback.format_exc().splitlines()[-1])
    finally:
        with _scan_lock:
            STORAGE["scanning"] = False
    return STORAGE


def used_pct():
    q = STORAGE.get("quota_bytes") or 0
    if q <= 0:
        return 0.0
    return min(100.0, STORAGE.get("used_bytes", 0) * 100.0 / q)


def free_bytes():
    """כמה נשאר: לפי המכסה, ואם מערכת הקבצים אמינה - הקטן מבין השניים."""
    by_quota = max(0.0, (STORAGE.get("quota_bytes") or 0) - STORAGE.get("used_bytes", 0))
    if STORAGE.get("fs_reliable") and STORAGE.get("fs_free"):
        return min(by_quota, float(STORAGE["fs_free"]))
    return by_quota


def fmt_size(b):
    b = float(b or 0)
    if b >= GB:
        return f"{b/GB:.2f} GB"
    if b >= MB:
        return f"{b/MB:.1f} MB"
    if b >= 1024:
        return f"{b/1024:.0f} KB"
    return f"{int(b)} B"


def verify_persistence():
    """
    ההוכחה האמיתית שהדלי שומר: סמן שנכתב בעלייה הראשונה ונקרא בכל עלייה.
    אם הוא שרד restart - הדלי עובד. אין דרך אמינה יותר לבדוק את זה מבפנים.
    """
    m = load_json(MARKER_FILE, {})
    boots = int(m.get("boots", 0)) + 1
    first = m.get("first_seen") or time.time()
    history = m.get("history", [])[-19:]
    history.append(round(time.time()))
    save_json(MARKER_FILE, {"boots": boots, "first_seen": first, "space": SPACE_ID,
                            "dir": DATA_DIR, "last_boot": time.time(), "history": history})
    STORAGE["boots"] = boots
    STORAGE["first_seen"] = first
    STORAGE["verified"] = boots >= 2
    return STORAGE["verified"]


# ==========================================================================================
# 5. פינוי מקום  ·  *רק* קבצי אודיו, מהישן לחדש
# ==========================================================================================

def _is_protected(path, name):
    if os.path.abspath(path) in (os.path.abspath(SCRIPT_FILE), os.path.abspath(SCRIPT_BAK)):
        return True
    if os.path.abspath(path).startswith(os.path.abspath(STATE_DIR)):
        return True
    ext = os.path.splitext(name)[1].lower()
    if ext == "":                      # קובץ בלי סיומת - לא נוגעים
        return True
    if ext in NEVER_DELETE_EXT:
        return True
    return False


def purge_audio(need_bytes=None, reason=""):
    """
    מוחק קבצי אודיו בלבד, מהישן לחדש, עד שהתפנה מספיק מקום.
    לא נוגע בקבצי טקסט, ini, json, קבצים בלי סיומת, קובץ הפייתון, או קבצי המערכת.
    """
    candidates = []
    stack = [DATA_DIR]
    while stack:
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except Exception:
            continue
        for e in entries:
            try:
                if e.is_symlink():
                    continue
                if e.is_dir(follow_symlinks=False):
                    if os.path.abspath(e.path) != os.path.abspath(STATE_DIR):
                        stack.append(e.path)
                    continue
                if os.path.splitext(e.name)[1].lower() not in AUDIO_EXT:
                    continue
                if _is_protected(e.path, e.name):
                    continue
                st = e.stat(follow_symlinks=False)
                candidates.append((st.st_mtime, st.st_size, e.path))
            except Exception:
                continue
    if not candidates:
        log("ℹ️ אין קבצי אודיו למחיקה - לא נמחק שום דבר אחר.")
        return 0, 0

    candidates.sort()          # הישן ביותר ראשון
    freed = 0
    count = 0
    for _mt, sz, p in candidates:
        try:
            os.remove(p)
            freed += sz
            count += 1
        except Exception:
            continue
        if need_bytes and freed >= need_bytes:
            break
    STORAGE["last_purge"] = time.time()
    STORAGE["purged_total"] += count
    log(f"🧹 פונו {count} קבצי אודיו ({fmt_size(freed)}){' - ' + reason if reason else ''}. "
        f"קבצי טקסט, ini ו-json לא נגעו.")
    threading.Thread(target=lambda: refresh_storage(True), daemon=True).start()
    return freed, count


def space_guard():
    """בודק לחץ מקום ומפנה אודיו אם צריך. מחזיר 'ok' / 'warn' / 'critical'."""
    pct = used_pct()
    fb = free_bytes()
    if pct >= 95 or fb < 150 * MB:
        need = max(int((STORAGE.get("quota_bytes") or 0) * 0.15), int(500 * MB))
        log(f"⚠️ המקום כמעט נגמר ({pct:.1f}% מהמכסה, נשאר {fmt_size(fb)}) - מפנה אודיו ישן.")
        purge_audio(need, reason="לחץ מקום")
        return "critical"
    if pct >= 80:
        return "warn"
    return "ok"


# ==========================================================================================
# 6. השומר על קובץ הפייתון  ·  הוא תמיד חייב להיות ב-/data
# ==========================================================================================

def save_script(code):
    """
    שומר את הקוד ב-/data/main.py ומחזיק עותק שמור. אם אין מקום - מפנה אודיו קודם.
    חדש בגרסה 6: אם הוגדר CODE_KEY, מה שנכתב לדלי הוא מעטפת מוצפנת ולא הקוד עצמו,
    ובנוסף נשמרת "תעודת זהות" של הקוד (שורות, גודל, טביעת אצבע) - כדי שלוח הבקרה
    יוכל להציג מידע עליו בלי לקרוא אותו ובלי לשלוח אותו לדפדפן.
    """
    blob = encrypt_text(code) if CODE_KEY else code
    ok = write_text(SCRIPT_FILE, blob)
    write_text(SCRIPT_BAK, blob)
    _chmod(SCRIPT_FILE, 0o600)
    _chmod(SCRIPT_BAK, 0o600)
    if ok:
        _secure_save(SCRIPT_META, {
            "exists": True,
            "lines": len(code.splitlines()),
            "bytes": len(code.encode("utf-8")),
            "sha": hashlib.sha256(code.encode("utf-8")).hexdigest(),
            "encrypted": bool(CODE_KEY),
            "ts": time.time(),
        })
        log(f"💾 הקוד נשמר ב-{SCRIPT_FILE} ({len(code.splitlines())} שורות)"
            f"{' · מוצפן בדלי' if CODE_KEY else ''}")
    return ok


def read_script():
    """מחזיר את הקוד הגלוי. מפענח לבד אם מה ששמור בדלי מוצפן."""
    for p in (SCRIPT_FILE, SCRIPT_BAK):
        try:
            if os.path.exists(p) and os.path.getsize(p) > 0:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    raw = f.read()
                return decrypt_text(raw) if is_encrypted(raw) else raw
        except Exception:
            continue
    return ""


def script_meta():
    """תעודת הזהות של הקוד, כדי לא לפענח ולא לקרוא אותו בכל טעינת דף."""
    m = load_json(SCRIPT_META, {})
    if m.get("exists") and os.path.exists(SCRIPT_FILE):
        return m
    try:
        if not (os.path.exists(SCRIPT_FILE) and os.path.getsize(SCRIPT_FILE) > 0):
            return {"exists": False}
        with open(SCRIPT_FILE, "r", encoding="utf-8", errors="replace") as f:
            head = f.read(24)
        code = read_script()
    except Exception:
        return {"exists": True, "lines": 0, "bytes": 0, "sha": "",
                "encrypted": True, "ts": 0}
    m = {"exists": True,
         "lines": len(code.splitlines()),
         "bytes": len(code.encode("utf-8")),
         "sha": hashlib.sha256(code.encode("utf-8")).hexdigest(),
         "encrypted": is_encrypted(head),
         "ts": os.path.getmtime(SCRIPT_FILE)}
    _secure_save(SCRIPT_META, m)
    return m


def ensure_script_present(quiet=True):
    """
    רץ בכל מחזור של השומר: מוודא שקובץ הפייתון קיים ב-/data.
    אם הוא נעלם משום סיבה - משוחזר מיד מהעותק השמור.
    """
    try:
        if os.path.exists(SCRIPT_FILE) and os.path.getsize(SCRIPT_FILE) > 0:
            return True
    except Exception:
        pass
    if os.path.exists(SCRIPT_BAK):
        try:
            with open(SCRIPT_BAK, "r", encoding="utf-8", errors="replace") as f:
                code = f.read()
            if code.strip():
                write_text(SCRIPT_FILE, code)
                log(f"🛟 קובץ הפייתון חזר ל-{SCRIPT_FILE} מהעותק השמור.")
                return True
        except Exception as e:
            log(f"⚠️ שחזור קובץ הפייתון נכשל: {e}")
    if not quiet:
        log("ℹ️ אין עדיין קוד שמור בדלי.")
    return False


# ==========================================================================================
# 7. גיבוי רשות ל-dataset פרטי (רק אם הוגדר HF_TOKEN)
# ==========================================================================================

BACKUP_SKIP_DIRS = {"__pycache__", "bin", "logs", "audio_tmp", "tmp", ".git",
                    ".cache", "node_modules", "venv", ".venv", ".restore"}
BACKUP_SKIP_EXT = AUDIO_EXT | {".log", ".tmp", ".pyc", ".part", ".zip", ".gz", ".tar"}
# אלה לעולם לא עולים לגיבוי: מי שישיג את מאגר הגיבוי לא יקבל איתם את הסיסמה,
# את הסוד שממנו נגזרים הנתיבים החשאיים, או עוגיות התחברות פעילות.
BACKUP_SKIP_NAMES = {"auth.json", "sessions.json", "secret.json", "child.pid"}
MAX_BACKUP_FILE = 8 * 1024 * 1024

_backup = {"enabled": False, "last_ok": 0, "last_error": "", "last_hash": "", "busy": False}
_backup_lock = threading.Lock()


def _ensure_hf_lib():
    try:
        import huggingface_hub  # noqa: F401
        return True
    except Exception:
        pass
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "huggingface_hub"],
                       capture_output=True, timeout=300)
        import huggingface_hub  # noqa: F401
        return True
    except Exception as e:
        _backup["last_error"] = f"{e}"[:120]
        return False


def backup_init(force=False):
    """
    מכין את הגיבוי ל-Hub. חשוב: בברירת מחדל *לא* יוצר repo בעלייה, כי יצירת/
    גישה ל-repo היא כתיבה ל-Hub, וכתיבה כזו בכל עלייה נראית כמו פעילות בוט
    אוטומטית מבחינת מדיניות HF. הוא ירוץ בפועל רק אם:
      · AUTO_BACKUP=1 (גיבוי אוטומטי הופעל במפורש), או
      · המשתמש לחץ על כפתור הגיבוי הידני (force=True).
    כך בהתקנה רגילה שום דבר לא נכתב ל-Hub אלא אם ביקשת.
    """
    if not (force or AUTO_BACKUP):
        _backup["last_error"] = "גיבוי כבוי (הפעל AUTO_BACKUP או לחץ גיבוי ידני)"
        return False
    if not HF_TOKEN:
        _backup["last_error"] = "לא הוגדר HF_TOKEN (רשות)"
        return False
    if not BACKUP_REPO or "/" not in BACKUP_REPO:
        _backup["last_error"] = "BACKUP_REPO לא תקין"
        return False
    if _backup["enabled"]:
        return True
    if not _ensure_hf_lib():
        return False
    try:
        from huggingface_hub import HfApi
        HfApi(token=HF_TOKEN).create_repo(repo_id=BACKUP_REPO, repo_type="dataset",
                                          private=True, exist_ok=True)
        _backup["enabled"] = True
        _backup["last_error"] = ""
        log(f"🗄️ גיבוי נוסף פעיל אל dataset פרטי: {BACKUP_REPO}")
        return True
    except Exception as e:
        _backup["last_error"] = f"{e}"[:160]
        log(f"⚠️ הגיבוי הנוסף לא הופעל: {e}")
        return False


def _iter_backup_files():
    stack = [DATA_DIR]
    while stack:
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except Exception:
            continue
        for e in entries:
            try:
                if e.is_symlink():
                    continue
                if e.is_dir(follow_symlinks=False):
                    if e.name not in BACKUP_SKIP_DIRS:
                        stack.append(e.path)
                    continue
                if e.name in BACKUP_SKIP_NAMES:
                    continue
                if os.path.splitext(e.name)[1].lower() in BACKUP_SKIP_EXT:
                    continue
                if e.stat(follow_symlinks=False).st_size > MAX_BACKUP_FILE:
                    continue
                yield e.path, os.path.relpath(e.path, DATA_DIR).replace(os.sep, "/")
            except Exception:
                continue


def _build_snapshot():
    buf = io.BytesIO()
    manifest = []
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for full, rel in _iter_backup_files():
            try:
                tar.add(full, arcname=rel)
                with open(full, "rb") as f:
                    manifest.append(rel + ":" + hashlib.sha256(f.read()).hexdigest())
            except Exception:
                continue
        meta = json.dumps({"ts": time.time(), "space": SPACE_ID,
                           "files": len(manifest), "version": VERSION}).encode()
        info = tarfile.TarInfo("_meta.json")
        info.size = len(meta)
        info.mtime = int(time.time())
        tar.addfile(info, io.BytesIO(meta))
    return buf.getvalue(), hashlib.sha256("|".join(sorted(manifest)).encode()).hexdigest(), len(manifest)


def backup_now(reason="", force=False):
    # אתחול עצל: אם הגיבוי עוד לא הופעל אבל המשתמש ביקש ידנית (force),
    # מקימים את ה-repo עכשיו. כך הכפתור הידני עובד בלי שהגיבוי ירוץ בכל עלייה.
    if not _backup["enabled"]:
        if force:
            if not backup_init(force=True):
                return False, _backup.get("last_error") or "הגיבוי אינו זמין"
        else:
            return False, "הגיבוי הנוסף אינו פעיל (רשות בלבד)"
    if _backup["busy"]:
        return False, "גיבוי כבר רץ"
    with _backup_lock:
        _backup["busy"] = True
        try:
            from huggingface_hub import HfApi
            data, digest, count = _build_snapshot()
            if not force and digest == _backup["last_hash"]:
                return True, "אין שינוי מאז הגיבוי האחרון"
            api = HfApi(token=HF_TOKEN)
            api.upload_file(path_or_fileobj=data, path_in_repo="snapshot.tar.gz",
                            repo_id=BACKUP_REPO, repo_type="dataset",
                            commit_message=f"backup {datetime.now():%Y-%m-%d %H:%M} {reason}".strip())
            try:
                api.upload_file(path_or_fileobj=data,
                                path_in_repo=datetime.now().strftime("history/%Y%m%d-%H.tar.gz"),
                                repo_id=BACKUP_REPO, repo_type="dataset", commit_message="hourly")
            except Exception:
                pass
            _backup["last_hash"] = digest
            _backup["last_ok"] = time.time()
            _backup["last_error"] = ""
            log(f"💾 גובו {count} קבצים ({len(data)//1024} KB) {reason}")
            return True, f"גובו {count} קבצים"
        except Exception as e:
            _backup["last_error"] = f"{e}"[:160]
            return False, f"{e}"[:160]
        finally:
            _backup["busy"] = False


def restore_backup(force=False):
    if not _backup["enabled"]:
        if force:
            if not backup_init(force=True):
                return False, _backup.get("last_error") or "הגיבוי אינו זמין"
        else:
            return False, "הגיבוי הנוסף אינו פעיל"
    try:
        from huggingface_hub import hf_hub_download
        path = hf_hub_download(repo_id=BACKUP_REPO, repo_type="dataset",
                               filename="snapshot.tar.gz", token=HF_TOKEN,
                               local_dir=os.path.join(STATE_DIR, ".restore"))
        n = 0
        with tarfile.open(path, "r:gz") as tar:
            for m in tar.getmembers():
                if not m.isfile() or m.name == "_meta.json":
                    continue
                if m.name.startswith(("/", "..")) or ".." in m.name:
                    continue
                tar.extract(m, DATA_DIR)
                n += 1
        log(f"♻️ שוחזרו {n} קבצים מהגיבוי הנוסף.")
        return True, f"שוחזרו {n} קבצים"
    except Exception as e:
        msg = f"{e}"[:160]
        if any(k in msg for k in ("404", "EntryNotFound", "RepoNotFound")):
            return False, "אין עדיין גיבוי במאגר"
        return False, msg


# ==========================================================================================
# 8. אימות
# ==========================================================================================

def hash_pw(password, salt=None):
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 150_000)
    return salt, dk.hex()


# ------------------------------------------------------------------------------------------
# 8א. הסוד המרכזי  ·  נוצר פעם אחת, חי בדלי, וממנו נגזרים כל הנתיבים החשאיים
# ------------------------------------------------------------------------------------------
# למה זה כאן: עד עכשיו כל הנתיבים היו קבועים וידועים מראש (/__login, /__health...).
# מי שיודע את שם התוכנה יודע לנחש אותם. מעכשיו כל נתיב ניהולי הוא מחרוזת ענקית
# שנגזרת מסוד אקראי של 64 בייט. אי אפשר לנחש אותה, אי אפשר לחשב אותה בלי הסוד,
# והיא זהה בכל עלייה מחדש (כי הסוד שמור בדלי) - כך שהסימנייה שלך תמשיך לעבוד.

_ALPHA = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _chmod(path, mode):
    try:
        os.chmod(path, mode)
    except Exception:
        pass


def _secure_save(path, data):
    ok = save_json(path, data)
    _chmod(path, 0o600)
    return ok


def _load_secret():
    d = load_json(SECRET_FILE, {})
    sec = str(d.get("secret") or "")
    pref = str(d.get("prefix") or "")
    if len(sec) != 128 or len(pref) < 24:
        sec = secrets.token_hex(64)
        pref = "".join(secrets.choice(_ALPHA) for _ in range(48))
        _secure_save(SECRET_FILE, {"secret": sec, "prefix": pref, "created": time.time()})
    return sec, pref


SERVER_SECRET, ADMIN_PREFIX = _load_secret()
SECRET_BYTES = bytes.fromhex(SERVER_SECRET)


def _sig(label, *parts):
    msg = "|".join([label] + [str(p) for p in parts]).encode("utf-8")
    return hmac.new(SECRET_BYTES, msg, hashlib.sha256).hexdigest()


# שמות העוגיות גם הם נגזרים מהסוד - אין "sid" קבוע שאפשר לחפש
_C1 = _sig("cookie", "session")[:22]
_C2 = _sig("cookie", "pre")[:22]
COOKIE_NAME = ("__Host-" + _C1) if SPACE_HOST else ("s" + _C1)
PRE_COOKIE = ("__Host-" + _C2) if SPACE_HOST else ("p" + _C2)

# הקשר לכל בקשה בנפרד: nonce ל-CSP ואסימון CSRF לטפסים
CTX = threading.local()


def new_nonce():
    n = secrets.token_urlsafe(18)
    CTX.nonce = n
    return n


def csrf_field():
    return f'<input type="hidden" name="_t" value="{html.escape(getattr(CTX, "csrf", ""), quote=True)}">'


def _eq(a, b):
    """
    השוואה בזמן קבוע שעובדת גם על עברית ועל כל תו אחר.
    למה זה קיים: hmac.compare_digest מסרב להשוות מחרוזות עם תווים שאינם ASCII
    וזורק TypeError. שם משתמש בעברית הפיל את ההתחברות. כאן ממירים לבייטים
    ומשווים אורך אחיד דרך SHA-256, כך שגם זמן ההשוואה לא מסגיר כלום.
    """
    ab = (a if isinstance(a, bytes) else str(a or "").encode("utf-8", "replace"))
    bb = (b if isinstance(b, bytes) else str(b or "").encode("utf-8", "replace"))
    return hmac.compare_digest(hashlib.sha256(ab).digest(), hashlib.sha256(bb).digest())


def route_path(name):
    """כל נתיב ניהולי = /<48 תווים אקראיים>/<64 תווים של HMAC>. 113 תווים שאי אפשר לנחש."""
    return "/" + ADMIN_PREFIX + "/" + _sig("route", name)


ROUTE_NAMES = ("home", "login", "logout", "setup", "run", "stop", "rescan", "purge",
               "resetlog", "backup", "restore", "logs", "health", "reveal")
ROUTES = {n: route_path(n) for n in ROUTE_NAMES}
ADMIN_BASE = "/" + ADMIN_PREFIX + "/"


def match_route(path):
    """התאמה בזמן קבוע, כדי שאי אפשר יהיה לגלות נתיב תו-אחר-תו לפי זמני תגובה."""
    if not path.startswith(ADMIN_BASE):
        return ""
    for name, p in ROUTES.items():
        if _eq(path, p):
            return name
    return "?"          # בתוך התחום הניהולי אבל לא נתיב מוכר - מקבל דמה


# ------------------------------------------------------------------------------------------
# 8ב. אסימוני CSRF  ·  אף פעולה לא מתבצעת בלי אסימון חתום שקשור לדפדפן שלך
# ------------------------------------------------------------------------------------------

def csrf_make(binding):
    ts = str(int(time.time()))
    return ts + "." + _sig("csrf", binding, ts)


def csrf_ok(binding, token, max_age=8 * 3600):
    try:
        ts, sig = str(token).split(".", 1)
        if abs(time.time() - int(ts)) > max_age:
            return False
        return _eq(_sig("csrf", binding, ts), sig)
    except Exception:
        return False


# ------------------------------------------------------------------------------------------
# 8ג. הצפנת קוד הפייתון במנוחה  (רשות - רק אם הגדרת CODE_KEY)
# ------------------------------------------------------------------------------------------
# בלי מפתח: הכל נשאר בדיוק כמו קודם, main.py נשמר כטקסט רגיל בדלי.
# עם מפתח (משתנה סביבה CODE_KEY / MASTER_KEY, שנשמר ב-Settings→Secrets ולא בדלי):
# הקובץ בדלי מכיל רק מעטפת מוצפנת. מי שמשיג גישה לדלי, לגיבוי או ל-HF_TOKEN
# מקבל ג'יבריש. הקוד הגלוי קיים רק בזיכרון ובקובץ זמני ב-/tmp שנמחק בכל restart.

CODE_KEY = (os.environ.get("CODE_KEY") or os.environ.get("MASTER_KEY") or "").strip()
ENC_MAGIC = "#dg-enc-v1"
_kdf_cache = {}


def _enc_keys(salt):
    k = _kdf_cache.get(salt)
    if k is None:
        dk = hashlib.pbkdf2_hmac("sha256", CODE_KEY.encode("utf-8"), salt, 200_000, dklen=64)
        k = (dk[:32], dk[32:])
        _kdf_cache[salt] = k
    return k


def _keystream(key, nonce, length):
    out = bytearray()
    ctr = 0
    while len(out) < length:
        out += hmac.new(key, nonce + ctr.to_bytes(8, "big"), hashlib.sha256).digest()
        ctr += 1
    return bytes(out[:length])


def is_encrypted(text):
    return isinstance(text, str) and text.startswith(ENC_MAGIC)


def encrypt_text(plain):
    """מעטפת ASCII נקייה, כדי שכל מנגנוני הכתיבה והשחזור הקיימים ימשיכו לעבוד כרגיל."""
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(16)
    ke, km = _enc_keys(salt)
    raw = plain.encode("utf-8")
    ct = bytes(a ^ b for a, b in zip(raw, _keystream(ke, nonce, len(raw))))
    tag = hmac.new(km, salt + nonce + ct, hashlib.sha256).hexdigest()
    env = {"v": 1, "alg": "pbkdf2-hmac-ctr-sha256", "s": salt.hex(), "n": nonce.hex(),
           "c": base64.b64encode(ct).decode("ascii"), "t": tag}
    return ENC_MAGIC + "\n" + json.dumps(env)


def decrypt_text(blob):
    if not CODE_KEY:
        raise RuntimeError("הקוד בדלי מוצפן אבל משתנה הסביבה CODE_KEY אינו מוגדר")
    env = json.loads(blob.split("\n", 1)[1])
    salt = bytes.fromhex(env["s"])
    nonce = bytes.fromhex(env["n"])
    ct = base64.b64decode(env["c"])
    ke, km = _enc_keys(salt)
    if not _eq(hmac.new(km, salt + nonce + ct, hashlib.sha256).hexdigest(), env["t"]):
        raise RuntimeError("חתימת הקוד המוצפן אינה תואמת - הקובץ שונה או המפתח שגוי")
    return bytes(a ^ b for a, b in zip(ct, _keystream(ke, nonce, len(ct)))).decode("utf-8", "replace")


# ------------------------------------------------------------------------------------------
# 8ד. הגבלת קצב  ·  לפי כתובת, ובנוסף תקרה גלובלית
# ------------------------------------------------------------------------------------------

_rl_lock = threading.Lock()
_rl_ip = {}
_rl_global = deque(maxlen=4000)
_ip_fails = {}


def _prune(dq, window):
    now = time.time()
    while dq and now - dq[0] > window:
        dq.popleft()


def rate_ok(ip, limit=RL_ADMIN_HITS, window=RL_WINDOW):
    """מחזיר False כשעברת את התקרה. הבקשה לא נדחית ברעש - היא פשוט מקבלת דף דמה."""
    with _rl_lock:
        dq = _rl_ip.get(ip)
        if dq is None:
            dq = _rl_ip.setdefault(ip, deque(maxlen=limit * 4))
        _prune(dq, window)
        _prune(_rl_global, window)
        if len(_rl_ip) > 5000:
            for k in [k for k, v in list(_rl_ip.items())[:2000] if not v]:
                _rl_ip.pop(k, None)
        dq.append(time.time())
        _rl_global.append(time.time())
        return len(dq) <= limit and len(_rl_global) <= RL_GLOBAL_HITS


def ip_locked(ip):
    e = _ip_fails.get(ip)
    return bool(e and e.get("until", 0) > time.time())


def ip_fail(ip):
    e = _ip_fails.setdefault(ip, {"n": 0, "until": 0})
    e["n"] += 1
    if e["n"] >= IP_LOGIN_FAILS:
        e["until"] = time.time() + LOCKOUT_HOURS * 3600
        e["n"] = 0
    # ניקוי: תחת מתקפה מכתובות רבות, המילון היה גדל בלי גבול. מסירים רשומות
    # שכבר פג תוקף הנעילה שלהן ואין להן ניסיונות פעילים.
    if len(_ip_fails) > 4000:
        now = time.time()
        for k in [k for k, v in list(_ip_fails.items())
                  if v.get("until", 0) < now and v.get("n", 0) == 0]:
            _ip_fails.pop(k, None)
    return e


def ip_clear(ip):
    _ip_fails.pop(ip, None)


def client_fp(ua):
    """טביעה גסה של הדפדפן. עוגייה גנובה שמוגשת מדפדפן אחר לא תתקבל."""
    return hashlib.sha256(("fp|" + (ua or "")).encode("utf-8", "replace")).hexdigest()[:24]


# ------------------------------------------------------------------------------------------
# 8ה. אימות
# ------------------------------------------------------------------------------------------

DUMMY_SALT = hashlib.sha256(b"dg-dummy-salt").hexdigest()[:32]


def auth_data():
    return load_json(AUTH_FILE, {})


def is_configured():
    a = auth_data()
    return bool(a.get("hash") and a.get("salt"))


def set_credentials(user, password):
    salt, h = hash_pw(password)
    _secure_save(AUTH_FILE, {"username": user, "salt": salt, "hash": h,
                             "created": time.time(), "fails": 0, "locked_until": 0})


def setup_allowed(token=""):
    """
    חלון ההגדרה הראשונית. בלי זה, מי שמגיע ראשון לשרת לא מוגדר קובע לעצמו סיסמה.
    אם הגדרת SETUP_TOKEN - הוא חובה. אחרת מותר רק בדקות הראשונות אחרי עלייה,
    או עם האסימון החד-פעמי שנרשם בלוג של הקונטיינר (שרק לך יש גישה אליו).
    """
    if is_configured():
        return False
    env_tok = (os.environ.get("SETUP_TOKEN") or "").strip()
    if env_tok:
        return bool(token) and _eq(token.strip(), env_tok)
    if token and _eq(token.strip(), BOOT_SETUP_TOKEN):
        return True
    return (time.time() - BOOT_TS) <= SETUP_WINDOW_MIN * 60


def check_login(user, password, ip=""):
    """
    שומר על אותה חתימה כמו קודם ומחזיר (ok, msg).
    חדש: נעילה נפרדת לכל כתובת, חישוב דמה כדי שזמן התגובה לא יסגיר כלום,
    ואין רמז אם השם קיים או לא.
    """
    a = auth_data()
    now = time.time()
    if ip and ip_locked(ip):
        return False, f"נעול לכתובת הזו. נסה שוב בעוד {LOCKOUT_HOURS} שעות."
    if a.get("locked_until", 0) > now:
        return False, f"המערכת נעולה. נסה שוב בעוד {int((a['locked_until']-now)/60)+1} דקות."
    if not a.get("hash"):
        hash_pw(password or "", DUMMY_SALT)          # אותו זמן תגובה בדיוק
        return False, "המערכת לא הוגדרה."
    _, h = hash_pw(password or "", a["salt"])
    good = _eq(h, a["hash"])
    same_user = _eq((user or "").strip(), a.get("username", ""))
    if good and same_user:
        a["fails"] = 0
        a["locked_until"] = 0
        _secure_save(AUTH_FILE, a)
        if ip:
            ip_clear(ip)
        return True, ""
    if ip:
        ip_fail(ip)
    a["fails"] = int(a.get("fails", 0)) + 1
    if a["fails"] >= MAX_LOGIN_FAILS:
        a["locked_until"] = now + LOCKOUT_HOURS * 3600
        a["fails"] = 0
        _secure_save(AUTH_FILE, a)
        log(f"🔒 נעילה: יותר מדי ניסיונות כניסה כושלים (כתובת {ip or '?'}).")
        return False, f"יותר מדי ניסיונות. המערכת ננעלה ל-{LOCKOUT_HOURS} שעות."
    _secure_save(AUTH_FILE, a)
    log(f"🚫 ניסיון כניסה כושל #{a['fails']} מכתובת {ip or '?'}")
    return False, f"שם משתמש או סיסמה שגויים. נותרו {MAX_LOGIN_FAILS - a['fails']} ניסיונות."


def sessions():
    d = load_json(SESS_FILE, {})
    return d if isinstance(d, dict) else {}


def _exp_of(v):
    if isinstance(v, dict):
        return float(v.get("exp") or 0)
    try:
        return float(v)
    except Exception:
        return 0.0


def new_session(fp="", ip=""):
    tok = secrets.token_urlsafe(48)
    now = time.time()
    live = [(k, v) for k, v in sessions().items() if _exp_of(v) > now]
    live.sort(key=lambda kv: _exp_of(kv[1]), reverse=True)
    s = {k: v for k, v in live[:MAX_SESSIONS - 1]}
    s[tok] = {"exp": now + SESSION_DAYS * 86400, "fp": fp, "ip": ip, "born": now}
    _secure_save(SESS_FILE, s)
    return tok


def valid_session(tok, fp=""):
    if not tok or len(tok) < 20:
        return False
    v = sessions().get(tok)
    if v is None:
        return False
    if _exp_of(v) <= time.time():
        return False
    if BIND_SESSION and isinstance(v, dict) and v.get("fp"):
        if not _eq(v.get("fp"), fp):
            return False
    return True


def drop_session(tok):
    s = sessions()
    s.pop(tok, None)
    _secure_save(SESS_FILE, s)


def harden_state():
    _chmod(STATE_DIR, 0o700)
    for p in (AUTH_FILE, SESS_FILE, SECRET_FILE, CONF_FILE, SCRIPT_FILE, SCRIPT_BAK):
        if os.path.exists(p):
            _chmod(p, 0o600)


harden_state()


# ==========================================================================================
# 9. הרצת הסקריפט
# ==========================================================================================

BOOTSTRAP = r'''# -*- coding: utf-8 -*-
# עוטף שמריץ את הסקריפט שלך בלי לשנות אותו:
# כל בקשת bind לפורט התפוס מנותבת בשקט לפורט הפנימי, כדי שלא תהיה
# קריסת "Address already in use". גם connect פנימי מנותב בהתאם.
import os, sys, socket, runpy

TARGET = int(os.environ.get("CHILD_PORT", "7861"))
BUSY = {int(os.environ.get("APP_PORT", "7860"))}
SCRIPT = os.environ["CHILD_SCRIPT"]

_bind = socket.socket.bind
def bind(self, addr):
    try:
        if isinstance(addr, tuple) and len(addr) >= 2 and isinstance(addr[1], int) and addr[1] in BUSY:
            addr = (addr[0], TARGET) + tuple(addr[2:])
    except Exception:
        pass
    return _bind(self, addr)
socket.socket.bind = bind

_connect = socket.socket.connect
def connect(self, addr):
    try:
        if (isinstance(addr, tuple) and len(addr) >= 2 and addr[1] in BUSY
                and str(addr[0]) in ("127.0.0.1", "localhost", "0.0.0.0", "::1")):
            addr = (addr[0], TARGET) + tuple(addr[2:])
    except Exception:
        pass
    return _connect(self, addr)
socket.socket.connect = connect

work = os.environ.get("CHILD_WORKDIR") or os.path.dirname(os.path.abspath(SCRIPT))
os.chdir(work)
sys.path.insert(0, work)
sys.argv = [SCRIPT]
runpy.run_path(SCRIPT, run_name="__main__")
'''


class Runner:
    def __init__(self):
        self.proc = None
        self.started = 0
        self.restarts = 0
        self.stopped_by_user = False
        self.ever_started = False
        self.busy = ""          # "מפעיל" / "עוצר" - מונע לחיצה כפולה מלהפעיל שני תהליכים
        self.lock = threading.Lock()

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def _pump(self, proc):
        try:
            for raw in iter(proc.stdout.readline, b""):
                line = raw.decode("utf-8", "replace").rstrip("\n")
                if line:
                    log(line, tag="script")
        except Exception:
            pass

    def start(self, install_pip=True):
        with self.lock:
            if self.alive():
                return False, "הסקריפט כבר רץ"
            if not ensure_script_present():
                return False, "אין קוד שמור בדלי. הדבק קוד ולחץ שמור."
            conf = load_json(CONF_FILE, DEFAULT_CONF)
            pkgs = (conf.get("pip_packages") or "").split()
            if install_pip and pkgs:
                log(f"📦 מתקין חבילות: {' '.join(pkgs)}")
                try:
                    r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", *pkgs],
                                       capture_output=True, text=True, timeout=900)
                    log("✅ ההתקנה הסתיימה" if r.returncode == 0
                        else f"⚠️ ההתקנה נכשלה: {r.stderr[:300]}")
                except Exception as e:
                    log(f"⚠️ שגיאת התקנה: {e}")

            write_text(BOOT_FILE, BOOTSTRAP)

            # אם הקוד שמור מוצפן, מפענחים אותו לקובץ זמני מחוץ לדלי (/tmp).
            # הוא נמחק בכל restart, לא מגובה לשום מקום, ולא נגיש דרך שום נתיב.
            script_path = SCRIPT_FILE
            if CODE_KEY:
                try:
                    plain = read_script()
                    if plain.strip():
                        os.makedirs(RUNTIME_DIR, exist_ok=True)
                        _chmod(RUNTIME_DIR, 0o700)
                        script_path = os.path.join(RUNTIME_DIR, "main.py")
                        write_text(script_path, plain)
                        _chmod(script_path, 0o600)
                except Exception as e:
                    return False, f"פענוח הקוד נכשל: {e}"

            env = dict(os.environ)
            env.update({
                "CHILD_SCRIPT": script_path,
                "CHILD_WORKDIR": DATA_DIR,
                "CHILD_PORT": str(CHILD_PORT),
                "APP_PORT": str(APP_PORT),
                "PORT": str(CHILD_PORT),
                "PYTHONUNBUFFERED": "1",
                "PYTHONIOENCODING": "utf-8",
                "DATA_DIR": DATA_DIR,
                "PUBLIC_URL": PUBLIC_URL,
            })
            # המפתחות הרגישים לא עוברים לתהליך הבן
            for _k in ("CODE_KEY", "MASTER_KEY", "SETUP_TOKEN"):
                env.pop(_k, None)
            try:
                self.proc = subprocess.Popen(
                    [sys.executable, "-u", BOOT_FILE], cwd=DATA_DIR, env=env,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
            except Exception as e:
                return False, f"ההפעלה נכשלה: {e}"

            self.started = time.time()
            self.ever_started = True
            self.stopped_by_user = False
            save_json(PID_FILE, {"pid": self.proc.pid, "ts": time.time()})
            threading.Thread(target=self._pump, args=(self.proc,), daemon=True).start()
            log(f"▶️ הסקריפט הופעל (pid {self.proc.pid}, פורט פנימי {CHILD_PORT})")
            return True, "הסקריפט הופעל"

    def stop(self, by_user=True, reason=""):
        with self.lock:
            if not self.alive():
                return False, "אין סקריפט פעיל"
            self.stopped_by_user = by_user
            p = self.proc
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            except Exception:
                try:
                    p.terminate()
                except Exception:
                    pass
            for _ in range(25):
                if p.poll() is not None:
                    break
                time.sleep(0.15)
            if p.poll() is None:
                try:
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                except Exception:
                    try:
                        p.kill()
                    except Exception:
                        pass
            log(f"⏹️ הסקריפט נעצר{(' - ' + reason) if reason else ''}")
            try:
                os.remove(PID_FILE)
            except Exception:
                pass
            return True, "הסקריפט נעצר"

    def uptime(self):
        if not self.alive():
            return ""
        s = int(time.time() - self.started)
        d, r = divmod(s, 86400)
        h, r = divmod(r, 3600)
        m, s = divmod(r, 60)
        return f"{d} ימים {h}:{m:02d}" if d else f"{h}:{m:02d}:{s:02d}"


RUNNER = Runner()


def kill_orphans():
    info = load_json(PID_FILE, {})
    pid = info.get("pid")
    if not pid:
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
        log(f"🧹 נוקה תהליך יתום מהרצה קודמת (pid {pid})")
    except Exception:
        pass
    try:
        os.remove(PID_FILE)
    except Exception:
        pass


def child_listening():
    try:
        with socket.create_connection(("127.0.0.1", CHILD_PORT), timeout=0.8):
            return True
    except Exception:
        return False


# ==========================================================================================
# 10. השומר הראשי
# ==========================================================================================

# ------------------------------------------------------------------------------------------
# הערה על שמירת ערנות (גרסה 6.2)
# ------------------------------------------------------------------------------------------
# בגרסאות קודמות הייתה כאן לולאה שדיגדגה את הכתובת הציבורית של הספייס כדי
# למנוע שינה. הסרנו אותה לחלוטין, ובכוונה: תעבורה מלאכותית שהקונטיינר מייצר
# אל עצמו היא בדיוק סוג ה"פעילות בוט אוטומטית" שמדיניות Hugging Face מסמנת,
# והיא חלק ממה שכנראה גרם להשעיה. הסקריפט המקורי שלך אף פעם לא עשה דבר כזה.
#
# אם צריך למנוע שינה אחרי 48 שעות, עושים זאת בדרך שהיא לגיטימית מבחינת HF:
# הגדרת סביבה חיצונית (שירות ניטור, cron חיצוני) שדוגמת את הכתובת. אבל שום
# דבר מזה כבר לא רץ מתוך הקוד הזה.


def watchdog():
    last_scan = time.time()
    last_backup = 0.0
    last_guard = 0.0
    backoff = 5
    while True:
        try:
            now = time.time()
            conf = load_json(CONF_FILE, DEFAULT_CONF)

            # א. קובץ הפייתון תמיד קיים בדלי
            ensure_script_present()

            # ב. הלוג נמחק ונוצר מחדש כל LOG_RESET_HOURS שעות
            if now - _log_state["started"] >= LOG_RESET_HOURS * 3600:
                reset_log_file()

            # ג. הסקריפט חייב לרוץ.
            # מפעילים מחדש אם: keepalive דלוק (הפעלה מחדש אם נפל) או autostart
            # דלוק (הקוד אמור תמיד לרוץ). לא מסתמכים על ever_started, כי אם
            # ההפעלה הראשונה בעלייה נכשלה הוא נשאר False והקוד לא היה עולה לעולם.
            # כן מכבדים עצירה יזומה מהמשתמש: אם לחצת "עצור", לא נפעיל מחדש.
            should_run = (conf.get("keepalive") or conf.get("autostart", True))
            if (should_run and not RUNNER.alive() and not RUNNER.stopped_by_user
                    and ensure_script_present()):
                log(f"🔄 הסקריפט אינו פעיל - מפעיל מחדש בעוד {backoff} שניות")
                time.sleep(backoff)
                ok, msg = RUNNER.start(install_pip=False)
                if ok:
                    RUNNER.restarts += 1
                    backoff = 5
                else:
                    log(f"⚠️ הפעלה מחדש נכשלה: {msg}")
                    backoff = min(backoff * 2, 120)

            # ד. מדידת אחסון מחדש כל 10 דקות + בדיקת לחץ מקום כל 5 דקות
            if now - last_scan > SCAN_MINUTES * 60:
                last_scan = now
                refresh_storage(True)
            if now - last_guard > 300:
                last_guard = now
                space_guard()

            # ה. גיבוי רשות (רק אם AUTO_BACKUP הופעל במפורש - כבוי כברירת מחדל)
            if AUTO_BACKUP and _backup["enabled"] and now - last_backup > BACKUP_INTERVAL:
                last_backup = now
                backup_now("(אוטומטי)")
        except Exception:
            log("watchdog: " + traceback.format_exc().splitlines()[-1])
        time.sleep(5)


# ==========================================================================================
# 11. הממשק  ·  HTML שנבנה בשרת, בלי CDN ובלי חיבור פתוח. עובד גם בלי JavaScript.
# ==========================================================================================

CSS = """
:root{
  --ink:#0B1015; --panel:#141D25; --panel-2:#0F171E; --line:#233240;
  --text:#E4ECF1; --muted:#82979F; --amber:#E9A13B; --ok:#4FD18B; --bad:#E5555B;
  --mono: ui-monospace,"Cascadia Mono","Consolas","Courier New",monospace;
  --sans: -apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans Hebrew",Arial,sans-serif;
}
*{box-sizing:border-box}
body{margin:0;background:var(--ink);color:var(--text);font-family:var(--sans);
     font-size:15px;line-height:1.6;direction:rtl}
a{color:var(--amber)}
.wrap{max-width:1060px;margin:0 auto;padding:20px 16px 64px}
header{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;
       border-bottom:1px solid var(--line);padding-bottom:14px;margin-bottom:22px}
header h1{margin:0;font-size:20px;letter-spacing:.5px;font-weight:600}
header .ver{color:var(--muted);font-family:var(--mono);font-size:12px}
header .out{margin-inline-start:auto}
.rail{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;
      background:var(--line);border:1px solid var(--line);border-radius:10px;overflow:hidden;margin-bottom:22px}
.lamp{background:var(--panel-2);padding:12px 14px}
.lamp .k{font-size:11px;letter-spacing:1.4px;color:var(--muted);text-transform:uppercase;
         font-family:var(--mono);display:block;margin-bottom:6px}
.lamp .v{display:flex;align-items:center;gap:8px;font-size:14px}
.dot{width:9px;height:9px;border-radius:50%;background:var(--muted);flex:0 0 auto}
.dot.on{background:var(--ok);box-shadow:0 0 0 3px rgba(79,209,139,.16)}
.dot.warn{background:var(--amber);box-shadow:0 0 0 3px rgba(233,161,59,.16)}
.dot.off{background:var(--bad);box-shadow:0 0 0 3px rgba(229,85,91,.14)}
.dot.on.live{animation:pulse 2.4s ease-in-out infinite}
@keyframes pulse{50%{box-shadow:0 0 0 7px rgba(79,209,139,0)}}
@media (prefers-reduced-motion:reduce){.dot.on.live{animation:none}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:18px;margin-bottom:18px}
.card h2{margin:0 0 4px;font-size:16px;font-weight:600}
.card p.sub{margin:0 0 16px;color:var(--muted);font-size:13.5px}
label{display:block;font-size:13px;color:var(--muted);margin:12px 0 5px}
input[type=text],input[type=password],textarea{
  width:100%;background:var(--panel-2);border:1px solid var(--line);border-radius:7px;
  color:var(--text);padding:10px 12px;font-family:var(--sans);font-size:14px}
textarea{font-family:var(--mono);font-size:13px;line-height:1.5;direction:ltr;text-align:left;min-height:320px}
input:focus,textarea:focus{outline:2px solid var(--amber);outline-offset:1px;border-color:transparent}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:14px}
button{font-family:var(--sans);font-size:14px;font-weight:600;border-radius:7px;
       padding:10px 20px;border:1px solid var(--line);background:var(--panel-2);
       color:var(--text);cursor:pointer}
button:hover{border-color:var(--amber)}
button.primary{background:var(--amber);color:#1A1206;border-color:var(--amber)}
button.danger{color:var(--bad)}
button:focus-visible{outline:2px solid var(--amber);outline-offset:2px}
.check{display:flex;align-items:center;gap:8px;color:var(--text);font-size:13.5px}
.check input{width:16px;height:16px;accent-color:var(--amber)}
.note{border-inline-start:3px solid var(--amber);background:rgba(233,161,59,.07);
      padding:12px 14px;border-radius:0 7px 7px 0;font-size:13.5px;margin-bottom:18px}
.note.bad{border-color:var(--bad);background:rgba(229,85,91,.08)}
.note.ok{border-color:var(--ok);background:rgba(79,209,139,.07)}
.note b{display:block;margin-bottom:3px}
pre.logs{background:#070C11;border:1px solid var(--line);border-radius:8px;padding:14px;
     height:340px;overflow:auto;margin:0;font-family:var(--mono);font-size:12.5px;
     direction:ltr;text-align:left;white-space:pre-wrap;word-break:break-word;color:#C7D6DE}
pre.logs .s{color:#7FB3D5}
code{font-family:var(--mono);background:var(--panel-2);padding:2px 6px;border-radius:4px;font-size:12.5px}
table.kv{width:100%;border-collapse:collapse;font-size:13.5px}
table.kv td{padding:7px 0;border-bottom:1px solid var(--line);vertical-align:top}
table.kv td:first-child{color:var(--muted);width:42%}
.center{max-width:460px;margin:8vh auto 0}
.muted{color:var(--muted);font-size:13px}
.gauge{margin:4px 0 10px}
.gauge .bar{height:14px;background:var(--panel-2);border:1px solid var(--line);
            border-radius:8px;overflow:hidden;position:relative}
.gauge .fill{height:100%;background:var(--ok)}
.gauge .fill.warn{background:var(--amber)}
.gauge .fill.bad{background:var(--bad)}
.gauge .txt{display:flex;justify-content:space-between;font-size:13px;margin-top:6px}
.gauge .txt b{font-weight:600}
.tag{display:inline-block;font-family:var(--mono);font-size:11px;padding:2px 7px;
     border:1px solid var(--line);border-radius:20px;color:var(--muted);margin-inline-start:6px}
.tag.ok{color:var(--ok);border-color:rgba(79,209,139,.4)}
.tag.bad{color:var(--bad);border-color:rgba(229,85,91,.4)}
"""

JS = """
(function(){
  var box=document.getElementById('logbox');
  if(!box) return;
  var since=parseInt(box.getAttribute('data-since')||'0',10);
  var stick=true;
  box.addEventListener('scroll',function(){
    stick = box.scrollTop+box.clientHeight >= box.scrollHeight-30;
  });
  box.scrollTop=box.scrollHeight;
  function tick(){
    fetch('__LOGS_URL__?since='+since,{cache:'no-store',credentials:'same-origin'})
      .then(function(r){return r.json()})
      .then(function(d){
        if(d.lines && d.lines.length){
          d.lines.forEach(function(l){
            var s=document.createElement('span');
            s.className = l.g==='script' ? 's' : '';
            s.textContent='['+l.t+'] '+l.m+'\\n';
            box.appendChild(s);
          });
          since=d.n;
          if(stick) box.scrollTop=box.scrollHeight;
        }
        var u=document.getElementById('uptime');
        if(u && d.uptime!==undefined) u.textContent = d.uptime || '-';
      })
      .catch(function(){})
      .then(function(){ setTimeout(tick,2000) });
  }
  setTimeout(tick,1500);
})();
"""


# --- הודעות בין בקשות ---------------------------------------------------------------
# למה זה כאן: עד עכשיו לחיצה על "הפעל" החזירה את הדף ישירות בתשובה ל-POST.
# לכן כל רענון של הדפדפן שלח את אותו POST שוב - וזה מה שהפעיל את הסקריפט מחדש
# בלי שביקשת. עכשיו כל פעולה מסתיימת בהפניה לדף הראשי, וההודעה נשמרת כאן
# לרגע אחד עד שהדף נטען. רענון = טעינה רגילה של הדף, בלי שום פעולה חוזרת.
_flash = {}
_flash_lock = threading.Lock()


def set_flash(sid, text, kind="ok"):
    if not sid:
        return
    with _flash_lock:
        now = time.time()
        for k in [k for k, v in _flash.items() if now - v[2] > 120]:
            _flash.pop(k, None)
        _flash[sid] = (text, kind, now)


def pop_flash(sid):
    with _flash_lock:
        item = _flash.pop(sid, None)
    if not item:
        return ""
    return note(html.escape(item[0]), item[1])


def page(title, body, logged_in=False):
    n = new_nonce()
    js = JS.replace("__LOGS_URL__", ROUTES["logs"])
    out = (f'<form class="out" method="post" action="{ROUTES["logout"]}">'
           f'{csrf_field()}<button>יציאה</button></form>') if logged_in else ""
    return f"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive,nosnippet">
<meta name="referrer" content="no-referrer">
<title>{html.escape(title)}</title>
<style nonce="{n}">{CSS}</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>{APP_NAME}</h1><span class="ver">v{VERSION}</span>
  {out}
</header>
{body}
</div>
<script nonce="{n}">{js}</script>
</body></html>"""


def note(text, kind="ok"):
    return f"<div class='note {kind}'>{text}</div>"


def _ago(ts):
    if not ts:
        return "—"
    d = int(time.time() - ts)
    if d < 60:
        return f"{d} שניות"
    if d < 3600:
        return f"{d//60} דקות"
    if d < 86400:
        return f"{d//3600} שעות"
    return f"{d//86400} ימים"


def storage_lamps():
    running = RUNNER.alive()
    pct = used_pct()
    kind = STORAGE["kind"]
    if kind == "bucket":
        s_cls = "on" if STORAGE["verified"] else "warn"
        s_txt = "דלי מחובר" + ("" if STORAGE["verified"] else " (ממתין לאימות)")
    elif kind == "volume":
        s_cls, s_txt = ("on" if STORAGE["verified"] else "warn"), "אחסון קבוע"
    else:
        s_cls, s_txt = "off", "לא מחובר"
    script_ok = os.path.exists(SCRIPT_FILE)
    return f"""<div class="rail">
  <div class="lamp"><span class="k">script</span><span class="v">
    <span class="dot {'on live' if running else 'off'}"></span>
    {'רץ · <span id="uptime">' + RUNNER.uptime() + '</span>' if running else 'עצור'}</span></div>
  <div class="lamp"><span class="k">bucket</span><span class="v">
    <span class="dot {s_cls}"></span>{s_txt}</span></div>
  <div class="lamp"><span class="k">main.py</span><span class="v">
    <span class="dot {'on' if script_ok else 'off'}"></span>
    {'קיים בדלי' if script_ok else 'חסר'}</span></div>
  <div class="lamp"><span class="k">storage</span><span class="v">
    <span class="dot {'off' if pct>=95 else ('warn' if pct>=80 else 'on')}"></span>
    {pct:.1f}% מהמכסה</span></div>
  <div class="lamp"><span class="k">port</span><span class="v">
    <span class="dot {'on' if child_listening() else 'warn'}"></span>
    {CHILD_PORT} {'מאזין' if child_listening() else 'סגור'}</span></div>
</div>"""


def storage_card():
    pct = used_pct()
    cls = "bad" if pct >= 95 else ("warn" if pct >= 80 else "")
    used = STORAGE.get("used_bytes", 0)
    quota = STORAGE.get("quota_bytes", 0)
    m = mount_of(DATA_DIR) or {}
    ver_tag = ('<span class="tag ok">מאומת</span>' if STORAGE["verified"]
               else '<span class="tag">ממתין ל-restart לאימות</span>')
    mount_tag = ('<span class="tag ok">mount אמיתי</span>' if STORAGE["is_mount"]
                 else '<span class="tag bad">לא נקודת עגינה</span>')
    partial = (' <span class="tag">סריקה חלקית</span>' if STORAGE.get("scan_partial") else "")
    fs_line = (f"{fmt_size(STORAGE['fs_total'])} · {fmt_size(STORAGE['fs_free'])} פנוי"
               if STORAGE["fs_reliable"] else
               f"מדווח {STORAGE['fs_total']/GB:,.0f} GB — מספר דמה של אחסון אובייקטים, לא בשימוש לחישוב")
    return f"""<div class="card">
  <h2>אחסון</h2>
  <p class="sub">הנתונים למטה מחושבים בסריקה אמיתית של התיקייה, לא לפי מה שמערכת הקבצים מדווחת.</p>
  <div class="gauge">
    <div class="bar"><div class="fill {cls}" style="width:{max(0.6,pct):.2f}%"></div></div>
    <div class="txt"><span><b>{fmt_size(used)}</b> בשימוש מתוך <b>{fmt_size(quota)}</b></span>
      <span class="muted">נשאר {fmt_size(free_bytes())} · {pct:.2f}%{partial}</span></div>
  </div>
  <table class="kv">
    <tr><td>תיקייה</td><td><code>{html.escape(DATA_DIR)}</code> {mount_tag} {ver_tag}</td></tr>
    <tr><td>סוג</td><td>{STORAGE['kind_he']} · <code>{html.escape(m.get('fstype') or '—')}</code>
        {'· לקריאה בלבד' if STORAGE['readonly'] else ''}</td></tr>
    <tr><td>מקור המכסה</td><td>{html.escape(STORAGE['quota_source'])}
        <span class="muted">— לשינוי: משתנה סביבה STORAGE_QUOTA_GB</span></td></tr>
    <tr><td>מה שמערכת הקבצים מדווחת</td><td class="muted">{fs_line}</td></tr>
    <tr><td>קבצים בתיקייה</td><td>{STORAGE['files']:,} קבצים · {STORAGE['dirs']:,} תיקיות
        <span class="muted">(נסרק לפני {_ago(STORAGE['scan_ts'])}, {STORAGE['scan_secs']:.1f} שניות)</span></td></tr>
    <tr><td>מתוכם אודיו</td><td>{STORAGE['audio_files']:,} קבצים · {fmt_size(STORAGE['audio_bytes'])}
        <span class="muted">(רק אלה נמחקים כשנגמר המקום)</span></td></tr>
    <tr><td>אימות שמירה</td><td>{'✅ הסמן שרד ' + str(STORAGE['boots']-1) + ' הפעלות מחדש — הדלי באמת שומר'
        if STORAGE['verified'] else 'זו העלייה הראשונה. האימות יושלם אחרי restart אחד.'}
        <span class="muted">(מאז {datetime.fromtimestamp(STORAGE['first_seen']):%d/%m/%Y %H:%M})</span></td></tr>
    <tr><td>קובץ הפייתון</td><td><code>{html.escape(SCRIPT_FILE)}</code>
        {'✅ קיים' if os.path.exists(SCRIPT_FILE) else '❌ חסר'}</td></tr>
    <tr><td>קובץ הלוג</td><td><code>{html.escape(_log_state['path'])}</code>
        · נמחק כל {LOG_RESET_HOURS:g} שעות (בוצע {_log_state['resets']} פעמים)
        {'<span class="tag bad">תיקייה חלופית</span>' if _log_state['fallback'] else ''}</td></tr>
  </table>
  <div class="row">
    <form method="post" action="{ROUTES['rescan']}">{csrf_field()}<button type="submit">סרוק מחדש</button></form>
    <form method="post" action="{ROUTES['purge']}"
          onsubmit="return confirm('למחוק קבצי אודיו ישנים? קבצי טקסט, ini ו-json לא ייגעו.')">
      {csrf_field()}<button type="submit" class="danger">פנה מקום (אודיו בלבד)</button></form>
    <form method="post" action="{ROUTES['resetlog']}">{csrf_field()}<button type="submit">אפס את הלוג עכשיו</button></form>
  </div>
</div>"""


def storage_warning():
    if STORAGE["kind"] == "ephemeral":
        return ("<div class='note bad'><b>התיקייה אינה מחוברת לדלי</b>"
                f"<code>{html.escape(DATA_DIR)}</code> היא חלק מהדיסק הזמני של הקונטיינר, "
                "ולכן כל מה שנשמר בה יימחק ב-restart הבא. "
                "בהגדרות הספייס → Storage Buckets → חבר דלי עם נתיב עגינה <code>/data</code>.</div>")
    if STORAGE["readonly"]:
        return ("<div class='note bad'><b>הדלי מחובר לקריאה בלבד</b>"
                "שנה את מצב הגישה ל-read-write בהגדרות הספייס, אחרת אי אפשר לשמור כלום.</div>")
    if used_pct() >= 95:
        return ("<div class='note bad'><b>המקום כמעט נגמר</b>"
                f"בשימוש {fmt_size(STORAGE['used_bytes'])} מתוך {fmt_size(STORAGE['quota_bytes'])}. "
                "המערכת מפנה קבצי אודיו ישנים לבד, אבל כדאי לבדוק מה תופס מקום.</div>")
    return ""


def setup_page(msg="", need_token=False):
    tok_field = ""
    if need_token:
        tok_field = """<label for="st">אסימון הגדרה חד-פעמי</label>
    <input id="st" name="setup_token" type="text" autocomplete="off" required>
    <p class="muted" style="margin:6px 0 0">האסימון נרשם בלוג של הקונטיינר בעליית השרת,
       או שהגדרת אותו בעצמך במשתנה הסביבה <code>SETUP_TOKEN</code>.</p>"""
    body = f"""<div class="center">
{storage_warning()}
<div class="card">
  <h2>הגדרת גישה</h2>
  <p class="sub">קבע שם משתמש וסיסמה. אחרי השמירה הדף הזה ננעל, והכניסה תהיה רק דרך מסך הכניסה.</p>
  {msg}
  <form method="post" action="{ROUTES['setup']}">
    {csrf_field()}
    <label for="u">שם משתמש</label>
    <input id="u" name="username" type="text" autocomplete="username" required>
    <label for="p">סיסמה</label>
    <input id="p" name="password" type="password" autocomplete="new-password" required>
    <label for="p2">אימות סיסמה</label>
    <input id="p2" name="password2" type="password" autocomplete="new-password" required>
    {tok_field}
    <div class="row"><button class="primary" type="submit">שמור ונעל</button></div>
  </form>
  <p class="muted" style="margin-top:14px">הדף עובד גם בלי JavaScript ובלי חיבור פתוח לשרת, כדי שיעבור דרך נטפרי.</p>
</div></div>"""
    return page("הגדרת גישה", body)


def login_page(msg=""):
    body = f"""<div class="center">
<div class="card">
  <h2>כניסה</h2>
  <p class="sub">אחרי {MAX_LOGIN_FAILS} ניסיונות כושלים המערכת ננעלת ל-{LOCKOUT_HOURS} שעות.</p>
  {msg}
  <form method="post" action="{ROUTES['login']}">
    {csrf_field()}
    <label for="u">שם משתמש</label>
    <input id="u" name="username" type="text" autocomplete="username" required>
    <label for="p">סיסמה</label>
    <input id="p" name="password" type="password" autocomplete="current-password" required>
    <div class="row"><button class="primary" type="submit">כניסה</button></div>
  </form>
</div></div>"""
    return page("כניסה", body)


def backup_buttons_html():
    return (
        f'<form method="post" action="{ROUTES["backup"]}">{csrf_field()}'
        '<button type="submit">גבה עכשיו</button></form>'
        f'<form method="post" action="{ROUTES["restore"]}" '
        'onsubmit="return confirm(\'לשחזר מהגיבוי?\')">' + csrf_field() +
        '<button type="submit" class="danger">שחזר מהגיבוי</button></form>'
    )


def code_card(code_text=None):
    """
    כרטיס הקוד. שינוי מהותי מגרסה 5: הקוד *אינו* נכתב לתוך הדף.
    מה שמוצג הוא רק תעודת זהות שלו - כמה שורות, כמה בייטים, וטביעת אצבע SHA-256.
    התיבה נשארת ריקה: מדביקים קוד חדש פעם אחת, לוחצים הרצה, והוא נשמר בדלי.
    להצגת הקוד השמור צריך להקליד את הסיסמה שוב, והוא מוצג לפעם אחת בלבד.
    """
    conf = load_json(CONF_FILE, DEFAULT_CONF)
    running = RUNNER.alive()
    m = script_meta()
    enc = "כן · מוצפן במנוחה" if m.get("encrypted") else ("לא (להצפנה: משתנה סביבה CODE_KEY)")
    if m.get("exists"):
        ident = (f"<tr><td>מצב</td><td>✅ קוד שמור בדלי</td></tr>"
                 f"<tr><td>גודל</td><td>{m.get('lines', 0):,} שורות · {fmt_size(m.get('bytes', 0))}</td></tr>"
                 f"<tr><td>טביעת אצבע</td><td><code>{html.escape(m.get('sha', '')[:32])}</code></td></tr>"
                 f"<tr><td>נשמר לאחרונה</td><td>לפני {_ago(m.get('ts', 0))}</td></tr>"
                 f"<tr><td>הצפנה</td><td>{enc}</td></tr>")
    else:
        ident = "<tr><td>מצב</td><td>❌ אין עדיין קוד שמור. הדבק קוד ולחץ שמור והפעל.</td></tr>"

    if code_text is None:
        area = ('<textarea id="code" name="code" spellcheck="false" '
                'placeholder="הדבק כאן קוד פייתון חדש. תיבה ריקה = הקוד השמור נשאר כמו שהוא."></textarea>')
        reveal = f"""<form method="post" action="{ROUTES['reveal']}" style="margin-top:14px">
      {csrf_field()}
      <label for="rp">להצגת הקוד השמור לעריכה - הקלד את הסיסמה שוב</label>
      <div class="row">
        <input id="rp" name="password" type="password" autocomplete="current-password"
               style="max-width:260px" placeholder="סיסמה">
        <button type="submit">הצג את הקוד פעם אחת</button>
      </div>
    </form>"""
        shown = note("הקוד השמור <b style='display:inline'>אינו</b> נשלח לדפדפן. "
                     "הדף הזה לא מכיל אותו בשום צורה - גם לא בקוד המקור שלו.", "ok")
    else:
        area = ('<textarea id="code" name="code" spellcheck="false">'
                + html.escape(code_text) + '</textarea>')
        reveal = ""
        shown = note("הקוד מוצג לעריכה חד-פעמית. ברגע שתשמור או תרענן את הדף הוא ייעלם מכאן שוב.", "bad")

    return f"""<div class="card">
  <h2>הקוד שרץ על השרת</h2>
  <p class="sub">נשמר ב-<code>{html.escape(SCRIPT_FILE)}</code> ולא נחשף החוצה.
     הכתובות הציבוריות מגיעות אליו דרך הפרוקסי.</p>
  {shown}
  <table class="kv">{ident}</table>
  <form method="post" action="{ROUTES['run']}" style="margin-top:16px">
    {csrf_field()}
    <label for="pip">חבילות pip להתקנה לפני הרצה (רשות, מופרדות ברווח)</label>
    <input id="pip" name="pip" type="text" value="{html.escape(conf.get('pip_packages',''))}" placeholder="requests pydub">
    <label for="code">קוד פייתון</label>
    {area}
    <div class="row">
      <label class="check"><input type="checkbox" name="autostart" {'checked' if conf.get('autostart') else ''}> הפעלה אוטומטית כשהשרת עולה</label>
      <label class="check"><input type="checkbox" name="keepalive" {'checked' if conf.get('keepalive') else ''}> הפעלה מחדש אם נפל</label>
    </div>
    <div class="row">
      <button class="primary" type="submit" name="action" value="run">{'שמור והפעל מחדש' if running else 'שמור והפעל'}</button>
      <button type="submit" name="action" value="save">שמירה בלבד</button>
      <button type="submit" name="action" value="stop" class="danger" formaction="{ROUTES['stop']}">עצור</button>
    </div>
  </form>
  {reveal}
</div>"""


def dashboard(msg="", code_text=None):
    backup_buttons = backup_buttons_html() if _backup["enabled"] else ""
    busy_note = (note(f"המערכת {html.escape(RUNNER.busy)} כרגע. הלוג למטה מתעדכן לבד.", "ok")
                 if RUNNER.busy else "")
    lines, seq = logs_since(max(0, _log_seq - 400))
    logtxt = "".join(
        f'<span class="{"s" if l["g"]=="script" else ""}">[{l["t"]}] {html.escape(l["m"])}\n</span>'
        for l in lines)
    body = f"""{storage_lamps()}
{storage_warning()}
{msg}
{busy_note}

{code_card(code_text)}

{storage_card()}

<div class="card">
  <h2>לוג חי</h2>
  <p class="sub">מתעדכן לבד כל 2 שניות. אם JavaScript חסום - לחץ רענון.</p>
  <pre class="logs" id="logbox" data-since="{seq}">{logtxt}</pre>
  <div class="row">
    <form method="get" action="{ROUTES['home']}"><button type="submit">רענון</button></form>
    {backup_buttons}
  </div>
</div>

<div class="card">
  <h2>פרטי השרת</h2>
  <table class="kv">
    <tr><td>כתובת ציבורית</td><td><code>{html.escape(PUBLIC_URL)}</code></td></tr>
    <tr><td>כתובת ל-API של ימות</td><td><code>{html.escape(PUBLIC_URL)}/ext1</code></td></tr>
    <tr><td>הפעלות מחדש של הסקריפט</td><td>{RUNNER.restarts}</td></tr>
    <tr><td>נתיב בריאות לניטור חיצוני</td><td>{
        ('<code>' + html.escape(PUBLIC_URL) + '/__ping</code> · מחזיר OK') if PUBLIC_PING else 'כבוי'
    }</td></tr>
    <tr><td>גיבוי נוסף (רשות)</td><td>{('פעיל · ' + BACKUP_REPO + ' · לפני ' + _ago(_backup['last_ok'])) if _backup['enabled'] else 'כבוי — ' + html.escape(_backup['last_error'] or 'לא הוגדר')}</td></tr>
  </table>
  <p class="muted" style="margin-top:12px">כל בקשה שאינה לתחום הניהול החשאי מועברת לסקריפט שלך אחד לאחד:
  אותה שיטה, נתיב, פרמטרים וגוף בקשה. עוגיות הניהול נחתכות מהבקשה לפני שהיא מגיעה לסקריפט.</p>
</div>

<div class="card">
  <h2>כתובת הניהול הפרטית שלך</h2>
  <p class="sub">שמור אותה בסימנייה. היא נשארת זהה גם אחרי restart, כל עוד הדלי מחובר.
     היא לא מופיעה בשום מקום ציבורי ואי אפשר לנחש אותה.</p>
  <table class="kv">
    <tr><td>לוח הבקרה</td><td><code style="word-break:break-all">{html.escape(PUBLIC_URL + ROUTES['home'])}</code></td></tr>
    <tr><td>בדיקת בריאות (דורשת התחברות)</td><td><code style="word-break:break-all">{html.escape(ROUTES['health'])}</code></td></tr>
  </table>
  <div class="row">
    <form method="post" action="{ROUTES['logout']}">{csrf_field()}<button class="danger" type="submit">יציאה מכל המכשירים</button></form>
  </div>
</div>"""
    return page("לוח בקרה", body, logged_in=True)


# ==========================================================================================
# 12. שרת HTTP
# ==========================================================================================

# דף התשובה האחיד. עד גרסה 6.0 הוא היה ריק לחלוטין, ושירותי ניטור חיצוניים
# (וגם עיני אדם) ראו עמוד לבן ולא ידעו אם השרת חי. עכשיו כתוב בו OK.
# הוא עדיין לא מסגיר כלום: אין בו שם מערכת, גרסה, נתיב או רמז לקיום ממשק ניהול.
DECOY_HTML = ("<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
              "<meta name=\"robots\" content=\"noindex,nofollow\"><title>OK</title></head>"
              "<body style=\"font-family:system-ui,sans-serif;color:#444;"
              "display:flex;align-items:center;justify-content:center;height:90vh;margin:0\">"
              "<div style=\"text-align:center\"><div style=\"font-size:40px\">✓</div>"
              "<div style=\"font-size:18px;font-weight:600\">OK</div>"
              "<div style=\"font-size:13px;color:#888\">Service is running</div>"
              "</div></body></html>")
DECOY_JSON = "{\"status\":\"ok\"}"


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "srv"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = 90

    def version_string(self):
        return "srv"

    def log_message(self, *a):
        pass

    def handle_one_request(self):
        CTX.nonce = ""
        CTX.csrf = ""
        return http.server.BaseHTTPRequestHandler.handle_one_request(self)

    # ---------------- זיהוי הפונה ----------------

    def _client_ip(self):
        xff = self.headers.get("X-Forwarded-For", "")
        if xff:
            parts = [p.strip() for p in xff.split(",") if p.strip()]
            if parts:
                return parts[-1][:45]
        try:
            return self.client_address[0]
        except Exception:
            return "?"

    def _fp(self):
        return client_fp(self.headers.get("User-Agent", ""))

    def _cookie(self, name):
        for part in self.headers.get("Cookie", "").split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                if k == name:
                    return v
        return ""

    def _sid(self):
        return self._cookie(COOKIE_NAME)

    def _authed(self):
        return valid_session(self._sid(), self._fp())

    # ---------------- עוגיות ----------------

    def _cookie_str(self, tok):
        secure = "; Secure" if SPACE_HOST else ""
        return f"{COOKIE_NAME}={tok}; Path=/; Max-Age={SESSION_DAYS*86400}; HttpOnly; SameSite=Lax{secure}"

    def _pre_cookie(self, val):
        secure = "; Secure" if SPACE_HOST else ""
        return f"{PRE_COOKIE}={val}; Path=/; Max-Age=1800; HttpOnly; SameSite=Lax{secure}"

    def _clear(self, name):
        secure = "; Secure" if SPACE_HOST else ""
        return f"{name}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax{secure}"

    # ---------------- שליחה ----------------

    def _send(self, code, body, ctype="text/html; charset=utf-8", headers=None,
              cookies=None, mask=True):
        """
        מיסוך סטטוס: כלפי חוץ כמעט הכל הוא 200. סורק אוטומטי לא מקבל שום אות
        שמבדיל בין "אין דף כזה", "אין הרשאה" ו"הצלחה" - אבל מבפנים המערכת
        ממשיכה לספור ניסיונות כושלים, לנעול, ולא לתת גישה בלי סיסמה.
        """
        if isinstance(body, str):
            body = body.encode("utf-8")
        real = 200 if (MASK_STATUS and mask) else code
        self.send_response_only(real)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        if SPACE_HOST:
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        n = getattr(CTX, "nonce", "")
        if "html" in ctype and n:
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; "
                             f"style-src 'nonce-{n}'; script-src 'nonce-{n}'; "
                             "connect-src 'self'; img-src 'self' data:; font-src 'self'; "
                             "form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        else:
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        for c in (cookies or []):
            self.send_header("Set-Cookie", c)
        self.end_headers()
        try:
            if self.command != "HEAD":
                self.wfile.write(body)
        except Exception:
            pass

    def _decoy(self, json_mode=False, slow=True, code=404):
        """
        התשובה לכל מה שלא מגיע לו כלום.
        כשמיסוך כבוי (ברירת המחדל מגרסה 6.2): מחזיר קוד אמיתי - 404 לנתיב לא
        קיים, כמו כל שרת רגיל. כך המרחב לא נראה כמו פרוקסי מתחמק. כשמיסוך פעיל
        (MASK_STATUS=1): הכל 200, כמו קודם. הנתיבים החשאיים מגינים על הפאנל
        בשני המקרים - הקוד עצמו לא מדליף שום מידע לגבי קיום ממשק הניהול.
        """
        if slow and MASK_STATUS:
            time.sleep(0.04 + secrets.randbelow(160) / 1000.0)
        if json_mode:
            self._send(code, DECOY_JSON, "application/json; charset=utf-8")
        else:
            self._send(code, DECOY_HTML)

    def _go(self, to="/", cookies=None):
        """
        הפניה אחרי פעולה. כשמיסוך כבוי (ברירת מחדל) - 303 רגיל, כמו כל שרת.
        כשמיסוך פעיל - 200 עם meta-refresh, כדי שגם ההפניה תיראה כמו 200.
        בשני המקרים רענון של הדפדפן לא חוזר על הפעולה.
        """
        if not MASK_STATUS:
            try:
                self.send_response_only(303)
                self.send_header("Location", to)
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                for c in (cookies or []):
                    self.send_header("Set-Cookie", c)
                self.end_headers()
            except Exception:
                pass
            return
        n = new_nonce()
        u = html.escape(to, quote=True)
        body = (f"<!DOCTYPE html><html lang=\"he\" dir=\"rtl\"><head><meta charset=\"utf-8\">"
                f"<meta name=\"robots\" content=\"noindex,nofollow\">"
                f"<meta name=\"referrer\" content=\"no-referrer\">"
                f"<meta http-equiv=\"refresh\" content=\"0; url={u}\"><title>·</title></head>"
                f"<body style=\"background:#0B1015;color:#82979F;font-family:sans-serif;padding:24px\">"
                f"<script nonce=\"{n}\">location.replace({json.dumps(to)});</script>"
                f"<p><a href=\"{u}\" style=\"color:#E9A13B\">המשך</a></p></body></html>")
        self._send(200, body, cookies=cookies)

    def _flash(self, sid, text, kind="ok"):
        set_flash(sid, text, kind)
        self._go(ROUTES["home"])

    # ---------------- קלט ----------------

    def _path(self):
        """
        ניקוי הנתיב לפני שנוגעים בו. חוסם: כתובת מוחלטת, תווי בקרה, בייט אפס,
        לוכסן הפוך, וכל צורה של יציאה מהתיקייה (גם מקודדת ב-%2e%2e).
        """
        raw = self.path or ""
        if len(raw) > 4096 or not raw.startswith("/"):
            return None
        for ch in raw:
            if ord(ch) < 32 or ord(ch) == 127:
                return None
        p = urllib.parse.urlparse(raw).path
        dec = urllib.parse.unquote(p)
        if "\\" in dec or "\x00" in dec:
            return None
        if ".." in dec.split("/"):
            return None
        return p

    def _form(self, limit=MAX_FORM_BYTES):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except Exception:
            n = 0
        if n <= 0:
            return {}
        if n > limit:
            self.close_connection = True
            return {}
        try:
            raw = self.rfile.read(n).decode("utf-8", "replace")
            return {k: v[0] for k, v in urllib.parse.parse_qs(raw, keep_blank_values=True).items()}
        except Exception:
            return {}

    def _csrf_ok(self, f):
        return csrf_ok(self._sid(), f.get("_t", ""))

    # ---------------- פרוקסי אל הסקריפט שלך ----------------

    def _strip_cookies(self, raw):
        """הסקריפט שלך לעולם לא רואה את עוגיות הניהול. גם אם ייפרץ - אין לו מה לגנוב."""
        keep = []
        for part in (raw or "").split(";"):
            s = part.strip()
            if not s:
                continue
            k = s.split("=", 1)[0].strip()
            if k in (COOKIE_NAME, PRE_COOKIE):
                continue
            keep.append(s)
        return "; ".join(keep)

    def _proxy(self):
        if not child_listening():
            # הסקריפט עדיין לא עלה או נפל - זה 503 אמיתי, לא דף ריק מזויף
            self._decoy(json_mode=True, slow=False, code=503)
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except Exception:
            n = 0
        if n > MAX_PROXY_BODY:
            self.close_connection = True
            self._decoy(json_mode=True, slow=False, code=413)
            return
        body = self.rfile.read(n) if n > 0 else None
        try:
            conn = http.client.HTTPConnection("127.0.0.1", CHILD_PORT, timeout=180)
            drop = ("host", "content-length", "connection", "accept-encoding",
                    "transfer-encoding", "keep-alive", "proxy-authorization",
                    "proxy-connection", "upgrade", "te", "x-forwarded-for",
                    "x-forwarded-host", "x-forwarded-proto", "x-real-ip")
            headers = {}
            for k, v in self.headers.items():
                if k.lower() in drop:
                    continue
                if k.lower() == "cookie":
                    v = self._strip_cookies(v)
                    if not v:
                        continue
                headers[k] = v
            headers["Host"] = f"127.0.0.1:{CHILD_PORT}"
            headers["X-Forwarded-For"] = self._client_ip()
            headers["X-Real-IP"] = self._client_ip()
            headers["X-Forwarded-Host"] = self.headers.get("Host", "")
            headers["X-Forwarded-Proto"] = "https" if SPACE_HOST else "http"
            if body is not None:
                headers["Content-Length"] = str(len(body))
            conn.request(self.command, self.path, body=body, headers=headers)
            r = conn.getresponse()
            data = r.read()
            self.send_response_only(200 if MASK_PROXY_STATUS else r.status)
            skip = {"transfer-encoding", "content-encoding", "connection",
                    "content-length", "keep-alive", "server", "date"}
            for k, v in r.getheaders():
                if k.lower() not in skip:
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                if self.command != "HEAD":
                    self.wfile.write(data)
            except Exception:
                pass
            conn.close()
        except Exception:
            # הסקריפט קרס או לא הגיב - 502 אמיתי (bad gateway)
            self._decoy(json_mode=True, slow=False, code=502)

    # ---------------- דלת הכניסה ----------------

    def _door(self):
        """
        הכתובת הראשית. זה הדבר היחיד שאפשר לנחש - וגם הוא לא מגלה כלום:
        טופס כניסה בלבד. כל שאר הניהול חי מאחורי הנתיבים החשאיים.
        """
        ip = self._client_ip()
        if not rate_ok(ip):
            self._decoy()
            return
        pre = self._cookie(PRE_COOKIE) or secrets.token_urlsafe(24)
        CTX.csrf = csrf_make(pre)
        cookies = [self._pre_cookie(pre)]
        if not is_configured():
            env_tok = (os.environ.get("SETUP_TOKEN") or "").strip()
            if setup_allowed() and not env_tok:
                self._send(200, setup_page(), cookies=cookies)
            else:
                self._send(200, setup_page(need_token=True), cookies=cookies)
            return
        if not self._authed():
            self._send(200, login_page(), cookies=cookies)
            return
        self._go(ROUTES["home"])

    def _login_screen(self, msg=""):
        pre = self._cookie(PRE_COOKIE) or secrets.token_urlsafe(24)
        CTX.csrf = csrf_make(pre)
        self._send(200, login_page(msg), cookies=[self._pre_cookie(pre)])

    # ---------------- GET ----------------

    def do_GET(self):
        path = self._path()
        if path is None:
            self._decoy()
            return
        if path == "/":
            self._door()
            return
        if path == "/favicon.ico":
            self._send(200, b"", "image/x-icon")
            return

        # נתיב הניטור הציבורי. מכוון: הוא לא סודי, כי שירות ניטור חיצוני חייב
        # להגיע אליו בלי סיסמה. מה שהוא מחזיר זה "OK" ותו לא - אין בו נתיב
        # אחסון, אין מספרי קבצים, אין גרסה ואין רמז לקיומו של ממשק ניהול.
        # זה בדיוק מה שהיה חסר: לפני כן נתיב כזה לא היה קיים, שירות הפינג
        # קיבל דף ריק, והספייס נעצר אחרי 48 שעות כאילו איש לא ביקר בו.
        if PUBLIC_PING and path in ("/__ping", "/__alive", "/healthz"):
            self._send(200, "OK", "text/plain; charset=utf-8", mask=False)
            return

        name = match_route(path)
        if name == "":
            self._proxy()                      # שייך לסקריפט שלך
            return
        if not rate_ok(self._client_ip()):
            self._decoy()
            return
        if name == "?" or not self._authed():
            self._decoy()
            return

        sid = self._sid()
        if name == "home":
            CTX.csrf = csrf_make(sid)
            self._send(200, dashboard(pop_flash(sid)))
            return
        if name == "logs":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            try:
                since = int((q.get("since") or ["0"])[0])
            except Exception:
                since = 0
            lines, seq = logs_since(since)
            self._send(200, json.dumps({"n": seq, "lines": lines[-300:],
                                        "running": RUNNER.alive(), "uptime": RUNNER.uptime()},
                                       ensure_ascii=False), "application/json; charset=utf-8")
            return
        if name == "health":
            self._send(200, json.dumps({
                "ok": True, "app": APP_NAME, "version": VERSION,
                "script_running": RUNNER.alive(), "script_file_present": os.path.exists(SCRIPT_FILE),
                "child_port_open": child_listening(), "restarts": RUNNER.restarts,
                "uptime": RUNNER.uptime(),
                "storage": {
                    "dir": DATA_DIR, "kind": STORAGE["kind"], "is_mount": STORAGE["is_mount"],
                    "fstype": STORAGE["fstype"], "readonly": STORAGE["readonly"],
                    "verified_persistent": STORAGE["verified"], "boots": STORAGE["boots"],
                    "used_bytes": STORAGE["used_bytes"], "used_human": fmt_size(STORAGE["used_bytes"]),
                    "quota_bytes": int(STORAGE["quota_bytes"]), "quota_human": fmt_size(STORAGE["quota_bytes"]),
                    "quota_source": STORAGE["quota_source"],
                    "free_human": fmt_size(free_bytes()), "used_pct": round(used_pct(), 2),
                    "files": STORAGE["files"], "audio_files": STORAGE["audio_files"],
                    "audio_human": fmt_size(STORAGE["audio_bytes"]),
                    "fs_reported_total": STORAGE["fs_total"], "fs_reliable": STORAGE["fs_reliable"],
                    "scan_partial": STORAGE["scan_partial"],
                    "scan_age_sec": int(time.time()-STORAGE["scan_ts"]) if STORAGE["scan_ts"] else None,
                },
                "log": {"path": _log_state["path"], "reset_hours": LOG_RESET_HOURS,
                        "resets": _log_state["resets"], "fallback_dir": _log_state["fallback"]},
                "backup_enabled": _backup["enabled"],
            }, ensure_ascii=False), "application/json; charset=utf-8")
            return
        self._decoy()

    # ---------------- POST ----------------

    def do_POST(self):
        path = self._path()
        if path is None:
            self._decoy()
            return
        if path == "/":
            self._door()
            return

        name = match_route(path)
        if name == "":
            self._proxy()
            return

        ip = self._client_ip()
        if not rate_ok(ip):
            self._decoy()
            return

        # --- הגדרה ראשונית ---
        if name == "setup":
            if is_configured():
                self._go("/")
                return
            f = self._form()
            pre = self._cookie(PRE_COOKIE)
            if not pre or not csrf_ok(pre, f.get("_t", "")):
                self._decoy()
                return
            need_tok = bool((os.environ.get("SETUP_TOKEN") or "").strip())
            if not setup_allowed(f.get("setup_token", "")):
                log(f"🚫 ניסיון הגדרה ראשונית ללא אסימון תקף מכתובת {ip}")
                CTX.csrf = csrf_make(pre)
                self._send(200, setup_page(note("אסימון ההגדרה שגוי או שחלון ההגדרה נסגר. "
                                                "הפעל מחדש את הספייס או הגדר SETUP_TOKEN.", "bad"),
                                           need_token=True))
                return
            u, p, p2 = f.get("username", "").strip(), f.get("password", ""), f.get("password2", "")
            CTX.csrf = csrf_make(pre)
            if len(u) < 2:
                self._send(200, setup_page(note("שם המשתמש קצר מדי.", "bad"), need_tok))
                return
            if len(p) < MIN_PASSWORD:
                self._send(200, setup_page(note(f"הסיסמה חייבת להיות באורך {MIN_PASSWORD} תווים לפחות.", "bad"), need_tok))
                return
            if p != p2:
                self._send(200, setup_page(note("הסיסמאות אינן זהות.", "bad"), need_tok))
                return
            set_credentials(u, p)
            log(f"🔐 הוגדרה גישה עבור המשתמש {u}")
            tok = new_session(self._fp(), ip)
            self._go(ROUTES["home"], cookies=[self._cookie_str(tok), self._clear(PRE_COOKIE)])
            return

        # --- כניסה ---
        if name == "login":
            f = self._form()
            pre = self._cookie(PRE_COOKIE)
            if not pre or not csrf_ok(pre, f.get("_t", "")):
                # טופס שלא נטען מהדף שלנו: אין ספירת כישלון (כדי שלא ינעלו אותך בכוונה),
                # אבל גם אין שום מידע חזרה. בוט עיוור מקבל דף ריק.
                self._decoy()
                return
            ok, msg = check_login(f.get("username", ""), f.get("password", ""), ip=ip)
            if not ok:
                time.sleep(0.25 + secrets.randbelow(400) / 1000.0)
                self._login_screen(note(html.escape(msg), "bad"))
                return
            tok = new_session(self._fp(), ip)
            log(f"✅ כניסה מוצלחת מכתובת {ip}")
            self._go(ROUTES["home"], cookies=[self._cookie_str(tok), self._clear(PRE_COOKIE)])
            return

        # --- מכאן והלאה: חובה להיות מחובר וחובה אסימון CSRF תקף ---
        if name == "?" or not self._authed():
            self._decoy()
            return
        f = self._form()
        if not self._csrf_ok(f):
            self._decoy()
            return
        sid = self._sid()

        if name == "logout":
            for t in list(sessions().keys()):
                drop_session(t)
            self._go("/", cookies=[self._clear(COOKIE_NAME), self._clear(PRE_COOKIE)])
            return

        if name == "reveal":
            a = auth_data()
            ok, _ = check_login(a.get("username", ""), f.get("password", ""), ip=ip)
            if not ok:
                time.sleep(0.25 + secrets.randbelow(400) / 1000.0)
                self._flash(sid, "הסיסמה שגויה. הקוד לא הוצג.", "bad")
                return
            try:
                code = read_script()
            except Exception as e:
                self._flash(sid, f"לא ניתן לפענח את הקוד: {e}", "bad")
                return
            log("👁️ הקוד השמור הוצג לעריכה חד-פעמית.")
            CTX.csrf = csrf_make(sid)
            self._send(200, dashboard(code_text=code))
            return

        if name == "run":
            conf = load_json(CONF_FILE, DEFAULT_CONF)
            conf["pip_packages"] = f.get("pip", "").strip()
            conf["autostart"] = "autostart" in f
            conf["keepalive"] = "keepalive" in f
            conf["updated"] = time.time()
            save_json(CONF_FILE, conf)

            code = f.get("code", "")
            saved = save_script(code) if code.strip() else False

            if f.get("action", "run") == "save":
                threading.Thread(target=lambda: refresh_storage(True), daemon=True).start()
                self._flash(sid, "הקוד וההגדרות נשמרו בדלי." if saved
                            else "ההגדרות נשמרו. לא היה קוד חדש לשמור.")
                return

            if RUNNER.busy:
                self._flash(sid, f"רגע, המערכת כבר {RUNNER.busy}. הלוג למטה מתעדכן לבד.", "ok")
                return

            # ההפעלה רצה ברקע: התקנת חבילות ועליית סקריפט גדול לוקחות זמן,
            # ואסור שהדפדפן יישאר תלוי ויתקע. הדף חוזר מיד, וההתקדמות בלוג.
            def _run_job():
                RUNNER.busy = "מפעילה את הסקריפט"
                try:
                    if RUNNER.alive():
                        RUNNER.stop(by_user=True, reason="הפעלה מחדש")
                    ok, msg = RUNNER.start()
                    if not ok:
                        log(f"⚠️ {msg}")
                finally:
                    RUNNER.busy = ""
            threading.Thread(target=_run_job, daemon=True).start()
            self._flash(sid, "הקוד נשמר והסקריפט עולה. עקוב אחרי הלוג למטה.")
            return

        if name == "stop":
            if RUNNER.busy:
                self._flash(sid, f"רגע, המערכת כבר {RUNNER.busy}.", "ok")
                return

            def _stop_job():
                RUNNER.busy = "עוצרת את הסקריפט"
                try:
                    RUNNER.stop(by_user=True)
                finally:
                    RUNNER.busy = ""
            threading.Thread(target=_stop_job, daemon=True).start()
            self._flash(sid, "פקודת העצירה נשלחה. אפשר להדביק קוד חדש כבר עכשיו.")
            return

        if name == "rescan":
            threading.Thread(target=lambda: refresh_storage(True), daemon=True).start()
            self._flash(sid, "סריקת האחסון רצה ברקע. רענן בעוד כמה שניות לתוצאה מעודכנת.")
            return

        if name == "purge":
            def _purge_job():
                freed, n = purge_audio(reason="בקשה ידנית")
                refresh_storage(True)
                log(f"סיכום פינוי: {n} קבצי אודיו, {fmt_size(freed)}")
            threading.Thread(target=_purge_job, daemon=True).start()
            self._flash(sid, "מפנה קבצי אודיו ישנים ברקע. קבצי טקסט, ini ו-json לא ייגעו.")
            return

        if name == "resetlog":
            reset_log_file()
            self._flash(sid, "server.log נמחק ונוצר מחדש.")
            return

        if name == "backup":
            threading.Thread(target=lambda: backup_now("(ידני)", force=True), daemon=True).start()
            self._flash(sid, "הגיבוי רץ ברקע. התוצאה תופיע בלוג.")
            return

        if name == "restore":
            def _restore_job():
                ok, msg = restore_backup(force=True)
                log(("♻️ " if ok else "⚠️ ") + msg)
            threading.Thread(target=_restore_job, daemon=True).start()
            self._flash(sid, "השחזור רץ ברקע. התוצאה תופיע בלוג.")
            return

        self._decoy()

    # ---------------- שאר השיטות ----------------

    def _passthrough(self):
        path = self._path()
        if path is None or path == "/" or match_route(path) != "":
            self._decoy()
            return
        self._proxy()

    def do_PUT(self):
        self._passthrough()

    def do_PATCH(self):
        self._passthrough()

    def do_DELETE(self):
        self._passthrough()

    def do_OPTIONS(self):
        self._passthrough()

    def do_HEAD(self):
        path = self._path()
        if path is None:
            self._decoy()
            return
        if path == "/" or match_route(path) != "":
            self._send(200, b"")
            return
        self._proxy()


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128


# ==========================================================================================
# 13. עלייה
# ==========================================================================================

def banner():
    log("=" * 70)
    log(f"  {APP_NAME}  ·  גרסה {VERSION}")
    log("=" * 70)
    log(f"🔗 כתובת ציבורית:   {PUBLIC_URL}")
    log(f"💾 תיקיית נתונים:   {DATA_DIR}   [{STORAGE['kind_he']}"
        f"{' · mount אמיתי' if STORAGE['is_mount'] else ' · לא נקודת עגינה'}"
        f"{' · ' + STORAGE['fstype'] if STORAGE['fstype'] else ''}]")
    log(f"📀 אחסון:            {fmt_size(STORAGE['used_bytes'])} בשימוש מתוך "
        f"{fmt_size(STORAGE['quota_bytes'])} ({used_pct():.2f}%) · נשאר {fmt_size(free_bytes())}")
    log(f"   מקור המכסה:      {STORAGE['quota_source']}")
    log(f"   נסרקו {STORAGE['files']:,} קבצים ב-{STORAGE['scan_secs']:.1f} שניות"
        f"{' (סריקה חלקית)' if STORAGE['scan_partial'] else ''}"
        f" · מתוכם אודיו: {STORAGE['audio_files']:,} ({fmt_size(STORAGE['audio_bytes'])})")
    if not STORAGE["fs_reliable"] and STORAGE["fs_total"]:
        log(f"   הערה: מערכת הקבצים מדווחת {STORAGE['fs_total']/GB:,.0f} GB - מספר דמה של "
            f"אחסון אובייקטים. לא בשימוש לחישוב.")
    if STORAGE["verified"]:
        log(f"✅ אימות: הסמן שרד {STORAGE['boots']-1} הפעלות מחדש - הדלי באמת שומר נתונים.")
    else:
        log("ℹ️ אימות: זו העלייה הראשונה בתיקייה הזו. אחרי restart אחד יופיע אישור מלא.")
    log(f"🐍 קובץ הפייתון:    {SCRIPT_FILE}  [{'קיים' if os.path.exists(SCRIPT_FILE) else 'עדיין אין'}]")
    log(f"📝 קובץ הלוג:       {_log_state['path']}  (נמחק ונוצר מחדש כל {LOG_RESET_HOURS:g} שעות)")
    log(f"🔌 פורט ממשק {APP_PORT}  ·  פורט הסקריפט {CHILD_PORT}")
    log("🛡️ אבטחה: כל נתיבי הניהול חשאיים ונגזרים מסוד אקראי ששמור בדלי.")
    log(f"   מיסוך סטטוס: {'פעיל - הכל יוצא 200' if MASK_STATUS else 'כבוי'}"
        f"  ·  קשירת עוגייה לדפדפן: {'פעילה' if BIND_SESSION else 'כבויה'}"
        f"  ·  הצפנת הקוד בדלי: {'פעילה' if CODE_KEY else 'כבויה (הגדר CODE_KEY)'}")
    log("   נכנסים דרך הכתובת הראשית בלבד. אחרי ההתחברות תקבל את כתובת לוח")
    log("   הבקרה הפרטית שלך - שמור אותה בסימנייה.")
    log("")
    log("🛡️ גרסה 6.2 - התאמות למדיניות Hugging Face:")
    log("   · אין פינג עצמי פנימי (נראה כמו בוט). לניטור: הפנה שירות חיצוני")
    log(f"     כמו UptimeRobot לכתובת {PUBLIC_URL}/__ping - היא מחזירה OK בלבד.")
    log(f"   · מיסוך סטטוס: {'פעיל (לא מומלץ)' if MASK_STATUS else 'כבוי - השרת מחזיר קודים רגילים'}")
    log(f"   · גיבוי אוטומטי ל-Hub: {'פעיל' if AUTO_BACKUP else 'כבוי - כתיבה תוכפתית ל-Hub נראית כמו בוט'}")
    if not HF_TOKEN:
        log("   · לניטור חיצוני של ספייס פרטי צריך HF_TOKEN, או להעביר ל-Public.")
    if not is_configured():
        log("🔑 המערכת עדיין לא הוגדרה. אסימון הגדרה חד-פעמי לשעת הצורך:")
        log(f"   {BOOT_SETUP_TOKEN}")
        log(f"   (או פשוט קבע סיסמה ב-{SETUP_WINDOW_MIN:g} הדקות הראשונות מרגע זה)")
    if STORAGE["kind"] == "ephemeral":
        log("⚠️  התיקייה אינה מחוברת לדלי! הנתונים יימחקו ב-restart הבא.")
        log("   הגדרות הספייס → Storage Buckets → חבר דלי בנתיב /data")
    log("=" * 70)


def _boot_start():
    """
    הפעלת הקוד השמור בעליית המרחב, בצורה חסינה.

    למה זה קריטי: כשHugging Face עושים restart (וזה קורה הרבה - אחרי שינה,
    אחרי תחזוקה, אחרי עדכון), המרחב עולה מאפס. אם ההפעלה הראשונה נכשלת מסיבה
    זמנית - הפורט הפנימי עוד תפוס משנייה קודם, התקנת pip איטית, או עומס רגעי -
    לא רוצים שהקוד פשוט יישאר כבוי עד שתיכנס ידנית. לכן מנסים כמה פעמים.

    זה בלתי תלוי ב-keepalive: גם אם המשתמש כיבה את "הפעלה מחדש אם נפל", הקוד
    עדיין יעלה בעצמו אחרי restart, כי זו התנהגות נפרדת שהמשתמש ציפה לה כשסימן
    "הפעלה אוטומטית כשהשרת עולה".
    """
    delays = [0, 5, 12, 25, 45]
    for i, d in enumerate(delays):
        if d:
            time.sleep(d)
        if RUNNER.alive():
            return
        if not ensure_script_present():
            log("ℹ️ אין קוד שמור להפעלה בעלייה.")
            return
        ok, msg = RUNNER.start(install_pip=(i == 0))
        if ok:
            return
        log(f"⚠️ ההפעלה בעלייה נכשלה (ניסיון {i + 1}/{len(delays)}): {msg}")
    log("❌ הקוד לא הצליח לעלות אחרי כמה ניסיונות. בדוק את הלוג, או הפעל ידנית מהפאנל.")


def main():
    # סדר העלייה: קודם לוודא מה יש בדלי, ורק אחר כך להריץ
    verify_persistence()
    refresh_storage(True)
    banner()
    space_guard()
    if AUTO_BACKUP:
        backup_init()
    kill_orphans()

    conf = load_json(CONF_FILE, DEFAULT_CONF)
    if ensure_script_present(quiet=False):
        if conf.get("autostart", True):
            log("🚀 נמצא קוד שמור בדלי - מפעיל אותו עכשיו.")
            threading.Thread(target=_boot_start, daemon=True).start()
        else:
            log("ℹ️ יש קוד שמור בדלי, אבל ההפעלה האוטומטית כבויה.")
    else:
        log("ℹ️ אין עדיין קוד שמור בדלי. לאחר שתדביק קוד ותלחץ הפעלה, הוא יעלה")
        log("   אוטומטית בכל הפעלה מחדש של המרחב.")

    threading.Thread(target=watchdog, daemon=True).start()

    def bye(*_):
        log("👋 המרחב נסגר (ככל הנראה restart של HF). הקוד יעלה שוב אוטומטית.")
        # שים לב: עוצרים בלי by_user=True. כיבוי של HF הוא לא "המשתמש ביקש
        # לעצור" - זה restart, והקוד השמור אמור לחזור ולעלות מעצמו כשהמרחב
        # יחזור. סימון by_user היה חוסם את ההפעלה האוטומטית הבאה.
        try:
            RUNNER.stop(by_user=False, reason="כיבוי המרחב")
        except Exception:
            pass
        os._exit(0)

    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGINT, bye)

    srv = Server(("0.0.0.0", APP_PORT), Handler)
    log(f"✅ הממשק פעיל. פתח את {PUBLIC_URL}")
    srv.serve_forever()


if __name__ == "__main__":
    main()

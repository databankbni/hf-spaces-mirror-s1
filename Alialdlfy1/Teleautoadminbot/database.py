import json
import os
import time
import shutil
from threading import Lock

DB_FILE = "/data/data.json"
BACKUP_DIR = "/data/backups"
SCHEMA_VERSION = 2
lock = Lock()

DEFAULT_BLOCKED_WORDS = [
    "إعلان", "اعلان", "تبادل", "ممول", "تمويل", "للتواصل",
    "اشتراك", "تابعونا", "اشترك", "قناتنا", "بوت", "عبر البوت",
    "عرض خاص", "لفترة محدودة", "اضغط هنا", "لمشاهدة المزيد",
    "حصرياً", "تم النشر بواسطة"
]

DEFAULT_DATA = {
    "schema_version": SCHEMA_VERSION,
    "channels": {},
    "public_sources": [],
    "source_meta": {},
    "blocked_words": DEFAULT_BLOCKED_WORDS,
    "allowed_users": [],
    "last_source_messages": {},
    "settings": {},
    "global_remove_terms": [],
    "recent_fingerprints": [],
    "source_stats": {},
    "source_logs": {},
    "system": {},
    "last_errors": [],
    "named_backups": [],
    "channel_failures": {},
    "published_messages": {},
    "sessions": {},
    "ai_keys": {},
    "publishing_bots": {},
    "websites": {},
    "trash": [],
    "naming_counters": {"session": 0, "ai_key": 0, "bot": 0, "website": 0},
    "channel_configs": {},
    "settings_clipboard": None,
    "_migrated_channel_word_lists": False,
    "notification_settings": {
        "session_stopped": True,
        "ai_key_error": True,
        "source_stopped": True,
        "channel_idle_hour": True,
        "backup_failed": True,
        "db_issue": True,
        "last_alert_ts": {},
    },
}


def _now():
    return int(time.time())


def _dedupe_int_list(values):
    out = []
    seen = set()
    for value in values or []:
        try:
            item = int(value)
        except Exception:
            item = value
        key = str(item)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _normalize_channel(cid, value):
    if not isinstance(value, dict):
        value = {"name": str(value)}
    value.setdefault("name", value.get("title") or str(cid))
    value.setdefault("title", value.get("name") or str(cid))
    value.setdefault("username", "")
    value.setdefault("link", "")
    value.setdefault("chat_type", "")
    value.setdefault("tail", "")
    value.setdefault("special_sources", [])
    value.setdefault("paused", False)
    value.setdefault("posts_count", 0)
    value.setdefault("publish_delay", None)
    value.setdefault("bold_publish", True)
    value.setdefault("quote_publish", False)
    # إعدادات الاقتباس حسب نوع المنشور.
    # توافق رجعي: إذا كان quote_publish القديم مفعلاً، نفعّل كل الأنواع افتراضياً.
    old_quote = bool(value.get("quote_publish", False))
    quote_types = value.get("quote_types")
    if not isinstance(quote_types, dict):
        quote_types = {}
    value["quote_types"] = {
        "text": bool(quote_types.get("text", old_quote)),
        "photo": bool(quote_types.get("photo", old_quote)),
        "video": bool(quote_types.get("video", old_quote)),
        "album": bool(quote_types.get("album", old_quote)),
    }
    # يبقى المفتاح القديم موجود للتوافق مع النسخ الاحتياطية القديمة.
    value["quote_publish"] = any(value["quote_types"].values())
    value.setdefault("hashtags", [])
    if not isinstance(value.get("hashtags"), list):
        value["hashtags"] = []
    value.setdefault("fail_count", 0)
    value.setdefault("disable_web_page_preview", False)
    value.setdefault("added_at", _now())
    value.setdefault("tail_enabled", True)
    # None means the channel has not yet inherited the legacy global setting.
    value.setdefault("ignore_short_posts", None)
    value.setdefault("tail_min_words", 20)
    value.setdefault("tail_position", "bottom")
    value["special_sources"] = _dedupe_int_list(value.get("special_sources", []))
    # الكلمات المحظورة وقائمة الحذف الآن مستقلة لكل قناة (وليست عامة).
    # None = لم تُهاجَر/تُحدَّد بعد؛ تتم معالجتها لاحقاً في _normalize_data.
    if not isinstance(value.get("blocked_words"), list):
        value["blocked_words"] = None
    if not isinstance(value.get("delete_terms"), list):
        value["delete_terms"] = None
    return value


def _normalize_source_meta(source_id, value=None):
    if not isinstance(value, dict):
        value = {}
    sid = str(source_id)
    value.setdefault("id", int(source_id) if str(source_id).lstrip('-').isdigit() else source_id)
    value.setdefault("name", value.get("title") or sid)
    value.setdefault("title", value.get("name") or sid)
    value.setdefault("username", "")
    value.setdefault("link", "")
    value.setdefault("chat_type", "")
    value.setdefault("added_at", _now())
    value.setdefault("paused", False)
    value.setdefault("remove_terms", [])
    if not isinstance(value.get("remove_terms"), list):
        value["remove_terms"] = []
    value.setdefault("remove_emoji", False)
    default_types = {"text": True, "photo": True, "video": True, "album": True, "voice": False, "audio": False, "document": False}
    types = value.get("content_types")
    if not isinstance(types, dict):
        types = {}
    value["content_types"] = {k: bool(types.get(k, v)) for k, v in default_types.items()}
    return value


def _normalize_data(data):
    if not isinstance(data, dict):
        data = {}

    for key, value in DEFAULT_DATA.items():
        if key not in data:
            data[key] = value.copy() if isinstance(value, (list, dict)) else value

    if not isinstance(data.get("channels"), dict):
        data["channels"] = {}
    if not isinstance(data.get("public_sources"), list):
        data["public_sources"] = []
    if not isinstance(data.get("source_meta"), dict):
        data["source_meta"] = {}
    if not isinstance(data.get("blocked_words"), list):
        data["blocked_words"] = DEFAULT_BLOCKED_WORDS.copy()
    if not isinstance(data.get("allowed_users"), list):
        data["allowed_users"] = []
    if not isinstance(data.get("last_source_messages"), dict):
        data["last_source_messages"] = {}
    if not isinstance(data.get("settings"), dict):
        data["settings"] = {}
    if not isinstance(data.get("global_remove_terms"), list):
        data["global_remove_terms"] = []
    if not isinstance(data.get("recent_fingerprints"), list):
        data["recent_fingerprints"] = []
    if not isinstance(data.get("source_stats"), dict):
        data["source_stats"] = {}
    if not isinstance(data.get("source_logs"), dict):
        data["source_logs"] = {}
    if not isinstance(data.get("system"), dict):
        data["system"] = {}
    if not isinstance(data.get("last_errors"), list):
        data["last_errors"] = []
    if not isinstance(data.get("named_backups"), list):
        data["named_backups"] = []
    if not isinstance(data.get("channel_failures"), dict):
        data["channel_failures"] = {}
    if not isinstance(data.get("published_messages"), dict):
        data["published_messages"] = {}
    if not isinstance(data.get("sessions"), dict):
        data["sessions"] = {}
    if not isinstance(data.get("ai_keys"), dict):
        data["ai_keys"] = {}
    if not isinstance(data.get("publishing_bots"), dict):
        data["publishing_bots"] = {}
    if not isinstance(data.get("websites"), dict):
        data["websites"] = {}
    if not isinstance(data.get("trash"), list):
        data["trash"] = []
    if not isinstance(data.get("naming_counters"), dict):
        data["naming_counters"] = {"session": 0, "ai_key": 0, "bot": 0, "website": 0}
    if not isinstance(data.get("channel_configs"), dict):
        data["channel_configs"] = {}
    if not isinstance(data.get("notification_settings"), dict):
        data["notification_settings"] = DEFAULT_DATA["notification_settings"].copy()
    ns = data["notification_settings"]
    for k, v in DEFAULT_DATA["notification_settings"].items():
        ns.setdefault(k, v.copy() if isinstance(v, dict) else v)

    data.setdefault("settings_clipboard", None)

    data["schema_version"] = SCHEMA_VERSION
    data["public_sources"] = _dedupe_int_list(data.get("public_sources", []))

    channels = {}
    for cid, ch in data.get("channels", {}).items():
        channels[str(cid)] = _normalize_channel(cid, ch)
    data["channels"] = channels

    # توافق رجعي: القنوات القديمة ترث قيمة الفلتر العام مرة واحدة في الذاكرة،
    # ثم تُحفظ القيمة محلياً عند أول كتابة لاحقة دون تغيير الإعداد العام.
    legacy_ignore_short = bool(data.get("settings", {}).get("ignore_short_posts", False))
    for ch in data["channels"].values():
        if ch.get("ignore_short_posts") is None:
            ch["ignore_short_posts"] = legacy_ignore_short

    # هجرة لمرة واحدة: نسخ القوائم العامة القديمة (الكلمات المحظورة / قائمة
    # الحذف العامة) داخل كل قناة موجودة حتى تصبح كل قناة مستقلة بقوائمها،
    # بدون فقدان البيانات القديمة. تعمل مرة وحدة فقط بفضل العلم أدناه، حتى
    # القنوات التي تُفرّغ قوائمها لاحقاً ما تنرجع تنعبي من جديد.
    if not data.get("_migrated_channel_word_lists"):
        legacy_blocked = data.get("blocked_words") or DEFAULT_BLOCKED_WORDS.copy()
        legacy_terms = data.get("global_remove_terms") or []
        for ch in data["channels"].values():
            if ch.get("blocked_words") is None:
                ch["blocked_words"] = list(legacy_blocked)
            if ch.get("delete_terms") is None:
                ch["delete_terms"] = list(legacy_terms)
        data["_migrated_channel_word_lists"] = True

    # أي قناة بلا قيمة بعد (مثلاً أُضيفت حديثاً بعد الهجرة) تاخذ افتراضي فارغ/عام.
    for ch in data["channels"].values():
        if ch.get("blocked_words") is None:
            ch["blocked_words"] = DEFAULT_BLOCKED_WORDS.copy()
        if ch.get("delete_terms") is None:
            ch["delete_terms"] = []

    meta = {}
    for source in data["public_sources"]:
        sid = str(source)
        meta[sid] = _normalize_source_meta(source, data.get("source_meta", {}).get(sid, {}))
    for sid, value in data.get("source_meta", {}).items():
        if sid not in meta:
            meta[sid] = _normalize_source_meta(sid, value)
    data["source_meta"] = meta

    # normalize last source ids as strings
    data["last_source_messages"] = {str(k): v for k, v in data.get("last_source_messages", {}).items()}
    return data



def _is_valid_data(data, allow_empty=True):
    """يتأكد أن ملف البيانات صالح وليس فارغاً/تالفاً."""
    if not isinstance(data, dict):
        return False
    if "channels" not in data or "public_sources" not in data:
        return False
    if not isinstance(data.get("channels"), dict):
        return False
    if not isinstance(data.get("public_sources"), list):
        return False
    if not allow_empty:
        if not data.get("channels") and not data.get("public_sources") and not data.get("source_meta"):
            return False
    return True


def _load_json_file(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not _is_valid_data(data, allow_empty=True):
        raise ValueError("ملف بيانات غير صالح")
    return _normalize_data(data)


def _backup_candidates():
    files = []
    if os.path.exists(DB_FILE + ".bak"):
        files.append(DB_FILE + ".bak")
    if os.path.isdir(BACKUP_DIR):
        files.extend(
            os.path.join(BACKUP_DIR, x)
            for x in os.listdir(BACKUP_DIR)
            if x.endswith(".json")
        )
    return sorted(files, key=lambda p: os.path.getmtime(p), reverse=True)


def _restore_latest_backup():
    """يحاول استعادة أحدث نسخة احتياطية صالحة."""
    os.makedirs("/data", exist_ok=True)
    for path in _backup_candidates():
        try:
            data = _load_json_file(path)
            tmp = DB_FILE + ".restore.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, DB_FILE)
            return data
        except Exception:
            continue
    return None


def verify_or_recover_storage():
    """فحص تخزين آمن عند تشغيل التطبيق/البوت."""
    os.makedirs("/data", exist_ok=True)
    if os.path.exists(DB_FILE):
        try:
            data = _load_json_file(DB_FILE)
            return {"ok": True, "recovered": False, "message": "data.json صالح", "data": data}
        except Exception as e:
            recovered = _restore_latest_backup()
            if recovered is not None:
                return {"ok": True, "recovered": True, "message": f"تمت الاستعادة من Backup بعد تلف data.json: {e}", "data": recovered}
            return {"ok": False, "recovered": False, "message": f"data.json تالف ولا توجد نسخة احتياطية صالحة: {e}", "data": None}

    recovered = _restore_latest_backup()
    if recovered is not None:
        return {"ok": True, "recovered": True, "message": "تمت الاستعادة من Backup لأن data.json غير موجود", "data": recovered}

    # أول تشغيل فقط: إنشاء ملف جديد فارغ
    data = _normalize_data(DEFAULT_DATA.copy())
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {"ok": True, "recovered": False, "message": "تم إنشاء قاعدة بيانات جديدة", "data": data}


def _read():
    os.makedirs("/data", exist_ok=True)
    status = verify_or_recover_storage()
    if not status.get("ok"):
        raise RuntimeError(status.get("message", "فشل قراءة قاعدة البيانات"))
    return _normalize_data(status.get("data") or DEFAULT_DATA.copy())


def _make_prewrite_backup():
    """نسخة احتياطية فورية قبل أي كتابة حتى لا تضيع البيانات عند توقف الاستضافة."""
    try:
        if os.path.exists(DB_FILE) and os.path.getsize(DB_FILE) > 5:
            shutil.copy2(DB_FILE, DB_FILE + ".bak")
    except Exception:
        pass


def _write(data):
    os.makedirs("/data", exist_ok=True)
    data = _normalize_data(data)

    # حماية من الكتابة بملف فارغ فوق بيانات موجودة
    if not _is_valid_data(data, allow_empty=True):
        raise ValueError("رفض كتابة بيانات غير صالحة")

    _make_prewrite_backup()
    tmp_file = DB_FILE + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        try:
            os.fsync(f.fileno())
        except Exception:
            pass
    os.replace(tmp_file, DB_FILE)


def _write_backup(data):
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        data = _normalize_data(data)
        if not _is_valid_data(data, allow_empty=True):
            return
        backup_file = os.path.join(BACKUP_DIR, f"backup_{int(time.time())}.json")
        with open(backup_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # keep last 20 backups
        files = sorted([os.path.join(BACKUP_DIR, x) for x in os.listdir(BACKUP_DIR) if x.endswith('.json')])
        for old in files[:-20]:
            try:
                os.remove(old)
            except Exception:
                pass
    except Exception:
        pass

def get_all_channels():
    with lock:
        data = _read()
    return [{"id": k, **v} for k, v in data["channels"].items()]


def add_channel(channel_id, name="", title="", username="", link="", chat_type=""):
    cid = str(channel_id)
    with lock:
        data = _read()
        created = cid not in data["channels"]
        if created:
            data["channels"][cid] = _normalize_channel(cid, {
                "name": title or name or cid,
                "title": title or name or cid,
                "username": username or "",
                "link": link or "",
                "chat_type": chat_type or "",
                "tail": "",
                "special_sources": [],
                "paused": False,
                "posts_count": 0,
                "added_at": _now(),
            })
        else:
            ch = data["channels"][cid]
            if title or name:
                ch["name"] = title or name
                ch["title"] = title or name
            if username is not None:
                ch["username"] = username or ch.get("username", "")
            if link is not None:
                ch["link"] = link or ch.get("link", "")
            if chat_type is not None:
                ch["chat_type"] = chat_type or ch.get("chat_type", "")
        _write(data)
        if created:
            _write_backup(data)
        return created


def delete_channel(channel_id):
    cid = str(channel_id)
    with lock:
        data = _read()
        if cid in data["channels"]:
            del data["channels"][cid]
            _write(data)
            _write_backup(data)
            return True
    return False


def update_channel(channel_id, key, value):
    cid = str(channel_id)
    with lock:
        data = _read()
        if cid in data["channels"]:
            data["channels"][cid][key] = value
            _write(data)
            _write_backup(data)
            return True
    return False


def increment_post_count(channel_id):
    cid = str(channel_id)
    with lock:
        data = _read()
        if cid in data["channels"]:
            data["channels"][cid].setdefault("posts_count", 0)
            data["channels"][cid]["posts_count"] += 1
            _write(data)
            return True
    return False


def get_channel(channel_id):
    cid = str(channel_id)
    with lock:
        data = _read()
    return data["channels"].get(cid)


def get_public_sources():
    with lock:
        data = _read()
    return data["public_sources"]


def get_source_meta(source_id):
    sid = str(source_id)
    with lock:
        data = _read()
    return data.get("source_meta", {}).get(sid, _normalize_source_meta(source_id))


def get_all_public_sources_with_meta():
    with lock:
        data = _read()
    return [{"id": s, **data.get("source_meta", {}).get(str(s), _normalize_source_meta(s))} for s in data["public_sources"]]


def add_public_source(source_id, name="", title="", username="", link="", chat_type=""):
    try:
        source_id = int(source_id)
    except Exception:
        pass
    sid = str(source_id)

    with lock:
        data = _read()
        created = source_id not in data["public_sources"]
        if created:
            data["public_sources"].append(source_id)
        old = data.setdefault("source_meta", {}).get(sid, {})
        meta = _normalize_source_meta(source_id, old)
        if title or name:
            meta["name"] = title or name
            meta["title"] = title or name
        if username is not None:
            meta["username"] = username or meta.get("username", "")
        if link is not None:
            meta["link"] = link or meta.get("link", "")
        if chat_type is not None:
            meta["chat_type"] = chat_type or meta.get("chat_type", "")
        data["source_meta"][sid] = meta
        _write(data)
        if created:
            _write_backup(data)
        return created


def update_source_meta(source_id, **kwargs):
    sid = str(source_id)
    with lock:
        data = _read()
        meta = _normalize_source_meta(source_id, data.setdefault("source_meta", {}).get(sid, {}))
        for key, value in kwargs.items():
            if value is not None:
                meta[key] = value
        data["source_meta"][sid] = meta
        _write(data)
        return True


def remove_public_source(source_id):
    try:
        source_id = int(source_id)
    except Exception:
        pass
    sid = str(source_id)

    with lock:
        data = _read()
        if source_id in data["public_sources"]:
            data["public_sources"].remove(source_id)
            data["last_source_messages"].pop(sid, None)
            data.get("source_meta", {}).pop(sid, None)
            _write(data)
            _write_backup(data)
            return True
    return False


def get_blocked_words():
    with lock:
        data = _read()
    return data["blocked_words"]


def add_blocked_word(word):
    word = str(word).strip()
    if not word:
        return False
    with lock:
        data = _read()
        if word not in data["blocked_words"]:
            data["blocked_words"].append(word)
            _write(data)
            _write_backup(data)
            return True
    return False


def remove_blocked_word(word):
    word = str(word).strip()
    with lock:
        data = _read()
        if word in data["blocked_words"]:
            data["blocked_words"].remove(word)
            _write(data)
            _write_backup(data)
            return True
    return False


# ============================================================
# الكلمات المحظورة / قائمة الحذف — مستقلة لكل قناة
# ============================================================

def get_channel_blocked_words(channel_id):
    cid = str(channel_id)
    with lock:
        data = _read()
        ch = data["channels"].get(cid)
        return list(ch.get("blocked_words", [])) if ch else []


def add_channel_blocked_word(channel_id, word):
    word = str(word).strip()
    if not word:
        return False
    cid = str(channel_id)
    with lock:
        data = _read()
        ch = data["channels"].get(cid)
        if not ch:
            return False
        ch.setdefault("blocked_words", [])
        if word not in ch["blocked_words"]:
            ch["blocked_words"].append(word)
            _write(data)
            _write_backup(data)
            return True
    return False


def remove_channel_blocked_word(channel_id, word):
    word = str(word).strip()
    cid = str(channel_id)
    with lock:
        data = _read()
        ch = data["channels"].get(cid)
        if not ch:
            return False
        if word in ch.get("blocked_words", []):
            ch["blocked_words"].remove(word)
            _write(data)
            _write_backup(data)
            return True
    return False


def get_channel_delete_terms(channel_id):
    cid = str(channel_id)
    with lock:
        data = _read()
        ch = data["channels"].get(cid)
        return list(ch.get("delete_terms", [])) if ch else []


def add_channel_delete_terms(channel_id, terms):
    cid = str(channel_id)
    with lock:
        data = _read()
        ch = data["channels"].get(cid)
        if not ch:
            return {"added": 0, "exists": 0}
        existing = [str(x).strip() for x in ch.get("delete_terms", []) if str(x).strip()]
        added = 0
        exists = 0
        for term in terms:
            term = str(term).strip()
            if not term:
                continue
            if term in existing:
                exists += 1
            else:
                existing.append(term)
                added += 1
        ch["delete_terms"] = existing
        _write(data)
        _write_backup(data)
    return {"added": added, "exists": exists}


def remove_channel_delete_terms(channel_id, terms):
    cid = str(channel_id)
    with lock:
        data = _read()
        ch = data["channels"].get(cid)
        if not ch:
            return {"removed": 0, "missing": 0}
        existing = [str(x).strip() for x in ch.get("delete_terms", []) if str(x).strip()]
        removed = 0
        missing = 0
        for term in terms:
            term = str(term).strip()
            if term in existing:
                existing.remove(term)
                removed += 1
            else:
                missing += 1
        ch["delete_terms"] = existing
        _write(data)
        _write_backup(data)
    return {"removed": removed, "missing": missing}


def get_last_source_message(source_id):
    with lock:
        data = _read()
    value = data.get("last_source_messages", {}).get(str(source_id))
    try:
        if isinstance(value, dict):
            return int(value.get("id")) if value.get("id") is not None else None
        return int(value) if value is not None else None
    except Exception:
        return None

def set_last_source_message(source_id, message_id):
    with lock:
        data = _read()
        data.setdefault("last_source_messages", {})[str(source_id)] = {"id": int(message_id), "ts": _now()}
        _write(data)
        return True

def reset_last_source_message(source_id):
    with lock:
        data = _read()
        if str(source_id) in data.get("last_source_messages", {}):
            del data["last_source_messages"][str(source_id)]
            _write(data)
            _write_backup(data)
            return True
    return False



def claim_source_event(source_id, message_id):
    """يحجز معالجة رسالة بشكل ذري دائم عبر مساري updates وpolling.
    مفتاح الحجز: source_id:message_id داخل source_event_claims.
    يرجع True إذا تم الحجز الآن (المعاملة جديدة)، False إذا كانت محجوزة مسبقاً.
    التنفيذ بالكامل داخل قفل الملف الحالي فلا يحدث سباق TOCTOU.
    """
    if source_id is None or message_id is None:
        return False
    sid = str(source_id)
    mid = int(message_id)
    with lock:
        data = _read()
        claims = data.setdefault("source_event_claims", {})
        per_source = claims.setdefault(sid, [])
        if any(isinstance(x, dict) and int(x.get("message_id", -1)) == mid for x in per_source):
            return False
        per_source.append({"message_id": mid, "ts": _now()})
        claims[sid] = per_source[-2000:]
        _write(data)
        return True


def is_source_event_claimed(source_id, message_id):
    """قراءة فقط: هل سبق حجز هذه الرسالة من أي مسار؟"""
    if source_id is None or message_id is None:
        return False
    sid = str(source_id)
    mid = int(message_id)
    with lock:
        data = _read()
    per_source = data.get("source_event_claims", {}).get(sid, [])
    return any(isinstance(x, dict) and int(x.get("message_id", -1)) == mid for x in per_source)


def release_source_event_claim(source_id, message_id):
    """يحرر claim عند فشل المعالجة حتى تسمح دورة لاحقة بإعادة المحاولة.
    العملية ذرية داخل القفل، ولا تحذف إلا claim المطابق للمصدر والرسالة."""
    if source_id is None or message_id is None:
        return False
    sid = str(source_id)
    mid = int(message_id)
    with lock:
        data = _read()
        claims = data.setdefault("source_event_claims", {})
        per_source = claims.get(sid, [])
        kept = [x for x in per_source if not (isinstance(x, dict) and int(x.get("message_id", -1)) == mid)]
        if len(kept) == len(per_source):
            return False
        if kept:
            claims[sid] = kept
        else:
            claims.pop(sid, None)
        data["source_event_claims"] = claims
        _write(data)
        return True


def export_data():
    with lock:
        data = _read()
    data = cleanup_old_runtime_data(data, days=3)
    return json.dumps(_normalize_data(data), ensure_ascii=False, indent=2)


def import_data(json_str):
    with lock:
        new_data = json.loads(json_str)
        if not _is_valid_data(new_data, allow_empty=False):
            raise ValueError("ملف الاستيراد فارغ أو غير صالح. تم رفضه لحماية بياناتك.")
        new_data = _normalize_data(new_data)

        # لا نقبل ملف بلا قنوات وبلا مصادر إلا إذا كان مقصوداً، وهذا غير مسموح هنا
        if not new_data.get("channels") and not new_data.get("public_sources") and not new_data.get("source_meta"):
            raise ValueError("ملف الاستيراد لا يحتوي قنوات أو مصادر.")

        _make_prewrite_backup()
        _write_backup(_read())
        new_data = cleanup_old_runtime_data(new_data, days=3)
        _write(new_data)
        _write_backup(new_data)
        return {
            "channels": len(new_data.get("channels", {})),
            "public_sources": len(new_data.get("public_sources", [])),
            "source_meta": len(new_data.get("source_meta", {})),
            "blocked_words": len(new_data.get("blocked_words", [])),
            "global_remove_terms": len(new_data.get("global_remove_terms", [])),
            "last_source_messages": len(new_data.get("last_source_messages", {})),
            "recent_fingerprints": len(new_data.get("recent_fingerprints", [])),
        }


def cleanup_old_runtime_data(data=None, days=3):
    """حذف بيانات التكرار والسجلات و IDs المؤقتة الأقدم من 3 أيام حتى لا يكبر الملف."""
    cutoff = _now() - int(days) * 86400
    own_write = data is None
    if data is None:
        data = _read()

    items = data.get("recent_fingerprints", [])
    if isinstance(items, list):
        data["recent_fingerprints"] = [
            x for x in items
            if isinstance(x, dict) and int(x.get("ts", _now())) >= cutoff
        ][-500:]

    logs = data.get("source_logs", {})
    if isinstance(logs, dict):
        new_logs = {}
        for sid, entries in logs.items():
            if isinstance(entries, list):
                new_logs[sid] = [
                    x for x in entries
                    if isinstance(x, dict) and int(x.get("ts", _now())) >= cutoff
                ][-20:]
        data["source_logs"] = new_logs

    # تنظيف IDs آخر الأخبار للمصادر إذا خزنّت بصيغة حديثة مع تاريخ.
    # القيم القديمة الرقمية تُترك كما هي للتوافق حتى يتم تحديثها تلقائياً عند أول فحص.
    last_ids = data.get("last_source_messages", {})
    if isinstance(last_ids, dict):
        cleaned_last = {}
        for sid, value in last_ids.items():
            if isinstance(value, dict):
                try:
                    if int(value.get("ts", _now())) >= cutoff:
                        cleaned_last[str(sid)] = value
                except Exception:
                    pass
            else:
                cleaned_last[str(sid)] = value
        data["last_source_messages"] = cleaned_last

    last_errors = data.get("last_errors", [])
    if isinstance(last_errors, list):
        data["last_errors"] = [
            x for x in last_errors
            if isinstance(x, dict) and int(x.get("ts", _now())) >= cutoff
        ][-50:]

    # تنظيف حجوزات منع التكرار القديمة حتى لا يكبر الملف.
    claims = data.get("source_event_claims", {})
    if isinstance(claims, dict):
        new_claims = {}
        for sid, entries in claims.items():
            if isinstance(entries, list):
                fresh = [
                    x for x in entries
                    if isinstance(x, dict) and int(x.get("ts", _now())) >= cutoff
                ]
                if fresh:
                    new_claims[str(sid)] = fresh[-1000:]
        data["source_event_claims"] = new_claims


    # تنظيف سجل الرسائل المنشورة القديمة حتى لا يكبر الملف.
    published = data.get("published_messages", {})
    if isinstance(published, dict):
        new_published = {}
        for cid, by_type in published.items():
            if not isinstance(by_type, dict):
                continue
            new_by_type = {}
            for kind, entries in by_type.items():
                if isinstance(entries, list):
                    new_by_type[kind] = [
                        x for x in entries
                        if isinstance(x, dict) and int(x.get("ts", _now())) >= cutoff
                    ][-1000:]
            new_published[str(cid)] = new_by_type
        data["published_messages"] = new_published

    if own_write:
        _write(data)
    return _normalize_data(data)

def get_source_remove_terms(source_id):
    sid = str(source_id)
    with lock:
        data = _read()
    meta = data.get("source_meta", {}).get(sid, _normalize_source_meta(source_id))
    terms = meta.get("remove_terms", [])
    if not isinstance(terms, list):
        return []
    return [str(x).strip() for x in terms if str(x).strip()]


def add_source_remove_terms(source_id, terms):
    sid = str(source_id)
    clean_terms = []
    for term in terms or []:
        term = str(term).strip()
        if term:
            clean_terms.append(term)

    if not clean_terms:
        return {"added": 0, "exists": 0}

    with lock:
        data = _read()
        meta = _normalize_source_meta(source_id, data.setdefault("source_meta", {}).get(sid, {}))
        existing = [str(x).strip() for x in meta.get("remove_terms", []) if str(x).strip()]
        existing_keys = {x.lower() for x in existing}

        added = 0
        exists = 0
        for term in clean_terms:
            key = term.lower()
            if key in existing_keys:
                exists += 1
                continue
            existing.append(term)
            existing_keys.add(key)
            added += 1

        meta["remove_terms"] = existing
        data["source_meta"][sid] = meta
        _write(data)
        if added:
            _write_backup(data)
    return {"added": added, "exists": exists}


def remove_source_remove_terms(source_id, terms):
    sid = str(source_id)
    remove_keys = {str(x).strip().lower() for x in terms or [] if str(x).strip()}
    if not remove_keys:
        return {"removed": 0, "missing": 0}

    with lock:
        data = _read()
        meta = _normalize_source_meta(source_id, data.setdefault("source_meta", {}).get(sid, {}))
        existing = [str(x).strip() for x in meta.get("remove_terms", []) if str(x).strip()]
        before = len(existing)
        existing = [x for x in existing if x.lower() not in remove_keys]
        removed = before - len(existing)
        meta["remove_terms"] = existing
        data["source_meta"][sid] = meta
        _write(data)
        if removed:
            _write_backup(data)
    return {"removed": removed, "missing": max(0, len(remove_keys) - removed)}


def remove_source_remove_term(source_id, term_or_index):
    terms = get_source_remove_terms(source_id)
    try:
        idx = int(term_or_index)
        if 0 <= idx < len(terms):
            return bool(remove_source_remove_terms(source_id, [terms[idx]]).get("removed"))
    except Exception:
        pass
    return bool(remove_source_remove_terms(source_id, [term_or_index]).get("removed"))


# ===== Phase 3 Part 1: source filters, global cleanup, smart dedupe =====
def get_global_remove_terms():
    with lock:
        data = _read()
    terms = data.get("global_remove_terms", [])
    if not isinstance(terms, list):
        return []
    return [str(x).strip() for x in terms if str(x).strip()]


def add_global_remove_terms(terms):
    clean_terms = []
    for term in terms or []:
        term = str(term).strip()
        if term:
            clean_terms.append(term)

    if not clean_terms:
        return {"added": 0, "exists": 0}

    with lock:
        data = _read()
        existing = [str(x).strip() for x in data.get("global_remove_terms", []) if str(x).strip()]
        existing_keys = {x.lower() for x in existing}
        added = 0
        exists = 0
        for term in clean_terms:
            key = term.lower()
            if key in existing_keys:
                exists += 1
                continue
            existing.append(term)
            existing_keys.add(key)
            added += 1
        data["global_remove_terms"] = existing
        _write(data)
        if added:
            _write_backup(data)
    return {"added": added, "exists": exists}


def remove_global_remove_terms(terms):
    remove_keys = {str(x).strip().lower() for x in terms or [] if str(x).strip()}
    if not remove_keys:
        return {"removed": 0, "missing": 0}

    with lock:
        data = _read()
        existing = [str(x).strip() for x in data.get("global_remove_terms", []) if str(x).strip()]
        before = len(existing)
        existing = [x for x in existing if x.lower() not in remove_keys]
        removed = before - len(existing)
        data["global_remove_terms"] = existing
        _write(data)
        if removed:
            _write_backup(data)
    return {"removed": removed, "missing": max(0, len(remove_keys) - removed)}


def set_source_paused(source_id, paused=True):
    return update_source_meta(source_id, paused=bool(paused))


def is_source_paused(source_id):
    sid = str(source_id)
    with lock:
        data = _read()
    meta = data.get("source_meta", {}).get(sid, _normalize_source_meta(source_id))
    return bool(meta.get("paused", False))


def set_source_remove_emoji(source_id, enabled=True):
    return update_source_meta(source_id, remove_emoji=bool(enabled))


def get_source_remove_emoji(source_id):
    sid = str(source_id)
    with lock:
        data = _read()
    meta = data.get("source_meta", {}).get(sid, _normalize_source_meta(source_id))
    return bool(meta.get("remove_emoji", False))


def get_source_content_types(source_id):
    sid = str(source_id)
    with lock:
        data = _read()
    meta = data.get("source_meta", {}).get(sid, _normalize_source_meta(source_id))
    default_types = {"text": True, "photo": True, "video": True, "album": True, "voice": False, "audio": False, "document": False}
    types = meta.get("content_types", {})
    if not isinstance(types, dict):
        types = {}
    return {k: bool(types.get(k, v)) for k, v in default_types.items()}


def set_source_content_type(source_id, content_type, enabled=True):
    if content_type not in {"text", "photo", "video", "album", "voice", "audio", "document"}:
        return False
    sid = str(source_id)
    default_types = {"text": True, "photo": True, "video": True, "album": True, "voice": False, "audio": False, "document": False}
    with lock:
        data = _read()
        meta = _normalize_source_meta(source_id, data.setdefault("source_meta", {}).get(sid, {}))
        current = meta.get("content_types", {})
        if not isinstance(current, dict):
            current = {}
        types = {k: bool(current.get(k, v)) for k, v in default_types.items()}
        types[content_type] = bool(enabled)
        # منع إطفاء كل الأنواع حتى لا يصبح المصدر شغال بلا أي محتوى
        if not any(types.values()):
            return False
        meta["content_types"] = types
        data["source_meta"][sid] = meta
        _write(data)
        _write_backup(data)
        return True


def set_source_content_types(source_id, content_types):
    allowed = {"text", "photo", "video", "album", "voice", "audio", "document"}
    values = {k: bool(content_types.get(k, False)) for k in allowed}
    if not any(values.values()):
        return False
    return update_source_meta(source_id, content_types=values)


DEDUP_WINDOW_SECONDS = 2 * 86400  # نافذة مقارنة 48 ساعة


def get_recent_fingerprints(scope_id=None):
    """بصمات الأخبار المقبولة والمنشورة فعلياً خلال آخر 48 ساعة.
    إذا تم تمرير scope_id تُرجع بصمات هذا القسم فقط (Dedup مشترك حسب القسم)."""
    cutoff = _now() - DEDUP_WINDOW_SECONDS
    with lock:
        data = _read()
        items = data.get("recent_fingerprints", [])
        if not isinstance(items, list):
            return []
        fresh = [x for x in items if isinstance(x, dict) and x.get("fp") and int(x.get("ts", _now())) >= cutoff]
        if scope_id is not None:
            fresh = [x for x in fresh if str(x.get("scope_id", "") or "") == str(scope_id)]
        if len(fresh) != len(items):
            data["recent_fingerprints"] = fresh[-500:]
            _write(data)
        return fresh[-500:]

def add_recent_fingerprint(fp, sample="", limit=500, source_id=None, message_id=None, event_fp=None, url_fp=None, scope_id=None, section_label=None):
    fp = str(fp or "").strip()
    if not fp:
        return False
    cutoff = _now() - DEDUP_WINDOW_SECONDS
    with lock:
        data = _read()
        items = data.get("recent_fingerprints", [])
        if not isinstance(items, list):
            items = []
        items = [x for x in items if isinstance(x, dict) and x.get("fp") != fp and int(x.get("ts", _now())) >= cutoff]
        items.append({
            "fp": fp,
            "sample": str(sample or "")[:500],
            "ts": _now(),
            "source_id": str(source_id) if source_id is not None else None,
            "message_id": message_id,
            "event_fp": str(event_fp or ""),
            "url_fp": str(url_fp or ""),
            "scope_id": str(scope_id or ""),
            "section_label": str(section_label or ""),
        })
        if len(items) > int(limit):
            items = items[-int(limit):]
        data["recent_fingerprints"] = items
        _write(data)
        return True

def _get_scope_claims(data):
    """مطالبات الأحداث على مستوى القسم (scope_id:event_fp) — Dedup مشترك بين المصادر."""
    return data.setdefault("section_event_claims", {})

def claim_section_event(scope_id, event_fp):
    """حجز ذري دائم للحدث على مستوى القسم: scope_id + fingerprint الحدث.
    يستخدم من مساري updates وpolling ومن مصادر مختلفة داخل نفس القسم.
    داخل قفل قاعدة البيانات فلا يوجد سباق TOCTOU.
    يرجع True إذا فاز هذا الاستدعاء بالحجز (الخبر جديد لهذا القسم)، False إذا سبق حجزه."""
    sid = str(scope_id or "")
    fp = str(event_fp or "").strip()
    if not sid or not fp:
        return False
    with lock:
        data = _read()
        claims = _get_scope_claims(data)
        per_scope = claims.setdefault(sid, [])
        if any(isinstance(x, dict) and str(x.get("event_fp", "")) == fp for x in per_scope):
            return False
        per_scope.append({"event_fp": fp, "ts": _now()})
        cutoff = _now() - DEDUP_WINDOW_SECONDS
        claims[sid] = [x for x in per_scope if int(x.get("ts", _now())) >= cutoff][-2000:]
        _write(data)
        return True

def is_section_event_claimed(scope_id, event_fp):
    """قراءة فقط: هل سبق حجز هذا الحدث لهذا القسم؟"""
    sid = str(scope_id or "")
    fp = str(event_fp or "").strip()
    if not sid or not fp:
        return False
    with lock:
        data = _read()
    per_scope = data.get("section_event_claims", {}).get(sid, [])
    return any(isinstance(x, dict) and str(x.get("event_fp", "")) == fp for x in per_scope)

def set_channel_publish_delay(channel_id, delay_seconds):
    try:
        if delay_seconds is None or str(delay_seconds).strip() == "":
            value = None
        else:
            value = max(0.0, float(delay_seconds))
    except Exception:
        return False
    return update_channel(channel_id, "publish_delay", value)


def get_channel_publish_delay(channel_id, default=0.5):
    ch = get_channel(channel_id)
    if not ch:
        return float(default)
    value = ch.get("publish_delay", None)
    if value is None or value == "":
        return float(default)
    try:
        return max(0.0, float(value))
    except Exception:
        return float(default)



def set_channel_bold_publish(channel_id, enabled=True):
    return update_channel(channel_id, "bold_publish", bool(enabled))


def get_channel_bold_publish(channel_id, default=True):
    ch = get_channel(channel_id)
    if not ch:
        return bool(default)
    return bool(ch.get("bold_publish", default))

def record_source_event(source_id, event_type, reason="", message_id=None, target_count=0):
    sid = str(source_id)
    with lock:
        data = _read()
        stats = data.setdefault("source_stats", {}).setdefault(sid, {
            "received": 0, "published": 0, "rejected": 0, "ignored": 0,
            "duplicates": 0, "errors": 0, "last_message_id": None,
            "last_event": "", "last_reason": "", "last_ts": None
        })
        event_type = str(event_type or "").lower()
        if event_type == "received":
            stats["received"] = int(stats.get("received", 0)) + 1
        elif event_type == "published":
            stats["published"] = int(stats.get("published", 0)) + 1
        elif event_type == "rejected":
            stats["rejected"] = int(stats.get("rejected", 0)) + 1
        elif event_type == "duplicate":
            stats["duplicates"] = int(stats.get("duplicates", 0)) + 1
            stats["ignored"] = int(stats.get("ignored", 0)) + 1
        elif event_type == "error":
            stats["errors"] = int(stats.get("errors", 0)) + 1
        else:
            stats["ignored"] = int(stats.get("ignored", 0)) + 1
        stats["last_message_id"] = message_id
        stats["last_event"] = event_type
        stats["last_reason"] = str(reason or "")[:300]
        stats["last_ts"] = _now()
        data["source_stats"][sid] = stats

        logs = data.setdefault("source_logs", {}).setdefault(sid, [])
        logs.append({
            "ts": _now(), "event": event_type, "reason": str(reason or "")[:300],
            "message_id": message_id, "target_count": int(target_count or 0)
        })
        data["source_logs"][sid] = logs[-20:]
        _write(data)
        return True


def get_source_stats(source_id):
    sid = str(source_id)
    with lock:
        data = _read()
    return data.get("source_stats", {}).get(sid, {
        "received": 0, "published": 0, "rejected": 0, "ignored": 0,
        "duplicates": 0, "errors": 0, "last_message_id": None,
        "last_event": "", "last_reason": "", "last_ts": None
    })


def get_source_logs(source_id, limit=20):
    sid = str(source_id)
    with lock:
        data = _read()
    logs = data.get("source_logs", {}).get(sid, [])
    if not isinstance(logs, list):
        return []
    return logs[-int(limit):]


def has_recent_source_event(source_id, message_id):
    if source_id is None or message_id is None:
        return False
    target_id = str(message_id)
    return any(str(item.get("message_id")) == target_id for item in get_source_logs(source_id, limit=20) if isinstance(item, dict))


def copy_source_settings(from_source_id, to_source_ids):
    from_sid = str(from_source_id)
    copied = 0
    with lock:
        data = _read()
        source_meta = _normalize_source_meta(from_source_id, data.setdefault("source_meta", {}).get(from_sid, {}))
        keys = ["remove_terms", "remove_emoji", "content_types", "paused"]
        for dst in to_source_ids or []:
            sid = str(dst)
            meta = _normalize_source_meta(dst, data.setdefault("source_meta", {}).get(sid, {}))
            for key in keys:
                if key in source_meta:
                    # copy JSON-compatible value
                    meta[key] = json.loads(json.dumps(source_meta[key], ensure_ascii=False))
            data["source_meta"][sid] = meta
            copied += 1
        _write(data)
        if copied:
            _write_backup(data)
    return copied


def set_system_value(key, value):
    with lock:
        data = _read()
        data.setdefault("system", {})[str(key)] = value
        _write(data)
        return True


def get_system_value(key, default=None):
    with lock:
        data = _read()
    return data.get("system", {}).get(str(key), default)


# ===== Professional safety/ops additions =====
def is_maintenance_mode():
    with lock:
        data = _read()
    return bool(data.get("system", {}).get("maintenance_mode", False))


def set_maintenance_mode(enabled):
    with lock:
        data = _read()
        data.setdefault("system", {})["maintenance_mode"] = bool(enabled)
        data["system"]["maintenance_updated_at"] = _now()
        _write(data)
        return True


def add_last_error(context, error):
    with lock:
        data = _read()
        errors = data.setdefault("last_errors", [])
        if not isinstance(errors, list):
            errors = []
        errors.append({
            "ts": _now(),
            "context": str(context or "")[:120],
            "error": str(error or "")[:500],
        })
        data["last_errors"] = errors[-20:]
        data.setdefault("system", {})["last_error"] = f"{context}: {error}"[:600]
        data["system"]["last_error_ts"] = _now()
        _write(data)
        return True


def get_last_errors(limit=20):
    with lock:
        data = _read()
    errors = data.get("last_errors", [])
    if not isinstance(errors, list):
        return []
    return errors[-int(limit):]


def clear_last_errors():
    with lock:
        data = _read()
        data["last_errors"] = []
        data.setdefault("system", {})["last_error"] = ""
        _write(data)
        return True


def _normalize_quote_types(value=None, fallback=False):
    if not isinstance(value, dict):
        value = {}
    return {
        "text": bool(value.get("text", fallback)),
        "photo": bool(value.get("photo", fallback)),
        "video": bool(value.get("video", fallback)),
        "album": bool(value.get("album", fallback)),
    }


def set_channel_quote_publish(channel_id, enabled=True):
    # المفتاح القديم: يبدّل كل الأنواع مرة واحدة للتوافق فقط.
    cid = str(channel_id)
    enabled = bool(enabled)
    with lock:
        data = _read()
        if cid not in data.get("channels", {}):
            return False
        data["channels"][cid]["quote_types"] = _normalize_quote_types({}, enabled)
        data["channels"][cid]["quote_publish"] = enabled
        _write(data)
        _write_backup(data)
        return True


def get_channel_quote_publish(channel_id, default=False):
    ch = get_channel(channel_id)
    if not ch:
        return bool(default)
    qt = _normalize_quote_types(ch.get("quote_types"), ch.get("quote_publish", default))
    return any(qt.values())


def get_channel_quote_types(channel_id):
    ch = get_channel(channel_id)
    if not ch:
        return _normalize_quote_types({}, False)
    return _normalize_quote_types(ch.get("quote_types"), ch.get("quote_publish", False))


def get_channel_quote_type(channel_id, content_type="text", default=False):
    ctype = str(content_type or "text")
    if ctype not in {"text", "photo", "video", "album"}:
        ctype = "text"
    return bool(get_channel_quote_types(channel_id).get(ctype, default))


def set_channel_quote_type(channel_id, content_type, enabled=True):
    cid = str(channel_id)
    ctype = str(content_type or "text")
    if ctype not in {"text", "photo", "video", "album"}:
        return False
    with lock:
        data = _read()
        if cid not in data.get("channels", {}):
            return False
        ch = data["channels"][cid]
        qt = _normalize_quote_types(ch.get("quote_types"), ch.get("quote_publish", False))
        qt[ctype] = bool(enabled)
        ch["quote_types"] = qt
        ch["quote_publish"] = any(qt.values())
        _write(data)
        _write_backup(data)
        return True


def get_channel_hashtags(channel_id):
    ch = get_channel(channel_id)
    if not ch:
        return []
    tags = ch.get("hashtags", [])
    if not isinstance(tags, list):
        return []
    out = []
    seen = set()
    for tag in tags:
        tag = str(tag).strip()
        if not tag:
            continue
        if not tag.startswith("#"):
            tag = "#" + tag.lstrip("#")
        key = tag.lower()
        if key not in seen:
            seen.add(key)
            out.append(tag)
    return out


def add_channel_hashtags(channel_id, tags):
    clean = []
    for tag in tags or []:
        tag = str(tag).strip()
        if not tag:
            continue
        if not tag.startswith("#"):
            tag = "#" + tag.lstrip("#")
        clean.append(tag)
    if not clean:
        return {"added": 0, "exists": 0}
    cid = str(channel_id)
    with lock:
        data = _read()
        if cid not in data["channels"]:
            return {"added": 0, "exists": 0}
        existing = []
        for tag in data["channels"][cid].get("hashtags", []):
            tag = str(tag).strip()
            if tag:
                existing.append(tag if tag.startswith("#") else "#" + tag.lstrip("#"))
        keys = {x.lower() for x in existing}
        added = 0
        exists = 0
        for tag in clean:
            key = tag.lower()
            if key in keys:
                exists += 1
                continue
            existing.append(tag)
            keys.add(key)
            added += 1
        data["channels"][cid]["hashtags"] = existing
        _write(data)
        if added:
            _write_backup(data)
        return {"added": added, "exists": exists}


def remove_channel_hashtags(channel_id, tags):
    remove_keys = set()
    for tag in tags or []:
        tag = str(tag).strip()
        if not tag:
            continue
        if not tag.startswith("#"):
            tag = "#" + tag.lstrip("#")
        remove_keys.add(tag.lower())
    if not remove_keys:
        return {"removed": 0, "missing": 0}
    cid = str(channel_id)
    with lock:
        data = _read()
        if cid not in data["channels"]:
            return {"removed": 0, "missing": len(remove_keys)}
        existing = []
        for tag in data["channels"][cid].get("hashtags", []):
            tag = str(tag).strip()
            if tag:
                existing.append(tag if tag.startswith("#") else "#" + tag.lstrip("#"))
        before = len(existing)
        existing = [x for x in existing if x.lower() not in remove_keys]
        removed = before - len(existing)
        data["channels"][cid]["hashtags"] = existing
        _write(data)
        if removed:
            _write_backup(data)
        return {"removed": removed, "missing": max(0, len(remove_keys)-removed)}


def record_channel_publish_success(channel_id):
    cid = str(channel_id)
    with lock:
        data = _read()
        if cid in data.get("channels", {}):
            data["channels"][cid]["fail_count"] = 0
        data.setdefault("channel_failures", {})[cid] = 0
        _write(data)
        return True


def record_channel_publish_failure(channel_id, error="", limit=5):
    cid = str(channel_id)
    with lock:
        data = _read()
        failures = data.setdefault("channel_failures", {})
        count = int(failures.get(cid, 0) or 0) + 1
        failures[cid] = count
        if cid in data.get("channels", {}):
            data["channels"][cid]["fail_count"] = count
            if count >= int(limit):
                data["channels"][cid]["paused"] = True
                data["channels"][cid]["auto_paused_reason"] = str(error or "")[:300]
                data["channels"][cid]["auto_paused_at"] = _now()
        errors = data.setdefault("last_errors", [])
        errors.append({"ts": _now(), "context": f"publish channel {cid}", "error": str(error or "")[:500]})
        data["last_errors"] = errors[-20:]
        _write(data)
        return count


def create_named_backup(name):
    name = str(name or "").strip()
    if not name:
        name = f"backup_{_now()}"
    safe = "".join(ch for ch in name if ch.isalnum() or ch in ("_", "-", ".", " ")).strip().replace(" ", "_")
    if not safe:
        safe = f"backup_{_now()}"
    with lock:
        data = _read()
        os.makedirs(BACKUP_DIR, exist_ok=True)
        path = os.path.join(BACKUP_DIR, f"manual_{safe}_{_now()}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(_normalize_data(data), f, ensure_ascii=False, indent=2)
        named = data.setdefault("named_backups", [])
        named.append({"name": name, "file": path, "ts": _now()})
        data["named_backups"] = named[-30:]
        _write(data)
        return path


def get_named_backups():
    with lock:
        data = _read()
    items = data.get("named_backups", [])
    return items if isinstance(items, list) else []


# ===== Published message tracking for channel cleanup =====
def record_published_message(channel_id, message_id, content_type):
    """يحفظ ID الرسالة التي نشرها البوت حتى يمكن حذفها لاحقاً حسب النوع."""
    if not message_id:
        return False
    cid = str(channel_id)
    ctype = str(content_type or "text")
    if ctype not in {"text", "photo", "video", "album"}:
        ctype = "photo"
    with lock:
        data = _read()
        box = data.setdefault("published_messages", {}).setdefault(cid, {}).setdefault(ctype, [])
        mid = int(message_id)
        if not any(isinstance(x, dict) and int(x.get("id", -1)) == mid for x in box):
            box.append({"id": mid, "ts": _now()})
        data["published_messages"][cid][ctype] = box[-1000:]
        _write(data)
        return True


def record_published_messages(channel_id, message_ids, content_type):
    count = 0
    for mid in message_ids or []:
        if record_published_message(channel_id, mid, content_type):
            count += 1
    return count


def get_published_message_ids(channel_id, content_type):
    cid = str(channel_id)
    ctype = str(content_type or "")
    with lock:
        data = _read()
    entries = data.get("published_messages", {}).get(cid, {}).get(ctype, [])
    ids = []
    for item in entries:
        try:
            ids.append(int(item.get("id") if isinstance(item, dict) else item))
        except Exception:
            pass
    return ids


def clear_published_message_ids(channel_id, content_type, message_ids=None):
    cid = str(channel_id)
    ctype = str(content_type or "")
    remove_set = None
    if message_ids is not None:
        remove_set = {int(x) for x in message_ids if str(x).lstrip("-").isdigit()}
    with lock:
        data = _read()
        entries = data.setdefault("published_messages", {}).setdefault(cid, {}).setdefault(ctype, [])
        if remove_set is None:
            removed = len(entries)
            data["published_messages"][cid][ctype] = []
        else:
            before = len(entries)
            data["published_messages"][cid][ctype] = [
                x for x in entries
                if int(x.get("id") if isinstance(x, dict) else x) not in remove_set
            ]
            removed = before - len(data["published_messages"][cid][ctype])
        _write(data)
        return removed


def get_ignore_short_posts():
    with lock:
        data = _read()
    return bool(data.get("settings", {}).get("ignore_short_posts", False))


def set_ignore_short_posts(enabled):
    with lock:
        data = _read()
        data.setdefault("settings", {})["ignore_short_posts"] = bool(enabled)
        _write(data)
        _write_backup(data)
        return True


def get_channel_ignore_short_posts(channel_id, default=None):
    """Return the channel-local short-post flag with legacy fallback."""
    ch = get_channel(channel_id)
    if not ch:
        return bool(get_ignore_short_posts() if default is None else default)
    value = ch.get("ignore_short_posts")
    if value is None:
        return bool(get_ignore_short_posts() if default is None else default)
    return bool(value)


def set_channel_ignore_short_posts(channel_id, enabled):
    """Persist the short-post flag for one channel only."""
    return update_channel(channel_id, "ignore_short_posts", bool(enabled))


# ============================================================
# Link Preview: per-channel disable
# ============================================================

def get_channel_disable_preview(channel_id, default=False):
    ch = get_channel(channel_id)
    if not ch:
        return bool(default)
    return bool(ch.get("disable_web_page_preview", default))


def set_channel_disable_preview(channel_id, enabled):
    return update_channel(channel_id, "disable_web_page_preview", bool(enabled))


def get_channel_tail_enabled(channel_id):
    ch = get_channel(str(channel_id))
    return bool(ch.get("tail_enabled", True)) if ch else True


def set_channel_tail_enabled(channel_id, enabled):
    return update_channel(str(channel_id), "tail_enabled", bool(enabled))


def get_channel_tail_min_words(channel_id):
    ch = get_channel(str(channel_id))
    return int(ch.get("tail_min_words", 20)) if ch else 20


def set_channel_tail_min_words(channel_id, count):
    return update_channel(str(channel_id), "tail_min_words", max(1, int(count)))


def get_channel_tail_position(channel_id):
    ch = get_channel(str(channel_id))
    val = ch.get("tail_position", "bottom") if ch else "bottom"
    return val if val in ("top", "bottom") else "bottom"


def set_channel_tail_position(channel_id, position):
    position = position if position in ("top", "bottom") else "bottom"
    return update_channel(str(channel_id), "tail_position", position)


def get_settings_clipboard():
    with lock:
        data = _read()
    return data.get("settings_clipboard")


def set_settings_clipboard(clipboard_data):
    with lock:
        data = _read()
        data["settings_clipboard"] = clipboard_data
        _write(data)


# ============================================================
# Notification Center Settings
# ============================================================

NOTIFICATION_TYPES = {
    "session_stopped": "توقف Session",
    "ai_key_error": "خطأ في مفتاح AI",
    "source_stopped": "توقف مصدر",
    "channel_idle_hour": "قناة لم تنشر منذ ساعة",
    "backup_failed": "فشل Backup",
    "db_issue": "مشكلة بقاعدة البيانات",
}


def get_notification_settings():
    with lock:
        data = _read()
    ns = data.get("notification_settings", {})
    return {k: bool(ns.get(k, True)) for k in NOTIFICATION_TYPES}


def set_notification_setting(key, enabled):
    if key not in NOTIFICATION_TYPES:
        return False
    with lock:
        data = _read()
        ns = data.setdefault("notification_settings", {})
        ns[str(key)] = bool(enabled)
        _write(data)
    return True


def get_notification_last_alert(key):
    with lock:
        data = _read()
    ns = data.get("notification_settings", {})
    return ns.get("last_alert_ts", {}).get(str(key), 0)


def set_notification_last_alert(key, ts=None):
    if ts is None:
        ts = _now()
    with lock:
        data = _read()
        ns = data.setdefault("notification_settings", {})
        alerts = ns.setdefault("last_alert_ts", {})
        alerts[str(key)] = int(ts)
        _write(data)
    return True


# ============================================================
# Multi-Bot Expansion: Sessions
# ============================================================

def _normalize_session(sid, value):
    if not isinstance(value, dict):
        value = {}
    sid = str(sid)
    value.setdefault("id", sid)
    value.setdefault("name", value.get("name") or f"Session {sid.split('_')[-1]}")
    value.setdefault("api_id", 0)
    value.setdefault("api_hash", "")
    value.setdefault("session_string", "")
    value.setdefault("enabled", True)
    value.setdefault("created_at", _now())
    value.setdefault("last_used", None)
    value.setdefault("usage_count", 0)
    value.setdefault("error_count", 0)
    value.setdefault("status", "idle")
    value.setdefault("channels_using", [])
    return value


def get_all_sessions():
    with lock:
        data = _read()
    return [{"id": k, **v} for k, v in data.get("sessions", {}).items()]


def get_session(session_id):
    sid = str(session_id)
    with lock:
        data = _read()
    raw = data.get("sessions", {}).get(sid)
    if raw is None:
        return None
    return {"id": sid, **raw}


def add_session(api_id, api_hash, session_string, name=None):
    items = get_all_sessions()
    n = _find_available_number([s.get("name", "") for s in items], "Session")
    final_name = name or f"Session {n}"
    sid = f"session_{n}"
    with lock:
        data = _read()
        if sid in data.get("sessions", {}):
            return False
        entry = _normalize_session(sid, {
            "id": sid, "name": final_name,
            "api_id": int(api_id), "api_hash": str(api_hash),
            "session_string": str(session_string),
            "enabled": True, "created_at": _now(),
        })
        data.setdefault("sessions", {})[sid] = entry
        _write(data)
        _write_backup(data)
    return True


def update_session(session_id, **kwargs):
    sid = str(session_id)
    allowed = {"name", "api_id", "api_hash", "session_string", "enabled", "status"}
    with lock:
        data = _read()
        entry = data.get("sessions", {}).get(sid)
        if not entry:
            return False
        for k, v in kwargs.items():
            if k in allowed and v is not None:
                entry[k] = v
        _write(data)
    return True


def delete_session(session_id):
    sid = str(session_id)
    with lock:
        data = _read()
        entry = data.get("sessions", {}).pop(sid, None)
        if entry is None:
            return False
        item = {"id": f"trash_session_{_now()}", "type": "session", "original_id": sid, "data": entry, "deleted_at": _now()}
        data.setdefault("trash", []).append(item)
        _write(data)
        _write_backup(data)
    return True


def set_session_enabled(session_id, enabled):
    return update_session(session_id, enabled=bool(enabled))


def record_session_usage(session_id):
    sid = str(session_id)
    with lock:
        data = _read()
        entry = data.get("sessions", {}).get(sid)
        if not entry:
            return False
        entry["last_used"] = _now()
        entry["usage_count"] = int(entry.get("usage_count", 0)) + 1
        _write(data)
    return True


def get_session_stats(session_id):
    s = get_session(session_id)
    if not s:
        return {}
    return {
        "usage_count": s.get("usage_count", 0),
        "error_count": s.get("error_count", 0),
        "last_used": s.get("last_used"),
        "status": s.get("status", "idle"),
        "enabled": s.get("enabled", True),
        "name": s.get("name", ""),
    }


# ============================================================
# Multi-Bot Expansion: AI Keys
# ============================================================

def _normalize_ai_key(kid, value):
    if not isinstance(value, dict):
        value = {}
    kid = str(kid)
    value.setdefault("id", kid)
    value.setdefault("name", value.get("name") or f"AI {kid.split('_')[-1]}")
    value.setdefault("provider", "gemini")
    value.setdefault("api_key", "")
    value.setdefault("enabled", True)
    value.setdefault("created_at", _now())
    value.setdefault("last_used", None)
    value.setdefault("usage_count", 0)
    value.setdefault("error_count", 0)
    value.setdefault("channels_using", [])
    value.setdefault("models", ["gemini-pro"])
    return value


def get_all_ai_keys():
    with lock:
        data = _read()
    return [{"id": k, **v} for k, v in data.get("ai_keys", {}).items()]


def get_ai_key(key_id):
    kid = str(key_id)
    with lock:
        data = _read()
    raw = data.get("ai_keys", {}).get(kid)
    return {"id": kid, **raw} if raw else None


def add_ai_key(provider, api_key, name=None):
    items = get_all_ai_keys()
    n = _find_available_number([k.get("name", "") for k in items], "AI")
    final_name = name or f"AI {n}"
    kid = f"ai_{n}"
    with lock:
        data = _read()
        if kid in data.get("ai_keys", {}):
            return False
        entry = _normalize_ai_key(kid, {
            "id": kid, "name": final_name,
            "provider": str(provider), "api_key": str(api_key),
            "enabled": True, "created_at": _now(),
        })
        data.setdefault("ai_keys", {})[kid] = entry
        _write(data)
        _write_backup(data)
    return True


def update_ai_key(key_id, **kwargs):
    kid = str(key_id)
    allowed = {"name", "provider", "api_key", "enabled", "models"}
    with lock:
        data = _read()
        entry = data.get("ai_keys", {}).get(kid)
        if not entry:
            return False
        for k, v in kwargs.items():
            if k in allowed and v is not None:
                entry[k] = v
        _write(data)
    return True


def delete_ai_key(key_id):
    kid = str(key_id)
    with lock:
        data = _read()
        entry = data.get("ai_keys", {}).pop(kid, None)
        if entry is None:
            return False
        item = {"id": f"trash_ai_{_now()}", "type": "ai_key", "original_id": kid, "data": entry, "deleted_at": _now()}
        data.setdefault("trash", []).append(item)
        _write(data)
        _write_backup(data)
    return True


def set_ai_key_enabled(key_id, enabled):
    return update_ai_key(key_id, enabled=bool(enabled))


def record_ai_key_usage(key_id):
    kid = str(key_id)
    with lock:
        data = _read()
        entry = data.get("ai_keys", {}).get(kid)
        if not entry:
            return False
        entry["last_used"] = _now()
        entry["usage_count"] = int(entry.get("usage_count", 0)) + 1
        _write(data)
    return True


def get_ai_key_stats(key_id):
    k = get_ai_key(key_id)
    if not k:
        return {}
    return {
        "provider": k.get("provider", ""),
        "usage_count": k.get("usage_count", 0),
        "error_count": k.get("error_count", 0),
        "last_used": k.get("last_used"),
        "enabled": k.get("enabled", True),
        "name": k.get("name", ""),
    }


# ============================================================
# Multi-Bot Expansion: Publishing Bots
# ============================================================

def _normalize_publishing_bot(bid, value):
    if not isinstance(value, dict):
        value = {}
    bid = str(bid)
    value.setdefault("id", bid)
    value.setdefault("name", value.get("name") or f"Bot {bid.split('_')[-1]}")
    value.setdefault("token", "")
    value.setdefault("username", "")
    value.setdefault("enabled", True)
    value.setdefault("created_at", _now())
    value.setdefault("last_publish", None)
    value.setdefault("publish_count", 0)
    value.setdefault("error_count", 0)
    value.setdefault("channels_using", [])
    return value


def get_all_publishing_bots():
    with lock:
        data = _read()
    return [{"id": k, **v} for k, v in data.get("publishing_bots", {}).items()]


def get_publishing_bot(bot_id):
    bid = str(bot_id)
    with lock:
        data = _read()
    raw = data.get("publishing_bots", {}).get(bid)
    return {"id": bid, **raw} if raw else None


def add_publishing_bot(token, username="", name=None):
    items = get_all_publishing_bots()
    n = _find_available_number([b.get("name", "") for b in items], "Bot")
    final_name = name or f"Bot {n}"
    bid = f"bot_{n}"
    with lock:
        data = _read()
        if bid in data.get("publishing_bots", {}):
            return False
        entry = _normalize_publishing_bot(bid, {
            "id": bid, "name": final_name,
            "token": str(token), "username": str(username),
            "enabled": True, "created_at": _now(),
        })
        data.setdefault("publishing_bots", {})[bid] = entry
        _write(data)
        _write_backup(data)
    return True


def update_publishing_bot(bot_id, **kwargs):
    bid = str(bot_id)
    allowed = {"name", "token", "username", "enabled"}
    with lock:
        data = _read()
        entry = data.get("publishing_bots", {}).get(bid)
        if not entry:
            return False
        for k, v in kwargs.items():
            if k in allowed and v is not None:
                entry[k] = v
        _write(data)
    return True


def delete_publishing_bot(bot_id):
    bid = str(bot_id)
    with lock:
        data = _read()
        entry = data.get("publishing_bots", {}).pop(bid, None)
        if entry is None:
            return False
        item = {"id": f"trash_bot_{_now()}", "type": "publishing_bot", "original_id": bid, "data": entry, "deleted_at": _now()}
        data.setdefault("trash", []).append(item)
        _write(data)
        _write_backup(data)
    return True


def set_publishing_bot_enabled(bot_id, enabled):
    return update_publishing_bot(bot_id, enabled=bool(enabled))


def record_bot_publish(bot_id, content_type="text"):
    bid = str(bot_id)
    ctype = str(content_type or "text")
    if ctype not in ("text", "photo", "video", "album"):
        ctype = "text"
    with lock:
        data = _read()
        entry = data.get("publishing_bots", {}).get(bid)
        if not entry:
            return False
        entry["last_publish"] = _now()
        entry["publish_count"] = int(entry.get("publish_count", 0)) + 1
        stats = entry.setdefault("stats", {})
        stats[ctype] = int(stats.get(ctype, 0)) + 1
        _write(data)
    return True


# ============================================================
# Bot-Channel Verification
# ============================================================

def _normalize_verification(key, value):
    if not isinstance(value, dict):
        value = {}
    value.setdefault("verified", False)
    value.setdefault("can_post", False)
    value.setdefault("status", "")
    value.setdefault("permissions", {})
    value.setdefault("last_check", 0)
    value.setdefault("bot_name", "")
    value.setdefault("channel_name", "")
    return value


def set_bot_channel_verification(bot_id, channel_id, verified, can_post=False, status="", permissions=None, bot_name="", channel_name=""):
    """تخزين نتيجة التحقق من وجود بوت في قناة."""
    key = f"{bot_id}|{channel_id}"
    with lock:
        data = _read()
        mapping = data.setdefault("bot_channel_verified", {})
        entry = _normalize_verification(key, mapping.get(key, {}))
        entry["verified"] = bool(verified)
        entry["can_post"] = bool(can_post)
        entry["status"] = str(status)
        entry["permissions"] = dict(permissions or {})
        entry["last_check"] = _now()
        entry["bot_name"] = str(bot_name)
        entry["channel_name"] = str(channel_name)
        mapping[key] = entry
        _write(data)
    return True


def get_bot_channel_verification(bot_id, channel_id):
    """إرجاع حالة التحقق المخزنة لبوت في قناة."""
    key = f"{bot_id}|{channel_id}"
    with lock:
        data = _read()
    entry = data.get("bot_channel_verified", {}).get(key)
    return _normalize_verification(key, entry)


def get_all_bot_channel_verifications():
    """إرجاع كل حالات التحقق."""
    with lock:
        data = _read()
    return {k: _normalize_verification(k, v) for k, v in data.get("bot_channel_verified", {}).items()}


def get_verifications_for_bot(bot_id):
    """إرجاع كل التحققات لبوت معين."""
    result = {}
    prefix = f"{bot_id}|"
    for k, v in get_all_bot_channel_verifications().items():
        if k.startswith(prefix):
            ch_id = k[len(prefix):]
            result[ch_id] = v
    return result


def get_verifications_for_channel(channel_id):
    """إرجاع كل التحققات لقناة معينة."""
    result = {}
    suffix = f"|{channel_id}"
    for k, v in get_all_bot_channel_verifications().items():
        if k.endswith(suffix):
            bot_id = k[:-len(suffix)]
            result[bot_id] = v
    return result


# ============================================================
# Multi-Bot Expansion: Website Sources
# ============================================================

def _normalize_website(wid, value):
    if not isinstance(value, dict):
        value = {}
    wid = str(wid)
    value.setdefault("id", wid)
    value.setdefault("name", value.get("name") or f"Website {wid.split('_')[-1]}")
    value.setdefault("url", "")
    value.setdefault("enabled", True)
    value.setdefault("selector", "body")
    value.setdefault("interval", 300)
    value.setdefault("created_at", _now())
    value.setdefault("last_fetch", None)
    value.setdefault("error_count", 0)
    value.setdefault("channels_using", [])
    return value


def get_all_websites():
    with lock:
        data = _read()
    return [{"id": k, **v} for k, v in data.get("websites", {}).items()]


def get_website(website_id):
    wid = str(website_id)
    with lock:
        data = _read()
    raw = data.get("websites", {}).get(wid)
    return {"id": wid, **raw} if raw else None


def add_website(url, name=None, selector="body"):
    items = get_all_websites()
    n = _find_available_number([w.get("name", "") for w in items], "Website")
    final_name = name or f"Website {n}"
    wid = f"web_{n}"
    with lock:
        data = _read()
        if wid in data.get("websites", {}):
            return False
        entry = _normalize_website(wid, {
            "id": wid, "name": final_name,
            "url": str(url), "selector": str(selector),
            "enabled": True, "created_at": _now(),
        })
        data.setdefault("websites", {})[wid] = entry
        _write(data)
        _write_backup(data)
    return True


def update_website(website_id, **kwargs):
    wid = str(website_id)
    allowed = {"name", "url", "enabled", "selector", "interval"}
    with lock:
        data = _read()
        entry = data.get("websites", {}).get(wid)
        if not entry:
            return False
        for k, v in kwargs.items():
            if k in allowed and v is not None:
                entry[k] = v
        _write(data)
    return True


def delete_website(website_id):
    wid = str(website_id)
    with lock:
        data = _read()
        entry = data.get("websites", {}).pop(wid, None)
        if entry is None:
            return False
        item = {"id": f"trash_web_{_now()}", "type": "website", "original_id": wid, "data": entry, "deleted_at": _now()}
        data.setdefault("trash", []).append(item)
        _write(data)
        _write_backup(data)
    return True


def set_website_enabled(website_id, enabled):
    return update_website(website_id, enabled=bool(enabled))


# ============================================================
# Multi-Bot Expansion: Trash System
# ============================================================

def get_trash_items():
    with lock:
        data = _read()
    items = data.get("trash", [])
    return items if isinstance(items, list) else []


def restore_from_trash(trash_id):
    with lock:
        data = _read()
        items = data.get("trash", [])
        for idx, item in enumerate(items):
            if item.get("id") == trash_id:
                orig_type = item.get("type")
                orig_id = item.get("original_id")
                orig_data = item.get("data", {})
                if orig_type == "session":
                    data.setdefault("sessions", {})[orig_id] = orig_data
                elif orig_type == "ai_key":
                    data.setdefault("ai_keys", {})[orig_id] = orig_data
                elif orig_type == "publishing_bot":
                    data.setdefault("publishing_bots", {})[orig_id] = orig_data
                elif orig_type == "website":
                    data.setdefault("websites", {})[orig_id] = orig_data
                else:
                    return False
                items.pop(idx)
                data["trash"] = items
                _write(data)
                _write_backup(data)
                return True
    return False


def permanent_delete_from_trash(trash_id):
    with lock:
        data = _read()
        items = data.get("trash", [])
        for idx, item in enumerate(items):
            if item.get("id") == trash_id:
                items.pop(idx)
                data["trash"] = items
                _write(data)
                return True
    return False


def empty_trash():
    with lock:
        data = _read()
        data["trash"] = []
        _write(data)
    return True


# ============================================================
# Multi-Bot Expansion: Auto Naming
# ============================================================

def _find_available_number(names, prefix):
    used = set()
    for name in names:
        if name.startswith(prefix):
            try:
                num = int(name[len(prefix):].strip())
                used.add(num)
            except ValueError:
                pass
    n = 1
    while n in used:
        n += 1
    return n


# ============================================================
# Multi-Bot Expansion: Channel Config Extensions
# ============================================================

def _normalize_channel_config(cid, value):
    if not isinstance(value, dict):
        value = {}
    cid = str(cid)
    value.setdefault("title_quote", False)
    value.setdefault("signature_quote", False)
    value.setdefault("assigned_sessions", [])
    value.setdefault("assigned_bots", [])
    value.setdefault("assigned_ai", [])
    value.setdefault("websites", [])
    value.setdefault("rss_sources", [])
    value.setdefault("prompt", "")
    value.setdefault("first_comment", "")
    value.setdefault("schedule", None)
    return value


def get_channel_config(channel_id):
    cid = str(channel_id)
    with lock:
        data = _read()
    raw = data.get("channel_configs", {}).get(cid)
    return _normalize_channel_config(cid, raw)


def update_channel_config(channel_id, **kwargs):
    cid = str(channel_id)
    allowed = {"title_quote", "signature_quote", "assigned_sessions", "assigned_bots", "assigned_ai", "websites", "rss_sources", "prompt", "first_comment", "schedule"}
    with lock:
        data = _read()
        cfg = _normalize_channel_config(cid, data.setdefault("channel_configs", {}).get(cid, {}))
        for k, v in kwargs.items():
            if k in allowed and v is not None:
                cfg[k] = v
        data["channel_configs"][cid] = cfg
        _write(data)
    return True


def set_channel_title_quote(channel_id, enabled):
    return update_channel_config(channel_id, title_quote=bool(enabled))


def get_channel_title_quote(channel_id):
    cfg = get_channel_config(channel_id)
    return bool(cfg.get("title_quote", False))


def set_channel_signature_quote(channel_id, enabled):
    return update_channel_config(channel_id, signature_quote=bool(enabled))


def get_channel_signature_quote(channel_id):
    cfg = get_channel_config(channel_id)
    return bool(cfg.get("signature_quote", False))


# ============================================================
# Multi-Bot Expansion: Dependency Check
# ============================================================

def get_dependencies_for(item_type, item_id):
    cid = str(item_id)
    result = []
    for ch in get_all_channels():
        ch_id = str(ch.get("id", ""))
        cfg = get_channel_config(ch_id)
        if item_type == "session":
            if cid in [str(x) for x in cfg.get("assigned_sessions", [])]:
                result.append(ch)
        elif item_type == "ai_key":
            if cid in [str(x) for x in cfg.get("assigned_ai", [])]:
                result.append(ch)
        elif item_type == "publishing_bot":
            if cid in [str(x) for x in cfg.get("assigned_bots", [])]:
                result.append(ch)
        elif item_type == "website":
            if cid in [str(x) for x in cfg.get("websites", [])]:
                result.append(ch)
    return result


# ============================================================
# Smart Cache System
# ============================================================

CACHE_TTL = {
    "bot_in_channel": 300,       # 5 د للعمليات الحساسة
    "channel_accessible": 600,   # 10 د للتحقق من وجود القناة
    "bot_token_valid": 3600,     # 1 س لصحة التوكن
    "session_valid": 600,        # 10 د لصلاحية الجلسة
    "ui_display": 900,           # 15 د للعرض في الواجهات
}

_verification_cache = {}
_cache_lock = Lock()


def cache_get(key):
    """إرجاع قيمة مخبأة إذا كانت ضمن TTL."""
    with _cache_lock:
        entry = _verification_cache.get(key)
        if entry is None:
            return None
        if time.time() - entry["ts"] < entry["ttl"]:
            return entry["data"]
        del _verification_cache[key]
        return None


def cache_set(key, data, ttl=None):
    """تخزين قيمة مع TTL."""
    if ttl is None:
        ttl = CACHE_TTL.get("ui_display", 900)
    with _cache_lock:
        _verification_cache[key] = {"data": data, "ts": time.time(), "ttl": ttl}


def cache_invalidate(key):
    """حذف قيمة من الكاش."""
    with _cache_lock:
        _verification_cache.pop(key, None)


def cache_invalidate_bot(bot_id):
    """مسح كل الكاش لبوت معين."""
    with _cache_lock:
        to_del = [k for k in _verification_cache if f"|{bot_id}|" in k or f"token_valid|{bot_id}" in k]
        for k in to_del:
            del _verification_cache[k]


def cache_invalidate_channel(channel_id):
    """مسح كل الكاش لقناة معينة."""
    with _cache_lock:
        to_del = [k for k in _verification_cache if k.endswith(f"|{channel_id}") or k == f"channel|{channel_id}"]
        for k in to_del:
            del _verification_cache[k]


def cache_clear_expired():
    """مسح القيم المنتهية."""
    now = time.time()
    with _cache_lock:
        to_del = [k for k, v in _verification_cache.items() if now - v["ts"] >= v["ttl"]]
        for k in to_del:
            del _verification_cache[k]


# ============================================================
# Real-Time Verification Functions (Database Layer)
# ============================================================

VERIFY_TTL_SHORT = 60     # 1 دقيقة
VERIFY_TTL_NORMAL = 300   # 5 دقائق


def get_fresh_bot_verification(bot_id, channel_id):
    """إرجاع التحقق من الكاش فقط إذا كان حديثاً (أقل من TTL قصير)."""
    key = f"verify|{bot_id}|{channel_id}"
    return cache_get(key)


def set_fresh_bot_verification(bot_id, channel_id, result):
    """تخزين نتيجة تحقق حديثة في الكاش."""
    key = f"verify|{bot_id}|{channel_id}"
    cache_set(key, result, ttl=VERIFY_TTL_SHORT)


def invalidate_bot_verification(bot_id, channel_id):
    """مسح التحقق المخبأ لبوت في قناة."""
    key = f"verify|{bot_id}|{channel_id}"
    cache_invalidate(key)


# ============================================================
# Bot Manager - المصدر الوحيد لجميع Bot Tokens
# ============================================================

class BotManager:
    """يدير جميع بوتات النشر.
    
    - أي كود يحتاج توكن بوت يستخدم هذا المدير فقط.
    - لا يسمح بالوصول المباشر إلى التوكن من أي مكان آخر.
    - يوفر التوثيق والتخزين والربط مع القنوات.
    """

    def __init__(self):
        self._cache = {}

    # ---- المصدر الوحيد للتوكن ----
    def get_token(self, bot_id):
        """الطريقة الوحيدة في المشروع بأكمله للحصول على توكن بوت."""
        b = get_publishing_bot(str(bot_id))
        if not b:
            return ""
        return b.get("token", "")

    def get_bot(self, bot_id):
        """إرجاع بيانات البوت كاملة (بدون ضمان إخفاء التوكن للاستخدام الداخلي)."""
        return get_publishing_bot(str(bot_id))

    def get_all_bots(self):
        """إرجاع جميع البوتات."""
        return get_all_publishing_bots()

    def add_bot(self, token, username="", name=""):
        """إضافة بوت جديد."""
        return add_publishing_bot(token, username=username, name=name)

    def delete_bot(self, bot_id):
        """حذف بوت ونقل إلى سلة المهملات."""
        return delete_publishing_bot(str(bot_id))

    def update_bot(self, bot_id, **kwargs):
        """تحديث بيانات بوت."""
        return update_publishing_bot(str(bot_id), **kwargs)

    def set_enabled(self, bot_id, enabled):
        """تشغيل/إيقاف بوت."""
        return set_publishing_bot_enabled(str(bot_id), enabled)

    def record_publish(self, bot_id, content_type="text"):
        """تسجيل عملية نشر لبوت."""
        return record_bot_publish(str(bot_id), content_type)

    def validate_token_format(self, token):
        """التحقق من صيغة التوكن (بدون اتصال بـ Telegram)."""
        return bool(token and ":" in token and len(token) > 20)


# ============================================================
# Channel Manager - إدارة موحدة للقنوات
# ============================================================

class ChannelManager:
    """يدير جميع القنوات بشكل موحد.
    
    - يدمج معلومات القناة (channels) مع إعداداتها (channel_configs).
    - كل قناة لها Chat ID كمعرف أساسي.
    - لا يعتمد على الأسماء.
    """

    def get(self, channel_id):
        """إرجاع معلومات القناة موحدة مع إعداداتها."""
        cid = str(channel_id)
        ch = get_channel(cid)
        if not ch:
            return None
        cfg = get_channel_config(cid)
        result = dict(ch)
        result["config"] = cfg
        return result

    def get_all(self):
        """إرجاع جميع القنوات مع إعداداتها."""
        channels = get_all_channels()
        result = []
        for ch in channels:
            cid = str(ch["id"])
            cfg = get_channel_config(cid)
            item = dict(ch)
            item["config"] = cfg
            result.append(item)
        return result

    def get_active(self):
        """إرجاع القنوات غير الموقوفة فقط."""
        return [ch for ch in self.get_all() if not ch.get("paused")]

    def add(self, channel_id, **meta):
        """إضافة قناة جديدة."""
        return add_channel(str(channel_id), **meta)

    def delete(self, channel_id):
        """حذف قناة."""
        return delete_channel(str(channel_id))

    def update(self, channel_id, key, value):
        """تحديث حقل في القناة."""
        return update_channel(str(channel_id), key, value)

    def get_config(self, channel_id):
        """إرجاع إعدادات القناة."""
        return get_channel_config(str(channel_id))

    def update_config(self, channel_id, **kwargs):
        """تحديث إعدادات القناة."""
        return update_channel_config(str(channel_id), **kwargs)

    def exists(self, channel_id):
        """التحقق من وجود القناة في قاعدة البيانات."""
        return get_channel(str(channel_id)) is not None


# ============================================================
# Bot-Channel Mapper - جدول ربط مستقل
# ============================================================

class BotChannelMapper:
    """يدير العلاقة بين البوتات والقنوات.
    
    - المصدر الوحيد لمعرفة أي بوت مرتبط بأي قناة.
    - لا يعتمد على التخزين في الذاكرة.
    - كل العلاقات مخزنة في قاعدة البيانات.
    """

    def assign(self, bot_id, channel_id):
        """ربط بوت بقناة."""
        bid = str(bot_id)
        cid = str(channel_id)
        cfg = get_channel_config(cid)
        assigned = list(cfg.get("assigned_bots", []))
        if bid not in [str(x) for x in assigned]:
            assigned.append(bid)
            update_channel_config(cid, assigned_bots=assigned)
            return True
        return False

    def unassign(self, bot_id, channel_id):
        """فك ربط بوت من قناة."""
        bid = str(bot_id)
        cid = str(channel_id)
        cfg = get_channel_config(cid)
        assigned = [str(x) for x in cfg.get("assigned_bots", [])]
        if bid in assigned:
            assigned = [x for x in assigned if x != bid]
            update_channel_config(cid, assigned_bots=assigned)
            return True
        return False

    def get_bots_for_channel(self, channel_id):
        """إرجاع IDs البوتات المرتبطة بقناة."""
        cfg = get_channel_config(str(channel_id))
        return [str(x) for x in cfg.get("assigned_bots", [])]

    def get_channels_for_bot(self, bot_id):
        """إرجاع IDs القنوات التي يستخدمها بوت."""
        bid = str(bot_id)
        result = []
        for ch in get_all_channels():
            cid = str(ch["id"])
            cfg = get_channel_config(cid)
            if bid in [str(x) for x in cfg.get("assigned_bots", [])]:
                result.append(cid)
        return result

    def get_assigned_bot_objects(self, channel_id):
        """إرجاع بيانات البوتات الكاملة المرتبطة بقناة."""
        bots = []
        for bid in self.get_bots_for_channel(channel_id):
            b = get_publishing_bot(bid)
            if b:
                bots.append(b)
        return bots

    def is_assigned(self, bot_id, channel_id):
        """التحقق من ارتباط بوت بقناة."""
        return str(bot_id) in self.get_bots_for_channel(channel_id)

    def unassign_all_for_bot(self, bot_id):
        """فك ربط بوت من جميع القنوات."""
        bid = str(bot_id)
        count = 0
        for cid in self.get_channels_for_bot(bid):
            if self.unassign(bid, cid):
                count += 1
        return count


# إنشاء instance عامة للاستخدام في جميع أنحاء المشروع
bot_manager = BotManager()
channel_manager = ChannelManager()
mapper = BotChannelMapper()

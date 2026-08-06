"""Persistence for analytics, topics, flags, test keys, users, billing, and
the app-key vault.

Runs on Supabase Postgres when DATABASE_URL is set (records live outside the
app containers, so deploys never touch them) and falls back to local SQLite
otherwise. All schema changes are additive (CREATE TABLE IF NOT EXISTS);
the application never drops, truncates, or bulk-deletes anything.
"""
import json
import os
import secrets
import time
from pathlib import Path

from db import ID_PK, IS_PG, TS, get_db

# Kept for compatibility with older imports/tests.
DB_PATH = Path(os.environ.get("VERSEO_DB", Path(__file__).parent / "data" / "verseo.db"))
TOPICS_SEED = Path(__file__).parent / "topics.json"

# Default feature flags / tunable config (seeded once; editable in admin).
DEFAULT_FLAGS = {
    "ask_enabled": "1",
    "crossrefs_enabled": "1",
    "similar_enabled": "1",
    "listen_enabled": "1",
    "maintenance": "0",
    # Global kill switch — when "1", all actions are disabled app-wide.
    "disabled": "0",
    # Test mode — when "1", the app is closed to the public and only accessible
    # with a valid test key (see test_keys table below).
    "test_mode": "0",
    # Search-quality weights (search lab tunes these live).
    "w_semantic": "0.65",
    "w_lexical": "0.35",
    "w_ce": "0.60",
    "w_ce_semantic": "0.25",
    "w_ce_lexical": "0.15",
}

_SCHEMA = [
    f"""CREATE TABLE IF NOT EXISTS events (
        id {ID_PK},
        ts {TS}, kind TEXT, mode TEXT, query TEXT,
        top_ref TEXT, confident INTEGER, version TEXT, scope TEXT, lang TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)",
    f"""CREATE TABLE IF NOT EXISTS topics (
        id {ID_PK},
        label TEXT, emoji TEXT, query TEXT,
        position INTEGER DEFAULT 0, enabled INTEGER DEFAULT 1
    )""",
    "CREATE TABLE IF NOT EXISTS flags (key TEXT PRIMARY KEY, value TEXT)",
    f"""CREATE TABLE IF NOT EXISTS test_keys (
        id {ID_PK},
        key TEXT UNIQUE NOT NULL,
        label TEXT,
        created_at {TS},
        last_used {TS},
        enabled INTEGER DEFAULT 1,
        speak INTEGER DEFAULT 1,
        type_ INTEGER DEFAULT 1,
        ask INTEGER DEFAULT 1,
        listen INTEGER DEFAULT 1
    )""",
    f"""CREATE TABLE IF NOT EXISTS feedback (
        id {ID_PK},
        ts {TS},
        key TEXT,
        label TEXT,
        rating INTEGER,
        message TEXT
    )""",
    # Accounts (id = Supabase auth user id).
    f"""CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT,
        name TEXT,
        plan TEXT DEFAULT 'free',
        status TEXT DEFAULT 'active',
        stripe_customer_id TEXT,
        created_at {TS},
        last_seen {TS},
        onboarded_at {TS}
    )""",
    # Payment history (idempotent on the Stripe object id).
    f"""CREATE TABLE IF NOT EXISTS payments (
        id {ID_PK},
        ts {TS},
        user_id TEXT,
        email TEXT,
        amount INTEGER,
        currency TEXT,
        status TEXT,
        stripe_id TEXT UNIQUE,
        description TEXT
    )""",
    # App-key vault: service credentials managed from the admin console.
    f"""CREATE TABLE IF NOT EXISTS app_keys (
        name TEXT PRIMARY KEY,
        value TEXT,
        updated_at {TS}
    )""",
    # Sermon Studio: outlines built around a storytelling arc, with Bible
    # passages linked to each point (Speaker-plan feature).
    f"""CREATE TABLE IF NOT EXISTS sermons (
        id {ID_PK},
        user_id TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT DEFAULT '',
        status TEXT DEFAULT 'draft',
        created_at {TS},
        updated_at {TS}
    )""",
    "CREATE INDEX IF NOT EXISTS idx_sermons_user ON sermons(user_id)",
    f"""CREATE TABLE IF NOT EXISTS sermon_points (
        id {ID_PK},
        sermon_id INTEGER NOT NULL,
        position INTEGER DEFAULT 0,
        beat TEXT DEFAULT '',
        title TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        verse_refs TEXT DEFAULT '[]'
    )""",
    "CREATE INDEX IF NOT EXISTS idx_sermon_points_sermon ON sermon_points(sermon_id)",
]


def init_db():
    with get_db() as db:
        for stmt in _SCHEMA:
            db.exec(stmt)
        # Additive migration for tables created before onboarded_at existed.
        try:
            db.exec(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarded_at {TS}")
        except Exception:  # noqa: BLE001 - older SQLite lacks IF NOT EXISTS
            pass
        # Seed flags (never overwrites existing values).
        for k, v in DEFAULT_FLAGS.items():
            db.exec(
                "INSERT INTO flags(key, value) VALUES (?, ?) ON CONFLICT(key) DO NOTHING",
                (k, v),
            )
        # Seed topics from the bundled JSON the first time only.
        n = db.one("SELECT COUNT(*) AS n FROM topics")["n"]
        if n == 0 and TOPICS_SEED.exists():
            seed = json.loads(TOPICS_SEED.read_text())
            for i, t in enumerate(seed):
                db.exec(
                    "INSERT INTO topics(label, emoji, query, position, enabled) VALUES (?,?,?,?,1)",
                    (t["label"], t.get("emoji", ""), t["query"], i),
                )


# -- analytics ----------------------------------------------------------------
def log_event(kind, mode, query, top_ref, confident, version="all", scope="all", lang=""):
    try:
        with get_db() as db:
            db.exec(
                "INSERT INTO events(ts, kind, mode, query, top_ref, confident, version, scope, lang)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (time.time(), kind, mode, (query or "")[:160], top_ref,
                 1 if confident else 0, version, scope, lang),
            )
    except Exception:  # noqa: BLE001 - analytics must never break a request
        pass


def stats(days=30):
    since = time.time() - days * 86400
    day_expr = (
        "to_char(to_timestamp(ts), 'YYYY-MM-DD')" if IS_PG else "date(ts,'unixepoch')"
    )
    with get_db() as db:
        total = db.one("SELECT COUNT(*) AS n FROM events WHERE ts>=?", (since,))["n"]
        searches = db.one(
            "SELECT COUNT(*) AS n FROM events WHERE ts>=? AND kind='search'", (since,)
        )["n"]
        asks = db.one(
            "SELECT COUNT(*) AS n FROM events WHERE ts>=? AND kind='ask'", (since,)
        )["n"]
        top = [
            {"term": r["query"], "count": r["n"]}
            for r in db.q(
                "SELECT query, COUNT(*) AS n FROM events WHERE ts>=? AND query<>'' "
                "GROUP BY query ORDER BY n DESC LIMIT 25", (since,)
            )
        ]
        modes = {
            r["mode"]: r["n"]
            for r in db.q(
                "SELECT mode, COUNT(*) AS n FROM events WHERE ts>=? GROUP BY mode", (since,)
            )
        }
        refs = [
            {"ref": r["top_ref"], "count": r["n"]}
            for r in db.q(
                "SELECT top_ref, COUNT(*) AS n FROM events WHERE ts>=? AND top_ref IS NOT NULL "
                "AND top_ref<>'' GROUP BY top_ref ORDER BY n DESC LIMIT 15", (since,)
            )
        ]
        daily = [
            {"day": r["d"], "count": r["n"]}
            for r in db.q(
                f"SELECT {day_expr} AS d, COUNT(*) AS n FROM events WHERE ts>=? "
                "GROUP BY d ORDER BY d", (since,)
            )
        ]
    return {
        "days": days, "total": total, "searches": searches, "asks": asks,
        "topTerms": top, "modes": modes, "topVerses": refs, "daily": daily,
    }


def zero_results(days=30, limit=40):
    """Queries that returned no confident match — the coverage-gap report."""
    since = time.time() - days * 86400
    with get_db() as db:
        rows = db.q(
            "SELECT query, COUNT(*) AS n FROM events WHERE ts>=? AND kind='search' "
            "AND confident=0 AND query<>'' GROUP BY query ORDER BY n DESC LIMIT ?",
            (since, limit),
        )
    return [{"query": r["query"], "count": r["n"]} for r in rows]


# -- topics CMS ---------------------------------------------------------------
def list_topics(enabled_only=False):
    q = "SELECT * FROM topics"
    if enabled_only:
        q += " WHERE enabled=1"
    q += " ORDER BY position, id"
    with get_db() as db:
        return db.q(q)


def add_topic(label, emoji, query):
    with get_db() as db:
        pos = db.one("SELECT COALESCE(MAX(position),0)+1 AS p FROM topics")["p"]
        row = db.one(
            "INSERT INTO topics(label, emoji, query, position, enabled) VALUES (?,?,?,?,1) RETURNING id",
            (label, emoji, query, pos),
        )
        return row["id"]


def update_topic(topic_id, fields):
    allowed = {"label", "emoji", "query", "position", "enabled"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    cols = ", ".join(f"{k}=?" for k in sets)
    with get_db() as db:
        db.exec(f"UPDATE topics SET {cols} WHERE id=?", (*sets.values(), topic_id))


def delete_topic(topic_id):
    with get_db() as db:
        db.exec("DELETE FROM topics WHERE id=?", (topic_id,))


# -- flags / config -----------------------------------------------------------
def get_flags():
    with get_db() as db:
        return {r["key"]: r["value"] for r in db.q("SELECT key, value FROM flags")}


def set_flags(updates: dict):
    with get_db() as db:
        for k, v in updates.items():
            db.exec(
                "INSERT INTO flags(key,value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (k, str(v)),
            )


def get_weights() -> dict:
    f = get_flags()

    def g(k, d):
        try:
            return float(f.get(k, d))
        except (TypeError, ValueError):
            return d

    return {
        "semantic": g("w_semantic", 0.65),
        "lexical": g("w_lexical", 0.35),
        "ce": g("w_ce", 0.60),
        "ce_semantic": g("w_ce_semantic", 0.25),
        "ce_lexical": g("w_ce_lexical", 0.15),
    }


# -- test keys / feedback -----------------------------------------------------
def _gen_key() -> str:
    """Short, URL-safe shareable key like 'vrs-ab12cd34ef56'."""
    return "vrs-" + secrets.token_hex(6)


def list_test_keys() -> list[dict]:
    with get_db() as db:
        return db.q("SELECT * FROM test_keys ORDER BY created_at DESC")


def add_test_key(label: str = "") -> dict:
    key = _gen_key()
    with get_db() as db:
        db.exec(
            "INSERT INTO test_keys(key, label, created_at) VALUES (?,?,?)",
            (key, label or "", time.time()),
        )
        return db.one("SELECT * FROM test_keys WHERE key=?", (key,))


def update_test_key(key_id: int, fields: dict):
    allowed = {"label", "enabled", "speak", "type_", "ask", "listen"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    cols = ", ".join(f"{k}=?" for k in sets)
    with get_db() as db:
        db.exec(f"UPDATE test_keys SET {cols} WHERE id=?", (*sets.values(), key_id))


def delete_test_key(key_id: int):
    with get_db() as db:
        db.exec("DELETE FROM test_keys WHERE id=?", (key_id,))


def get_test_key(key: str) -> dict | None:
    """Look up a key; mark as used."""
    if not key:
        return None
    with get_db() as db:
        row = db.one(
            "SELECT * FROM test_keys WHERE key=? AND enabled=1", (key.strip(),)
        )
        if row:
            db.exec("UPDATE test_keys SET last_used=? WHERE id=?",
                    (time.time(), row["id"]))
    return row


def add_feedback(key: str, label: str, rating: int | None, message: str):
    with get_db() as db:
        db.exec(
            "INSERT INTO feedback(ts, key, label, rating, message) VALUES (?,?,?,?,?)",
            (time.time(), key or "", label or "", rating, (message or "")[:2000]),
        )


def list_feedback(limit: int = 200) -> list[dict]:
    with get_db() as db:
        return db.q("SELECT * FROM feedback ORDER BY ts DESC LIMIT ?", (limit,))


def delete_feedback(fid: int):
    with get_db() as db:
        db.exec("DELETE FROM feedback WHERE id=?", (fid,))


# -- users / accounts ---------------------------------------------------------
def upsert_user(user_id: str, email: str = "", name: str = "") -> dict:
    """Create or refresh a user row on sign-in (id = Supabase auth uid)."""
    now = time.time()
    with get_db() as db:
        db.exec(
            "INSERT INTO users(id, email, name, created_at, last_seen) VALUES (?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET email=excluded.email, last_seen=excluded.last_seen",
            (user_id, email or "", name or "", now, now),
        )
        return db.one("SELECT * FROM users WHERE id=?", (user_id,))


def get_user(user_id: str) -> dict | None:
    with get_db() as db:
        return db.one("SELECT * FROM users WHERE id=?", (user_id,))


def get_user_by_customer(stripe_customer_id: str) -> dict | None:
    with get_db() as db:
        return db.one(
            "SELECT * FROM users WHERE stripe_customer_id=?", (stripe_customer_id,)
        )


def mark_onboarded(user_id: str) -> None:
    with get_db() as db:
        db.exec(
            "UPDATE users SET onboarded_at=? WHERE id=? AND onboarded_at IS NULL",
            (time.time(), user_id),
        )


def set_user_billing(user_id: str, plan: str | None = None, status: str | None = None,
                     stripe_customer_id: str | None = None):
    sets, params = [], []
    if plan is not None:
        sets.append("plan=?"); params.append(plan)
    if status is not None:
        sets.append("status=?"); params.append(status)
    if stripe_customer_id is not None:
        sets.append("stripe_customer_id=?"); params.append(stripe_customer_id)
    if not sets:
        return
    params.append(user_id)
    with get_db() as db:
        db.exec(f"UPDATE users SET {', '.join(sets)} WHERE id=?", tuple(params))


def list_users(limit: int = 500) -> list[dict]:
    with get_db() as db:
        return db.q("SELECT * FROM users ORDER BY created_at DESC LIMIT ?", (limit,))


# -- payments -----------------------------------------------------------------
def record_payment(stripe_id: str, user_id: str, email: str, amount: int,
                   currency: str, status: str, description: str = ""):
    """Idempotent on stripe_id (webhooks may be retried)."""
    with get_db() as db:
        db.exec(
            "INSERT INTO payments(ts, user_id, email, amount, currency, status, stripe_id, description) "
            "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(stripe_id) DO NOTHING",
            (time.time(), user_id or "", email or "", amount, currency, status,
             stripe_id, (description or "")[:200]),
        )


def list_payments(limit: int = 200) -> list[dict]:
    with get_db() as db:
        return db.q("SELECT * FROM payments ORDER BY ts DESC LIMIT ?", (limit,))


def billing_stats() -> dict:
    with get_db() as db:
        revenue = db.one(
            "SELECT COALESCE(SUM(amount),0) AS s FROM payments WHERE status IN ('paid','succeeded','complete')"
        )["s"]
        n_payments = db.one("SELECT COUNT(*) AS n FROM payments")["n"]
        n_users = db.one("SELECT COUNT(*) AS n FROM users")["n"]
        plans = {
            r["plan"]: r["n"]
            for r in db.q("SELECT plan, COUNT(*) AS n FROM users GROUP BY plan")
        }
    return {
        "revenue_cents": int(revenue or 0),
        "payments": n_payments,
        "users": n_users,
        "plans": plans,
    }


# -- app-key vault ------------------------------------------------------------
# Known service keys, their env-var fallbacks, and admin labels.
KNOWN_APP_KEYS = [
    {"name": "anthropic_api_key", "env": "ANTHROPIC_API_KEY", "label": "Anthropic (Claude) API key"},
    {"name": "stripe_secret_key", "env": "STRIPE_SECRET_KEY", "label": "Stripe secret key"},
    {"name": "stripe_webhook_secret", "env": "STRIPE_WEBHOOK_SECRET", "label": "Stripe webhook signing secret"},
    {"name": "stripe_price_plus", "env": "STRIPE_PRICE_PLUS", "label": "Stripe price ID — Plus plan"},
    {"name": "stripe_price_speaker", "env": "STRIPE_PRICE_SPEAKER", "label": "Stripe price ID — Speaker plan"},
]


def set_app_key(name: str, value: str):
    with get_db() as db:
        db.exec(
            "INSERT INTO app_keys(name, value, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (name.strip(), value, time.time()),
        )


def delete_app_key(name: str):
    with get_db() as db:
        db.exec("DELETE FROM app_keys WHERE name=?", (name,))


def get_app_key(name: str, env: str | None = None) -> str:
    """DB value first, then the env-var fallback."""
    try:
        with get_db() as db:
            row = db.one("SELECT value FROM app_keys WHERE name=?", (name,))
        if row and row["value"]:
            return row["value"]
    except Exception:  # noqa: BLE001 - fall through to env
        pass
    if env is None:
        env = next((k["env"] for k in KNOWN_APP_KEYS if k["name"] == name), None)
    return os.environ.get(env, "") if env else ""


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return value[:4] + "…" + value[-4:]


def list_app_keys_masked() -> list[dict]:
    """Every known key + any custom rows, values masked (never returned raw)."""
    with get_db() as db:
        rows = {r["name"]: r for r in db.q("SELECT * FROM app_keys")}
    out = []
    seen = set()
    for spec in KNOWN_APP_KEYS:
        row = rows.get(spec["name"])
        env_val = os.environ.get(spec["env"], "")
        val = (row or {}).get("value") or ""
        out.append({
            "name": spec["name"],
            "label": spec["label"],
            "set": bool(val or env_val),
            "source": "db" if val else ("env" if env_val else ""),
            "masked": _mask(val or env_val),
            "updated_at": (row or {}).get("updated_at"),
        })
        seen.add(spec["name"])
    for name, row in rows.items():
        if name not in seen:
            out.append({
                "name": name, "label": name, "set": bool(row["value"]),
                "source": "db", "masked": _mask(row["value"] or ""),
                "updated_at": row["updated_at"],
            })
    return out


# -- Sermon Studio --------------------------------------------------------------
def _load_point(row: dict) -> dict:
    row = dict(row)
    try:
        row["verse_refs"] = json.loads(row.get("verse_refs") or "[]")
    except (TypeError, ValueError):
        row["verse_refs"] = []
    return row


def _replace_points(db, sermon_id: int, points: list[dict]):
    db.exec("DELETE FROM sermon_points WHERE sermon_id=?", (sermon_id,))
    for i, p in enumerate(points):
        db.exec(
            "INSERT INTO sermon_points(sermon_id, position, beat, title, notes, verse_refs) "
            "VALUES (?,?,?,?,?,?)",
            (sermon_id, i, p.get("beat", ""), p.get("title", ""), p.get("notes", ""),
             json.dumps(p.get("verse_refs") or [])),
        )


def _sermon_with_points(db, sermon: dict) -> dict:
    points = db.q(
        "SELECT * FROM sermon_points WHERE sermon_id=? ORDER BY position", (sermon["id"],)
    )
    sermon = dict(sermon)
    sermon["points"] = [_load_point(p) for p in points]
    return sermon


def create_sermon(user_id: str, title: str, description: str = "",
                  points: list[dict] | None = None) -> dict:
    now = time.time()
    with get_db() as db:
        row = db.one(
            "INSERT INTO sermons(user_id, title, description, created_at, updated_at) "
            "VALUES (?,?,?,?,?) RETURNING id",
            (user_id, title, description, now, now),
        )
        sermon_id = row["id"]
        _replace_points(db, sermon_id, points or [])
        sermon = db.one("SELECT * FROM sermons WHERE id=?", (sermon_id,))
        return _sermon_with_points(db, sermon)


def list_sermons(user_id: str, include_archived: bool = False) -> list[dict]:
    q = "SELECT * FROM sermons WHERE user_id=?"
    if not include_archived:
        q += " AND status != 'archived'"
    q += " ORDER BY updated_at DESC"
    with get_db() as db:
        return db.q(q, (user_id,))


def get_sermon(user_id: str, sermon_id: int) -> dict | None:
    with get_db() as db:
        sermon = db.one(
            "SELECT * FROM sermons WHERE id=? AND user_id=?", (sermon_id, user_id)
        )
        if not sermon:
            return None
        return _sermon_with_points(db, sermon)


def update_sermon(user_id: str, sermon_id: int, title: str | None = None,
                  description: str | None = None, status: str | None = None,
                  points: list[dict] | None = None) -> dict | None:
    with get_db() as db:
        existing = db.one(
            "SELECT id FROM sermons WHERE id=? AND user_id=?", (sermon_id, user_id)
        )
        if not existing:
            return None
        sets, params = ["updated_at=?"], [time.time()]
        if title is not None:
            sets.append("title=?"); params.append(title)
        if description is not None:
            sets.append("description=?"); params.append(description)
        if status is not None:
            sets.append("status=?"); params.append(status)
        params.append(sermon_id)
        db.exec(f"UPDATE sermons SET {', '.join(sets)} WHERE id=?", tuple(params))
        if points is not None:
            _replace_points(db, sermon_id, points)
        sermon = db.one("SELECT * FROM sermons WHERE id=?", (sermon_id,))
        return _sermon_with_points(db, sermon)


def archive_sermon(user_id: str, sermon_id: int) -> bool:
    """Soft-delete only — records are never hard-deleted."""
    with get_db() as db:
        existing = db.one(
            "SELECT id FROM sermons WHERE id=? AND user_id=?", (sermon_id, user_id)
        )
        if not existing:
            return False
        db.exec(
            "UPDATE sermons SET status='archived', updated_at=? WHERE id=?",
            (time.time(), sermon_id),
        )
        return True

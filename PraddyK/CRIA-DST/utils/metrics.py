"""
utils/metrics.py — lightweight, crash-proof visit counter + star ratings/reviews.

Storage: a single JSON file on the Space's filesystem. This survives app restarts
but is reset on a full redeploy/rebuild (that is the trade-off of the "simple file"
approach). Every function is wrapped so a storage failure can NEVER break the app —
on any error it degrades to safe defaults.
"""

import json
import os
import time
import threading
from pathlib import Path

_LOCK = threading.Lock()
_FILE = Path(__file__).resolve().parent.parent / "data" / "metrics.json"

# ── Optional persistence to a free HuggingFace Dataset (survives rebuilds) ──
# Set two Space secrets to turn it on:  CRIA_DATA_REPO = "user/cria-data"  and
# HF_TOKEN = <your HF write token>. If unset, everything falls back to the local
# file exactly as before — so this is always safe.
try:
    from huggingface_hub import HfApi, hf_hub_download
except Exception:
    HfApi = None
    hf_hub_download = None

_REPO = (os.environ.get("CRIA_DATA_REPO", "") or "").strip()
_TOKEN = (os.environ.get("HF_TOKEN", "") or os.environ.get("HUGGINGFACE_TOKEN", "") or "").strip()
_HF_ON = bool(HfApi and _REPO and _TOKEN)
_pulled = [False]
_last_push = [0.0]
_PUSH_LOCK = threading.Lock()


def _pull_once():
    """On first use, restore metrics.json from the HF Dataset (persists reviews/visits)."""
    if _pulled[0]:
        return
    _pulled[0] = True
    if not _HF_ON:
        return
    try:
        import shutil
        p = hf_hub_download(repo_id=_REPO, filename="metrics.json",
                            repo_type="dataset", token=_TOKEN, force_download=True)
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(p, _FILE)
    except Exception:
        pass  # dataset empty / first run — start fresh, nothing lost


def _push(force=False):
    """Upload metrics.json to the HF Dataset. Debounced (~60s) unless forced (reviews)."""
    if not _HF_ON:
        return

    def _do():
        try:
            with _PUSH_LOCK:
                now = time.time()
                if not force and now - _last_push[0] < 60:
                    return
                _last_push[0] = now
                HfApi().upload_file(path_or_fileobj=str(_FILE), path_in_repo="metrics.json",
                                    repo_id=_REPO, repo_type="dataset", token=_TOKEN,
                                    commit_message="update metrics")
        except Exception:
            pass  # never break the app on a sync hiccup

    threading.Thread(target=_do, daemon=True).start()


def _load():
    _pull_once()
    try:
        d = json.loads(_FILE.read_text())
        d.setdefault("visits", 0)
        d.setdefault("ratings", [])
        d.setdefault("reviews", [])
        return d
    except Exception:
        return {"visits": 0, "ratings": [], "reviews": []}


def _save(d, force=False):
    try:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d))
        tmp.replace(_FILE)
    except Exception:
        pass  # never raise
    _push(force)  # sync to the HF Dataset if configured (debounced; forced for reviews)


def bump_visit():
    """Increment and return the total visit count."""
    try:
        with _LOCK:
            d = _load()
            d["visits"] = int(d.get("visits", 0)) + 1
            _save(d)
            return d["visits"]
    except Exception:
        return 0


def add_rating(stars, review=""):
    """Record a star rating (1-5) and optional review text. Returns fresh summary()."""
    try:
        stars = max(1, min(5, int(stars)))
        with _LOCK:
            d = _load()
            d["ratings"].append(stars)
            text = (review or "").strip()
            if text:
                d["reviews"].append({"stars": stars, "text": text[:600]})
            _save(d, force=True)
            # Also echo to stdout so submissions appear in the Space's logs
            # (viewable in the Hugging Face UI even if the file resets on redeploy).
            try:
                print(f"[CRIA feedback] {stars}★"
                      + (f" — {text[:600]}" if text else ""), flush=True)
            except Exception:
                pass
            return _summary(d)
    except Exception:
        return summary()


def add_review(stars, name="", role="", avatar="", text=""):
    """Record a full testimonial. Returns the new review's id (or '' on error)."""
    try:
        import time
        import uuid
        stars = max(1, min(5, int(stars)))
        rid = uuid.uuid4().hex[:12]
        with _LOCK:
            d = _load()
            d["ratings"].append(stars)
            entry = {
                "id": rid,
                "stars": stars,
                "name": (name or "").strip()[:60],
                "role": (role or "").strip()[:80],
                "avatar": (avatar or "").strip()[:200000],
                "text": (text or "").strip()[:10000],
                "ts": int(time.time()),
            }
            d["reviews"].append(entry)
            _save(d, force=True)
            try:
                print(f"[CRIA review] {stars}★ {entry['name'] or 'Anonymous'}"
                      f" ({entry['role'] or '-'}) — {entry['text']}", flush=True)
            except Exception:
                pass
            return rid
    except Exception:
        return ""


def delete_review(rid):
    """Delete a review by id. Returns True if one was removed."""
    try:
        rid = (rid or "").strip()
        if not rid:
            return False
        with _LOCK:
            d = _load()
            revs = d.get("reviews", [])
            before = len(revs)
            d["reviews"] = [r for r in revs if r.get("id") != rid]
            _save(d, force=True)
            return len(d["reviews"]) < before
    except Exception:
        return False


def edit_review(rid, stars=None, name=None, role=None, avatar=None, text=None):
    """Update fields of a review by id. Returns True on success."""
    try:
        rid = (rid or "").strip()
        if not rid:
            return False
        with _LOCK:
            d = _load()
            ok = False
            for r in d.get("reviews", []):
                if r.get("id") == rid:
                    if stars is not None:
                        r["stars"] = max(1, min(5, int(stars)))
                    if name is not None:
                        r["name"] = (name or "").strip()[:60]
                    if role is not None:
                        r["role"] = (role or "").strip()[:80]
                    if avatar is not None and avatar != "":
                        r["avatar"] = (avatar or "").strip()[:200000]
                    if text is not None:
                        r["text"] = (text or "").strip()[:10000]
                    ok = True
                    break
            if ok:
                _save(d, force=True)
            return ok
    except Exception:
        return False


def get_reviews(limit=40):
    """Recent reviews with comment text, most recent first — safe empty list on error."""
    try:
        d = _load()
        revs = [r for r in d.get("reviews", []) if isinstance(r, dict) and r.get("text")]
        return revs[-limit:][::-1]
    except Exception:
        return []


def bump_country(code):
    """Increment the per-country visit tally (aggregate only — no IPs stored)."""
    try:
        code = (code or "").strip().upper()[:2]
        if not code.isalpha():
            return
        with _LOCK:
            d = _load()
            c = d.setdefault("countries", {})
            c[code] = int(c.get(code, 0)) + 1
            _save(d)
    except Exception:
        pass


def bump_tz(zone):
    """Increment the per-timezone tally (aggregate only — the browser's IANA zone,
    e.g. 'America/Phoenix'). No IP or precise location is ever stored."""
    try:
        zone = (zone or "").strip()[:64]
        if not zone or "/" not in zone:
            return
        with _LOCK:
            d = _load()
            z = d.setdefault("tz_zones", {})
            z[zone] = int(z.get(zone, 0)) + 1
            _save(d)
    except Exception:
        pass


def get_tz_counts(limit=20):
    """Top visitor timezones as (zone, count) pairs, most first."""
    try:
        z = _load().get("tz_zones", {})
        return sorted(z.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    except Exception:
        return []


def reset_geo_once():
    """One-time migration: the old country tally was IP-based and, behind the
    Hugging Face proxy, counted the proxy's location rather than the visitor's. Clear
    it once so the new timezone-based tally starts clean. Guarded by a persisted flag,
    so it runs exactly once ever (idempotent across restarts and workers)."""
    try:
        with _LOCK:
            d = _load()
            if not d.get("_geo_reset_v2"):
                d["countries"] = {}
                d["tz_zones"] = {}
                d["_geo_reset_v2"] = True
                _save(d, force=True)
    except Exception:
        pass


def get_countries(limit=8):
    """Top visitor country codes by count, most first — safe empty list on error."""
    try:
        c = _load().get("countries", {})
        return [code for code, _ in sorted(c.items(), key=lambda kv: kv[1], reverse=True)[:limit]]
    except Exception:
        return []


def get_country_counts(limit=12):
    """Top visitor countries as (code, count) pairs, most first — for the admin view."""
    try:
        c = _load().get("countries", {})
        return sorted(c.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    except Exception:
        return []


def ensure_seed_reviews(entries):
    """Add demo/seed reviews (each carrying a FIXED id) if not already present.
       Idempotent — safe to call on every startup and across multiple workers;
       it never duplicates and never touches user-submitted reviews."""
    try:
        import time
        with _LOCK:
            d = _load()
            have = {r.get("id") for r in d.get("reviews", []) if isinstance(r, dict)}
            added = 0
            for e in entries:
                rid = e.get("id")
                if not rid or rid in have:
                    continue
                stars = max(1, min(5, int(e.get("stars", 5))))
                d["reviews"].append({
                    "id": rid, "stars": stars,
                    "name": (e.get("name", "") or "").strip()[:60],
                    "role": (e.get("role", "") or "").strip()[:80],
                    "avatar": (e.get("avatar", "") or "").strip()[:200000],
                    "text": (e.get("text", "") or "").strip()[:10000],
                    "ts": int(e.get("ts", time.time())),
                })
                d["ratings"].append(stars)
                have.add(rid)
                added += 1
            if added:
                _save(d)
            return added
    except Exception:
        return 0


def summary():
    """Return {'visits', 'avg', 'count'} — safe defaults on any error."""
    try:
        return _summary(_load())
    except Exception:
        return {"visits": 0, "avg": 0.0, "count": 0}


def _summary(d):
    r = [x for x in d.get("ratings", []) if isinstance(x, (int, float))]
    avg = round(sum(r) / len(r), 1) if r else 0.0
    return {"visits": int(d.get("visits", 0)), "avg": avg, "count": len(r)}

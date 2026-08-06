"""Cloud-side five-company packet collection (data-only).

Why: the Hermes host cannot reach vip.titan007.com directly, so every local
capture fell back to a single public relay at ~112s per page. One match needs 10
changeDetail pages, so formal prediction always blew its timeout. Measured on
this Space: direct vip.titan007.com fetches return in 2.3-3.2s. Collection
belongs here.

Runs the same collector the host ran (collector/hermes_hf_client.live_packet),
persists immutable packets to the Dataset, and never emits a direction, stake or
bankroll write. The host stays the sole decision maker.
"""
from __future__ import annotations

import os, sys, json, time, hashlib, threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

COLLECTOR_DIR = Path(__file__).resolve().parent / "collector"
if str(COLLECTOR_DIR) not in sys.path:
    sys.path.insert(0, str(COLLECTOR_DIR))

_LOCK = threading.Lock()
_STATE: dict = {"running": False, "started_at": None, "day": None, "total": 0,
                "done": 0, "ok": 0, "failed": 0, "current": None,
                "results": {}, "finished_at": None}

MAX_WORKERS = int(os.getenv("CROW_PACKET_WORKERS", "4"))
TZ8 = timezone(timedelta(hours=8))


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _collector():
    import hermes_hf_client as client
    return client


def collect_one(match_id: str) -> dict:
    client = _collector()
    started = time.time()
    try:
        packet = client.live_packet(str(match_id))
    except Exception as exc:
        return {"match_id": str(match_id), "ok": False,
                "code": "CLOUD_COLLECT_FAILED", "error": type(exc).__name__,
                "detail": str(exc)[:200], "elapsed": round(time.time()-started, 1)}
    packet = dict(packet)
    packet["collected_by"] = "hf_space_cloud_collector"
    packet["cloud_collection"] = {
        "space": os.getenv("SPACE_ID") or "football-data-hub-space",
        "collected_at": _now_utc().isoformat(),
        "direct_vip_egress": True,
        "elapsed_seconds": round(time.time()-started, 1),
    }
    packet["data_only_guard"] = {"model_call_performed": False,
                                 "analysis_performed": False,
                                 "final_pick_written": False,
                                 "bankroll_written": False}
    packet.pop("packet_sha256", None)
    packet["packet_sha256"] = hashlib.sha256(json.dumps(
        packet, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()
    return {"match_id": str(match_id), "ok": bool(packet.get("ok")),
            "code": packet.get("code"),
            "packet_sha256": packet["packet_sha256"],
            "captured_at": packet.get("captured_at"),
            "elapsed": round(time.time()-started, 1), "packet": packet}


def _future_match_ids(pool: dict, lead_minutes: int, horizon_minutes: int) -> list[str]:
    out = []
    now = datetime.now(TZ8)
    lo, hi = now + timedelta(minutes=lead_minutes), now + timedelta(minutes=horizon_minutes)
    for row in (pool.get("matches") or []):
        ko_raw = row.get("kickoff") or row.get("kickoff_local")
        mid = str(row.get("match_id") or "")
        if not (ko_raw and mid):
            continue
        try:
            ko = datetime.fromisoformat(str(ko_raw))
        except ValueError:
            continue
        if ko.tzinfo is None:
            ko = ko.replace(tzinfo=TZ8)
        if lo <= ko <= hi:
            out.append((ko, mid))
    return [m for _, m in sorted(out)]


def select_targets(pool: dict, lead_minutes: int, horizon_minutes: int,
                   limit: int | None) -> list[str]:
    ids = _future_match_ids(pool, lead_minutes, horizon_minutes)
    return ids[:limit] if limit else ids


def run_batch(match_ids: list[str], day: str, save_fn,
              workers: int = MAX_WORKERS) -> dict:
    with _LOCK:
        if _STATE["running"]:
            return {"ok": False, "code": "BATCH_ALREADY_RUNNING",
                    "state": public_state()}
        _STATE.update({"running": True, "started_at": _now_utc().isoformat(),
                       "day": day, "total": len(match_ids), "done": 0, "ok": 0,
                       "failed": 0, "current": None, "results": {},
                       "finished_at": None})

    def _work(mid: str):
        res = collect_one(mid)
        packet = res.pop("packet", None)
        if packet is not None:
            try:
                save_fn(day, mid, packet)
                res["persisted"] = True
            except Exception as exc:
                res["persisted"] = False
                res["persist_error"] = f"{type(exc).__name__}:{str(exc)[:120]}"
        return mid, res

    try:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = [pool.submit(_work, m) for m in match_ids]
            for fut in as_completed(futures):
                try:
                    mid, res = fut.result()
                except Exception as exc:
                    mid, res = "unknown", {"ok": False, "error": type(exc).__name__}
                with _LOCK:
                    _STATE["results"][mid] = res
                    _STATE["done"] += 1
                    _STATE["current"] = mid
                    if res.get("ok") and res.get("persisted"):
                        _STATE["ok"] += 1
                    else:
                        _STATE["failed"] += 1
    finally:
        with _LOCK:
            _STATE["running"] = False
            _STATE["finished_at"] = _now_utc().isoformat()
    return {"ok": True, "state": public_state()}


def public_state() -> dict:
    with _LOCK:
        s = dict(_STATE)
    results = s.pop("results", {})
    s["ready_match_ids"] = sorted(k for k, v in results.items()
                                  if v.get("ok") and v.get("persisted"))
    s["failed_detail"] = {k: {kk: vv for kk, vv in v.items() if kk != "packet"}
                          for k, v in results.items()
                          if not (v.get("ok") and v.get("persisted"))}
    return s

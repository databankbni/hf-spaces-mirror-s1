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


def _canonical_digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode()).hexdigest()


# Optional display aliases accelerate common JC short names. Matching no longer
# requires exact equality: after normalization, containment / high character
# overlap can confirm the same club. Keep aliases narrow; fuzzy rules do the rest.
_TEAM_IDENTITY_ALIASES = {
    # Brommapojkarna: 竞彩 short board name vs Titan full transliteration
    "布鲁马波": "布洛马波卡纳",
    "布洛马波卡纳": "布洛马波卡纳",
    "庞马普卡纳": "布洛马波卡纳",
    "龐馬普卡納": "布洛马波卡纳",
    # Västerås / Djurgården (瑞典超)
    "韦斯特罗": "瓦斯特拉斯",
    "瓦斯特拉斯": "瓦斯特拉斯",
    "佐加顿斯": "尤尔加登",
    "尤尔加登": "尤尔加登",
    # C.D. Nacional (葡超 short board name)
    "葡国民": "葡萄牙国民",
    "葡萄牙国民": "葡萄牙国民",
    "阿拉木图": "阿拉木图凯拉特",
    "阿拉木图凯拉特": "阿拉木图凯拉特",
    "索列夫": "索非亚列夫斯基",
    "索非亚列夫斯基": "索非亚列夫斯基",
    "圣吉联合": "圣吉罗斯",
    "圣吉罗斯": "圣吉罗斯",
    "巴竞技": "巴拉纳竞技",
    "巴拉纳竞技": "巴拉纳竞技",
    "哈尔姆斯": "哈尔姆斯塔德",
    "哈尔姆斯塔德": "哈尔姆斯塔德",
    "盖斯": "哥德堡盖斯",
    "哥德堡盖斯": "哥德堡盖斯",
    "厄格里特": "奥尔格里特",
    "奥尔格里特": "奥尔格里特",
    "克里斯蒂": "克里斯蒂安松",
    "克里斯蒂安松": "克里斯蒂安松",
    "AC奥卢": "奥卢",
    "奥卢": "奥卢",
    "国际图尔": "图尔库国际",
    "图尔库国际": "图尔库国际",
    "库奥皮奥": "古比斯",
    "古比斯": "古比斯",
    "TPS图尔": "TPS土尔库",
    "TPS土尔库": "TPS土尔库",
    "鹿斯巴达": "鹿特丹斯巴达",
    "鹿特丹斯巴达": "鹿特丹斯巴达",
    "阿尔维卡": "艾华卡",
    "艾华卡": "艾华卡",
    "马里迪莫": "马里迪莫",
    "卡萨皮亚": "卡萨比亚",
    "卡萨比亚": "卡萨比亚",
    "摩雷伦斯": "摩里伦斯",
    "摩里伦斯": "摩里伦斯",
    # Al-Hazem: verified same-match JC/Titan names for match 3046931.
    "拉斯决心": "哈森姆",
    "哈森姆": "哈森姆",
    # Clube do Remo: JC short 里莫 vs Titan 瑞模贝雷 (match 2910852).
    "里莫": "瑞模贝雷",
    "瑞模贝雷": "瑞模贝雷",
}


def _identity_norm(value) -> str:
    text = "".join(str(value or "").split()).replace("&nbsp;", "")
    text = __import__("re").sub(r"^\d{4}-\d{4}赛季", "", text)
    text = __import__("re").sub(r"\[[^\]]*\d+[^\]]*\]", "", text)
    text = __import__("re").sub(r"\([^)]*\d+[^)]*\)", "", text)
    # Titan and cp.titan007.com may place the Chinese club marker on opposite
    # boundaries (``FC安养`` vs ``安养FC``).  Normalize only a boundary marker;
    # keep internal FC and all raw identity fields unchanged.
    if text.startswith("FC") and len(text) > 2:
        text = text[2:]
    if text.endswith("FC") and len(text) > 2:
        text = text[:-2]
    return _TEAM_IDENTITY_ALIASES.get(text, text)


def _char_overlap_ratio(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    from collections import Counter
    a, b = Counter(left), Counter(right)
    shared = sum(min(a[ch], b[ch]) for ch in a)
    return shared / max(len(left), len(right))


def _identity_same_team(left, right) -> bool:
    """Confirm same club after rank/FC strip; fuzzy, not exact-string only."""
    a, b = _identity_norm(left), _identity_norm(right)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) >= 2 and short in long:
        return True
    if len(short) >= 2 and _char_overlap_ratio(a, b) >= 0.55:
        return True
    if len(short) >= 3 and _char_overlap_ratio(a, b) >= 0.45:
        return True
    return False


def _identity_same_league(left, right) -> bool:
    a, b = _identity_norm(left), _identity_norm(right)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 2 and short in long


def _bind_jingcai_admission(packet: dict, match_id: str,
                            admission: dict | None) -> tuple[dict | None, dict]:
    """Bind caller-verified JC admission before the cloud packet is hashed."""
    if not isinstance(admission, dict):
        return None, {"status": "ADMISSION_MISSING", "match_id": str(match_id)}
    claimed = str(admission.get("admission_sha256") or "")
    actual = _canonical_digest({k: v for k, v in admission.items()
                                if k != "admission_sha256"})
    identity = packet.get("identity") if isinstance(packet.get("identity"), dict) else {}
    checks = {
        "hash": bool(claimed) and claimed == actual,
        "scope": admission.get("scope") == "JINGCAI_ON_SALE",
        "source": admission.get("source") == "cp.titan007.com:竞彩足球:cansale=true",
        "match_id": str(admission.get("match_id")) == str(match_id),
        "titan_match_id": str(admission.get("titan_match_id")) == str(match_id),
        "jc_no": bool(admission.get("jc_no")),
        "on_sale": admission.get("cansale") is True and admission.get("sale_status") == "ON_SALE",
        "home": _identity_same_team(identity.get("home"), admission.get("home")),
        "away": _identity_same_team(identity.get("away"), admission.get("away")),
        "league": _identity_same_league(identity.get("league"), admission.get("league")),
    }
    hard_keys = ("hash", "scope", "source", "match_id", "titan_match_id",
                 "jc_no", "on_sale", "league")
    valid = all(checks[key] for key in hard_keys)
    team_name_warning = not (checks["home"] and checks["away"])
    receipt = {"status": "ADMISSION_VALID" if valid else "ADMISSION_INVALID",
               "match_id": str(match_id), "checks": checks,
               "team_name_warning": team_name_warning,
               "team_name_status": "DIAGNOSTIC_MISMATCH" if team_name_warning else "MATCHED",
               "admission_sha256": claimed}
    if not valid:
        return None, receipt
    bound = {**packet, "jingcai_admission": admission,
             "jingcai_admission_receipt": receipt,
             "admission_bound_by": "hf_space_cloud_collector"}
    # This is the admission-bound source packet hash.  Market evidence is built
    # from this exact packet next; collect_one() then computes a final hash after
    # evidence and cloud metadata are present.
    bound.pop("packet_sha256", None)
    bound["packet_sha256"] = _canonical_digest(bound)
    return bound, receipt


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _collector():
    import hermes_hf_client as client
    return client


def collect_one(match_id: str, admission: dict | None = None) -> dict:
    client = _collector()
    started = time.time()
    if not isinstance(admission, dict):
        return {"match_id": str(match_id), "ok": False,
                "code": "JINGCAI_ADMISSION_REJECTED",
                "admission_receipt": {"status": "ADMISSION_MISSING",
                                      "match_id": str(match_id)},
                "elapsed": round(time.time()-started, 1)}
    try:
        packet = client.live_packet(str(match_id))
    except Exception as exc:
        return {"match_id": str(match_id), "ok": False,
                "code": "CLOUD_COLLECT_FAILED", "error": type(exc).__name__,
                "detail": str(exc)[:200], "elapsed": round(time.time()-started, 1)}
    packet = dict(packet)
    # The Space-local snapshot path is not portable to Hermes and must not enter
    # the distributed packet provenance. Raw payload hashes remain in the
    # market evidence; the final packet must be independently read-backable.
    packet.pop("snapshot_path", None)
    packet, admission_receipt = _bind_jingcai_admission(
        packet, str(match_id), admission)
    if packet is None:
        return {"match_id": str(match_id), "ok": False,
                "code": "JINGCAI_ADMISSION_REJECTED",
                "admission_receipt": admission_receipt,
                "elapsed": round(time.time()-started, 1)}

    # The admission-bound hash is the immutable source hash for the portable
    # market evidence. The final packet hash is computed only after the
    # distribution metadata, evidence, and data-only guard are present.
    source_packet_sha = str(packet.get("packet_sha256") or "")
    packet["source_packet_sha256"] = source_packet_sha
    packet["origin_source_mode"] = "local_live_packet"
    packet["source_mode"] = "hf_remote_packet"
    packet["remote_packet_found"] = True
    packet["freshness_contract"] = {
        **(packet.get("freshness_contract") or {}),
        "origin_source_mode": "local_live_packet",
        "remote_packet_found": True,
        "distribution_source": "hf_dataset",
        "source_mode": "hf_remote_packet",
    }
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
                                 "bankroll_written": False,
                                 "telegram_sent": False}
    try:
        evidence = client.build_market_evidence(packet)
    except Exception as exc:
        return {"match_id": str(match_id), "ok": False,
                "code": "MARKET_EVIDENCE_BUILD_FAILED",
                "error": type(exc).__name__,
                "elapsed": round(time.time()-started, 1)}
    if not client._market_evidence_valid(
            evidence, expected_match_id=str(match_id),
            expected_source_packet_sha=source_packet_sha):
        return {"match_id": str(match_id), "ok": False,
                "code": "MARKET_EVIDENCE_INVALID",
                "market_evidence": {k: evidence.get(k) for k in
                                     ("match_id", "source_packet_sha256",
                                      "integrity_passed", "invalid_records")},
                "elapsed": round(time.time()-started, 1)}
    packet["market_evidence"] = evidence
    packet.pop("packet_sha256", None)
    packet["packet_sha256"] = _canonical_digest(packet)
    return {"match_id": str(match_id), "ok": bool(packet.get("ok")),
            "code": packet.get("code"),
            "packet_sha256": packet["packet_sha256"],
            "source_packet_sha256": source_packet_sha,
            "market_evidence_sha256": evidence.get("market_evidence_sha256"),
            "jingcai_admission_sha256": admission.get("admission_sha256"),
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
              workers: int = MAX_WORKERS,
              admissions: dict[str, dict] | None = None) -> dict:
    with _LOCK:
        if _STATE["running"]:
            return {"ok": False, "code": "BATCH_ALREADY_RUNNING",
                    "state": public_state()}
        _STATE.update({"running": True, "started_at": _now_utc().isoformat(),
                       "day": day, "total": len(match_ids), "done": 0, "ok": 0,
                       "failed": 0, "current": None, "results": {},
                       "finished_at": None})

    def _work(mid: str):
        res = collect_one(mid, (admissions or {}).get(str(mid)))
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

"""사용 통계 대시보드 — HF Dataset logs/**/*.json 집계.

  /logs/stats              HTML 대시보드
  /api/logs/stats          집계 JSON
  /logs/user/{username}    사용자별 생성 갤러리
  /api/logs/user/{username}
  /logs/asset/{path}       private dataset 이미지 프록시
"""
from __future__ import annotations

import datetime
import glob as _glob
import json
import os
import re
import time as _time
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

HF_TOKEN = os.environ.get("HF_TOKEN", "")
HF_DATASET_REPO = os.environ.get("HF_DATASET_REPO", "")

_STATS_CACHE: Dict[str, Any] = {"records": None, "loaded_at": 0.0}
_DSINDEX_CACHE: Dict[str, Any] = {"index": None, "loaded_at": 0.0}
_STATS_TTL_SEC = 60
_TS_RE = re.compile(r"(\d{8}_\d{6}_\d{3})")
_ASSET_PREFIXES = ("images/", "thumbs/", "inputs/product/", "inputs/persona/")
_STYLE_CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{4,24}$")
_STYLE_CODE_SKIP = frozenset({
    "product", "sub", "sub_product", "persona", "preset", "fashion", "thumb", "image",
    "design", "ghost", "model", "front", "back", "side",
})


def _hub_creds():
    return (
        os.environ.get("HF_TOKEN", "") or HF_TOKEN,
        os.environ.get("HF_DATASET_REPO", "") or HF_DATASET_REPO,
    )


def _load_log_records(force: bool = False) -> List[dict]:
    now = _time.time()
    cached = _STATS_CACHE.get("records")
    if (not force) and cached is not None and (now - _STATS_CACHE["loaded_at"] < _STATS_TTL_SEC):
        return cached

    records: List[dict] = []
    token, repo = _hub_creds()
    if not token or not repo:
        _STATS_CACHE.update(records=records, loaded_at=now)
        return records

    try:
        from huggingface_hub import snapshot_download
        local_dir = snapshot_download(
            repo_id=repo,
            repo_type="dataset",
            allow_patterns=["logs/**/*.json"],
            token=token,
        )
        for fp in _glob.glob(os.path.join(local_dir, "logs", "**", "*.json"), recursive=True):
            try:
                with open(fp, encoding="utf-8") as f:
                    rec = json.load(f)
                if isinstance(rec, dict):
                    records.append(rec)
            except Exception:
                continue
    except Exception as e:
        print(f"[STATS] 로그 로드 실패: {e}")

    records.sort(key=lambda r: str(r.get("ts") or ""))
    _STATS_CACHE.update(records=records, loaded_at=now)
    return records


def _fmt_ts(ts: str) -> str:
    if not ts or len(ts) < 13:
        return ts or ""
    try:
        return f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}"
    except Exception:
        return ts


def _fmt_day(day: str) -> str:
    return f"{day[0:4]}-{day[4:6]}-{day[6:8]}" if len(day) == 8 else day


def _rec_day(rec: dict) -> str:
    ts = str(rec.get("ts") or "")
    if len(ts) >= 8 and ts[:8].isdigit():
        return ts[:8]
    tsmp = str(rec.get("timestamp") or "")
    return tsmp[:10].replace("-", "") if tsmp else ""


def _user_key(rec: dict) -> str:
    return (rec.get("user_username") or rec.get("user_email") or "anonymous").strip() or "anonymous"


def extract_style_code(filename: Optional[str]) -> Optional[str]:
    """원본 업로드 파일명에서 스타일코드 추출. 예: CGMW0197M_00.jpg → CGMW0197M"""
    if not filename or not isinstance(filename, str):
        return None
    base = os.path.basename(filename.replace("\\", "/")).strip()
    if not base:
        return None
    stem = os.path.splitext(base)[0]
    token = stem.split("_")[0].strip()
    if not token or token.lower() in _STYLE_CODE_SKIP:
        return None
    if token.lower().startswith(("product", "preset", "persona", "sub", "design", "image")):
        return None
    if not _STYLE_CODE_RE.match(token):
        return None
    return token.upper()


def rec_product_filenames(rec: dict) -> List[str]:
    names: List[str] = []
    for key in (
        "product_image_filenames", "product_input_filenames",
        "design_image_filenames", "design_input_filenames",
        "sub_product_image_filenames", "sub_product_input_filenames",
    ):
        vals = rec.get(key) or []
        if not isinstance(vals, list):
            continue
        for v in vals:
            if isinstance(v, str) and v.strip():
                names.append(v.strip())
    for key in ("product_input_paths", "design_input_paths", "sub_product_input_paths"):
        vals = rec.get(key) or []
        if not isinstance(vals, list):
            continue
        for v in vals:
            if isinstance(v, str) and v.strip():
                names.append(os.path.basename(v.strip()))
    seen = set()
    out = []
    for n in names:
        k = n.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(n)
    return out


def _build_stats_payload(date_from: str = "", date_to: str = "") -> dict:
    records = _load_log_records()
    df = (date_from or "").replace("-", "")
    dt = (date_to or "").replace("-", "")

    users: Dict[str, dict] = {}
    daily: Dict[str, dict] = {}
    total_gen = total_edit = total_video = 0
    all_days = set()
    style_codes: Dict[str, dict] = {}
    recent_inputs: List[dict] = []

    for rec in records:
        day = _rec_day(rec)
        if not day:
            continue
        if df and day < df:
            continue
        if dt and day > dt:
            continue

        rec_type = rec.get("type") or "generated"
        is_edit = rec_type == "edited"
        is_video = rec_type == "video"
        uk = _user_key(rec)
        u = users.get(uk)
        if u is None:
            u = users[uk] = {
                "username": uk, "name": "", "email": "", "logged_in": False,
                "gen": 0, "edit": 0, "video": 0, "ref": 0, "bg": 0,
                "transform": 0, "original": 0,
                "shots": {}, "elapsed": [],
                "first": "", "last": "", "days": set(),
            }
        if rec.get("user_name"):
            u["name"] = rec["user_name"]
        if rec.get("user_email"):
            u["email"] = rec["user_email"]
        if rec.get("user_logged_in"):
            u["logged_in"] = True

        ts = str(rec.get("ts") or "")
        if ts:
            if not u["first"] or ts < u["first"]:
                u["first"] = ts
            if not u["last"] or ts > u["last"]:
                u["last"] = ts
        u["days"].add(day)
        all_days.add(day)

        d = daily.get(day) or daily.setdefault(day, {"day": day, "gen": 0, "edit": 0, "video": 0})
        shot = rec.get("shot_label") or "(미지정)"

        if is_edit:
            u["edit"] += 1
            d["edit"] += 1
            total_edit += 1
            shot = rec.get("shot_label") or "편집"
        elif is_video:
            u["video"] += 1
            d["video"] = d.get("video", 0) + 1
            total_video += 1
            u["gen"] += 1
            d["gen"] += 1
            total_gen += 1
            shot = rec.get("shot_label") or "스판 영상"
            u["shots"][shot] = u["shots"].get(shot, 0) + 1
            es = rec.get("elapsed_sec")
            if isinstance(es, (int, float)):
                u["elapsed"].append(float(es))
        else:
            u["gen"] += 1
            d["gen"] += 1
            total_gen += 1
            shot = rec.get("shot_label") or "(미지정)"
            u["shots"][shot] = u["shots"].get(shot, 0) + 1
            if rec.get("has_reference"):
                u["ref"] += 1
            if rec.get("has_background"):
                u["bg"] += 1
            if rec.get("mode") == "TRANSFORM":
                u["transform"] += 1
            elif rec.get("mode") == "ORIGINAL":
                u["original"] += 1
            es = rec.get("elapsed_sec")
            if isinstance(es, (int, float)):
                u["elapsed"].append(float(es))

        if not is_edit:
            filenames = rec_product_filenames(rec)
            codes_in_rec = []
            for fn in filenames:
                code = extract_style_code(fn)
                if not code:
                    continue
                codes_in_rec.append(code)
                sc = style_codes.get(code)
                if sc is None:
                    sc = style_codes[code] = {
                        "style_code": code,
                        "gen": 0,
                        "filenames": set(),
                        "users": set(),
                        "last": "",
                    }
                sc["filenames"].add(fn)
                sc["users"].add(uk)
                if ts and (not sc["last"] or ts > sc["last"]):
                    sc["last"] = ts
            for code in set(codes_in_rec):
                style_codes[code]["gen"] += 1

            if filenames:
                recent_inputs.append({
                    "ts": ts,
                    "time": _fmt_ts(ts),
                    "username": uk,
                    "name": rec.get("user_name") or uk,
                    "shot": shot,
                    "filenames": filenames,
                    "style_codes": sorted(set(codes_in_rec)),
                })

    user_list = []
    for u in users.values():
        total = u["gen"] + u["edit"]
        top_shot = max(u["shots"].items(), key=lambda kv: kv[1])[0] if u["shots"] else ""
        avg_elapsed = round(sum(u["elapsed"]) / len(u["elapsed"]), 1) if u["elapsed"] else None
        ref_rate = round(u["ref"] / u["gen"] * 100) if u["gen"] else 0
        user_list.append({
            "username": u["username"], "name": u["name"], "email": u["email"],
            "logged_in": u["logged_in"],
            "gen": u["gen"], "edit": u["edit"], "video": u.get("video", 0), "total": total,
            "active_days": len(u["days"]),
            "top_shot": top_shot, "shots": u["shots"],
            "transform": u["transform"], "original": u["original"],
            "ref_rate": ref_rate, "avg_elapsed": avg_elapsed,
            "first": _fmt_ts(u["first"]), "last": _fmt_ts(u["last"]),
            "last_raw": u["last"],
        })
    user_list.sort(key=lambda x: x["total"], reverse=True)
    daily_list = [daily[d] for d in sorted(daily.keys())]

    style_list = []
    for sc in style_codes.values():
        style_list.append({
            "style_code": sc["style_code"],
            "gen": sc["gen"],
            "users": len(sc["users"]),
            "filenames": sorted(sc["filenames"])[:8],
            "filename_count": len(sc["filenames"]),
            "last": _fmt_ts(sc["last"]),
            "last_raw": sc["last"],
        })
    style_list.sort(key=lambda x: (-x["gen"], x["style_code"]))

    recent_inputs.sort(key=lambda x: x.get("ts") or "", reverse=True)
    recent_inputs = recent_inputs[:80]

    return {
        "summary": {
            "users": len(user_list), "gen": total_gen, "edit": total_edit,
            "video": total_video,
            "total": total_gen + total_edit, "days": len(all_days),
            "style_codes": len(style_list),
            "first_day": _fmt_day(min(all_days)) if all_days else "",
            "last_day": _fmt_day(max(all_days)) if all_days else "",
            "configured": bool(_hub_creds()[0] and _hub_creds()[1]),
            "repo": (_hub_creds()[1] or "(미설정)"),
            "loaded_at": datetime.datetime.fromtimestamp(_STATS_CACHE["loaded_at"]).strftime("%Y-%m-%d %H:%M:%S") if _STATS_CACHE["loaded_at"] else "",
        },
        "users": user_list,
        "daily": daily_list,
        "style_codes": style_list,
        "recent_inputs": recent_inputs,
        "filter": {"from": date_from, "to": date_to},
    }


def _render_stats_html(payload: dict) -> str:
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return _STATS_HTML_TEMPLATE.replace("__DATA__", data_json)


def _load_dataset_index(force: bool = False) -> Dict[str, dict]:
    now = _time.time()
    cached = _DSINDEX_CACHE.get("index")
    if (not force) and cached is not None and (now - _DSINDEX_CACHE["loaded_at"] < _STATS_TTL_SEC):
        return cached

    index: Dict[str, dict] = {}
    token, repo = _hub_creds()
    if not token or not repo:
        _DSINDEX_CACHE.update(index=index, loaded_at=now)
        return index
    try:
        from huggingface_hub import HfApi
        files = HfApi(token=token).list_repo_files(repo_id=repo, repo_type="dataset")
    except Exception as e:
        print(f"[STATS] list_repo_files 실패: {e}")
        files = []

    for fp in files:
        m = _TS_RE.search(fp)
        if not m:
            continue
        ts = m.group(1)
        slot = index.setdefault(ts, {"output": None, "thumb": None, "persona": None, "products": []})
        if fp.startswith("images/"):
            slot["output"] = fp
        elif fp.startswith("thumbs/"):
            slot["thumb"] = fp
        elif fp.startswith("inputs/persona/"):
            slot["persona"] = fp
        elif fp.startswith("inputs/product/"):
            slot["products"].append(fp)
    for slot in index.values():
        slot["products"].sort()

    _DSINDEX_CACHE.update(index=index, loaded_at=now)
    return index


def _asset_url(path: Optional[str]) -> Optional[str]:
    return ("/logs/asset/" + path) if path else None


def _build_user_detail(username: str, date_from: str = "", date_to: str = "", limit: int = 200) -> dict:
    records = _load_log_records()
    index = _load_dataset_index()
    df = (date_from or "").replace("-", "")
    dt = (date_to or "").replace("-", "")

    items = []
    name = email = ""
    logged_in = False
    gen = edit = 0
    elapsed_all = []

    for rec in records:
        if _user_key(rec) != username:
            continue
        day = _rec_day(rec)
        if df and day < df:
            continue
        if dt and day > dt:
            continue

        ts = str(rec.get("ts") or "")
        assets = index.get(ts, {})
        rec_type = rec.get("type") or "generated"
        is_edit = rec_type == "edited"
        is_video = rec_type == "video"
        if rec.get("user_name"):
            name = rec["user_name"]
        if rec.get("user_email"):
            email = rec["user_email"]
        if rec.get("user_logged_in"):
            logged_in = True

        es = rec.get("elapsed_sec")
        filenames = rec_product_filenames(rec)
        style_codes = sorted({c for c in (extract_style_code(fn) for fn in filenames) if c})

        kind = "편집" if is_edit else ("영상" if is_video else "생성")
        items.append({
            "ts": ts, "time": _fmt_ts(ts), "day": day,
            "kind": kind, "is_edit": is_edit, "is_video": is_video,
            "shot": rec.get("shot_label") or ("스판 영상" if is_video else ""),
            "mode": rec.get("mode") or "",
            "model_face": rec.get("model_face") or "",
            "body_type": rec.get("body_type") or "",
            "model_preset": rec.get("model_preset") or "",
            "elapsed": es if isinstance(es, (int, float)) else None,
            "has_reference": bool(rec.get("has_reference")),
            "has_background": bool(rec.get("has_background")),
            "custom_prompt": ((rec.get("edit_instruction") if is_edit else rec.get("custom_prompt")) or ""),
            "full_prompt": rec.get("prompt") or "",
            "filenames": filenames,
            "style_codes": style_codes,
            "product_cats": [],
            "output_url": _asset_url(assets.get("output") or assets.get("thumb")),
            "thumb_url": _asset_url(assets.get("thumb") or assets.get("output")),
            "persona_url": _asset_url(assets.get("persona")),
            "product_urls": [_asset_url(p) for p in (assets.get("products") or [])],
        })
        if is_edit:
            edit += 1
        else:
            gen += 1
            if isinstance(es, (int, float)):
                elapsed_all.append(float(es))

    items.sort(key=lambda x: x["ts"], reverse=True)
    truncated = len(items) > limit
    items = items[:limit]
    avg = round(sum(elapsed_all) / len(elapsed_all), 1) if elapsed_all else None

    return {
        "user": {"username": username, "name": name, "email": email, "logged_in": logged_in},
        "summary": {
            "gen": gen, "edit": edit, "total": gen + edit, "avg_elapsed": avg,
            "shown": len(items), "truncated": truncated, "limit": limit,
            "configured": bool(_hub_creds()[0] and _hub_creds()[1]),
        },
        "items": items,
        "filter": {"from": date_from, "to": date_to},
    }


def _render_user_html(payload: dict) -> str:
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return _USER_HTML_TEMPLATE.replace("__DATA__", data_json)


def register_usage_stats_routes(app: FastAPI) -> None:
    @app.get("/api/logs/stats")
    def api_logs_stats(request: Request):
        qp = request.query_params
        if qp.get("refresh"):
            _load_log_records(force=True)
        return JSONResponse(_build_stats_payload(qp.get("from", ""), qp.get("to", "")))

    @app.get("/logs/stats", response_class=HTMLResponse)
    def logs_stats_page(request: Request):
        qp = request.query_params
        if qp.get("refresh"):
            _load_log_records(force=True)
        payload = _build_stats_payload(qp.get("from", ""), qp.get("to", ""))
        return HTMLResponse(_render_stats_html(payload))

    @app.get("/api/logs/user/{username}")
    def api_logs_user(request: Request, username: str):
        qp = request.query_params
        if qp.get("refresh"):
            _load_log_records(force=True)
            _load_dataset_index(force=True)
        return JSONResponse(_build_user_detail(unquote(username), qp.get("from", ""), qp.get("to", "")))

    @app.get("/logs/user/{username}", response_class=HTMLResponse)
    def logs_user_page(request: Request, username: str):
        qp = request.query_params
        if qp.get("refresh"):
            _load_log_records(force=True)
            _load_dataset_index(force=True)
        payload = _build_user_detail(unquote(username), qp.get("from", ""), qp.get("to", ""))
        return HTMLResponse(_render_user_html(payload))

    @app.get("/logs/asset/{path:path}")
    def logs_asset(path: str):
        decoded = unquote(path)
        if not decoded.startswith(_ASSET_PREFIXES) or ".." in decoded:
            raise HTTPException(status_code=404, detail="not allowed")
        token, repo = _hub_creds()
        if not token or not repo:
            raise HTTPException(status_code=404, detail="dataset not configured")
        url = f"https://huggingface.co/datasets/{repo}/resolve/main/{quote(decoded, safe='/')}"
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                content = resp.read()
                media = resp.headers.get("Content-Type", "application/octet-stream")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"fetch failed: {e}")
        return Response(
            content=content,
            media_type=media,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    print("[STATS] /logs/stats dashboard routes registered")


_STATS_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>에블린 AI 룩북 · 사용 통계</title>
<link rel="stylesheet" as="style" crossorigin href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css"/>
<style>
  :root{
    --bg:#f7f8fa; --panel:#ffffff; --border:#e6e8ec; --ink:#1a202c;
    --muted:#6b7280; --accent:#2563eb; --accent-soft:#eff4ff;
    --edit:#0d9488; --warn:#d97706; --track:#eef1f5;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font-family:'Pretendard',-apple-system,BlinkMacSystemFont,system-ui,sans-serif;
    -webkit-font-smoothing:antialiased;}
  a{color:inherit}
  .wrap{max-width:1180px;margin:0 auto;padding:28px 20px 60px}
  header{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:6px}
  h1{font-size:22px;font-weight:800;margin:0;letter-spacing:-.02em}
  .sub{color:var(--muted);font-size:13px;margin-top:4px}
  .sub code{background:#eef1f5;padding:1px 6px;border-radius:5px;font-size:12px}
  .toolbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
  .toolbar input[type=date]{font-family:inherit;border:1px solid var(--border);border-radius:8px;
    padding:7px 9px;font-size:13px;background:#fff;color:var(--ink)}
  .btn{border:1px solid var(--border);background:#fff;border-radius:8px;padding:8px 13px;
    font-size:13px;font-weight:600;cursor:pointer;color:var(--ink);text-decoration:none;
    display:inline-flex;align-items:center;gap:6px;transition:.15s}
  .btn:hover{border-color:var(--accent);color:var(--accent)}
  .btn.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
  .btn.primary:hover{filter:brightness(1.05);color:#fff}

  .cards{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin:22px 0}
  @media(max-width:960px){.cards{grid-template-columns:repeat(3,1fr)}}
  @media(max-width:560px){.cards{grid-template-columns:repeat(2,1fr)}}
  .card{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:16px 18px}
  .card .k{font-size:12px;color:var(--muted);font-weight:600;letter-spacing:.01em}
  .card .v{font-size:26px;font-weight:800;margin-top:6px;letter-spacing:-.02em}
  .card .v small{font-size:13px;font-weight:600;color:var(--muted)}

  .panel{background:var(--panel);border:1px solid var(--border);border-radius:16px;padding:18px 20px;margin-bottom:18px}
  .panel h2{font-size:14px;font-weight:700;margin:0 0 14px;display:flex;align-items:center;gap:8px}
  .panel h2 .tag{font-size:11px;font-weight:600;color:var(--muted)}
  .fn{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:11.5px;
    background:#f3f5f8;padding:2px 7px;border-radius:6px;display:inline-block;margin:1px 3px 1px 0;
    max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;vertical-align:middle}
  .codepill{display:inline-block;font-size:12px;font-weight:700;letter-spacing:.02em;
    padding:3px 9px;border-radius:8px;background:#111827;color:#fff}

  /* daily chart */
  .chart{display:flex;align-items:flex-end;gap:6px;height:160px;overflow-x:auto;padding-bottom:6px}
  .col{display:flex;flex-direction:column;align-items:center;gap:6px;min-width:26px;flex:0 0 auto}
  .bar{width:18px;border-radius:5px 5px 0 0;background:var(--track);position:relative;display:flex;flex-direction:column-reverse;overflow:hidden}
  .seg-gen{background:var(--accent)}
  .seg-edit{background:var(--edit)}
  .col .lbl{font-size:10px;color:var(--muted);white-space:nowrap;transform:rotate(-45deg);transform-origin:center;height:30px;margin-top:4px}
  .legend{display:flex;gap:16px;font-size:12px;color:var(--muted);margin-top:6px}
  .legend span{display:inline-flex;align-items:center;gap:6px}
  .dot{width:10px;height:10px;border-radius:3px;display:inline-block}

  table{width:100%;border-collapse:collapse;font-size:13px}
  thead th{text-align:left;font-weight:600;color:var(--muted);font-size:12px;
    padding:10px 10px;border-bottom:1px solid var(--border);white-space:nowrap;cursor:pointer;user-select:none}
  thead th.num{text-align:right}
  thead th:hover{color:var(--accent)}
  thead th .arrow{opacity:.4;font-size:10px;margin-left:3px}
  thead th.active .arrow{opacity:1;color:var(--accent)}
  tbody td{padding:11px 10px;border-bottom:1px solid #f1f3f6;vertical-align:middle}
  tbody tr:hover{background:#fafbfc}
  td.num{text-align:right;font-variant-numeric:tabular-nums}
  .u-name{font-weight:700}
  .u-id{color:var(--muted);font-size:11.5px;margin-top:1px}
  a.ulink{text-decoration:none;color:inherit;display:inline-block}
  a.ulink:hover .u-name{color:var(--accent);text-decoration:underline}
  .u-name .chev{font-size:11px;color:var(--accent);margin-left:5px;opacity:.7}
  .pill{display:inline-block;font-size:11px;font-weight:600;padding:2px 8px;border-radius:999px;background:var(--accent-soft);color:var(--accent)}
  .pill.gray{background:#f1f3f6;color:var(--muted)}
  .pill.anon{background:#fdf2f2;color:#b91c1c}
  .barmini{height:6px;border-radius:4px;background:var(--track);overflow:hidden;width:60px;display:inline-block;vertical-align:middle;margin-right:6px}
  .barmini > i{display:block;height:100%;background:var(--accent)}
  .empty{text-align:center;color:var(--muted);padding:40px 0;font-size:14px}
  .foot{color:var(--muted);font-size:12px;margin-top:18px;text-align:center}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>에블린 AI 룩북 · 사용 통계</h1>
      <div class="sub">데이터셋 <code id="repo"></code> · 마지막 갱신 <span id="loaded"></span></div>
    </div>
    <div class="toolbar">
      <input type="date" id="from"/>
      <span style="color:var(--muted)">~</span>
      <input type="date" id="to"/>
      <button class="btn primary" onclick="applyFilter()">기간 적용</button>
      <button class="btn" onclick="resetFilter()">전체</button>
      <a class="btn" id="refreshBtn" href="?refresh=1">↻ 새로고침</a>
    </div>
  </header>

  <div class="cards" id="cards"></div>

  <div class="panel">
    <h2>일자별 활동 <span class="tag" id="rangeTag"></span></h2>
    <div class="chart" id="chart"></div>
    <div class="legend">
      <span><i class="dot" style="background:var(--accent)"></i>생성</span>
      <span><i class="dot" style="background:var(--edit)"></i>편집</span>
    </div>
  </div>

  <div class="panel">
    <h2>스타일코드별 생성 <span class="tag">원본 파일명에서 추출 · 열 제목 클릭 정렬</span></h2>
    <div style="overflow-x:auto">
      <table id="styleTable">
        <thead>
          <tr>
            <th data-k="style_code" data-t="str" data-table="style">스타일코드<span class="arrow"></span></th>
            <th class="num active" data-k="gen" data-table="style">생성<span class="arrow">▼</span></th>
            <th class="num" data-k="users" data-table="style">사용자<span class="arrow"></span></th>
            <th data-k="filenames" data-t="str" data-table="style">원본 파일명 예시<span class="arrow"></span></th>
            <th data-k="last_raw" data-t="str" data-table="style">최근 생성<span class="arrow"></span></th>
          </tr>
        </thead>
        <tbody id="styleBody"></tbody>
      </table>
    </div>
    <div class="empty" id="styleEmpty" style="display:none">스타일코드를 추출할 원본 파일명 로그가 없습니다. (배포 이후 생성분부터 집계됩니다)</div>
  </div>

  <div class="panel">
    <h2>최근 생성 · 원본 파일명 <span class="tag">최대 80건</span></h2>
    <div style="overflow-x:auto">
      <table>
        <thead>
          <tr>
            <th>시각</th>
            <th>사용자</th>
            <th>샷</th>
            <th>스타일코드</th>
            <th>원본 파일명</th>
          </tr>
        </thead>
        <tbody id="recentBody"></tbody>
      </table>
    </div>
    <div class="empty" id="recentEmpty" style="display:none">원본 파일명이 기록된 최근 생성이 없습니다.</div>
  </div>

  <div class="panel">
    <h2>사용자별 사용 현황 <span class="tag">열 제목을 클릭하면 정렬됩니다</span></h2>
    <div style="overflow-x:auto">
      <table id="userTable">
        <thead>
          <tr>
            <th data-k="name" data-t="str" data-table="user">사용자<span class="arrow"></span></th>
            <th class="num" data-k="gen" data-table="user">생성<span class="arrow"></span></th>
            <th class="num" data-k="edit" data-table="user">편집<span class="arrow"></span></th>
            <th class="num active" data-k="total" data-table="user">합계<span class="arrow">▼</span></th>
            <th class="num" data-k="active_days" data-table="user">활동일<span class="arrow"></span></th>
            <th data-k="top_shot" data-t="str" data-table="user">주 사용 샷<span class="arrow"></span></th>
            <th class="num" data-k="ref_rate" data-table="user">레퍼런스율<span class="arrow"></span></th>
            <th class="num" data-k="avg_elapsed" data-table="user">평균 소요<span class="arrow"></span></th>
            <th data-k="last_raw" data-t="str" data-table="user">최근 활동<span class="arrow"></span></th>
          </tr>
        </thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>
    <div class="empty" id="empty" style="display:none">표시할 로그가 없습니다.</div>
  </div>

  <div class="foot" id="foot"></div>
</div>

<script>
const DATA = __DATA__;
let sortKey = "total", sortType = "num", sortDir = -1;
let styleSortKey = "gen", styleSortType = "num", styleSortDir = -1;

function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}

function renderCards(){
  const s = DATA.summary;
  const range = (s.first_day && s.last_day) ? (s.first_day + " ~ " + s.last_day) : "데이터 없음";
  document.getElementById("repo").textContent = s.repo;
  document.getElementById("loaded").textContent = s.loaded_at || "-";
  document.getElementById("rangeTag").textContent = range;
  const cards = [
    ["사용자", s.users, ""],
    ["총 생성", s.gen, "건"],
    ["총 편집", s.edit, "건"],
    ["스타일코드", s.style_codes || 0, "종"],
    ["활동 일수", s.days, "일"],
    ["기간", "", range],
  ];
  document.getElementById("cards").innerHTML = cards.map(([k,v,suf])=>{
    const val = (k==="기간") ? `<span style="font-size:14px;font-weight:700">${esc(suf)||"-"}</span>`
                             : `${Number(v).toLocaleString()}${suf?` <small>${suf}</small>`:""}`;
    return `<div class="card"><div class="k">${k}</div><div class="v">${val}</div></div>`;
  }).join("");
  if(!s.configured){
    document.getElementById("foot").innerHTML =
      "⚠️ HF_TOKEN / HF_DATASET_REPO 환경변수가 설정되지 않아 로그를 불러올 수 없습니다. (로컬 개발 환경)";
  }
}

function renderChart(){
  const daily = DATA.daily || [];
  const el = document.getElementById("chart");
  if(!daily.length){ el.innerHTML = '<div class="empty" style="width:100%">활동 기록이 없습니다.</div>'; return; }
  const max = Math.max(...daily.map(d=>d.gen+d.edit), 1);
  const H = 120;
  el.innerHTML = daily.map(d=>{
    const tot = d.gen+d.edit;
    const h = Math.round(tot/max*H);
    const gh = tot ? Math.round(d.gen/tot*h) : 0;
    const eh = h - gh;
    const day = d.day, lbl = day.slice(4,6)+"/"+day.slice(6,8);
    return `<div class="col" title="${day.slice(0,4)}-${day.slice(4,6)}-${day.slice(6,8)} · 생성 ${d.gen} / 편집 ${d.edit}">
      <div class="bar" style="height:${Math.max(h,3)}px">
        <div class="seg-edit" style="height:${eh}px"></div>
        <div class="seg-gen" style="height:${gh}px"></div>
      </div>
      <div class="lbl">${lbl}</div>
    </div>`;
  }).join("");
}

function renderTable(){
  const rows = [...DATA.users];
  rows.sort((a,b)=>{
    let x=a[sortKey], y=b[sortKey];
    if(sortType==="str"){ x=(x||"").toString().toLowerCase(); y=(y||"").toString().toLowerCase();
      return x<y?-1*sortDir:x>y?1*sortDir:0; }
    x = (x==null?-1:Number(x)); y = (y==null?-1:Number(y));
    return (x-y)*sortDir;
  });
  const tb = document.getElementById("tbody");
  const empty = document.getElementById("empty");
  if(!rows.length){ tb.innerHTML=""; empty.style.display="block"; return; }
  empty.style.display="none";
  const maxTotal = Math.max(...rows.map(r=>r.total),1);
  const f=DATA.filter||{}; const qs=[]; if(f.from)qs.push("from="+f.from); if(f.to)qs.push("to="+f.to);
  const dateQS = qs.length?("?"+qs.join("&")):"";
  tb.innerHTML = rows.map(u=>{
    const isAnon = u.username==="anonymous";
    const href = "/logs/user/"+encodeURIComponent(u.username)+dateQS;
    const inner = `<div class="u-name">${esc(u.name || u.username)}<span class="chev">›</span></div>`
      + (isAnon ? `<span class="pill anon">비로그인</span>`
                : `<div class="u-id">@${esc(u.username)}${u.email?` · ${esc(u.email)}`:""}</div>`);
    const nameCell = `<a class="ulink" href="${href}">${inner}</a>`;
    const totalBar = `<span class="barmini"><i style="width:${Math.round(u.total/maxTotal*100)}%"></i></span>`;
    const shot = u.top_shot ? `<span class="pill gray">${esc(u.top_shot)}</span>` : "-";
    const avg = (u.avg_elapsed==null) ? "-" : `${u.avg_elapsed}s`;
    return `<tr>
      <td>${nameCell}</td>
      <td class="num">${u.gen.toLocaleString()}</td>
      <td class="num">${u.edit.toLocaleString()}</td>
      <td class="num">${totalBar}<b>${u.total.toLocaleString()}</b></td>
      <td class="num">${u.active_days}</td>
      <td>${shot}</td>
      <td class="num">${u.ref_rate}%</td>
      <td class="num">${avg}</td>
      <td>${esc(u.last)}</td>
    </tr>`;
  }).join("");
}

function renderStyleTable(){
  const rows = [...(DATA.style_codes||[])];
  rows.sort((a,b)=>{
    let x=a[styleSortKey], y=b[styleSortKey];
    if(styleSortKey==="filenames"){
      x=(a.filenames&&a.filenames[0]||"").toLowerCase();
      y=(b.filenames&&b.filenames[0]||"").toLowerCase();
      return x<y?-1*styleSortDir:x>y?1*styleSortDir:0;
    }
    if(styleSortType==="str"){ x=(x||"").toString().toLowerCase(); y=(y||"").toString().toLowerCase();
      return x<y?-1*styleSortDir:x>y?1*styleSortDir:0; }
    x = (x==null?-1:Number(x)); y = (y==null?-1:Number(y));
    return (x-y)*styleSortDir;
  });
  const tb = document.getElementById("styleBody");
  const empty = document.getElementById("styleEmpty");
  if(!rows.length){ tb.innerHTML=""; empty.style.display="block"; return; }
  empty.style.display="none";
  const maxGen = Math.max(...rows.map(r=>r.gen),1);
  tb.innerHTML = rows.map(r=>{
    const bar = `<span class="barmini"><i style="width:${Math.round(r.gen/maxGen*100)}%"></i></span>`;
    const files = (r.filenames||[]).map(f=>`<span class="fn" title="${esc(f)}">${esc(f)}</span>`).join("");
    const more = (r.filename_count||0) > (r.filenames||[]).length
      ? `<span class="pill gray">+${r.filename_count - r.filenames.length}</span>` : "";
    return `<tr>
      <td><span class="codepill">${esc(r.style_code)}</span></td>
      <td class="num">${bar}<b>${r.gen.toLocaleString()}</b></td>
      <td class="num">${r.users}</td>
      <td>${files||"-"}${more}</td>
      <td>${esc(r.last)||"-"}</td>
    </tr>`;
  }).join("");
}

function renderRecentInputs(){
  const rows = DATA.recent_inputs || [];
  const tb = document.getElementById("recentBody");
  const empty = document.getElementById("recentEmpty");
  if(!rows.length){ tb.innerHTML=""; empty.style.display="block"; return; }
  empty.style.display="none";
  tb.innerHTML = rows.map(r=>{
    const codes = (r.style_codes||[]).map(c=>`<span class="codepill">${esc(c)}</span>`).join(" ") || "-";
    const files = (r.filenames||[]).map(f=>`<span class="fn" title="${esc(f)}">${esc(f)}</span>`).join("") || "-";
    return `<tr>
      <td>${esc(r.time)||"-"}</td>
      <td><div class="u-name">${esc(r.name||r.username)}</div><div class="u-id">@${esc(r.username)}</div></td>
      <td>${r.shot?`<span class="pill gray">${esc(r.shot)}</span>`:"-"}</td>
      <td>${codes}</td>
      <td>${files}</td>
    </tr>`;
  }).join("");
}

document.querySelectorAll("thead th[data-k]").forEach(th=>{
  th.addEventListener("click",()=>{
    const table = th.dataset.table || "user";
    const k = th.dataset.k, t = th.dataset.t==="str"?"str":"num";
    if(table==="style"){
      if(styleSortKey===k){ styleSortDir *= -1; } else { styleSortKey=k; styleSortType=t; styleSortDir = (t==="str")?1:-1; }
      document.querySelectorAll("#styleTable thead th").forEach(x=>{x.classList.remove("active"); const a=x.querySelector(".arrow"); if(a)a.textContent="";});
      th.classList.add("active");
      th.querySelector(".arrow").textContent = styleSortDir<0?"▼":"▲";
      renderStyleTable();
      return;
    }
    if(sortKey===k){ sortDir *= -1; } else { sortKey=k; sortType=t; sortDir = (t==="str")?1:-1; }
    document.querySelectorAll("#userTable thead th").forEach(x=>{x.classList.remove("active"); const a=x.querySelector(".arrow"); if(a)a.textContent="";});
    th.classList.add("active");
    th.querySelector(".arrow").textContent = sortDir<0?"▼":"▲";
    renderTable();
  });
});

function applyFilter(){
  const f=document.getElementById("from").value, t=document.getElementById("to").value;
  const p=new URLSearchParams();
  if(f)p.set("from",f); if(t)p.set("to",t);
  location.search = p.toString();
}
function resetFilter(){ location.search=""; }

(function init(){
  if(DATA.filter){
    if(DATA.filter.from) document.getElementById("from").value=DATA.filter.from;
    if(DATA.filter.to) document.getElementById("to").value=DATA.filter.to;
  }
  const q=new URLSearchParams(location.search);
  const keep=[]; if(q.get("from"))keep.push("from="+q.get("from")); if(q.get("to"))keep.push("to="+q.get("to"));
  document.getElementById("refreshBtn").href = "?refresh=1"+(keep.length?"&"+keep.join("&"):"");
  renderCards(); renderChart(); renderStyleTable(); renderRecentInputs(); renderTable();
})();
</script>
</body>
</html>"""


_USER_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>사용 상세 · 에블린 AI 룩북</title>
<link rel="stylesheet" as="style" crossorigin href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css"/>
<style>
  :root{--bg:#f7f8fa;--panel:#fff;--border:#e6e8ec;--ink:#1a202c;--muted:#6b7280;
        --accent:#2563eb;--accent-soft:#eff4ff;--edit:#0d9488;--warn:#d97706;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font-family:'Pretendard',-apple-system,BlinkMacSystemFont,system-ui,sans-serif;-webkit-font-smoothing:antialiased}
  a{color:inherit}
  .wrap{max-width:1180px;margin:0 auto;padding:24px 20px 60px}
  .back{display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:600;color:var(--muted);text-decoration:none;margin-bottom:14px}
  .back:hover{color:var(--accent)}
  header{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:18px}
  h1{font-size:21px;font-weight:800;margin:0;letter-spacing:-.02em}
  h1 .uid{font-size:13px;font-weight:600;color:var(--muted);margin-left:8px}
  .meta-sum{display:flex;gap:18px;margin-top:8px;font-size:13px;color:var(--muted);flex-wrap:wrap}
  .meta-sum b{color:var(--ink);font-weight:700}
  .btn{border:1px solid var(--border);background:#fff;border-radius:8px;padding:7px 12px;font-size:13px;font-weight:600;cursor:pointer;color:var(--ink);text-decoration:none}
  .btn:hover{border-color:var(--accent);color:var(--accent)}

  .grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}
  @media(max-width:820px){.grid{grid-template-columns:1fr}}
  .card{background:var(--panel);border:1px solid var(--border);border-radius:16px;overflow:hidden;display:flex;flex-direction:column}
  .card-top{display:flex;gap:14px;padding:14px}
  .outwrap{flex:0 0 168px;width:168px}
  .outwrap a{display:block;border-radius:10px;overflow:hidden;border:1px solid var(--border);background:#f0f2f5;aspect-ratio:3/4}
  .outwrap img{width:100%;height:100%;object-fit:cover;display:block}
  .card-body{flex:1;min-width:0}
  .badges{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
  .badge{font-size:11px;font-weight:700;padding:3px 9px;border-radius:999px;background:var(--accent-soft);color:var(--accent)}
  .badge.edit{background:#e6fffb;color:var(--edit)}
  .badge.gray{background:#f1f3f6;color:var(--muted)}
  .badge.time{background:#fff7ed;color:var(--warn)}
  .when{font-size:12px;color:var(--muted);margin-bottom:10px}
  .inputs{margin-top:6px}
  .inputs .lbl{font-size:11px;font-weight:700;color:var(--muted);margin-bottom:5px}
  .thumbs{display:flex;gap:7px;flex-wrap:wrap}
  .thumbs .t{position:relative;width:52px;height:64px;border-radius:7px;overflow:hidden;border:1px solid var(--border);background:#f0f2f5}
  .thumbs .t img{width:100%;height:100%;object-fit:cover;display:block}
  .thumbs .t .tag{position:absolute;left:0;bottom:0;right:0;font-size:8.5px;text-align:center;background:rgba(0,0,0,.55);color:#fff;padding:1px 0}
  .noimg{font-size:12px;color:#aab;padding:6px 0}
  .prompt{border-top:1px solid #f1f3f6;padding:12px 14px;background:#fcfcfd}
  .prompt .lbl{font-size:11px;font-weight:700;color:var(--muted);margin-bottom:5px;display:flex;justify-content:space-between;align-items:center}
  .prompt .box{font-size:12.5px;line-height:1.55;color:#222;white-space:pre-wrap;word-break:break-word;
    background:#fff;border:1px solid var(--border);border-radius:9px;padding:9px 11px;max-height:140px;overflow:auto}
  .prompt .box.empty{color:#aab;font-style:italic}
  .togglefull{font-size:11px;font-weight:600;color:var(--accent);cursor:pointer;user-select:none}
  .fullbox{display:none;margin-top:8px}
  .fullbox.open{display:block}
  .empty{text-align:center;color:var(--muted);padding:60px 0;font-size:14px}
  .foot{color:var(--muted);font-size:12px;margin-top:20px;text-align:center}
</style>
</head>
<body>
<div class="wrap">
  <a class="back" href="/logs/stats" id="backlink">← 전체 통계로</a>
  <header>
    <div>
      <h1 id="title"></h1>
      <div class="meta-sum" id="sum"></div>
    </div>
    <a class="btn" id="refreshBtn" href="?refresh=1">↻ 새로고침</a>
  </header>
  <div class="grid" id="grid"></div>
  <div class="empty" id="empty" style="display:none">표시할 생성 기록이 없습니다.</div>
  <div class="foot" id="foot"></div>
</div>

<script>
const DATA = __DATA__;
function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}
const u=DATA.user, s=DATA.summary, f=DATA.filter||{};
const qs=[]; if(f.from)qs.push("from="+f.from); if(f.to)qs.push("to="+f.to);
const dateQS=qs.length?("?"+qs.join("&")):"";
document.getElementById("backlink").href="/logs/stats"+dateQS;
document.getElementById("refreshBtn").href="?refresh=1"+(qs.length?"&"+qs.join("&"):"");

document.getElementById("title").innerHTML =
  esc(u.name||u.username) + (u.username==="anonymous" ? '<span class="uid">비로그인</span>'
    : `<span class="uid">@${esc(u.username)}${u.email?" · "+esc(u.email):""}</span>`);
document.getElementById("sum").innerHTML =
  `<span>생성 <b>${s.gen}</b></span><span>편집 <b>${s.edit}</b></span>`
  + `<span>합계 <b>${s.total}</b></span>`
  + (s.avg_elapsed!=null?`<span>평균 소요 <b>${s.avg_elapsed}초</b></span>`:"")
  + (f.from||f.to?`<span>기간 <b>${esc(f.from||"~")} ~ ${esc(f.to||"~")}</b></span>`:"");

if(!s.configured){
  document.getElementById("foot").textContent="⚠️ HF_TOKEN / HF_DATASET_REPO 미설정 — 이미지를 불러올 수 없습니다.";
}
if(s.truncated){
  document.getElementById("foot").textContent=`최근 ${s.limit}건만 표시했습니다. 더 보려면 기간 필터를 사용하세요.`;
}

function imgOrNone(url, alt, tag){
  if(!url) return "";
  return `<div class="t"><img loading="lazy" src="${url}" alt="${esc(alt)}" onerror="this.parentNode.style.display='none'"/>${tag?`<span class="tag">${esc(tag)}</span>`:""}</div>`;
}

function card(it){
  const badges=[];
  badges.push(`<span class="badge ${it.is_edit?'edit':''}">${it.kind}</span>`);
  if(it.shot) badges.push(`<span class="badge gray">${esc(it.shot)}</span>`);
  (it.style_codes||[]).forEach(c=>badges.push(`<span class="badge" style="background:#111;color:#fff">${esc(c)}</span>`));
  if(it.mode) badges.push(`<span class="badge gray">${esc(it.mode)}</span>`);
  if(it.is_edit && it.is_background_change) badges.push(`<span class="badge gray">배경변경</span>`);
  if(it.elapsed!=null) badges.push(`<span class="badge time">⏱ ${it.elapsed}초</span>`);

  // 입력 이미지 스트립
  let inputsHtml="";
  if(!it.is_edit){
    const parts=[];
    if(it.persona_url) parts.push(imgOrNone(it.persona_url,"persona","페르소나"));
    (it.product_urls||[]).forEach((purl,i)=>{
      const cat=(it.product_cats&&it.product_cats[i])?it.product_cats[i]:("제품"+(i+1));
      parts.push(imgOrNone(purl,"product",cat));
    });
    inputsHtml = parts.join("") || `<div class="noimg">저장된 입력 이미지 없음</div>`;
  } else {
    inputsHtml = `<div class="noimg">편집 — 입력은 직전 결과 이미지</div>`;
  }

  const outImg = it.thumb_url
    ? `<a href="${it.output_url||it.thumb_url}" target="_blank" rel="noopener"><img loading="lazy" src="${it.thumb_url}" alt="output" onerror="this.parentNode.innerHTML='<div class=&quot;noimg&quot; style=&quot;padding:20px&quot;>출력 이미지 없음</div>'"/></a>`
    : `<a><div class="noimg" style="padding:30px 8px;text-align:center">출력 이미지 없음</div></a>`;

  const promptText = it.custom_prompt && it.custom_prompt!=="(none)" ? it.custom_prompt : "";
  const promptLabel = it.is_edit ? "편집 지시" : "사용자 프롬프트";
  const fullToggle = it.full_prompt
    ? `<span class="togglefull" onclick="this.closest('.prompt').querySelector('.fullbox').classList.toggle('open');this.textContent=this.textContent.includes('▾')?'전체 프롬프트 ▸':'전체 프롬프트 ▾'">전체 프롬프트 ▸</span>`
    : "";

  return `<div class="card">
    <div class="card-top">
      <div class="outwrap">${outImg}</div>
      <div class="card-body">
        <div class="badges">${badges.join("")}</div>
        <div class="when">${esc(it.time)} · ${esc(it.ts)}</div>${(it.filenames&&it.filenames.length)?`<div class="inputs" style="margin-top:8px"><div class="lbl">원본 파일명</div><div>${it.filenames.map(f=>`<span style="font-family:ui-monospace,monospace;font-size:11px;background:#f3f5f8;padding:2px 7px;border-radius:6px;display:inline-block;margin:1px 3px 1px 0">${esc(f)}</span>`).join("")}</div></div>`:""}
        <div class="inputs"><div class="lbl">입력 이미지</div><div class="thumbs">${inputsHtml}</div></div>
      </div>
    </div>
    <div class="prompt">
      <div class="lbl"><span>${promptLabel}</span>${fullToggle}</div>
      <div class="box ${promptText?'':'empty'}">${promptText?esc(promptText):"(입력한 프롬프트 없음)"}</div>
      ${it.full_prompt?`<div class="fullbox"><div class="box">${esc(it.full_prompt)}</div></div>`:""}
    </div>
  </div>`;
}

(function(){
  const items=DATA.items||[];
  if(!items.length){ document.getElementById("empty").style.display="block"; return; }
  document.getElementById("grid").innerHTML = items.map(card).join("");
})();
</script>
</body>
</html>"""

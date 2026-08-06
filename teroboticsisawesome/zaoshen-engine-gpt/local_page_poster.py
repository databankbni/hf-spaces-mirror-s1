#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""造神引擎 —— 本機粉專發文器(輕量版,無瀏覽器)。

為什麼要它:HF Space 對 Facebook 的網路出口被擋(TCP 通、HTTPS 資料傳不過去),
所以粉專發文改由「你這台電腦」用官方 Graph API 發(你的網路連 FB 正常)。

資源:純 stdlib、不開瀏覽器。閒置時就是 sleep,幾乎不吃 CPU/RAM(~15MB)。
只有真的有「已核准的粉專貼文」時,才打一次 HTTPS 把它發出去。

用法:
  python3 local_page_poster.py once     # 跑一輪就結束(示範/測試)
  python3 local_page_poster.py loop      # 常駐,每 POLL 秒巡一次
設定(環境變數,可不設用預設):
  ZAOSHEN_SERVER / ZAOSHEN_USER / ZAOSHEN_PASS
  FB_PAGE_ID / FB_PAGE_TOKEN(或 FB_PAGE_TOKEN_FILE 指向 page_token.txt)
"""
import json, os, sys, time, ssl, urllib.request, urllib.parse, urllib.error
from pathlib import Path

SERVER = os.environ.get("ZAOSHEN_SERVER", "https://teroboticsisawesome-zaoshen-engine-gpt.hf.space").rstrip("/")
USER = os.environ.get("ZAOSHEN_USER", "wayne")
PASSWORD = os.environ.get("ZAOSHEN_PASS", "1234")
PAGE_ID = os.environ.get("FB_PAGE_ID", "371027582769797")
POLL = int(os.environ.get("ZAOSHEN_POLL_SECONDS", "20"))
GRAPH = "https://graph.facebook.com/v23.0"

_tok_file = os.environ.get("FB_PAGE_TOKEN_FILE", str(Path.home() / "californiadays_fb/secrets/page_token.txt"))
PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN") or (
    Path(_tok_file).read_text().strip() if Path(_tok_file).is_file() else "")

_cookie = ""


def _http(url, data=None, method="GET", headers=None, timeout=30):
    h = {"Content-Type": "application/json"}
    if _cookie:
        h["Cookie"] = _cookie
    if headers:
        h.update(headers)
    body = json.dumps(data).encode() if isinstance(data, (dict, list)) else data
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    return urllib.request.urlopen(req, timeout=timeout)


def login():
    """登入 HF app 拿 session cookie(唯讀取內容 + 標記已送用)。"""
    global _cookie
    resp = _http(f"{SERVER}/api/login", {"username": USER, "password": PASSWORD}, method="POST")
    sc = resp.headers.get("Set-Cookie", "")
    _cookie = sc.split(";")[0] if sc else ""
    return bool(_cookie)


def approved_page_items():
    """抓所有『已核准、還沒送出』的粉專貼文。"""
    resp = _http(f"{SERVER}/api/queue?status=approved", timeout=30)
    data = json.load(resp)
    items = data if isinstance(data, list) else data.get("items", data.get("queue", []))
    return [i for i in items if i.get("kind") == "page"]


def post_to_facebook(item):
    """從本機用 Graph API 發一篇粉專貼文。帶圖用公開 URL 讓 FB 自己抓。回 (post_id, post_url)。"""
    body = item.get("body", "")
    image_hint = item.get("image_hint") or ""
    if image_hint:
        media_url = f"{SERVER}/media/{Path(image_hint).name}"
        payload = urllib.parse.urlencode(
            {"caption": body, "url": media_url, "access_token": PAGE_TOKEN}).encode()
        url = f"{GRAPH}/{PAGE_ID}/photos"
    else:
        payload = urllib.parse.urlencode(
            {"message": body, "access_token": PAGE_TOKEN}).encode()
        url = f"{GRAPH}/{PAGE_ID}/feed"
    req = urllib.request.Request(url, data=payload, method="POST")
    with urllib.request.urlopen(req, timeout=90) as r:
        res = json.load(r)
    if "error" in res:
        raise RuntimeError(res["error"].get("message"))
    pid = res.get("post_id") or res.get("id", "")
    public = pid.split("_", 1)[1] if "_" in pid else pid
    return pid, (f"https://www.facebook.com/{PAGE_ID}/posts/{public}" if public else "")


def mark_sent(qid, post_url, post_id):
    """回報 HF:這篇已由本機發出(HF 只更新狀態,不再自己連 FB)。"""
    try:
        _http(f"{SERVER}/api/queue/{qid}/mark-sent",
              {"post_url": post_url, "post_id": post_id}, method="POST", timeout=20)
        return True
    except Exception as e:
        print(f"  ⚠ 回報 HF 失敗(貼文已發出):{e}", flush=True)
        return False


def run_once():
    if not PAGE_TOKEN:
        print("❌ 沒有 FB_PAGE_TOKEN,設定 FB_PAGE_TOKEN 或 FB_PAGE_TOKEN_FILE"); return 0
    if not login():
        print("❌ 登入 HF 失敗"); return 0
    items = approved_page_items()
    print(f"待發粉專貼文:{len(items)} 篇", flush=True)
    done = 0
    for it in items:
        qid = it.get("id")
        try:
            post_id, post_url = post_to_facebook(it)
            print(f"  ✅ 已從本機發出 q#{qid} → {post_url}", flush=True)
            mark_sent(qid, post_url, post_id)
            done += 1
        except Exception as e:
            print(f"  ❌ q#{qid} 發文失敗:{e}", flush=True)
    return done


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "once"
    if mode == "loop":
        print(f"本機粉專發文器啟動(每 {POLL}s 巡一次,閒置時幾乎不吃資源)", flush=True)
        while True:
            try:
                run_once()
            except Exception as e:
                print("巡查錯誤:", e, flush=True)
            time.sleep(POLL)
    else:
        run_once()


if __name__ == "__main__":
    main()

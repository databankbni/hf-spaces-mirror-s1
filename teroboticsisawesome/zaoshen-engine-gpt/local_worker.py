#!/usr/bin/env python3
"""造神引擎單人版本機 RPA 執行器。

cookie 只存在使用者的 LOCALAPPDATA/ZaoshenRPA/fb_profile。
使用者在網站認領時即授權自動發布；排程時間到後，以後端下發的 live 狀態決定是否送出。
"""
import json, os, time, urllib.request, platform, threading, subprocess, socket
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
APPDATA = Path(os.environ.get("LOCALAPPDATA", ROOT)) / "ZaoshenRPA"
PROFILE = APPDATA / "fb_profile"
SHOTS = APPDATA / "screenshots"
CACHE = APPDATA / "media"
SERVER = os.environ.get("ZAOSHEN_SERVER", "https://teroboticsisawesome-zaoshen-engine-gpt.hf.space")
POLL = int(os.environ.get("ZAOSHEN_POLL_SECONDS", "5"))
VERSION = "1.2.3"
CONFIG = APPDATA / "device.json"
DEVICE_TOKEN = ""


def request(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if DEVICE_TOKEN:
        headers["Authorization"] = "Bearer " + DEVICE_TOKEN
    req = urllib.request.Request(SERVER + path, data=data, headers=headers,
                                 method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def load_or_pair():
    global DEVICE_TOKEN, SERVER
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    if CONFIG.is_file():
        saved = json.loads(CONFIG.read_text(encoding="utf-8"))
        DEVICE_TOKEN = saved.get("device_token", "")
        SERVER = saved.get("server", SERVER).rstrip("/")
        if DEVICE_TOKEN:
            return saved
    print("\n首次啟動：請先登入造神引擎網站，在『夥伴與裝置』產生配對碼。")
    server = input(f"網站網址 [{SERVER}]：").strip() or SERVER
    SERVER = server.rstrip("/")
    code = input("一次性配對碼：").strip().upper()
    name = input(f"裝置名稱 [{platform.node() or 'Windows 電腦'}]：").strip() or platform.node() or "Windows 電腦"
    paired = request("/api/rpa/pair", {"code": code, "device_name": name,
        "rpa_version": VERSION, "os_version": platform.platform()})
    DEVICE_TOKEN = paired["device_token"]
    saved = {"server": SERVER, "device_token": DEVICE_TOKEN, "device_id": paired["device_id"],
             "display_name": paired["display_name"], "device_name": name}
    CONFIG.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"配對成功：{paired['display_name']}／{name}")
    return saved


def heartbeat_loop(status):
    while not status["stop"]:
        try:
            request("/api/worker/heartbeat", {"state": status["state"], "current_job": status["job"],
                "last_error": status["error"], "rpa_version": VERSION, "os_version": platform.platform()})
        except Exception as exc:
            print("心跳連線失敗：", exc, flush=True)
        time.sleep(20)


def fill_first(page, selectors, text):
    for selector in selectors:
        loc = page.locator(selector)
        if loc.count():
            try:
                loc.first.click(timeout=3000)
                loc.first.fill(text, timeout=5000)
                return True
            except Exception:
                try:
                    loc.first.press_sequentially(text, delay=2)
                    return True
                except Exception:
                    pass
    return False


def click_first(page, names):
    for name in names:
        loc = page.get_by_role("button", name=name, exact=True)
        if loc.count():
            loc.last.click(timeout=5000)
            return True
    return False


def target_url(value):
    value = (value or "").strip()
    if value and not value.startswith(("http://", "https://")):
        return "https://www.facebook.com/" + value.lstrip("@/")
    return value


def fetch_media(name):
    if not name:
        return None
    safe = Path(name).name
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / safe
    headers = {"Authorization": "Bearer " + DEVICE_TOKEN}
    req = urllib.request.Request(SERVER + "/api/worker/media/" + safe, headers=headers)
    with urllib.request.urlopen(req, timeout=45) as response:
        path.write_bytes(response.read())
    return path


def execute(page, job, live):
    url = target_url(job.get("target_url"))
    if not url:
        raise RuntimeError("目標沒有 URL，請先補上")
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(2500)
    if page.locator("input[name='email']").count():
        return "needs_attention", "Facebook 尚未登入，請在本機視窗登入"

    kind = job["kind"]
    if kind == "page" or (kind == "group" and job.get("phase") == "grouppost"):
        # Facebook 會依語系顯示其中一個名稱。
        opened = click_first(page, ["建立貼文", "撰寫貼文", "Write something…", "Create post"])
        if not opened:
            for text in ["建立貼文", "撰寫貼文", "Write something..."]:
                loc = page.get_by_text(text, exact=False)
                if loc.count():
                    loc.first.click(); opened = True; break
        page.wait_for_timeout(1200)
        filled = fill_first(page,
            ["div[role='dialog'] div[contenteditable='true']",
             "div[contenteditable='true'][role='textbox']"], job["body"])
        if not opened or not filled:
            return "needs_attention", "找不到社團發文輸入框，可能需要回答入社問題或版面已變更"
        image_name = job.get("image_hint") or ""
        image_path = fetch_media(image_name) if image_name else None
        if image_path and image_path.is_file():
            attached = False
            for selector in ["div[role='dialog'] input[type='file']", "input[type='file']"]:
                files = page.locator(selector)
                if files.count():
                    try:
                        files.first.set_input_files(str(image_path), timeout=5000)
                        attached = True; page.wait_for_timeout(1500); break
                    except Exception:
                        pass
            if not attached:
                return "needs_attention", "文案已填入，但找不到圖片上傳欄位"
        if live and not click_first(page, ["發佈", "發布", "Post"]):
            return "needs_attention", "文案已填入，但找不到發佈按鈕"
    else:
        # target_url 可是對方頁面或既有 Messenger 對話。
        click_first(page, ["發送訊息", "傳送訊息", "Message"])
        page.wait_for_timeout(1000)
        filled = fill_first(page,
            ["div[contenteditable='true'][role='textbox']",
             "div[aria-label='訊息'][contenteditable='true']",
             "div[aria-label='Message'][contenteditable='true']"], job["body"])
        if not filled:
            return "needs_attention", "找不到私訊輸入框，請確認目標網址與對方是否允許收訊息"
        if live:
            page.keyboard.press("Enter")

    page.wait_for_timeout(1800)
    return ("succeeded", "") if live else ("needs_attention", "安全模式：已開啟並填稿，沒有按送出")


def wait_for_facebook_login(page, status):
    """首次啟動先把瀏覽器完整交給使用者；確認登入前絕不領任務或切換頁面。"""
    status.update(state="attention", job="", error="請在 RPA 專用 Edge 完成 Facebook 登入")
    page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=60000)
    print("請在目前的 RPA 專用 Edge 完成 Facebook 登入；登入前不會領取任務。", flush=True)
    while True:
        try:
            url = page.url.lower()
            has_login = page.locator("input[name='email'], input#email, input[name='pass']").count() > 0
            login_url = "login" in url or "checkpoint" in url
            if not has_login and not login_url and "facebook.com" in url:
                status.update(state="idle", job="", error="")
                print("Facebook 登入已確認，RPA 開始待命。", flush=True)
                return
        except Exception:
            pass
        time.sleep(2)


def find_edge():
    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe",
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise RuntimeError("找不到 Microsoft Edge，請先安裝或更新 Edge")


def launch_manual_edge(pw):
    """Windows 先正常啟動專用 Edge，使用者可完整操作 2FA；RPA 再從 localhost 連入。"""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    command = [str(find_edge()),
        f"--remote-debugging-port={port}", "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={PROFILE}", "--no-first-run", "--no-default-browser-check",
        "--start-maximized", "https://www.facebook.com/"]
    process = subprocess.Popen(command)
    endpoint = f"http://127.0.0.1:{port}"
    last_error = None
    for _ in range(40):
        if process.poll() is not None:
            raise RuntimeError("RPA 專用 Edge 啟動後立即關閉")
        try:
            browser = pw.chromium.connect_over_cdp(endpoint, timeout=2000)
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else context.new_page()
            return process, browser, context, page
        except Exception as exc:
            last_error = exc
            time.sleep(.5)
    process.terminate()
    raise RuntimeError(f"無法連接 RPA 專用 Edge：{last_error}")


def main():
    saved = load_or_pair()
    PROFILE.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    status = {"state": "idle", "job": "", "error": "", "stop": False}
    threading.Thread(target=heartbeat_loop, args=(status,), daemon=True).start()
    with sync_playwright() as pw:
        edge_process, browser, ctx, page = launch_manual_edge(pw)
        print(f"造神引擎 RPA {VERSION} 已在線：{saved['display_name']}／{saved['device_name']}；登入資料僅存於 {PROFILE}", flush=True)
        wait_for_facebook_login(page, status)
        while True:
            try:
                claimed = request("/api/worker/claim", {})
                job = claimed.get("job")
                if not job:
                    time.sleep(POLL); continue
                status.update(state="working", job=f"工作 #{job['job_id']} · {job['target_name']}", error="")
                live = bool(claimed.get("live"))
                try:
                    state, error = execute(page, job, live)
                except Exception as exc:
                    state, error = "failed", str(exc)
                shot = SHOTS / f"job_{job['job_id']}.png"
                try: page.screenshot(path=str(shot), full_page=True)
                except Exception: shot = Path()
                request(f"/api/worker/jobs/{job['job_id']}/result", {
                    "state": state, "error": error,
                    "screenshot_path": str(shot) if shot else "",
                    "external_url": page.url if state == "succeeded" else ""})
                print(f"job {job['job_id']} -> {state} {error}", flush=True)
                status.update(state="idle" if state == "succeeded" else "attention", job="", error=error)
            except KeyboardInterrupt:
                status["stop"] = True
                break
            except Exception as exc:
                status.update(state="attention", error=str(exc))
                print("worker error:", exc, flush=True); time.sleep(POLL)
        try: browser.close()
        except Exception: pass
        if edge_process.poll() is None:
            edge_process.terminate()


if __name__ == "__main__":
    main()

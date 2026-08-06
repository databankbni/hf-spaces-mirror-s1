"""以獨立 Edge profile 開啟 Meta 系統用戶設定；不讀取或輸出權杖。"""
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


PROFILE = Path.home() / "AppData" / "Local" / "ZaoshenRPA" / "meta_admin_profile"
URL = "https://business.facebook.com/settings/system-users"


with sync_playwright() as pw:
    context = pw.chromium.launch_persistent_context(
        str(PROFILE), channel="msedge", headless=False,
        locale="zh-TW", no_viewport=True,
        args=["--start-maximized", "--remote-debugging-port=9223"],
    )
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(URL, wait_until="domcontentloaded", timeout=120_000)
    page.evaluate("document.body.style.zoom='80%'")
    print("META_EDGE_OPEN", flush=True)
    print("請在 Edge 手動完成 Meta 登入與二階段驗證；完成後保留視窗。", flush=True)
    try:
        while True:
            time.sleep(2)
    except KeyboardInterrupt:
        context.close()

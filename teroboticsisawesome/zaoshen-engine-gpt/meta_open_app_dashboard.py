from pathlib import Path
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    browser = pw.chromium.connect_over_cdp("http://127.0.0.1:9223")
    context = browser.contexts[0]
    page = context.new_page()
    page.goto("https://developers.facebook.com/apps/26715819381426213/", wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(7000)
    page.screenshot(path=str(Path(__file__).with_name("meta_app_current.png")), full_page=False)
    state = {"url": page.url, "title": page.title(), "text": page.locator("body").inner_text(timeout=15_000)[:10000]}
    Path(__file__).with_name("meta_app_state.txt").write_text(repr(state), encoding="utf-8")

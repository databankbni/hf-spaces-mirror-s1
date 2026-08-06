from pathlib import Path
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    browser = pw.chromium.connect_over_cdp("http://127.0.0.1:9223")
    pages = [p for c in browser.contexts for p in c.pages]
    page = next(p for p in pages if "developers.facebook.com/apps/26715819381426213" in p.url)
    page.get_by_role("button", name="儲存", exact=True).click()
    page.wait_for_timeout(5000)
    page.screenshot(path=str(Path(__file__).with_name("meta_app_current.png")), full_page=False)
    state = {"url": page.url, "text": page.locator("body").inner_text(timeout=15_000)[-10000:]}
    Path(__file__).with_name("meta_app_state.txt").write_text(repr(state), encoding="utf-8")

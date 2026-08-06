from pathlib import Path
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    browser = pw.chromium.connect_over_cdp("http://127.0.0.1:9223")
    page = [p for c in browser.contexts for p in c.pages][-1]
    page.get_by_text("驗證應用程式", exact=True).click()
    page.get_by_role("button", name="繼續", exact=True).click()
    page.wait_for_timeout(1500)
    page.screenshot(path=str(Path(__file__).with_name("meta_current.png")))
    print(page.url)

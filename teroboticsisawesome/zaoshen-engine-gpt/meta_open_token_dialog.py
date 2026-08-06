from pathlib import Path
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    browser = pw.chromium.connect_over_cdp("http://127.0.0.1:9223")
    pages = [p for c in browser.contexts for p in c.pages]
    page = next(p for p in pages if "/latest/settings/system_users" in p.url)
    page.get_by_text("產生權杖", exact=True).click()
    page.wait_for_timeout(2500)
    page.screenshot(path=str(Path(__file__).with_name("meta_current.png")))
    print(page.locator("body").inner_text()[-5000:])

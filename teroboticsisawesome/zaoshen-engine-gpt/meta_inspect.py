from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).with_name("meta_current.png")
with sync_playwright() as pw:
    browser = pw.chromium.connect_over_cdp("http://127.0.0.1:9223")
    pages = [p for c in browser.contexts for p in c.pages]
    page = next((p for p in pages if "/latest/settings/system_users" in p.url), pages[-1])
    page.screenshot(path=str(OUT), full_page=False)
    print("URL", page.url)
    print("TITLE", page.title())
    print("TEXT", page.locator("body").inner_text(timeout=10_000)[:6000])

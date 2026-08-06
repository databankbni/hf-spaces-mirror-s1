from pathlib import Path
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    browser = pw.chromium.connect_over_cdp("http://127.0.0.1:9223")
    pages = [p for c in browser.contexts for p in c.pages]
    page = next(p for p in pages if "developers.facebook.com/apps/26715819381426213" in p.url)
    dialog = page.locator('[role="dialog"]')
    if dialog.count():
        box = dialog.bounding_box()
        if box:
            page.mouse.click(box["x"] + box["width"] - 35, box["y"] + 35)
        page.wait_for_timeout(800)
    page.get_by_text("新增使用案例", exact=True).click()
    page.wait_for_timeout(2500)
    page.screenshot(path=str(Path(__file__).with_name("meta_app_current.png")), full_page=False)
    state = {"url": page.url, "text": page.locator("body").inner_text(timeout=15_000)[-12000:]}
    Path(__file__).with_name("meta_app_state.txt").write_text(repr(state), encoding="utf-8")

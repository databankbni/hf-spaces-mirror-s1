from pathlib import Path
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    browser = pw.chromium.connect_over_cdp("http://127.0.0.1:9223")
    pages = [p for c in browser.contexts for p in c.pages]
    page = next(p for p in pages if "/latest/settings/system_users" in p.url)
    events = []
    page.on("pageerror", lambda exc: events.append({"kind": "pageerror", "error": str(exc)}))
    page.on("console", lambda msg: events.append({"kind": "console", "type": msg.type, "text": msg.text}) if msg.type in ("error", "warning") else None)
    page.on("requestfailed", lambda req: events.append({"kind": "failed", "url": req.url, "error": req.failure}))
    page.on("response", lambda res: events.append({"kind": "http", "status": res.status, "url": res.url}) if res.status >= 400 else None)
    page.goto("https://business.facebook.com/latest/settings/system_users?business_id=523343780310734&selected_user_id=61592060695338",
              wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(5000)
    page.get_by_text("產生權杖", exact=True).click()
    page.wait_for_timeout(10000)
    Path(__file__).with_name("meta_token_network.txt").write_text(repr(events[-100:]), encoding="utf-8")

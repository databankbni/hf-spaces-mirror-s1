from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    browser = pw.chromium.connect_over_cdp("http://127.0.0.1:9223")
    page = [p for c in browser.contexts for p in c.pages][-1]
    failed = []
    errors = []
    page.on("requestfailed", lambda req: failed.append((req.url, req.failure)))
    page.on("console", lambda msg: errors.append((msg.type, msg.text)) if msg.type == "error" else None)
    page.reload(wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(15000)
    lines = ["URL " + page.url, "FAILED"]
    lines += [repr(row) for row in failed[:30]]
    lines += ["CONSOLE"]
    lines += [repr(row) for row in errors[:30]]
    with open(__file__.replace("meta_diagnose_loading.py", "meta_diag.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

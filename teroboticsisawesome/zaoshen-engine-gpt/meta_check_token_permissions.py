from pathlib import Path
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    browser = pw.chromium.connect_over_cdp("http://127.0.0.1:9223")
    context = browser.contexts[0]
    pages = [p for p in context.pages]
    page = next((p for p in pages if "/latest/settings/system_users" in p.url), context.new_page())
    page.goto("https://business.facebook.com/latest/settings/system_users?business_id=523343780310734&selected_user_id=61592060695338",
              wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(7000)
    page.get_by_text("產生權杖", exact=True).click()
    page.wait_for_timeout(5000)
    page.screenshot(path=str(Path(__file__).with_name("meta_current.png")), full_page=False)
    state = page.evaluate("""() => ({
      url: location.href,
      text: document.body.innerText.slice(-12000),
      dialogs: [...document.querySelectorAll('[role=dialog]')].map(x => x.innerText)
    })""")
    Path(__file__).with_name("meta_dialog_state.txt").write_text(repr(state), encoding="utf-8")

from pathlib import Path
from playwright.sync_api import sync_playwright

out = Path(__file__).with_name("meta_dialog_state.txt")
with sync_playwright() as pw:
    browser = pw.chromium.connect_over_cdp("http://127.0.0.1:9223")
    pages = [p for c in browser.contexts for p in c.pages]
    page = next(p for p in pages if "/latest/settings/system_users" in p.url)
    state = page.evaluate("""() => ({
      url: location.href,
      title: document.title,
      text: document.body.innerText.slice(-8000),
      dialogs: [...document.querySelectorAll('[role=dialog]')].map(x => x.innerText),
      iframes: [...document.querySelectorAll('iframe')].map(x => x.src)
    })""")
    out.write_text(repr(state), encoding="utf-8")

from pathlib import Path
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    browser = pw.chromium.connect_over_cdp("http://127.0.0.1:9223")
    pages = [p for c in browser.contexts for p in c.pages]
    page = next(p for p in pages if "developers.facebook.com/apps/26715819381426213" in p.url)
    links = page.evaluate("""() => [...document.querySelectorAll('a')]
      .map(a => ({text:(a.innerText||'').trim(), href:a.href}))
      .filter(x => x.text.includes('使用案例') || x.href.includes('use_case'))""")
    Path(__file__).with_name("meta_links.txt").write_text(repr(links), encoding="utf-8")

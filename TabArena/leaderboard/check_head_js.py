"""Parse-check every ``<script>`` block in ``main.py``'s ``HEAD``.

``HEAD`` is an ordinary Python string, so a backslash escape written for JavaScript is read by
Python first: a newline escape meant for a JS string literal arrives as a real line break, which
is an unterminated string, which takes the whole script block down with it. Nothing reports
that at runtime -- the block simply never defines anything, and the page looks fine until
something it defined is called -- so check it here instead.

Run after touching ``HEAD``::

    ./.venv/bin/python check_head_js.py

Needs playwright with a chromium build available; skips (exit 0) when there is none, so it can
sit in a pre-commit hook without becoming a hard dependency. Set ``CHROMIUM_EXECUTABLE`` to
point at a browser playwright did not install itself.
"""

from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

MAIN = Path(__file__).with_name("main.py")


def head_scripts() -> list[str]:
    """The JS of every ``<script>`` block in ``HEAD``."""
    module = ast.parse(MAIN.read_text(encoding="utf-8"))
    head = next(
        ast.literal_eval(node.value)
        for node in module.body
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "HEAD"
    )
    return re.findall(r"<script>(.*?)</script>", head, re.S)


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed; skipping the head-script parse check")
        return 0

    scripts = head_scripts()
    failures = 0
    with sync_playwright() as pw:
        executable = os.environ.get("CHROMIUM_EXECUTABLE") or None
        try:
            browser = pw.chromium.launch(executable_path=executable)
        except Exception as err:  # noqa: BLE001 - any launch failure means "no browser here"
            print(f"no chromium available ({type(err).__name__}); skipping the parse check")
            return 0
        page = browser.new_page()
        page.goto("about:blank")
        for index, source in enumerate(scripts):
            result = page.evaluate(
                "(src) => { try { new Function(src); return 'ok'; } catch (e) { return e.message; } }",
                source,
            )
            print(f"script block {index} ({len(source)} chars): {result}")
            failures += result != "ok"
        browser.close()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

import pathlib
import re
import quickjs

text = pathlib.Path("index.html").read_text(encoding="utf-8")
match = re.search(r"<script>([\s\S]*?)</script>", text)
if not match:
    raise SystemExit("No script block found")
js = match.group(1)

ctx = quickjs.Context()
try:
    ctx.eval(js)
    print("OK")
except Exception as exc:
    print(type(exc).__name__)
    print(exc)

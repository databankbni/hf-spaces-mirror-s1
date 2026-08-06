import pathlib
import re
import esprima

path = pathlib.Path("index.html")
text = path.read_text(encoding="utf-8")
match = re.search(r"<script>([\s\S]*?)</script>", text)
if not match:
    raise SystemExit("No inline <script> found")
js = match.group(1)

try:
    esprima.parseScript(js, {"tolerant": False, "loc": True})
    print("OK")
except Exception as exc:
    print(type(exc).__name__, exc)

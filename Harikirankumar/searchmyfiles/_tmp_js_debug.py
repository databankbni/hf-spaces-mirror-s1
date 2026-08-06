import pathlib, re
import esprima
text = pathlib.Path("index.html").read_text(encoding="utf-8")
m = re.search(r"<script>([\s\S]*?)</script>", text)
js = m.group(1)
lines = js.splitlines()
for n in [500,510,515,516,517,518,519,520,530,540,560]:
    start = max(1, n-2)
    end = min(len(lines), n+2)
    print(f"--- JS around {n} ---")
    for i in range(start, end+1):
        print(f"{i}: {lines[i-1]}")
try:
    esprima.parseScript(js, {"tolerant": False, "loc": True})
    print("OK")
except Exception as e:
    print("ERR", type(e).__name__, e)

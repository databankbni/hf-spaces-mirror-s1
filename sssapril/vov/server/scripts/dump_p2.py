import json
with open(r'd:\agents\vov\server\logs\server.log', 'rb') as f:
    raw = f.read()
text = raw.decode('utf-8', errors='replace')
lines = text.splitlines()

# 玩家 2 启动时间 ~16:57:11，过滤这个时段的全部 log
import re
for line in lines:
    m = re.match(r'\[?(\d{2}:\d{2}:\d{2})\]?', line)
    if m:
        ts = m.group(1)
        if ts >= '16:57:11' and ts <= '17:02:50':
            print(line.rstrip())

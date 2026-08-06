#!/bin/bash

# ==========================================
# 关键修复：清除 Hugging Face 注入的默认出网代理
# 防止代理打断长连接，导致不停重连从而触发 Lichess 限制
# ==========================================
unset HTTP_PROXY
unset HTTPS_PROXY
unset http_proxy
unset https_proxy
export NO_PROXY="*"
cat <<EOF > /app/index.html
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Lichess External Engine</title>
    <style>
        body { font-family: monospace; background: #121212; color: #00ff66; padding: 20px; }
    </style>
</head>
<body>
    <h2>♟️ Lichess External Engine is RUNNING!</h2>
    <p>Stockfish is online and connected to Lichess API.</p>
</body>
</html>
EOF

# 将 config.yml 中的占位符替换为您在 HF Secrets 中设置的 LICHESS_TOKEN
sed -i "s/YOUR_LICHESS_TOKEN/${LICHESS_TOKEN}/g" config.yml

# 在后台启动一个简单的 HTTP 服务器，监听 7860 端口（应付健康检查）
python3 -m http.server 7860 &

# 启动 Lichess Bot
python3 lichess-bot.py
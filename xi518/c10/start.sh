#!/bin/sh
# 将外部 7860 端口转发到 QMediaSync 监听的 12333
socat TCP-LISTEN:7860,fork,reuseaddr TCP:localhost:12333 &
# 启动 QMediaSync 主程序
exec /app/QMediaSync
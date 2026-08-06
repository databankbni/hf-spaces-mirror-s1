#!/bin/bash

echo "[entrypoint] 启动 MCSManager Web 端..."
echo "[entrypoint] Web 端口: 23333"
echo "[entrypoint] 数据目录: /opt/mcsmanager/web/data"
echo "[entrypoint] 日志目录: /opt/mcsmanager/web/logs"

cd /opt/mcsmanager/web

# 直接启动 Web 端
npm start
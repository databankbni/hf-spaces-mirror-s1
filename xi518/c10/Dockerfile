# 原版 TaoSync 部署到 Hugging Face Docker Space
# 基于官方预构建镜像 dr34m/tao-sync（PyInstaller 独立二进制，无需自己编译/放源码）。
# 适配点：① 监听 HF 注入的 $PORT（默认 7860）；② 数据持久化到 /data；
#         ③ 反向代理：原版只监听 127.0.0.1，HF 反向代理需要 0.0.0.0，故加一层转发。
# 端口分工：原版跑在内部端口 8023（TAO_PORT），代理监听 0.0.0.0:$PORT 转发到 127.0.0.1:8023，避免抢端口。
# 原版项目：https://github.com/Yijian0707/taosync
FROM dr34m/tao-sync:latest@sha256:c65a935e0de1505cde6887b32ed0fcaa19a0cc834f41d5bfa583a4cf22fd9bf7

# 原版把数据写在 /app/data，映射到 HF 的持久化目录 /data（重启不丢配置/任务）
RUN rm -rf /app/data && ln -s /data /app/data

# 基础镜像是 Alpine：优先用 apk 装 socat 做并发转发；装不上就回退 busybox nc（Alpine 自带）。
RUN apk add --no-cache socat 2>/dev/null || true

# busybox nc 回退方案：用 FIFO 做双向转发（顺序处理连接，单用户管理界面够用）。
# 用法：/relay.sh <外部端口> <内部端口>
RUN cat > /relay.sh <<'SH'
#!/bin/sh
PORT=$1
TPORT=$2
while true; do
  mkfifo /tmp/tao_f
  nc -l -p "$PORT" < /tmp/tao_f | nc 127.0.0.1 "$TPORT" > /tmp/tao_f &
  wait
  rm -f /tmp/tao_f
done
SH

EXPOSE 7860
# 原版在内部端口 8023 运行（监听 127.0.0.1）；代理作为前台进程监听 0.0.0.0:$PORT 并转发到 127.0.0.1:8023。
# 代理前台常驻，保证容器不会因前台 shell 退出而崩溃循环。
CMD ["sh", "-c", "TAO_PORT=8023 ./taoSync & (command -v socat >/dev/null 2>&1 && exec socat TCP-LISTEN:${PORT:-7860},fork,reuseaddr TCP:127.0.0.1:8023 || exec sh /relay.sh ${PORT:-7860} 8023)"]

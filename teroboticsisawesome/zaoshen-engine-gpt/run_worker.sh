#!/usr/bin/env bash
# 另開一個終端執行。預設只開頁、填稿和截圖，不按送出。
cd "$(dirname "$0")"
export ZAOSHEN_LIVE="${ZAOSHEN_LIVE:-0}"
exec python3 local_worker.py

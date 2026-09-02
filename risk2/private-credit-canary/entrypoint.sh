#!/bin/bash
# HF Space 컨테이너 진입점.
# 1단계 batch (데이터 수집/요약/점수) → 2단계 streamlit 순차 실행.
#
# 환경변수:
#   SKIP_BATCH=true        → 모든 batch 단계 스킵 (Streamlit 만 시작)
#   FORCE_RUN_BATCH=true   → 오늘 marker 무시하고 batch 강제 실행 (코드 수정 후 재실행용)

set -e

echo "============================================"
echo "  Private Credit Canary — HF Space 부팅"
echo "============================================"

# KST 기준 오늘 — cron 이 KST 07:00 에 발사돼도 컨테이너 UTC date 와 어긋나지 않게.
# 이 값이 marker 비교/기록에 동시에 쓰이므로 한 군데서 KST 로 통일하면 충분.
TODAY=$(TZ=Asia/Seoul date +%Y-%m-%d)
MARKER_FILE=/app/data/last_batch_date.txt

# SKIP_BATCH 환경변수 — 비어있지 않고 false/0/no 가 아니면 batch 스킵 (대소문자 무관)
_SB_LOWER="$(echo "${SKIP_BATCH:-}" | tr '[:upper:]' '[:lower:]' | tr -d ' ')"
SKIP_BY_ENV=false
if [ -n "$_SB_LOWER" ] && [ "$_SB_LOWER" != "false" ] && [ "$_SB_LOWER" != "0" ] && [ "$_SB_LOWER" != "no" ]; then
    SKIP_BY_ENV=true
fi

# FORCE_RUN_BATCH — 같은 방식으로 파싱
_FR_LOWER="$(echo "${FORCE_RUN_BATCH:-}" | tr '[:upper:]' '[:lower:]' | tr -d ' ')"
FORCE_RUN=false
if [ -n "$_FR_LOWER" ] && [ "$_FR_LOWER" != "false" ] && [ "$_FR_LOWER" != "0" ] && [ "$_FR_LOWER" != "no" ]; then
    FORCE_RUN=true
fi

# 1) SKIP_BATCH 명시적 설정 — 무조건 batch 스킵
if [ "$SKIP_BY_ENV" = "true" ]; then
    echo "[INFO] SKIP_BATCH=${SKIP_BATCH} 감지 — batch 모두 스킵, 기존 data/ 그대로 사용"
else
    # 2) Marker file 기반 — 오늘 이미 실행됐으면 스킵 (FORCE_RUN_BATCH 가 override)
    SKIP_BY_MARKER=false
    if [ -f "$MARKER_FILE" ] && [ "$(cat $MARKER_FILE 2>/dev/null)" = "$TODAY" ]; then
        SKIP_BY_MARKER=true
    fi

    if [ "$SKIP_BY_MARKER" = "true" ] && [ "$FORCE_RUN" != "true" ]; then
        echo "[INFO] 오늘 ($TODAY) batch 이미 실행됨 — SKIP, Streamlit 만 시작"
        echo "  마지막 실행 marker: $(cat $MARKER_FILE)"
        echo "  강제 재실행: HF Variables 에 FORCE_RUN_BATCH=true 설정"
    else
        if [ "$FORCE_RUN" = "true" ]; then
            echo "[INFO] FORCE_RUN_BATCH=${FORCE_RUN_BATCH} 감지 — marker 무시하고 batch 강제 실행"
        fi

        echo ""
        echo "▶ [1/5] 데이터 수집 (colab_collect.py)..."
        python tools/colab_collect.py || echo "[WARN] colab_collect.py 일부 실패 — 다음 단계 계속"

        echo ""
        echo "▶ [2/5] 뉴스 요약 (summarize_news.py)..."
        python tools/summarize_news.py || echo "[WARN] summarize_news.py 일부 실패 — 다음 단계 계속"

        echo ""
        echo "▶ [3/5] SEC 공시 요약 (summarize_filings.py)..."
        python tools/summarize_filings.py || echo "[WARN] summarize_filings.py 일부 실패 — 다음 단계 계속"

        echo ""
        echo "▶ [4/5] 리스크 점수 산출 (score_risk_test_gemma.py — Gemma)..."
        python tools/score_risk_test_gemma.py --output risk_scores_history.json || echo "[WARN] score_risk_test_gemma.py 일부 실패 — 다음 단계 계속"

        # Marker 기록 — [5/5] push 에 포함되어 git 에 commit 됨.
        # 다음 rebuild 가 이 marker 를 보고 batch 스킵 → loop 끊김.
        echo "$TODAY" > "$MARKER_FILE"
        echo ""
        echo "[INFO] Marker 파일 갱신: $MARKER_FILE = $TODAY"

        echo ""
        echo "▶ [5/5] HF Space repo 로 최종 push (요약+점수+marker 까지 누적)..."
        python tools/hf_push.py || echo "[WARN] hf_push.py 실패 — 다음 단계 계속"
    fi
fi

echo ""
echo "============================================"
echo "  ▶ Streamlit 시작..."
echo "============================================"
exec streamlit run app.py \
    --server.port=8501 \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --browser.gatherUsageStats=false

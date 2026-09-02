FROM python:3.10-slim

WORKDIR /app

# Python 출력 즉시 flush (buffered → 실시간 로그)
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Python 패키지 먼저 설치 (Docker layer caching)
COPY requirements.txt ./
RUN pip3 install -r requirements.txt

# 앱 본체 + 데이터 + tools/ (batch 스크립트들) + Streamlit 설정 복사
COPY app.py ./
COPY data/ ./data/
COPY tools/ ./tools/
COPY .streamlit/ ./.streamlit/
COPY entrypoint.sh ./

# Streamlit 정적 HTML 의 <title>·OG 메타태그를 우리 앱 이름으로 교체
# (카카오톡/슬랙 등 link unfurl 크롤러용 — JS 실행 안 하므로 런타임 page_title 로는 불가)
RUN python tools/patch_streamlit_og.py

# entrypoint 실행 권한 부여
RUN chmod +x entrypoint.sh

EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health

# 진입점: entrypoint.sh — 1단계 batch (데이터 수집/요약/점수) → 2단계 streamlit
ENTRYPOINT ["./entrypoint.sh"]

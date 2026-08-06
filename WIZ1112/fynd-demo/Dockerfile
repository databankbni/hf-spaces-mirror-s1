# FYND 추천 시스템 — Hugging Face Spaces (Docker) 배포용
# fynd-demo의 Dockerfile 구조를 계승하되, 로컬 개발 환경에 맞춰 Python 3.11로 상향

FROM python:3.11

# Hugging Face Spaces 권한 설정 (보안상 필수)
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app

# 의존성 설치 (레이어 캐시 활용을 위해 먼저 복사)
COPY --chown=user ./requirements.txt $HOME/app/requirements.txt
# torch는 CPU 전용 휠로 먼저 설치 — 기본 인덱스는 CUDA 포함 수 GB를 받다가
# 빌드 네트워크가 끊기는 문제가 있음 (cpu-basic 하드웨어라 CPU 휠이 맞음)
RUN pip install --no-cache-dir --retries 10 --timeout 120 torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir --retries 10 --timeout 120 --upgrade -r requirements.txt

# 프로젝트 전체 복사
COPY --chown=user . $HOME/app

# 상품 이미지 압축 해제 (개별 이미지 5,880장 대신 zip 1개로 배포)
RUN unzip -q images.zip && rm images.zip

# Flask 앱 실행 (포트 5001 — README frontmatter의 app_port와 일치해야 함)
CMD ["python", "app.py"]

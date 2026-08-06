FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV ZAOSHEN_LIVE=0
EXPOSE 7860
# HF Space 用 7860;Cloud Run 會設 PORT(通常 8080)。兩邊都相容。
CMD exec uvicorn backend:app --host 0.0.0.0 --port ${PORT:-7860}

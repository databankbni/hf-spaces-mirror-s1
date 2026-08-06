# HuggingFace Space (Docker SDK) for the skill-audit x402 endpoint.
# Free, no credit card, stable URL. Sleeps after ~48h idle, wakes on request.
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PORT=7860

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scripts ./scripts
COPY mcp_servers ./mcp_servers

EXPOSE 7860
# --proxy-headers + trust all forwarders so the x402 `resource` URL is built as
# https:// (HF terminates TLS at its proxy and forwards plain http internally);
# a scheme mismatch can make strict x402 verifiers reject the payment.
CMD ["uvicorn", "scripts.x402_api.main:app", "--host", "0.0.0.0", "--port", "7860", "--proxy-headers", "--forwarded-allow-ips", "*"]

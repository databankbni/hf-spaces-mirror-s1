# Hugging Face Space builds from this repo root (Dockerfile, app.py, index.html, …).
# Do not use monorepo paths like sushi_atelier/… — those files are not in the Space clone.
#
# Media: HF Dataset PIANDT/sushi_atelier_artifacts — app.py proxies /sushi_atelier_artifacts/* using Bearer auth.
# Docker Spaces do not inject HF_TOKEN automatically: Space Settings → Repository secrets → HF_TOKEN (read access to that dataset).
# Mail: set SMTP_USER + SMTP_PASSWORD (and optional SMTP_HOST/PORT, MAIL_TO) for POST /api/contact.
# Optional: add a `sushi_atelier_artifacts/` folder here only if you want fallback local assets in the image.
#
# https://huggingface.co/docs/hub/spaces-sdks-docker
FROM python:3.9

RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY . /app/

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]

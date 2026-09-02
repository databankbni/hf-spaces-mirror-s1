FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        git build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install ALL app dependencies at BUILD time, system-wide (readable by every
# user). This avoids any runtime permission problem when importing them.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY start.py /app/start.py

ENV PORT=7860
EXPOSE 7860

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH

CMD ["python", "/app/start.py"]

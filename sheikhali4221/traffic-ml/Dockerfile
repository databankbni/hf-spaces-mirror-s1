FROM python:3.10-slim

WORKDIR /code

# Dynamic environment optimization
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Explicit stable versions mapping block
COPY ./backend/requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir -r /code/requirements.txt

# Complete software workspace copy protocol
COPY ./backend /code

EXPOSE 7860

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
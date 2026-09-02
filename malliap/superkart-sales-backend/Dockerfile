FROM python:3.9-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir --upgrade -r requirements.txt

CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:7860", "app:superkart_api"]
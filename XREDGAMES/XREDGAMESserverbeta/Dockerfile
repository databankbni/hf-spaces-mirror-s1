FROM python:3.9
RUN pip install fastapi uvicorn
COPY . .
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]

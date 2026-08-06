FROM python:3.12-slim
RUN pip install --no-cache-dir pyyaml markdown
WORKDIR /app
COPY app.py viz.py /app/
EXPOSE 7860
CMD ["python", "app.py"]

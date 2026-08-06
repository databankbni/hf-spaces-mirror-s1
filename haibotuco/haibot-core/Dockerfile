FROM rasa/rasa:3.6.21-full

WORKDIR /app
COPY . /app/

USER root
RUN pip install --no-cache-dir "sqlalchemy<2.0" "rasa-sdk==3.6.0" \
    && mkdir -p /app/models && \
    chown -R 1001:0 /app

USER 1001

# Entrenar el modelo durante el build (se cachea en la imagen)
RUN rasa train \
    --config config.yml \
    --domain domain.yml \
    --data data/ \
    --out models/

EXPOSE 7860

ENTRYPOINT []

CMD ["python", "/app/start-haibot.py"]

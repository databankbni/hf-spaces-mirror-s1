FROM python:3.11-slim
# rebuild trigger 1783431069
ENV REBUILD_TIMESTAMP=1783443579
ENV PYTHONUNBUFFERED=1
ENV HERMES_HOME=/opt/data
ENV PORT=7860
WORKDIR /app
RUN pip install --no-cache-dir flask qrcode[pil] huggingface_hub requests pillow
COPY app.py /app/app.py
COPY assets/ /app/assets/
COPY web_search.py /app/web_search.py
COPY notify_session.py /app/notify_session.py
COPY data_sync.py /app/data_sync.py
COPY security.py /app/security.py
COPY memory_cleanup.py /app/memory_cleanup.py
COPY soul.json /app/soul.json
COPY profile.json /app/profile.json
COPY config.yaml /app/config.yaml
COPY app.js /app/app.js
COPY template.html /app/template.html
COPY wechat_auto.py /app/wechat_auto.py
COPY ziwei.html /app/ziwei.html
COPY manifest.json /app/manifest.json
COPY service-worker.js /app/service-worker.js
COPY assets /app/assets
COPY skills/ /app/skills/
RUN mkdir -p /opt/data
EXPOSE 7860
CMD ["python", "/app/app.py"]

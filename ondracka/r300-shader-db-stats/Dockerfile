# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pavel Ondračka

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV HF_DATASET_REPO=ondracka/r300-shader-db-stats-data
ENV HF_DB_FILENAME=shaderdb-web.sqlite
ENV DB_PATH=/data/shaderdb-web.sqlite

WORKDIR /app

COPY web/ /app/web/
COPY tools/r300_shaderdb_web.py /app/tools/r300_shaderdb_web.py
COPY start.py /app/start.py
COPY README.md /app/README.md

RUN mkdir -p /data

EXPOSE 7860

CMD ["python3", "/app/start.py"]

#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pavel Ondračka
"""Start the Hugging Face Space server, downloading the public DB."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


CHUNK_SIZE = 8 * 1024 * 1024


def db_url() -> str:
    explicit = os.environ.get("DB_URL")
    if explicit:
        return explicit
    repo = os.environ.get("HF_DATASET_REPO", "ondracka/r300-shader-db-stats-data")
    filename = os.environ.get("HF_DB_FILENAME", "shaderdb-web.sqlite")
    return f"https://huggingface.co/datasets/{repo}/resolve/main/{filename}"


def download_db(path: Path) -> None:
    url = db_url()
    tmp = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading database from {url}", flush=True)
    start = time.monotonic()
    try:
        with urlopen(url, timeout=60) as response, tmp.open("wb") as out:
            shutil.copyfileobj(response, out, length=CHUNK_SIZE)
    except (HTTPError, URLError, TimeoutError) as exc:
        if tmp.exists():
            tmp.unlink()
        raise SystemExit(f"failed to download database: {exc}") from exc
    tmp.replace(path)
    elapsed = time.monotonic() - start
    size_gb = path.stat().st_size / 1024**3
    print(f"Downloaded {size_gb:.2f} GiB in {elapsed:.1f}s", flush=True)


def main() -> None:
    db_path = Path(os.environ.get("DB_PATH", "/data/shaderdb-web.sqlite"))
    download_db(db_path)

    port = os.environ.get("PORT", "7860")
    args = [
        "python3",
        "/app/tools/r300_shaderdb_web.py",
        "--db",
        str(db_path),
        "--web-root",
        "/app/web",
        "--host",
        "0.0.0.0",
        "--port",
        port,
    ]
    os.execvp(args[0], args)


if __name__ == "__main__":
    main()

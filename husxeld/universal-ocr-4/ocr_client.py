#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
import uuid
from pathlib import Path
from urllib import error, request


def api_json(method: str, url: str, token: str | None = None, data: bytes | None = None, headers: dict[str, str] | None = None, timeout: float = 60) -> dict:
    h = {"Accept": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if headers:
        h.update(headers)
    req = request.Request(url, data=data, headers=h, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code}: {body}") from exc


def multipart(file_path: Path, fields: dict[str, str]) -> tuple[bytes, str]:
    boundary = f"----OCRAutomation{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for key, value in fields.items():
        parts += [f"--{boundary}\r\n".encode(), f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(), str(value).encode(), b"\r\n"]
    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    parts += [
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'.encode(),
        f"Content-Type: {mime}\r\n\r\n".encode(),
        file_path.read_bytes(),
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(parts), boundary


def submit(args: argparse.Namespace) -> str:
    base = args.base_url.rstrip("/")
    token = args.token or os.getenv("HF_TOKEN")
    fields = {
        "engine": args.engine,
        "pages_per_chunk": str(args.pages_per_chunk),
        "concurrency": str(args.concurrency),
        "include_raw": str(args.include_raw).lower(),
    }
    if args.server_path:
        body = json.dumps(
            {
                "path": args.input,
                "engine": args.engine,
                "pages_per_chunk": args.pages_per_chunk,
                "concurrency": args.concurrency,
                "include_raw": args.include_raw,
            }
        ).encode("utf-8")
        payload = api_json("POST", f"{base}/upload-path", token, body, {"Content-Type": "application/json"})
    else:
        path = Path(args.input)
        if not path.exists() or not path.is_file():
            raise SystemExit(f"Input file not found: {path}")
        body, boundary = multipart(path, fields)
        payload = api_json("POST", f"{base}/upload", token, body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return payload["job_id"]


def wait_result(args: argparse.Namespace, job_id: str) -> dict:
    base = args.base_url.rstrip("/")
    token = args.token or os.getenv("HF_TOKEN")
    while True:
        payload = api_json("GET", f"{base}/status/{job_id}", token, timeout=args.timeout)
        status = payload.get("status")
        progress = payload.get("progress") or {}
        print(f"{job_id}: {status} - {progress.get('message', '')}", file=sys.stderr)
        if status == "completed":
            return payload["result"]
        if status == "failed":
            raise SystemExit(f"OCR failed: {payload.get('error')}")
        time.sleep(args.poll_interval)


def result_text(result: dict) -> str:
    lines = []
    for page in result.get("pages") or []:
        lines.append(f"===== Page {page.get('page')} =====")
        lines.append((page.get("content") or "").strip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="OCR Automation API client")
    parser.add_argument("input", help="Local file path, or server absolute path with --server-path")
    parser.add_argument("-o", "--output", default="ocr-result.json")
    parser.add_argument("--base-url", default="http://127.0.0.1:4033")
    parser.add_argument("--token", default=None, help="Bearer token for private HF Space; default HF_TOKEN")
    parser.add_argument("--server-path", action="store_true", help="Send input as server/container path instead of uploading bytes")
    parser.add_argument("--engine", default="auto", choices=["auto", "olmocr-web", "pdf-text"])
    parser.add_argument("--pages-per-chunk", type=int, default=6)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--include-raw", action="store_true")
    parser.add_argument("--poll-interval", type=float, default=3)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--text", help="Optional .txt output path")
    args = parser.parse_args()

    job_id = submit(args)
    result = wait_result(args, job_id)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.text:
        Path(args.text).write_text(result_text(result), encoding="utf-8")
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()

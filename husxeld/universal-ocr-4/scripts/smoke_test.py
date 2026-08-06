#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib import error, request

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def write_minimal_text_pdf(path: Path, text: str) -> None:
    """Create a tiny one-page PDF with selectable text and no external deps."""
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 24 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1", errors="replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{i} 0 obj\n".encode("ascii"))
        out.extend(obj)
        out.extend(b"\nendobj\n")
    xref = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(bytes(out))


def http_json(method: str, url: str, data: bytes | None = None, headers: dict[str, str] | None = None, timeout: float = 10) -> dict:
    req = request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {url}: {body}") from exc


def http_text(method: str, url: str, timeout: float = 10) -> str:
    req = request.Request(url, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {url}: {body}") from exc


def wait_health(base_url: str, timeout: float = 30) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            payload = http_json("GET", f"{base_url}/health", timeout=3)
            if payload.get("status") == "ok":
                return
            last = str(payload)
        except Exception as exc:
            last = str(exc)
        time.sleep(0.7)
    raise RuntimeError(f"Server did not become healthy at {base_url}: {last}")


def multipart(fields: dict[str, str], file_field: str, file_path: Path) -> tuple[bytes, str]:
    boundary = f"----SmokeBoundary{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for key, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        parts.append(str(value).encode())
        parts.append(b"\r\n")
    mime = mimetypes.guess_type(file_path.name)[0] or "application/pdf"
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'.encode()
    )
    parts.append(f"Content-Type: {mime}\r\n\r\n".encode())
    parts.append(file_path.read_bytes())
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), boundary


def upload_file(base_url: str, pdf_path: Path) -> str:
    body, boundary = multipart(
        {"engine": "pdf-text", "pages_per_chunk": "6", "concurrency": "1", "include_raw": "false"},
        "file",
        pdf_path,
    )
    payload = http_json(
        "POST",
        f"{base_url}/upload",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        timeout=15,
    )
    return payload["job_id"]


def upload_path(base_url: str, pdf_path: Path) -> str:
    body = json.dumps(
        {"path": str(pdf_path), "engine": "pdf-text", "pages_per_chunk": 6, "concurrency": 1, "include_raw": False}
    ).encode("utf-8")
    payload = http_json(
        "POST",
        f"{base_url}/upload-path",
        data=body,
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    return payload["job_id"]


def assert_sanitized_content(base_url: str, job_id: str, result: dict, expected: str) -> None:
    sanitized = result.get("sanitized_text") or ""
    if "\n" in sanitized or "\r" in sanitized:
        raise RuntimeError("sanitized_text contains newline characters")
    if expected not in sanitized:
        raise RuntimeError("expected text missing from sanitized_text")
    content = http_text("GET", f"{base_url}/download/{job_id}/content")
    if "\n" in content or "\r" in content:
        raise RuntimeError("content.txt download contains newline characters")
    if expected not in content:
        raise RuntimeError("expected text missing from content.txt download")


def wait_result(base_url: str, job_id: str, expected: str, timeout: float = 30) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = http_json("GET", f"{base_url}/status/{job_id}", timeout=10)
        if last.get("status") == "completed":
            result = last["result"]
            combined = result.get("combined_text") or ""
            if expected not in combined:
                raise RuntimeError(f"Expected text not found in result: {combined!r}")
            return result
        if last.get("status") == "failed":
            raise RuntimeError(f"Job failed: {last.get('error')}")
        time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for {job_id}. Last status: {last}")


def assert_bad_embedded_text_detection() -> None:
    from app.main import assess_embedded_text_quality

    fake_pages = [
        {"page": i, "content": "History – BY : Khan SirKHAN GLOBAL STUDIES  1883  1891 "}
        for i in range(1, 59)
    ]
    quality = assess_embedded_text_quality(fake_pages, 58)
    if quality["usable"]:
        raise RuntimeError(f"bad embedded text quality was incorrectly accepted: {quality}")


def main() -> None:
    assert_bad_embedded_text_detection()
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:4033")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    wait_health(base_url)
    expected = "Hello OCR Automation Smoke Test"
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "smoke.pdf"
        write_minimal_text_pdf(pdf_path, expected)

        file_job = upload_file(base_url, pdf_path)
        file_result = wait_result(base_url, file_job, expected)
        assert_sanitized_content(base_url, file_job, file_result, expected)
        print(f"upload OK job={file_job} engine={file_result['metadata']['engine_used']} clean_chars={file_result['stats']['sanitized_characters']}")

        path_job = upload_path(base_url, pdf_path.resolve())
        path_result = wait_result(base_url, path_job, expected)
        assert_sanitized_content(base_url, path_job, path_result, expected)
        print(f"path OK job={path_job} engine={path_result['metadata']['engine_used']} clean_chars={path_result['stats']['sanitized_characters']}")

        uploads = http_json("GET", f"{base_url}/uploads")
        if not uploads.get("items"):
            raise RuntimeError("/uploads returned no items")
        catalog = http_json("GET", f"{base_url}/ai/catalog")
        if "providers" not in catalog:
            raise RuntimeError("/ai/catalog missing providers")

    print("smoke test passed")


if __name__ == "__main__":
    main()

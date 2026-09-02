"""Extract RICS Home Survey report content via LlamaParse (LlamaCloud).

Library used by live ingest (``PDF_EXTRACTOR=llamaparse``) and by the CLI
wrapper ``scripts/rics_llamaparse_extract.py``.

Reads ``LLAMA_CLOUD_API_KEY`` (or ``LLAMA_PARSE_API_KEY``) from the environment,
optional ``--api-key``, or the repo ``.env``.

Requires one of:
  pip install "llama-cloud>=2.1"
  pip install llama-parse          # legacy fallback
  (or neither — uses stdlib REST against api.cloud.llamaindex.ai)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.config import REPO_ROOT

_API_BASE = "https://api.cloud.llamaindex.ai"
_DEFAULT_TIER = "agentic"
_RICS_PARSE_HINT = (
    "This document is a RICS Home Survey Level 3 report. "
    # Parser prompt wording, not an internal constant.
    "Preserve section codes (A-N, D1-J5, etc.), "
    "condition ratings (1/2/3), "  # rics-literal-ok
    "tables, and headings exactly. Do not invent missing sections."
)


# ---------------------------------------------------------------------------
# Env / .env
# ---------------------------------------------------------------------------


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def resolve_api_key(cli_key: str | None) -> str:
    _load_dotenv(REPO_ROOT / ".env")
    _load_dotenv(Path.cwd() / ".env")
    key = (
        (cli_key or "").strip()
        or os.environ.get("LLAMA_CLOUD_API_KEY", "").strip()
        or os.environ.get("LLAMA_PARSE_API_KEY", "").strip()
    )
    if not key:
        raise SystemExit(
            "Missing API key. Set LLAMA_CLOUD_API_KEY (or LLAMA_PARSE_API_KEY), "
            "add it to .env, or pass --api-key."
        )
    return key


# ---------------------------------------------------------------------------
# Backend: llama-cloud SDK
# ---------------------------------------------------------------------------


def parse_with_llama_cloud(
    pdf_path: Path,
    *,
    api_key: str,
    tier: str,
    version: str,
) -> dict[str, Any]:
    from llama_cloud import LlamaCloud  # type: ignore[import-not-found]

    client = LlamaCloud(api_key=api_key)
    uploaded = client.files.create(file=str(pdf_path), purpose="parse")
    file_id = getattr(uploaded, "id", None) or uploaded["id"]

    kwargs: dict[str, Any] = {
        "file_id": file_id,
        "tier": tier,
        "version": version,
        "expand": ["markdown", "text"],
        "processing_options": {
            "ocr_parameters": {"languages": ["en"]},
        },
        "output_options": {
            "markdown": {"tables": {"output_tables_as_markdown": True}},
        },
    }
    # Best-effort: some SDK versions accept custom instructions under input/processing.
    try:
        result = client.parsing.parse(
            **kwargs,
            input_options={"custom_prompt": _RICS_PARSE_HINT},
        )
    except TypeError:
        result = client.parsing.parse(**kwargs)

    return _normalize_sdk_result(result, engine="llama_cloud", file_id=str(file_id))


def _normalize_sdk_result(result: Any, *, engine: str, file_id: str) -> dict[str, Any]:
    md_pages: list[str] = []
    text_pages: list[str] = []

    markdown = getattr(result, "markdown", None)
    if markdown is not None:
        pages = getattr(markdown, "pages", None) or []
        for page in pages:
            md = getattr(page, "markdown", None)
            if md is None and isinstance(page, dict):
                md = page.get("markdown")
            if md:
                md_pages.append(str(md))

    text_obj = getattr(result, "text", None)
    if text_obj is not None:
        pages = getattr(text_obj, "pages", None) or []
        for page in pages:
            t = getattr(page, "text", None)
            if t is None and isinstance(page, dict):
                t = page.get("text")
            if t:
                text_pages.append(str(t))

    # Some SDK shapes expose a single combined string.
    if not md_pages:
        for attr in ("markdown", "md"):
            val = getattr(result, attr, None)
            if isinstance(val, str) and val.strip():
                md_pages = [val]
                break

    job_id = getattr(result, "id", None) or getattr(result, "job_id", None) or ""
    status = getattr(result, "status", None) or "COMPLETED"

    markdown_full = "\n\n".join(md_pages).strip()
    text_full = "\n\n".join(text_pages).strip() or markdown_full

    return {
        "engine": engine,
        "file_id": file_id,
        "job_id": str(job_id),
        "status": str(status),
        "page_count": max(len(md_pages), len(text_pages), 1 if markdown_full else 0),
        "markdown": markdown_full,
        "text": text_full,
        "pages_markdown": md_pages,
        "pages_text": text_pages,
        "raw": _safe_jsonable(result),
    }


# ---------------------------------------------------------------------------
# Backend: legacy llama-parse
# ---------------------------------------------------------------------------


def parse_with_llama_parse(
    pdf_path: Path,
    *,
    api_key: str,
    result_type: str = "markdown",
) -> dict[str, Any]:
    from llama_parse import LlamaParse  # type: ignore[import-not-found]

    parser = LlamaParse(
        api_key=api_key,
        result_type=result_type,
        parsing_instruction=_RICS_PARSE_HINT,
        language="en",
    )
    docs = parser.load_data(str(pdf_path))
    pages_md = [getattr(d, "text", "") or "" for d in docs]
    markdown_full = "\n\n".join(p for p in pages_md if p.strip()).strip()
    return {
        "engine": "llama_parse",
        "file_id": "",
        "job_id": "",
        "status": "COMPLETED",
        "page_count": len(pages_md),
        "markdown": markdown_full,
        "text": markdown_full,
        "pages_markdown": pages_md,
        "pages_text": pages_md,
        "raw": {"document_count": len(docs)},
    }


# ---------------------------------------------------------------------------
# Backend: REST (stdlib)
# ---------------------------------------------------------------------------


def parse_with_rest(
    pdf_path: Path,
    *,
    api_key: str,
    tier: str,
    version: str,
    poll_interval: float = 3.0,
    timeout_s: float = 900.0,
) -> dict[str, Any]:
    file_id = _rest_upload(pdf_path, api_key=api_key)
    job_id = _rest_start_parse(file_id, api_key=api_key, tier=tier, version=version)

    deadline = time.monotonic() + timeout_s
    payload: dict[str, Any] = {}
    while time.monotonic() < deadline:
        payload = _rest_get_result(job_id, api_key=api_key, expand=("markdown", "text"))
        status = str(
            payload.get("status")
            or (payload.get("job") or {}).get("status")
            or ""
        ).upper()
        if status in {"COMPLETED", "SUCCESS", "DONE"}:
            break
        if status in {"FAILED", "ERROR", "CANCELLED"}:
            raise RuntimeError(f"LlamaParse job failed: {json.dumps(payload)[:800]}")
        time.sleep(poll_interval)
    else:
        raise TimeoutError(f"LlamaParse job timed out after {timeout_s:.0f}s (job_id={job_id})")

    md_pages, text_pages = _rest_extract_pages(payload)
    markdown_full = "\n\n".join(md_pages).strip()
    text_full = "\n\n".join(text_pages).strip() or markdown_full
    return {
        "engine": "rest",
        "file_id": file_id,
        "job_id": job_id,
        "status": "COMPLETED",
        "page_count": max(len(md_pages), len(text_pages), 1 if markdown_full else 0),
        "markdown": markdown_full,
        "text": text_full,
        "pages_markdown": md_pages,
        "pages_text": text_pages,
        "raw": payload,
    }


def _rest_headers(api_key: str, *, json_body: bool = False) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def _rest_upload(pdf_path: Path, *, api_key: str) -> str:
    boundary = f"----llamaparse{int(time.time() * 1000)}"
    filename = pdf_path.name
    file_bytes = pdf_path.read_bytes()
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="purpose"\r\n\r\n',
            b"parse\r\n",
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="file"; '
                f'filename="{filename}"\r\n'
            ).encode(),
            b"Content-Type: application/pdf\r\n\r\n",
            file_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    req = urllib.request.Request(
        f"{_API_BASE}/api/v1/beta/files",
        data=body,
        headers={
            **_rest_headers(api_key),
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    file_id = data.get("id")
    if not file_id:
        raise RuntimeError(f"Upload response missing id: {data}")
    return str(file_id)


def _rest_start_parse(
    file_id: str, *, api_key: str, tier: str, version: str
) -> str:
    payload = {
        "file_id": file_id,
        "tier": tier,
        "version": version,
        "processing_options": {
            "ocr_parameters": {"languages": ["en"]},
        },
        "output_options": {
            "markdown": {"tables": {"output_tables_as_markdown": True}},
        },
    }
    req = urllib.request.Request(
        f"{_API_BASE}/api/v2/parse",
        data=json.dumps(payload).encode("utf-8"),
        headers=_rest_headers(api_key, json_body=True),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    job_id = data.get("id") or data.get("job_id")
    if not job_id:
        raise RuntimeError(f"Parse start response missing id: {data}")
    return str(job_id)


def _rest_get_result(
    job_id: str, *, api_key: str, expand: tuple[str, ...]
) -> dict[str, Any]:
    qs = urllib.parse.urlencode({"expand": ",".join(expand)})
    req = urllib.request.Request(
        f"{_API_BASE}/api/v2/parse/{job_id}?{qs}",
        headers=_rest_headers(api_key),
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _rest_extract_pages(payload: dict[str, Any]) -> tuple[list[str], list[str]]:
    md_pages: list[str] = []
    text_pages: list[str] = []

    md = payload.get("markdown") or {}
    if isinstance(md, dict):
        for page in md.get("pages") or []:
            if isinstance(page, dict) and page.get("markdown"):
                md_pages.append(str(page["markdown"]))
    elif isinstance(md, str) and md.strip():
        md_pages = [md]

    text = payload.get("text") or {}
    if isinstance(text, dict):
        for page in text.get("pages") or []:
            if isinstance(page, dict) and page.get("text"):
                text_pages.append(str(page["text"]))
    elif isinstance(text, str) and text.strip():
        text_pages = [text]

    return md_pages, text_pages


def _safe_jsonable(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _safe_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_jsonable(v) for v in obj]
    model_dump = getattr(obj, "model_dump", None)
    if callable(model_dump):
        try:
            return _safe_jsonable(model_dump())
        except Exception:
            pass
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        try:
            return _safe_jsonable(to_dict())
        except Exception:
            pass
    return str(obj)


# ---------------------------------------------------------------------------
# Optional RICS sectioning (reuse project chunker when available)
# ---------------------------------------------------------------------------


def segment_rics(markdown: str, *, source_filename: str) -> dict[str, Any]:
    try:
        from backend.domain.rics_level3_schema import (  # type: ignore[import-not-found]
            build_canonical_template_schema,
        )
        from backend.rag.reference_chunker import (  # type: ignore[import-not-found]
            build_reference_chunks,
        )

        schema = build_canonical_template_schema(source_filename="RICS_L3_CANONICAL")
        valid_ids = set(schema.section_ids())
        valid_ids |= {s.id[0].upper() for s in schema.sections if s.id}
        chunks = build_reference_chunks(
            markdown,
            source_filename=source_filename,
            valid_section_ids=valid_ids,
        )
        rows = [
            {
                "chunk_id": c.chunk_id,
                "section_id": c.section_id,
                "paragraph_index": c.paragraph_index,
                "content_role": c.content_role,
                "parent_id": c.parent_id,
                "text": c.text,
            }
            for c in chunks
        ]
        return {
            "method": "backend.reference_chunker",
            "chunk_count": len(rows),
            "sections": sorted(
                {r["section_id"] for r in rows if r.get("section_id")}
            ),
            "chunks": rows,
        }
    except Exception as exc:
        return {
            "method": "unavailable",
            "error": str(exc),
            "chunk_count": 0,
            "sections": [],
            "chunks": [],
        }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def parse_rics_pdf(
    pdf_path: Path,
    *,
    api_key: str,
    tier: str,
    version: str,
    engine: str,
) -> dict[str, Any]:
    errors: list[str] = []

    order = (
        ["llama_cloud", "llama_parse", "rest"]
        if engine == "auto"
        else [engine]
    )

    for name in order:
        try:
            if name == "llama_cloud":
                return parse_with_llama_cloud(
                    pdf_path, api_key=api_key, tier=tier, version=version
                )
            if name == "llama_parse":
                return parse_with_llama_parse(pdf_path, api_key=api_key)
            if name == "rest":
                return parse_with_rest(
                    pdf_path, api_key=api_key, tier=tier, version=version
                )
        except ImportError as exc:
            errors.append(f"{name}: missing package ({exc})")
        except Exception as exc:
            errors.append(f"{name}: {exc}")

    raise RuntimeError(
        "All LlamaParse backends failed:\n- " + "\n- ".join(errors)
    )


def write_outputs(
    *,
    pdf_path: Path,
    out_dir: Path,
    parsed: dict[str, Any],
    rics: dict[str, Any] | None,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem
    written: dict[str, Path] = {}

    md_path = out_dir / f"{stem}.llamaparse.md"
    md_path.write_text(parsed["markdown"] or "", encoding="utf-8")
    written["markdown"] = md_path

    txt_path = out_dir / f"{stem}.llamaparse.txt"
    txt_path.write_text(parsed["text"] or "", encoding="utf-8")
    written["text"] = txt_path

    manifest = {
        "source_pdf": str(pdf_path.resolve()),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "engine": parsed["engine"],
        "file_id": parsed.get("file_id"),
        "job_id": parsed.get("job_id"),
        "status": parsed.get("status"),
        "page_count": parsed.get("page_count"),
        "outputs": {k: str(v.resolve()) for k, v in written.items()},
        "rics": rics,
    }
    # Keep raw payload but avoid dumping huge duplicate markdown twice.
    raw = dict(parsed.get("raw") or {})
    if isinstance(raw, dict):
        raw.pop("markdown", None)
        raw.pop("text", None)
    manifest["raw_meta"] = raw

    json_path = out_dir / f"{stem}.llamaparse.json"
    json_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    written["json"] = json_path

    if rics and rics.get("chunks"):
        rics_path = out_dir / f"{stem}.rics_chunks.json"
        rics_path.write_text(
            json.dumps(rics, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        written["rics_chunks"] = rics_path

    return written


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Extract RICS report content with LlamaParse (LlamaCloud API)."
    )
    p.add_argument("pdfs", nargs="+", type=Path, help="RICS report PDF path(s)")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output directory (default: <pdf_dir>/<stem>_llamaparse)",
    )
    p.add_argument(
        "--api-key",
        default=None,
        help="LlamaCloud API key (else LLAMA_CLOUD_API_KEY / .env)",
    )
    p.add_argument(
        "--tier",
        default=_DEFAULT_TIER,
        choices=("agentic", "agentic_plus", "cost_effective", "fast"),
        help="Parse tier (default: agentic)",
    )
    p.add_argument(
        "--version",
        default="latest",
        help="Parse model version (default: latest)",
    )
    p.add_argument(
        "--engine",
        choices=("auto", "llama_cloud", "llama_parse", "rest"),
        default="auto",
        help="Backend (default: auto = try SDK then REST)",
    )
    p.add_argument(
        "--rics",
        action="store_true",
        help="Also segment parsed markdown into RICS L3 section chunks",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    api_key = resolve_api_key(args.api_key)

    pdfs = [p for p in args.pdfs if p.is_file() and p.suffix.lower() == ".pdf"]
    for p in args.pdfs:
        if not p.is_file():
            print(f"Error: not found: {p}", file=sys.stderr)
        elif p.suffix.lower() != ".pdf":
            print(f"Warning: skipping non-PDF: {p}", file=sys.stderr)
    if not pdfs:
        print("Error: no PDF files to process.", file=sys.stderr)
        return 1

    ok = 0
    for pdf in pdfs:
        out_dir = args.output
        if out_dir is None:
            out_dir = pdf.parent / f"{pdf.stem}_llamaparse"
        elif len(pdfs) > 1:
            out_dir = out_dir / pdf.stem

        print(f"Parsing {pdf.name} via LlamaParse ({args.engine}/{args.tier}) ...")
        try:
            parsed = parse_rics_pdf(
                pdf,
                api_key=api_key,
                tier=args.tier,
                version=args.version,
                engine=args.engine,
            )
        except (RuntimeError, TimeoutError, urllib.error.URLError) as exc:
            print(f"  Error: {exc}", file=sys.stderr)
            continue

        rics = None
        if args.rics:
            print("  Segmenting into RICS L3 sections ...")
            rics = segment_rics(parsed["markdown"] or parsed["text"], source_filename=pdf.name)

        written = write_outputs(
            pdf_path=pdf, out_dir=out_dir, parsed=parsed, rics=rics
        )
        ok += 1
        print(f"  engine={parsed['engine']} pages~{parsed['page_count']}")
        print(f"  out: {out_dir.resolve()}")
        for kind, path in written.items():
            print(f"    {kind}: {path.name} ({path.stat().st_size} bytes)")
        if rics:
            print(
                f"    rics: {rics.get('chunk_count', 0)} chunk(s), "
                f"{len(rics.get('sections') or [])} section(s) "
                f"via {rics.get('method')}"
            )

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

# ---------------------------------------------------------------------------
# Run examples (from Report-genius-ai repo root, with LLAMA_CLOUD_API_KEY set):
#
#   python scripts/rics_llamaparse_extract.py "E:\my report ai\5 Hillcrest Avenue, Pinner, HA5 1AJ.pdf" -o "E:\my report ai\out_llamaparse"
#
#   python scripts/rics_llamaparse_extract.py "E:\my report ai\1a Woodland Hill London SE19 1PB.pdf" -o "E:\my report ai\out_llamaparse" --tier agentic
#
# Prefer the one-shot pipeline (parse + chunk):
#   python scripts/rics_pdf_to_chunks.py "E:\my report ai\1a Woodland Hill London SE19 1PB.pdf" -o "E:\my report ai\out_llamaparse" --regex-only --one-chunk-per-section
#
# Textract equivalent (AWS credentials + AWS_S3_BUCKET):
#   python scripts/pdf_textract_extract.py "E:\my report ai\1a Woodland Hill London SE19 1PB.pdf" -o "E:\my report ai\out_textract"
#   python scripts/rics_pdf_textract_to_chunks.py "E:\my report ai\1a Woodland Hill London SE19 1PB.pdf" -o "E:\my report ai\out_textract" --regex-only --one-chunk-per-section
# ---------------------------------------------------------------------------

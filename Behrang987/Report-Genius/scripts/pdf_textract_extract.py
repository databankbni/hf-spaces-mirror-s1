#!/usr/bin/env python3
"""Extract text from a PDF using Amazon Textract.

Multi-page PDFs use the async API (S3 upload -> StartDocumentTextDetection ->
poll GetDocumentTextDetection). Single-page images can use sync DetectDocumentText.

Usage (from repo root):
  pip install boto3

  # Local PDF (uploads to S3, then runs Textract)
  set AWS_REGION=eu-west-2
  set AWS_S3_BUCKET=rics-report-storage
  python scripts/pdf_textract_extract.py "E:\\path\\report.pdf" -o ./out_textract

  # Already on S3
  python scripts/pdf_textract_extract.py s3://your-bucket/reports/report.pdf -o ./out

Env:
  AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN (or IAM role / profile)
  AWS_REGION or AWS_DEFAULT_REGION
  AWS_S3_BUCKET (or TEXTRACT_S3_BUCKET)  required when input is a local file
  TEXTRACT_S3_PREFIX   optional key prefix (default: textract-input/)
  AWS_PROFILE          optional named profile
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _load_dotenv() -> None:
    for path in (_REPO_ROOT / ".env", Path.cwd() / ".env"):
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


def _require_boto3():
    try:
        import boto3  # noqa: F401
    except ImportError as exc:
        raise SystemExit("boto3 is required: pip install boto3") from exc
    return __import__("boto3")


def _clients(*, region: str, profile: str | None):
    boto3 = _require_boto3()
    session = (
        boto3.Session(profile_name=profile, region_name=region)
        if profile
        else boto3.Session(region_name=region)
    )
    return session.client("textract"), session.client("s3")


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.lstrip("/"):
        raise ValueError(f"Invalid S3 URI: {uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def _resolve_region(cli_region: str | None) -> str:
    region = (
        (cli_region or "").strip()
        or os.environ.get("AWS_REGION", "").strip()
        or os.environ.get("AWS_DEFAULT_REGION", "").strip()
    )
    if not region:
        raise SystemExit(
            "Missing AWS region. Set AWS_REGION / AWS_DEFAULT_REGION or pass --region."
        )
    return region


def upload_local_pdf(
    s3,
    pdf_path: Path,
    *,
    bucket: str,
    prefix: str,
) -> tuple[str, str]:
    """Upload local PDF to S3; return (bucket, key)."""
    safe_name = pdf_path.name.replace(" ", "_")
    key = f"{prefix.rstrip('/')}/{uuid.uuid4().hex}_{safe_name}"
    print(f"Uploading {pdf_path.name} -> s3://{bucket}/{key}")
    s3.upload_file(
        str(pdf_path),
        bucket,
        key,
        ExtraArgs={"ContentType": "application/pdf"},
    )
    return bucket, key


def start_text_detection(textract, *, bucket: str, key: str) -> str:
    resp = textract.start_document_text_detection(
        DocumentLocation={"S3Object": {"Bucket": bucket, "Name": key}},
        # Avoid slashes/spaces in JobTag (Textract rejects them).
        JobTag=f"pdf-{uuid.uuid4().hex[:12]}",
    )
    job_id = resp["JobId"]
    print(f"Textract job started: {job_id}")
    return job_id


def start_document_analysis(textract, *, bucket: str, key: str) -> str:
    """Forms + tables analysis (async)."""
    resp = textract.start_document_analysis(
        DocumentLocation={"S3Object": {"Bucket": bucket, "Name": key}},
        FeatureTypes=["TABLES", "FORMS"],
        JobTag=f"pdf-{uuid.uuid4().hex[:12]}",
    )
    job_id = resp["JobId"]
    print(f"Textract analysis job started: {job_id}")
    return job_id


def _poll_job(
    fetch_page,
    *,
    job_id: str,
    poll_seconds: float,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    """Poll Get* until SUCCEEDED; return all Blocks across pages."""
    deadline = time.monotonic() + timeout_seconds
    next_token: str | None = None
    blocks: list[dict[str, Any]] = []
    status = "IN_PROGRESS"

    while True:
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"Textract job {job_id} timed out after {timeout_seconds:.0f}s "
                f"(last status={status})"
            )
        kwargs: dict[str, Any] = {"JobId": job_id}
        if next_token:
            kwargs["NextToken"] = next_token
        resp = fetch_page(**kwargs)
        status = resp.get("JobStatus") or status
        if status == "FAILED":
            raise RuntimeError(
                f"Textract job failed: {resp.get('StatusMessage') or resp}"
            )
        if status in {"SUCCEEDED", "PARTIAL_SUCCESS"}:
            blocks.extend(resp.get("Blocks") or [])
            next_token = resp.get("NextToken")
            if not next_token:
                return blocks
            continue
        # Still running — wait before first result page.
        print(f"  status={status}; waiting {poll_seconds:.0f}s ...")
        time.sleep(poll_seconds)


def poll_text_detection(
    textract,
    job_id: str,
    *,
    poll_seconds: float = 5.0,
    timeout_seconds: float = 1800.0,
) -> list[dict[str, Any]]:
    return _poll_job(
        lambda **kw: textract.get_document_text_detection(**kw),
        job_id=job_id,
        poll_seconds=poll_seconds,
        timeout_seconds=timeout_seconds,
    )


def poll_document_analysis(
    textract,
    job_id: str,
    *,
    poll_seconds: float = 5.0,
    timeout_seconds: float = 1800.0,
) -> list[dict[str, Any]]:
    return _poll_job(
        lambda **kw: textract.get_document_analysis(**kw),
        job_id=job_id,
        poll_seconds=poll_seconds,
        timeout_seconds=timeout_seconds,
    )


def blocks_to_pages(blocks: list[dict[str, Any]]) -> dict[int, list[str]]:
    """Group LINE text by Page (1-based)."""
    pages: dict[int, list[str]] = {}
    for block in blocks:
        if block.get("BlockType") != "LINE":
            continue
        page = int(block.get("Page") or 1)
        text = (block.get("Text") or "").rstrip()
        if text:
            pages.setdefault(page, []).append(text)
    return dict(sorted(pages.items()))


def pages_to_text(pages: dict[int, list[str]]) -> str:
    from backend.ingest.text_reflow import unwrap_soft_line_breaks

    parts: list[str] = []
    for page_no, lines in pages.items():
        parts.append(f"----- Page {page_no} -----")
        # Unwrap PDF hard-wraps inside the page so prose matches LlamaParse style.
        parts.append(unwrap_soft_line_breaks("\n".join(lines)))
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def pages_to_markdown(pages: dict[int, list[str]], *, title: str) -> str:
    from backend.ingest.text_reflow import unwrap_soft_line_breaks

    parts: list[str] = [f"# {title}", ""]
    for page_no, lines in pages.items():
        parts.append(f"## Page {page_no}")
        parts.append("")
        parts.append(unwrap_soft_line_breaks("\n".join(lines)))
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def extract_pdf(
    pdf: str | Path,
    *,
    region: str,
    profile: str | None,
    bucket: str | None,
    prefix: str,
    analyze: bool,
    keep_s3: bool,
    poll_seconds: float,
    timeout_seconds: float,
) -> dict[str, Any]:
    textract, s3 = _clients(region=region, profile=profile)
    uploaded = False
    source_label: str

    if isinstance(pdf, str) and pdf.lower().startswith("s3://"):
        bucket_name, key = _parse_s3_uri(pdf)
        source_label = pdf
    else:
        pdf_path = Path(pdf)
        if not pdf_path.is_file():
            raise FileNotFoundError(pdf_path)
        if not bucket:
            raise SystemExit(
                "Local PDF requires AWS_S3_BUCKET / TEXTRACT_S3_BUCKET (or --bucket). "
                "Textract async PDF processing reads from S3."
            )
        bucket_name, key = upload_local_pdf(
            s3, pdf_path, bucket=bucket, prefix=prefix
        )
        uploaded = True
        source_label = str(pdf_path.resolve())

    if analyze:
        job_id = start_document_analysis(textract, bucket=bucket_name, key=key)
        blocks = poll_document_analysis(
            textract,
            job_id,
            poll_seconds=poll_seconds,
            timeout_seconds=timeout_seconds,
        )
        mode = "analysis"
    else:
        job_id = start_text_detection(textract, bucket=bucket_name, key=key)
        blocks = poll_text_detection(
            textract,
            job_id,
            poll_seconds=poll_seconds,
            timeout_seconds=timeout_seconds,
        )
        mode = "text_detection"

    pages = blocks_to_pages(blocks)
    if uploaded and not keep_s3:
        try:
            s3.delete_object(Bucket=bucket_name, Key=key)
            print(f"Deleted temp s3://{bucket_name}/{key}")
        except Exception as exc:  # noqa: BLE001 — best-effort cleanup
            print(f"Warning: could not delete s3 object: {exc}", file=sys.stderr)

    return {
        "source": source_label,
        "s3_bucket": bucket_name,
        "s3_key": key,
        "job_id": job_id,
        "mode": mode,
        "region": region,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "page_count": len(pages) or max((int(b.get("Page") or 0) for b in blocks), default=0),
        "line_count": sum(len(v) for v in pages.values()),
        "pages": {str(k): v for k, v in pages.items()},
        "text": pages_to_text(pages),
        "block_count": len(blocks),
    }


def write_outputs(result: dict[str, Any], out_dir: Path, stem: str) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    txt_path = out_dir / f"{stem}.textract.txt"
    txt_path.write_text(result["text"], encoding="utf-8")
    written["text"] = txt_path

    md_path = out_dir / f"{stem}.textract.md"
    md_path.write_text(
        pages_to_markdown(
            {int(k): v for k, v in result["pages"].items()},
            title=stem,
        ),
        encoding="utf-8",
    )
    written["markdown"] = md_path

    meta = {k: v for k, v in result.items() if k != "text"}
    json_path = out_dir / f"{stem}.textract.json"
    json_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    written["json"] = json_path
    return written


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Extract PDF text with Amazon Textract (async S3 pipeline)."
    )
    p.add_argument(
        "pdf",
        type=str,
        help="Local PDF path or s3://bucket/key.pdf",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output directory (default: <pdf_dir>/<stem>_textract)",
    )
    p.add_argument("--region", default=None, help="AWS region (else AWS_REGION)")
    p.add_argument("--profile", default=None, help="AWS named profile")
    p.add_argument(
        "--bucket",
        default=None,
        help="S3 bucket for local uploads (else AWS_S3_BUCKET / TEXTRACT_S3_BUCKET)",
    )
    p.add_argument(
        "--prefix",
        default=None,
        help="S3 key prefix (else TEXTRACT_S3_PREFIX / textract-input/)",
    )
    p.add_argument(
        "--analyze",
        action="store_true",
        help="Use StartDocumentAnalysis (TABLES+FORMS) instead of text-only",
    )
    p.add_argument(
        "--keep-s3",
        action="store_true",
        help="Do not delete the uploaded S3 object after extraction",
    )
    p.add_argument(
        "--poll-seconds",
        type=float,
        default=5.0,
        help="Polling interval while job runs (default: 5)",
    )
    p.add_argument(
        "--timeout-seconds",
        type=float,
        default=1800.0,
        help="Max wait for Textract job (default: 1800)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    args = parse_args(argv)
    region = _resolve_region(args.region)
    profile = args.profile or os.environ.get("AWS_PROFILE") or None
    bucket = (
        args.bucket
        or os.environ.get("AWS_S3_BUCKET")
        or os.environ.get("TEXTRACT_S3_BUCKET")
        or None
    )
    prefix = (
        args.prefix
        or os.environ.get("TEXTRACT_S3_PREFIX")
        or "textract-input/"
    )

    pdf_arg = args.pdf
    if pdf_arg.lower().startswith("s3://"):
        stem = Path(urlparse(pdf_arg).path).stem or "document"
        default_out = Path.cwd() / f"{stem}_textract"
    else:
        pdf_path = Path(pdf_arg)
        if not pdf_path.is_file():
            print(f"Error: not found: {pdf_path}", file=sys.stderr)
            return 1
        if pdf_path.suffix.lower() != ".pdf":
            print(f"Warning: expected a .pdf file: {pdf_path}", file=sys.stderr)
        stem = pdf_path.stem
        default_out = pdf_path.parent / f"{stem}_textract"

    out_dir = args.output or default_out

    try:
        result = extract_pdf(
            pdf_arg,
            region=region,
            profile=profile,
            bucket=bucket,
            prefix=prefix,
            analyze=args.analyze,
            keep_s3=args.keep_s3,
            poll_seconds=args.poll_seconds,
            timeout_seconds=args.timeout_seconds,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    written = write_outputs(result, out_dir, stem)
    print(f"Done. pages~{result['page_count']} lines={result['line_count']}")
    print(f"Output: {out_dir.resolve()}")
    for kind, path in written.items():
        print(f"  {kind}: {path.name} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# ---------------------------------------------------------------------------
# Run examples (from Report-genius-ai repo root):
#
# Prerequisites (.env or shell):
#   AWS_REGION=eu-west-2
#   AWS_ACCESS_KEY_ID=...
#   AWS_SECRET_ACCESS_KEY=...
#   AWS_S3_BUCKET=rics-report-storage
#   pip install boto3   # also in backend/requirements.txt
#
# --- Textract only (writes .textract.txt / .md / .json) ---
#   python scripts/pdf_textract_extract.py "E:\my report ai\1a Woodland Hill London SE19 1PB.pdf" -o "E:\my report ai\out_textract"
#
#   python scripts/pdf_textract_extract.py "E:\my report ai\5 Hillcrest Avenue, Pinner, HA5 1AJ.pdf" -o "E:\my report ai\out_textract"
#
#   python scripts/pdf_textract_extract.py s3://rics-report-storage/reports/report.pdf -o "E:\my report ai\out_textract"
#
#   python scripts/pdf_textract_extract.py report.pdf -o ./out --analyze --keep-s3 --region eu-west-2
#
# --- One-shot: Textract + RICS section chunks ---
#   python scripts/rics_pdf_textract_to_chunks.py "E:\my report ai\1a Woodland Hill London SE19 1PB.pdf" -o "E:\my report ai\out_textract" --regex-only --one-chunk-per-section
#
#   python scripts/rics_pdf_textract_to_chunks.py "E:\my report ai\5 Hillcrest Avenue, Pinner, HA5 1AJ.pdf" -o "E:\my report ai\out_textract" --regex-only --one-chunk-per-section
#
# --- Chunk existing Textract markdown (no AWS call) ---
#   python scripts/rics_pdf_textract_to_chunks.py --from-md "E:\my report ai\out_textract\1a Woodland Hill London SE19 1PB.textract.md" -o "E:\my report ai\out_textract" --regex-only --one-chunk-per-section
#
#   python scripts/chunk_rics_text.py "E:\my report ai\out_textract\1a Woodland Hill London SE19 1PB.textract.md" -o "E:\my report ai\out_textract" --regex-only --one-chunk-per-section
#
# Outputs (extract):
#   <out>/<stem>.textract.txt
#   <out>/<stem>.textract.md
#   <out>/<stem>.textract.json
# Outputs (chunks):
#   <out>/<stem>.textract/extracted_chunks.json
#   <out>/<stem>.textract/chunks_only.json
# ---------------------------------------------------------------------------

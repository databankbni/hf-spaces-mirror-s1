#!/usr/bin/env python3
"""One-shot RICS pipeline: PDF -> Amazon Textract MD/TXT -> section chunks.

Combines ``pdf_textract_extract.py`` + ``chunk_rics_text.py`` so you do not
need two commands. Chunks the Textract markdown (same segmenters as LlamaParse).

Usage (from repo root):
  python scripts/rics_pdf_textract_to_chunks.py "E:\\path\\report.pdf" -o "E:\\my report ai\\out_textract"
  python scripts/rics_pdf_textract_to_chunks.py report.pdf -o ./out --regex-only --one-chunk-per-section

  # Chunk an already-extracted Textract markdown (skip Textract):
  python scripts/rics_pdf_textract_to_chunks.py --from-md "E:\\path\\report.textract.md" -o ./out --regex-only

Requires AWS credentials + AWS_S3_BUCKET (for local PDF upload). See
``pdf_textract_extract.py``.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


_SCRIPTS = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _load_sibling(module_name: str) -> Any:
    path = _SCRIPTS / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Parse a RICS PDF with Amazon Textract, then chunk the resulting "
            "markdown in one command."
        )
    )
    p.add_argument(
        "pdfs",
        nargs="*",
        type=str,
        help="Local PDF path(s) or s3://bucket/key.pdf",
    )
    p.add_argument(
        "--from-md",
        type=Path,
        default=None,
        help="Skip Textract; chunk this existing .textract.md (or .md/.txt)",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help=(
            "Output root (default: <pdf_dir>/<stem>_textract_rics). "
            "Writes <stem>.textract.md/.txt/.json here, and chunks under "
            "<output>/<stem>.textract/"
        ),
    )
    p.add_argument("--region", default=None, help="AWS region (else AWS_REGION)")
    p.add_argument("--profile", default=None, help="AWS named profile")
    p.add_argument(
        "--bucket",
        default=None,
        help="S3 bucket for local uploads (else AWS_S3_BUCKET)",
    )
    p.add_argument(
        "--prefix",
        default=None,
        help="S3 key prefix (else TEXTRACT_S3_PREFIX / textract-input/)",
    )
    p.add_argument(
        "--analyze",
        action="store_true",
        help="Use Textract TABLES+FORMS analysis instead of text-only",
    )
    p.add_argument(
        "--keep-s3",
        action="store_true",
        help="Do not delete uploaded S3 objects after extraction",
    )
    p.add_argument("--poll-seconds", type=float, default=5.0)
    p.add_argument("--timeout-seconds", type=float, default=1800.0)
    p.add_argument(
        "--regex-only",
        action="store_true",
        help="Chunk with regex only (no LLM segmentation)",
    )
    p.add_argument(
        "--one-chunk-per-section",
        action="store_true",
        default=True,
        help="One chunk per subsection (default: on)",
    )
    p.add_argument(
        "--multi-chunk",
        action="store_true",
        help="Allow multiple chunks per subsection (overrides --one-chunk-per-section)",
    )
    p.add_argument(
        "--scrub",
        action="store_true",
        help="PII-scrub chunk text before save",
    )
    p.add_argument(
        "--skip-chunk",
        action="store_true",
        help="Only run Textract (no chunking)",
    )
    return p.parse_args(argv)


def _stem_for_pdf_arg(pdf_arg: str) -> str:
    if pdf_arg.lower().startswith("s3://"):
        return Path(urlparse(pdf_arg).path).stem or "document"
    return Path(pdf_arg).stem


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    textract = _load_sibling("pdf_textract_extract")
    chunker = _load_sibling("chunk_rics_text")
    textract._load_dotenv()

    if args.multi_chunk:
        one_chunk = False
    else:
        one_chunk = bool(args.one_chunk_per_section)

    # --- Chunk-only path ----------------------------------------------------
    if args.from_md is not None:
        md_path = args.from_md
        if not md_path.is_file():
            print(f"Error: not found: {md_path}", file=sys.stderr)
            return 1
        out_root = args.output or (md_path.parent / f"{md_path.stem}_chunks")
        chunk_dir = out_root / md_path.stem
        print(
            f"[chunk] {md_path.name} "
            f"(regex_only={args.regex_only}, one_chunk={one_chunk}) ..."
        )
        try:
            result = chunker.process_one(
                md_path,
                chunk_dir,
                prefer_llm=not args.regex_only,
                regex_only=args.regex_only,
                scrub=args.scrub,
                source_name=None,
                one_chunk_per_section=one_chunk,
            )
        except Exception as exc:
            print(f"Error: chunking failed: {exc}", file=sys.stderr)
            return 1
        print(
            f"  method={result['method']} chunks={result['chunk_count']} "
            f"sections={len(result['sections'])}"
        )
        print(f"  chunks: {result['extracted_chunks']}")
        return 0

    if not args.pdfs:
        print("Error: pass PDF path(s) or --from-md <file>", file=sys.stderr)
        return 1

    region = textract._resolve_region(args.region)
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

    pdfs: list[str] = []
    for raw in args.pdfs:
        if raw.lower().startswith("s3://"):
            pdfs.append(raw)
            continue
        path = Path(raw)
        if not path.is_file():
            print(f"Error: not found: {path}", file=sys.stderr)
        elif path.suffix.lower() != ".pdf":
            print(f"Warning: skipping non-PDF: {path}", file=sys.stderr)
        else:
            pdfs.append(str(path))
    if not pdfs:
        print("Error: no PDF files to process.", file=sys.stderr)
        return 1

    ok = 0
    for pdf_arg in pdfs:
        stem = _stem_for_pdf_arg(pdf_arg)
        if args.output is not None:
            parse_dir = args.output
        elif pdf_arg.lower().startswith("s3://"):
            parse_dir = Path.cwd() / f"{stem}_textract_rics"
        else:
            parse_dir = Path(pdf_arg).parent / f"{stem}_textract_rics"
        parse_dir.mkdir(parents=True, exist_ok=True)

        print(f"[1/2] Textract {stem} ({region}) ...")
        try:
            result = textract.extract_pdf(
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
            print(f"  Error: Textract failed: {exc}", file=sys.stderr)
            continue

        written = textract.write_outputs(result, parse_dir, stem)
        md_path: Path = written["markdown"]
        print(f"  pages~{result['page_count']} lines={result['line_count']}")
        print(f"  md: {md_path}")

        if args.skip_chunk:
            ok += 1
            continue

        chunk_dir = parse_dir / md_path.stem
        print(
            f"[2/2] Chunking {md_path.name} "
            f"(regex_only={args.regex_only}, one_chunk={one_chunk}) ..."
        )
        try:
            chunk_result = chunker.process_one(
                md_path,
                chunk_dir,
                prefer_llm=not args.regex_only,
                regex_only=args.regex_only,
                scrub=args.scrub,
                source_name=None,
                one_chunk_per_section=one_chunk,
            )
        except Exception as exc:
            print(f"  Error: chunking failed: {exc}", file=sys.stderr)
            continue

        ok += 1
        print(
            f"  method={chunk_result['method']} chunks={chunk_result['chunk_count']} "
            f"sections={len(chunk_result['sections'])}"
        )
        print(f"  chunks: {chunk_result['extracted_chunks']}")

    print(f"\nDone. {ok}/{len(pdfs)} PDF(s).")
    return 0 if ok else 1


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
#
# --- Full pipeline: PDF -> Textract MD/TXT/JSON -> RICS chunks ---
#   python scripts/rics_pdf_textract_to_chunks.py "E:\my report ai\1a Woodland Hill London SE19 1PB.pdf" -o "E:\my report ai\out_textract" --regex-only --one-chunk-per-section
#
#   python scripts/rics_pdf_textract_to_chunks.py "E:\my report ai\5 Hillcrest Avenue, Pinner, HA5 1AJ.pdf" -o "E:\my report ai\out_textract" --regex-only --one-chunk-per-section
#
# --- Chunk existing Textract markdown (skip Textract / no AWS call) ---
#   python scripts/rics_pdf_textract_to_chunks.py --from-md "E:\my report ai\out_textract\1a Woodland Hill London SE19 1PB.textract.md" -o "E:\my report ai\out_textract" --regex-only --one-chunk-per-section
#
# --- Textract extract only (no chunking) ---
#   python scripts/rics_pdf_textract_to_chunks.py "E:\my report ai\1a Woodland Hill London SE19 1PB.pdf" -o "E:\my report ai\out_textract" --skip-chunk
#
#   # or use the extract script directly:
#   python scripts/pdf_textract_extract.py "E:\my report ai\1a Woodland Hill London SE19 1PB.pdf" -o "E:\my report ai\out_textract"
#
# --- Optional flags ---
#   --analyze          Textract TABLES+FORMS instead of text-only
#   --keep-s3          leave uploaded PDF on S3
#   --multi-chunk      allow multiple chunks per subsection
#   --scrub            PII-scrub chunk text before save
#   --region eu-west-2 override AWS_REGION
#
# Outputs:
#   <out>/<stem>.textract.md|.txt|.json
#   <out>/<stem>.textract/extracted_chunks.json
#   <out>/<stem>.textract/chunks_only.json
#   <out>/<stem>.textract/<stem>_chunk_manifest.json
# ---------------------------------------------------------------------------

#!/usr/bin/env python3
"""One-shot RICS pipeline: PDF -> LlamaParse MD/TXT -> section chunks.

Combines ``rics_llamaparse_extract.py`` + ``chunk_rics_text.py`` so you do not
need two commands.

Usage (from repo root):
  python scripts/rics_pdf_to_chunks.py "E:\\path\\report.pdf" -o "E:\\my report ai\\out_llamaparse"
  python scripts/rics_pdf_to_chunks.py report.pdf -o ./out --regex-only --one-chunk-per-section
  python scripts/rics_pdf_to_chunks.py a.pdf b.pdf -o ./out --tier agentic

Requires LLAMA_CLOUD_API_KEY (or LLAMA_PARSE_API_KEY / --api-key).
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any


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
            "Parse a RICS PDF with LlamaParse, then chunk the resulting markdown "
            "in one command."
        )
    )
    p.add_argument("pdfs", nargs="+", type=Path, help="RICS report PDF path(s)")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help=(
            "Output root (default: <pdf_dir>/<stem>_rics). "
            "Writes <stem>.llamaparse.md/.txt/.json here, and chunks under "
            "<output>/<stem>.llamaparse/"
        ),
    )
    p.add_argument(
        "--api-key",
        default=None,
        help="LlamaCloud API key (else LLAMA_CLOUD_API_KEY / .env)",
    )
    p.add_argument(
        "--tier",
        default="agentic",
        choices=("agentic", "agentic_plus", "cost_effective", "fast"),
        help="LlamaParse tier (default: agentic)",
    )
    p.add_argument(
        "--version",
        default="latest",
        help="LlamaParse model version (default: latest)",
    )
    p.add_argument(
        "--engine",
        choices=("auto", "llama_cloud", "llama_parse", "rest"),
        default="auto",
        help="LlamaParse backend (default: auto)",
    )
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
        help="Only run LlamaParse (no chunking)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    lp = _load_sibling("rics_llamaparse_extract")
    chunker = _load_sibling("chunk_rics_text")

    api_key = lp.resolve_api_key(args.api_key)

    pdfs = [p for p in args.pdfs if p.is_file() and p.suffix.lower() == ".pdf"]
    for p in args.pdfs:
        if not p.is_file():
            print(f"Error: not found: {p}", file=sys.stderr)
        elif p.suffix.lower() != ".pdf":
            print(f"Warning: skipping non-PDF: {p}", file=sys.stderr)
    if not pdfs:
        print("Error: no PDF files to process.", file=sys.stderr)
        return 1

    if args.multi_chunk:
        one_chunk = False
    else:
        one_chunk = bool(args.one_chunk_per_section)

    ok = 0
    for pdf in pdfs:
        parse_dir = args.output
        if parse_dir is None:
            parse_dir = pdf.parent / f"{pdf.stem}_rics"
        parse_dir.mkdir(parents=True, exist_ok=True)

        print(f"[1/2] LlamaParse {pdf.name} ({args.engine}/{args.tier}) ...")
        try:
            parsed = lp.parse_rics_pdf(
                pdf,
                api_key=api_key,
                tier=args.tier,
                version=args.version,
                engine=args.engine,
            )
        except Exception as exc:
            print(f"  Error: LlamaParse failed: {exc}", file=sys.stderr)
            continue

        written = lp.write_outputs(
            pdf_path=pdf, out_dir=parse_dir, parsed=parsed, rics=None
        )
        md_path: Path = written["markdown"]
        print(f"  engine={parsed['engine']} pages~{parsed['page_count']}")
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
            print(f"  Error: chunking failed: {exc}", file=sys.stderr)
            continue

        ok += 1
        print(
            f"  method={result['method']} chunks={result['chunk_count']} "
            f"sections={len(result['sections'])}"
        )
        print(f"  chunks: {result['extracted_chunks']}")

    print(f"\nDone. {ok}/{len(pdfs)} PDF(s).")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

# ---------------------------------------------------------------------------
# Run examples (from Report-genius-ai repo root, with LLAMA_CLOUD_API_KEY set):
#
#   python scripts/rics_pdf_to_chunks.py "E:\my report ai\5 Hillcrest Avenue, Pinner, HA5 1AJ.pdf" -o "E:\my report ai\out_llamaparse" --regex-only --one-chunk-per-section
#
#   python scripts/rics_pdf_to_chunks.py "E:\my report ai\1a Woodland Hill London SE19 1PB.pdf" -o "E:\my report ai\out_llamaparse" --regex-only --one-chunk-per-section
#
#   python scripts/rics_pdf_to_chunks.py report.pdf -o ./out --tier agentic --regex-only
#
#   python scripts/rics_pdf_to_chunks.py report.pdf -o ./out --skip-chunk
#
# Outputs:
#   <out>/<stem>.llamaparse.md|.txt|.json
#   <out>/<stem>.llamaparse/extracted_chunks.json  (and related chunk sidecars)
#
# Textract equivalent (AWS credentials + AWS_S3_BUCKET):
#   python scripts/rics_pdf_textract_to_chunks.py "E:\my report ai\1a Woodland Hill London SE19 1PB.pdf" -o "E:\my report ai\out_textract" --regex-only --one-chunk-per-section
# ---------------------------------------------------------------------------

"""Env-selected PDF text extraction for reference upload / re-ingest.

``PDF_EXTRACTOR`` (alias ``REFERENCE_PDF_EXTRACTOR``) chooses the backend:

* ``textract`` — Amazon Textract async (S3 upload) — default
* ``llamaparse`` — LlamaCloud parse (SDK or REST)
* ``pypdf`` — local pypdf with PyMuPDF fallback

DOCX / DOC paths are unchanged and still go through :mod:`doc_extractor`.
"""

from __future__ import annotations

import importlib.util
import logging
import re
from pathlib import Path
from types import ModuleType
from typing import Literal

from backend.config import REPO_ROOT, settings

logger = logging.getLogger(__name__)

PdfExtractor = Literal["textract", "llamaparse", "pypdf"]

_ALIASES: dict[str, PdfExtractor] = {
    "textract": "textract",
    "amazon_textract": "textract",
    "aws_textract": "textract",
    "aws": "textract",
    "llamaparse": "llamaparse",
    "llama_parse": "llamaparse",
    "llama-parse": "llamaparse",
    "llama": "llamaparse",
    "pypdf": "pypdf",
    "pymupdf": "pypdf",
    "fitz": "pypdf",
    "local": "pypdf",
}


def resolve_pdf_extractor(raw: str | None = None) -> PdfExtractor:
    token = (raw if raw is not None else settings.pdf_extractor or "").strip().lower()
    if not token:
        return "textract"
    mapped = _ALIASES.get(token)
    if mapped is None:
        allowed = ", ".join(sorted({*{"textract", "llamaparse", "pypdf"}, *_ALIASES}))
        raise ValueError(
            f"Unknown PDF_EXTRACTOR={token!r}. Use one of: textract, llamaparse, pypdf "
            f"(aliases: {allowed})."
        )
    return mapped


def extract_pdf_text(path: Path, *, extractor: str | None = None) -> tuple[str, str]:
    """Return ``(text, method)`` for a PDF using the configured extractor."""
    method = resolve_pdf_extractor(extractor)
    logger.info("Extracting PDF %s via %s", path.name, method)
    if method == "pypdf":
        return _extract_pypdf(path), "pypdf"
    if method == "llamaparse":
        return _extract_llamaparse(path), "llamaparse"
    return _extract_textract(path), "textract"


def _load_script(module_name: str) -> ModuleType:
    path = REPO_ROOT / "scripts" / f"{module_name}.py"
    if not path.is_file():
        raise FileNotFoundError(f"Missing extractor script: {path}")
    spec = importlib.util.spec_from_file_location(f"rics_pdf_scripts.{module_name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _extract_pypdf(path: Path) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        if text.strip():
            return text
    except Exception as exc:  # noqa: BLE001
        logger.warning("pypdf extraction failed for %s (%s); trying PyMuPDF.", path, exc)
    try:
        import fitz  # type: ignore[import-untyped]

        with fitz.open(str(path)) as doc:
            return "\n".join(page.get_text() for page in doc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("PyMuPDF extraction failed for %s (%s).", path, exc)
        return ""


def _pdf_page_count(path: Path) -> int | None:
    """Local page count via pypdf (preferred for billing). Returns None on failure."""
    try:
        from pypdf import PdfReader

        n = len(PdfReader(str(path)).pages)
        return int(n) if n > 0 else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("pypdf page count failed for %s (%s)", path, exc)
        return None


def _extract_llamaparse(path: Path) -> str:
    api_key = (settings.llama_cloud_api_key or "").strip()
    if not api_key:
        raise RuntimeError(
            "PDF_EXTRACTOR=llamaparse requires LLAMA_CLOUD_API_KEY "
            "(or LLAMA_PARSE_API_KEY) in the environment / .env."
        )
    from backend.ingest.llamaparse_extract import parse_rics_pdf

    configured_tier = (settings.llama_parse_tier or "agentic").strip() or "agentic"
    parsed = parse_rics_pdf(
        path,
        api_key=api_key,
        tier=configured_tier,
        version=(settings.llama_parse_version or "latest").strip() or "latest",
        engine="auto",
    )
    markdown = (parsed.get("markdown") or parsed.get("text") or "").strip()
    if not markdown:
        raise RuntimeError(f"LlamaParse returned empty text for {path.name}")

    try:
        from backend.cost import record_parse_cost

        engine = str(parsed.get("engine") or "").strip()
        api_pages = int(parsed.get("page_count") or 0)
        pdf_pages = _pdf_page_count(path)
        if pdf_pages and pdf_pages > 0:
            pages = pdf_pages
            pages_source = "pdf"
        elif api_pages > 0:
            pages = api_pages
            pages_source = "api"
        else:
            pages = 1
            pages_source = "api"

        priced_assumed = False
        tier = configured_tier
        if engine == "llama_parse":
            # Legacy SDK path does not forward LLAMA_PARSE_TIER.
            tier = (
                (settings.llamaparse_legacy_assumed_tier or configured_tier).strip()
                or configured_tier
            )
            priced_assumed = True

        record_parse_cost(
            provider="llamaparse",
            tier=tier,
            pages=pages,
            pages_source=pages_source,
            engine=engine,
            label="llamaparse",
            document_id=path.stem,
            priced_assumed=priced_assumed,
            api_page_count=api_pages if api_pages > 0 else None,
        )
    except Exception:  # noqa: BLE001 - metering must not break ingest
        logger.debug("LlamaParse cost record failed", exc_info=True)

    return _normalize_markdown_for_rics(markdown)


def _normalize_markdown_for_rics(text: str) -> str:
    """Prefer the CLI normalizer so ingest matches offline LlamaParse runs."""
    try:
        chunk_mod = _load_script("chunk_rics_text")
        normalize = getattr(chunk_mod, "normalize_markdown_for_rics", None)
        if callable(normalize):
            return str(normalize(text))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Markdown normalize skipped (%s).", exc)
    return text


def _extract_textract(path: Path) -> str:
    region = (settings.aws_region or "").strip()
    if not region:
        raise RuntimeError(
            "PDF_EXTRACTOR=textract requires AWS_REGION (or AWS_DEFAULT_REGION)."
        )
    bucket = (settings.aws_s3_bucket or "").strip()
    if not bucket:
        raise RuntimeError(
            "PDF_EXTRACTOR=textract requires AWS_S3_BUCKET (or TEXTRACT_S3_BUCKET). "
            "Textract async PDF processing reads from S3."
        )
    mod = _load_script("pdf_textract_extract")
    # CLI loads .env in ``__main__``; library import does not. Ensure AWS_* from
    # repo ``.env`` are in ``os.environ`` before boto3 resolves credentials.
    load_dotenv = getattr(mod, "_load_dotenv", None)
    if callable(load_dotenv):
        load_dotenv()
    profile = (settings.aws_profile or "").strip() or None
    prefix = (settings.textract_s3_prefix or "textract-input/").strip() or "textract-input/"
    try:
        result = mod.extract_pdf(
            path,
            region=region,
            profile=profile,
            bucket=bucket,
            prefix=prefix,
            analyze=False,
            keep_s3=False,
            poll_seconds=5.0,
            timeout_seconds=1800.0,
        )
    except SystemExit as exc:
        raise RuntimeError(str(exc) or "Textract extraction failed.") from exc

    from backend.ingest.text_reflow import unwrap_soft_line_breaks

    pages = result.get("pages") or {}
    if pages:
        # Single newline between pages so wraps that cross a page boundary reflow.
        all_lines: list[str] = []
        for key in sorted(pages.keys(), key=lambda k: int(k)):
            all_lines.extend(pages[key] or [])
        text = "\n".join(all_lines).strip()
    else:
        # Fallback: strip CLI page separators if present.
        text = re.sub(
            r"(?m)^----- Page \d+ -----\s*$",
            "",
            str(result.get("text") or ""),
        )
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

    if not text:
        raise RuntimeError(f"Textract returned empty text for {path.name}")

    try:
        from backend.cost import record_parse_cost

        api_pages = int(result.get("page_count") or 0)
        pdf_pages = _pdf_page_count(path)
        page_map = result.get("pages") or {}
        if pdf_pages and pdf_pages > 0:
            pages_n, pages_source = pdf_pages, "pdf"
        elif api_pages > 0:
            pages_n, pages_source = api_pages, "api"
        else:
            pages_n, pages_source = max(len(page_map) if isinstance(page_map, dict) else 0, 1), "api"
        record_parse_cost(
            provider="textract",
            tier="textract",
            pages=pages_n,
            pages_source=pages_source,
            engine="textract",
            label="textract",
            document_id=path.stem,
            api_page_count=api_pages if api_pages > 0 else None,
        )
    except Exception:  # noqa: BLE001
        logger.debug("Textract cost record failed", exc_info=True)

    # Textract LINE blocks keep PDF hard-wraps; unwrap so prose matches LlamaParse
    # (mid-sentence \\n hurts chunking and embedding quality).
    return unwrap_soft_line_breaks(text)

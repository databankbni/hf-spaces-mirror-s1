"""Document extraction for DOCX / PDF / legacy DOC.

Produces an ordered list of :class:`Block` objects (text + heading flag + level)
so the template discoverer can infer section structure, and a plain-text helper
for reference ingest. Legacy ``.doc`` files are converted to ``.docx`` first using
the first available tool: pandoc, LibreOffice, or Microsoft Word via pywin32.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Word VBA: wdFormatXMLDocument — Office Open XML (.docx) without macros.
_WD_FORMAT_DOCX = 12


@dataclass
class Block:
    """One extracted paragraph/line."""

    text: str
    is_heading: bool = False
    level: int = 0


def _soffice_executable() -> str | None:
    for name in ("soffice", "libreoffice"):
        p = shutil.which(name)
        if p:
            return p
    if sys.platform == "win32":
        for pf in (
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        ):
            cand = Path(pf) / "LibreOffice" / "program" / "soffice.exe"
            if cand.is_file():
                return str(cand)
    return None


def convert_doc_to_docx(source: Path) -> tuple[Path | None, Path | None]:
    """Convert a legacy ``.doc`` to ``.docx`` in a temp dir.

    Returns ``(docx_path, temp_dir)``; the caller must ``shutil.rmtree(temp_dir)``.
    Returns ``(None, None)`` on failure.
    """
    out_dir = Path(tempfile.mkdtemp(prefix="rics_v2_doc_"))
    out = out_dir / f"{source.stem}.docx"

    pandoc = shutil.which("pandoc")
    if pandoc:
        try:
            subprocess.run(
                [pandoc, str(source.resolve()), "-o", str(out.resolve())],
                check=True,
                capture_output=True,
                text=True,
                timeout=180,
            )
            if out.is_file() and out.stat().st_size > 0:
                logger.info("Converted %s via pandoc", source.name)
                return out, out_dir
        except (
            subprocess.CalledProcessError,
            OSError,
            subprocess.TimeoutExpired,
        ) as exc:
            logger.debug("pandoc .doc->.docx failed for %s: %s", source, exc)

    soffice = _soffice_executable()
    if soffice:
        try:
            subprocess.run(
                [
                    soffice,
                    "--headless",
                    "--convert-to",
                    "docx",
                    "--outdir",
                    str(out_dir),
                    str(source.resolve()),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=240,
            )
            if out.is_file() and out.stat().st_size > 0:
                logger.info("Converted %s via LibreOffice", source.name)
                return out, out_dir
        except (
            subprocess.CalledProcessError,
            OSError,
            subprocess.TimeoutExpired,
        ) as exc:
            logger.debug("LibreOffice .doc->.docx failed for %s: %s", source, exc)

    try:
        import win32com.client  # type: ignore[import-untyped]
    except ImportError:
        pass
    else:
        word = doc = None
        try:
            word = win32com.client.Dispatch("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0
            doc = word.Documents.Open(str(source.resolve()), ReadOnly=True)
            doc.SaveAs2(str(out.resolve()), FileFormat=_WD_FORMAT_DOCX)
            doc.Close(SaveChanges=False)
            doc = None
            word.Quit()
            word = None
            if out.is_file() and out.stat().st_size > 0:
                logger.info("Converted %s via Microsoft Word (COM)", source.name)
                return out, out_dir
        except Exception as exc:  # noqa: BLE001
            logger.debug("Word COM .doc->.docx failed for %s: %s", source, exc)
        finally:
            if doc is not None:
                try:
                    doc.Close(SaveChanges=False)
                except Exception:  # noqa: BLE001
                    pass
            if word is not None:
                try:
                    word.Quit()
                except Exception:  # noqa: BLE001
                    pass

    shutil.rmtree(out_dir, ignore_errors=True)
    logger.warning(
        "Could not convert legacy .doc %s. Install pandoc, LibreOffice, or "
        "Microsoft Word + pywin32, or provide a .docx instead.",
        source,
    )
    return None, None


def _docx_blocks(path: Path) -> list[Block]:
    from docx import Document  # type: ignore[import-untyped]

    doc = Document(str(path))
    blocks: list[Block] = []
    for para in doc.paragraphs:
        text = (para.text or "").strip()
        if not text:
            continue
        style = (para.style.name or "") if para.style else ""
        is_heading = style.lower().startswith("heading") or style.lower() == "title"
        level = 0
        if is_heading:
            m = re.search(r"(\d+)", style)
            level = int(m.group(1)) if m else 1
        blocks.append(Block(text=text, is_heading=is_heading, level=level))
    return blocks


def _pdf_blocks(path: Path) -> list[Block]:
    """Heuristic PDF extraction: short, title-cased lines are treated as headings."""
    text = _pdf_text(path)
    blocks: list[Block] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        words = line.split()
        looks_heading = (
            len(words) <= 9
            and not line.endswith((".", ",", ";"))
            and (line.isupper() or line[:1].isupper())
            and len(line) <= 80
        )
        blocks.append(
            Block(text=line, is_heading=looks_heading, level=1 if looks_heading else 0)
        )
    return blocks


def _pdf_text(path: Path) -> str:
    """Extract PDF plain text using ``settings.pdf_extractor`` (env ``PDF_EXTRACTOR``)."""
    from backend.ingest.pdf_extractors import extract_pdf_text

    text, method = extract_pdf_text(path)
    logger.info("PDF text extraction complete for %s via %s (%d chars)", path.name, method, len(text))
    return text


def extract_blocks(path: Path) -> list[Block]:
    """Return ordered blocks for a DOCX / PDF / legacy DOC file."""
    suffix = path.suffix.lower()
    if suffix == ".doc":
        converted, tmp = convert_doc_to_docx(path)
        if converted is None:
            return []
        try:
            return _docx_blocks(converted)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    if suffix in (".docx", ".docm"):
        return _docx_blocks(path)
    if suffix == ".pdf":
        return _pdf_blocks(path)
    raise ValueError(f"Unsupported document type: {path.suffix}")


def extract_text(path: Path) -> str:
    """Return plain text for a document (used for reference ingest).

    PDFs go through :func:`backend.ingest.pdf_extractors.extract_pdf_text` so the
    configured extractor (textract / llamaparse / pypdf) is honoured without a
    lossy block round-trip. DOCX / DOC still use :func:`extract_blocks`.
    """
    if path.suffix.lower() == ".pdf":
        return _pdf_text(path)
    return "\n".join(b.text for b in extract_blocks(path))

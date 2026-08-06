import io
import html
import importlib
import json
import os
import re
import tempfile
import threading
import uuid
import base64
import csv
import zipfile
import textwrap
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import wraps
from html.parser import HTMLParser
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

from pypdf import PdfReader, PdfWriter
from openpyxl import Workbook

import pypdfium2 as pdfium
import pytesseract
import cv2
import numpy as np
from flask import Flask, jsonify, render_template, render_template_string, request, send_file
from PIL import Image, ImageFilter, ImageStat, ImageOps, ImageDraw, ImageFont

try:
    from flask_cors import CORS
except Exception:
    CORS = None

try:
    from ddgs import DDGS as _DDGSClient
except Exception:
    _DDGSClient = None

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__, template_folder=str(BASE_DIR), static_folder=str(BASE_DIR))

if os.getenv("OCR_ENABLE_CORS", "1").strip().lower() in {"1", "true", "yes"} and CORS is not None:
    cors_origins = os.getenv("OCR_CORS_ORIGINS", "*").strip() or "*"
    CORS(app, resources={r"/api/*": {"origins": cors_origins}})


@dataclass
class DocumentStore:
    pages: List[Image.Image]
    filename: str
    file_type: str = "image"
    embedded_text_pages: List[str] = field(default_factory=list)
    original_bytes: bytes = b""
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class OCRPdfJob:
    file_id: str
    filename: str
    status: str = "queued"
    progress: int = 0
    done_pages: int = 0
    total_pages: int = 0
    error: str = ""
    output_path: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class OCRBatchPdfJob:
    file_ids: List[str]
    status: str = "queued"
    progress: int = 0
    done_docs: int = 0
    total_docs: int = 0
    done_pages: int = 0
    total_pages: int = 0
    error: str = ""
    output_path: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)


FILES: Dict[str, DocumentStore] = {}
PDF_JOBS: Dict[str, OCRPdfJob] = {}
BATCH_PDF_JOBS: Dict[str, OCRBatchPdfJob] = {}
PDF_JOBS_LOCK = threading.Lock()
MAX_DOCS = 12
TTL_MINUTES = 30
JOB_TTL_MINUTES = 60
SUPPORTED_LANGS = ["eng", "fra", "spa", "deu", "ita", "por"]
PRESET_OPTIONS: Dict[str, Dict[str, int]] = {
    "invoice": {"psm": 6, "low_conf_threshold": 60},
    "contract": {"psm": 3, "low_conf_threshold": 55},
    "receipt": {"psm": 6, "low_conf_threshold": 65},
}
PADDLE_TABLE_ENGINE: Optional[Any] = None
PADDLE_TABLE_ENGINE_ERROR: str = ""
PADDLE_TABLE_ENGINE_LOCK = threading.Lock()


class _SimpleTableHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: List[List[Dict[str, Any]]] = []
        self._active_row: List[Dict[str, Any]] = []
        self._active_cell: Optional[Dict[str, Any]] = None
        self._in_table = False
        self._in_row = False

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attrs_map = {k.lower(): (v or "") for k, v in attrs}
        t = tag.lower()

        if t == "table":
            self._in_table = True
            return

        if not self._in_table:
            return

        if t == "tr":
            self._in_row = True
            self._active_row = []
            return

        if t not in {"td", "th"} or not self._in_row:
            return

        try:
            colspan = max(1, int((attrs_map.get("colspan", "1") or "1").strip()))
        except Exception:
            colspan = 1
        try:
            rowspan = max(1, int((attrs_map.get("rowspan", "1") or "1").strip()))
        except Exception:
            rowspan = 1

        self._active_cell = {
            "tag": t,
            "rowspan": rowspan,
            "colspan": colspan,
            "parts": [],
        }

    def handle_data(self, data: str) -> None:
        if self._active_cell is not None and data:
            self._active_cell["parts"].append(data)

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t == "table":
            self._in_table = False
            self._in_row = False
            self._active_cell = None
            self._active_row = []
            return

        if t in {"td", "th"} and self._active_cell is not None and self._in_row:
            text = " ".join(part.strip() for part in self._active_cell.get("parts", []) if part.strip()).strip()
            self._active_row.append(
                {
                    "text": text,
                    "rowspan": int(self._active_cell.get("rowspan", 1)),
                    "colspan": int(self._active_cell.get("colspan", 1)),
                    "is_header": t == "th",
                }
            )
            self._active_cell = None
            return

        if t == "tr" and self._in_row:
            if self._active_row:
                self.rows.append(self._active_row)
            self._active_row = []
            self._active_cell = None
            self._in_row = False


def _normalize_rows(rows: List[List[str]]) -> List[List[str]]:
    cleaned = [[(cell or "").strip() for cell in row] for row in rows]
    max_cols = max((len(row) for row in cleaned), default=0)
    if max_cols <= 0:
        return []
    out = [row + [""] * (max_cols - len(row)) for row in cleaned]
    while out and all((not cell.strip()) for cell in out[-1]):
        out.pop()
    return out


def _rows_to_html_table(rows: List[List[str]]) -> str:
    safe_rows = _normalize_rows(rows)
    parts: List[str] = ["<table>"]
    for row in safe_rows:
        parts.append("<tr>")
        for cell in row:
            parts.append(f"<td>{html.escape(cell or '')}</td>")
        parts.append("</tr>")
    parts.append("</table>")
    return "".join(parts)


def _rows_from_html_table(table_html: str) -> List[List[str]]:
    src = (table_html or "").strip()
    if not src:
        return []

    parser = _SimpleTableHTMLParser()
    parser.feed(src)
    parser.close()

    parsed_rows = parser.rows
    if not parsed_rows:
        return []

    matrix: List[List[str]] = []
    rowspan_map: Dict[int, Dict[str, Any]] = {}

    for parsed_row in parsed_rows:
        row_vals: List[str] = []
        col = 0

        def fill_rowspans_until(stop_col: int) -> None:
            nonlocal col, row_vals
            while col < stop_col:
                span = rowspan_map.get(col)
                if not span:
                    row_vals.append("")
                else:
                    row_vals.append(span.get("text", ""))
                    span["left"] = int(span.get("left", 0)) - 1
                    if span["left"] <= 0:
                        rowspan_map.pop(col, None)
                col += 1

        for cell in parsed_row:
            while col in rowspan_map:
                fill_rowspans_until(col + 1)

            text = (cell.get("text") or "").strip()
            colspan = max(1, int(cell.get("colspan", 1)))
            rowspan = max(1, int(cell.get("rowspan", 1)))

            fill_rowspans_until(col)
            for offset in range(colspan):
                row_vals.append(text)
                if rowspan > 1:
                    rowspan_map[col + offset] = {"text": text, "left": rowspan - 1}
            col += colspan

        if rowspan_map:
            trailing_cols = sorted(c for c in rowspan_map.keys() if c >= col)
            for target_col in trailing_cols:
                fill_rowspans_until(target_col + 1)

        matrix.append(row_vals)

    while rowspan_map:
        row_vals = []
        col = 0
        max_col = max(rowspan_map.keys())
        while col <= max_col:
            span = rowspan_map.get(col)
            if not span:
                row_vals.append("")
            else:
                row_vals.append(span.get("text", ""))
                span["left"] = int(span.get("left", 0)) - 1
                if span["left"] <= 0:
                    rowspan_map.pop(col, None)
            col += 1
        matrix.append(row_vals)

    return _normalize_rows(matrix)


def _load_paddle_table_engine() -> Any:
    global PADDLE_TABLE_ENGINE, PADDLE_TABLE_ENGINE_ERROR
    if PADDLE_TABLE_ENGINE is not None:
        return PADDLE_TABLE_ENGINE

    with PADDLE_TABLE_ENGINE_LOCK:
        if PADDLE_TABLE_ENGINE is not None:
            return PADDLE_TABLE_ENGINE

        try:
            paddleocr_mod = importlib.import_module("paddleocr")
            PPStructure = getattr(paddleocr_mod, "PPStructure")
        except Exception as err:
            PADDLE_TABLE_ENGINE_ERROR = (
                "Paddle table engine is unavailable. Install 'paddleocr' and 'paddlepaddle' in this Space. "
                f"Import error: {err}"
            )
            raise RuntimeError(PADDLE_TABLE_ENGINE_ERROR) from err

        lang = os.getenv("PADDLE_TABLE_LANG", "en").strip() or "en"

        try:
            engine = PPStructure(show_log=False, lang=lang, layout=False, ocr=True, table=True)
        except TypeError:
            try:
                engine = PPStructure(show_log=False, lang=lang)
            except Exception as err:
                PADDLE_TABLE_ENGINE_ERROR = f"Failed to initialize Paddle table engine: {err}"
                raise RuntimeError(PADDLE_TABLE_ENGINE_ERROR) from err
        except Exception as err:
            PADDLE_TABLE_ENGINE_ERROR = f"Failed to initialize Paddle table engine: {err}"
            raise RuntimeError(PADDLE_TABLE_ENGINE_ERROR) from err

        PADDLE_TABLE_ENGINE = engine
        PADDLE_TABLE_ENGINE_ERROR = ""
        return PADDLE_TABLE_ENGINE


def _extract_table_with_paddle(image: Image.Image) -> Dict[str, Any]:
    engine = _load_paddle_table_engine()

    rgb = np.array(image.convert("RGB"))
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    try:
        result = engine(bgr)
    except Exception as err:
        raise RuntimeError(f"Paddle table extraction failed: {err}") from err

    table_item: Dict[str, Any] = {}
    for item in result or []:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type", "")).strip().lower()
        if item_type == "table" or (isinstance(item.get("res"), dict) and item.get("res", {}).get("html")):
            table_item = item
            break

    if not table_item:
        return {"rows": [], "columns": 0, "cells": [], "method": "paddle-ppstructure", "html_table": ""}

    res = table_item.get("res") if isinstance(table_item.get("res"), dict) else {}
    table_html = (res.get("html") or table_item.get("html") or "").strip()
    rows = _rows_from_html_table(table_html)
    columns = max((len(r) for r in rows), default=0)

    cells: List[Dict[str, Any]] = []
    for r_idx, row in enumerate(rows, start=1):
        for c_idx, cell_text in enumerate(row, start=1):
            cells.append({"row": r_idx, "col": c_idx, "text": cell_text})

    if not table_html and rows:
        table_html = _rows_to_html_table(rows)

    return {
        "rows": rows,
        "columns": columns,
        "cells": cells,
        "method": "paddle-ppstructure",
        "html_table": table_html,
    }


def _api_password() -> str:
    return os.getenv("OCR_API_PASSWORD", "").strip()


def _accepted_api_passwords() -> set[str]:
    passwords: set[str] = set()
    primary = _api_password()
    if primary:
        passwords.add(primary)

    fallback = os.getenv("OCR_FALLBACK_PASSWORD", "").strip()
    if fallback:
        passwords.add(fallback)

    return passwords


def _is_ui_request() -> bool:
    if request.headers.get("X-UI-Client", "") != "portable-ocr-web":
        return False

    host = request.host_url.rstrip("/")
    host_lower = host.lower()
    origin = request.headers.get("Origin", "").strip().rstrip("/")
    origin_lower = origin.lower()
    referer = request.headers.get("Referer", "").strip()
    referer_lower = referer.lower()

    if origin and origin_lower == host_lower:
        return True
    if referer and referer_lower.startswith(host_lower + "/"):
        return True

    is_hf_space_host = host_lower.endswith(".hf.space")
    if is_hf_space_host:
        if origin_lower == "https://huggingface.co":
            return True
        if referer_lower.startswith("https://huggingface.co/spaces/"):
            return True
        if referer_lower.startswith("https://huggingface.co/") and "/spaces/" in referer_lower:
            return True

    # Browsers usually send this header for fetch/XHR requests.
    sec_fetch_site = request.headers.get("Sec-Fetch-Site", "").strip().lower()
    return sec_fetch_site in {"same-origin", "same-site"}


def _is_request_authorized() -> bool:
    passwords = _accepted_api_passwords()
    if not passwords:
        return True

    # Allow browser UI traffic from this app without requiring API key.
    if _is_ui_request():
        return True

    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if token in passwords:
            return True

    x_api_key = request.headers.get("X-API-Key", "").strip()
    if x_api_key in passwords:
        return True

    query_key = request.args.get("api_key", "").strip()
    if query_key in passwords:
        return True

    return False


def require_api_auth(handler):
    @wraps(handler)
    def wrapper(*args, **kwargs):
        if not _is_request_authorized():
            return jsonify({"error": "Unauthorized. Provide valid API key."}), 401
        return handler(*args, **kwargs)

    return wrapper


def _configure_tesseract() -> None:
    def _is_executable_cmd(cmd_path: str) -> bool:
        p = str(cmd_path or "").strip()
        if not p or not os.path.isfile(p):
            return False

        if os.name != "nt" and p.lower().endswith(".exe"):
            return False

        if os.name == "nt":
            return True

        return os.access(p, os.X_OK)

    def _is_valid_tessdata_dir(path: str) -> bool:
        p = str(path or "").strip()
        if not p or not os.path.isdir(p):
            return False
        if os.path.exists(os.path.join(p, "eng.traineddata")):
            return True
        if os.path.exists(os.path.join(p, "osd.traineddata")):
            return True
        try:
            return any(name.lower().endswith(".traineddata") for name in os.listdir(p))
        except Exception:
            return False

    def _activate_candidate(cmd_path: str, tessdata_candidates: List[str]) -> bool:
        if not _is_executable_cmd(cmd_path):
            return False

        current = os.getenv("TESSDATA_PREFIX", "").strip()
        if _is_valid_tessdata_dir(current):
            pytesseract.pytesseract.tesseract_cmd = cmd_path
            return True

        for candidate in tessdata_candidates:
            if _is_valid_tessdata_dir(candidate):
                os.environ["TESSDATA_PREFIX"] = candidate
                pytesseract.pytesseract.tesseract_cmd = cmd_path
                return True

        return False

    current_prefix = os.getenv("TESSDATA_PREFIX", "").strip()
    if current_prefix and not _is_valid_tessdata_dir(current_prefix):
        os.environ.pop("TESSDATA_PREFIX", None)

    if os.name != "nt":
        custom_cmd = os.getenv("TESSERACT_CMD", "").strip()
        if _is_executable_cmd(custom_cmd):
            pytesseract.pytesseract.tesseract_cmd = custom_cmd
            return

        pytesseract.pytesseract.tesseract_cmd = "tesseract"
        return

    custom_cmd = os.getenv("TESSERACT_CMD", "").strip()
    if custom_cmd:
        custom_tessdata = os.path.join(os.path.dirname(custom_cmd), "tessdata")
        if _activate_candidate(custom_cmd, [custom_tessdata]):
            return

    bundled_cmd = str(BASE_DIR / "portable_tesseract" / "Tesseract-OCR" / "tesseract.exe")
    bundled_tessdata = str(BASE_DIR / "portable_tesseract" / "Tesseract-OCR" / "tessdata")
    if _activate_candidate(bundled_cmd, [bundled_tessdata]):
        return

    common_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    common_tessdata = r"C:\Program Files\Tesseract-OCR\tessdata"
    if _activate_candidate(common_cmd, [common_tessdata]):
        return

    scoop_cmd = os.path.expandvars(r"%USERPROFILE%\scoop\shims\tesseract.exe")
    scoop_tessdata = os.path.expandvars(r"%USERPROFILE%\scoop\apps\tesseract\current\tessdata")
    scoop_persist_tessdata = os.path.expandvars(r"%USERPROFILE%\scoop\persist\tesseract\tessdata")
    if _activate_candidate(scoop_cmd, [scoop_tessdata, scoop_persist_tessdata]):
        return

    if custom_cmd and os.path.exists(custom_cmd):
        pytesseract.pytesseract.tesseract_cmd = custom_cmd


def _cleanup_store() -> None:
    now = datetime.utcnow()
    expired = [
        key for key, val in FILES.items()
        if now - val.created_at > timedelta(minutes=TTL_MINUTES)
    ]
    for key in expired:
        FILES.pop(key, None)

    if len(FILES) > MAX_DOCS:
        ordered = sorted(FILES.items(), key=lambda kv: kv[1].created_at)
        for key, _ in ordered[: len(FILES) - MAX_DOCS]:
            FILES.pop(key, None)


def _cleanup_pdf_jobs() -> None:
    now = datetime.utcnow()
    expired: List[str] = []
    with PDF_JOBS_LOCK:
        for key, job in PDF_JOBS.items():
            if now - job.created_at > timedelta(minutes=JOB_TTL_MINUTES):
                expired.append(key)

        for key in expired:
            job = PDF_JOBS.pop(key, None)
            if not job:
                continue
            if job.output_path and os.path.exists(job.output_path):
                try:
                    os.remove(job.output_path)
                except OSError:
                    pass

        expired_batch: List[str] = []
        for key, job in BATCH_PDF_JOBS.items():
            if now - job.created_at > timedelta(minutes=JOB_TTL_MINUTES):
                expired_batch.append(key)

        for key in expired_batch:
            job = BATCH_PDF_JOBS.pop(key, None)
            if not job:
                continue
            if job.output_path and os.path.exists(job.output_path):
                try:
                    os.remove(job.output_path)
                except OSError:
                    pass


def _load_pdf(file_bytes: bytes) -> List[Image.Image]:
    doc = pdfium.PdfDocument(file_bytes)
    pages: List[Image.Image] = []
    render_scale = float(os.getenv("OCR_PDF_RENDER_SCALE", "4.0"))
    render_scale = max(2.0, min(render_scale, 6.0))
    for i in range(len(doc)):
        page = doc[i]
        bitmap = page.render(scale=render_scale)
        pil_image = bitmap.to_pil().convert("RGB")
        pages.append(pil_image)
    return pages


def _load_image(file_bytes: bytes) -> List[Image.Image]:
    image = Image.open(io.BytesIO(file_bytes))

    # Fix EXIF rotation — mobile phones embed orientation tag; Pillow ignores it by default
    try:
        from PIL import ImageOps
        image = ImageOps.exif_transpose(image)
    except Exception:
        pass  # older Pillow or no EXIF — ignore

    image = image.convert("RGB")

    # Downscale oversized mobile photos — 2400px on the long edge is ample for OCR
    MAX_DIM = 2400
    w, h = image.size
    longest = max(w, h)
    if longest > MAX_DIM:
        ratio = MAX_DIM / float(longest)
        new_w = max(1, int(w * ratio))
        new_h = max(1, int(h * ratio))
        image = image.resize((new_w, new_h), Image.Resampling.LANCZOS)

    return [image]


def _extract_pdf_embedded_text_pages(file_bytes: bytes) -> List[str]:
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except Exception:
        return []

    out: List[str] = []
    for page in getattr(reader, "pages", []):
        try:
            text = str(page.extract_text() or "")
        except Exception:
            text = ""
        text = re.sub(r"\s+", " ", text).strip()
        out.append(text)
    return out


def _extract_text_from_docx(file_bytes: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            if "word/document.xml" not in zf.namelist():
                return ""
            xml_bytes = zf.read("word/document.xml")
    except Exception:
        return ""

    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return ""

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: List[str] = []
    for p in root.findall(".//w:p", ns):
        parts: List[str] = []
        for t in p.findall(".//w:t", ns):
            if t.text:
                parts.append(t.text)
        line = "".join(parts).strip()
        if line:
            paragraphs.append(line)

    return "\n".join(paragraphs).strip()


def _extract_docx_blocks(file_bytes: bytes) -> List[Dict[str, Any]]:
    """Extract DOCX content as styled blocks with soft structure and page breaks."""
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            if "word/document.xml" not in zf.namelist():
                return []
            xml_bytes = zf.read("word/document.xml")
    except Exception:
        return []

    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return []

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    blocks: List[Dict[str, Any]] = []

    for p in root.findall(".//w:p", ns):
        style_id = ""
        ppr = p.find("w:pPr", ns)
        if ppr is not None:
            pstyle = ppr.find("w:pStyle", ns)
            if pstyle is not None:
                style_id = str(pstyle.attrib.get(f"{{{ns['w']}}}val", "") or "").strip().lower()

        parts: List[str] = []
        saw_page_break = False
        for r in p.findall(".//w:r", ns):
            for br in r.findall("w:br", ns):
                br_type = str(br.attrib.get(f"{{{ns['w']}}}type", "") or "").strip().lower()
                if br_type == "page":
                    saw_page_break = True
            if r.find("w:lastRenderedPageBreak", ns) is not None:
                saw_page_break = True
            for t in r.findall("w:t", ns):
                if t.text:
                    parts.append(t.text)

        text = "".join(parts).strip()
        if saw_page_break:
            blocks.append({"kind": "page_break", "text": ""})

        if not text:
            continue

        kind = "normal"
        if style_id.startswith("heading1") or style_id == "title":
            kind = "heading1"
        elif style_id.startswith("heading2") or style_id.startswith("heading3"):
            kind = "heading2"
        elif "list" in style_id:
            kind = "bullet"

        if text.startswith(("•", "-", "*")) and kind == "normal":
            kind = "bullet"

        blocks.append({"kind": kind, "text": text})

    return blocks


def _decode_text_bytes(file_bytes: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return file_bytes.decode(encoding)
        except Exception:
            continue
    return file_bytes.decode("utf-8", errors="replace")


def _render_text_pages(text: str) -> List[Image.Image]:
    cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not cleaned:
        cleaned = "(No readable text found in this document.)"

    page_w, page_h = 1700, 2300
    margin_x, margin_y = 95, 95
    usable_w = page_w - (margin_x * 2)
    usable_h = page_h - (margin_y * 2)

    font = ImageFont.load_default()
    line_h = 22
    max_lines = max(10, usable_h // line_h)

    sample_draw = ImageDraw.Draw(Image.new("RGB", (10, 10), "white"))
    avg_char_w = max(6, sample_draw.textlength("ABCDEFGHIJKLMNOPQRSTUVWXYZ", font=font) / 26.0)
    wrap_width = max(30, int(usable_w / avg_char_w))

    wrapped_lines: List[str] = []
    for raw_line in cleaned.split("\n"):
        line = raw_line.strip()
        if not line:
            wrapped_lines.append("")
            continue
        chunks = textwrap.wrap(line, width=wrap_width, break_long_words=True, break_on_hyphens=False)
        wrapped_lines.extend(chunks if chunks else [line])

    pages: List[Image.Image] = []
    idx = 0
    while idx < len(wrapped_lines):
        page = Image.new("RGB", (page_w, page_h), "white")
        draw = ImageDraw.Draw(page)
        y = margin_y
        for _ in range(max_lines):
            if idx >= len(wrapped_lines):
                break
            draw.text((margin_x, y), wrapped_lines[idx], fill="black", font=font)
            y += line_h
            idx += 1
        pages.append(page)

    return pages or [Image.new("RGB", (page_w, page_h), "white")]


def _render_docx_blocks_to_pages(blocks: List[Dict[str, Any]]) -> Tuple[List[Image.Image], List[str]]:
    if not blocks:
        return _render_text_pages(""), [""]

    page_w, page_h = 1700, 2300
    margin_x, margin_y = 95, 95
    usable_w = page_w - (margin_x * 2)
    usable_h = page_h - (margin_y * 2)

    base_font = ImageFont.load_default()
    line_h = 24

    def _wrap(draw: ImageDraw.ImageDraw, text: str, width_px: int) -> List[str]:
        if not text:
            return [""]
        words = text.split()
        if not words:
            return [""]
        lines: List[str] = []
        cur = words[0]
        for w in words[1:]:
            candidate = f"{cur} {w}"
            if draw.textlength(candidate, font=base_font) <= width_px:
                cur = candidate
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
        return lines

    pages: List[Image.Image] = []
    page_texts: List[str] = []
    page = Image.new("RGB", (page_w, page_h), "white")
    draw = ImageDraw.Draw(page)
    y = margin_y
    page_lines: List[str] = []

    def _flush_page() -> None:
        nonlocal page, draw, y, page_lines
        pages.append(page)
        page_texts.append("\n".join(page_lines).strip())
        page = Image.new("RGB", (page_w, page_h), "white")
        draw = ImageDraw.Draw(page)
        y = margin_y
        page_lines = []

    for block in blocks:
        kind = str(block.get("kind") or "normal")
        text = str(block.get("text") or "").strip()

        if kind == "page_break":
            _flush_page()
            continue
        if not text:
            continue

        prefix = ""
        if kind == "heading1":
            prefix = "# "
        elif kind == "heading2":
            prefix = "## "
        elif kind == "bullet":
            prefix = "• "

        wrapped = _wrap(draw, prefix + text, usable_w)
        needed_h = max(line_h, len(wrapped) * line_h)
        if y + needed_h > margin_y + usable_h:
            _flush_page()

        for ln in wrapped:
            draw.text((margin_x, y), ln, fill="black", font=base_font)
            page_lines.append(ln)
            y += line_h
        y += 6

    if page_lines or not pages:
        _flush_page()

    return pages, page_texts


def _load_docx(file_bytes: bytes) -> Tuple[List[Image.Image], List[str]]:
    blocks = _extract_docx_blocks(file_bytes)
    if blocks:
        return _render_docx_blocks_to_pages(blocks)
    text = _extract_text_from_docx(file_bytes)
    pages = _render_text_pages(text)
    return pages, [text] if text else [""]


def _load_text_document(file_bytes: bytes) -> Tuple[List[Image.Image], List[str]]:
    text = _decode_text_bytes(file_bytes)
    pages = _render_text_pages(text)
    # split plain text into page-sized chunks roughly aligned with rendered pages
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    chunk = max(40, int(len(lines) / max(1, len(pages))) + 1)
    page_texts: List[str] = []
    for i in range(0, len(lines), chunk):
        page_texts.append("\n".join(lines[i:i + chunk]).strip())
    while len(page_texts) < len(pages):
        page_texts.append("")
    return pages, page_texts[:len(pages)]


def _parse_uploaded_content(name: str, content: bytes):
    ext = os.path.splitext(name)[1].lower()
    embedded_text_pages: List[str] = []
    if ext == ".pdf":
        pages = _load_pdf(content)
        file_type = "pdf"
        embedded_text_pages = _extract_pdf_embedded_text_pages(content)
    elif ext == ".docx":
        pages, embedded_text_pages = _load_docx(content)
        file_type = "pdf" if len(pages) > 1 else "image"
    elif ext in {".txt", ".csv", ".json", ".md", ".rtf", ".log"}:
        pages, embedded_text_pages = _load_text_document(content)
        file_type = "pdf" if len(pages) > 1 else "image"
    elif ext in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".gif"}:
        pages = _load_image(content)
        file_type = "image"
    else:
        raise ValueError("Unsupported file type. Supported: PDF, DOCX, TXT, CSV, JSON, MD, RTF, LOG, and images.")
    if embedded_text_pages:
        cleaned = [re.sub(r"\s+", " ", str(t or "")).strip() for t in embedded_text_pages]
        if len(cleaned) < len(pages):
            cleaned.extend([""] * (len(pages) - len(cleaned)))
        embedded_text_pages = cleaned[:len(pages)]
    return pages, file_type, embedded_text_pages


def _guess_filename_from_url(url: str, content_type: str = "") -> str:
    parsed = urllib.parse.urlparse(url)
    base = os.path.basename(parsed.path or "").strip()
    if base and "." in base:
        return base

    ctype = (content_type or "").split(";")[0].strip().lower()
    ext_map = {
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "text/plain": ".txt",
        "text/csv": ".csv",
        "application/json": ".json",
        "text/markdown": ".md",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/tiff": ".tiff",
    }
    ext = ext_map.get(ctype, ".bin")
    return f"url_import{ext}"


def _decode_base64_file(encoded: str) -> bytes:
    value = (encoded or "").strip()
    if not value:
        raise ValueError("file_base64 is required.")

    if "," in value and value.lower().startswith("data:"):
        value = value.split(",", 1)[1]

    value = "".join(value.split())
    if not value:
        raise ValueError("file_base64 is required.")

    missing_padding = len(value) % 4
    if missing_padding:
        value += "=" * (4 - missing_padding)

    try:
        return base64.b64decode(value, validate=True)
    except Exception as err:
        raise ValueError(f"Invalid base64 input: {err}") from err


def _detect_file_type(filename: str, explicit_type: str) -> str:
    normalized_type = (explicit_type or "").strip().lower()
    if normalized_type in {"pdf", "image"}:
        return normalized_type

    ext = os.path.splitext((filename or "").strip())[1].lower()
    if ext == ".pdf":
        return "pdf"
    if ext in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".gif"}:
        return "image"

    raise ValueError("Unsupported or missing file type. Provide filename or file_type='pdf'/'image'.")


def _load_pages_from_bytes(file_bytes: bytes, file_type: str) -> List[Image.Image]:
    if file_type == "pdf":
        return _load_pdf(file_bytes)
    if file_type == "image":
        return _load_image(file_bytes)
    raise ValueError("Unsupported file type.")


def _crop_region(image: Image.Image, region: Optional[dict]) -> Image.Image:
    if not region:
        return image

    try:
        raw = {k: region.get(k, 0) for k in ("x", "y", "w", "h")}
        if any(v is None for v in raw.values()):
            raise ValueError("Region coordinates contain null values. Draw a selection box first.")
        x = int(raw["x"])
        y = int(raw["y"])
        w = int(raw["w"])
        h = int(raw["h"])
        if w <= 0 or h <= 0:
            raise ValueError("Selection is empty.")

        x2 = max(0, min(image.width, x + w))
        y2 = max(0, min(image.height, y + h))
        x = max(0, min(image.width, x))
        y = max(0, min(image.height, y))
        cropped = image.crop((x, y, x2, y2))

        # Upscale small crops aggressively so region OCR matches manual zoom quality
        MIN_DIM = 1200
        cw, ch = cropped.size
        if cw > 0 and ch > 0 and (cw < MIN_DIM or ch < MIN_DIM):
            scale = max(MIN_DIM / cw, MIN_DIM / ch, 2.5)
            scale = min(scale, 10.0)
            new_w = max(1, int(cw * scale))
            new_h = max(1, int(ch * scale))
            cropped = cropped.resize((new_w, new_h), Image.Resampling.LANCZOS)

        return cropped
    except ValueError:
        raise
    except Exception as err:
        raise ValueError(f"Invalid selection coordinates: {err}") from err


def _ocr_image(image: Image.Image, lang: str, psm: int) -> str:
    config = f"--oem 3 --psm {psm}"
    return pytesseract.image_to_string(image, lang=lang, config=config)


def _preprocess_for_ocr(image: Image.Image, is_region: bool = False, is_image: bool = False) -> Image.Image:
    """High-quality OCR preprocessing for watermark-heavy PDFs and region captures."""
    rgb = image.convert("RGB")

    # For normal full-image OCR, keep preprocessing conservative unless this is a phone photo.
    if not is_region:
        if is_image:
            arr = np.array(rgb)
            gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
            clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
            gray = clahe.apply(gray)
            gray = cv2.fastNlMeansDenoising(gray, None, h=9, templateWindowSize=7, searchWindowSize=21)
            bw = cv2.adaptiveThreshold(
                gray,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                31,
                9,
            )
            k = np.ones((2, 2), np.uint8)
            bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, k, iterations=1)
            bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, k, iterations=1)
            return Image.fromarray(bw).convert("RGB")

        gray = ImageOps.grayscale(rgb)
        gray = ImageOps.autocontrast(gray, cutoff=1)
        gray = gray.filter(ImageFilter.MedianFilter(size=3))
        gray = gray.filter(ImageFilter.SHARPEN)
        return gray.convert("RGB")

    # Region selections can be tiny; force a larger working resolution.
    if is_region:
        min_dim = int(float(os.getenv("OCR_REGION_MIN_DIM", "1300")))
        min_dim = max(800, min(min_dim, 2600))
        w, h = rgb.size
        if w > 0 and h > 0 and (w < min_dim or h < min_dim):
            scale = max(min_dim / float(w), min_dim / float(h), 2.0)
            scale = min(scale, 10.0)
            rgb = rgb.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)

    arr = np.array(rgb)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

    # Local contrast enhancement for faint text
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    # Light denoise (keeps edges/shapes)
    gray = cv2.bilateralFilter(gray, 5, 50, 50)

    # Estimate and remove smooth background (watermarks / paper gradients)
    bg_kernel = 41 if min(gray.shape[:2]) > 900 else 25
    background = cv2.GaussianBlur(gray, (bg_kernel, bg_kernel), 0)
    norm = cv2.divide(gray, background, scale=255)

    # Adaptive binarization for mixed contrast text/watermark overlays
    bw = cv2.adaptiveThreshold(
        norm,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        11,
    )

    # Morph cleanup to remove speckles while preserving glyphs
    k = np.ones((2, 2), np.uint8)
    bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, k, iterations=1)
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, k, iterations=1)

    # Unsharp to improve stroke boundaries
    sharp = cv2.addWeighted(norm, 1.35, cv2.GaussianBlur(norm, (0, 0), 1.2), -0.35, 0)
    sharp_bw = cv2.adaptiveThreshold(
        sharp,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        9,
    )

    # Combine both masks to preserve difficult characters
    combined = cv2.bitwise_and(bw, sharp_bw)

    return Image.fromarray(combined).convert("RGB")


def _region_psm_candidates(image: Image.Image, requested_psm: int) -> List[int]:
    """Return the best PSM candidates for a cropped region.
    PSM 11 (sparse) is intentionally excluded — it scans too broadly and bleeds into
    text outside the selection.
    Strategy: adapt based on aspect ratio of the crop."""
    w, h = image.size
    ratio = w / max(h, 1)

    if ratio >= 5.0:
        # Very wide, short strip — single line or heading
        adaptive = [7, 8, 6]
    elif ratio >= 2.5:
        # Wide — likely one or two lines
        adaptive = [7, 6]
    elif ratio >= 0.8:
        # Roughly square or normal block
        adaptive = [6, 4]
    else:
        # Tall narrow column
        adaptive = [5, 6]

    # Always honour the user's explicit PSM choice first, then fallback list
    merged = list(dict.fromkeys([requested_psm] + adaptive))
    # Never include PSM 11 (sparse – bleeds text) or PSM 0 (orientation detect only)
    merged = [p for p in merged if p not in (0, 11)]
    return merged[:3]  # cap at 3 candidates


def _ocr_with_region_fallback(
    image: Image.Image,
    lang: str,
    psm: int,
    low_conf_threshold: int = 55,
) -> Dict[str, Any]:
    """Run OCR with multiple region-friendly passes in PARALLEL and return the best result.
    Helps when a selected region only returns partial text."""
    psm_candidates = _region_psm_candidates(image, psm)  # adaptive, no PSM 11

    def _run_psm(p: int) -> Dict[str, Any]:
        d = _ocr_with_details(image=image, lang=lang, psm=int(p), low_conf_threshold=int(low_conf_threshold))
        d["_score"] = float(d.get("confidence_score", 0.0)) + (0.08 * float(d.get("words_count", 0)))
        d["_psm_used"] = int(p)
        return d

    candidates: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=len(psm_candidates)) as pool:
        futures = {pool.submit(_run_psm, p): p for p in psm_candidates}
        for fut in as_completed(futures):
            try:
                candidates.append(fut.result())
            except Exception:
                pass

    if not candidates:
        return _ocr_with_details(image=image, lang=lang, psm=psm, low_conf_threshold=low_conf_threshold)

    best = max(candidates, key=lambda item: float(item.get("_score", 0.0)))
    best.pop("_score", None)
    return best


def _text_quality_score(text: str) -> float:
    raw = str(text or "")
    if not raw.strip():
        return 0.0

    total = len(raw)
    letters = sum(ch.isalpha() for ch in raw)
    digits = sum(ch.isdigit() for ch in raw)
    spaces = sum(ch.isspace() for ch in raw)
    punctuation = sum((not ch.isalnum()) and (not ch.isspace()) for ch in raw)

    alpha_num_ratio = (letters + digits) / max(total, 1)
    space_ratio = spaces / max(total, 1)
    punct_ratio = punctuation / max(total, 1)

    # Penalize symbol-heavy outputs like "###|@@@..."
    score = (alpha_num_ratio * 100.0) + (space_ratio * 8.0) - (punct_ratio * 65.0)
    return round(score, 3)


# Quality threshold above which we skip the preprocessed pass (saves ~40-60% time on clean images)
_OCR_FAST_QUALITY_THRESHOLD = float(os.getenv("OCR_FAST_QUALITY_THRESHOLD", "72"))


def _ocr_best_details(
    image: Image.Image,
    lang: str,
    psm: int,
    low_conf_threshold: int = 55,
    is_region: bool = False,
    is_image: bool = False,
) -> Dict[str, Any]:
    """Run OCR on raw + preprocessed passes CONCURRENTLY and choose the best result.

    Fast path: if raw OCR scores above _OCR_FAST_QUALITY_THRESHOLD we skip the
    preprocessed pass entirely — accuracy is identical on clean images, much faster.
    """
    def _run_pass(pass_image: Image.Image, label: str) -> Dict[str, Any]:
        if is_region:
            d = _ocr_with_region_fallback(image=pass_image, lang=lang, psm=psm, low_conf_threshold=low_conf_threshold)
        else:
            d = _ocr_with_details(image=pass_image, lang=lang, psm=psm, low_conf_threshold=low_conf_threshold)
        text_value = str(d.get("text") or "")
        text_len = len(text_value.strip())
        quality = _text_quality_score(text_value)
        d["_score"] = (
            float(d.get("confidence_score", 0.0))
            + 0.03 * float(d.get("words_count", 0))
            + min(text_len / 200.0, 6.0)
            + 0.65 * quality
        )
        d["_pass"] = label
        d["_quality"] = quality
        return d

    # --- Step 1: run raw pass first (fast) ---
    try:
        raw_result = _run_pass(image, "raw")
    except Exception:
        raw_result = None

    # --- Step 2: if raw quality is already good, skip preprocessing (fast path) ---
    raw_quality = float(raw_result.get("_quality", 0.0)) if raw_result else 0.0
    quality_threshold = _OCR_FAST_QUALITY_THRESHOLD
    if raw_quality >= quality_threshold:
        if raw_result:
            raw_result.pop("_score", None)
            raw_result.pop("_quality", None)
        return raw_result or _ocr_with_details(image=image, lang=lang, psm=psm, low_conf_threshold=low_conf_threshold)

    # --- Step 3: quality is low — run preprocessing in background WHILE we already have raw ---
    # For photo images: only apply heavy cv2 preprocessing when raw text is actually noisy
    # (high punct ratio = special-char garbage). On clean-but-low-conf images, light path is enough.
    effective_is_image = False
    if is_image and not is_region:
        raw_text = str(raw_result.get("text") or "") if raw_result else ""
        total_chars = max(1, len(raw_text))
        punct_count = sum((not ch.isalnum()) and (not ch.isspace()) for ch in raw_text)
        raw_punct_ratio = punct_count / total_chars
        noise_threshold = float(os.getenv("OCR_IMAGE_NOISE_PUNCT_THRESHOLD", "0.04"))
        noise_quality_max = float(os.getenv("OCR_IMAGE_NOISE_QUALITY_MAX", "65.0"))
        if raw_punct_ratio > noise_threshold and raw_quality < noise_quality_max:
            effective_is_image = True  # image is genuinely noisy — use heavy cv2 path

    processed_result = None
    try:
        processed_img = _preprocess_for_ocr(image, is_region=is_region, is_image=effective_is_image)
        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(_run_pass, processed_img, "preprocessed")
            processed_result = fut.result()
    except Exception:
        pass

    candidates = [r for r in [raw_result, processed_result] if r is not None]
    if not candidates:
        if is_region:
            return _ocr_with_region_fallback(image=image, lang=lang, psm=psm, low_conf_threshold=low_conf_threshold)
        return _ocr_with_details(image=image, lang=lang, psm=psm, low_conf_threshold=low_conf_threshold)

    best = max(candidates, key=lambda item: float(item.get("_score", 0.0)))
    best.pop("_score", None)
    best.pop("_quality", None)
    return best


def _ocr_block_by_block(
    image: Image.Image,
    lang: str,
    low_conf_threshold: int = 55,
    upscale: float = 2.0,
) -> Dict[str, Any]:
    """
    Mimics the manual zoom+region workflow:
    1. Upscale the page (same effect as zooming in the viewer).
    2. Let Tesseract detect text blocks with PSM 3 layout analysis.
    3. Crop each block, add padding, OCR with PSM 6 (single uniform block).
    4. Stitch blocks back in reading order.
    Falls back to single-pass OCR if block detection fails.
    """
    w, h = image.size
    scaled_w = max(1, int(w * upscale))
    scaled_h = max(1, int(h * upscale))
    layout_img = image.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS).convert("RGB")

    try:
        data = pytesseract.image_to_data(
            layout_img,
            lang=lang,
            config="--oem 3 --psm 3",
            output_type=pytesseract.Output.DICT,
        )
    except Exception:
        return _ocr_with_details(image, lang=lang, psm=3, low_conf_threshold=low_conf_threshold)

    levels     = data.get("level", [])
    block_nums = data.get("block_num", [])
    lefts      = data.get("left", [])
    tops       = data.get("top", [])
    widths     = data.get("width", [])
    heights    = data.get("height", [])

    # Collect bounding box of each block (level=2 entries)
    block_boxes: Dict[int, List[int]] = {}
    for i, lvl in enumerate(levels):
        if int(lvl) == 2:
            bnum = int(block_nums[i])
            x1 = int(lefts[i])
            y1 = int(tops[i])
            x2 = x1 + int(widths[i])
            y2 = y1 + int(heights[i])
            if (x2 - x1) > 20 and (y2 - y1) > 10:
                block_boxes[bnum] = [x1, y1, x2, y2]

    if not block_boxes:
        return _ocr_with_details(image, lang=lang, psm=3, low_conf_threshold=low_conf_threshold)

    # Sort top→bottom, left→right (simple reading order)
    sorted_boxes = sorted(block_boxes.values(), key=lambda b: (b[1], b[0]))

    block_texts: List[str] = []
    all_words:   List[Dict] = []
    all_confs:   List[float] = []
    pad = 8

    for bbox in sorted_boxes:
        x1, y1, x2, y2 = bbox
        cx1 = max(0, x1 - pad)
        cy1 = max(0, y1 - pad)
        cx2 = min(layout_img.width, x2 + pad)
        cy2 = min(layout_img.height, y2 + pad)
        crop = layout_img.crop((cx1, cy1, cx2, cy2))
        if crop.width < 20 or crop.height < 10:
            continue
        try:
            result = _ocr_with_details(
                crop,
                lang=lang,
                psm=6,
                low_conf_threshold=low_conf_threshold,
            )
            block_text = (result.get("text") or "").strip()
            if block_text:
                block_texts.append(block_text)
            all_words.extend(result.get("words", []))
            cs = result.get("confidence_score", 0.0)
            if cs > 0:
                all_confs.append(float(cs))
        except Exception:
            continue

    if not block_texts:
        return _ocr_with_details(image, lang=lang, psm=3, low_conf_threshold=low_conf_threshold)

    combined_text = "\n\n".join(block_texts)
    avg_conf = round(sum(all_confs) / len(all_confs), 2) if all_confs else 0.0
    low_words = [wd for wd in all_words if float(wd.get("conf", 0)) < float(low_conf_threshold)]

    return {
        "text": combined_text,
        "confidence_score": avg_conf,
        "words_count": len(all_words),
        "low_conf_threshold": low_conf_threshold,
        "low_confidence_count": len(low_words),
        "low_confidence_words": low_words[:150],
        "words": all_words[:500],
    }


def _detect_language_from_image(
    image: Image.Image,
    psm: int = 6,
    candidates: Optional[List[str]] = None,
) -> Tuple[str, Dict[str, float]]:
    scores: Dict[str, float] = {}
    sample = image.convert("RGB")
    max_dim = 1400
    largest = max(sample.width, sample.height)
    if largest > max_dim:
        ratio = max_dim / float(largest)
        sample = sample.resize(
            (max(1, int(sample.width * ratio)), max(1, int(sample.height * ratio))),
            Image.Resampling.LANCZOS,
        )

    langs = [str(item).strip().lower() for item in (candidates or SUPPORTED_LANGS)]
    langs = [item for item in langs if item in SUPPORTED_LANGS]
    if not langs:
        langs = ["eng"]

    for lang in langs:
        try:
            data = pytesseract.image_to_data(
                sample,
                lang=lang,
                config=f"--oem 3 --psm {psm}",
                output_type=pytesseract.Output.DICT,
            )
            confs: List[float] = []
            texts = data.get("text", [])
            raw_confs = data.get("conf", [])
            for text, conf_raw in zip(texts, raw_confs):
                token = (text or "").strip()
                if not token:
                    continue
                try:
                    conf = float(conf_raw)
                except Exception:
                    continue
                if conf >= 0:
                    confs.append(conf)
            scores[lang] = round(sum(confs) / len(confs), 2) if confs else 0.0
        except Exception:
            scores[lang] = 0.0

    if not scores:
        return "eng", {}
    best = max(scores.items(), key=lambda item: item[1])[0]
    return best, scores


def _resolve_ocr_options(
    image: Image.Image,
    lang: str,
    psm: int,
    preset: str,
    low_conf_threshold: int,
    is_region: bool = False,
    is_image: bool = False,
) -> Dict[str, Any]:
    normalized_preset = (preset or "").strip().lower()
    resolved_psm = int(psm)
    resolved_threshold = int(low_conf_threshold)

    # For region crops default PSM 3 (auto) performs poorly;
    # switch to PSM 6 (uniform block) if no preset overrides it.
    if is_region and resolved_psm == 3 and not normalized_preset:
        resolved_psm = 6
    # For phone photos / image uploads, PSM 6 is typically cleaner and faster than auto page layout.
    if is_image and not is_region and resolved_psm == 3 and not normalized_preset:
        resolved_psm = int(os.getenv("OCR_IMAGE_DEFAULT_PSM", "6"))
    detected_lang = ""
    lang_scores: Dict[str, float] = {}

    if normalized_preset in PRESET_OPTIONS:
        preset_cfg = PRESET_OPTIONS[normalized_preset]
        resolved_psm = int(preset_cfg.get("psm", resolved_psm))
        resolved_threshold = int(preset_cfg.get("low_conf_threshold", resolved_threshold))

    resolved_lang = (lang or "eng").strip().lower()
    if resolved_lang == "auto":
        image_auto_candidates = os.getenv("OCR_IMAGE_AUTO_LANG_CANDIDATES", "eng")
        auto_candidates = [tok.strip().lower() for tok in image_auto_candidates.split(",") if tok.strip()]
        if is_image and len(auto_candidates) == 1 and auto_candidates[0] in SUPPORTED_LANGS:
            detected_lang = auto_candidates[0]
            lang_scores = {detected_lang: 100.0}
        else:
            detected_lang, lang_scores = _detect_language_from_image(
                image,
                psm=resolved_psm,
                candidates=auto_candidates if is_image else None,
            )
        resolved_lang = detected_lang or "eng"

    if resolved_lang not in SUPPORTED_LANGS:
        resolved_lang = "eng"

    return {
        "lang": resolved_lang,
        "psm": resolved_psm,
        "preset": normalized_preset,
        "low_conf_threshold": resolved_threshold,
        "detected_lang": detected_lang,
        "lang_scores": lang_scores,
    }


def _ocr_with_details(
    image: Image.Image,
    lang: str,
    psm: int,
    low_conf_threshold: int = 55,
) -> Dict[str, Any]:
    config = f"--oem 3 --psm {psm}"
    text = pytesseract.image_to_string(image, lang=lang, config=config)
    data = pytesseract.image_to_data(
        image,
        lang=lang,
        config=config,
        output_type=pytesseract.Output.DICT,
    )

    words: List[Dict[str, Any]] = []
    valid_confs: List[float] = []

    texts = data.get("text", [])
    confs = data.get("conf", [])
    lefts = data.get("left", [])
    tops = data.get("top", [])
    widths = data.get("width", [])
    heights = data.get("height", [])

    for idx in range(min(len(texts), len(confs), len(lefts), len(tops), len(widths), len(heights))):
        token = (texts[idx] or "").strip()
        if not token:
            continue
        try:
            conf = float(confs[idx])
        except Exception:
            continue
        if conf < 0:
            continue

        valid_confs.append(conf)
        words.append(
            {
                "text": token,
                "conf": round(conf, 2),
                "bbox": {
                    "x": int(lefts[idx]),
                    "y": int(tops[idx]),
                    "w": int(widths[idx]),
                    "h": int(heights[idx]),
                },
            }
        )

    low_words = [word for word in words if float(word.get("conf", 0.0)) < float(low_conf_threshold)]
    avg_conf = round(sum(valid_confs) / len(valid_confs), 2) if valid_confs else 0.0

    return {
        "text": text,
        "confidence_score": avg_conf,
        "words_count": len(words),
        "low_conf_threshold": int(low_conf_threshold),
        "low_confidence_count": len(low_words),
        "low_confidence_words": low_words[:150],
        "words": words,
    }


def _cluster_line_items(items: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    if not items:
        return []

    heights = [int(item["bbox"]["h"]) for item in items if int(item["bbox"]["h"]) > 0]
    tol = max(8, int((median(heights) if heights else 12) * 0.6))

    sorted_items = sorted(items, key=lambda w: (int(w["bbox"]["y"]), int(w["bbox"]["x"])))
    lines: List[List[Dict[str, Any]]] = []
    line_ys: List[float] = []

    for item in sorted_items:
        y_mid = int(item["bbox"]["y"]) + int(item["bbox"]["h"]) / 2.0
        placed = False
        for idx, line_y in enumerate(line_ys):
            if abs(y_mid - line_y) <= tol:
                lines[idx].append(item)
                new_len = len(lines[idx])
                line_ys[idx] = ((line_y * (new_len - 1)) + y_mid) / new_len
                placed = True
                break
        if not placed:
            lines.append([item])
            line_ys.append(y_mid)

    for row in lines:
        row.sort(key=lambda w: int(w["bbox"]["x"]))
    return lines


def _infer_column_centers(lines: List[List[Dict[str, Any]]]) -> List[float]:
    x_positions: List[float] = []
    for row in lines:
        for item in row:
            x_positions.append(float(int(item["bbox"]["x"])))

    if not x_positions:
        return []

    x_positions.sort()
    centers: List[float] = []
    tol = 48.0
    for x in x_positions:
        if not centers:
            centers.append(x)
            continue
        nearest_idx = min(range(len(centers)), key=lambda i: abs(centers[i] - x))
        if abs(centers[nearest_idx] - x) <= tol:
            centers[nearest_idx] = (centers[nearest_idx] + x) / 2.0
        else:
            centers.append(x)

    centers.sort()
    return centers[:12]


def _infer_column_boundaries_from_words(lines: List[List[Dict[str, Any]]]) -> List[Tuple[int, int]]:
    if not lines:
        return []

    all_words = [w for row in lines for w in row]
    if not all_words:
        return []

    min_x = min(int(w["bbox"]["x"]) for w in all_words)
    max_x = max(int(w["bbox"]["x"]) + int(w["bbox"]["w"]) for w in all_words)
    if max_x <= min_x:
        return []

    x_gaps: List[Tuple[int, int]] = []
    for row in lines:
        ordered = sorted(row, key=lambda w: int(w["bbox"]["x"]))
        for left, right in zip(ordered, ordered[1:]):
            left_end = int(left["bbox"]["x"]) + int(left["bbox"]["w"])
            right_start = int(right["bbox"]["x"])
            gap = right_start - left_end
            if gap >= 24:
                x_gaps.append((left_end, right_start))

    if not x_gaps:
        return [(min_x, max_x)]

    separators: List[int] = []
    for start, end in x_gaps:
        center = int((start + end) / 2)
        placed = False
        for idx, sep in enumerate(separators):
            if abs(sep - center) <= 26:
                separators[idx] = int((sep + center) / 2)
                placed = True
                break
        if not placed:
            separators.append(center)

    separators = sorted([s for s in separators if min_x + 8 < s < max_x - 8])
    if not separators:
        return [(min_x, max_x)]

    bounds: List[Tuple[int, int]] = []
    prev = min_x
    for sep in separators:
        if sep - prev > 8:
            bounds.append((prev, sep))
        prev = sep
    if max_x - prev > 8:
        bounds.append((prev, max_x))

    if not bounds:
        return [(min_x, max_x)]
    return bounds[:16]


def _cluster_line_positions(indices: np.ndarray, max_gap: int = 6) -> List[int]:
    if indices.size == 0:
        return []
    values = sorted(int(v) for v in indices.tolist())
    groups: List[List[int]] = [[values[0]]]
    for val in values[1:]:
        if val - groups[-1][-1] <= max_gap:
            groups[-1].append(val)
        else:
            groups.append([val])
    return [int(sum(group) / len(group)) for group in groups]


def _extract_table_from_grid_lines(image: Image.Image, words: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    arr = np.array(image.convert("L"))
    if arr.ndim != 2:
        return None

    img_h, img_w = arr.shape[:2]
    if img_h < 30 or img_w < 30:
        return None

    try:
        bin_inv = cv2.adaptiveThreshold(
            arr,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            31,
            12,
        )

        h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, img_w // 28), 1))
        v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, img_h // 28)))

        horizontal = cv2.morphologyEx(bin_inv, cv2.MORPH_OPEN, h_kernel, iterations=1)
        vertical = cv2.morphologyEx(bin_inv, cv2.MORPH_OPEN, v_kernel, iterations=1)

        h_proj = np.sum(horizontal > 0, axis=1)
        v_proj = np.sum(vertical > 0, axis=0)

        y_idx = np.where(h_proj > max(25, int(img_w * 0.18)))[0]
        x_idx = np.where(v_proj > max(25, int(img_h * 0.18)))[0]

        y_lines = _cluster_line_positions(y_idx, max_gap=6)
        x_lines = _cluster_line_positions(x_idx, max_gap=6)

        if len(y_lines) < 2 or len(x_lines) < 2:
            return None

        if len(y_lines) > 90 or len(x_lines) > 45:
            return None

        rows_count = len(y_lines) - 1
        cols_count = len(x_lines) - 1
        if rows_count <= 0 or cols_count <= 0 or rows_count * cols_count > 1500:
            return None

        rows: List[List[str]] = [["" for _ in range(cols_count)] for _ in range(rows_count)]
        row_word_buckets: List[List[List[Dict[str, Any]]]] = [[[] for _ in range(cols_count)] for _ in range(rows_count)]

        for token in words:
            box = token.get("bbox") or {}
            cx = int(box.get("x", 0)) + int(box.get("w", 0)) // 2
            cy = int(box.get("y", 0)) + int(box.get("h", 0)) // 2

            row_idx = -1
            for r in range(rows_count):
                if y_lines[r] <= cy <= y_lines[r + 1]:
                    row_idx = r
                    break

            if row_idx < 0:
                continue

            col_idx = -1
            for c in range(cols_count):
                if x_lines[c] <= cx <= x_lines[c + 1]:
                    col_idx = c
                    break

            if col_idx < 0:
                continue

            row_word_buckets[row_idx][col_idx].append(token)

        cells: List[Dict[str, Any]] = []
        for r in range(rows_count):
            y1 = int(y_lines[r])
            y2 = int(y_lines[r + 1])
            if y2 - y1 < 6:
                continue
            for c in range(cols_count):
                x1 = int(x_lines[c])
                x2 = int(x_lines[c + 1])
                if x2 - x1 < 6:
                    continue

                bucket = row_word_buckets[r][c]
                if bucket:
                    bucket = sorted(bucket, key=lambda w: (int(w["bbox"]["y"]), int(w["bbox"]["x"])))
                    text = " ".join((w.get("text") or "").strip() for w in bucket).strip()
                else:
                    text = ""

                rows[r][c] = text
                cells.append(
                    {
                        "row": r + 1,
                        "col": c + 1,
                        "text": text,
                        "bbox": {"x": x1, "y": y1, "w": max(1, x2 - x1), "h": max(1, y2 - y1)},
                    }
                )

        while rows and all(not val.strip() for val in rows[-1]):
            rows.pop()

        if rows:
            non_empty_cols = [idx for idx in range(len(rows[0])) if any((row[idx] or "").strip() for row in rows)]
            if non_empty_cols:
                rows = [[row[idx] for idx in non_empty_cols] for row in rows]
                cells = [
                    {
                        **cell,
                        "col": non_empty_cols.index(int(cell.get("col", 1)) - 1) + 1,
                    }
                    for cell in cells
                    if (int(cell.get("col", 1)) - 1) in non_empty_cols and int(cell.get("row", 0)) <= len(rows)
                ]

        if not rows:
            return None

        return {
            "rows": rows,
            "columns": len(rows[0]) if rows else 0,
            "cells": cells,
            "method": "grid-lines",
            "grid_lines": {
                "vertical": x_lines,
                "horizontal": y_lines,
            },
        }
    except Exception:
        return None


def _extract_table_from_words(words: List[Dict[str, Any]], image: Optional[Image.Image] = None) -> Dict[str, Any]:
    if image is not None:
        grid_result = _extract_table_from_grid_lines(image, words)
        if grid_result:
            return grid_result

    lines = _cluster_line_items(words)
    if not lines:
        return {"rows": [], "columns": 0, "cells": [], "method": "ocr-geometry"}

    col_bounds = _infer_column_boundaries_from_words(lines)
    if not col_bounds:
        col_bounds = []

    if not col_bounds:
        rows = [[" ".join(item.get("text", "") for item in row).strip()] for row in lines]
        cells: List[Dict[str, Any]] = []
        for row_idx, row in enumerate(lines, start=1):
            if not row:
                continue
            x1 = min(int(w["bbox"]["x"]) for w in row)
            y1 = min(int(w["bbox"]["y"]) for w in row)
            x2 = max(int(w["bbox"]["x"]) + int(w["bbox"]["w"]) for w in row)
            y2 = max(int(w["bbox"]["y"]) + int(w["bbox"]["h"]) for w in row)
            cells.append(
                {
                    "row": row_idx,
                    "col": 1,
                    "text": rows[row_idx - 1][0] if row_idx - 1 < len(rows) else "",
                    "bbox": {"x": x1, "y": y1, "w": max(1, x2 - x1), "h": max(1, y2 - y1)},
                }
            )
        return {"rows": rows, "columns": 1, "cells": cells, "method": "ocr-geometry"}

    rows: List[List[str]] = []
    cells: List[Dict[str, Any]] = []

    for row_idx, line in enumerate(lines, start=1):
        row_cells = [""] * len(col_bounds)
        bucket_words: List[List[Dict[str, Any]]] = [[] for _ in col_bounds]

        for token in line:
            x = int(token["bbox"]["x"])
            token_center = x + int(token["bbox"]["w"]) / 2.0
            col_idx = 0
            for idx, (left, right) in enumerate(col_bounds):
                if left <= token_center <= right:
                    col_idx = idx
                    break
            bucket_words[col_idx].append(token)

        for col_idx, bucket in enumerate(bucket_words, start=1):
            if not bucket:
                continue
            bucket = sorted(bucket, key=lambda w: int(w["bbox"]["x"]))
            text = " ".join(w.get("text", "") for w in bucket).strip()
            row_cells[col_idx - 1] = text

            x1 = min(int(w["bbox"]["x"]) for w in bucket)
            y1 = min(int(w["bbox"]["y"]) for w in bucket)
            x2 = max(int(w["bbox"]["x"]) + int(w["bbox"]["w"]) for w in bucket)
            y2 = max(int(w["bbox"]["y"]) + int(w["bbox"]["h"]) for w in bucket)

            cells.append(
                {
                    "row": row_idx,
                    "col": col_idx,
                    "text": text,
                    "bbox": {"x": x1, "y": y1, "w": max(1, x2 - x1), "h": max(1, y2 - y1)},
                }
            )

        rows.append([cell.strip() for cell in row_cells])

    while rows and all(not c for c in rows[-1]):
        rows.pop()

    valid_row_count = len(rows)
    cells = [c for c in cells if int(c.get("row", 0)) <= valid_row_count]

    return {"rows": rows, "columns": len(col_bounds), "cells": cells, "method": "ocr-geometry"}


def _rows_to_csv_text(rows: List[List[str]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()


def _is_table_structure_strong(table: Dict[str, Any]) -> bool:
    method = str(table.get("method", "")).strip().lower()
    rows = table.get("rows", []) or []
    columns = int(table.get("columns", 0) or 0)

    if not rows:
        return False

    if method.startswith("grid-lines"):
        return len(rows) >= 2 and columns >= 2

    if columns < 2 or len(rows) < 2:
        return False

    non_empty_counts: List[int] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        non_empty_counts.append(sum(1 for cell in row if str(cell or "").strip()))

    if not non_empty_counts:
        return False

    rows_with_two_plus = sum(1 for cnt in non_empty_counts if cnt >= 2)
    avg_non_empty = sum(non_empty_counts) / float(len(non_empty_counts))

    if rows_with_two_plus < max(2, int(len(non_empty_counts) * 0.5)):
        return False
    if avg_non_empty < 1.8:
        return False

    return True


def _rows_to_xlsx_bytes(rows: List[List[str]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Extracted Table"
    for row in rows:
        ws.append(row)
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out.getvalue()


def _prepare_image_for_pdf_ocr(image: Image.Image) -> Image.Image:
    max_dim = int(os.getenv("OCR_PDF_MAX_DIM", "2200"))
    rgb = image.convert("RGB")
    width, height = rgb.size
    largest = max(width, height)
    if largest <= max_dim:
        return rgb

    ratio = max_dim / float(largest)
    new_size = (max(1, int(width * ratio)), max(1, int(height * ratio)))
    return rgb.resize(new_size, Image.Resampling.LANCZOS)


def _build_searchable_pdf_bytes(
    pages: List[Image.Image],
    lang: str,
    psm: int,
    page_timeout: Optional[int] = None,
) -> bytes:
    writer = PdfWriter()
    source_streams: List[io.BytesIO] = []
    source_readers: List[PdfReader] = []

    for image in pages:
        prepared = _prepare_image_for_pdf_ocr(image)
        kwargs = {
            "lang": lang,
            "config": f"--oem 3 --psm {psm}",
            "extension": "pdf",
        }
        if page_timeout is not None:
            kwargs["timeout"] = page_timeout

        pdf_bytes = pytesseract.image_to_pdf_or_hocr(prepared, **kwargs)
        stream = io.BytesIO(pdf_bytes)
        source_streams.append(stream)
        reader = PdfReader(stream)
        source_readers.append(reader)
        for page in reader.pages:
            writer.add_page(page)

    if not writer.pages:
        raise RuntimeError("no pages were produced")

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _safe_pdf_name(filename: str) -> str:
    base = os.path.basename(filename or "document")
    stem = base.rsplit(".", 1)[0] if "." in base else base
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", " ", "."} else "_" for ch in stem).strip()
    return safe or "document"


_WEB_TOPIC_STOPWORDS = {
    "the", "and", "that", "this", "from", "with", "were", "have", "will", "shall", "which", "when", "what",
    "where", "your", "about", "into", "there", "their", "then", "than", "they", "them", "would", "could",
    "should", "been", "being", "also", "such", "only", "each", "some", "more", "most", "many", "much", "very",
    "over", "under", "across", "between", "before", "after", "because", "while", "during", "until", "including",
    "without", "within", "document", "page", "pages", "section", "clause", "table", "figure", "using", "used",
    "here", "into", "onto", "from", "text", "ocr", "result", "results", "file", "files", "image", "images",
    "for", "are", "was", "you", "its", "our", "out", "any", "all", "can", "not", "has", "had", "his", "her",
    "she", "him", "who", "why", "how", "let", "may", "per", "via", "etc", "com", "www", "http", "https",
}


def _clean_text_for_query(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _tokenize_search_terms(text: str) -> List[str]:
    cleaned = _clean_text_for_query(text)
    if not cleaned:
        return []

    raw_tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9&+./\-]{1,}", cleaned)
    out: List[str] = []
    for raw in raw_tokens:
        token = str(raw or "").strip("._-/+&").lower()
        if not token:
            continue
        if token in _WEB_TOPIC_STOPWORDS or token.isdigit():
            continue
        if len(token) < 3 and not raw.isupper() and not any(ch.isdigit() for ch in raw):
            continue
        out.append(token)

    return out


def _build_duckduckgo_query(text: str, max_terms: int = 8) -> str:
    cleaned = _clean_text_for_query(text)
    if not cleaned:
        return ""

    raw_tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9&+./\-]{1,}", cleaned)
    filtered = _tokenize_search_terms(cleaned)
    if not filtered:
        return cleaned[:140]

    token_meta: Dict[str, Dict[str, int]] = {}
    ordered_tokens: List[str] = []
    for idx, raw in enumerate(raw_tokens):
        token = str(raw or "").strip("._-/+&").lower()
        if token not in filtered:
            continue
        if token not in token_meta:
            token_meta[token] = {"count": 0, "first": idx, "bonus": 0}
            ordered_tokens.append(token)
        token_meta[token]["count"] += 1

        bonus = 0
        if idx < 4:
            bonus += 2
        if any(ch.isdigit() for ch in raw):
            bonus += 3
        if any(ch in raw for ch in "-/+&."):
            bonus += 2
        if raw.isupper() and 2 <= len(raw) <= 8:
            bonus += 3
        if len(token) >= 7:
            bonus += 1
        token_meta[token]["bonus"] = max(token_meta[token]["bonus"], bonus)

    ranked_tokens = sorted(
        ordered_tokens,
        key=lambda token: (
            -(token_meta[token]["count"] * 5 + token_meta[token]["bonus"] + max(0, 6 - token_meta[token]["first"])),
            token_meta[token]["first"],
        ),
    )[: max(1, min(int(max_terms or 8), 12))]
    if not ranked_tokens:
        return cleaned[:140]

    selected = sorted(ranked_tokens, key=lambda token: token_meta[token]["first"])
    phrase_tokens: Optional[Tuple[str, str]] = None
    for left, right in zip(filtered, filtered[1:]):
        if left == right:
            continue
        if left in selected and right in selected and len(left) >= 4 and len(right) >= 4:
            phrase_tokens = (left, right)
            break

    if phrase_tokens is not None:
        phrase = f'"{phrase_tokens[0]} {phrase_tokens[1]}"'
        extras = [token for token in selected if token not in set(phrase_tokens)]
        return " ".join([phrase] + extras[: max(0, len(selected) - 2)])

    return " ".join(selected)


def _score_search_result(query_text: str, result: Dict[str, str]) -> float:
    query_tokens = _tokenize_search_terms(query_text)
    if not query_tokens:
        return 0.0

    url = str(result.get("url") or "").strip().lower()
    try:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.netloc or "").lower().strip()
        path = (parsed.path or "").lower().strip()
    except Exception:
        host = ""
        path = ""

    title = _clean_text_for_query(str(result.get("title") or "")).lower()
    snippet = _clean_text_for_query(str(result.get("snippet") or "")).lower()
    combined = f"{title} {snippet}".strip()
    if not combined:
        return 0.0

    distinct_query = list(dict.fromkeys(query_tokens))
    title_tokens = set(_tokenize_search_terms(title))
    snippet_tokens = set(_tokenize_search_terms(snippet))
    title_hits = sum(1 for token in distinct_query if token in title_tokens)
    snippet_hits = sum(1 for token in distinct_query if token in snippet_tokens and token not in title_tokens)
    query_bigrams = {f"{left} {right}" for left, right in zip(query_tokens, query_tokens[1:]) if left != right}
    bigram_hits = sum(1 for phrase in query_bigrams if phrase in combined)

    exact_phrase_bonus = 0
    normalized_query = " ".join(distinct_query[:6]).strip()
    if normalized_query and normalized_query in combined:
        exact_phrase_bonus = 12

    score = float(title_hits * 12 + snippet_hits * 5 + bigram_hits * 8 + exact_phrase_bonus)
    if title_hits > 0 and snippet_hits > 0:
        score += 4.0
    if len(distinct_query) >= 2 and (title_hits + snippet_hits) < 2:
        score -= 10.0

    is_generic_search_shortcut = (
        ("duckduckgo.com" in host and path.startswith("/"))
        or ("bing.com" in host and path.startswith("/search"))
        or ("google.com" in host and path.startswith("/search"))
        or ("wikipedia.org" in host and path.startswith("/w/index.php"))
    )
    if is_generic_search_shortcut:
        score -= 120.0

    return score


def _rerank_search_results(results: List[Dict[str, str]], query_text: str) -> List[Dict[str, str]]:
    if not results:
        return []

    scored = [(_score_search_result(query_text, item), idx, item) for idx, item in enumerate(results)]
    if not any(score > 0 for score, _, _ in scored):
        return results

    scored.sort(key=lambda row: (-row[0], row[1]))
    return [item for _, _, item in scored]


def _search_ddgs_text_results(query: str, max_results: int = 10) -> List[Dict[str, str]]:
    if _DDGSClient is None:
        return []

    timeout_seconds = int(float(os.getenv("OCR_WEB_SEARCH_TIMEOUT", "12")))
    region = os.getenv("OCR_DDGS_REGION", "us-en").strip().lower() or "us-en"
    safesearch = os.getenv("OCR_DDGS_SAFESEARCH", "moderate").strip().lower() or "moderate"
    backend = os.getenv("OCR_DDGS_BACKEND", "auto").strip().lower() or "auto"
    timelimit = (os.getenv("OCR_DDGS_TIMELIMIT", "").strip().lower() or None)

    if safesearch not in {"on", "moderate", "off"}:
        safesearch = "moderate"
    if timelimit not in {None, "d", "w", "m", "y"}:
        timelimit = None

    requested = max(1, min(int(max_results or 10), 25))

    try:
        with _DDGSClient(timeout=timeout_seconds, verify=True) as ddgs:
            rows = ddgs.text(
                query,
                region=region,
                safesearch=safesearch,
                timelimit=timelimit,
                page=1,
                backend=backend,
                max_results=requested,
            )
    except Exception:
        return []

    out: List[Dict[str, str]] = []
    seen_urls: set[str] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue

        href = str(row.get("href") or row.get("url") or "").strip()
        title = str(row.get("title") or "").strip()
        snippet = str(row.get("body") or row.get("snippet") or "").strip()
        if not href or not title:
            continue

        if not _is_valid_result_url(href, title):
            continue

        key = href.lower()
        if key in seen_urls:
            continue
        seen_urls.add(key)
        out.append({"title": title, "snippet": snippet, "url": href})
        if len(out) >= requested:
            break

    return _rerank_search_results(out, query_text=query)


def _ddgs_common_options(max_results: int = 10) -> Dict[str, Any]:
    timeout_seconds = int(float(os.getenv("OCR_WEB_SEARCH_TIMEOUT", "12")))
    region = os.getenv("OCR_DDGS_REGION", "us-en").strip().lower() or "us-en"
    safesearch = os.getenv("OCR_DDGS_SAFESEARCH", "moderate").strip().lower() or "moderate"
    backend = os.getenv("OCR_DDGS_BACKEND", "auto").strip().lower() or "auto"
    timelimit = (os.getenv("OCR_DDGS_TIMELIMIT", "").strip().lower() or None)

    if safesearch not in {"on", "moderate", "off"}:
        safesearch = "moderate"
    if timelimit not in {None, "d", "w", "m", "y"}:
        timelimit = None

    requested = max(1, min(int(max_results or 10), 25))
    return {
        "timeout": timeout_seconds,
        "region": region,
        "safesearch": safesearch,
        "backend": backend,
        "timelimit": timelimit,
        "max_results": requested,
    }


def _search_ddgs_vertical(query: str, vertical: str = "text", max_results: int = 10) -> List[Dict[str, Any]]:
    if _DDGSClient is None:
        return []

    opts = _ddgs_common_options(max_results=max_results)
    try:
        with _DDGSClient(timeout=int(opts["timeout"]), verify=True) as ddgs:
            if vertical == "images":
                rows = ddgs.images(
                    query=query,
                    region=str(opts["region"]),
                    safesearch=str(opts["safesearch"]),
                    timelimit=opts["timelimit"],
                    page=1,
                    backend=str(opts["backend"]),
                    max_results=int(opts["max_results"]),
                )
            elif vertical == "videos":
                rows = ddgs.videos(
                    query=query,
                    region=str(opts["region"]),
                    safesearch=str(opts["safesearch"]),
                    timelimit=opts["timelimit"],
                    page=1,
                    backend=str(opts["backend"]),
                    max_results=int(opts["max_results"]),
                )
            elif vertical == "news":
                rows = ddgs.news(
                    query=query,
                    region=str(opts["region"]),
                    safesearch=str(opts["safesearch"]),
                    timelimit=opts["timelimit"],
                    page=1,
                    backend=str(opts["backend"]),
                    max_results=int(opts["max_results"]),
                )
            elif vertical == "books":
                rows = ddgs.books(
                    query=query,
                    page=1,
                    backend=str(opts["backend"]),
                    max_results=int(opts["max_results"]),
                )
            else:
                rows = ddgs.text(
                    query=query,
                    region=str(opts["region"]),
                    safesearch=str(opts["safesearch"]),
                    timelimit=opts["timelimit"],
                    page=1,
                    backend=str(opts["backend"]),
                    max_results=int(opts["max_results"]),
                )
    except Exception:
        return []

    return [r for r in (rows or []) if isinstance(r, dict)][: int(opts["max_results"])]


def _flatten_ddg_related_topics(related: Any) -> List[Dict[str, str]]:
    flat: List[Dict[str, str]] = []
    if not isinstance(related, list):
        return flat

    for item in related:
        if isinstance(item, dict) and isinstance(item.get("Topics"), list):
            flat.extend(_flatten_ddg_related_topics(item.get("Topics")))
            continue

        if not isinstance(item, dict):
            continue
        text = str(item.get("Text") or "").strip()
        url = str(item.get("FirstURL") or "").strip()
        if not text and not url:
            continue

        title = text
        snippet = ""
        if " - " in text:
            title, snippet = text.split(" - ", 1)
            title = title.strip()
            snippet = snippet.strip()

        flat.append({"title": title or text, "snippet": snippet, "url": url})

    return flat


def _search_duckduckgo_instant_answer(query: str, max_results: int = 6) -> Dict[str, Any]:
    params = {
        "q": query,
        "format": "json",
        "no_redirect": "1",
        "no_html": "1",
        "skip_disambig": "1",
    }
    endpoint = f"https://api.duckduckgo.com/?{urllib.parse.urlencode(params)}"

    timeout_seconds = float(os.getenv("OCR_WEB_SEARCH_TIMEOUT", "12"))
    req = urllib.request.Request(
        endpoint,
        headers={
            "User-Agent": "portable-pytesseract-ocr-studio/1.0",
            "Accept": "application/json",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as err:
        raise RuntimeError(f"DuckDuckGo request failed with HTTP {err.code}") from err
    except urllib.error.URLError as err:
        raise RuntimeError(f"DuckDuckGo request failed: {err.reason}") from err
    except Exception as err:
        raise RuntimeError(f"DuckDuckGo request failed: {err}") from err

    try:
        payload = json.loads(raw)
    except Exception as err:
        raise RuntimeError(f"Could not parse DuckDuckGo response: {err}") from err

    heading = str(payload.get("Heading") or "").strip()
    abstract_text = str(payload.get("AbstractText") or "").strip()
    abstract_url = str(payload.get("AbstractURL") or "").strip()

    sources: List[Dict[str, str]] = []
    if abstract_text:
        sources.append(
            {
                "title": heading or query,
                "snippet": abstract_text,
                "url": abstract_url,
            }
        )

    related = _flatten_ddg_related_topics(payload.get("RelatedTopics"))
    for item in related:
        if len(sources) >= max_results:
            break
        sources.append(item)

    topic = ""
    if heading:
        topic = heading
    elif sources and sources[0].get("title"):
        topic = str(sources[0].get("title") or "").strip()
    elif query:
        topic = query
    else:
        topic = "Unknown topic"

    summary = ""
    if abstract_text:
        summary = abstract_text
    elif sources and sources[0].get("snippet"):
        summary = str(sources[0].get("snippet") or "").strip()

    confidence = "low"
    if abstract_text and heading:
        confidence = "high"
    elif len(sources) >= 3:
        confidence = "medium"

    return {
        "provider": "duckduckgo_instant_answer",
        "query": query,
        "topic": topic,
        "summary": summary,
        "confidence": confidence,
        "sources": sources[:max_results],
    }


def _search_duckduckgo_html_results(query: str, max_results: int = 10) -> List[Dict[str, str]]:
    endpoint = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote_plus(query)}"
    timeout_seconds = float(os.getenv("OCR_WEB_SEARCH_TIMEOUT", "12"))
    req = urllib.request.Request(
        endpoint,
        headers={
            "User-Agent": "portable-pytesseract-ocr-studio/1.0",
            "Accept": "text/html,application/xhtml+xml",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            raw_html = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return []

    link_pat = re.compile(
        r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    uddg_link_pat = re.compile(
        r'<a[^>]*href="(?P<href>[^"]*uddg=[^"]+)"[^>]*>(?P<title>.*?)</a>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    snippet_pat = re.compile(
        r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(?P<snippet>.*?)</a>|<div[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(?P<snippet2>.*?)</div>',
        flags=re.IGNORECASE | re.DOTALL,
    )

    links = list(link_pat.finditer(raw_html))
    if not links:
        links = list(uddg_link_pat.finditer(raw_html))
    snippets = list(snippet_pat.finditer(raw_html))

    def _clean_html_text(value: str) -> str:
        txt = re.sub(r"<[^>]+>", " ", value or "")
        txt = html.unescape(re.sub(r"\s+", " ", txt)).strip()
        return txt

    def _normalize_result_href(raw_href: str) -> str:
        href = html.unescape(raw_href or "").strip()
        if not href:
            return ""

        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = "https://duckduckgo.com" + href

        try:
            parsed = urllib.parse.urlparse(href)
            if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
                q = urllib.parse.parse_qs(parsed.query)
                uddg = (q.get("uddg") or [""])[0]
                if uddg:
                    return urllib.parse.unquote(uddg)
        except Exception:
            pass

        return href

    out: List[Dict[str, str]] = []
    seen_urls: set[str] = set()
    for idx, match in enumerate(links):
        href = _normalize_result_href(match.group("href") or "")
        title = _clean_html_text(match.group("title") or "")
        snippet = ""
        if idx < len(snippets):
            snippet = _clean_html_text(snippets[idx].group("snippet") or snippets[idx].group("snippet2") or "")

        if not href or not title:
            continue

        try:
            parsed = urllib.parse.urlparse(href)
            if not parsed.scheme.startswith("http"):
                continue
            if parsed.netloc.endswith("duckduckgo.com"):
                continue
        except Exception:
            continue

        key = href.strip().lower()
        if key in seen_urls:
            continue
        seen_urls.add(key)

        out.append({"title": title, "snippet": snippet, "url": href})
        if len(out) >= max_results:
            break

    return out


def _search_duckduckgo_lite_results(query: str, max_results: int = 10) -> List[Dict[str, str]]:
    endpoint = f"https://lite.duckduckgo.com/lite/?q={urllib.parse.quote_plus(query)}"
    timeout_seconds = float(os.getenv("OCR_WEB_SEARCH_TIMEOUT", "12"))
    req = urllib.request.Request(
        endpoint,
        headers={
            "User-Agent": "portable-pytesseract-ocr-studio/1.0",
            "Accept": "text/html,application/xhtml+xml",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            raw_html = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return []

    def _clean_html_text(value: str) -> str:
        txt = re.sub(r"<[^>]+>", " ", value or "")
        txt = html.unescape(re.sub(r"\s+", " ", txt)).strip()
        return txt

    def _normalize_result_href(raw_href: str) -> str:
        href = html.unescape(raw_href or "").strip()
        if not href:
            return ""

        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = "https://duckduckgo.com" + href

        try:
            parsed = urllib.parse.urlparse(href)
            if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
                q = urllib.parse.parse_qs(parsed.query)
                uddg = (q.get("uddg") or [""])[0]
                if uddg:
                    return urllib.parse.unquote(uddg)
        except Exception:
            pass

        return href

    link_pat = re.compile(
        r'<a[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
        flags=re.IGNORECASE | re.DOTALL,
    )

    out: List[Dict[str, str]] = []
    seen_urls: set[str] = set()
    for match in link_pat.finditer(raw_html):
        raw_href = match.group("href") or ""
        href = _normalize_result_href(raw_href)
        title = _clean_html_text(match.group("title") or "")
        if not href or not title:
            continue

        if not _is_valid_result_url(href, title):
            continue

        key = href.strip().lower()
        if key in seen_urls:
            continue
        seen_urls.add(key)
        out.append({"title": title, "snippet": "", "url": href})
        if len(out) >= max_results:
            break

    return out


def _search_bing_html_results(query: str, max_results: int = 10) -> List[Dict[str, str]]:
    endpoint = f"https://www.bing.com/search?q={urllib.parse.quote_plus(query)}"
    timeout_seconds = float(os.getenv("OCR_WEB_SEARCH_TIMEOUT", "12"))
    req = urllib.request.Request(
        endpoint,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            raw_html = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return []

    def _clean_html_text(value: str) -> str:
        txt = re.sub(r"<[^>]+>", " ", value or "")
        txt = html.unescape(re.sub(r"\s+", " ", txt)).strip()
        return txt

    item_pat = re.compile(
        r'<li[^>]*class="[^"]*b_algo[^"]*"[^>]*>(?P<item>.*?)</li>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    link_pat = re.compile(
        r'<h2[^>]*>\s*<a[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    snippet_pat = re.compile(
        r'<p[^>]*>(?P<snippet>.*?)</p>',
        flags=re.IGNORECASE | re.DOTALL,
    )

    out: List[Dict[str, str]] = []
    seen_urls: set[str] = set()
    for item_match in item_pat.finditer(raw_html):
        chunk = item_match.group("item") or ""
        lm = link_pat.search(chunk)
        if not lm:
            continue

        href = html.unescape((lm.group("href") or "").strip())
        title = _clean_html_text(lm.group("title") or "")
        if not href or not title:
            continue

        if not _is_valid_result_url(href, title):
            continue

        key = href.lower().strip()
        if key in seen_urls:
            continue
        seen_urls.add(key)

        sm = snippet_pat.search(chunk)
        snippet = _clean_html_text(sm.group("snippet") if sm else "")

        out.append({"title": title, "snippet": snippet, "url": href})
        if len(out) >= max_results:
            break

    return out


def _search_via_jina_ai_proxy(query: str, max_results: int = 10) -> List[Dict[str, str]]:
    target = f"https://www.bing.com/search?q={urllib.parse.quote_plus(query)}"
    endpoint = f"https://r.jina.ai/http://{target.replace('https://', '', 1)}"
    timeout_seconds = float(os.getenv("OCR_WEB_SEARCH_TIMEOUT", "12"))
    req = urllib.request.Request(
        endpoint,
        headers={
            "User-Agent": "portable-pytesseract-ocr-studio/1.0",
            "Accept": "text/plain,text/markdown;q=0.9,*/*;q=0.8",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            raw_text = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return []

    link_pat = re.compile(r"\[(?P<title>[^\]]+)\]\((?P<url>https?://[^)]+)\)", flags=re.IGNORECASE)

    out: List[Dict[str, str]] = []
    seen: set[str] = set()
    blocked_hosts = {"bing.com", "www.bing.com", "r.jina.ai"}
    for m in link_pat.finditer(raw_text):
        title = (m.group("title") or "").strip()
        url = (m.group("url") or "").strip()
        if not title or not url:
            continue

        try:
            host = (urllib.parse.urlparse(url).netloc or "").lower().strip()
        except Exception:
            continue

        if not _is_valid_result_url(url, title):
            continue

        key = url.lower()
        if key in seen:
            continue
        seen.add(key)

        out.append({"title": title, "snippet": "", "url": url})
        if len(out) >= max_results:
            break

    return out


_BLOCKED_RESULT_HOSTS = {
    "r.bing.com", "c.bing.com", "s.bing.com", "api.bing.com",
    "bat.bing.com", "bing.com", "www.bing.com",
    "duckduckgo.com", "lite.duckduckgo.com",
    "r.jina.ai", "jina.ai",
    "google.com", "www.google.com",
    "schema.org", "w3.org", "openstreetmap.org",
}

_BLOCKED_RESULT_EXTENSIONS = {
    ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".ico", ".css", ".js", ".woff", ".woff2", ".ttf",
    ".json", ".xml", ".rss", ".atom",
}

_BLOCKED_RESULT_PATH_PREFIXES = (
    "/rp/", "/th/", "/images/", "/assets/", "/static/",
    "/cdn/", "/media/favicon", "/favicon",
)


def _is_valid_result_url(url: str, title: str = "") -> bool:
    if not url:
        return False
    try:
        p = urllib.parse.urlparse(url)
        host = (p.netloc or "").lower().strip()
        path = (p.path or "").lower().strip()
    except Exception:
        return False

    if not host or not p.scheme.startswith("http"):
        return False

    if host in _BLOCKED_RESULT_HOSTS:
        return False

    # Block CDN/asset subdomains
    if any(sub in host for sub in ("cdn.", "static.", "assets.", "img.", "images.")):
        return False

    if any(path.endswith(ext) for ext in _BLOCKED_RESULT_EXTENSIONS):
        return False

    if any(path.startswith(pfx) for pfx in _BLOCKED_RESULT_PATH_PREFIXES):
        return False

    return True


def _build_search_shortcuts(query: str) -> List[Dict[str, str]]:
    q = urllib.parse.quote_plus(query)
    return [
        {
            "title": f"DuckDuckGo results for {query}",
            "snippet": "Open DuckDuckGo web results.",
            "url": f"https://duckduckgo.com/?q={q}",
        },
        {
            "title": f"Bing results for {query}",
            "snippet": "Open Bing web results.",
            "url": f"https://www.bing.com/search?q={q}",
        },
        {
            "title": f"Google results for {query}",
            "snippet": "Open Google web results.",
            "url": f"https://www.google.com/search?q={q}",
        },
        {
            "title": f"Wikipedia search for {query}",
            "snippet": "Open Wikipedia search results.",
            "url": f"https://en.wikipedia.org/w/index.php?search={q}",
        },
    ]


def _quality_band(score: float) -> str:
    if score >= 78:
        return "good"
    if score >= 58:
        return "fair"
    return "poor"


def _page_quality_metrics(image: Image.Image) -> Dict[str, float]:
    gray = image.convert("L")
    stat = ImageStat.Stat(gray)

    brightness = float(stat.mean[0]) if stat.mean else 0.0
    contrast = float(stat.stddev[0]) if stat.stddev else 0.0

    edge_img = gray.filter(ImageFilter.FIND_EDGES)
    edge_stat = ImageStat.Stat(edge_img)
    sharpness = float(edge_stat.stddev[0]) if edge_stat.stddev else 0.0

    contrast_score = min(100.0, max(0.0, (contrast / 64.0) * 100.0))
    sharpness_score = min(100.0, max(0.0, (sharpness / 45.0) * 100.0))
    exposure_score = max(0.0, 100.0 - (abs(brightness - 128.0) / 128.0) * 100.0)
    overall = max(0.0, min(100.0, contrast_score * 0.35 + sharpness_score * 0.45 + exposure_score * 0.20))

    return {
        "brightness": round(brightness, 2),
        "contrast": round(contrast, 2),
        "sharpness": round(sharpness, 2),
        "exposure_score": round(exposure_score, 2),
        "contrast_score": round(contrast_score, 2),
        "sharpness_score": round(sharpness_score, 2),
        "overall_score": round(overall, 2),
        "quality_band": _quality_band(overall),
    }


def _run_batch_ocr_pdf_job(job_id: str, lang: str, psm: int) -> None:
    with PDF_JOBS_LOCK:
        job = BATCH_PDF_JOBS.get(job_id)
    if not job:
        return

    docs: List[Tuple[str, DocumentStore]] = []
    for file_id in job.file_ids:
        doc = FILES.get(file_id)
        if doc:
            docs.append((file_id, doc))

    if not docs:
        with PDF_JOBS_LOCK:
            current = BATCH_PDF_JOBS.get(job_id)
            if current:
                current.status = "failed"
                current.error = "All file sessions expired. Upload again."
        return

    total_docs = len(docs)
    total_pages = sum(len(doc.pages) for _, doc in docs)
    page_timeout = int(os.getenv("OCR_PDF_PAGE_TIMEOUT", "120"))

    with PDF_JOBS_LOCK:
        current = BATCH_PDF_JOBS.get(job_id)
        if current:
            current.status = "running"
            current.total_docs = total_docs
            current.total_pages = total_pages

    done_docs = 0
    done_pages = 0

    try:
        fd, output_path = tempfile.mkstemp(suffix="_searchable_ocr_batch.zip")
        os.close(fd)
        used_names: Dict[str, int] = {}

        with zipfile.ZipFile(output_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for _, doc in docs:
                pdf_bytes = _build_searchable_pdf_bytes(doc.pages, lang=lang, psm=psm, page_timeout=page_timeout)
                safe_base = _safe_pdf_name(doc.filename)
                unique_name = f"{safe_base}_searchable_ocr.pdf"
                if unique_name in used_names:
                    used_names[unique_name] += 1
                    unique_name = f"{safe_base}_searchable_ocr_{used_names[unique_name]}.pdf"
                else:
                    used_names[unique_name] = 1
                zf.writestr(unique_name, pdf_bytes)

                done_docs += 1
                done_pages += len(doc.pages)

                with PDF_JOBS_LOCK:
                    current = BATCH_PDF_JOBS.get(job_id)
                    if current:
                        current.done_docs = done_docs
                        current.done_pages = done_pages
                        if total_pages > 0:
                            current.progress = int((done_pages / total_pages) * 100)
                        else:
                            current.progress = int((done_docs / max(total_docs, 1)) * 100)

        with PDF_JOBS_LOCK:
            current = BATCH_PDF_JOBS.get(job_id)
            if current:
                current.output_path = output_path
                current.progress = 100
                current.status = "done"
    except Exception as err:
        with PDF_JOBS_LOCK:
            current = BATCH_PDF_JOBS.get(job_id)
            if current:
                current.status = "failed"
                current.error = f"Batch searchable PDF generation failed: {err}"


def _run_ocr_pdf_job(job_id: str, lang: str, psm: int) -> None:
    with PDF_JOBS_LOCK:
        job = PDF_JOBS.get(job_id)
    if not job:
        return

    doc = FILES.get(job.file_id)
    if not doc:
        with PDF_JOBS_LOCK:
            current = PDF_JOBS.get(job_id)
            if current:
                current.status = "failed"
                current.error = "File session expired. Upload again."
        return

    page_timeout = int(os.getenv("OCR_PDF_PAGE_TIMEOUT", "120"))
    total_pages = len(doc.pages)

    with PDF_JOBS_LOCK:
        current = PDF_JOBS.get(job_id)
        if current:
            current.status = "running"
            current.total_pages = total_pages

    try:
        for idx in range(1, total_pages + 1):
            with PDF_JOBS_LOCK:
                current = PDF_JOBS.get(job_id)
                if current:
                    current.done_pages = idx - 1
                    current.progress = int(((idx - 1) / total_pages) * 100)

        pdf_bytes = _build_searchable_pdf_bytes(doc.pages, lang=lang, psm=psm, page_timeout=page_timeout)

        fd, output_path = tempfile.mkstemp(suffix="_searchable_ocr.pdf")
        os.close(fd)
        with open(output_path, "wb") as f:
            f.write(pdf_bytes)

        with PDF_JOBS_LOCK:
            current = PDF_JOBS.get(job_id)
            if current:
                current.output_path = output_path
                current.progress = 100
                current.status = "done"
    except Exception as err:
        with PDF_JOBS_LOCK:
            current = PDF_JOBS.get(job_id)
            if current:
                current.status = "failed"
                current.error = f"Searchable PDF generation failed: {err}"


@app.get("/")
def home():
    return render_template("index.html")
    
@app.get("/tutorial_quickstart.gif")
def tutorial_quickstart_gif():
    root = os.path.dirname(os.path.abspath(__file__))
    gif_path = os.path.join(root, "tutorial_quickstart.gif")
    if not os.path.exists(gif_path):
        return jsonify({"error": "Tutorial GIF not found."}), 404
    return send_file(gif_path, mimetype="image/gif")


@app.post("/api/upload")
@require_api_auth
def upload_file():
    _configure_tesseract()
    _cleanup_store()

    if "file" not in request.files:
        return jsonify({"error": "No file sent."}), 400

    up = request.files["file"]
    if not up.filename:
        return jsonify({"error": "Missing file name."}), 400

    name = up.filename
    content = up.read()

    try:
        pages, file_type, embedded_text_pages = _parse_uploaded_content(name, content)
    except Exception as err:
        return jsonify({"error": f"Could not parse file: {err}"}), 400

    file_id = str(uuid.uuid4())
    FILES[file_id] = DocumentStore(
        pages=pages,
        filename=name,
        file_type=file_type,
        embedded_text_pages=embedded_text_pages,
        original_bytes=content if str(name).lower().endswith(".docx") else b"",
    )

    return jsonify(
        {
            "file_id": file_id,
            "filename": name,
            "file_type": file_type,
            "pages": len(pages),
        }
    )


@app.post("/api/upload_batch")
@require_api_auth
def upload_batch():
    _configure_tesseract()
    _cleanup_store()

    incoming = request.files.getlist("files")
    if not incoming:
        return jsonify({"error": "No files sent."}), 400

    prepared = []
    for idx, up in enumerate(incoming):
        name = (up.filename or "").strip()
        if not name:
            continue
        prepared.append((idx, name, up.read()))

    if not prepared:
        return jsonify({"error": "Missing file name."}), 400

    uploaded = []
    failed = []

    def _worker(item):
        idx, name, content = item
        pages, file_type, embedded_text_pages = _parse_uploaded_content(name, content)
        return idx, name, pages, file_type, embedded_text_pages, (content if str(name).lower().endswith(".docx") else b"")

    max_workers = max(1, min(4, len(prepared)))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_worker, item) for item in prepared]
        for future in as_completed(futures):
            try:
                idx, name, pages, file_type, embedded_text_pages, original_bytes = future.result()
                file_id = str(uuid.uuid4())
                FILES[file_id] = DocumentStore(
                    pages=pages,
                    filename=name,
                    file_type=file_type,
                    embedded_text_pages=embedded_text_pages,
                    original_bytes=original_bytes,
                )
                uploaded.append(
                    {
                        "_idx": idx,
                        "file_id": file_id,
                        "filename": name,
                        "file_type": file_type,
                        "pages": len(pages),
                    }
                )
            except Exception as err:
                failed.append({"error": str(err)})

    uploaded.sort(key=lambda item: item.get("_idx", 0))
    for item in uploaded:
        item.pop("_idx", None)

    status_code = 200 if uploaded else 400
    return jsonify({"uploaded": uploaded, "failed": failed}), status_code


@app.get("/api/page/<file_id>/<int:page_no>")
@require_api_auth
def get_page(file_id: str, page_no: int):
    doc = FILES.get(file_id)
    if not doc:
        return jsonify({"error": "File session expired. Upload again."}), 404

    if page_no < 1 or page_no > len(doc.pages):
        return jsonify({"error": "Invalid page."}), 400

    image = doc.pages[page_no - 1]
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.get("/api/docx/<file_id>")
@require_api_auth
def get_docx_bytes(file_id: str):
    doc = FILES.get(file_id)
    if not doc:
        return jsonify({"error": "File session expired. Upload again."}), 404

    if not str(doc.filename or "").lower().endswith(".docx"):
        return jsonify({"error": "Active file is not a DOCX document."}), 400

    raw = bytes(getattr(doc, "original_bytes", b"") or b"")
    if not raw:
        return jsonify({"error": "DOCX source bytes are unavailable for this session."}), 404

    buf = io.BytesIO(raw)
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=False,
        download_name=doc.filename,
    )


@app.post("/api/ocr")
@require_api_auth
def ocr_page():
    payload = request.get_json(force=True)
    file_id = payload.get("file_id", "")
    page_no = int(payload.get("page", 1))
    lang = payload.get("lang", "eng")
    psm = int(payload.get("psm", 3))
    preset = payload.get("preset", "")
    low_conf_threshold = int(payload.get("low_conf_threshold", 55))
    region = payload.get("region")

    doc = FILES.get(file_id)
    if not doc:
        return jsonify({"error": "File session expired. Upload again."}), 404

    if page_no < 1 or page_no > len(doc.pages):
        return jsonify({"error": "Invalid page."}), 400

    image = doc.pages[page_no - 1]
    is_image = str(getattr(doc, "file_type", "image") or "image").lower() == "image"
    is_region = bool(region)

    if not is_region:
        native_pages = list(getattr(doc, "embedded_text_pages", []) or [])
        native_text = native_pages[page_no - 1] if page_no - 1 < len(native_pages) else ""
        native_text = str(native_text or "").strip()
        if native_text:
            resolved_lang = (lang or "eng").strip().lower() or "eng"
            return jsonify(
                {
                    "text": native_text,
                    "confidence_score": 99.0,
                    "low_conf_threshold": int(low_conf_threshold),
                    "low_confidence_count": 0,
                    "low_confidence_words": [],
                    "words": [],
                    "lang": resolved_lang,
                    "detected_lang": resolved_lang,
                    "lang_scores": {resolved_lang: 99.0},
                    "preset": (preset or "").strip().lower(),
                    "psm": int(psm),
                    "source": "embedded-text",
                }
            )
    try:
        image = _crop_region(image, region)
    except ValueError as err:
        return jsonify({"error": str(err)}), 400

    try:
        resolved = _resolve_ocr_options(
            image=image,
            lang=lang,
            psm=psm,
            preset=preset,
            low_conf_threshold=low_conf_threshold,
            is_region=is_region,
            is_image=is_image,
        )
        details = _ocr_best_details(
            image=image,
            lang=resolved["lang"],
            psm=int(resolved["psm"]),
            low_conf_threshold=int(resolved["low_conf_threshold"]),
            is_region=is_region,
            is_image=is_image,
        )
    except Exception as err:
        return jsonify({"error": f"OCR failed: {err}"}), 500

    return jsonify(
        {
            "text": details["text"],
            "confidence_score": details["confidence_score"],
            "low_conf_threshold": details["low_conf_threshold"],
            "low_confidence_count": details["low_confidence_count"],
            "low_confidence_words": details["low_confidence_words"],
            "words": details.get("words", [])[:500],
            "lang": resolved["lang"],
            "detected_lang": resolved["detected_lang"],
            "lang_scores": resolved["lang_scores"],
            "preset": resolved["preset"],
            "psm": resolved["psm"],
        }
    )


@app.post("/api/ocr_image")
@require_api_auth
def ocr_uploaded_image():
    uploaded = request.files.get("image")
    if not uploaded:
        return jsonify({"error": "image file is required."}), 400

    lang = request.form.get("lang", "eng")
    psm = int(request.form.get("psm", 3))
    preset = request.form.get("preset", "")
    low_conf_threshold = int(request.form.get("low_conf_threshold", 55))

    try:
        image = Image.open(uploaded.stream).convert("RGB")
    except Exception as err:
        return jsonify({"error": f"Invalid image payload: {err}"}), 400

    try:
        resolved = _resolve_ocr_options(
            image=image,
            lang=lang,
            psm=psm,
            preset=preset,
            low_conf_threshold=low_conf_threshold,
            is_region=True,
            is_image=True,
        )
        details = _ocr_best_details(
            image=image,
            lang=resolved["lang"],
            psm=int(resolved["psm"]),
            low_conf_threshold=int(resolved["low_conf_threshold"]),
            is_region=True,
            is_image=True,
        )
    except Exception as err:
        return jsonify({"error": f"OCR failed: {err}"}), 500

    return jsonify(
        {
            "text": details["text"],
            "confidence_score": details["confidence_score"],
            "low_conf_threshold": details["low_conf_threshold"],
            "low_confidence_count": details["low_confidence_count"],
            "low_confidence_words": details["low_confidence_words"],
            "words": details.get("words", [])[:500],
            "lang": resolved["lang"],
            "detected_lang": resolved["detected_lang"],
            "lang_scores": resolved["lang_scores"],
            "preset": resolved["preset"],
            "psm": resolved["psm"],
            "source": "region-image",
        }
    )


@app.post("/api/ocr_once")
@require_api_auth
def ocr_once():
    _configure_tesseract()

    payload = request.get_json(force=True)
    encoded = payload.get("file_base64", "")
    filename = payload.get("filename", "")
    file_type = payload.get("file_type", "")
    lang = payload.get("lang", "eng")
    psm = int(payload.get("psm", 3))
    preset = payload.get("preset", "")
    low_conf_threshold = int(payload.get("low_conf_threshold", 55))
    page_no = payload.get("page")
    start_page = payload.get("start_page")
    end_page = payload.get("end_page")
    region = payload.get("region")

    try:
        file_bytes = _decode_base64_file(encoded)
        pages, resolved_type, embedded_text_pages = _parse_uploaded_content(filename or "uploaded.bin", file_bytes)
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    except Exception as err:
        return jsonify({"error": f"Could not parse file: {err}"}), 400

    total_pages = len(pages)
    if total_pages == 0:
        return jsonify({"error": "No pages could be extracted from the input file."}), 400

    if page_no is not None:
        try:
            selected_page = int(page_no)
        except Exception:
            return jsonify({"error": "page must be an integer."}), 400

        if selected_page < 1 or selected_page > total_pages:
            return jsonify({"error": f"Invalid page: {selected_page}."}), 400

        if not region:
            native_text = ""
            if selected_page - 1 < len(embedded_text_pages):
                native_text = str(embedded_text_pages[selected_page - 1] or "").strip()
            if native_text:
                resolved_lang = (lang or "eng").strip().lower() or "eng"
                return jsonify(
                    {
                        "text": native_text,
                        "confidence_score": 99.0,
                        "low_conf_threshold": int(low_conf_threshold),
                        "low_confidence_count": 0,
                        "low_confidence_words": [],
                        "words": [],
                        "lang": resolved_lang,
                        "detected_lang": resolved_lang,
                        "lang_scores": {resolved_lang: 99.0},
                        "preset": (preset or "").strip().lower(),
                        "psm": int(psm),
                        "page": selected_page,
                        "total_pages": total_pages,
                        "file_type": resolved_type,
                        "stored": False,
                        "source": "embedded-text",
                    }
                )

        try:
            is_region = bool(region)
            is_image = resolved_type == "image"
            image = _crop_region(pages[selected_page - 1], region)
            resolved = _resolve_ocr_options(
                image=image,
                lang=lang,
                psm=psm,
                preset=preset,
                low_conf_threshold=low_conf_threshold,
                is_region=is_region,
                is_image=is_image,
            )
            details = _ocr_best_details(
                image=image,
                lang=resolved["lang"],
                psm=int(resolved["psm"]),
                low_conf_threshold=int(resolved["low_conf_threshold"]),
                is_region=is_region,
                is_image=is_image,
            )
        except ValueError as err:
            return jsonify({"error": str(err)}), 400
        except Exception as err:
            return jsonify({"error": f"OCR failed: {err}"}), 500

        return jsonify(
            {
                "text": details["text"],
                "confidence_score": details["confidence_score"],
                "low_conf_threshold": details["low_conf_threshold"],
                "low_confidence_count": details["low_confidence_count"],
                "low_confidence_words": details["low_confidence_words"],
                "words": details.get("words", [])[:500],
                "lang": resolved["lang"],
                "detected_lang": resolved["detected_lang"],
                "lang_scores": resolved["lang_scores"],
                "preset": resolved["preset"],
                "psm": resolved["psm"],
                "page": selected_page,
                "total_pages": total_pages,
                "file_type": resolved_type,
                "stored": False,
            }
        )

    if start_page is None:
        start_page = 1
    if end_page is None:
        end_page = total_pages

    try:
        start_page = int(start_page)
        end_page = int(end_page)
    except Exception:
        return jsonify({"error": "start_page and end_page must be integers."}), 400

    if start_page < 1 or end_page > total_pages or start_page > end_page:
        return jsonify({"error": f"Invalid page range: {start_page}-{end_page}."}), 400

    if not region and embedded_text_pages:
        fast_results = []
        resolved_lang = (lang or "eng").strip().lower() or "eng"
        for page_idx in range(start_page, end_page + 1):
            native_text = str(embedded_text_pages[page_idx - 1] or "").strip() if page_idx - 1 < len(embedded_text_pages) else ""
            if native_text:
                fast_results.append(
                    {
                        "page": page_idx,
                        "text": native_text,
                        "confidence_score": 99.0,
                        "low_conf_threshold": int(low_conf_threshold),
                        "low_confidence_count": 0,
                        "lang": resolved_lang,
                        "detected_lang": resolved_lang,
                        "preset": (preset or "").strip().lower(),
                        "psm": int(psm),
                        "source": "embedded-text",
                    }
                )
        if fast_results:
            return jsonify(
                {
                    "results": fast_results,
                    "start_page": start_page,
                    "end_page": end_page,
                    "total_pages": total_pages,
                    "file_type": resolved_type,
                    "stored": False,
                }
            )

    def _ocr_page_once(page_idx: int):
        image = pages[page_idx - 1]
        is_image = resolved_type == "image"
        is_reg = bool(region and page_idx == start_page and start_page == end_page)
        if is_reg:
            image = _crop_region(image, region)
        resolved = _resolve_ocr_options(
            image=image, lang=lang, psm=psm, preset=preset,
            low_conf_threshold=low_conf_threshold, is_region=is_reg, is_image=is_image,
        )
        details = _ocr_best_details(
            image=image, lang=resolved["lang"],
            psm=int(resolved["psm"]),
            low_conf_threshold=int(resolved["low_conf_threshold"]),
            is_region=is_reg,
            is_image=is_image,
        )
        return {
            "page": page_idx,
            "text": details["text"],
            "confidence_score": details["confidence_score"],
            "low_conf_threshold": details["low_conf_threshold"],
            "low_confidence_count": details["low_confidence_count"],
            "lang": resolved["lang"],
            "detected_lang": resolved["detected_lang"],
            "preset": resolved["preset"],
            "psm": resolved["psm"],
        }

    page_range = list(range(start_page, end_page + 1))
    n_workers = max(1, min(4, len(page_range)))
    results_map: Dict[int, Any] = {}
    try:
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futs = {pool.submit(_ocr_page_once, pi): pi for pi in page_range}
            for fut in as_completed(futs):
                results_map[futs[fut]] = fut.result()
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    except Exception as err:
        return jsonify({"error": f"OCR failed: {err}"}), 500

    results = [results_map[pi] for pi in page_range if pi in results_map]

    return jsonify(
        {
            "results": results,
            "start_page": start_page,
            "end_page": end_page,
            "total_pages": total_pages,
            "file_type": resolved_type,
            "stored": False,
        }
    )


@app.post("/api/ocr_all")
@require_api_auth
def ocr_all_pages():
    payload = request.get_json(force=True)
    file_id = payload.get("file_id", "")
    lang = payload.get("lang", "eng")
    psm = int(payload.get("psm", 3))
    preset = payload.get("preset", "")
    low_conf_threshold = int(payload.get("low_conf_threshold", 55))

    doc = FILES.get(file_id)
    if not doc:
        return jsonify({"error": "File session expired. Upload again."}), 404

    total_pages = len(doc.pages)
    start_page = int(payload.get("start_page", 1))
    end_page = int(payload.get("end_page", total_pages))

    if start_page < 1 or end_page > total_pages or start_page > end_page:
        return jsonify({"error": f"Invalid page range: {start_page}-{end_page}."}), 400

    native_pages = list(getattr(doc, "embedded_text_pages", []) or [])
    if native_pages:
        fast_results = []
        resolved_lang = (lang or "eng").strip().lower() or "eng"
        for page_no in range(start_page, end_page + 1):
            native_text = str(native_pages[page_no - 1] or "").strip() if page_no - 1 < len(native_pages) else ""
            if not native_text:
                continue
            fast_results.append(
                {
                    "page": page_no,
                    "text": native_text,
                    "confidence_score": 99.0,
                    "low_conf_threshold": int(low_conf_threshold),
                    "low_confidence_count": 0,
                    "low_confidence_words": [],
                    "lang": resolved_lang,
                    "detected_lang": resolved_lang,
                    "lang_scores": {resolved_lang: 99.0},
                    "preset": (preset or "").strip().lower(),
                    "psm": int(psm),
                    "source": "embedded-text",
                }
            )
        if fast_results:
            return jsonify({"results": fast_results, "start_page": start_page, "end_page": end_page})


    def _ocr_page_all(page_no: int):
        image = doc.pages[page_no - 1]
        is_image = str(getattr(doc, "file_type", "image") or "image").lower() == "image"
        resolved = _resolve_ocr_options(
            image=image, lang=lang, psm=psm, preset=preset,
            low_conf_threshold=low_conf_threshold,
            is_image=is_image,
        )
        details = _ocr_best_details(
            image=image, lang=resolved["lang"],
            psm=int(resolved["psm"]),
            low_conf_threshold=int(resolved["low_conf_threshold"]),
            is_region=False,
            is_image=is_image,
        )
        return {
            "page": page_no,
            "text": details["text"],
            "confidence_score": details["confidence_score"],
            "low_conf_threshold": details["low_conf_threshold"],
            "low_confidence_count": details["low_confidence_count"],
            "low_confidence_words": details.get("low_confidence_words", []),
            "lang": resolved["lang"],
            "detected_lang": resolved["detected_lang"],
            "lang_scores": resolved.get("lang_scores", {}),
            "preset": resolved["preset"],
            "psm": resolved["psm"],
        }

    all_page_range = list(range(start_page, end_page + 1))
    n_workers_all = max(1, min(4, len(all_page_range)))
    results_map_all: Dict[int, Any] = {}
    try:
        with ThreadPoolExecutor(max_workers=n_workers_all) as pool:
            futs = {pool.submit(_ocr_page_all, pn): pn for pn in all_page_range}
            for fut in as_completed(futs):
                results_map_all[futs[fut]] = fut.result()
    except Exception as err:
        return jsonify({"error": f"OCR failed: {err}"}), 500

    results = [results_map_all[pn] for pn in all_page_range if pn in results_map_all]

    return jsonify({"results": results, "start_page": start_page, "end_page": end_page})


@app.post("/api/chat")
@require_api_auth
def chat():
    payload = request.get_json(force=True)
    message = str(payload.get("message", "") or "").strip()
    doc_text = str(payload.get("text", "") or "").strip()
    include_context = bool(payload.get("include_context", False))
    mode = str(payload.get("mode", "all") or "all").strip().lower()
    extract_url = str(payload.get("extract_url", "") or "").strip()

    if not message:
        return jsonify({"error": "Message is required."}), 400

    query = message[:200].strip()
    if include_context and doc_text:
        doc_keywords = _build_duckduckgo_query(doc_text, max_terms=4)
        if doc_keywords:
            combined = f"{message} {doc_keywords}".strip()
            if len(combined) <= 250:
                query = combined

    if not extract_url:
        url_match = re.search(r"https?://\S+", message)
        if url_match:
            extract_url = url_match.group(0).rstrip(").,;!?\"'")

    use_multi = mode in {"all", "multi", "auto"}
    single_vertical_modes = {"text", "images", "videos", "news", "books"}

    sources: List[Dict[str, str]] = []
    verticals: Dict[str, Any] = {}

    if mode == "extract":
        if not extract_url:
            return jsonify({"error": "Use /extract <url>"}), 400
        if _DDGSClient is None:
            return jsonify({"error": "DDGS client unavailable."}), 500
        try:
            timeout_seconds = int(float(os.getenv("OCR_WEB_SEARCH_TIMEOUT", "12")))
            with _DDGSClient(timeout=timeout_seconds, verify=True) as ddgs:
                extracted = ddgs.extract(extract_url)
            if isinstance(extracted, dict):
                content = str(extracted.get("text") or extracted.get("content") or extracted.get("body") or "").strip()
                title = str(extracted.get("title") or extract_url).strip()
                snippet = content[:1200]
                sources = [{"title": title, "snippet": snippet, "url": extract_url}]
            elif isinstance(extracted, list) and extracted:
                item = extracted[0] if isinstance(extracted[0], dict) else {}
                content = str(item.get("text") or item.get("content") or item.get("body") or "").strip()
                title = str(item.get("title") or extract_url).strip()
                snippet = content[:1200]
                sources = [{"title": title, "snippet": snippet, "url": extract_url}]
            else:
                sources = [{"title": extract_url, "snippet": "No extractable content found.", "url": extract_url}]
        except Exception as err:
            return jsonify({"error": f"Extract failed: {err}"}), 500

        return jsonify({
            "query": query,
            "sources": sources,
            "mode": mode,
            "verticals": {"text": [], "images": [], "videos": [], "news": [], "books": []},
            "vertical_errors": {},
        })

    if mode in single_vertical_modes:
        try:
            rows = _search_ddgs_vertical(query=query, vertical=mode, max_results=8)
            if mode == "text":
                for row in rows:
                    url = str(row.get("href") or row.get("url") or "").strip()
                    title = str(row.get("title") or url).strip()
                    snippet = str(row.get("body") or row.get("snippet") or "").strip()
                    if url:
                        sources.append({"title": title, "snippet": snippet, "url": url})
            else:
                verticals[mode] = rows
        except Exception:
            pass

        return jsonify({
            "query": query,
            "sources": sources,
            "mode": mode,
            "verticals": {
                "text": verticals.get("text", []) if isinstance(verticals, dict) else [],
                "images": verticals.get("images", []) if isinstance(verticals, dict) else [],
                "videos": verticals.get("videos", []) if isinstance(verticals, dict) else [],
                "news": verticals.get("news", []) if isinstance(verticals, dict) else [],
                "books": verticals.get("books", []) if isinstance(verticals, dict) else [],
            },
            "vertical_errors": verticals.get("errors", {}) if isinstance(verticals, dict) else {},
        })

    try:
        sources = _search_ddgs_text_results(query=query, max_results=10)
    except Exception:
        pass

    if use_multi:
        try:
            verticals = _collect_ddgs_multi_search(query=query, max_results=8)
        except Exception:
            verticals = {}

    return jsonify({
        "query": query,
        "sources": sources,
        "mode": mode,
        "verticals": {
            "text": verticals.get("text", []) if isinstance(verticals, dict) else [],
            "images": verticals.get("images", []) if isinstance(verticals, dict) else [],
            "videos": verticals.get("videos", []) if isinstance(verticals, dict) else [],
            "news": verticals.get("news", []) if isinstance(verticals, dict) else [],
            "books": verticals.get("books", []) if isinstance(verticals, dict) else [],
        },
        "vertical_errors": verticals.get("errors", {}) if isinstance(verticals, dict) else {},
    })


@app.post("/api/upload_url")
@require_api_auth
def upload_from_url():
    _configure_tesseract()
    _cleanup_store()

    payload = request.get_json(force=True)
    url = str(payload.get("url", "") or "").strip()
    if not url:
        return jsonify({"error": "URL is required."}), 400

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return jsonify({"error": "Only http/https URLs are supported."}), 400

    timeout_seconds = float(os.getenv("OCR_URL_FETCH_TIMEOUT", "20"))
    max_bytes = int(os.getenv("OCR_URL_MAX_BYTES", "30000000"))

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "portable-pytesseract-ocr-studio/1.0",
            "Accept": "application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/*,image/*,*/*;q=0.8",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            content_type = str(resp.headers.get("Content-Type") or "").strip().lower()
            raw = resp.read(max_bytes + 1)
    except Exception as err:
        return jsonify({"error": f"URL fetch failed: {err}"}), 400

    if len(raw) > max_bytes:
        return jsonify({"error": f"Remote file is too large (>{max_bytes} bytes)."}), 400

    filename = _guess_filename_from_url(url, content_type)
    try:
        pages, file_type, embedded_text_pages = _parse_uploaded_content(filename, raw)
    except Exception as err:
        return jsonify({"error": f"Could not parse URL content: {err}"}), 400

    file_id = str(uuid.uuid4())
    FILES[file_id] = DocumentStore(
        pages=pages,
        filename=filename,
        file_type=file_type,
        embedded_text_pages=embedded_text_pages,
        original_bytes=raw if str(filename).lower().endswith(".docx") else b"",
    )

    return jsonify(
        {
            "file_id": file_id,
            "filename": filename,
            "file_type": file_type,
            "pages": len(pages),
            "url": url,
            "source": "url",
        }
    )


def _collect_web_sources(query: str, max_results: int = 12) -> Tuple[str, str, str, List[Dict[str, str]]]:
    sources: List[Dict[str, str]] = []
    topic = query
    summary = ""
    error = ""
    effective_query = _build_duckduckgo_query(query, max_terms=min(10, max_results + 3)) or query

    try:
        ddgs_sources = _search_ddgs_text_results(query=effective_query, max_results=max_results)
        if ddgs_sources:
            sources = ddgs_sources
            topic = str(ddgs_sources[0].get("title") or query).strip() or query
            summary = str(ddgs_sources[0].get("snippet") or "").strip()
    except Exception as err:
        error = str(err)

    try:
        result = _search_duckduckgo_instant_answer(query=effective_query, max_results=max_results)
        instant_topic = str(result.get("topic") or query)
        instant_summary = str(result.get("summary") or "")
        raw_sources = result.get("sources")
        if instant_topic and (not topic or topic == query):
            topic = instant_topic
        if instant_summary and (not summary or len(summary) < 50):
            summary = instant_summary

        if isinstance(raw_sources, list):
            seen = {str(s.get("url") or "").strip().lower() for s in sources}
            for item in raw_sources:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("url") or "").strip().lower()
                if not key or key in seen:
                    continue
                sources.append(item)
                seen.add(key)
                if len(sources) >= max_results:
                    break
    except Exception as err:
        if error:
            error = f"{error} | {err}"
        else:
            error = str(err)

    if len(sources) < 4:
        fallback = _search_duckduckgo_html_results(query=effective_query, max_results=max_results)
        if fallback:
            seen = {str(s.get("url") or "").strip() for s in sources}
            for item in fallback:
                key = str(item.get("url") or "").strip()
                if not key or key in seen:
                    continue
                sources.append(item)
                seen.add(key)
                if len(sources) >= max_results:
                    break

    if len(sources) < 4:
        lite = _search_duckduckgo_lite_results(query=effective_query, max_results=max_results)
        if lite:
            seen = {str(s.get("url") or "").strip() for s in sources}
            for item in lite:
                key = str(item.get("url") or "").strip()
                if not key or key in seen:
                    continue
                sources.append(item)
                seen.add(key)
                if len(sources) >= max_results:
                    break

    if len(sources) < 4:
        bing = _search_bing_html_results(query=effective_query, max_results=max_results)
        if bing:
            seen = {str(s.get("url") or "").strip() for s in sources}
            for item in bing:
                key = str(item.get("url") or "").strip()
                if not key or key in seen:
                    continue
                sources.append(item)
                seen.add(key)
                if len(sources) >= max_results:
                    break

    if len(sources) < 4:
        proxy = _search_via_jina_ai_proxy(query=effective_query, max_results=max_results)
        if proxy:
            seen = {str(s.get("url") or "").strip() for s in sources}
            for item in proxy:
                key = str(item.get("url") or "").strip()
                if not key or key in seen:
                    continue
                sources.append(item)
                seen.add(key)
                if len(sources) >= max_results:
                    break

    if len(sources) < 4:
        vertical_rows = _search_ddgs_vertical(query=effective_query, vertical="text", max_results=max_results)
        if vertical_rows:
            seen = {str(s.get("url") or "").strip().lower() for s in sources}
            for row in vertical_rows:
                if not isinstance(row, dict):
                    continue
                url = str(row.get("href") or row.get("url") or "").strip()
                title = str(row.get("title") or url).strip()
                snippet = str(row.get("body") or row.get("snippet") or "").strip()
                key = url.lower()
                if not url or not title or key in seen:
                    continue
                if not _is_valid_result_url(url, title):
                    continue
                sources.append({"title": title, "snippet": snippet, "url": url})
                seen.add(key)
                if len(sources) >= max_results:
                    break

    sources = _rerank_search_results(sources[:max_results], query_text=query)

    if not sources:
        shortcuts = _build_search_shortcuts(effective_query)
        seen = {str(s.get("url") or "").strip().lower() for s in sources}
        for item in shortcuts:
            key = str(item.get("url") or "").strip().lower()
            if not key or key in seen:
                continue
            sources.append(item)
            seen.add(key)
            if len(sources) >= max_results:
                break

    return topic, summary, error, sources[:max_results]


def _collect_ddgs_multi_search(query: str, max_results: int = 6) -> Dict[str, Any]:
    requested = max(1, min(int(max_results or 6), 12))
    payload: Dict[str, Any] = {
        "text": [],
        "images": [],
        "videos": [],
        "news": [],
        "books": [],
        "errors": {},
    }

    for vertical in ["text", "images", "videos", "news", "books"]:
        try:
            rows = _search_ddgs_vertical(query=query, vertical=vertical, max_results=requested)
            payload[vertical] = rows
        except Exception as err:
            payload[vertical] = []
            payload["errors"][vertical] = str(err)

    return payload


@app.get("/api/web_links")
@require_api_auth
def web_links():
    query = _clean_text_for_query(request.args.get("q", ""))
    if not query:
        return jsonify({"error": "Query is required."}), 400

    requested = int(request.args.get("max_results", 6) or 6)
    max_results = max(1, min(12, requested))
    topic, summary, error, sources = _collect_web_sources(query=query, max_results=max_results)
    multi = _collect_ddgs_multi_search(query=query, max_results=max_results)
    merged_sources = list(sources)
    seen_urls = {str(item.get("url") or "").strip().lower() for item in merged_sources if isinstance(item, dict)}
    for row in multi.get("text", []):
        if not isinstance(row, dict):
            continue
        url = str(row.get("href") or row.get("url") or "").strip()
        title = str(row.get("title") or url).strip()
        snippet = str(row.get("body") or row.get("snippet") or "").strip()
        key = url.lower()
        if not url or not title or key in seen_urls:
            continue
        if not _is_valid_result_url(url, title):
            continue
        merged_sources.append({"title": title, "snippet": snippet, "url": url})
        seen_urls.add(key)

    sources = _rerank_search_results(merged_sources, query_text=query)[:max_results]
    return jsonify(
        {
            "query": query,
            "topic": topic,
            "summary": summary,
            "error": error,
            "sources": sources,
            "verticals": {
                "text": multi.get("text", []),
                "images": multi.get("images", []),
                "videos": multi.get("videos", []),
                "news": multi.get("news", []),
                "books": multi.get("books", []),
            },
            "vertical_errors": multi.get("errors", {}),
        }
    )


@app.get("/api/ddgs_search")
@require_api_auth
def ddgs_search():
    query = _clean_text_for_query(request.args.get("q", ""))
    if not query:
        return jsonify({"error": "Query is required."}), 400

    requested = int(request.args.get("max_results", 6) or 6)
    max_results = max(1, min(12, requested))
    vertical = (request.args.get("vertical", "all") or "all").strip().lower()

    if vertical in {"all", "*"}:
        multi = _collect_ddgs_multi_search(query=query, max_results=max_results)
        return jsonify(
            {
                "query": query,
                "vertical": "all",
                "max_results": max_results,
                "results": {
                    "text": multi.get("text", []),
                    "images": multi.get("images", []),
                    "videos": multi.get("videos", []),
                    "news": multi.get("news", []),
                    "books": multi.get("books", []),
                },
                "errors": multi.get("errors", {}),
            }
        )

    if vertical not in {"text", "images", "videos", "news", "books"}:
        return jsonify({"error": "vertical must be one of: all, text, images, videos, news, books"}), 400

    rows = _search_ddgs_vertical(query=query, vertical=vertical, max_results=max_results)
    return jsonify({"query": query, "vertical": vertical, "max_results": max_results, "results": rows})


@app.post("/api/extract_table")
@require_api_auth
def extract_table():
    payload = request.get_json(force=True)
    file_id = payload.get("file_id", "")
    page_no = int(payload.get("page", 1))
    engine = (payload.get("engine", "tesseract") or "tesseract").strip().lower()
    lang = payload.get("lang", "eng")
    psm = int(payload.get("psm", 6))
    preset = payload.get("preset", "")
    output_format = (payload.get("format", "json") or "json").strip().lower()
    low_conf_threshold = int(payload.get("low_conf_threshold", 55))
    region = payload.get("region")

    doc = FILES.get(file_id)
    if not doc:
        return jsonify({"error": "File session expired. Upload again."}), 404

    if page_no < 1 or page_no > len(doc.pages):
        return jsonify({"error": "Invalid page."}), 400

    image = doc.pages[page_no - 1]
    try:
        image = _crop_region(image, region)
    except ValueError as err:
        return jsonify({"error": str(err)}), 400

    normalized_engine = engine
    if normalized_engine in {"ocr-geometry", "geometry", "tesseract-geometry"}:
        normalized_engine = "tesseract"
    if normalized_engine in {"paddle", "paddle_table", "ppstructure"}:
        normalized_engine = "paddle_table"

    resolved: Dict[str, Any] = {
        "lang": (lang or "eng").strip().lower() or "eng",
        "detected_lang": "",
        "lang_scores": {},
        "preset": (preset or "").strip().lower(),
        "psm": int(psm),
        "low_conf_threshold": int(low_conf_threshold),
    }
    details: Dict[str, Any] = {
        "confidence_score": 0.0,
        "low_conf_threshold": int(low_conf_threshold),
        "low_confidence_count": 0,
        "low_confidence_words": [],
    }
    requested_engine = normalized_engine
    engine_fallback_reason = ""

    def _run_tesseract_table() -> Dict[str, Any]:
        nonlocal resolved, details
        resolved = _resolve_ocr_options(
            image=image,
            lang=lang,
            psm=psm,
            preset=preset,
            low_conf_threshold=low_conf_threshold,
        )
        details = _ocr_with_details(
            image=image,
            lang=resolved["lang"],
            psm=int(resolved["psm"]),
            low_conf_threshold=int(resolved["low_conf_threshold"]),
        )
        return _extract_table_from_words(details["words"], image=image)

    try:
        if normalized_engine == "paddle_table":
            try:
                table = _extract_table_with_paddle(image)
            except Exception as paddle_err:
                engine_fallback_reason = str(paddle_err)
                table = _run_tesseract_table()
                table["method"] = f"{table.get('method', 'ocr-geometry')}+paddle-fallback"
                normalized_engine = "tesseract"
            rows = table.get("rows", [])
        elif normalized_engine == "tesseract":
            table = _run_tesseract_table()
            rows = table.get("rows", [])
        else:
            return jsonify({"error": "Unsupported table engine. Use 'tesseract' or 'paddle_table'."}), 400
    except Exception as err:
        return jsonify({"error": f"Table extraction failed: {err}"}), 500

    has_strong_table = _is_table_structure_strong(table)
    if not has_strong_table:
        table = {
            "rows": [],
            "columns": 0,
            "cells": [],
            "method": f"{table.get('method', 'ocr-geometry')}-no-table",
            "html_table": "",
        }

    rows = table.get("rows", [])

    if output_format in {"csv", "xlsx", "html"} and not has_strong_table:
        return jsonify({
            "error": "No table structure detected on this page. Try Region Select around the table area.",
            "table_engine": normalized_engine,
            "table_engine_requested": requested_engine,
            "table_engine_fallback_reason": engine_fallback_reason,
        }), 422

    safe_name = _safe_pdf_name(doc.filename)
    if output_format == "csv":
        csv_text = _rows_to_csv_text(rows)
        buf = io.BytesIO(csv_text.encode("utf-8"))
        buf.seek(0)
        return send_file(
            buf,
            mimetype="text/csv",
            as_attachment=True,
            download_name=f"{safe_name}_page_{page_no}_table.csv",
        )

    if output_format == "xlsx":
        xlsx_bytes = _rows_to_xlsx_bytes(rows)
        buf = io.BytesIO(xlsx_bytes)
        buf.seek(0)
        return send_file(
            buf,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=f"{safe_name}_page_{page_no}_table.xlsx",
        )

    if output_format == "html":
        html_table = (table.get("html_table") or "").strip()
        if not html_table:
            html_table = _rows_to_html_table(rows)
        html_doc = (
            "<!doctype html><html><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{html.escape(safe_name)} page {page_no} table</title>"
            "<style>"
            "body{font-family:Arial,Helvetica,sans-serif;margin:16px;}"
            "table{border-collapse:collapse;border:1px solid #333;min-width:320px;}"
            "th,td{border:1px solid #333;padding:6px 8px;vertical-align:top;text-align:left;}"
            "thead th{background:#f3f4f6;}"
            "</style>"
            "</head><body>"
            f"{html_table}"
            "</body></html>"
        )
        buf = io.BytesIO(html_doc.encode("utf-8"))
        buf.seek(0)
        return send_file(
            buf,
            mimetype="text/html",
            as_attachment=True,
            download_name=f"{safe_name}_page_{page_no}_table.html",
        )

    return jsonify(
        {
            "file_id": file_id,
            "page": page_no,
            "rows": rows,
            "columns": table.get("columns", 0),
            "cells": table.get("cells", []),
            "table_method": table.get("method", "ocr-geometry"),
            "table_engine": normalized_engine,
            "table_engine_requested": requested_engine,
            "table_engine_fallback_reason": engine_fallback_reason,
            "html_table": table.get("html_table", ""),
            "grid_lines": table.get("grid_lines", {}),
            "confidence_score": details["confidence_score"],
            "low_conf_threshold": details["low_conf_threshold"],
            "low_confidence_count": details["low_confidence_count"],
            "low_confidence_words": details["low_confidence_words"],
            "lang": resolved["lang"],
            "detected_lang": resolved["detected_lang"],
            "lang_scores": resolved["lang_scores"],
            "preset": resolved["preset"],
            "psm": resolved["psm"],
        }
    )


@app.get("/api/download_ocr_pdf/<file_id>")
@require_api_auth
def download_ocr_pdf(file_id: str):
    doc = FILES.get(file_id)
    if not doc:
        return jsonify({"error": "File session expired. Upload again."}), 404

    lang = request.args.get("lang", "eng")
    try:
        psm = int(request.args.get("psm", "3"))
    except ValueError:
        psm = 3

    _configure_tesseract()

    try:
        pdf_bytes = _build_searchable_pdf_bytes(doc.pages, lang=lang, psm=psm)
        buf = io.BytesIO()
        buf.write(pdf_bytes)
        buf.seek(0)
    except Exception as err:
        return jsonify({"error": f"Searchable PDF generation failed: {err}"}), 500

    safe_name = doc.filename.rsplit(".", 1)[0] if "." in doc.filename else doc.filename
    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{safe_name}_searchable_ocr.pdf",
    )


@app.post("/api/download_ocr_pdf_start")
@require_api_auth
def download_ocr_pdf_start():
    payload = request.get_json(force=True)
    file_id = payload.get("file_id", "")
    lang = payload.get("lang", "eng")
    try:
        psm = int(payload.get("psm", 3))
    except Exception:
        psm = 3

    _cleanup_pdf_jobs()

    doc = FILES.get(file_id)
    if not doc:
        return jsonify({"error": "File session expired. Upload again."}), 404

    _configure_tesseract()
    job_id = str(uuid.uuid4())
    with PDF_JOBS_LOCK:
        PDF_JOBS[job_id] = OCRPdfJob(
            file_id=file_id,
            filename=doc.filename,
            total_pages=len(doc.pages),
        )

    worker = threading.Thread(target=_run_ocr_pdf_job, args=(job_id, lang, psm), daemon=True)
    worker.start()

    return jsonify({"job_id": job_id, "status": "queued", "total_pages": len(doc.pages)})


@app.get("/api/download_ocr_pdf_status/<job_id>")
@require_api_auth
def download_ocr_pdf_status(job_id: str):
    _cleanup_pdf_jobs()
    with PDF_JOBS_LOCK:
        job = PDF_JOBS.get(job_id)
        if not job:
            return jsonify({"error": "Job not found or expired."}), 404

        return jsonify(
            {
                "job_id": job_id,
                "status": job.status,
                "progress": job.progress,
                "done_pages": job.done_pages,
                "total_pages": job.total_pages,
                "error": job.error,
            }
        )


@app.get("/api/download_ocr_pdf_result/<job_id>")
@require_api_auth
def download_ocr_pdf_result(job_id: str):
    _cleanup_pdf_jobs()
    with PDF_JOBS_LOCK:
        job = PDF_JOBS.get(job_id)
        if not job:
            return jsonify({"error": "Job not found or expired."}), 404

        if job.status == "failed":
            return jsonify({"error": job.error or "PDF generation failed."}), 500
        if job.status != "done" or not job.output_path:
            return jsonify({"error": "PDF is still being generated."}), 409

        output_path = job.output_path
        safe_name = job.filename.rsplit(".", 1)[0] if "." in job.filename else job.filename

    return send_file(
        output_path,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{safe_name}_searchable_ocr.pdf",
    )


@app.post("/api/download_ocr_pdf_batch_start")
@require_api_auth
def download_ocr_pdf_batch_start():
    payload = request.get_json(force=True)
    file_ids = payload.get("file_ids") or []
    lang = payload.get("lang", "eng")
    try:
        psm = int(payload.get("psm", 3))
    except Exception:
        psm = 3

    if not isinstance(file_ids, list) or not file_ids:
        return jsonify({"error": "file_ids must be a non-empty array."}), 400

    _cleanup_pdf_jobs()
    _configure_tesseract()

    existing_ids = [file_id for file_id in file_ids if file_id in FILES]
    if not existing_ids:
        return jsonify({"error": "No valid active file sessions found."}), 404

    job_id = str(uuid.uuid4())
    with PDF_JOBS_LOCK:
        BATCH_PDF_JOBS[job_id] = OCRBatchPdfJob(
            file_ids=existing_ids,
            total_docs=len(existing_ids),
            total_pages=sum(len(FILES[file_id].pages) for file_id in existing_ids),
        )

    worker = threading.Thread(target=_run_batch_ocr_pdf_job, args=(job_id, lang, psm), daemon=True)
    worker.start()

    return jsonify(
        {
            "job_id": job_id,
            "status": "queued",
            "total_docs": len(existing_ids),
            "total_pages": sum(len(FILES[file_id].pages) for file_id in existing_ids),
        }
    )


@app.get("/api/download_ocr_pdf_batch_status/<job_id>")
@require_api_auth
def download_ocr_pdf_batch_status(job_id: str):
    _cleanup_pdf_jobs()
    with PDF_JOBS_LOCK:
        job = BATCH_PDF_JOBS.get(job_id)
        if not job:
            return jsonify({"error": "Job not found or expired."}), 404

        return jsonify(
            {
                "job_id": job_id,
                "status": job.status,
                "progress": job.progress,
                "done_docs": job.done_docs,
                "total_docs": job.total_docs,
                "done_pages": job.done_pages,
                "total_pages": job.total_pages,
                "error": job.error,
            }
        )


@app.get("/api/download_ocr_pdf_batch_result/<job_id>")
@require_api_auth
def download_ocr_pdf_batch_result(job_id: str):
    _cleanup_pdf_jobs()
    with PDF_JOBS_LOCK:
        job = BATCH_PDF_JOBS.get(job_id)
        if not job:
            return jsonify({"error": "Job not found or expired."}), 404

        if job.status == "failed":
            return jsonify({"error": job.error or "Batch PDF generation failed."}), 500
        if job.status != "done" or not job.output_path:
            return jsonify({"error": "Batch PDF archive is still being generated."}), 409

        output_path = job.output_path

    return send_file(
        output_path,
        mimetype="application/zip",
        as_attachment=True,
        download_name="searchable_ocr_batch.zip",
    )


@app.get("/api/quality/<file_id>/<int:page_no>")
@require_api_auth
def quality_page(file_id: str, page_no: int):
    doc = FILES.get(file_id)
    if not doc:
        return jsonify({"error": "File session expired. Upload again."}), 404

    if page_no < 1 or page_no > len(doc.pages):
        return jsonify({"error": "Invalid page."}), 400

    image = doc.pages[page_no - 1]
    metrics = _page_quality_metrics(image)
    metrics.update(
        {
            "page": page_no,
            "width": image.width,
            "height": image.height,
        }
    )
    return jsonify(metrics)


@app.get("/api/quality_summary/<file_id>")
@require_api_auth
def quality_summary(file_id: str):
    doc = FILES.get(file_id)
    if not doc:
        return jsonify({"error": "File session expired. Upload again."}), 404

    per_page = []
    for idx, image in enumerate(doc.pages, start=1):
        metrics = _page_quality_metrics(image)
        metrics.update({"page": idx, "width": image.width, "height": image.height})
        per_page.append(metrics)

    total = len(per_page)
    if total == 0:
        return jsonify({"error": "No pages available."}), 400

    avg_overall = round(sum(p["overall_score"] for p in per_page) / total, 2)
    avg_sharp = round(sum(p["sharpness"] for p in per_page) / total, 2)
    avg_contrast = round(sum(p["contrast"] for p in per_page) / total, 2)
    avg_brightness = round(sum(p["brightness"] for p in per_page) / total, 2)

    poor_pages = [p["page"] for p in per_page if p["quality_band"] == "poor"]
    fair_pages = [p["page"] for p in per_page if p["quality_band"] == "fair"]
    good_pages = [p["page"] for p in per_page if p["quality_band"] == "good"]

    ranked = sorted(per_page, key=lambda item: item["overall_score"])
    flagged = [
        {
            "page": item["page"],
            "overall_score": item["overall_score"],
            "quality_band": item["quality_band"],
        }
        for item in ranked[: min(8, len(ranked))]
        if item["quality_band"] != "good"
    ]

    return jsonify(
        {
            "file_id": file_id,
            "filename": doc.filename,
            "pages": total,
            "document_overall_score": avg_overall,
            "document_quality_band": _quality_band(avg_overall),
            "avg_sharpness": avg_sharp,
            "avg_contrast": avg_contrast,
            "avg_brightness": avg_brightness,
            "counts": {
                "good": len(good_pages),
                "fair": len(fair_pages),
                "poor": len(poor_pages),
            },
            "flagged_pages": flagged,
            "per_page": per_page,
        }
    )


@app.post("/api/clear_session")
@require_api_auth
def clear_session():
    payload = request.get_json(force=True)
    file_id = payload.get("file_id", "")
    if not file_id:
        return jsonify({"error": "file_id is required."}), 400

    existed = FILES.pop(file_id, None) is not None
    return jsonify({"cleared": existed})


@app.get("/api/health")
def health():
    auth_enabled = bool(_api_password())
    return jsonify({"status": "ok", "auth_enabled": auth_enabled})


@app.get("/api/download_installer")
def download_installer():
    """Return a full portable setup ZIP for running on other Windows computers."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    bundle_root = "portable-ocr-studio"

    install_bat = r"""@echo off
setlocal EnableDelayedExpansion
title Portable OCR Studio - Installer
color 0A
echo =====================================================
echo   Portable OCR Studio  -  Full Setup Installer
echo =====================================================
echo.

set PYTHON_EXE=

py -3 --version >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)"') do set PYTHON_EXE=%%P
)

if "!PYTHON_EXE!"=="" (
    for /f "delims=" %%P in ('where python 2^>nul') do (
        echo %%P | findstr /i "WindowsApps" >nul
        if errorlevel 1 (
            if "!PYTHON_EXE!"=="" set PYTHON_EXE=%%P
        )
    )
)

if "!PYTHON_EXE!"=="" (
    for %%V in (313 312 311 310) do (
        if "!PYTHON_EXE!"=="" if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" set PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe
    )
)

if "!PYTHON_EXE!"=="" (
    echo.
    echo [ERROR] Python 3.10+ not found.
    echo   Install from: https://python.org/downloads
    echo   Enable: Add Python to PATH
    echo.
    pause & exit /b 1
)

echo [OK] Python found: !PYTHON_EXE!
echo !PYTHON_EXE!> .python_path.txt

echo.
echo Creating virtual environment...
"!PYTHON_EXE!" -m venv .venv
if errorlevel 1 (
    echo [ERROR] Could not create virtual environment.
    pause & exit /b 1
)

echo.
echo Installing dependencies...
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\pip.exe install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install requirements.
    pause & exit /b 1
)

if exist "portable_tesseract\Tesseract-OCR\tesseract.exe" (
    echo %cd%\portable_tesseract\Tesseract-OCR\tesseract.exe> .tesseract_path.txt
    echo [OK] Bundled Tesseract detected and configured.
) else (
    echo [WARN] Bundled Tesseract not found in package.
)

echo.
echo Trying optional desktop-window support...
.venv\Scripts\pip.exe install pywebview >nul 2>&1

echo.
echo Creating desktop shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try {$ws=New-Object -ComObject WScript.Shell; $s=$ws.CreateShortcut((Join-Path $env:USERPROFILE 'Desktop\\Portable OCR Studio.lnk')); $s.TargetPath=(Join-Path '%cd%' 'launch.bat'); $s.WorkingDirectory='%cd%'; $icon=(Join-Path '%cd%' 'assets\\app_icon.ico'); if (Test-Path $icon) {$s.IconLocation=$icon}; $s.Description='Launch Portable OCR Studio'; $s.Save(); exit 0} catch {exit 1}" >nul 2>&1
if errorlevel 1 (
    echo [WARN] Could not create desktop shortcut automatically.
) else (
    echo [OK] Desktop shortcut created.
)

echo.
echo =====================================================
echo   Installation complete!
echo   Run launch.bat to start Portable OCR Studio.
echo =====================================================
echo.
pause
endlocal
"""

    launch_bat = r"""@echo off
setlocal EnableDelayedExpansion
title Portable OCR Studio
color 0B

if not exist .venv\Scripts\python.exe (
    echo [ERROR] Virtual environment missing.
    echo Please run install.bat first.
    pause & exit /b 1
)

if exist .tesseract_path.txt (
    set /p TESSERACT_CMD=<.tesseract_path.txt
)

if "!TESSERACT_CMD!"=="" if exist "%cd%\portable_tesseract\Tesseract-OCR\tesseract.exe" (
    set "TESSERACT_CMD=%cd%\portable_tesseract\Tesseract-OCR\tesseract.exe"
)
if "!TESSDATA_PREFIX!"=="" if exist "%cd%\portable_tesseract\Tesseract-OCR\tessdata" (
    set "TESSDATA_PREFIX=%cd%\portable_tesseract\Tesseract-OCR\tessdata"
)

echo =====================================================
echo   Portable OCR Studio - Starting
echo =====================================================
echo.

.venv\Scripts\python.exe -c "import webview" >nul 2>&1
if !errorlevel! EQU 0 (
    .venv\Scripts\python.exe desktop_app.py
    goto :done
)

start "" "http://127.0.0.1:7860"
.venv\Scripts\python.exe app.py

:done
endlocal
"""

    readme_txt = (
        "Portable OCR Studio - Full Setup Bundle\n"
        "========================================\n\n"
        "This package includes:\n"
        "  - App source + launcher files\n"
        "  - Bundled portable Tesseract OCR\n"
        "  - Windows install/start BAT files\n\n"
        "Install on another computer:\n"
        "  1) Extract the ZIP\n"
        "  2) Double-click install.bat\n"
        "  3) Double-click launch.bat\n\n"
        "Notes:\n"
        "  - Python 3.10+ is required (https://python.org/downloads)\n"
        "  - No separate Tesseract install is required when bundled files are present\n"
        "  - If desktop window mode is unavailable, app opens in browser mode\n"
    )

    def _zip_add_file(zf: zipfile.ZipFile, rel_path: str) -> None:
        src = os.path.join(base_dir, rel_path)
        if os.path.exists(src):
            normalized = rel_path.replace("\\", "/")
            zf.write(src, f"{bundle_root}/{normalized}")

    def _zip_add_dir(zf: zipfile.ZipFile, rel_dir: str) -> None:
        src_dir = os.path.join(base_dir, rel_dir)
        if not os.path.isdir(src_dir):
            return
        for root, _, files in os.walk(src_dir):
            for name in files:
                src = os.path.join(root, name)
                rel = os.path.relpath(src, base_dir).replace("\\", "/")
                zf.write(src, f"{bundle_root}/{rel}")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel_file in (
            "app.py",
            "index.html",
            "requirements.txt",
            "requirements-desktop.txt",
            "desktop_app.py",
            "launch_app.bat",
            "create_desktop_shortcut.bat",
            "build_desktop.ps1",
            "build_desktop.bat",
            "tutorial_quickstart.gif",
        ):
            _zip_add_file(zf, rel_file)

        _zip_add_dir(zf, "portable_tesseract")
        _zip_add_dir(zf, "assets")

        zf.writestr(f"{bundle_root}/install.bat", install_bat)
        zf.writestr(f"{bundle_root}/launch.bat", launch_bat)
        zf.writestr(f"{bundle_root}/README.txt", readme_txt)

    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name="portable-ocr-studio-full-setup.zip",
        mimetype="application/zip",
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7860, debug=False)

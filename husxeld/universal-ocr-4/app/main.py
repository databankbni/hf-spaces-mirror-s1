from __future__ import annotations

import asyncio
import hashlib
import html
import json
import os
import re
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, BinaryIO, TypedDict

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from PIL import Image, ImageOps, ImageSequence
from playwright.async_api import async_playwright
from pypdf import PdfReader, PdfWriter

from .ai_service import AiService, default_model_name, default_provider_name, load_env_files

load_env_files(override=False)

# ==============================================================================
# Configuration
# ==============================================================================

APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
STATIC_DIR = APP_DIR / "static"

WEBSITE = os.getenv("OLMOCR_WEBSITE", "https://playground.allenai.org/model/olmocr-2-7b-1025")
DEFAULT_ENGINE = os.getenv("OCR_DEFAULT_ENGINE", "auto").strip().lower()
DEFAULT_PAGES_PER_CHUNK = int(os.getenv("OCR_PAGES_PER_CHUNK", "6"))
DEFAULT_CONCURRENCY = int(os.getenv("OCR_CHUNK_CONCURRENCY", "1"))
MAX_RETRIES = int(os.getenv("OCR_MAX_RETRIES", "3"))
CHUNK_TIMEOUT_SECONDS = int(os.getenv("OCR_CHUNK_TIMEOUT_SECONDS", "600"))
PDF_TEXT_MIN_CHARS = int(os.getenv("OCR_PDF_TEXT_MIN_CHARS", "20"))
ALLOW_SERVER_PATH = os.getenv("OCR_ALLOW_SERVER_PATH", "1") != "0"
KEEP_UPLOADS = os.getenv("OCR_KEEP_UPLOADS", "0") == "1"
AI_CONTEXT_MAX_CHARS = int(os.getenv("OCR_AI_CONTEXT_MAX_CHARS", "180000"))
ENABLE_HF_STORAGE = os.getenv("OCR_HF_STORAGE", "1" if os.getenv("SPACE_ID") else "0") != "0"
ENABLE_HF_STORAGE_PULL = os.getenv("OCR_HF_STORAGE_PULL", "1") != "0"
HF_STORAGE_PRIVATE = os.getenv("OCR_HF_STORAGE_PRIVATE", "1") != "0"
HF_USERNAME = os.getenv("HF_USERNAME") or os.getenv("HF_USER")
HF_STORAGE_REPO_ID = os.getenv("HF_STORAGE_REPO_ID") or (f"{HF_USERNAME}/ocr-mcq-automation-storage" if HF_USERNAME else None)


def default_data_dir() -> Path:
    # Hugging Face persistent Space storage is mounted at /data when enabled.
    # The Dockerfile creates this path too, so it also works as ephemeral storage on free Spaces.
    if os.getenv("SPACE_ID") or Path("/data").exists():
        return Path("/data/ocr-automation")
    return PROJECT_DIR / "outputs" / "api"


DATA_DIR = Path(os.getenv("OCR_DATA_DIR", str(default_data_dir()))).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
SPLIT_DIR = DATA_DIR / "splits"
RESULTS_DIR = DATA_DIR / "jobs"
for directory in (DATA_DIR, UPLOAD_DIR, SPLIT_DIR, RESULTS_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SUPPORTED_ENGINES = {"auto", "olmocr-web", "pdf-text"}
SUPPORTED_IMAGE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
    ".gif",
}
SUPPORTED_SUFFIXES = {".pdf", *SUPPORTED_IMAGE_SUFFIXES}

# ==============================================================================
# FastAPI app
# ==============================================================================

app = FastAPI(
    title="OCR Automation Studio",
    description=(
        "Hugging Face ready FastAPI + UI wrapper for the olmOCR web demo. "
        "Supports local browser upload, absolute server paths, chunked PDFs, and downloads."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# In-memory job state. Results are also written to disk under RESULTS_DIR.
jobs: dict[str, dict[str, Any]] = {}
tasks: dict[str, asyncio.Task[Any]] = {}

# ==============================================================================
# Models and helpers
# ==============================================================================


class ExtractedPage(TypedDict):
    page: int
    content: str


class RawExtractedPage(TypedDict):
    page: int
    raw_response: dict[str, Any]


class UploadPathRequest(BaseModel):
    path: str = Field(..., description="Absolute path inside the FastAPI server/container")
    engine: str | None = Field(
        DEFAULT_ENGINE,
        description="auto, olmocr-web, or pdf-text. auto uses embedded PDF text when present, else olmOCR web.",
    )
    pages_per_chunk: int | None = Field(None, ge=1, le=10)
    concurrency: int | None = Field(None, ge=1, le=4)
    include_raw: bool = True


class McqGenerateRequest(BaseModel):
    job_id: str = Field(..., description="Completed OCR job id")
    count: int = Field(30, ge=1, le=100)
    language: str = Field("hinglish", description="english, hinglish, or hindi")
    provider: str | None = Field(None, description="AI provider override")
    model: str | None = Field(None, description="AI model override")
    temperature: float = Field(0.2, ge=0, le=2)
    subject: str | None = Field(None, max_length=120)
    exam: str | None = Field("competitive exams", max_length=160)
    difficulty_mix: str | None = Field("balanced", description="balanced, easy, medium, hard")


class JobOptions(TypedDict):
    engine: str
    pages_per_chunk: int
    concurrency: int
    include_raw: bool


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_filename(filename: str | None, fallback: str = "upload") -> str:
    name = Path(filename or fallback).name.strip() or fallback
    return re.sub(r"[^A-Za-z0-9._()\-\u0900-\u097F ]+", "_", name)[:180]


def normalize_engine(engine: str | None) -> str:
    value = (engine or DEFAULT_ENGINE or "auto").strip().lower()
    if value not in SUPPORTED_ENGINES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported engine '{engine}'. Use one of: {', '.join(sorted(SUPPORTED_ENGINES))}",
        )
    return value


def normalize_options(
    engine: str | None,
    pages_per_chunk: int | None,
    concurrency: int | None,
    include_raw: bool,
) -> JobOptions:
    ppc = pages_per_chunk or DEFAULT_PAGES_PER_CHUNK
    conc = concurrency or DEFAULT_CONCURRENCY
    if ppc < 1 or ppc > 10:
        raise HTTPException(status_code=400, detail="pages_per_chunk must be between 1 and 10")
    if conc < 1 or conc > 4:
        raise HTTPException(status_code=400, detail="concurrency must be between 1 and 4")
    return {
        "engine": normalize_engine(engine),
        "pages_per_chunk": ppc,
        "concurrency": conc,
        "include_raw": include_raw,
    }


def accepted_payload(job_id: str) -> dict[str, Any]:
    return {
        "status": "accepted",
        "job_id": job_id,
        "status_url": f"/status/{job_id}",
        "result_url": f"/result/{job_id}",
        "download_json_url": f"/download/{job_id}/json",
        "download_text_url": f"/download/{job_id}/text",
        "download_content_url": f"/download/{job_id}/content",
    }


def create_job(job_id: str, original_filename: str, input_kind: str, options: JobOptions) -> None:
    now = utc_now()
    jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "created_at": now,
        "updated_at": now,
        "source": {"file_name": original_filename, "input_kind": input_kind},
        "options": options,
        "progress": {
            "stage": "queued",
            "message": "Queued",
            "percent": 0,
            "processed_pages": 0,
            "total_pages": None,
            "processed_chunks": 0,
            "total_chunks": None,
        },
        "result": None,
        "error": None,
        "warnings": [],
        "files": {},
    }


def update_job(job_id: str, **updates: Any) -> None:
    if job_id in jobs:
        jobs[job_id].update(updates)
        jobs[job_id]["updated_at"] = utc_now()


def update_progress(job_id: str, message: str, **progress_updates: Any) -> None:
    if job_id not in jobs:
        return
    progress = dict(jobs[job_id].get("progress") or {})
    progress.update(progress_updates)
    progress["message"] = message
    jobs[job_id]["progress"] = progress
    jobs[job_id]["updated_at"] = utc_now()


def add_warning(job_id: str, warning: str) -> None:
    if job_id in jobs:
        jobs[job_id].setdefault("warnings", []).append(warning)
        jobs[job_id]["updated_at"] = utc_now()


# ==============================================================================
# Input normalization
# ==============================================================================


def normalize_image_frame(frame: Image.Image) -> Image.Image:
    transformed = ImageOps.exif_transpose(frame)
    image = transformed if transformed is not None else frame.copy()

    # Preserve transparent images on a white background instead of black.
    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background

    if image.mode != "RGB":
        return image.convert("RGB")
    return image.copy()


def image_to_pdf(source: str | Path | BinaryIO, output_path: Path) -> None:
    with Image.open(source) as image:
        frames = [normalize_image_frame(frame) for frame in ImageSequence.Iterator(image)]

    if not frames:
        raise HTTPException(status_code=400, detail="Unable to read image file")

    first, *rest = frames
    first.save(output_path, format="PDF", save_all=bool(rest), append_images=rest)


def prepare_upload_as_pdf(upload_file: UploadFile, job_id: str) -> tuple[Path, str, str]:
    original_filename = safe_filename(upload_file.filename, "upload")
    suffix = Path(original_filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail="Supported formats: PDF, PNG, JPG, JPEG, WEBP, BMP, TIFF, GIF",
        )

    job_upload_dir = UPLOAD_DIR / job_id
    job_upload_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = job_upload_dir / "input.pdf"
    original_path = job_upload_dir / f"original_{original_filename}"

    upload_file.file.seek(0)
    with open(original_path, "wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)

    if suffix == ".pdf":
        shutil.copyfile(str(original_path), str(pdf_path))
        return pdf_path, original_filename, "upload-pdf"

    try:
        image_to_pdf(original_path, pdf_path)
    except OSError as exc:
        raise HTTPException(status_code=400, detail="Invalid image file") from exc
    return pdf_path, original_filename, "upload-image"


def prepare_server_path_as_pdf(input_path: Path, job_id: str) -> tuple[Path, str, str]:
    if not ALLOW_SERVER_PATH:
        raise HTTPException(status_code=403, detail="Server path input is disabled")
    if not input_path.is_absolute():
        raise HTTPException(status_code=400, detail="Path must be absolute")
    if not input_path.exists() or not input_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    suffix = input_path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail="Supported formats: PDF, PNG, JPG, JPEG, WEBP, BMP, TIFF, GIF",
        )

    job_upload_dir = UPLOAD_DIR / job_id
    job_upload_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = job_upload_dir / "input.pdf"
    original_filename = safe_filename(input_path.name, "input")
    original_path = job_upload_dir / f"original_{original_filename}"
    shutil.copyfile(str(input_path), str(original_path))

    if suffix == ".pdf":
        shutil.copyfile(str(original_path), str(pdf_path))
        return pdf_path, original_filename, "server-path-pdf"

    try:
        image_to_pdf(original_path, pdf_path)
    except OSError as exc:
        raise HTTPException(status_code=400, detail="Invalid image file") from exc
    return pdf_path, original_filename, "server-path-image"


# ==============================================================================
# PDF text and split helpers
# ==============================================================================


def extract_embedded_pdf_text(pdf_path: Path) -> tuple[list[ExtractedPage], int]:
    reader = PdfReader(str(pdf_path))
    pages: list[ExtractedPage] = []
    for index, pdf_page in enumerate(reader.pages, start=1):
        try:
            text = pdf_page.extract_text() or ""
        except Exception:
            text = ""
        pages.append({"page": index, "content": text.strip()})
    return pages, len(reader.pages)


def split_pdf(pdf_path: Path, job_id: str, pages_per_chunk: int) -> tuple[list[dict[str, Any]], int]:
    reader = PdfReader(str(pdf_path))
    total_pages = len(reader.pages)
    job_split_dir = SPLIT_DIR / job_id
    job_split_dir.mkdir(parents=True, exist_ok=True)

    chunks: list[dict[str, Any]] = []
    for start in range(0, total_pages, pages_per_chunk):
        end = min(start + pages_per_chunk, total_pages)
        writer = PdfWriter()
        for page_index in range(start, end):
            writer.add_page(reader.pages[page_index])

        chunk_path = job_split_dir / f"chunk_{start + 1:04d}-{end:04d}.pdf"
        with open(chunk_path, "wb") as out_file:
            writer.write(out_file)

        chunks.append(
            {
                "path": str(chunk_path),
                "start_page": start + 1,
                "end_page": end,
                "page_count": end - start,
            }
        )
    return chunks, total_pages


# ==============================================================================
# olmOCR Playwright extraction
# ==============================================================================


def extract_raw_response(dialog_text: str) -> dict[str, Any]:
    marker = "Raw Response:"
    marker_index = dialog_text.find(marker)
    candidate = dialog_text[marker_index + len(marker) :] if marker_index >= 0 else dialog_text
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Unable to locate raw response JSON in modal")

    raw_json = candidate[start : end + 1].strip()
    payload = json.loads(raw_json)
    if not isinstance(payload, dict):
        raise ValueError("Raw response payload is not a JSON object")
    return payload


def _find_text_in_value(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        for key in ("natural_text", "text", "markdown", "base_text", "content"):
            nested = value.get(key)
            found = _find_text_in_value(nested)
            if found:
                return found
    return None


def extract_content_from_raw_response(raw_response: dict[str, Any]) -> str:
    for key in ("natural_text", "text", "markdown", "base_text", "content"):
        found = _find_text_in_value(raw_response.get(key))
        if found:
            return found

    # Last-resort recursive scan for common nested olmOCR payloads.
    for value in raw_response.values():
        found = _find_text_in_value(value)
        if found:
            return found

    raise ValueError("Raw response does not contain text content")


async def wait_for_completed_chunk(page: Any, expected_pages: int) -> None:
    deadline = asyncio.get_running_loop().time() + CHUNK_TIMEOUT_SECONDS
    while asyncio.get_running_loop().time() < deadline:
        # New UI: "Copy" button appears per page result (aria-label="Copy page text")
        copy_count = await page.locator('button[aria-label="Copy page text"]').count()
        if copy_count >= expected_pages:
            return
        # Fallback: also check for old "View Raw" buttons
        view_raw_count = await page.locator('button:has-text("View Raw")').count()
        if view_raw_count >= expected_pages:
            return
        await asyncio.sleep(5)
    raise TimeoutError(f"Timeout waiting for {expected_pages} page result(s)")


async def extract_chunk_results(
    page: Any, page_offset: int, expected_pages: int
) -> tuple[list[ExtractedPage], list[RawExtractedPage]]:
    extracted_pages: list[ExtractedPage] = []
    raw_pages: list[RawExtractedPage] = []

    # Try new UI first: extract text directly from page content
    try:
        page_text = await page.locator('body').inner_text(timeout=15000)
        new_pages = _parse_new_playground_text(page_text, page_offset)
        if new_pages:
            return new_pages, []
    except Exception:
        pass

    # Fallback: try old "View Raw" dialog extraction
    for index in range(expected_pages):
        try:
            view_raw_button = page.locator('button:has-text("View Raw")').nth(index)
            await view_raw_button.scroll_into_view_if_needed(timeout=15000)
            await view_raw_button.click(timeout=15000)

            dialog = page.locator('[role="dialog"]').filter(has_text="Raw Response").first
            await dialog.wait_for(state="visible", timeout=15000)
            dialog_text = await dialog.inner_text(timeout=15000)

            raw_response = extract_raw_response(dialog_text)
            content = extract_content_from_raw_response(raw_response)
            page_number = page_offset + index + 1

            extracted_pages.append({"page": page_number, "content": content})
            raw_pages.append({"page": page_number, "raw_response": raw_response})

            try:
                close_button = dialog.get_by_role("button", name=re.compile("Close", re.I))
                await close_button.click(timeout=5000)
            except Exception:
                await page.keyboard.press("Escape")
            await dialog.wait_for(state="hidden", timeout=15000)
        except Exception:
            pass

    return extracted_pages, raw_pages


def _parse_new_playground_text(page_text: str, page_offset: int) -> list[ExtractedPage]:
    """Parse the new playground.allenai.org response format.

    The new UI shows results like:
        Page 1
        Copy
        <extracted text content>
        primary_language: "en"
        is_rotation_valid: true
        ...
    """
    pages: list[ExtractedPage] = []
    # Split by "Page N" markers
    page_pattern = re.compile(r'Page\s+(\d+)\s*\n\s*Copy\s*\n(.*?)(?=Page\s+\d+|$)', re.DOTALL)
    for match in page_pattern.finditer(page_text):
        page_num = int(match.group(1))
        content = match.group(2).strip()
        # Remove metadata lines at the end
        content = re.sub(r'\s*primary_language:.*$', '', content, flags=re.DOTALL)
        content = re.sub(r'\s*is_rotation_valid:.*$', '', content, flags=re.DOTALL)
        content = re.sub(r'\s*rotation_correction:.*$', '', content, flags=re.DOTALL)
        content = re.sub(r'\s*is_table:.*$', '', content, flags=re.DOTALL)
        content = re.sub(r'\s*is_diagram:.*$', '', content, flags=re.DOTALL)
        content = content.strip()
        if content and len(content) > 5:
            pages.append({"page": page_offset + page_num, "content": content})
    return pages


async def extract_chunk_results_from_dom(page: Any, page_offset: int) -> list[ExtractedPage]:
    """Fallback scraper for both old and new UI formats."""
    # Try new UI format first
    try:
        page_text = await page.locator('body').inner_text(timeout=10000)
        new_pages = _parse_new_playground_text(page_text, page_offset)
        if new_pages:
            return new_pages
    except Exception:
        pass

    # Old UI DOM fallback
    dom_pages = await page.evaluate(
        r'''() => {
            const allText = document.body.textContent || "";
            const pages = [];
            const pageRegex = /Page\s*(\d+)\s*(\d+)?\s*(tokens\s*processed)?\s*Copy([\s\S]*?)(?=Page\s*\d+\s*\d*\s*tokens|Preview is limited|Check out our GitHub|$)/gi;
            let match;
            while ((match = pageRegex.exec(allText)) !== null) {
                const pageNum = Number.parseInt(match[1], 10) || pages.length + 1;
                let content = match[4] || "";
                content = content.replace(/Page Metadata[\s\S]*?View Raw/gi, "");
                content = content.replace(/\d+\s*tokens\s*processed\s*Copy/gi, "");
                content = content.replace(/Primary language:[\s\S]*?$/gim, "");
                content = content.replace(/Is rotation valid:[\s\S]*?$/gim, "");
                content = content.replace(/Rotation correction:[\s\S]*?$/gim, "");
                content = content.replace(/Is a table:[\s\S]*?$/gim, "");
                content = content.replace(/Is a diagram:[\s\S]*?$/gim, "");
                content = content.replace(/View Raw/gi, "");
                content = content.replace(/Preview is limited[\s\S]*$/gi, "");
                content = content.replace(/Check out our GitHub[\s\S]*$/gi, "");
                content = content.replace(/Analyze any PDF[\s\S]*$/gi, "");
                content = content.replace(/Process Document[\s\S]*$/gi, "");
                content = content.trim();
                if (content.length > 10) pages.push({ page: pageNum, content });
            }
            return pages;
        }'''
    )
    results: list[ExtractedPage] = []
    for item in dom_pages or []:
        local_page = int(item.get("page") or len(results) + 1)
        results.append(
            {"page": page_offset + local_page, "content": str(item.get("content") or "").strip()}
        )
    return results


async def process_chunk_with_retry(
    browser: Any,
    chunk: dict[str, Any],
) -> tuple[list[ExtractedPage], list[RawExtractedPage], str | None]:
    expected_pages = int(chunk["page_count"])
    last_error: str | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()
        try:
            await page.goto(WEBSITE, wait_until="networkidle", timeout=60000)

            # Handle cookie consent (Osano banner) - click all Accept buttons
            for _ in range(3):
                try:
                    buttons = await page.locator('button:has-text("Accept")').all()
                    for button in buttons:
                        if await button.is_visible(timeout=1000):
                            await button.click(timeout=3000)
                            await asyncio.sleep(1)
                except Exception:
                    break

            await asyncio.sleep(1)

            # Handle terms dialog - use force click to bypass overlay
            try:
                terms_btn = page.locator('button:has-text("Accept terms")').first
                if await terms_btn.is_visible(timeout=3000):
                    await terms_btn.click(force=True, timeout=5000)
                    await asyncio.sleep(2)
            except Exception:
                pass

            # Dismiss any remaining dialogs with Escape
            for _ in range(3):
                try:
                    remaining_dialogs = await page.locator('[role="dialog"]').all()
                    has_visible = False
                    for d in remaining_dialogs:
                        if await d.is_visible(timeout=500):
                            has_visible = True
                            break
                    if not has_visible:
                        break
                    await page.keyboard.press("Escape")
                    await asyncio.sleep(1)
                except Exception:
                    break

            await asyncio.sleep(1)

            await page.locator('input[type="file"]').set_input_files(str(chunk["path"]))
            await asyncio.sleep(2)

            # Try new UI submit button first, then fall back to old "Process" button
            submitted = False
            try:
                submit_button = page.locator('button[aria-label="Submit prompt"]').first
                if await submit_button.is_visible(timeout=5000):
                    await submit_button.click(force=True, timeout=10000)
                    submitted = True
            except Exception:
                pass

            if not submitted:
                try:
                    process_button = page.locator('button:has-text("Process")').first
                    if await process_button.is_visible(timeout=5000):
                        await process_button.click(timeout=10000)
                        submitted = True
                except Exception:
                    pass

            if not submitted:
                raise RuntimeError("No submit/process button found on page")

            await wait_for_completed_chunk(page, expected_pages)
            data, raw_pages = await extract_chunk_results(
                page,
                page_offset=int(chunk["start_page"]) - 1,
                expected_pages=expected_pages,
            )
            if len(data) == expected_pages:
                return data, raw_pages, None
            raise RuntimeError(f"Expected {expected_pages} page(s), got {len(data)}")
        except Exception as exc:
            last_error = f"attempt {attempt}/{MAX_RETRIES}: {exc}"
            try:
                fallback_pages = await extract_chunk_results_from_dom(
                    page, page_offset=int(chunk["start_page"]) - 1
                )
                if fallback_pages:
                    return fallback_pages, [], f"Used DOM fallback after raw extraction error: {last_error}"
            except Exception:
                pass
            if attempt < MAX_RETRIES:
                await asyncio.sleep(3)
        finally:
            await context.close()

    return [], [], last_error or "Unknown chunk error"


# ==============================================================================
# Result building, sanitation, MCQ generation, and job execution
# ==============================================================================


def sanitize_text_for_ai(text: str) -> str:
    """Return one-line plain content suitable for AI prompts.

    This removes markdown/html/control markers while preserving English, Hindi,
    Hinglish, numbers, and punctuation. All whitespace/newlines become one space.
    """
    value = html.unescape(text or "")
    value = value.replace("\x00", " ")
    value = re.sub(r"```(?:[a-zA-Z0-9_-]+)?", " ", value)
    value = value.replace("```", " ")
    value = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"^[\s>*_`#~|\-]{1,}\s*", " ", value, flags=re.MULTILINE)
    value = re.sub(r"[*_`>#~|]{1,}", " ", value)
    value = re.sub(r"\b(?:View Raw|Copy|Raw Response|Page Metadata)\b", " ", value, flags=re.I)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def content_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def assess_embedded_text_quality(pages: list[ExtractedPage], total_pages: int) -> dict[str, Any]:
    """Decide whether PDF embedded text is good enough to skip real OCR.

    Some scanned PDFs contain a broken/minimal hidden text layer. pypdf then
    extracts only headers, bullets, years, or font glyphs in seconds. Auto mode
    must treat that as low quality and fall back to olmOCR-web.
    """
    combined = " ".join((page.get("content") or "") for page in pages)
    sanitized = sanitize_text_for_ai(combined)
    char_count = len(sanitized)
    non_empty_pages = sum(1 for page in pages if (page.get("content") or "").strip())
    words = re.findall(r"[A-Za-z\u0900-\u097F]{2,}", sanitized)
    word_count = len(words)
    unique_words = len({word.lower() for word in words})
    chars_per_page = char_count / max(1, total_pages)
    words_per_page = word_count / max(1, total_pages)
    bad_glyphs = sum(sanitized.count(ch) for ch in "○●□■◆◇�")
    bad_glyph_ratio = bad_glyphs / max(1, char_count)
    meaningful_chars = sum(1 for ch in sanitized if ch.isalnum() or ("\u0900" <= ch <= "\u097F"))
    meaningful_ratio = meaningful_chars / max(1, char_count)
    unique_word_ratio = unique_words / max(1, word_count)

    reasons: list[str] = []
    min_total_chars = max(PDF_TEXT_MIN_CHARS, total_pages * 30)
    if char_count < min_total_chars:
        reasons.append(f"too_few_chars:{char_count}<{min_total_chars}")
    if total_pages >= 3 and chars_per_page < 180:
        reasons.append(f"low_chars_per_page:{chars_per_page:.1f}<180")
    if total_pages >= 3 and words_per_page < 25:
        reasons.append(f"low_words_per_page:{words_per_page:.1f}<25")
    if total_pages >= 10 and unique_words < 80:
        reasons.append(f"low_unique_words:{unique_words}<80")
    if word_count >= 50 and unique_word_ratio < 0.12:
        reasons.append(f"low_unique_word_ratio:{unique_word_ratio:.2f}<0.12")
    if bad_glyph_ratio > 0.035:
        reasons.append(f"bad_glyph_ratio:{bad_glyph_ratio:.3f}>0.035")
    if char_count and meaningful_ratio < 0.45:
        reasons.append(f"low_meaningful_ratio:{meaningful_ratio:.2f}<0.45")
    if total_pages >= 3 and non_empty_pages < max(1, (total_pages + 1) // 2):
        reasons.append(f"too_few_non_empty_pages:{non_empty_pages}/{total_pages}")

    return {
        "usable": not reasons,
        "reasons": reasons,
        "char_count": char_count,
        "word_count": word_count,
        "unique_words": unique_words,
        "non_empty_pages": non_empty_pages,
        "total_pages": total_pages,
        "chars_per_page": round(chars_per_page, 2),
        "words_per_page": round(words_per_page, 2),
        "bad_glyph_ratio": round(bad_glyph_ratio, 4),
        "meaningful_ratio": round(meaningful_ratio, 4),
        "unique_word_ratio": round(unique_word_ratio, 4),
    }


def source_upload_dir(job_id: str) -> Path:
    return UPLOAD_DIR / job_id


def result_job_dir(job_id: str) -> Path:
    return RESULTS_DIR / job_id


def copy_source_files_to_result(job_id: str) -> dict[str, str]:
    copied: dict[str, str] = {}
    src_dir = source_upload_dir(job_id)
    dst_dir = result_job_dir(job_id) / "source"
    if not src_dir.exists():
        return copied
    dst_dir.mkdir(parents=True, exist_ok=True)
    for item in src_dir.iterdir():
        if item.is_file():
            target = dst_dir / item.name
            shutil.copyfile(str(item), str(target))
            if item.name == "input.pdf":
                copied["normalized_pdf"] = str(target)
            elif item.name.startswith("original_"):
                copied["original"] = str(target)
    if copied:
        copied["source_directory"] = str(dst_dir)
    return copied


def result_to_text(result: dict[str, Any]) -> str:
    metadata = result.get("metadata") or {}
    sections = [
        f"File: {metadata.get('file_name', '')}",
        f"Job: {result.get('job_id', '')}",
        f"Engine: {metadata.get('engine_used', metadata.get('engine_requested', ''))}",
        f"Total pages: {metadata.get('total_pages', '')}",
        "",
    ]
    for page in result.get("pages") or []:
        sections.append(f"===== Page {page.get('page')} =====")
        sections.append(str(page.get("content") or "").strip())
        sections.append("")
    return "\n".join(sections).rstrip() + "\n"


def build_result(
    job_id: str,
    original_filename: str,
    input_kind: str,
    total_pages: int,
    engine_requested: str,
    engine_used: str,
    pages: list[ExtractedPage],
    raw_pages: list[RawExtractedPage],
    options: JobOptions,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    sorted_pages = sorted(pages, key=lambda item: item["page"])
    sorted_raw_pages = sorted(raw_pages, key=lambda item: item["page"])
    combined_text = "\n\n".join((page.get("content") or "").strip() for page in sorted_pages).strip()
    sanitized_text = sanitize_text_for_ai(combined_text)
    non_empty_pages = sum(1 for page in sorted_pages if (page.get("content") or "").strip())

    return {
        "job_id": job_id,
        "metadata": {
            "file_name": original_filename,
            "input_kind": input_kind,
            "total_pages": total_pages,
            "engine_requested": engine_requested,
            "engine_used": engine_used,
            "olmocr_website": WEBSITE if engine_used == "olmocr-web" else None,
            "pages_per_chunk": options["pages_per_chunk"],
            "concurrency": options["concurrency"],
            "created_at": jobs.get(job_id, {}).get("created_at"),
            "completed_at": utc_now(),
        },
        "pages": sorted_pages,
        "combined_text": combined_text,
        "sanitized_text": sanitized_text,
        "raw_pages": sorted_raw_pages if options["include_raw"] else [],
        "stats": {
            "pages_returned": len(sorted_pages),
            "non_empty_pages": non_empty_pages,
            "total_characters": len(combined_text),
            "sanitized_characters": len(sanitized_text),
            "content_sha256": content_sha256(sanitized_text) if sanitized_text else None,
        },
        "warnings": warnings or [],
    }


def save_result_files(job_id: str, result: dict[str, Any]) -> dict[str, str]:
    job_dir = RESULTS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    json_path = job_dir / "ocr-result.json"
    text_path = job_dir / "ocr-result.txt"
    content_path = job_dir / "content.txt"
    raw_path = job_dir / "raw-pages.json"

    source_files = copy_source_files_to_result(job_id)
    result.setdefault("metadata", {})["output_directory"] = str(job_dir)
    result.setdefault("metadata", {})["storage_root"] = str(DATA_DIR)
    files = {
        "json": str(json_path),
        "text": str(text_path),
        "content": str(content_path),
        "raw": str(raw_path),
        "directory": str(job_dir),
        **source_files,
    }
    result["files"] = files

    with open(json_path, "w", encoding="utf-8") as out_file:
        json.dump(result, out_file, ensure_ascii=False, indent=2)
    with open(text_path, "w", encoding="utf-8") as out_file:
        out_file.write(result_to_text(result))
    with open(content_path, "w", encoding="utf-8") as out_file:
        out_file.write((result.get("sanitized_text") or "").strip())
    with open(raw_path, "w", encoding="utf-8") as out_file:
        json.dump(result.get("raw_pages") or [], out_file, ensure_ascii=False, indent=2)
    return files


def sync_job_to_hf_storage(job_id: str) -> dict[str, Any] | None:
    """Optional private Hugging Face dataset backup for uploaded files and outputs."""
    if not ENABLE_HF_STORAGE:
        return None
    token = os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN")
    repo_id = HF_STORAGE_REPO_ID
    if not token or not repo_id:
        return {"enabled": True, "synced": False, "error": "HF_TOKEN/HF_STORAGE_REPO_ID missing"}
    job_dir = result_job_dir(job_id)
    if not job_dir.exists():
        return {"enabled": True, "synced": False, "error": "job directory missing"}
    try:
        from huggingface_hub import HfApi

        api = HfApi(token=token)
        api.create_repo(repo_id=repo_id, repo_type="dataset", private=HF_STORAGE_PRIVATE, exist_ok=True)
        api.upload_folder(
            repo_id=repo_id,
            repo_type="dataset",
            folder_path=str(job_dir),
            path_in_repo=f"jobs/{job_id}",
            commit_message=f"Add OCR job {job_id}",
        )
        return {
            "enabled": True,
            "synced": True,
            "repo_id": repo_id,
            "repo_type": "dataset",
            "path_in_repo": f"jobs/{job_id}",
            "private": HF_STORAGE_PRIVATE,
        }
    except Exception as exc:
        return {"enabled": True, "synced": False, "repo_id": repo_id, "error": str(exc)}


def rewrite_result_json(job_id: str, result: dict[str, Any]) -> None:
    path = result_job_dir(job_id) / "ocr-result.json"
    if path.exists():
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def hf_storage_token_repo() -> tuple[str, str] | None:
    token = os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN")
    if not token or not HF_STORAGE_REPO_ID:
        return None
    return token, HF_STORAGE_REPO_ID


def pull_hf_storage_index(limit_jobs: int = 200) -> dict[str, Any] | None:
    """Restore OCR result indexes from the private HF dataset storage.

    This makes the Uploaded tab useful even on free/ephemeral Spaces after a rebuild.
    Large source PDFs are not pulled eagerly; only JSON/text artifacts are restored.
    """
    if not (ENABLE_HF_STORAGE and ENABLE_HF_STORAGE_PULL):
        return None
    token_repo = hf_storage_token_repo()
    if not token_repo:
        return None
    token, repo_id = token_repo
    try:
        from huggingface_hub import HfApi, hf_hub_download

        api = HfApi(token=token)
        files = api.list_repo_files(repo_id=repo_id, repo_type="dataset")
        job_ids: list[str] = []
        for file_name in files:
            match = re.match(r"^jobs/([^/]+)/ocr-result\.json$", file_name)
            if match:
                job_ids.append(match.group(1))
        restored = 0
        files_set = set(files)
        for job_id in sorted(set(job_ids), reverse=True)[:limit_jobs]:
            job_dir = result_job_dir(job_id)
            job_dir.mkdir(parents=True, exist_ok=True)
            artifacts = ["ocr-result.json", "content.txt", "ocr-result.txt", "raw-pages.json"]
            artifacts.extend(
                Path(name).name
                for name in files
                if re.match(rf"^jobs/{re.escape(job_id)}/mcq-[^/]+\.json$", name)
            )
            for artifact in artifacts:
                local_path = job_dir / artifact
                if local_path.exists():
                    continue
                remote_name = f"jobs/{job_id}/{artifact}"
                if remote_name not in files_set:
                    continue
                downloaded = hf_hub_download(repo_id=repo_id, repo_type="dataset", filename=remote_name, token=token)
                shutil.copyfile(downloaded, local_path)
            if (job_dir / "ocr-result.json").exists():
                restored += 1
        return {"repo_id": repo_id, "restored_jobs": restored}
    except Exception as exc:
        return {"repo_id": repo_id, "error": str(exc)}


def ensure_artifact_available(job_id: str, artifact: str) -> Path:
    path = result_job_dir(job_id) / artifact
    if path.exists():
        return path
    pull_hf_storage_index(limit_jobs=300)
    if path.exists():
        return path
    raise HTTPException(status_code=404, detail=f"{artifact} not found")


async def run_olmocr_web(
    job_id: str,
    pdf_path: Path,
    original_filename: str,
    input_kind: str,
    total_pages: int,
    options: JobOptions,
) -> dict[str, Any]:
    update_progress(
        job_id,
        f"Splitting PDF into {options['pages_per_chunk']}-page chunks...",
        stage="splitting",
        percent=5,
        total_pages=total_pages,
    )
    chunks, _ = await asyncio.to_thread(split_pdf, pdf_path, job_id, options["pages_per_chunk"])
    if not chunks:
        raise RuntimeError("No PDF pages found")

    all_pages: list[ExtractedPage] = []
    all_raw_pages: list[RawExtractedPage] = []
    warnings: list[str] = []
    processed_chunks = 0
    processed_pages = 0
    lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(options["concurrency"])

    update_progress(
        job_id,
        f"Processing {len(chunks)} chunk(s) with olmOCR web...",
        stage="olmocr-web",
        percent=10,
        total_chunks=len(chunks),
        processed_chunks=0,
    )

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        async def chunk_worker(chunk: dict[str, Any]) -> None:
            nonlocal processed_chunks, processed_pages
            async with semaphore:
                label = f"pages {chunk['start_page']}-{chunk['end_page']}"
                async with lock:
                    update_progress(
                        job_id,
                        f"Processing chunk {label}...",
                        stage="olmocr-web",
                    )

                data, raw_pages, warning_or_error = await process_chunk_with_retry(browser, chunk)

                async with lock:
                    processed_chunks += 1
                    processed_pages += len(data)
                    all_pages.extend(data)
                    all_raw_pages.extend(raw_pages)
                    if warning_or_error:
                        warnings.append(f"Chunk {label}: {warning_or_error}")
                    percent = 10 + int((processed_chunks / len(chunks)) * 80)
                    update_progress(
                        job_id,
                        f"Finished {processed_chunks}/{len(chunks)} chunk(s); extracted {processed_pages}/{total_pages} page(s)",
                        stage="olmocr-web",
                        percent=percent,
                        processed_chunks=processed_chunks,
                        total_chunks=len(chunks),
                        processed_pages=processed_pages,
                        total_pages=total_pages,
                    )

        await asyncio.gather(*(chunk_worker(chunk) for chunk in chunks))
        await browser.close()

    if not all_pages:
        detail = "; ".join(warnings[-3:]) if warnings else "No content extracted"
        raise RuntimeError(f"olmOCR web extraction failed: {detail}")

    if len(all_pages) < total_pages:
        warnings.append(f"Expected {total_pages} page(s), extracted {len(all_pages)} page result(s).")

    return build_result(
        job_id=job_id,
        original_filename=original_filename,
        input_kind=input_kind,
        total_pages=total_pages,
        engine_requested=options["engine"],
        engine_used="olmocr-web",
        pages=all_pages,
        raw_pages=all_raw_pages,
        options=options,
        warnings=warnings,
    )


async def run_ocr_job(
    job_id: str,
    pdf_path: Path,
    original_filename: str,
    input_kind: str,
    options: JobOptions,
) -> None:
    update_job(job_id, status="processing")
    update_progress(job_id, "Reading PDF...", stage="reading", percent=2)

    try:
        embedded_pages, total_pages = await asyncio.to_thread(extract_embedded_pdf_text, pdf_path)
        embedded_quality = assess_embedded_text_quality(embedded_pages, total_pages)
        embedded_chars = int(embedded_quality["char_count"])

        use_pdf_text = options["engine"] == "pdf-text" or (
            options["engine"] == "auto" and bool(embedded_quality["usable"])
        )

        if use_pdf_text:
            if embedded_chars < PDF_TEXT_MIN_CHARS:
                raise RuntimeError(
                    "No embedded PDF text was found. Re-run with engine=olmocr-web for scanned PDFs/images."
                )
            update_progress(job_id, "Using embedded PDF text (fast path)...", stage="pdf-text", percent=85)
            result = build_result(
                job_id=job_id,
                original_filename=original_filename,
                input_kind=input_kind,
                total_pages=total_pages,
                engine_requested=options["engine"],
                engine_used="pdf-text",
                pages=embedded_pages,
                raw_pages=[],
                options=options,
                warnings=(
                    [f"PDF text quality: {embedded_quality}"]
                    if options["engine"] == "pdf-text" and not embedded_quality["usable"]
                    else [] if options["engine"] == "pdf-text"
                    else ["Auto mode used high-quality embedded PDF text; no external OCR was needed.", f"PDF text quality: {embedded_quality}"]
                ),
            )
        else:
            if options["engine"] == "auto":
                add_warning(job_id, f"Embedded PDF text looked incomplete; falling back to olmOCR web. Quality: {embedded_quality}")
            result = await run_olmocr_web(
                job_id=job_id,
                pdf_path=pdf_path,
                original_filename=original_filename,
                input_kind=input_kind,
                total_pages=total_pages,
                options=options,
            )

        update_progress(job_id, "Saving result files...", stage="saving", percent=95)
        files = await asyncio.to_thread(save_result_files, job_id, result)
        result.setdefault("metadata", {})["output_directory"] = files["directory"]
        if ENABLE_HF_STORAGE:
            update_progress(job_id, "Syncing job to Hugging Face storage...", stage="hf-storage", percent=97)
            hf_storage = await asyncio.to_thread(sync_job_to_hf_storage, job_id)
            if hf_storage:
                result.setdefault("metadata", {})["hf_storage"] = hf_storage
                files["hf_storage"] = hf_storage
                if not hf_storage.get("synced"):
                    add_warning(job_id, f"HF storage sync failed: {hf_storage.get('error')}")
                await asyncio.to_thread(rewrite_result_json, job_id, result)
        all_warnings = list(jobs.get(job_id, {}).get("warnings") or []) + list(result.get("warnings") or [])
        result["warnings"] = all_warnings
        await asyncio.to_thread(rewrite_result_json, job_id, result)

        update_job(job_id, status="completed", result=result, error=None, files=files, warnings=all_warnings)
        update_progress(job_id, "Done", stage="done", percent=100, processed_pages=total_pages, total_pages=total_pages)
    except Exception as exc:
        update_job(job_id, status="failed", error=str(exc), result=None)
        update_progress(job_id, "Failed", stage="failed", percent=100)
    finally:
        if not KEEP_UPLOADS:
            shutil.rmtree(UPLOAD_DIR / job_id, ignore_errors=True)
        shutil.rmtree(SPLIT_DIR / job_id, ignore_errors=True)
        tasks.pop(job_id, None)


def start_background_job(
    job_id: str,
    pdf_path: Path,
    original_filename: str,
    input_kind: str,
    options: JobOptions,
) -> None:
    tasks[job_id] = asyncio.create_task(
        run_ocr_job(job_id, pdf_path, original_filename, input_kind, options)
    )


def load_result_from_disk(job_id: str) -> dict[str, Any] | None:
    path = RESULTS_DIR / job_id / "ocr-result.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_completed_result(job_id: str) -> dict[str, Any]:
    if job_id in jobs and jobs[job_id].get("status") == "completed" and jobs[job_id].get("result"):
        return jobs[job_id]["result"]
    disk_result = load_result_from_disk(job_id)
    if not disk_result:
        pull_hf_storage_index()
        disk_result = load_result_from_disk(job_id)
    if disk_result:
        return disk_result
    if job_id in jobs:
        raise HTTPException(status_code=409, detail=f"Job is {jobs[job_id].get('status')}")
    raise HTTPException(status_code=404, detail="Job ID not found")


def summarize_upload_result(result: dict[str, Any]) -> dict[str, Any]:
    metadata = result.get("metadata") or {}
    stats = result.get("stats") or {}
    files = result.get("files") or {}
    job_id = str(result.get("job_id") or "")
    mcq_files = []
    job_dir = RESULTS_DIR / job_id
    if job_dir.exists():
        mcq_result_paths = [
            path for path in job_dir.glob("mcq-*.json")
            if re.match(r"^mcq-[A-Za-z0-9_-]+\.json$", path.name)
        ]
        for path in sorted(mcq_result_paths, key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                mcq_files.append(
                    {
                        "generation_id": payload.get("generation_id") or path.stem,
                        "file": str(path),
                        "created_at": payload.get("created_at"),
                        "count": len(payload.get("mcqs") or []),
                        "language": payload.get("language"),
                        "provider": payload.get("provider"),
                        "model": payload.get("model"),
                    }
                )
            except Exception:
                pass
    sanitized = result.get("sanitized_text") or ""
    return {
        "job_id": job_id,
        "status": "completed",
        "file_name": metadata.get("file_name"),
        "input_kind": metadata.get("input_kind"),
        "engine_used": metadata.get("engine_used"),
        "total_pages": metadata.get("total_pages"),
        "completed_at": metadata.get("completed_at"),
        "output_directory": metadata.get("output_directory"),
        "stats": stats,
        "files": files,
        "content_preview": sanitized[:700],
        "content_download_url": f"/download/{job_id}/content",
        "json_download_url": f"/download/{job_id}/json",
        "text_download_url": f"/download/{job_id}/text",
        "mcq_generations": mcq_files,
    }


def list_uploaded_items() -> list[dict[str, Any]]:
    pull_hf_storage_index()
    items: dict[str, dict[str, Any]] = {}
    for job_id, job in jobs.items():
        if job.get("status") == "completed" and job.get("result"):
            items[job_id] = summarize_upload_result(job["result"])
        else:
            items[job_id] = {
                "job_id": job_id,
                "status": job.get("status"),
                "file_name": (job.get("source") or {}).get("file_name"),
                "input_kind": (job.get("source") or {}).get("input_kind"),
                "created_at": job.get("created_at"),
                "updated_at": job.get("updated_at"),
                "progress": job.get("progress"),
                "error": job.get("error"),
            }
    for result_path in RESULTS_DIR.glob("*/ocr-result.json"):
        job_id = result_path.parent.name
        if job_id in items:
            continue
        result = load_result_from_disk(job_id)
        if result:
            items[job_id] = summarize_upload_result(result)
    return sorted(items.values(), key=lambda item: item.get("completed_at") or item.get("updated_at") or item.get("created_at") or "", reverse=True)


def difficulty_distribution(count: int, mix: str | None) -> dict[str, int]:
    value = (mix or "balanced").strip().lower()
    if value in {"easy", "medium", "hard"}:
        return {"easy": count if value == "easy" else 0, "medium": count if value == "medium" else 0, "hard": count if value == "hard" else 0}
    easy = max(1, round(count * 0.34)) if count >= 3 else max(0, count - 1)
    medium = max(1, round(count * 0.40)) if count >= 3 else 1 if count else 0
    hard = max(0, count - easy - medium)
    while easy + medium + hard < count:
        medium += 1
    while easy + medium + hard > count and easy > 0:
        easy -= 1
    return {"easy": easy, "medium": medium, "hard": hard}


def normalize_language(language: str | None) -> str:
    value = (language or "hinglish").strip().lower()
    aliases = {"en": "english", "english": "english", "hi": "hindi", "hindi": "hindi", "pure hindi": "hindi", "hinglish": "hinglish", "hindi+english": "hinglish"}
    if value not in aliases:
        raise HTTPException(status_code=400, detail="language must be english, hinglish, or hindi")
    return aliases[value]


def language_instruction(language: str) -> str:
    if language == "english":
        return "Write everything in polished, exam-standard English. Fix OCR spelling/capitalization in names and terms."
    if language == "hindi":
        return "Write everything in शुद्ध, परीक्षा-स्तरीय हिंदी using Devanagari. Correct Hindi spellings, matras, names, dates, and standard terminology. Avoid unnecessary English words."
    return "Write in natural exam-friendly Hinglish for Indian students. Use correct Hindi spellings in Devanagari for Hindi words/names and standard English terms where natural. Fix OCR/transliteration mistakes."


def build_mcq_prompt(source_text: str, req: McqGenerateRequest) -> tuple[str, bool]:
    language = normalize_language(req.language)
    dist = difficulty_distribution(req.count, req.difficulty_mix)
    truncated = len(source_text) > AI_CONTEXT_MAX_CHARS
    source_for_prompt = source_text[:AI_CONTEXT_MAX_CHARS]
    subject = (req.subject or "Uploaded OCR PDF content").strip()
    exam = (req.exam or "competitive exams").strip()
    prompt = f"""
You are a senior Indian competitive-exam content expert, OCR-repair specialist, and bilingual editor.

PRIMARY GOAL:
Generate exactly {req.count} ultra-accurate MCQs from the uploaded OCR content for {exam}.
Subject/context: {subject}
Language policy: {language_instruction(language)}
Difficulty distribution: easy={dist['easy']}, medium={dist['medium']}, hard={dist['hard']}.

SOURCE AND KNOWLEDGE POLICY:
- SOURCE_TEXT is the main evidence. Questions must be based on facts that are present or strongly implied in SOURCE_TEXT.
- You MAY use your own general knowledge ONLY to repair obvious OCR/transliteration/spelling issues and normalize well-known terms, names, dates, places, and Hindi spellings.
  Examples: "mahatma gandhi ka janm" -> "महात्मा गांधी का जन्म"; "londan" -> "London/लंदन"; "Champaran" -> "चंपारण"; broken matras or half-letters -> corrected Hindi spelling.
- You MAY use general knowledge to choose the correct standard spelling among OCR variants, but do NOT introduce a new fact that is not supported by SOURCE_TEXT.
- If SOURCE_TEXT has a likely typo but the intended fact is clear, correct it silently in the question/options/explanation.
- If SOURCE_TEXT is ambiguous, contradictory, or too damaged, SKIP that fact and choose a safer one.

OCR CLEANUP RULES:
- Ignore page headers/footers, watermarks, repeated teacher/channel names, bullets, UI artifacts, and random OCR glyphs.
- Normalize dates, names, movements, places, books, organizations, and legal/political terms.
- Fix minor spelling mistakes in English, Hinglish, and Hindi before creating MCQs.
- For Hindi output, use correct Devanagari spellings and matras. Do not copy romanized OCR if proper Hindi is expected.
- For Hinglish output, keep it readable and exam-friendly; prefer correct Hindi names/terms in Devanagari plus common English exam words.

MCQ QUALITY RULES:
- Each MCQ must have exactly 4 options: A, B, C, D.
- Only one option must be correct.
- Distractors must be plausible, same category/length, but clearly wrong.
- Avoid vague questions. Every question should test one clear fact/concept.
- Mix styles: direct factual, conceptual, statement-based, matching, chronology/sequence, and NOT-correct style.
- Explanations must teach WHY the answer is correct and why distractors are wrong when useful.
- Do not create MCQs from uncertain OCR fragments, broken lists without context, or unsupported details.
- Maintain exam-level spelling, grammar, capitalization, punctuation, and language consistency.

ACCURACY SELF-CHECK BEFORE FINAL OUTPUT:
1. Does each question come from SOURCE_TEXT after safe OCR repair?
2. Is the spelling of names/terms/dates corrected?
3. Are all 4 options grammatically parallel and plausible?
4. Is exactly one answer correct?
5. Is the explanation short but useful?
6. Is the output valid JSON only?

Return valid JSON only. No markdown. No comments. No trailing text.

Required JSON schema:
{{
  "language": "{language}",
  "mcqs": [
    {{
      "id": 1,
      "difficulty": "easy|medium|hard",
      "question": "clean, corrected exam-quality question",
      "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
      "correct_answer": "A|B|C|D",
      "explanation": "short explanation with corrected spelling/terminology",
      "source_quote": "short raw or lightly corrected supporting quote from SOURCE_TEXT",
      "correction_note": "optional: mention important OCR spelling correction, else empty string"
    }}
  ]
}}

SOURCE_TEXT:
{source_for_prompt}
""".strip()
    return prompt, truncated


def _json_candidate(text: str) -> str:
    cleaned = (text or "").strip().replace("\ufeff", "")
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    if start < 0:
        start = cleaned.find("[")
    if start < 0:
        return cleaned

    # Prefer balanced JSON object/array instead of naive rfind, because the AI
    # sometimes appends notes after JSON. This scanner respects strings.
    opener = cleaned[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(cleaned)):
        ch = cleaned[index]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return cleaned[start : index + 1]
    end = cleaned.rfind(closer)
    return cleaned[start : end + 1] if end > start else cleaned[start:]


def _loads_json_lenient(candidate: str) -> Any:
    attempts = [candidate]
    repaired = candidate
    repaired = repaired.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    attempts.append(repaired)
    for item in attempts:
        try:
            return json.loads(item, strict=False)
        except json.JSONDecodeError:
            continue
    return json.loads(attempts[-1], strict=False)


def extract_json_payload(text: str) -> dict[str, Any]:
    candidate = _json_candidate(text)
    try:
        payload = _loads_json_lenient(candidate)
    except json.JSONDecodeError as exc:
        preview = candidate[max(0, exc.pos - 180) : exc.pos + 180]
        raise HTTPException(
            status_code=502,
            detail={
                "code": "ai_invalid_json",
                "message": f"AI returned invalid JSON: {exc}",
                "line": exc.lineno,
                "column": exc.colno,
                "position": exc.pos,
                "near": preview,
            },
        ) from exc
    if isinstance(payload, list):
        payload = {"mcqs": payload}
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="AI returned JSON that is not an object")
    return payload


def invalid_json_message(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        return str(detail.get("message") or detail)
    return str(detail)


def build_json_repair_prompt(raw_text: str, req: McqGenerateRequest, parse_error: str) -> str:
    language = normalize_language(req.language)
    raw = raw_text[:120000]
    return f"""
You are a strict JSON repair engine for MCQ generation output.

The previous AI output was intended to be JSON but is malformed.
Parse error: {parse_error}

TASK:
- Repair syntax and return valid JSON only.
- Preserve as many MCQs as possible.
- If an MCQ object is too broken to repair safely, remove only that object.
- Keep exactly these keys per MCQ when possible: id, difficulty, question, options, correct_answer, explanation, source_quote, correction_note.
- options must be an object with A, B, C, D.
- correct_answer must be A, B, C, or D.
- Keep language as {language}.
- Do not add markdown, comments, or extra text.

Required shape:
{{"language":"{language}","mcqs":[{{"id":1,"difficulty":"easy|medium|hard","question":"...","options":{{"A":"...","B":"...","C":"...","D":"..."}},"correct_answer":"A","explanation":"...","source_quote":"...","correction_note":""}}]}}

MALFORMED_OUTPUT:
{raw}
""".strip()


def validate_mcq_payload(payload: dict[str, Any], requested_count: int) -> list[dict[str, Any]]:
    mcqs = payload.get("mcqs")
    if not isinstance(mcqs, list):
        raise HTTPException(status_code=502, detail="AI JSON does not contain mcqs list")
    normalized: list[dict[str, Any]] = []
    for idx, item in enumerate(mcqs, start=1):
        if not isinstance(item, dict):
            continue
        options = item.get("options")
        if isinstance(options, list):
            options = {letter: str(options[i]) for i, letter in enumerate("ABCD") if i < len(options)}
        if not isinstance(options, dict):
            continue
        fixed_options = {letter: str(options.get(letter) or options.get(letter.lower()) or "").strip() for letter in "ABCD"}
        if any(not fixed_options[letter] for letter in "ABCD"):
            continue
        correct = str(item.get("correct_answer") or item.get("answer") or "").strip().upper().replace("(", "").replace(")", "")[:1]
        if correct not in "ABCD":
            continue
        normalized.append(
            {
                "id": int(item.get("id") or idx),
                "difficulty": str(item.get("difficulty") or "medium").strip().lower(),
                "question": str(item.get("question") or "").strip(),
                "options": fixed_options,
                "correct_answer": correct,
                "explanation": str(item.get("explanation") or "").strip(),
                "source_quote": str(item.get("source_quote") or "").strip(),
                "correction_note": str(item.get("correction_note") or "").strip(),
            }
        )
    if not normalized:
        raise HTTPException(status_code=502, detail="AI did not return usable MCQs")
    return normalized[:requested_count]


def save_mcq_generation(job_id: str, generation: dict[str, Any]) -> dict[str, str]:
    job_dir = result_job_dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    path = job_dir / f"mcq-{generation['generation_id']}.json"
    files = dict(generation.get("files") or {})
    files.update({"json": str(path), "download_url": f"/mcq/{generation['generation_id']}/download"})
    generation["files"] = files
    with open(path, "w", encoding="utf-8") as out_file:
        json.dump(generation, out_file, ensure_ascii=False, indent=2)
    return files


def find_mcq_generation(generation_id: str) -> tuple[Path, dict[str, Any]]:
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "", generation_id)
    for path in RESULTS_DIR.glob(f"*/mcq-{safe_id}.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        return path, payload
    raise HTTPException(status_code=404, detail="MCQ generation not found")


def sse_line(event: dict[str, Any]) -> str:
    payload = {"ts": utc_now(), **event}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def exception_payload(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, HTTPException):
        detail = exc.detail
        message = detail.get("message") if isinstance(detail, dict) else str(detail)
        return {"type": "error", "status_code": exc.status_code, "message": message, "detail": detail}
    return {"type": "error", "message": str(exc)}


async def generate_mcqs_core(req: McqGenerateRequest, emit: Any | None = None) -> dict[str, Any]:
    generation_id = uuid.uuid4().hex[:16]
    job_dir = result_job_dir(req.job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    partial_path = job_dir / f"mcq-{generation_id}.partial.txt"
    progress_path = job_dir / f"mcq-{generation_id}.progress.json"
    log_lock = Lock()
    stream_state: dict[str, Any] = {"chars": 0, "last_emit_chars": 0, "last_emit_at": 0.0, "last_preview": ""}

    def write_progress(event: dict[str, Any]) -> None:
        progress = {
            "generation_id": generation_id,
            "job_id": req.job_id,
            "updated_at": utc_now(),
            "event": {key: value for key, value in event.items() if key != "delta"},
            "stream_chars": stream_state["chars"],
            "partial_file": str(partial_path),
        }
        progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")

    def log(event: dict[str, Any]) -> None:
        event = {"generation_id": generation_id, **event}
        with log_lock:
            if event.get("type") == "token_delta":
                delta = str(event.get("delta") or "")
                if delta:
                    with open(partial_path, "a", encoding="utf-8") as partial_file:
                        partial_file.write(delta)
                    stream_state["chars"] = int(event.get("total_chars") or stream_state["chars"] + len(delta))
                    stream_state["last_preview"] = (stream_state.get("last_preview", "") + delta)[-180:]
                now = time.monotonic()
                should_emit = (
                    stream_state["chars"] - int(stream_state["last_emit_chars"]) >= 400
                    or now - float(stream_state["last_emit_at"]) >= 1.5
                )
                if should_emit:
                    stream_state["last_emit_chars"] = stream_state["chars"]
                    stream_state["last_emit_at"] = now
                    progress_event = {
                        "type": "stream_progress",
                        "stage": "ai_streaming",
                        "message": f"AI streamed {stream_state['chars']:,} characters so far",
                        "percent": 35,
                        "provider": event.get("provider"),
                        "model": event.get("model"),
                        "key_mask": event.get("key_mask"),
                        "stream_chars": stream_state["chars"],
                        "partial_file": str(partial_path),
                        "preview": stream_state["last_preview"],
                    }
                    write_progress(progress_event)
                    if emit:
                        emit(progress_event)
                return
            write_progress(event)
            if emit:
                emit(event)

    log({"type": "stage", "stage": "created", "message": "Created MCQ generation files", "percent": 2, "partial_file": str(partial_path), "progress_file": str(progress_path)})
    log({"type": "stage", "stage": "loading", "message": "Loading OCR content", "percent": 5, "job_id": req.job_id})
    result = get_completed_result(req.job_id)
    source_text = str(result.get("sanitized_text") or "").strip()
    if not source_text:
        source_text = sanitize_text_for_ai(str(result.get("combined_text") or ""))
    if len(source_text) < 50:
        raise HTTPException(status_code=400, detail="OCR content is too small for MCQ generation")

    log(
        {
            "type": "stage",
            "stage": "prompt",
            "message": f"Preparing prompt from {len(source_text):,} sanitized characters",
            "percent": 15,
            "source_chars": len(source_text),
            "requested_count": req.count,
            "language": normalize_language(req.language),
        }
    )
    prompt, truncated = build_mcq_prompt(source_text, req)
    provider = req.provider or default_provider_name()
    model = req.model or default_model_name(provider)
    log(
        {
            "type": "stage",
            "stage": "ai_start",
            "message": f"Calling AI provider {provider} with model {model}",
            "percent": 25,
            "provider": provider,
            "model": model,
            "prompt_chars": len(prompt),
            "source_truncated": truncated,
        }
    )

    ai_result = await asyncio.to_thread(
        AiService().generate_text,
        prompt=prompt,
        provider=req.provider,
        model=req.model,
        temperature=req.temperature,
        event_callback=log,
    )

    log(
        {
            "type": "stage",
            "stage": "parsing",
            "message": f"AI response received ({len(ai_result.text):,} chars). Parsing JSON...",
            "percent": 72,
            "provider": ai_result.provider,
            "model": ai_result.model,
            "key_mask": ai_result.key_mask,
            "response_chars": len(ai_result.text),
        }
    )

    raw_ai_text = ai_result.text
    json_repaired = False
    repair_attempts: list[dict[str, Any]] = []
    payload: dict[str, Any] | None = None
    last_parse_error = ""
    for parse_attempt in range(1, 4):
        try:
            payload = extract_json_payload(raw_ai_text)
            if parse_attempt > 1:
                json_repaired = True
                log({"type": "stage", "stage": "json_repaired", "message": f"JSON repaired on attempt {parse_attempt - 1}", "percent": 80})
            break
        except HTTPException as exc:
            last_parse_error = invalid_json_message(exc)
            invalid_path = job_dir / f"mcq-{generation_id}.invalid-attempt-{parse_attempt}.txt"
            invalid_path.write_text(raw_ai_text, encoding="utf-8")
            log(
                {
                    "type": "warning",
                    "stage": "json_parse_failed",
                    "message": f"AI JSON parse failed; auto-repair attempt {parse_attempt}/3 will run instead of stopping. {last_parse_error}",
                    "percent": 74,
                    "invalid_file": str(invalid_path),
                }
            )
            repair_prompt = build_json_repair_prompt(raw_ai_text, req, last_parse_error)
            repair_result = await asyncio.to_thread(
                AiService().generate_text,
                prompt=repair_prompt,
                provider=ai_result.provider,
                model=ai_result.model,
                temperature=0,
                event_callback=None,
            )
            repair_attempts.append(
                {
                    "attempt": parse_attempt,
                    "invalid_file": str(invalid_path),
                    "error": last_parse_error,
                    "repair_chars": len(repair_result.text),
                    "provider": repair_result.provider,
                    "model": repair_result.model,
                    "key_mask": repair_result.key_mask,
                }
            )
            repair_path = job_dir / f"mcq-{generation_id}.repair-attempt-{parse_attempt}.txt"
            repair_path.write_text(repair_result.text, encoding="utf-8")
            log(
                {
                    "type": "stage",
                    "stage": "json_repair_response",
                    "message": f"Repair attempt {parse_attempt} returned {len(repair_result.text):,} chars; parsing again...",
                    "percent": 78,
                    "repair_file": str(repair_path),
                    "key_mask": repair_result.key_mask,
                    "provider": repair_result.provider,
                    "model": repair_result.model,
                }
            )
            raw_ai_text = repair_result.text

    if payload is None:
        raise HTTPException(status_code=502, detail=f"AI JSON repair failed after 3 attempts: {last_parse_error}")

    mcqs = validate_mcq_payload(payload, req.count)
    log({"type": "stage", "stage": "validated", "message": f"Validated {len(mcqs)} MCQs", "percent": 84, "count": len(mcqs), "json_repaired": json_repaired})

    generation = {
        "generation_id": generation_id,
        "job_id": req.job_id,
        "created_at": utc_now(),
        "language": normalize_language(req.language),
        "requested_count": req.count,
        "count": len(mcqs),
        "difficulty_mix": req.difficulty_mix,
        "provider": ai_result.provider,
        "model": ai_result.model,
        "key_mask": ai_result.key_mask,
        "source_content_sha256": (result.get("stats") or {}).get("content_sha256") or content_sha256(source_text),
        "source_truncated": truncated,
        "mcqs": mcqs,
        "raw_ai_text": raw_ai_text,
        "json_repaired": json_repaired,
        "repair_attempts": repair_attempts,
        "files": {
            "partial_raw_ai_text": str(partial_path),
            "progress": str(progress_path),
        },
    }
    log({"type": "stage", "stage": "saving", "message": "Saving MCQ JSON", "percent": 90, "generation_id": generation_id})
    files = await asyncio.to_thread(save_mcq_generation, req.job_id, generation)
    generation["files"] = files
    if ENABLE_HF_STORAGE:
        log({"type": "stage", "stage": "hf_storage", "message": "Syncing MCQ output to Hugging Face storage", "percent": 94})
        hf_storage = await asyncio.to_thread(sync_job_to_hf_storage, req.job_id)
        if hf_storage:
            generation["hf_storage"] = hf_storage
            await asyncio.to_thread(save_mcq_generation, req.job_id, generation)
            if not hf_storage.get("synced"):
                log({"type": "warning", "stage": "hf_storage", "message": f"HF storage sync failed: {hf_storage.get('error')}"})
    log({"type": "stage", "stage": "done", "message": "MCQs generated", "percent": 100, "generation_id": generation_id, "count": len(mcqs)})
    return generation


# ==============================================================================
# Routes
# ==============================================================================


@app.get("/", include_in_schema=False, response_model=None)
def index():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return health()


@app.get("/ui", include_in_schema=False)
def ui() -> FileResponse:
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="UI not found")
    return FileResponse(str(index_path))


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "ocr-automation",
        "version": app.version,
        "data_dir": str(DATA_DIR),
        "default_engine": DEFAULT_ENGINE,
        "default_ai_provider": default_provider_name(),
        "default_ai_model": default_model_name(default_provider_name()),
        "olmocr_website": WEBSITE,
    }


@app.get("/config")
def config() -> dict[str, Any]:
    return {
        "supported_engines": sorted(SUPPORTED_ENGINES),
        "supported_suffixes": sorted(SUPPORTED_SUFFIXES),
        "defaults": {
            "engine": DEFAULT_ENGINE,
            "pages_per_chunk": DEFAULT_PAGES_PER_CHUNK,
            "concurrency": DEFAULT_CONCURRENCY,
            "include_raw": True,
            "ai_provider": default_provider_name(),
            "ai_model": default_model_name(default_provider_name()),
        },
        "limits": {"pages_per_chunk": [1, 10], "concurrency": [1, 4], "mcq_count": [1, 100]},
        "server_path_enabled": ALLOW_SERVER_PATH,
        "data_dir": str(DATA_DIR),
        "hf_storage": {
            "enabled": ENABLE_HF_STORAGE,
            "pull_enabled": ENABLE_HF_STORAGE_PULL,
            "repo_id": HF_STORAGE_REPO_ID,
            "private": HF_STORAGE_PRIVATE,
        },
    }


@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    engine: str = Form(DEFAULT_ENGINE),
    pages_per_chunk: int | None = Form(None),
    concurrency: int | None = Form(None),
    include_raw: bool = Form(True),
) -> dict[str, Any]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")
    job_id = str(uuid.uuid4())
    options = normalize_options(engine, pages_per_chunk, concurrency, include_raw)
    pdf_path, original_filename, input_kind = prepare_upload_as_pdf(file, job_id)
    create_job(job_id, original_filename, input_kind, options)
    start_background_job(job_id, pdf_path, original_filename, input_kind, options)
    return accepted_payload(job_id)


@app.post("/api/upload", include_in_schema=False)
async def api_upload_file(
    file: UploadFile = File(...),
    engine: str = Form(DEFAULT_ENGINE),
    pages_per_chunk: int | None = Form(None),
    concurrency: int | None = Form(None),
    include_raw: bool = Form(True),
) -> dict[str, Any]:
    return await upload_file(file, engine, pages_per_chunk, concurrency, include_raw)


@app.post("/upload-path")
async def upload_path(req: UploadPathRequest) -> dict[str, Any]:
    path_text = (req.path or "").strip()
    if not path_text:
        raise HTTPException(status_code=400, detail="Missing 'path'")
    job_id = str(uuid.uuid4())
    options = normalize_options(req.engine, req.pages_per_chunk, req.concurrency, req.include_raw)
    pdf_path, original_filename, input_kind = prepare_server_path_as_pdf(Path(path_text), job_id)
    create_job(job_id, original_filename, input_kind, options)
    jobs[job_id]["source"]["path"] = path_text
    start_background_job(job_id, pdf_path, original_filename, input_kind, options)
    return accepted_payload(job_id)


@app.post("/api/upload-path", include_in_schema=False)
async def api_upload_path(req: UploadPathRequest) -> dict[str, Any]:
    return await upload_path(req)


@app.get("/status/{job_id}")
def get_status(job_id: str) -> dict[str, Any]:
    if job_id not in jobs:
        disk_result = load_result_from_disk(job_id)
        if disk_result:
            return {
                "status": "completed",
                "job_id": job_id,
                "created_at": (disk_result.get("metadata") or {}).get("created_at"),
                "updated_at": (disk_result.get("metadata") or {}).get("completed_at"),
                "source": {
                    "file_name": (disk_result.get("metadata") or {}).get("file_name"),
                    "input_kind": (disk_result.get("metadata") or {}).get("input_kind"),
                },
                "options": {},
                "progress": {"stage": "done", "message": "Loaded from storage", "percent": 100},
                "warnings": disk_result.get("warnings", []),
                "files": disk_result.get("files", {}),
                "result": disk_result,
            }
        raise HTTPException(status_code=404, detail="Job ID not found")
    job = jobs[job_id]
    payload = {
        "status": job["status"],
        "job_id": job_id,
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "source": job.get("source"),
        "options": job.get("options"),
        "progress": job.get("progress"),
        "warnings": job.get("warnings", []),
        "files": job.get("files", {}),
    }
    if job["status"] == "completed":
        payload["result"] = job.get("result")
    if job["status"] == "failed":
        payload["error"] = job.get("error")
    return payload


@app.get("/api/status/{job_id}", include_in_schema=False)
def api_get_status(job_id: str) -> dict[str, Any]:
    return get_status(job_id)


@app.get("/result/{job_id}")
def get_result(job_id: str) -> dict[str, Any]:
    if job_id not in jobs:
        result_path = RESULTS_DIR / job_id / "ocr-result.json"
        if result_path.exists():
            return json.loads(result_path.read_text(encoding="utf-8"))
        raise HTTPException(status_code=404, detail="Job ID not found")
    job = jobs[job_id]
    if job["status"] != "completed" or not job.get("result"):
        raise HTTPException(status_code=409, detail=f"Job is {job['status']}")
    return job["result"]


@app.get("/jobs")
def list_jobs() -> dict[str, Any]:
    items = []
    for job_id, job in sorted(jobs.items(), key=lambda kv: kv[1].get("created_at", ""), reverse=True):
        items.append(
            {
                "job_id": job_id,
                "status": job.get("status"),
                "created_at": job.get("created_at"),
                "updated_at": job.get("updated_at"),
                "source": job.get("source"),
                "progress": job.get("progress"),
                "warnings": job.get("warnings", []),
            }
        )
    return {"jobs": items}


@app.get("/uploads")
def uploads() -> dict[str, Any]:
    return {"items": list_uploaded_items(), "storage_root": str(DATA_DIR)}


@app.get("/uploads/{job_id}")
def upload_detail(job_id: str) -> dict[str, Any]:
    return get_completed_result(job_id)


@app.get("/ai/catalog")
def ai_catalog(refresh: bool = False) -> dict[str, Any]:
    return AiService().catalog(refresh=refresh)


@app.get("/ai/status")
def ai_status(provider: str | None = None) -> dict[str, Any]:
    return AiService().status(provider=provider)


@app.post("/mcq/generate")
async def generate_mcqs(req: McqGenerateRequest) -> dict[str, Any]:
    return await generate_mcqs_core(req)


@app.post("/mcq/generate/stream")
async def generate_mcqs_stream(req: McqGenerateRequest) -> StreamingResponse:
    async def event_generator():
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        done = asyncio.Event()

        def emit(event: dict[str, Any]) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, event)

        async def worker() -> None:
            try:
                generation = await generate_mcqs_core(req, emit=emit)
                emit({"type": "done", "message": "Done", "percent": 100, "result": generation})
            except Exception as exc:
                emit(exception_payload(exc))
            finally:
                loop.call_soon_threadsafe(done.set)

        task = asyncio.create_task(worker())
        try:
            yield sse_line({"type": "connected", "message": "MCQ SSE stream connected", "percent": 0})
            while not done.is_set() or not queue.empty():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield sse_line({"type": "ping", "message": "still working"})
                    continue
                yield sse_line(event)
            await task
        except asyncio.CancelledError:
            task.cancel()
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/mcq/{generation_id}")
def get_mcq_generation(generation_id: str) -> dict[str, Any]:
    _, payload = find_mcq_generation(generation_id)
    return payload


@app.get("/mcq/{generation_id}/download")
def download_mcq_generation(generation_id: str) -> FileResponse:
    path, _ = find_mcq_generation(generation_id)
    return FileResponse(str(path), filename=f"{generation_id}-mcqs.json", media_type="application/json")


@app.post("/cancel/{job_id}")
def cancel_job(job_id: str) -> dict[str, Any]:
    task = tasks.get(job_id)
    if not task:
        raise HTTPException(status_code=404, detail="Running task not found")
    task.cancel()
    update_job(job_id, status="failed", error="Cancelled by user")
    update_progress(job_id, "Cancelled", stage="cancelled", percent=100)
    return {"ok": True, "job_id": job_id, "status": "cancelled"}


@app.get("/download/{job_id}/json")
def download_json(job_id: str) -> FileResponse:
    path = ensure_artifact_available(job_id, "ocr-result.json")
    return FileResponse(str(path), filename=f"{job_id}-ocr-result.json", media_type="application/json")


@app.get("/download/{job_id}/text")
def download_text(job_id: str) -> FileResponse:
    path = ensure_artifact_available(job_id, "ocr-result.txt")
    return FileResponse(str(path), filename=f"{job_id}-ocr-result.txt", media_type="text/plain; charset=utf-8")


@app.get("/download/{job_id}/content")
def download_content(job_id: str) -> FileResponse:
    path = ensure_artifact_available(job_id, "content.txt")
    return FileResponse(str(path), filename=f"{job_id}-content.txt", media_type="text/plain; charset=utf-8")


@app.get("/download/{job_id}/raw")
def download_raw(job_id: str) -> FileResponse:
    path = ensure_artifact_available(job_id, "raw-pages.json")
    return FileResponse(str(path), filename=f"{job_id}-raw-pages.json", media_type="application/json")


@app.get("/download/{job_id}.json", include_in_schema=False)
def download_json_short(job_id: str) -> FileResponse:
    return download_json(job_id)


@app.get("/download/{job_id}.txt", include_in_schema=False)
def download_text_short(job_id: str) -> FileResponse:
    return download_text(job_id)


@app.get("/download/{job_id}.content.txt", include_in_schema=False)
def download_content_short(job_id: str) -> FileResponse:
    return download_content(job_id)


@app.post("/cleanup")
def cleanup(delete_results: bool = False) -> dict[str, Any]:
    deleted_upload_dirs = 0
    deleted_split_dirs = 0
    for directory in UPLOAD_DIR.glob("*"):
        if directory.is_dir():
            shutil.rmtree(directory, ignore_errors=True)
            deleted_upload_dirs += 1
    for directory in SPLIT_DIR.glob("*"):
        if directory.is_dir():
            shutil.rmtree(directory, ignore_errors=True)
            deleted_split_dirs += 1
    deleted_results = 0
    if delete_results:
        for directory in RESULTS_DIR.glob("*"):
            if directory.is_dir():
                shutil.rmtree(directory, ignore_errors=True)
                deleted_results += 1
    return {
        "ok": True,
        "deleted_upload_dirs": deleted_upload_dirs,
        "deleted_split_dirs": deleted_split_dirs,
        "deleted_result_dirs": deleted_results,
    }


@app.get("/explain")
def explain() -> PlainTextResponse:
    return PlainTextResponse(
        "ocr-automation.sh opened olmocr.allenai.org with Playwright CLI, uploaded a fixed PDF, "
        "waited for the web demo, and scraped output manually. This FastAPI version automates that "
        "flow end-to-end: upload or server path -> PDF/image normalization -> PDF chunking -> olmOCR "
        "Playwright extraction -> JSON/TXT downloads. Use / for UI, /docs for Swagger, /upload or "
        "/upload-path for API."
    )

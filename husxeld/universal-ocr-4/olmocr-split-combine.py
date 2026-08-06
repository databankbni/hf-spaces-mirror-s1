#!/usr/bin/env python3
"""
Full PDF OCR using olmOCR with PDF splitting
Splits PDF into chunks, processes each through olmOCR web demo in parallel,
and combines results.

Bypasses the 10-page demo limit by processing in batches, and runs multiple
batches concurrently via isolated browser contexts (asyncio.Semaphore).

Each chunk runs in its own context, drives olmOCR, waits for N "View Raw"
buttons (= one per page), then clicks each one to extract the structured
JSON from the dialog.  This mirrors the proven FastAPI server path.

Usage:
    python ocr-automation/olmocr-split-combine.py <pdf_path> [pages_per_chunk] [concurrency]

    pdf_path       absolute path to the PDF (or set OCR_PDF_PATH)
    pages_per_chunk 1..10, default 6
    concurrency    1..4, default 2 (each chunk = own browser context)

All three are also overridable via env vars: OCR_PDF_PATH, OCR_PAGES_PER_CHUNK,
OCR_CONCURRENCY, OCR_OUTPUT_DIR, OCR_TEMP_DIR, OLMOCR_WEBSITE.
"""

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from playwright.async_api import async_playwright

# Defaults (overridable via CLI / env)
DEFAULT_PDF_PATH = (
    "/teamspace/studios/this_studio/works/kgshai/downloads/"
    "Bihar Police Batch 2026/Biology By Gyan Sir/Videos/"
    "Lecture 01  Nutrition  पोषण (Part 01).pdf"
)
BASE_OUTPUT_DIR = os.environ.get(
    "OCR_OUTPUT_DIR",
    "/teamspace/studios/this_studio/works/ocr-automation/outputs",
)
TEMP_DIR = os.environ.get(
    "OCR_TEMP_DIR",
    "/teamspace/studios/this_studio/works/ocr-automation/temp-split",
)
WEBSITE = os.environ.get("OLMOCR_WEBSITE", "https://olmocr.allenai.org/")

DEFAULT_PAGES_PER_CHUNK = 6
DEFAULT_CONCURRENCY = 2
MAX_CONCURRENCY = 4
MAX_RETRIES = 2
CHUNK_TIMEOUT_SECONDS = 600  # per-chunk hard cap


def _cli_arg(idx: int, env: str, default):
    if len(sys.argv) > idx:
        return sys.argv[idx]
    return os.environ.get(env, default)


PDF_PATH = _cli_arg(1, "OCR_PDF_PATH", DEFAULT_PDF_PATH)
PAGES_PER_CHUNK = int(_cli_arg(2, "OCR_PAGES_PER_CHUNK", DEFAULT_PAGES_PER_CHUNK))
CONCURRENCY = int(_cli_arg(3, "OCR_CONCURRENCY", DEFAULT_CONCURRENCY))

PAGES_PER_CHUNK = max(1, min(10, PAGES_PER_CHUNK))
CONCURRENCY = max(1, min(MAX_CONCURRENCY, CONCURRENCY))


# ==============================================================================
# PDF splitting
# ==============================================================================


def split_pdf(pdf_path: str, pages_per_chunk: int) -> list[dict]:
    reader = PdfReader(pdf_path)
    total_pages = len(reader.pages)
    chunks: list[dict] = []
    os.makedirs(TEMP_DIR, exist_ok=True)

    for start in range(0, total_pages, pages_per_chunk):
        end = min(start + pages_per_chunk, total_pages)
        chunk_num = start // pages_per_chunk
        writer = PdfWriter()
        for i in range(start, end):
            writer.add_page(reader.pages[i])
        chunk_path = os.path.join(
            TEMP_DIR, f"chunk_{chunk_num:03d}_pages{start + 1}-{end}.pdf"
        )
        with open(chunk_path, "wb") as f:
            writer.write(f)
        chunks.append(
            {
                "path": chunk_path,
                "start_page": start + 1,
                "end_page": end,
                "page_count": end - start,
            }
        )
    return chunks


# ==============================================================================
# Per-chunk processing (async, runs in its own browser context)
# ==============================================================================


async def _wait_for_view_raw_buttons(page, expected: int, timeout: float) -> bool:
    """Poll for `expected` 'View Raw' buttons to appear (= chunk is done)."""
    deadline = time.monotonic() + timeout
    last_count = -1
    while time.monotonic() < deadline:
        try:
            count = await page.locator('button:has-text("View Raw")').count()
        except Exception:
            count = 0
        if count != last_count:
            print(f"      view-raw buttons: {count}/{expected}", flush=True)
            last_count = count
        if count >= expected:
            return True
        await asyncio.sleep(3)
    return False


def _extract_raw_response(dialog_text: str) -> dict | None:
    marker = "Raw Response:"
    idx = dialog_text.find(marker)
    candidate = dialog_text[idx + len(marker) :] if idx >= 0 else dialog_text
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(candidate[start : end + 1].strip())
    except json.JSONDecodeError:
        return None


def _find_text_in_value(value) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        for key in ("natural_text", "text", "markdown", "base_text", "content"):
            nested = value.get(key)
            if nested is not None:
                t = _find_text_in_value(nested)
                if t:
                    return t
    if isinstance(value, list):
        for item in value:
            t = _find_text_in_value(item)
            if t:
                return t
    return None


async def _extract_pages_via_view_raw(page, expected: int) -> list[dict]:
    """Click each 'View Raw' button, parse the dialog JSON."""
    out: list[dict] = []
    for index in range(expected):
        btn = page.locator('button:has-text("View Raw")').nth(index)
        await btn.scroll_into_view_if_needed(timeout=15_000)
        await btn.click(timeout=15_000)
        dialog = page.locator('[role="dialog"]').filter(has_text="Raw Response").first
        await dialog.wait_for(state="visible", timeout=15_000)
        dialog_text = await dialog.inner_text(timeout=15_000)
        raw = _extract_raw_response(dialog_text) or {}
        text = _find_text_in_value(raw) or ""
        out.append({"raw": raw, "text": text})
        try:
            close_btn = dialog.get_by_role("button", name=re.compile("Close", re.I))
            await close_btn.click(timeout=5_000)
        except Exception:
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass
        await dialog.wait_for(state="hidden", timeout=15_000)
    return out


async def _extract_pages_from_dom(page, page_offset: int) -> list[dict]:
    """Fallback: regex over document.body.textContent."""
    js = r"""
    (offset) => {
      const allText = document.body.textContent;
      const pages = [];
      const re = /Page\s*(\d+)\s*(\d+)?\s*(tokens\s*processed)?\s*Copy([\s\S]*?)(?=Page\s*\d+\s*\d*\s*tokens|Preview is limited|Check out our GitHub|$)/gi;
      let m;
      while ((m = re.exec(allText)) !== null) {
        let content = m[4];
        content = content.replace(/Page Metadata[\s\S]*?View Raw/gi, '');
        content = content.replace(/\d+\s*tokens\s*processed\s*Copy/gi, '');
        content = content.replace(/Primary language:[\s\S]*?$/gim, '');
        content = content.replace(/Is rotation valid:[\s\S]*?$/gim, '');
        content = content.replace(/Rotation correction:[\s\S]*?$/gim, '');
        content = content.replace(/Is a table:[\s\S]*?$/gim, '');
        content = content.replace(/Is a diagram:[\s\S]*?$/gim, '');
        content = content.replace(/View Raw/gi, '');
        content = content.replace(/Preview is limited[\s\S]*$/gi, '');
        content = content.replace(/Process Document[\s\S]*$/gi, '');
        content = content.replace(/Analyze any PDF[\s\S]*$/gi, '');
        content = content.replace(/Or try a sample[\s\S]*$/gi, '');
        content = content.replace(/Follow Ai2[\s\S]*$/gi, '');
        content = content.replace(/© The Allen Institute[\s\S]*$/gi, '');
        content = content.trim();
        if (content.length > 30) {
          pages.push({ originalPage: parseInt(m[1]) + offset, content });
        }
      }
      return pages;
    }
    """
    return await page.evaluate(js, page_offset)


async def _process_chunk(
    context, chunk: dict, chunk_index: int, total_chunks: int
) -> tuple[list[dict], str | None]:
    """Process a chunk in the given context. Returns (pages, warning)."""
    label = f"pages {chunk['start_page']}-{chunk['end_page']}"
    expected = int(chunk["page_count"])
    page_offset = int(chunk["start_page"]) - 1

    for attempt in range(1, MAX_RETRIES + 1):
        page = await context.new_page()
        try:
            t0 = time.monotonic()
            await page.goto(WEBSITE, wait_until="domcontentloaded", timeout=60_000)
            print(
                f"    [{chunk_index}/{total_chunks}] {label}: page loaded in {time.monotonic() - t0:.1f}s",
                flush=True,
            )

            for btn_label in ("Accept", "I Agree", "Agree"):
                try:
                    btn = page.locator(f'button:has-text("{btn_label}")').first
                    if await btn.is_visible(timeout=1500):
                        await btn.click(timeout=5000)
                        break
                except Exception:
                    pass

            await page.locator('input[type="file"]').set_input_files(chunk["path"])
            print(
                f"    [{chunk_index}/{total_chunks}] {label}: file uploaded", flush=True
            )

            process_btn = page.locator('button:has-text("Process")').first
            if await process_btn.is_visible(timeout=10_000):
                await process_btn.click(timeout=10_000)
                print(
                    f"    [{chunk_index}/{total_chunks}] {label}: processing started",
                    flush=True,
                )

            if not await _wait_for_view_raw_buttons(
                page, expected, CHUNK_TIMEOUT_SECONDS
            ):
                raise TimeoutError(
                    f"Only got <{expected} View Raw buttons within {CHUNK_TIMEOUT_SECONDS}s"
                )
            ocr_elapsed = time.monotonic() - t0
            print(
                f"    [{chunk_index}/{total_chunks}] {label}: OCR done in {ocr_elapsed:.1f}s",
                flush=True,
            )

            try:
                extracted = await _extract_pages_via_view_raw(page, expected)
                if len(extracted) == expected and all(e["text"] for e in extracted):
                    pages = [
                        {
                            "originalPage": page_offset + i + 1,
                            "content": e["text"],
                            "raw": e["raw"],
                        }
                        for i, e in enumerate(extracted)
                    ]
                    print(
                        f"    [{chunk_index}/{total_chunks}] {label}: extracted {len(pages)} page(s) via View Raw",
                        flush=True,
                    )
                    return pages, None
            except Exception as exc:
                print(
                    f"    [{chunk_index}/{total_chunks}] {label}: View Raw extract failed ({exc}), falling back to DOM",
                    flush=True,
                )

            dom_pages = await _extract_pages_from_dom(page, page_offset)
            if dom_pages:
                print(
                    f"    [{chunk_index}/{total_chunks}] {label}: extracted {len(dom_pages)} page(s) via DOM fallback",
                    flush=True,
                )
                return dom_pages, None

            raise RuntimeError("No pages extracted (both View Raw and DOM failed)")

        except Exception as exc:
            err = f"attempt {attempt}/{MAX_RETRIES}: {exc}"
            print(
                f"    [{chunk_index}/{total_chunks}] {label}: FAILED ({err})",
                flush=True,
            )
            if attempt < MAX_RETRIES:
                await asyncio.sleep(3)
        finally:
            try:
                await page.close()
            except Exception:
                pass

    return [], "All retries exhausted"


async def process_all_chunks(
    browser, chunks: list[dict], concurrency: int
) -> tuple[list[dict], list[str]]:
    sem = asyncio.Semaphore(concurrency)
    warnings: list[str] = []
    all_pages: list[dict] = []
    lock = asyncio.Lock()
    total = len(chunks)

    async def worker(chunk: dict, idx: int) -> None:
        async with sem:
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080}
            )
            try:
                pages, warn = await _process_chunk(context, chunk, idx, total)
            finally:
                try:
                    await context.close()
                except Exception:
                    pass
        async with lock:
            all_pages.extend(pages)
            if warn:
                warnings.append(f"{chunk['start_page']}-{chunk['end_page']}: {warn}")

    await asyncio.gather(*(worker(c, i) for i, c in enumerate(chunks, 1)))
    return all_pages, warnings


# ==============================================================================
# Output writing
# ==============================================================================


def _clean_text(text: str) -> str:
    lines = text.split("\n")
    return "\n".join(s.strip() for s in lines if s.strip() and len(s.strip()) > 3)


def _dedupe_lines(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        n = line.strip().lower()
        if n and n not in seen and len(line.strip()) > 20:
            seen.add(n)
            out.append(line.strip())
    return out


def save_results(
    output_dir: str,
    all_pages: list[dict],
    pdf_path: str,
    concurrency: int,
    pages_per_chunk: int,
) -> dict:
    all_pages = sorted(all_pages, key=lambda x: x["originalPage"])
    combined = _clean_text("\n\n".join(p["content"] for p in all_pages))
    all_lines: list[str] = []
    for p in all_pages:
        all_lines.extend(p["content"].split("\n"))
    unique = _dedupe_lines(all_lines)

    output = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "sourcePdf": os.path.basename(pdf_path),
            "method": "olmOCR with PDF splitting (parallel, View Raw extraction)",
            "concurrency": concurrency,
            "pagesPerChunk": pages_per_chunk,
            "outputDirectory": output_dir,
        },
        "content": {
            "pages": [
                {"originalPage": p["originalPage"], "content": p["content"]}
                for p in all_pages
            ],
            "combinedText": combined,
            "structuredLines": unique,
        },
        "stats": {
            "totalPages": len(all_pages),
            "uniqueLines": len(unique),
            "totalCharacters": len(combined),
        },
    }
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "ocr-result.json"), "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    with open(os.path.join(output_dir, "ocr-result.txt"), "w", encoding="utf-8") as f:
        for p in all_pages:
            f.write(f"=== Page {p['originalPage']} ===\n")
            f.write(p["content"])
            f.write("\n\n")
    with open(os.path.join(output_dir, "run-info.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": datetime.now().isoformat(),
                "pdfFile": pdf_path,
                "outputDirectory": output_dir,
                "pagesExtracted": len(all_pages),
                "concurrency": concurrency,
                "pagesPerChunk": pages_per_chunk,
                "method": "olmOCR Split & Combine (parallel)",
            },
            f,
            indent=2,
        )
    return output


def cleanup_temp() -> None:
    for f in Path(TEMP_DIR).glob("*.pdf"):
        try:
            f.unlink()
        except OSError:
            pass


# ==============================================================================
# Main
# ==============================================================================


async def amain() -> int:
    print("=" * 64, flush=True)
    print("olmOCR Full PDF Extraction (Split & Combine, Parallel)", flush=True)
    print("=" * 64, flush=True)
    print(f"PDF          : {PDF_PATH}", flush=True)
    print(f"Chunk size   : {PAGES_PER_CHUNK} pages", flush=True)
    print(f"Concurrency  : {CONCURRENCY} parallel browser context(s)", flush=True)
    print("=" * 64, flush=True)

    if not os.path.exists(PDF_PATH):
        print(f"ERROR: PDF not found at {PDF_PATH}", flush=True)
        return 1

    reader = PdfReader(PDF_PATH)
    total_pages = len(reader.pages)
    print(f"Total pages in PDF: {total_pages}", flush=True)

    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    output_dir = os.path.join(BASE_OUTPUT_DIR, f"run-{timestamp}-split-combine")
    os.makedirs(output_dir, exist_ok=True)
    print(f"Output dir   : {output_dir}\n", flush=True)

    print(f"[1/3] Splitting PDF into {PAGES_PER_CHUNK}-page chunks...", flush=True)
    chunks = split_pdf(PDF_PATH, PAGES_PER_CHUNK)
    for c in chunks:
        print(
            f"  chunk: pages {c['start_page']}-{c['end_page']} ({c['page_count']} pages)",
            flush=True,
        )
    print(f"      Created {len(chunks)} chunks\n", flush=True)

    print(
        f"[2/3] Processing {len(chunks)} chunk(s) with concurrency={CONCURRENCY}...",
        flush=True,
    )
    t0 = time.monotonic()
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        try:
            all_pages, warnings = await process_all_chunks(browser, chunks, CONCURRENCY)
        finally:
            try:
                await browser.close()
            except Exception:
                pass
    elapsed = time.monotonic() - t0
    print(
        f"      Done in {elapsed:.1f}s ({elapsed / max(1, len(chunks)):.1f}s/chunk avg)",
        flush=True,
    )
    for w in warnings:
        print(f"      WARN: {w}", flush=True)

    print(f"\n[3/3] Saving combined results...", flush=True)
    output = save_results(output_dir, all_pages, PDF_PATH, CONCURRENCY, PAGES_PER_CHUNK)
    cleanup_temp()

    print("\n" + "=" * 64, flush=True)
    print("Complete!", flush=True)
    print("=" * 64, flush=True)
    print(f"Output          : {output_dir}", flush=True)
    print(f"Wall time       : {elapsed:.1f}s", flush=True)
    print(
        f"Pages extracted : {output['stats']['totalPages']}/{total_pages}", flush=True
    )
    print(f"Unique lines    : {output['stats']['uniqueLines']}", flush=True)
    print(f"Total characters: {output['stats']['totalCharacters']}", flush=True)
    print("=" * 64, flush=True)

    if all_pages:
        print("\nFirst page preview:", flush=True)
        print("-" * 40, flush=True)
        print(all_pages[0]["content"][:400], flush=True)
        print("-" * 40, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))

"""
Hierarchical chunking: chia PDF thành 3 cấp độ + trích xuất metadata tài liệu.

  Cấp 1 (level=1): Document Summary — 1 chunk/file, chứa mục lục + đoạn mở đầu
  Cấp 2 (level=2): Section chunks — nhóm đoạn văn theo heading, tối đa 1024 token
  Cấp 3 (level=3): Paragraph chunks — 256 token, có overlap, dùng cho trích dẫn chính xác

Trả về: (list[Chunk], DocMeta) — DocMeta chứa title, category, page_count, TOC có số trang.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

import pdfplumber
from transformers import AutoTokenizer

from config import EMBEDDING_MODEL

_tokenizer = AutoTokenizer.from_pretrained(EMBEDDING_MODEL)

CHUNK_SIZE_L2 = 1024
CHUNK_SIZE_L3 = 256
CHUNK_OVERLAP_L3 = 40


@dataclass
class DocMeta:
    title: str          # Tên hiển thị (có thể khác tên file)
    category: str       # Phân loại tài liệu
    page_count: int     # Tổng số trang
    toc: list[dict]     # [{"heading": str, "page": int}, ...]
    summary: str = ""   # Tóm tắt 3-5 câu (DeepSeek)
    topics: list[str] = field(default_factory=list)  # Từ khóa chủ đề (DeepSeek)


@dataclass
class Chunk:
    text: str
    source_file: str
    page_start: int
    page_end: int
    chunk_index: int
    level: int = 3          # 1=doc summary, 2=section, 3=paragraph
    heading: str = ""
    metadata: dict = field(default_factory=dict)


def _token_len(text: str) -> int:
    return len(_tokenizer.encode(text, add_special_tokens=True))


def _is_heading(text: str) -> bool:
    if len(text) > 120 or len(text) < 3:
        return False
    if text[-1] in ".!?,;:":
        return False
    patterns = [
        r"^(chương|phần|mục|bài|chapter|section|part)\s+\w",
        r"^\d+[\.\)]\s+\S",
        r"^[IVXLC]+\.\s+\S",
        r"^[A-ZÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚĂĐĨŨƠƯẠẶ]{3,}",
    ]
    return any(re.match(p, text, re.IGNORECASE) for p in patterns)



def _guess_title(source_name: str, first_paragraphs: list[tuple[str, int, bool]]) -> str:
    """Đoán tiêu đề từ tên file, ưu tiên heading đầu tiên nếu ngắn và rõ ràng."""
    for text, _, is_h in first_paragraphs[:10]:
        if is_h and 5 < len(text) < 100:
            return text
    # Fallback: tên file bỏ extension, thay _ và - bằng khoảng trắng
    name = Path(source_name).stem
    return re.sub(r"[_\-]+", " ", name).strip()


def _configure_tesseract() -> None:
    """Trỏ pytesseract tới tesseract.exe + set TESSDATA_PREFIX về backend/tessdata.
    Tránh truyền --tessdata-dir qua config string vì path có space sẽ bị escape sai.
    """
    import os
    import pytesseract

    # 1. Tìm tesseract.exe
    cmd = pytesseract.pytesseract.tesseract_cmd or ""
    if not os.path.exists(cmd):
        for candidate in [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            r"/opt/homebrew/bin/tesseract",
            r"/usr/bin/tesseract",
            r"/usr/local/bin/tesseract",
        ]:
            if os.path.exists(candidate):
                pytesseract.pytesseract.tesseract_cmd = candidate
                break

    # 2. Set TESSDATA_PREFIX về backend/tessdata (chứa vie + eng)
    project_tessdata = Path(__file__).parent / "tessdata"
    if (project_tessdata / "vie.traineddata").exists():
        os.environ["TESSDATA_PREFIX"] = str(project_tessdata)


_TESS_INITIALIZED = False


def _ocr_page(pdf_path: Path, page_num: int) -> str:
    """OCR 1 trang PDF bằng PyMuPDF + pytesseract (không cần poppler)."""
    try:
        import fitz  # PyMuPDF
        import pytesseract
        from PIL import Image
        import io

        doc = fitz.open(str(pdf_path))
        page = doc[page_num - 1]
        pix = page.get_pixmap(dpi=200)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        doc.close()

        text = pytesseract.image_to_string(img, lang="vie+eng")
        logger.debug("OCR trang %d: %d ký tự", page_num, len(text))
        return text
    except Exception as e:
        logger.warning("OCR trang %d thất bại: %s", page_num, e)
        return ""


def _extract_text_pymupdf(pdf_path: Path, page_num: int) -> str:
    """Dùng PyMuPDF để extract text — xử lý được nhiều encoding hơn pdfplumber."""
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        text = doc[page_num - 1].get_text()
        doc.close()
        return text or ""
    except Exception as e:
        logger.warning("PyMuPDF trang %d thất bại: %s", page_num, e)
        return ""


def _append_text_blocks(
    paragraphs: list[tuple[str, int, bool]],
    raw: str,
    page_num: int,
) -> None:
    blocks = re.split(r"\n{2,}", raw.strip())
    for block in blocks:
        block = block.strip().replace("\n", " ")
        block = re.sub(r" {2,}", " ", block)
        if len(block) > 2:
            paragraphs.append((block, page_num, _is_heading(block)))


def _extract_paragraphs_pymupdf(pdf_path: Path) -> tuple[list[tuple[str, int, bool]], int]:
    """Fallback toàn file bằng PyMuPDF khi pdfplumber/pdfminer không mở được PDF."""
    paragraphs: list[tuple[str, int, bool]] = []
    try:
        import fitz

        doc = fitz.open(str(pdf_path))
        page_count = doc.page_count
        for idx in range(page_count):
            page_num = idx + 1
            raw = doc[idx].get_text() or ""
            if not raw.strip():
                raw = _ocr_page(pdf_path, page_num)
            _append_text_blocks(paragraphs, raw, page_num)
        doc.close()
        return paragraphs, page_count
    except Exception as e:
        logger.warning("PyMuPDF toàn file thất bại: %s", e)
        return paragraphs, 0


def _extract_paragraphs(pdf_path: Path) -> tuple[list[tuple[str, int, bool]], int]:
    """Trả về (danh sách đoạn văn, số trang).
    Thứ tự ưu tiên: pdfplumber → PyMuPDF → OCR (pytesseract).
    """
    paragraphs: list[tuple[str, int, bool]] = []
    page_count = 0
    try:
        with pdfplumber.open(pdf_path) as pdf:
            page_count = len(pdf.pages)
            for page_num, page in enumerate(pdf.pages, start=1):
                raw = page.extract_text() or ""
                if not raw.strip():
                    raw = _extract_text_pymupdf(pdf_path, page_num)
                if not raw.strip():
                    raw = _ocr_page(pdf_path, page_num)
                _append_text_blocks(paragraphs, raw, page_num)
    except Exception as e:
        logger.warning("pdfplumber không đọc được %s, chuyển sang PyMuPDF: %s", pdf_path.name, e)
        return _extract_paragraphs_pymupdf(pdf_path)
    return paragraphs, page_count


def chunk_pdf_hierarchical(pdf_path: Path, source_name: str) -> tuple[List[Chunk], DocMeta]:
    """
    Chia PDF thành chunks 3 cấp + trích xuất DocMeta (title, category, TOC).
    Trả về (chunks, doc_meta).
    """
    paragraphs, page_count = _extract_paragraphs(pdf_path)
    if not paragraphs:
        meta = DocMeta(title=Path(source_name).stem, category="Tài liệu khác", page_count=0, toc=[])
        return [], meta

    all_chunks: List[Chunk] = []

    # ── Trích xuất TOC (heading + số trang) ───────────────────────────────────
    toc: list[dict] = []
    seen_headings: set[str] = set()
    for text, page, is_h in paragraphs:
        if is_h and text not in seen_headings:
            toc.append({"heading": text, "page": page})
            seen_headings.add(text)

    # ── Đoạn giới thiệu (để đoán category) ───────────────────────────────────
    intro_parts: list[str] = []
    pending = False
    for p, _, is_h in paragraphs:
        if is_h:
            pending = True
        elif pending:
            intro_parts.append(p[:300])
            pending = False
            if len(intro_parts) >= 5:
                break
    intro_text = "\n".join(intro_parts)

    fallback_title = _guess_title(source_name, paragraphs)

    # Gọi DeepSeek để tóm tắt + phân loại (1 lần/file)
    from doc_enrich import enrich_document
    enriched = enrich_document(source_name, fallback_title, intro_text, toc)
    title = enriched["title"]
    category = enriched["category"]
    summary = enriched["summary"]
    topics = enriched["topics"]

    doc_meta = DocMeta(
        title=title,
        category=category,
        page_count=page_count,
        toc=toc,
        summary=summary,
        topics=topics,
    )

    # ── Cấp 1: Document Summary (1 chunk/file) ────────────────────────────────
    toc_lines = " | ".join(
        f"{item['heading']} (tr.{item['page']})" for item in toc[:30]
    ) if toc else "(không phát hiện mục lục)"

    topics_line = ", ".join(topics) if topics else "(chưa xác định)"
    summary_line = summary or intro_text[:600]

    l1_text = (
        f"[TÀI LIỆU: {source_name}]\n"
        f"Tiêu đề: {title}\n"
        f"Phân loại: {category}\n"
        f"Chủ đề chính: {topics_line}\n"
        f"Số trang: {page_count}\n"
        f"Tóm tắt: {summary_line}\n"
        f"Mục lục: {toc_lines}"
    )
    all_chunks.append(Chunk(
        text=l1_text,
        source_file=source_name,
        page_start=paragraphs[0][1],
        page_end=paragraphs[-1][1],
        chunk_index=0,
        level=1,
        heading="",
    ))

    # ── Cấp 2: Section chunks (theo heading) ─────────────────────────────────
    sections: list[tuple[str, list[tuple[str, int]]]] = []
    cur_heading = ""
    cur_paras: list[tuple[str, int]] = []
    for p, page, is_h in paragraphs:
        if is_h:
            if cur_paras or cur_heading:
                sections.append((cur_heading, cur_paras))
            cur_heading = p
            cur_paras = []
        else:
            cur_paras.append((p, page))
    if cur_paras or cur_heading:
        sections.append((cur_heading, cur_paras))

    l2_idx = 0
    for heading, paras in sections:
        prefix = f"[{heading}]\n" if heading else ""
        prefix_tokens = _token_len(prefix)
        cur_texts: list[str] = []
        cur_pages: list[int] = []
        cur_tokens = 0

        def flush_l2() -> None:
            nonlocal l2_idx, cur_texts, cur_pages, cur_tokens
            if not cur_texts:
                return
            text = prefix + " ".join(cur_texts)
            all_chunks.append(Chunk(
                text=text,
                source_file=source_name,
                page_start=cur_pages[0],
                page_end=cur_pages[-1],
                chunk_index=l2_idx,
                level=2,
                heading=heading,
            ))
            l2_idx += 1
            cur_texts.clear()
            cur_pages.clear()
            cur_tokens = 0

        for p, page in paras:
            pt = _token_len(p)
            if prefix_tokens + cur_tokens + pt > CHUNK_SIZE_L2:
                flush_l2()
            cur_texts.append(p)
            cur_pages.append(page)
            cur_tokens += pt
        flush_l2()

    # ── Cấp 3: Paragraph chunks (256 token, có overlap) ──────────────────────
    all_chunks.extend(_chunk_paragraphs_l3(paragraphs, source_name))

    return all_chunks, doc_meta


def _chunk_paragraphs_l3(
    paragraphs: list[tuple[str, int, bool]],
    source_name: str,
) -> List[Chunk]:
    chunks: List[Chunk] = []
    cur_texts: list[str] = []
    cur_pages: list[int] = []
    cur_tokens = 0
    chunk_idx = 0
    cur_heading = ""

    def flush(overlap: list[tuple[str, int]]) -> None:
        nonlocal chunk_idx, cur_texts, cur_pages, cur_tokens
        if not cur_texts:
            return
        body = " ".join(cur_texts)
        text = f"[{cur_heading}] {body}" if cur_heading else body
        chunks.append(Chunk(
            text=text,
            source_file=source_name,
            page_start=cur_pages[0],
            page_end=cur_pages[-1],
            chunk_index=chunk_idx,
            level=3,
            heading=cur_heading,
        ))
        chunk_idx += 1
        cur_texts[:] = [p for p, _ in overlap]
        cur_pages[:] = [pg for _, pg in overlap]
        cur_tokens = sum(_token_len(p) for p in cur_texts)

    for para, page, is_heading in paragraphs:
        if is_heading:
            cur_heading = para

        pt = _token_len(para)
        if pt > CHUNK_SIZE_L3:
            for sent in re.split(r"(?<=[.!?])\s+", para):
                st = _token_len(sent)
                if cur_tokens + st > CHUNK_SIZE_L3:
                    flush(_tail_overlap(cur_texts, cur_pages, CHUNK_OVERLAP_L3))
                cur_texts.append(sent)
                cur_pages.append(page)
                cur_tokens += st
        else:
            if cur_tokens + pt > CHUNK_SIZE_L3:
                flush(_tail_overlap(cur_texts, cur_pages, CHUNK_OVERLAP_L3))
            cur_texts.append(para)
            cur_pages.append(page)
            cur_tokens += pt

    flush([])
    return chunks


def _tail_overlap(texts: list[str], pages: list[int], limit: int) -> list[tuple[str, int]]:
    result = []
    tokens = 0
    for text, page in zip(reversed(texts), reversed(pages)):
        t = _token_len(text)
        if tokens + t > limit:
            break
        result.append((text, page))
        tokens += t
    return list(reversed(result))

"""Манипуляции с PDF-файлами: нарезка/склейка страниц, сжатие, конвертация, детекция сканов."""
import os
import re
import asyncio
import cv2
import numpy as np
import io
import json
import uuid
import shutil
import logging
import subprocess
import tempfile
import docx
from pypdf import PdfReader
import pikepdf
import img2pdf
from pdf2image import convert_from_path
from google import genai
from google.genai import types
from rapidfuzz import fuzz
from pptx import Presentation
import fitz
from PIL import Image

ALLOWED_WORK_TYPES = ["ЛР", "ПЗ", "КР", "КП", "ИЗ", "СРС", "ДКР", "СР", "ПР", "УП", "ПП"]
from text_helpers import normalize_text

async def extract_page_texts(file_bytes: bytes) -> list:
    temp_dir = f"/tmp/extract_{uuid.uuid4().hex}"
    os.makedirs(temp_dir, exist_ok=True)
    pdf_path = os.path.join(temp_dir, "temp.pdf")
    try:
        with open(pdf_path, "wb") as f:
            f.write(file_bytes)
        doc = fitz.open(pdf_path)
        pages = []
        for page_num in range(len(doc)):
            text = doc[page_num].get_text()
            pages.append((page_num + 1, normalize_text(text)))
        doc.close()
        return pages
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

def get_page_start_text(reader, page_num: int, words_count: int = 50) -> str:
    if page_num >= len(reader.pages):
        return ""
    return normalize_text(reader.pages[page_num].extract_text() or "")

# ─── PDF / файловые операции ──────────────────────────────

def split_pdf_to_single_pages(input_path: str, output_dir: str) -> list:
    parts = []
    with pikepdf.Pdf.open(input_path) as pdf:
        for i, page in enumerate(pdf.pages):
            new_pdf = pikepdf.Pdf.new()
            new_pdf.pages.append(page)
            out_name = os.path.join(output_dir, f"page_{i}.pdf")
            new_pdf.save(out_name)
            parts.append(out_name)
    return parts

def merge_to_one_pdf(file_paths: list, output_path: str):
    new_pdf = pikepdf.Pdf.new()
    for path in file_paths:
        ext = os.path.splitext(path)[1].lower()
        if ext in ('.jpg', '.jpeg', '.png'):
            with open(path, "rb") as img_f:
                pdf_bytes = img2pdf.convert(img_f.read())
            tmp = path + "_tmp.pdf"
            with open(tmp, "wb") as f:
                f.write(pdf_bytes)
            with pikepdf.Pdf.open(tmp) as p:
                new_pdf.pages.extend(p.pages)
            os.remove(tmp)
        else:
            with pikepdf.Pdf.open(path) as p:
                new_pdf.pages.extend(p.pages)
    new_pdf.save(output_path)

def replace_specific_pages(orig_path: str, replacements: dict, out_path: str):
    with pikepdf.Pdf.open(orig_path) as orig:
        new_pdf = pikepdf.Pdf.new()
        skip_until = -1
        for i, page in enumerate(orig.pages):
            if i < skip_until:
                continue
            if i in replacements:
                scan_path = replacements[i]
                with pikepdf.Pdf.open(scan_path) as scan:
                    for sp in scan.pages:
                        new_pdf.pages.append(sp)
                    skip_until = i + len(scan.pages)
            else:
                new_pdf.pages.append(page)
        new_pdf.save(out_path)

async def compress_pdf(input_path: str, output_path: str):
    proc = await asyncio.create_subprocess_exec(
        'gs', '-sDEVICE=pdfwrite', '-dCompatibilityLevel=1.4',
        '-dPDFSETTINGS=/screen', '-dNOPAUSE', '-dQUIET', '-dBATCH',
        f'-sOutputFile={output_path}', input_path
    )
    await proc.communicate()

# ─── ОСНОВНАЯ ФУНКЦИЯ КОНВЕРТАЦИИ (без изменения имени и инфалтера) ─────

async def convert_to_pdf(input_path: str, output_dir: str) -> str:
    ext = os.path.splitext(input_path)[1].lower()
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    output_path = os.path.join(output_dir, f"{base_name}.pdf")

    # Если уже PDF – возвращаем как есть
    if ext == '.pdf':
        return input_path

    # Изображения конвертируем через img2pdf
    if ext in ('.jpg', '.jpeg', '.png'):
        with open(input_path, "rb") as img_f, open(output_path, "wb") as pdf_f:
            pdf_f.write(img2pdf.convert(img_f.read()))
        return output_path

    # Для всех офисных документов (DOCX, PPTX, PPT, ODT и др.)
    # Создаём уникальный изолированный профиль для каждой задачи
    unique_id = uuid.uuid4().hex
    unique_profile = os.path.join(tempfile.gettempdir(), f"lo_profile_{unique_id}")

    cmd = [
        'soffice',
        f'-env:UserInstallation=file://{unique_profile}',
        '--headless',
        '--invisible',
        '--nofirststartwizard',
        '--nolockcheck',
        '--nologo',
        '--norestore',
        '--convert-to', 'pdf',
        '--outdir', output_dir,
        input_path
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            err_msg = stderr.decode(errors='ignore') if stderr else "Неизвестная ошибка LibreOffice"
            raise Exception(f"Ошибка конвертации (код {proc.returncode}): {err_msg}")

        if os.path.exists(output_path):
            return output_path
        else:
            raise Exception(f"Файл PDF не был найден по ожидаемому пути: {output_path}")

    finally:
        # Очищаем временный профиль
        if os.path.exists(unique_profile):
            shutil.rmtree(unique_profile, ignore_errors=True)

def detect_scanned_pages(file_path: str, coverage_threshold: float = 0.85, max_pages: int = 3) -> list:
    """Возвращает список номеров страниц (начиная с 1), которые являются сканами."""
    scanned_pages = []
    try:
        with fitz.open(file_path) as doc:
            total_pages = min(len(doc), max_pages)
            logging.info(f"🔍 [SCAN DETECT] Анализ PDF: {file_path} (первые {total_pages} стр.)")
            for page_num in range(total_pages):
                try:
                    page = doc[page_num]
                    page_area = page.rect.width * page.rect.height
                    images = page.get_images(full=True)
                    is_scan = False

                    for img in images:
                        xref = img[0]
                        try:
                            rects = page.get_image_rects(xref)
                            for rect in rects:
                                coverage = (rect.width * rect.height) / page_area
                                if coverage > coverage_threshold:
                                    logging.info(f"    ❌ Страница {page_num+1}: покрытие {coverage:.1%} > {coverage_threshold:.0%} → СКАН")
                                    is_scan = True
                                    break
                            if is_scan:
                                break
                        except Exception as e:
                            logging.warning(f"    - Ошибка обработки xref {xref} на стр {page_num+1}: {e}")
                    if is_scan:
                        scanned_pages.append(page_num + 1)
                    else:
                        logging.info(f"    ✅ Страница {page_num+1}: НЕ скан")
                except Exception as e:
                    logging.warning(f"    - Ошибка при обработке страницы {page_num+1}: {e}")
            logging.info(f"🔍 [SCAN DETECT] Итог: найдено {len(scanned_pages)} сканов из {total_pages} проверенных")
    except Exception as e:
        logging.error(f"❌ Ошибка при анализе PDF: {e}")
    return scanned_pages
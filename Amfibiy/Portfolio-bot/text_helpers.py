"""Общие текстовые хелперы: unicode-safety, нормализация, fuzzy-сравнение."""
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

def safe_unicode(text: str) -> str:
    if not isinstance(text, str):
        text = str(text)
    try:
        return text.encode('utf-8', errors='replace').decode('utf-8')
    except Exception:
        return ''.join(ch if ord(ch) < 0xd800 or ord(ch) > 0xdfff else '?' for ch in text)

def clean_text_for_parsing(text: str) -> str:
    replacements = {
        'A': 'А', 'B': 'В', 'C': 'С', 'E': 'Е', 'H': 'Н', 'K': 'К',
        'M': 'М', 'O': 'О', 'P': 'Р', 'T': 'Т', 'X': 'Х',
        'a': 'а', 'c': 'с', 'e': 'е', 'o': 'о', 'p': 'р', 'x': 'х',
        '\u0391': 'А', '\u0392': 'В', '\u0395': 'Е', '\u039f': 'О',
        '\u03b1': 'а', '\u03bf': 'о'
    }

    def _repl_latin_run(match: "re.Match") -> str:
        run = match.group(0)
        # Если это цельная последовательность из 2+ латинских букв — скорее всего настоящее
        # английское слово/аббревиатура (WEB, PDF, JavaScript и т.п.), а не спутанная при OCR
        # кириллица. Такие слова не трогаем, иначе они перестают совпадать с оригиналом в БД
        # (например, "WEB-технологии" превращалось в "WЕВ-технологии" с кириллическими Е/В).
        if len(run) >= 2:
            return run
        return replacements.get(run, run)

    # Заменяем похожие латинские буквы на кириллические только для ОДИНОЧНЫХ вкраплений —
    # именно так выглядит типичная OCR-путаница внутри кириллического слова.
    text = re.sub(r'[A-Za-z]+', _repl_latin_run, text)
    for bad, good in {'\u0391': 'А', '\u0392': 'В', '\u0395': 'Е', '\u039f': 'О',
                       '\u03b1': 'а', '\u03bf': 'о'}.items():
        text = text.replace(bad, good)
    text = re.sub(r'№\s*[зЗzZ]', '№3', text)
    text = re.sub(r'№\s*[lIіІi]', '№1', text)
    return text

def normalize_text(text: str) -> str:
    if not isinstance(text, str):
        text = str(text)
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r' \[ Image \d+ \] ', '', text)
    return safe_unicode(text.strip())

def compare_texts_fuzzy(text1: str, text2: str) -> float:
    if not text1 or not text2:
        return 0.0
    t1 = " ".join(text1.lower().split()[:50])
    t2 = " ".join(text2.lower().split()[:50])
    return fuzz.token_sort_ratio(t1, t2)
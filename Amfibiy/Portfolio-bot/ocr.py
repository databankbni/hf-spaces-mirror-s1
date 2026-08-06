"""OCR и распознавание: нативное извлечение текста, Gemini OCR, детекция подписи."""
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

def enhance_image(image_bytes: bytes) -> bytes:
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=4.5, tileGridSize=(8, 8))
    cl = clahe.apply(l_channel)
    limg = cv2.merge((cl, a_channel, b_channel))
    enhanced = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
    gaussian = cv2.GaussianBlur(enhanced, (0, 0), 3)
    final_img = cv2.addWeighted(enhanced, 1.5, gaussian, -0.5, 0)
    _, encoded_img = cv2.imencode('.jpg', final_img, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    return encoded_img.tobytes()

def is_review_page(text: str) -> bool:
    if not text:
        return False
    text_lower = text.lower()
    return "отзыв руководителя" in text_lower

def _is_text_readable(text: str, min_words: int = 15) -> bool:
    if not text or len(text.strip()) < 30:
        return False
    cyrillic = len(re.findall(r'[а-яА-ЯёЁ]', text))
    words = sum(1 for w in text.split() if len(w) > 2)
    return cyrillic >= 8 and words >= min_words

def get_page_text_native(pdf_path: str) -> str:
    try:
        doc = fitz.open(pdf_path)
        if len(doc) > 0:
            text = doc[0].get_text()
            return text.replace('\u00A0', ' ') if text else ""
        return ""
    except Exception as e:
        logging.error(f"get_page_text_native error: {e}")
        return ""

async def perform_ocr(pdf_scan_path: str) -> str:
    logging.info(f"OCR через Gemini: {pdf_scan_path}")
    try:
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            return ""
        images = convert_from_path(pdf_scan_path, dpi=300, first_page=1, last_page=1, fmt='jpeg')
        if not images:
            return ""
        buf = io.BytesIO()
        images[0].save(buf, format='JPEG', quality=95)
        image_bytes = enhance_image(buf.getvalue())

        ai_client = genai.Client(api_key=api_key)
        prompt = (
            "Ты выполняешь OCR титульного листа учебного отчёта российского вуза. "
            "Перепиши то, что написано — символ за символом, без подгонки под шаблон.\n\n"
            "Справка о типичном виде полей:\n"
            "— Шифр группы: буквы‑цифры‑буква (например ПЕ-41Б). Перепиши как есть.\n"
            "— ФИО автора: фамилия + инициалы. КРИТИЧЕСКИ ВАЖНО: перепиши фамилию "
            "ТОЧНО так, как она написана на листе, даже если она выглядит непривычно, "
            "нестандартно или похожа на опечатку. НЕ подменяй её на похожую существующую "
            "или более распространённую фамилию. Транслитерация и «исправление» под "
            "known-фамилии запрещены — нужна дословная транскрипция символов.\n"
            "— Название дисциплины: полностью, без кавычек.\n"
            "— Тип работы: ЛР/ПЗ/КР/КП/ИЗ/СРС/ДКР/СР/ПР или полное название.\n"
            "— Номер работы (только цифры); для КР и КП номер обычно отсутствует.\n"
            "— Кафедра: строка после слова 'Кафедра' в любом регистре.\n\n"
            "Неразборчивые поля оставь пустыми. "
            "Для каждого поля укажи уверенность от 0.0 до 1.0."
        )
        ocr_schema = types.Schema(
            type=types.Type.OBJECT,
            properties={
                "group":       types.Schema(type=types.Type.STRING),
                "author":      types.Schema(type=types.Type.STRING),
                "subject":     types.Schema(type=types.Type.STRING),
                "work_type":   types.Schema(type=types.Type.STRING),
                "work_number": types.Schema(type=types.Type.STRING),
                "department":  types.Schema(type=types.Type.STRING,
                                            description="Название кафедры полностью"),
                "confidence":  types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "group":     types.Schema(type=types.Type.NUMBER),
                        "author":    types.Schema(type=types.Type.NUMBER),
                        "subject":   types.Schema(type=types.Type.NUMBER),
                        "work_type": types.Schema(type=types.Type.NUMBER),
                    }
                ),
            },
            required=["group", "author", "subject", "work_type", "work_number"]
        )

        response = await asyncio.wait_for(
            ai_client.aio.models.generate_content(
                model='gemini-3.1-flash-lite',
                contents=[types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg'), prompt],
                config=types.GenerateContentConfig(
                    media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH,
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=ocr_schema,
                )
            ),
            timeout=30
        )

        if response.text:
            try:
                res_json = json.loads(response.text)
                conf = res_json.get('confidence') or {}
                low = [f for f, c in conf.items() if isinstance(c, (int, float)) and c < 0.6]
                if low:
                    logging.warning(f"Низкая уверенность OCR: {low} → {conf}")
                dept_val = res_json.get('department') or ''
                return (
                    f"Группа: {res_json.get('group') or ''}\n"
                    f"Выполнил студент: {res_json.get('author') or ''}\n"
                    f"По дисциплине: {res_json.get('subject') or ''}\n"
                    f"Тип работы: {res_json.get('work_type') or ''}\n"
                    f"Номер: {res_json.get('work_number') or ''}\n"
                    f"Кафедра: {dept_val}"
                )
            except Exception as e:
                logging.error(f"Ошибка парсинга JSON OCR: {e}")
                return response.text
        return ""
    except asyncio.TimeoutError:
        logging.error("OCR timeout (30 сек)")
        return ""
    except Exception as e:
        logging.error(f"OCR error: {e}")
        return ""

async def extract_raw_text_gemini(pdf_path: str) -> str:
    try:
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            return ""
        images = convert_from_path(pdf_path, dpi=300, first_page=1, last_page=1, fmt='jpeg')
        if not images:
            return ""
        buf = io.BytesIO()
        images[0].save(buf, format='JPEG', quality=95)
        image_bytes = enhance_image(buf.getvalue())
        return await _gemini_raw_text(image_bytes)
    except asyncio.TimeoutError:
        logging.error("Gemini Raw Text timeout")
        return ""
    except Exception as e:
        logging.error(f"Gemini Raw Text error: {e}")
        return ""

async def extract_raw_text_gemini_from_bytes(image_bytes: bytes) -> str:
    try:
        return await _gemini_raw_text(image_bytes)
    except Exception as e:
        logging.error(f"Gemini Raw Text (bytes) error: {e}")
        return ""

async def _gemini_raw_text(image_bytes: bytes) -> str:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return ""
    ai_client = genai.Client(api_key=api_key)
    prompt = (
        "Распознай и напиши весь текст на этой странице. Без комментариев и форматирования. "
        "Транскрибируй дословно, символ в символ — включая имена, фамилии и другие слова, "
        "даже если они выглядят непривычно или как опечатка. НЕ исправляй их на более "
        "«правильные», известные или ожидаемые варианты — это сломает последующее "
        "текстовое сравнение (rapidfuzz) с ранее сохранённым текстом той же работы."
    )
    response = await asyncio.wait_for(
        ai_client.aio.models.generate_content(
            model='gemini-3.1-flash-lite',
            contents=[types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg'), prompt],
            config=types.GenerateContentConfig(
                media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH,
                temperature=0.0,
            )
        ),
        timeout=30
    )
    return response.text if response.text else ""

async def get_scan_page_text(page_pdf_path: str, page_idx: int, cache: dict, gemini_used: dict) -> str:
    if page_pdf_path in cache:
        return cache[page_pdf_path]

    native = await asyncio.to_thread(get_page_text_native, page_pdf_path)
    if _is_text_readable(native):
        result = normalize_text(native)
        gemini_used[page_pdf_path] = False
        cache[page_pdf_path] = result
        return result

    gemini_text = await extract_raw_text_gemini(page_pdf_path)
    result = normalize_text(gemini_text)
    gemini_used[page_pdf_path] = True
    cache[page_pdf_path] = result
    return result

async def get_page_text_robust(pdf_path: str, force_gemini: bool = False) -> str:
    try:
        native = get_page_text_native(pdf_path)
        if not force_gemini and _is_text_readable(native):
            return normalize_text(native)
        gemini_text = await extract_raw_text_gemini(pdf_path)
        return normalize_text(gemini_text)
    except Exception as e:
        logging.error(f"get_page_text_robust error: {e}")
        return ""

# ─── Вспомогательные функции (без изменений) ────────────────

async def detect_signature_async(text: str, file_bytes: bytes = None) -> tuple[bool, str, str]:
    """
    Проверяет наличие рукописной подписи на титульном листе.
    Возвращает (True/False, причина, детали).
    Причины: 'hard_marker', 'opencv_roi', 'gemini_vision', 'opencv_override', 'gemini_none', 'none'
    """
    if not text:
        text = ""

    text_lower = text.lower()

    # ----- 1. Жёсткие текстовые маркеры (только явные рукописные пометки) -----
    hard_markers = ["зачтено", "отлично", "хорошо", "удовлетворительно", "неудовлетворительно"]
    for marker in hard_markers:
        if marker in text_lower:
            for line in text.split('\n'):
                if marker in line.lower():
                    return True, "hard_marker", f"Найден маркер '{marker}' в строке: {line.strip()}"
            return True, "hard_marker", f"Найден маркер '{marker}' в тексте"

    # Инициализируем переменные заранее, чтобы они были гарантированно доступны при любых сбоях
    gemini_roi_bytes = None
    anchor_type = "default"
    found_anchor = None
    total_area = 0  

    # ----- 2. Локальный анализ ROI с маскированием печатного текста -----
    if file_bytes is not None:
        try:
            with fitz.open(stream=file_bytes, filetype="pdf") as doc:
                if len(doc) == 0:
                    return False, "none", "Пустой PDF"

                page = doc[0]
                width, height = page.rect.width, page.rect.height

                # --- 2.1 Находим якоря и определяем выровненный горизонтальный ROI ---
                anchors = ["екатеринбург", "проверил", "руководитель", "преподаватель"]
                target_rect = None

                words = page.get_text("words")
                for anchor in anchors:
                    for w in words:
                        if anchor in w[4].lower():
                            inst = fitz.Rect(w[0], w[1], w[2], w[3])
                            if anchor == "екатеринбург":
                                # Область строго НАД городом на ВСЮ ширину листа (от 0 до width)
                                y0 = max(0, inst.y0 - 240)
                                y1 = min(height, inst.y1 + 15)
                                target_rect = fitz.Rect(0, y0, width, y1)
                                anchor_type = "city"
                            else:
                                # Огромный запас ВВЕРХ (-340) и на ВСЮ ширину листа (от 0 до width)
                                y0 = max(0, inst.y0 - 340)
                                y1 = min(height, inst.y1 + 120)
                                target_rect = fitz.Rect(0, y0, width, y1)
                                anchor_type = "teacher"
                            found_anchor = anchor
                            break
                    if target_rect:
                        break

                # --- 2.2 Если якорь не найден, берем нижнюю треть страницы по умолчанию ---
                if target_rect is None:
                    target_rect = fitz.Rect(0, height * 0.7, width, height)
                    anchor_type = "default"

                # --- 2.3 Надежный и быстрый рендеринг строго по выровненной рамке ---
                scale = 2  # Увеличение четкости (DPI ~ 150)
                mat = fitz.Matrix(scale, scale)
                
                pix = page.get_pixmap(matrix=mat, clip=target_rect)
                
                # Сохраняем чистые байты фрагмента для Gemini
                gemini_roi_bytes = pix.tobytes("jpeg")
                
                # Создаем массив для OpenCV
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                roi = cv2.cvtColor(np.array(img.convert('RGB')), cv2.COLOR_RGB2BGR)

                if roi.size != 0:
                    # --- 2.4 Стабильное маскирование печатных слов внутри ROI ---
                    words_in_roi = page.get_text("words", clip=target_rect)
                    
                    # Не зажимаем сильно отступ, оставляем баланс 2 пикселя для зоны преподавателя
                    padding = 2 if anchor_type == "teacher" else 3
                    
                    for w in words_in_roi:
                        # Локальные координаты внутри кропа с учетом смещения target_rect
                        x0 = int((w[0] - target_rect.x0) * scale)
                        y0 = int((w[1] - target_rect.y0) * scale)
                        x1 = int((w[2] - target_rect.x0) * scale)
                        y1 = int((w[3] - target_rect.y0) * scale)
                        
                        cv2.rectangle(roi, (x0 - padding, y0 - padding),
                                      (x1 + padding, y1 + padding), (255, 255, 255), -1)

                    # --- 2.5 Анализ оставшихся контуров штрихов ---
                    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                    _, binary = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY_INV)
                    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

                    total_area = sum(cv2.contourArea(cnt) for cnt in contours if cv2.contourArea(cnt) > 15)

                    # Динамический порог уверенности: для зоны препода (где текст съедает подпись) планка ниже
                    confidence_threshold = 100 if anchor_type == "teacher" else 200

                    # Если штрихов много — OpenCV заявляет True БЕЗ сомнений и без вызова Gemini
                    if total_area > confidence_threshold:
                        return True, "opencv_roi", f"OpenCV: обнаружены штрихи площадью {total_area:.0f} пкс в зоне '{anchor_type}' (порог {confidence_threshold}, якорь: {found_anchor})"
                    
                    # Если область идеально чистая — подписи точно нет, экономим баланс
                    if total_area == 0:
                        return False, "opencv_empty", f"Локально: область '{anchor_type}' абсолютно пустая"
                    
                    logging.info(f"OpenCV сомневается ({total_area:.0f} пкс). Передаю фрагмент в каскад Gemini...")

        except Exception as e:
            logging.warning(f"Локальный OpenCV анализ упал: {e}")

    # ----- 3. Резервный шаг (Fallback): Визуальный анализ через Gemini (с каскадом моделей) -----
    if gemini_roi_bytes is not None:
        try:
            api_key = os.environ.get("GOOGLE_API_KEY")
            if not api_key:
                if total_area > 50:
                    return True, "opencv_override", f"Аппаратный апрув (нет API_KEY): OpenCV зафиксировал штрихи ({total_area:.0f} пкс)"
                return False, "none", "OpenCV не подтвердил, а GOOGLE_API_KEY отсутствует"

            ai_client = genai.Client(api_key=api_key)
            
            prompt = (
                "Ты — строгий эксперт по верификации документов. Перед тобой фрагмент титульного листа отчёта.\n"
                "Определи, есть ли на нём РУКОПИСНЫЕ ПОМЕТКИ, сделанные ручкой от руки (подписи, даты, отметки 'okey').\n"
                "Внимательно осмотри области рядом с именами преподавателей и линиями бланка.\n"
                "Ответь строго в формате JSON:\n"
                "{\n"
                "  \"signature_detected\": true или false,\n"
                "  \"comment\": \"Описание\"\n"
                "}"
            )

            signature_schema = types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "signature_detected": types.Schema(type=types.Type.BOOLEAN),
                    "comment":            types.Schema(type=types.Type.STRING),
                },
                required=["signature_detected", "comment"]
            )

            # Каскад моделей: если 3.5-flash упирается в лимиты или зависает, код пробует 3.1-flash-lite
            models_to_try = ['gemini-3.5-flash', 'gemini-3.1-flash-lite']
            response = None
            used_model = None

            for model_name in models_to_try:
                try:
                    logging.info(f"Отправляю запрос в модель {model_name}...")
                    response = await asyncio.wait_for(
                        ai_client.aio.models.generate_content(
                            model=model_name,
                            contents=[types.Part.from_bytes(data=gemini_roi_bytes, mime_type='image/jpeg'), prompt],
                            config=types.GenerateContentConfig(
                                media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH,
                                temperature=0.15,
                                response_mime_type="application/json",
                                response_schema=signature_schema,
                            )
                        ),
                        timeout=15  # Таймаут 15 секунд на модель, чтобы быстрее переключиться на резервную
                    )
                    if response and response.text:
                        used_model = model_name
                        break  # Ответ успешно получен, выходим из цикла каскада
                except Exception as model_err:
                    logging.warning(f"Модель {model_name} выдала ошибку или таймаут: {model_err}. Переключаюсь на следующую...")
                    continue

            # Если ни одна модель из списка не смогла отдать текст
            if not response or not response.text:
                raise RuntimeError("Все доступные модели Gemini вернули ошибку или таймаут")

            # Разбор ответа успешной модели
            res_json = json.loads(response.text)
            is_detected = res_json.get("signature_detected", False)
            comment = res_json.get("comment", "Без комментариев")
            
            if is_detected:
                return True, "gemini_vision", f"[{used_model}] обнаружил подпись: {comment} (зона: {anchor_type})"
            else:
                if total_area > 50:
                    return True, "opencv_override", f"Аппаратный апрув: {used_model} вернула False, но OpenCV зафиксировал штрихи ({total_area:.0f} пкс)"
                return False, "gemini_none", f"[{used_model}] зафиксировал отсутствие подписи: {comment}"

        except Exception as gemini_err:
            logging.error(f"Полный сбой резервного шага Gemini (все модели упали): {gemini_err}")
            # Железная страховка: если упали лимиты или сеть, но пиксели контуров в заначке есть — одобряем!
            if total_area > 50:
                logging.warning(f"Сбой всех нейросетей, но OpenCV спасает ситуацию (площадь {total_area:.0f} пкс). Подпись одобрена.")
                return True, "opencv_override", f"Аппаратный апрув (тотальный сбой API): OpenCV зафиксировал штрихи ({total_area:.0f} пкс) в зоне '{anchor_type}'"

    return False, "none", "Подпись не обнаружена (все этапы проверки не дали результата)"
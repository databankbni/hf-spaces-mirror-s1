import os
import re
import shutil
import asyncio
import logging
import uuid
import traceback
from datetime import datetime
from aiogram import Bot
from aiogram.types import FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
import db
import utils
from batch_queues import state_manager, processing_queue   # <-- убрана точка
from bson.objectid import ObjectId
from rapidfuzz import fuzz

def _get_words(text: str) -> set:
    return set(re.findall(r'[а-яА-Яa-zA-Z]{5,}', text.lower()))


# Локальные функции (без изменений)
async def download_file_with_retry(bot, file_path: str, destination: str, retries: int = 3, delay: float = 2.0):
    last_error = None
    for attempt in range(retries):
        try:
            await bot.download_file(file_path, destination)
            return
        except Exception as e:
            last_error = e
            logging.warning(f"Ошибка скачивания (попытка {attempt+1}/{retries}): {e}")
            if os.path.exists(destination):
                try:
                    os.remove(destination)
                except Exception:
                    pass
            if attempt < retries - 1:
                await asyncio.sleep(delay * (attempt + 1))
    raise last_error


async def try_link_presentations(tg_id: int, work_metadata: dict, work_ids: list):
    """Сравнивает новую работу со всеми презентациями и обновляет их best_match_score."""
    presentations = await db.get_all_presentations(tg_id)
    if not presentations or not work_ids:
        return

    first_work_id = work_ids[0]
    new_work_full_text = await db.get_work_full_text(first_work_id)
    if not new_work_full_text:
        new_work_full_text = work_metadata.get('raw_text', '')

    # Метаданные новой работы
    new_work_group = (work_metadata.get('group') or '').lower().replace('-', '')
    new_work_subject = (work_metadata.get('subject') or '').lower()
    new_work_full_subject = (work_metadata.get('full_subject') or '').lower()
    new_work_authors = work_metadata.get('authors', [])
    new_author_surnames = []
    for auth in new_work_authors:
        surname = auth.split()[0].lower() if auth else ''
        if surname:
            new_author_surnames.append(surname)

    for pres in presentations:
        pres_id = pres['_id']
        pres_full_text = await db.get_work_full_text(pres_id)
        if not pres_full_text:
            pres_full_text = pres.get('raw_text', '')

        # Базовое сравнение текстов
        score = fuzz.WRatio(pres_full_text, new_work_full_text)

        # Бонус за общие слова
        common_words = _get_words(pres_full_text) & _get_words(new_work_full_text)
        score += len(common_words) * 2

        # ---------- БОНУСЫ ЗА МЕТАДАННЫЕ (усиленные) ----------
        pres_lower = pres_full_text.lower()

        # 1. Авторы
        matched_authors = 0
        author_bonus = 0
        for surname in new_author_surnames:
            if surname in pres_lower:
                author_bonus += 30
                matched_authors += 1
        if matched_authors >= 3:
            author_bonus += 50
        score += author_bonus

        # 2. Предмет
        subject_bonus = 0
        if new_work_full_subject and new_work_full_subject in pres_lower:
            subject_bonus += 30
        elif new_work_subject and new_work_subject in pres_lower:
            subject_bonus += 20
        score += subject_bonus

        # 3. Группа
        group_bonus = 0
        if new_work_group and new_work_group in pres_lower:
            group_bonus += 15
        score += group_bonus

        # 4. ДОПОЛНИТЕЛЬНЫЙ БОНУС ЗА СОВПАДЕНИЕ МЕТАДАННЫХ (если они есть в презентации)
        pres_subject = (pres.get('subject') or '').lower()
        pres_full_subject = (pres.get('full_subject') or '').lower()
        pres_group = (pres.get('group') or '').lower().replace('-', '')
        if pres_subject and pres_subject == new_work_subject:
            score += 50
        elif pres_full_subject and pres_full_subject == new_work_full_subject:
            score += 40
        if pres_group and pres_group == new_work_group:
            score += 30
        # Совпадение авторов (по фамилиям)
        pres_authors = pres.get('authors', [])
        if pres_authors and new_work_authors:
            for pa in pres_authors:
                pa_surname = pa.split()[0].lower() if pa else ''
                if pa_surname and pa_surname in new_author_surnames:
                    score += 40
                    break

        logging.info(f"🔗 Сравнение презентации {pres['filename']} с новой работой: итого={score}, авторов={matched_authors}, subject={subject_bonus}, group={group_bonus}")

        # update_presentation_best_match сам сравнивает score с уже сохранённым best_match_score
        # и обновляет best_match_score/best_work_id только если score оказался выше. Раньше на этом
        # всё и заканчивалось — реальные метаданные (subject/group/authors/linked_work_ids) при этом
        # НЕ обновлялись, поэтому в конце очереди презентация могла показывать best_work_id/score от
        # самой релевантной работы, а метаданные — от первой, более слабой (например, score=261.5),
        # которая успела привязаться раньше через link_presentation_to_works. Теперь при каждом новом
        # максимуме сразу копируем метаданные лучшей на данный момент работы — так после обработки
        # всей очереди презентация гарантированно останется привязана именно к работе с максимальным
        # баллом, а не к первой, прошедшей какой-то условный порог.
        is_new_best = await db.update_presentation_best_match(pres_id, first_work_id, score)
        if is_new_best:
            best_work_doc = await db.get_work_by_id(first_work_id)
            if best_work_doc:
                await link_presentation_to_all_authors(pres_id, best_work_doc, score)
                logging.info(f"🔗 Презентация {pres['filename']}: обновлена привязка к более релевантной работе {best_work_doc.get('filename')} (score={score})")


async def link_presentation_to_works(pres_id: ObjectId, tg_id: int):
    """Находит лучшую существующую работу для презентации с учётом метаданных."""
    pres = await db.get_work_by_id(pres_id)
    if not pres:
        logging.warning(f"Презентация {pres_id} не найдена")
        return

    pres_full_text = await db.get_work_full_text(pres_id)
    if not pres_full_text:
        pres_full_text = pres.get('raw_text', '')

    # Извлекаем метаданные презентации (безопасно)
    pres_subject = pres.get('subject')
    pres_full_subject = pres.get('full_subject')
    pres_group = pres.get('group')
    pres_authors = pres.get('authors', [])

    # ---------- ФИЛЬТРАЦИЯ КАНДИДАТОВ ----------
    candidate_works = []
    if pres_subject:
        candidate_works = await db.get_works_by_subject(tg_id, pres_subject)
        if not candidate_works and pres_full_subject:
            all_works = await db.get_all_user_works(tg_id)
            candidate_works = [w for w in all_works if (w.get('full_subject') or '').lower() == pres_full_subject.lower()]
        if not candidate_works and pres_group:
            all_works = await db.get_all_user_works(tg_id)
            candidate_works = [w for w in all_works if w.get('group') == pres_group]
    elif pres_group:
        all_works = await db.get_all_user_works(tg_id)
        candidate_works = [w for w in all_works if w.get('group') == pres_group]

    if not candidate_works:
        candidate_works = await db.get_all_user_works(tg_id)

    if not candidate_works:
        logging.info(f"ℹ️ Для презентации {pres['filename']} нет работ для сравнения")
        return

    best_score = 0
    best_work = None

    for work in candidate_works:
        if work['_id'] == pres_id:
            continue
        if work.get('is_presentation', False):
            continue

        work_full_text = await db.get_work_full_text(work['_id'])
        if not work_full_text:
            work_full_text = work.get('raw_text', '')

        # Базовое сравнение
        score = fuzz.WRatio(pres_full_text, work_full_text)

        # Бонус за общие слова
        common_words = _get_words(pres_full_text) & _get_words(work_full_text)
        score += len(common_words) * 2

        # ---------- БОНУСЫ ЗА МЕТАДАННЫЕ ----------
        pres_lower = pres_full_text.lower()
        work_authors = work.get('authors', [work.get('author')])
        matched_authors = 0
        author_bonus = 0
        for auth in work_authors:
            surname = auth.split()[0].lower() if auth else ''
            if surname and surname in pres_lower:
                author_bonus += 30
                matched_authors += 1
        if matched_authors >= 3:
            author_bonus += 50
        score += author_bonus

        work_subject = (work.get('subject') or '').lower()
        work_full_subject = (work.get('full_subject') or '').lower()
        if work_full_subject and work_full_subject in pres_lower:
            score += 30
        elif work_subject and work_subject in pres_lower:
            score += 20

        work_group = (work.get('group') or '').lower().replace('-', '')
        if work_group and work_group in pres_lower:
            score += 15

        # ---------- ДОПОЛНИТЕЛЬНЫЙ БОНУС ЗА СОВПАДЕНИЕ МЕТАДАННЫХ ----------
        if pres_subject:
            if pres_subject.lower() == (work.get('subject') or '').lower():
                score += 50
            elif pres_full_subject and pres_full_subject.lower() == (work.get('full_subject') or '').lower():
                score += 40
        if pres_group and pres_group == work.get('group'):
            score += 30
        if pres_authors and work_authors:
            for pa in pres_authors:
                for wa in work_authors:
                    if fuzz.ratio(pa.lower(), wa.lower()) > 80:
                        score += 40
                        break

        if score > best_score:
            best_score = score
            best_work = work

    if best_work and best_score > 60:
        # Раньше здесь только сохранялся best_match_score/best_work_id, но метаданные
        # презентации (group/subject/author и т.д.) так и оставались плейсхолдерами
        # ("Предмет", "РАБ" и т.п.). Теперь подтягиваем их от самой подходящей работы.
        await link_presentation_to_all_authors(pres_id, best_work, best_score)
        logging.info(f"🔗 Презентация {pres['filename']}: привязана к работе {best_work['filename']} (score={best_score}), метаданные скопированы")
    else:
        logging.info(f"ℹ️ Презентация {pres['filename']} не привязана (лучший score={best_score})")


async def link_presentation_to_all_authors(presentation_id, best_work, best_score):
    fs, _, works_collection = db.get_fs_and_collections()
    file_id = best_work.get('file_id')
    if not file_id:
        return

    cursor = works_collection.find({"file_id": file_id})
    all_works = await cursor.to_list(length=None)
    if not all_works:
        return

    work_ids = [w['_id'] for w in all_works]
    first_work = all_works[0]
    metadata = {
        "group": first_work.get("group"),
        "author": first_work.get("author"),
        "authors": first_work.get("authors", []),
        "subject": first_work.get("subject"),
        "full_subject": first_work.get("full_subject"),
        "work_type": first_work.get("work_type"),
        "work_number": first_work.get("work_number"),
        "department": first_work.get("department"),
    }

    await works_collection.update_one(
        {"_id": presentation_id},
        {"$set": {
            "linked_work_ids": work_ids,
            "best_work_id": best_work['_id'],
            "best_match_score": best_score,
            **metadata,
            "updated_at": datetime.utcnow()
        }}
    )


async def background_work_processing(bot: Bot, task: dict):
    chat_id = task['chat_id']
    user_id = task['user_id']
    msg_id = task['msg_id']
    file_path = task['file_path']
    original_filename = task['orig_filename']

    if not file_path:
        await bot.edit_message_text(chat_id=chat_id, message_id=msg_id,
                                    text="❌ Ошибка: путь к файлу не передан.")
        return

    task_dir = os.path.dirname(file_path)
    input_path = file_path

    try:
        if os.path.getsize(input_path) < 1000:
            await bot.edit_message_text(chat_id=chat_id, message_id=msg_id,
                                        text="❌ Файл скачан не полностью (меньше 1 КБ).")
            return

        logging.info(f"📥 Принят файл: {original_filename}")
        notification_parts = []

                # ----- ПРЕЗЕНТАЦИИ -----
        if input_path.lower().endswith(('.pptx', '.ppt')):
            logging.info("📝 Презентация – конвертация в PDF и извлечение метаданных")
            pdf_path = await utils.convert_to_pdf(input_path, task_dir)
            with open(pdf_path, "rb") as f:
                file_bytes = f.read()
            pages_text = await utils.extract_page_texts(file_bytes)
            full_text = " ".join([text for _, text in pages_text])

            # ---- Сначала пробуем найти совпадающую работу по агрегированному поиску текста
            # (как было в исходной, не разделённой на модули версии) — это надёжнее, чем
            # извлекать метаданные из самой презентации, где их часто нет или они неточные.
            work_id, _ = await db.find_work_by_aggregated_content(
                user_id,
                full_text,
                hint_group=None,
                hint_author=None,
                is_review_page=False
            )
            parsed = None
            if work_id:
                work = await db.get_work_by_id(work_id)
                if work:
                    parsed = {
                        "group": work.get("group"),
                        "author": work.get("author"),
                        "authors": work.get("authors", [work.get("author")]),
                        "subject": work.get("subject"),
                        "full_subject": work.get("full_subject", work.get("subject")),
                        "work_type": "РАБ",
                        "work_number": work.get("work_number"),
                        "department": work.get("department"),
                    }
                    if not parsed["authors"]:
                        parsed["authors"] = [work.get("author") or "Неизвестный автор"]
                    logging.info(f"🔍 Презентация привязана к работе {work_id} по тексту (авторы: {parsed['authors']})")

            # ---- Если по тексту работу не нашли — извлекаем метаданные из самой презентации (как раньше) ----
            if not parsed:
                # ---- ИЗВЛЕКАЕМ МЕТАДАННЫЕ ИЗ ТЕКСТА ПРЕЗЕНТАЦИИ ----
                parsed = utils.extract_metadata(pdf_path, full_text, is_presentation=True)

                # Дополнительные попытки извлечь группу, предмет, авторов, если extract_metadata не помогла
                if not parsed.get("group"):
                    grp_match = re.search(r'(?:гр\.?|группа)\s*([А-ЯЁA-Z]{2,4}[-\s]?\d{2,4}[А-ЯЁA-Z]?)', full_text, re.IGNORECASE)
                    if grp_match:
                        parsed["group"] = grp_match.group(1).upper().replace(" ", "-")
                if not parsed.get("subject") or parsed["subject"] == "Предмет":
                    subj_match = re.search(r'(?:по\s+дисциплине|по\s+предмету|на\s+тему)\s*[«"]*([^»"\n]{5,100})', full_text, re.IGNORECASE)
                    if subj_match:
                        parsed["subject"] = subj_match.group(1).strip()
                        parsed["full_subject"] = parsed["subject"]
                    else:
                        parsed["subject"] = "Предмет"
                        parsed["full_subject"] = "Предмет"
                if not parsed.get("authors"):
                    authors = utils.extract_authors(full_text)
                    if authors:
                        parsed["authors"] = authors
                        parsed["author"] = authors[0]
                    else:
                        parsed["authors"] = ["Неизвестный автор"]
                        parsed["author"] = "Неизвестный автор"
                parsed["work_type"] = "РАБ"
                parsed["work_number"] = ""
                logging.info(f"🔍 Презентация не привязана по тексту, метаданные извлечены из самой презентации: группа={parsed.get('group')}, предмет={parsed.get('subject')}, авторы={parsed.get('authors')}")

            # Сохраняем презентацию с этими метаданными
            original_pdf_name = os.path.splitext(original_filename)[0] + ".pdf"
            with open(pdf_path, "rb") as f:
                file_bytes = f.read()

            parsed.pop('filename', None)
            work_ids = await db.save_digital_work(
                parsed, file_bytes, user_id,
                selected_authors='all',
                custom_filename=original_pdf_name,
                status="digital_only",
                is_presentation=True
            )
            if work_ids:
                state_manager.queue_file_for_zip_batch(bot, user_id, chat_id, pdf_path, original_pdf_name, kind="work")
                await bot.edit_message_text(chat_id=chat_id, message_id=msg_id,
                                            text=f"✅ Успешно сохранена презентация: {original_pdf_name}")
                # Привязка к работам (теперь будет искать по своим метаданным)
                await link_presentation_to_works(work_ids[0], user_id)
            else:
                await bot.edit_message_text(chat_id=chat_id, message_id=msg_id,
                                            text="❌ Ошибка сохранения презентации.")
            return

        # ----- ОБЫЧНЫЕ ДОКУМЕНТЫ -----
        if input_path.lower().endswith('.docx'):
            logging.info("📝 DOCX – прямой разбор до конвертации")
            parsed = await utils.parse_title_page(input_path)
            try:
                pdf_path = await utils.convert_to_pdf(input_path, task_dir)
            except Exception:
                alt_name = os.path.join(task_dir, f"doc_{uuid.uuid4().hex}.docx")
                os.rename(input_path, alt_name)
                pdf_path = await utils.convert_to_pdf(alt_name, task_dir)
        elif input_path.lower().endswith('.pdf'):
            logging.info("📝 PDF – разбор слоя")
            pdf_path = input_path
            parsed = await utils.parse_title_page(pdf_path)
        else:
            logging.info("📝 Другой формат – конвертация в PDF")
            pdf_path = await utils.convert_to_pdf(input_path, task_dir)
            parsed = await utils.parse_title_page(pdf_path)

        # ---------- ИНИЦИАЛИЗАЦИЯ АВТОРОВ ----------
        if not parsed.get('authors'):
            parsed['authors'] = ["Неизвестный автор"]
        if not parsed.get('author'):
            parsed['author'] = parsed['authors'][0]

        # ---------- ИЗВЛЕЧЕНИЕ ДАННЫХ ИЗ ИМЕНИ ФАЙЛА ----------
        name_group = None
        name_author = None
        name_subject = None
        name_work_type = None
        name_number = None

        filename_check = utils.check_filename_format(original_filename)
        if filename_check.get("valid", False):
            name_parsed = filename_check.get("parsed", {})
            name_group = name_parsed.get("group")
            name_author = name_parsed.get("author")
            name_subject = name_parsed.get("subject")
            name_work_type = name_parsed.get("work_type")
            name_number = name_parsed.get("work_number")
        else:
            grp_match = re.search(r'([А-ЯЁA-Z]{2,4}[_\-\s]?\d{2,4}[А-ЯЁA-Z]?)', original_filename, re.IGNORECASE)
            if grp_match:
                name_group = grp_match.group(1).upper().replace(" ", "-")
                if not re.match(r'^[А-ЯЁA-Z]{2,4}[-\s]?\d{2,4}[А-ЯЁA-Z]?$', name_group, re.IGNORECASE):
                    name_group = None
            auth_match = re.search(r'([А-ЯЁ][а-яё]+)\s*([А-ЯЁ])\.?\s*([А-ЯЁ])?\.?', original_filename)
            if auth_match:
                name_author = f"{auth_match.group(1)} {auth_match.group(2)}{auth_match.group(3) or ''}".replace('.', '')
            for wt in utils.ALLOWED_WORK_TYPES:
                if f"_{wt}" in original_filename or f"_{wt.lower()}" in original_filename:
                    name_work_type = wt
                    break
            num_match = re.search(r'(?:ПЗ|ЛР|ИЗ|СРС|ДКР|СР|УП|ПП)\s*(\d+)', original_filename, re.IGNORECASE)
            if num_match:
                name_number = num_match.group(1)

        # ---------- ФИЛЬТРАЦИЯ АВТОРОВ ----------
        if parsed.get('authors'):
            filtered = []
            for a in parsed['authors']:
                if re.search(r'[А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.?[А-ЯЁ]?\.?', a):
                    filtered.append(a)
                else:
                    logging.info(f"Исключён возможный преподаватель/мусор из авторов: {a}")
            if filtered:
                parsed['authors'] = filtered
                parsed['author'] = filtered[0]
            else:
                logging.warning("Все авторы отфильтрованы – будет использован автор из имени или 'Неизвестный автор'")
                parsed['authors'] = []
                parsed['author'] = None

        # ---------- НОРМАЛИЗАЦИЯ ГРУППЫ ----------
        if not name_group and parsed.get("group"):
            group_text = parsed["group"]
            group_text = re.sub(r'(гр\.?|группа|group)\s*', '', group_text, flags=re.IGNORECASE).strip()
            if re.match(r'^[А-ЯЁA-Z]{2,4}[-\s]?\d{2,4}[А-ЯЁA-Z]?$', group_text, re.IGNORECASE):
                parsed["group"] = utils.clean_group_name(group_text)
            else:
                logging.info(f"Группа из текста '{group_text}' не соответствует формату, игнорируем")
                parsed["group"] = None

        # ---------- ПОИСК ПРЕДМЕТА ----------
        raw_text = parsed.get("raw_text", "")
        subject_match = None
        for pattern in [
            r'(?:по\s+дисциплине|по\s+дис\s*циплине|по\s+предмету|на\s+тему)\s*[«"]*([^»"\n]{3,120})',
            r'дисциплине\s*[«"]*([^»"\n]{3,120})',
        ]:
            m = re.search(pattern, raw_text, re.IGNORECASE)
            if m:
                subject_match = m.group(1).strip().strip('»"«"')
                break
        if subject_match:
            parsed["full_subject"] = subject_match
            parsed["subject"] = utils.get_subject_abbreviation(subject_match) if len(subject_match.split()) > 1 else subject_match
        elif not parsed.get("subject") or parsed["subject"] == "Предмет":
            parsed["subject"] = "Предмет"
            parsed["full_subject"] = "Предмет"

        # ---------- ОБЪЕДИНЕНИЕ ДАННЫХ ----------
        if name_group and name_group != "БЕЗ_ГРУППЫ":
            parsed["group"] = name_group.upper()
        else:
            if not parsed.get("group") or parsed["group"] == "БЕЗ_ГРУППЫ":
                parsed["group"] = None

        if name_work_type:
            wt = name_work_type.upper()
            if wt == "ПР":
                wt = "ПЗ"
            if wt in utils.ALLOWED_WORK_TYPES:
                parsed["work_type"] = wt

        if parsed.get("work_type") in [None, "", "РАБ"]:
            parsed["work_number"] = None
            name_number = None

        if parsed.get("work_type") not in [None, "", "РАБ", "КР", "КП"]:
            if name_number:
                parsed["work_number"] = name_number
            elif not parsed.get("work_number"):
                num_match = re.search(r'(?:работа|лр|пз|лабораторная|практическая)[\s:]*(?:№|номер)?[\s:]*(\d+)', raw_text, re.IGNORECASE)
                if num_match:
                    parsed["work_number"] = num_match.group(1)
        else:
            parsed["work_number"] = None

        if name_author:
            norm_name = utils.clean_author_name(name_author)
            existing = any(utils.clean_author_name(a) == norm_name for a in parsed.get("authors", []))
            if not existing:
                parsed["authors"].append(name_author)
            parsed["author"] = name_author
        else:
            if parsed.get("authors"):
                parsed["author"] = parsed["authors"][0]
            else:
                parsed["authors"] = ["Неизвестный автор"]
                parsed["author"] = "Неизвестный автор"

        if parsed.get("authors"):
            seen = set()
            unique = []
            for a in parsed["authors"]:
                norm = utils.clean_author_name(a)
                if norm not in seen:
                    seen.add(norm)
                    unique.append(a)
            parsed["authors"] = unique
            if not parsed.get("author") and unique:
                parsed["author"] = unique[0]

        authors = parsed.get("authors", [])

        # ---------- ПРОВЕРКА ДУБЛИКАТОВ ----------
        existing_work = await db.find_exact_work(parsed, user_id)
        if existing_work:
            replaced_pages = existing_work.get("replaced_pages", [])
            if replaced_pages:
                notification_parts.append(f"ℹ️ В работе уже есть заменённые страницы: {', '.join(map(str, replaced_pages))}")

            dup_key = f"dup_{user_id}_{uuid.uuid4().hex[:8]}"
            state_manager.temp_work_data[dup_key] = {
                'work': existing_work,
                'parsed': parsed,
                'chat_id': chat_id,
                'msg_id': msg_id,
                'task_dir': task_dir,
                'is_duplicate': True
            }

            authors_list = existing_work.get('authors', [])
            if len(authors_list) > 1:
                full_subject = existing_work.get('full_subject') or existing_work.get('subject') or 'неизвестный предмет'
                info = f"Найдена работа по предмету \"{full_subject}\" с несколькими авторами"
            else:
                info = f"Найдена работа: {existing_work.get('filename')}"

            builder = InlineKeyboardBuilder()
            builder.button(text="✅ Да", callback_data=f"dup_confirm:{dup_key}:yes")
            builder.button(text="❌ Нет", callback_data=f"dup_confirm:{dup_key}:no")
            builder.adjust(2)
            state_manager.register_menu(user_id)
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=f"⚠️ {info}\n\nДобавить работу в архив?",
                reply_markup=builder.as_markup()
            )
            return

        # ---------- ДЕТЕКЦИЯ СКАНОВ ----------
        scanned_pages_list = await asyncio.to_thread(utils.detect_scanned_pages, pdf_path)
        is_merged = len(scanned_pages_list) > 0
        status = "merged" if is_merged else "digital_only"
        parsed['replaced_pages'] = scanned_pages_list

        # ---------- ПРОВЕРКА ПОДПИСИ ----------
        if is_merged:
            try:
                with open(pdf_path, "rb") as f:
                    file_bytes_full = f.read()
                pages_text = await utils.extract_page_texts(file_bytes_full)
                first_page_text = pages_text[0][1] if pages_text else ""
                if not first_page_text:
                    first_page_text = parsed.get("raw_text", "")
            except Exception as e:
                logging.warning(f"Не удалось извлечь текст первой страницы: {e}")
                first_page_text = parsed.get("raw_text", "")

            with open(pdf_path, "rb") as f:
                file_bytes_for_check = f.read()

            has_signature, reason, detail = await utils.detect_signature_async(first_page_text, file_bytes_for_check)
            if has_signature:
                logging.info(f"✅ Подпись найдена (причина: {reason}) — {detail}")
                notification_parts.append("✅ <b>Подпись найдена!</b>")
            else:
                logging.warning(f"❌ Подпись не обнаружена (причина: {reason}) — {detail}")
                notification_parts.append("⚠️ <b>Внимание!</b>\nНа титульном листе не обнаружена подпись, оценка или дата. Проверьте, что работа подписана.")
        else:
            logging.info("📄 Цифровая работа (без сканов) – проверка подписи не требуется.")

        # ---------- ДОПОЛНИТЕЛЬНАЯ ОБРАБОТКА ДЛЯ MERGED ----------
        if is_merged:
            notification_parts.append(f"📎 Обнаружены сканированные страницы.\nКоманда /add_scan не требуется.")
            if (not parsed.get("group") or parsed["group"] == "БЕЗ_ГРУППЫ") and name_group:
                parsed["group"] = name_group.upper()
            if (not parsed.get("author") or parsed["author"] == "Автор") and name_author:
                parsed["author"] = name_author
                if not parsed.get("authors"):
                    parsed["authors"] = [name_author]
            if (not parsed.get("subject") or parsed["subject"] == "Предмет") and name_subject:
                parsed["subject"] = name_subject
                parsed["full_subject"] = name_subject
        else:
            notification_parts.append("📄 Работа без скана, подпись не проверяется.")
            
        if is_merged and (not parsed.get("group") or not parsed.get("author") or not parsed.get("subject")):
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text="⚠️ Не удалось распознать титульный лист скана.\n\n"
                     "Пожалуйста, пришлите другой скан с более чётким титулом или отправьте работу без скана через /add_work."
            )
            return

        # ---------- ГЕНЕРАЦИЯ ИМЕНИ ----------
        if len(authors) > 1:
            # Финальное имя всё равно будет сгенерировано отдельно для каждого автора
            # в db.save_digital_work — здесь переименовывать преждевременно и бессмысленно
            final_filename = original_filename
            notification_parts.append("⏳ <b>Подождите, формируется меню выбора автора...</b>")
        else:
            can_generate = (
                parsed.get("group") and parsed.get("group") != "БЕЗ_ГРУППЫ" and
                parsed.get("author") and parsed.get("author") != "Автор" and
                parsed.get("subject") and parsed.get("subject") != "Предмет" and
                parsed.get("work_type") and parsed.get("work_type") in utils.ALLOWED_WORK_TYPES
            )

            if can_generate:
                generated_name = utils.generate_safe_filename(parsed, specific_author=parsed.get("author"))
                orig_base = os.path.splitext(original_filename)[0].lower()
                gen_base = os.path.splitext(generated_name)[0].lower()
                if gen_base != orig_base:
                    final_filename = generated_name
                    notification_parts.append(f"🔄 Автоматически переименовано в:\n<code><b>{final_filename}</b></code>")
                else:
                    final_filename = original_filename
                    notification_parts.append("📌 Название файла правильное, данные совпали.")
            else:
                final_filename = original_filename
                notification_parts.append("⚠️ Не удалось автоматически переименовать файл.\nСохранено с исходным именем.")

        status_text = "\n\n".join(notification_parts) if notification_parts else None

        if len(authors) > 1:
            if status_text:
                await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=status_text, parse_mode="HTML")
        else:
            await bot.delete_message(chat_id, msg_id)
            if status_text:
                await bot.send_message(chat_id=chat_id, text=status_text, parse_mode="HTML")

        # ---------- СОХРАНЕНИЕ ----------
        with open(pdf_path, "rb") as f:
            file_bytes = f.read()

        if len(authors) == 1:
            work_ids = await db.save_digital_work(
                parsed, file_bytes, user_id,
                selected_authors=None,
                custom_filename=final_filename,
                status=status
            )
            if work_ids:
                neutral_path = os.path.join(task_dir, "output.pdf")
                if os.path.exists(pdf_path) and pdf_path != neutral_path:
                    os.rename(pdf_path, neutral_path)
                state_manager.queue_file_for_zip_batch(bot, user_id, chat_id, neutral_path, final_filename, kind="work")
                await try_link_presentations(user_id, parsed, work_ids)
            else:
                await bot.send_message(chat_id=chat_id, text="❌ Ошибка сохранения.")
            return

        # ---------- Несколько авторов ----------
        parsed.pop('filename', None)
        work_ids = await db.save_digital_work(
            parsed, file_bytes, user_id,
            selected_authors='all',
            custom_filename=None,
            status=status
        )
        if not work_ids:
            await bot.send_message(chat_id=chat_id, text="❌ Ошибка сохранения.")
            return

        await try_link_presentations(user_id, parsed, work_ids)

        state_manager.temp_work_data[user_id] = {
            'work_ids': work_ids,
            'authors_list': authors,
            'metadata': parsed,
            'chat_id': chat_id,
            'msg_id': msg_id,
            'task_dir': task_dir,
            'final_filename': final_filename
        }

        builder = InlineKeyboardBuilder()
        for idx, author in enumerate(authors):
            builder.button(text=author, callback_data=f"author_work_sel:{idx}")
        builder.button(text="✅ Всех", callback_data="author_work_sel:all")
        builder.button(text="❌ Закрыть", callback_data="author_work_sel:close")
        builder.adjust(2)

        state_manager.register_menu(user_id)
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text="🔍 <b>Распознано несколько авторов.</b>\nВыберите, для кого сохранить работу:",
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )
        state_manager.temp_work_data[user_id]['menu_msg_id'] = msg_id
        asyncio.create_task(state_manager._send_menu_reminder(bot, chat_id, user_id))

    except Exception as e:
        logging.error(f"Work processing error:\n{traceback.format_exc()}")
        try:
            await bot.send_message(chat_id=chat_id, text=f"❌ Ошибка: {str(e) if str(e) else 'смотрите логи'}")
        except Exception:
            pass
    finally:
        state_manager.dec_processing(user_id)
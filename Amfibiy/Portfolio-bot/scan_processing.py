import os
import re
import hashlib
import uuid
import asyncio
import logging
import traceback
import shutil
from collections import defaultdict
from aiogram import Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder
import fitz

import db
import utils
from batch_queues import state_manager, ZIP_BATCH_IDLE_SECONDS   # убрана точка


def score_scan_replacement_match(scanned_text: str, work_data: dict) -> float:
    """
    Вычисляет итоговый балл совпадения метаданных для повторного скана (на замену страниц).
    Использует extract_metadata для стандартизированного разбора текста скана.
    """
    if not work_data:
        return 0.0

    from rapidfuzz import fuzz
    import utils  # Используем твой парсер метаданных

    # ---- 1. Метаданные архивной работы из БД (приводим к строке) ----
    db_subject = str(work_data.get("subject", "")).upper().strip()
    db_full_subject = str(work_data.get("full_subject", "")).lower().strip()
    db_work_type = str(work_data.get("work_type", "")).upper().strip()
    db_work_number = str(work_data.get("work_number", "")).strip()
    db_group = str(work_data.get("group", "")).upper().strip()

    db_authors = work_data.get("authors", [])
    if not isinstance(db_authors, list):
        db_authors = [str(db_authors)]
    db_authors = [str(a).upper().strip() for a in db_authors if a]

    # ---- 2. Метаданные из распознанного текста скана ----
    scan_meta = utils.extract_metadata("scan.pdf", scanned_text)

    scan_subject = str(scan_meta.get("subject", "")).upper().strip()
    scan_work_type = str(scan_meta.get("work_type", "")).upper().strip()
    scan_work_number = str(scan_meta.get("work_number", "")).strip()
    scan_group = str(scan_meta.get("group", "")).upper().strip()
    scan_authors = [str(a).upper().strip() for a in scan_meta.get("authors", [])]

    score = 0.0

    # ==========================================
    # КРИТЕРИЙ 1: ПРЕДМЕТ (ДИСЦИПЛИНА) — СТРОГИЙ БАРЬЕР
    # ==========================================
    subject_matched = False

    if db_subject and scan_subject and db_subject == scan_subject and db_subject != "ПРЕДМЕТ":
        subject_matched = True
        score += 150.0
    elif db_full_subject and fuzz.partial_ratio(db_full_subject, scanned_text.lower()) >= 80.0:
        subject_matched = True
        score += 120.0

    if not subject_matched and db_subject != "ПРЕДМЕТ":
        return 0.0

    # ==========================================
    # КРИТЕРИЙ 2: НОМЕР РАБОТЫ (Высший приоритет)
    # ==========================================
    if db_work_number and db_work_number not in ("None", ""):
        if scan_work_number and scan_work_number not in ("None", ""):
            if db_work_number == scan_work_number:
                score += 200.0
            else:
                score -= 150.0
        else:
            score -= 40.0

    # ==========================================
    # КРИТЕРИЙ 3: ТИП РАБОТЫ (ЛР, ПЗ, КР, КП)
    # ==========================================
    if db_work_type and scan_work_type:
        if db_work_type == scan_work_type:
            score += 150.0
        else:
            score -= 120.0

    # ==========================================
    # КРИТЕРИЙ 4: АВТОРЫ И ИХ КОЛИЧЕСТВО (МНОГОАВТОРСТВО)
    # ==========================================
    if db_authors and scan_authors:
        matched_authors_count = 0
        for db_auth in db_authors:
            if any(fuzz.ratio(db_auth, sc_auth) >= 85.0 for sc_auth in scan_authors):
                matched_authors_count += 1
            else:
                db_last_name = db_auth.split()[0] if ' ' in db_auth else db_auth
                if db_last_name in scanned_text.upper():
                    matched_authors_count += 1

        if matched_authors_count > 0:
            score += matched_authors_count * 80.0

        if len(db_authors) == len(scan_authors) and matched_authors_count == len(db_authors):
            score += 100.0
        elif matched_authors_count == 0:
            score -= 80.0
    else:
        if db_authors and any((db_auth.split()[0] if ' ' in db_auth else db_auth) in scanned_text.upper() for db_auth in db_authors):
            score += 60.0

    # ==========================================
    # КРИТЕРИЙ 5: ГРУППА
    # ==========================================
    if db_group and scan_group:
        if db_group == scan_group:
            score += 90.0
        else:
            score -= 120.0

    return score


async def background_scan_batch_processing(bot: Bot, task: dict):
    chat_id = task['chat_id']
    user_id = task['user_id']
    msg_id = task['msg_id']
    files = task['files']
    batch_dir = task['batch_dir']

    task_id = str(uuid.uuid4())
    task_dir = os.path.join("temp", task_id)
    state_manager.active_scan_batches.add(task_dir)
    try:
        os.makedirs(task_dir, exist_ok=True)

        # ----- 1. Проверка на сканы -----
        if files:
            try:
                check_count = min(3, len(files))
                for i in range(check_count):
                    with fitz.open(files[i]) as doc:
                        if len(doc) == 0:
                            continue
                        page = doc[0]
                        images = page.get_images(full=True)
                        text = page.get_text().strip()
                        if not images and len(text) > 100:
                            await bot.send_message(
                                chat_id=chat_id,
                                text="❌ Похоже, вы отправили готовую работу, а не скан. "
                                     "Пожалуйста, используйте /add_work для загрузки работ."
                            )
                            return
            except Exception as e:
                logging.warning(f"Не удалось проверить тип файла: {e}")

        # ----- 2. Сшивка и нарезка -----
        progress_msg = await bot.send_message(chat_id=chat_id, text=f"📄 Начинаю обработку {len(files)} сканов...")
        await asyncio.sleep(0.5)
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=progress_msg.message_id,
            text=f"🔄 Сшиваю {len(files)} сканов in один документ..."
        )
        master_scan = os.path.join(task_dir, f"master_scan_{task_id}.pdf")
        await asyncio.to_thread(utils.merge_to_one_pdf, files, master_scan)

        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=progress_msg.message_id,
            text="✂️ Нарезаю на отдельные листы..."
        )
        scan_pages = await asyncio.to_thread(utils.split_pdf_to_single_pages, master_scan, task_dir)
        total_pages = len(scan_pages)
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=progress_msg.message_id,
            text=f"📄 Получено {total_pages} листов. Начинаю распознавание..."
        )
        asyncio.create_task(state_manager._fade_and_delete(bot, chat_id, progress_msg.message_id, delay=2.0))

        # ----- 3. Заглушки -----
        placeholders = []
        for idx in range(total_pages):
            sent = await bot.send_message(
                chat_id=chat_id,
                text=f"🔍 Распознаю лист {idx+1} из {total_pages}..."
            )
            placeholders.append(sent)

        # ----- 4. Обработка каждого листа -----
        scan_texts = {}
        scan_gemini_used = {}
        ocr_cache = {}
        replacements_by_work = {}
        processed_pages = set()
        replacements_summary = []
        total_titles = 0
        signed_titles = 0
        main_batch_stats = []
        title_pages = set()

        MIN_REPLACEMENT_SCORE = 250.0  # Порог уверенности для замены

        async def _ocr_with_persistent_cache(page_path: str) -> str:
            """
            Перед вызовом Gemini проверяет персистентный (между запусками) кэш по хэшу
            содержимого страницы — если этот физический скан уже распознавался раньше
            (например, при повторной тестовой отправке того же файла), Gemini заново не
            вызывается: результат для того же байт-в-байт содержимого не изменится, а
            вызов впустую тратит дневной лимит запросов.
            """
            with open(page_path, "rb") as f:
                content_hash = hashlib.sha256(f.read()).hexdigest()
            cached = await db.get_cached_ocr(content_hash)
            if cached is not None:
                logging.info(f"♻️ [OCR CACHE] Найден кэш для этой страницы (hash={content_hash[:10]}...), Gemini не вызывается")
                return cached
            text = await utils.get_page_text_robust(page_path, force_gemini=True)
            if text:
                await db.save_cached_ocr(content_hash, text)
            return text

        for idx, p in enumerate(scan_pages):
            placeholder_msg = placeholders[idx]

            native_text = await asyncio.to_thread(utils.get_page_text_native, p)
            logging.info(f"📄 [SCAN DEBUG] Page {idx+1} | Native extract: {native_text[:100]}...")

            cyrillic_count = len([c for c in native_text if '\u0400' <= c <= '\u04ff'])
            if len(native_text.strip()) >= 50 and cyrillic_count >= 10:
                if idx == 0:
                    result = ocr_cache.get(p)
                    if result is None:
                        result = await _ocr_with_persistent_cache(p)
                        ocr_cache[p] = result
                    scan_gemini_used[p] = True
                else:
                    result = utils.normalize_text(native_text)
                    scan_gemini_used[p] = False
            else:
                logging.info(f"📄 [SCAN DEBUG] Page {idx+1} | Нечитаемо, запускаю Gemini OCR...")
                result = ocr_cache.get(p)
                if result is None:
                    result = await _ocr_with_persistent_cache(p)
                    ocr_cache[p] = result
                scan_gemini_used[p] = True

            scan_texts[p] = result
            scan_text = result

            is_review = utils.is_review_page(result)
            if is_review:
                logging.info(f"📄 [REVIEW] Page {idx+1} text: {result[:500]}...")
            
            if scan_gemini_used.get(p):
                logging.info(f"🤖 [GEMINI OCR] Page {idx+1} text: {result[:600]}...")

            if not result or len(result) < 10:
                logging.warning(f"⚠️ [SCAN DEBUG] Gemini/Robust failed on page {idx+1}")

            meta = utils.extract_metadata(p, scan_text)
            if not is_review and (meta and (meta.get("work_type") == "РАБ" or meta.get("group") == "БЕЗ_ГРУППЫ")):
                ocr_res = await utils.perform_ocr(p)
                if ocr_res:
                    gemini_meta = utils.parse_gemini_ocr_text(ocr_res)
                    if gemini_meta: # <--- Добавляем проверку
                        meta = gemini_meta
            work_id, page_num = None, None

            # ШАГ А: Проверяем точное совпадение по метаданным
            # ВАЖНО: одного факта, что group/subject распознались, недостаточно — на зашумлённом
            # native-OCR тексте обычной (не титульной) страницы регэкспы иногда случайно
            # выхватывают что-то, формально похожее на группу/предмет, и это может случайно
            # совпасть с метаданными СОВЕРШЕННО другой существующей работы. Раньше это приводило
            # к тому, что рядовые страницы содержимого ошибочно считались чужими титульными
            # листами (page_num жёстко = 1) и лист неверно помечался "уже заменён". Поэтому
            # дополнительно проверяем, что текст ДЕЙСТВИТЕЛЬНО похож на титульный лист —
            # есть характерные маркеры "Выполнил/Студент" рядом с "Проверил/дисциплин/предмет".
            looks_like_title = bool(
                re.search(r'выполнил|студент', scan_text, re.IGNORECASE) and
                re.search(r'проверил|дисциплин|предмет', scan_text, re.IGNORECASE)
            )
            if not is_review and looks_like_title and meta.get("group") and meta.get("group") != "БЕЗ_ГРУППЫ" \
                    and meta.get("subject") and meta.get("subject") != "Предмет":
                try:
                    exact_work = await db.find_exact_work(meta, user_id)
                except Exception as e:
                    exact_work = None
                    logging.warning(f"find_exact_work error: {e}")
                if exact_work:
                    work_id = exact_work["_id"]
                    page_num = 1
                    logging.info(f"📄 [SCAN DEBUG] Точное совпадение по метаданным (группа/предмет/тип/номер): work={work_id}")

            # ШАГ Б: Если точного совпадения нет, ищем через нечеткие/агрегированные механизмы базы
            if not work_id:

                async def _resolve_candidates(cands, stage_label):
                    """
                    Разрешает список кандидатов (work_id, page_num):
                    - если все указывают на одну и ту же работу (или кандидат один) — берём его сразу,
                      без порога скоринга (единственное совпадение не должно резаться слишком строгим
                      score_scan_replacement_match, который годится только для разрешения расхождений);
                    - если кандидатов несколько и они расходятся — прогоняем через скоринг и
                      утверждаем только при прохождении порога MIN_REPLACEMENT_SCORE.
                    Возвращает (work_id, page_num, resolved: bool).
                    """
                    if not cands:
                        return None, None, False
                    uniq = {c_work_id for c_work_id, _ in cands}
                    if len(uniq) == 1:
                        w_id, p_num = cands[0]
                        logging.info(f"📄 [SCAN DEBUG] {stage_label}: единственный кандидат (без расхождений): work={w_id}, page={p_num}")
                        return w_id, p_num, True

                    logging.info(f"📄 [SCAN DEBUG] {stage_label}: обнаружены дубликаты-кандидаты ({len(uniq)} разных работ), запускаю скоринг...")
                    best_id, best_page, best_score = None, None, -100.0
                    for c_work_id, c_page_num in cands:
                        work_card = await db.get_work_by_id(c_work_id)
                        if work_card:
                            score = score_scan_replacement_match(scan_text, work_card)
                            logging.info(f"📊 [REPLACEMENT RANKING] Проверка листа {idx+1} с «{work_card.get('filename')}» | Балл: {score}")
                            if score > best_score:
                                best_score = score
                                best_id, best_page = c_work_id, c_page_num
                    if best_score >= MIN_REPLACEMENT_SCORE:
                        logging.info(f"✅ [REPLACEMENT MATCH] {stage_label}: дубликат разрешён скорингом.")
                        return best_id, best_page, True
                    logging.info(f"📄 [REPLACEMENT KICK] {stage_label}: дубликаты отклонены скорингом (Балл {best_score} < {MIN_REPLACEMENT_SCORE}).")
                    return None, None, False

                # Уровень 1: базовые методы поиска
                candidates = []

                # 1. Полнотекстовый поиск с метаданными
                w_id, p_num = await db.find_page_by_text_with_metadata(user_id, scan_text, meta)
                if w_id and p_num:
                    candidates.append((w_id, p_num))

                # 2. Просто полнотекстовый поиск по тексту страницы
                w_id, p_num = await db.find_page_by_text(user_id, scan_text)
                if w_id and p_num:
                    candidates.append((w_id, p_num))

                # 3. Агрегированный контентный поиск
                w_id, p_num = await db.find_work_by_aggregated_content(
                    user_id, scan_text, hint_group=meta.get("group"),
                    hint_author=meta.get("author"), is_review_page=is_review
                )
                if w_id and p_num:
                    candidates.append((w_id, p_num))

                work_id, page_num, resolved = await _resolve_candidates(candidates, "Уровень 1")

                # Уровень 2 (усиленный OCR + расширенный поиск): раньше срабатывал ТОЛЬКО если
                # candidates был пустым списком. Из-за этого, если находилась пара кандидатов,
                # которые потом не проходили скоринг (например, оба с другим предметом), поиск
                # останавливался и лист объявлялся "новым уникальным", даже если настоящая
                # подходящая работа в базе была — её просто не пытались искать. Теперь фолбэк
                # запускается всегда, когда на первом уровне ничего не подтвердилось (пусто ИЛИ
                # кандидаты не прошли скоринг).
                if not resolved:
                    enhanced = scan_texts[p] if scan_gemini_used.get(p) else await _ocr_with_persistent_cache(p)
                    if enhanced:
                        ocr_cache[p] = enhanced
                        scan_gemini_used[p] = True

                        fallback_candidates = []
                        if enhanced != scan_text:
                            w_id, p_num = await db.find_page_by_text(user_id, enhanced)
                            if w_id and p_num:
                                fallback_candidates.append((w_id, p_num))

                        fallback_text = enhanced if len(enhanced) > len(scan_text or "") else scan_text
                        w_id, p_num = await db.find_work_by_aggregated_content(
                            user_id, fallback_text, hint_group=meta.get("group"),
                            hint_author=meta.get("author"), is_review_page=is_review
                        )
                        if w_id and p_num:
                            fallback_candidates.append((w_id, p_num))

                        if fallback_candidates:
                            work_id, page_num, resolved = await _resolve_candidates(fallback_candidates, "Уровень 2 (усиленный OCR)")

            final_text = ""
            has_menu = False
            if work_id and page_num:
                work = await db.get_work_by_id(work_id)
                if work:
                    if page_num in work.get("replaced_pages", []):
                        req_key = f"replace_{uuid.uuid4().hex[:8]}"
                        state_manager.pending_replacements[req_key] = {
                            'work_id': work_id,
                            'page_num': page_num,
                            'page_path': p,
                            'work': work,
                            'user_id': user_id,
                            'task_dir': task_dir,
                            'scan_text': scan_text,
                        }
                        builder = InlineKeyboardBuilder()
                        builder.button(text="✅ Да, заменить", callback_data=f"replace_confirm:{req_key}:yes")
                        builder.button(text="❌ Нет, оставить", callback_data=f"replace_confirm:{req_key}:no")
                        builder.adjust(2)
                        state_manager.register_menu(user_id)

                        repl_authors = work.get('authors', [])
                        if len(repl_authors) > 1:
                            repl_subject = work.get('full_subject') or work.get('subject') or 'неизвестный предмет'
                            work_display = f"Предмет: {repl_subject}\n(несколько авторов)"
                        else:
                            work_display = work.get('filename', 'неизвестная')

                        await bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=placeholder_msg.message_id,
                            text=f"⚠️ Стр. {page_num} в работе уже заменена в работе «{work_display}».\n"
                                 f"Нажмите «Да», чтобы заменить его новым сканом, или «Нет», чтобы оставить текущий.",
                            reply_markup=builder.as_markup()
                        )
                        has_menu = True
                        continue

                    authors = work.get('authors', [])
                    if page_num == 1:
                        if len(authors) > 1:
                            subject_name = work.get('full_subject') or work.get('subject') or work.get('filename', 'неизвестная')
                            display_name = f"Предмет: {subject_name}\n(несколько авторов)"
                        else:
                            display_name = work.get('filename', 'неизвестная')
                        final_text = f"📄 Распознан титульный лист:\n<b>{display_name}</b>"
                        with open(p, "rb") as f:
                            page_bytes = f.read()
                        has_sig, reason, detail = await utils.detect_signature_async(scan_text, page_bytes)
                        if has_sig:
                            final_text += "\n\n✅ Подпись найдена"
                            signed_titles += 1
                        else:
                            final_text += "\n\n⚠️ Подпись не обнаружена"
                        total_titles += 1
                        title_pages.add(p)
                    else:
                        if len(authors) > 1:
                            display_name = work.get('full_subject') or work.get('subject') or work.get('filename', 'неизвестная')
                            display_name = f"Предмет: {display_name} (несколько авторов)"
                        else:
                            display_name = work.get('filename', 'неизвестная')
                        final_text = f"📄 Стр. {page_num} в работе: <b>{display_name}</b> (не титульный)"

                    if work_id not in replacements_by_work:
                        replacements_by_work[work_id] = {}
                    replacements_by_work[work_id][page_num - 1] = p
                    processed_pages.add(p)
                    replacements_summary.append((work.get('filename', 'неизвестная'), page_num))
                    main_batch_stats.append({
                        'page_num': page_num,
                        'filename': work.get('filename', 'неизвестная'),
                        'has_signature': has_sig if page_num == 1 else None,
                    })

                    if page_num == 1:
                        related = await db.get_related_works_for_scan(user_id, work_id)
                        if related and len(related) > 1:
                            final_text += "\n\nℹ️ Титул принадлежит работе с несколькими авторами. Замена будет применена ко всем копиям."

                else:
                    final_text = f"❌ Не удалось найти работу для скана {idx+1}"
            else:
                final_text = f"❌ Не удалось найти работу для скана {idx+1}"

            if not has_menu:
                asyncio.create_task(state_manager._fade_and_delete(bot, chat_id, placeholder_msg.message_id, delay=0.3))
                try:
                    await bot.send_message(chat_id=chat_id, text=final_text, parse_mode="HTML")
                except Exception as e:
                    logging.warning(f"Не удалось отправить финальный статус листа: {e}")

        # Цикл по страницам завершён — все меню "уже заменено?" для этой пачки к этому
        # моменту гарантированно уже созданы. Снимаем флаг активности, чтобы проверка
        # "остались ли ещё нерешённые меню этой пачки" (в callback_replace_confirm)
        # больше не занижала результат из-за того, что цикл ещё не дошёл до какой-то страницы.
        state_manager.active_scan_batches.discard(task_dir)

        # ----- 5. Замены -----
        if not replacements_by_work:
            has_pending_repl_confirm = any(
                v.get('task_dir') == task_dir for v in state_manager.pending_replacements.values()
            )
            if not has_pending_repl_confirm:
                await bot.send_message(chat_id=chat_id, text="⚠️ Ни один лист не привязан к существующим работам.")
            else:
                # Раньше здесь был безусловный return — если ВСЕ листы пачки ушли на
                # подтверждение "уже заменено?" (ни одного прямого совпадения), финальная
                # секция со статистикой и показом напоминания о меню вообще не вызывалась,
                # и пользователь не видел ни сколько листов ждёт ответа, ни само напоминание.
                pending_count = len([
                    k for k, v in state_manager.pending_replacements.items()
                    if v.get('task_dir') == task_dir
                ])
                wait_msg = await bot.send_message(
                    chat_id=chat_id,
                    text=f"⏳ Ожидается подтверждение для {pending_count} листов. "
                         f"Они будут заменены после вашего ответа.",
                    parse_mode="HTML"
                )
                state_manager.pending_wait_messages[task_dir] = (chat_id, wait_msg.message_id)
                if state_manager.open_menu_counts.get(user_id, 0) > 0:
                    await state_manager._send_menu_reminder(bot, chat_id, user_id)
            return

        apply_msg = await bot.send_message(chat_id=chat_id, text="📦 Применяю замены и обновляю работы...")
        ready_files: dict = {}

        async def _process_single_replacement(work_id, repl_dict):
            work = await db.get_work_by_id(work_id)
            if not work:
                return None
            orig_path = os.path.join(task_dir, f"orig_{work_id}.pdf")
            out_path = os.path.join(task_dir, f"ready_{work['filename']}")

            await db.download_file(work['file_id'], orig_path)
            await asyncio.to_thread(utils.replace_specific_pages, orig_path, repl_dict, out_path)

            with open(out_path, "rb") as f:
                ready_bytes = f.read()

            new_replaced = [idx + 1 for idx in repl_dict.keys()]
            related_works = await db.get_related_works_for_scan(user_id, work_id)
            if not related_works:
                related_works = [work]

            w_ids = [rw["_id"] for rw in related_works]
            first_work = related_works[0] if related_works else work

            await db.update_multiple_works_with_scan(
                work_ids=w_ids,
                file_bytes=ready_bytes,
                new_filename=first_work['filename'],
                new_replaced_pages=new_replaced,
            )

            for page_idx, page_path_for_text in repl_dict.items():
                page_text = scan_texts.get(page_path_for_text)
                if page_text:
                    try:
                        await db.update_pages_text(w_ids, page_idx + 1, page_text)
                    except Exception as e:
                        logging.warning(f"⚠️ Не удалось обновить текст страницы в pages: {e}")

            return [(str(rw["_id"]), out_path, rw.get('filename', first_work['filename']), rw.get('author', ''), rw.get('authors', [])) for rw in related_works]

        tasks = [_process_single_replacement(wid, rd) for wid, rd in replacements_by_work.items()]
        results = await asyncio.gather(*tasks)
        for res in results:
            if res:
                for wid_str, out_path, fname, author, authors_list in res:
                    ready_files[wid_str] = (out_path, fname, author)

        asyncio.create_task(state_manager._fade_and_delete(bot, chat_id, apply_msg.message_id, delay=2.0))

        has_pending_menus_in_batch = (
            any(v.get('task_dir') == task_dir for v in state_manager.pending_replacements.values())
            or state_manager.active_replace_tasks.get(task_dir, 0) > 0
        )

        # ----- 6. Группировка и меню -----
        groups: dict[str, list] = defaultdict(list)
        for wid_str, (out_path, filename, author) in ready_files.items():
            work = await db.get_work_by_id(wid_str)
            if not work:
                continue
            authors_list = work.get('authors', [])
            own_author = work.get('author') or (authors_list[0] if authors_list else 'Автор')
            file_id = work.get('file_id')
            if not file_id:
                file_id = wid_str
            groups[str(file_id)].append((wid_str, out_path, filename, authors_list, own_author))

        logging.info(f"📄 Группы: { {fid: len(members) for fid, members in groups.items()} }")

        multi_author_groups = {}
        single_author_groups = {}

        for file_id, members in groups.items():
            all_authors = set()
            for _, _, _, authors_list, _ in members:
                all_authors.update(authors_list)
            if len(all_authors) > 1:
                multi_author_groups[file_id] = members
            else:
                single_author_groups[file_id] = members

        files_sent = 0

        # Отправляем работы с одним автором (сразу в архив)
        for group_key, members in single_author_groups.items():
            for wid_str, out_path, filename, authors_list, own_author in members:
                if os.path.exists(out_path):
                    state_manager.queue_file_for_zip_batch(
                        bot=bot, user_id=user_id, chat_id=chat_id,
                        file_path=out_path, filename=filename,
                        kind="scan", restart_timer=False
                    )
                    files_sent += 1

        # Многоавторские – накапливаем файлы в кеш (не перезаписывая то, что уже могло
        # накопиться от подтверждённых через confirm-меню замен той же пачки)
        if multi_author_groups:
            user_files = state_manager.pending_scan_ready_files.get(user_id, {})
            for file_id, members in multi_author_groups.items():
                for wid_str, out_path, filename, authors_list, own_author in members:
                    # ВАЖНО: own_author — "своё" имя КОНКРЕТНОЙ копии (work.author), а не
                    # authors_list[0] (первый элемент общего списка авторов работы, который
                    # мог быть одинаковым на всех копиях — тогда все кнопки схлопывались в
                    # одну и в меню оставался только один автор вместо всех).
                    user_files[wid_str] = (out_path, filename, own_author)
            state_manager.pending_scan_ready_files[user_id] = user_files

            if has_pending_menus_in_batch:
                # В пачке ещё есть нерешённые "уже заменено?" запросы — меню выбора автора
                # покажем позже, ОДНИМ общим сообщением вместе с итоговой сводкой, когда
                # пользователь ответит на все вопросы (см. _apply_replace_confirm_yes).
                logging.info("🔍 Многоавторская группа найдена, но пачка ещё ждёт подтверждений — меню авторов отложено")
            else:
                builder = InlineKeyboardBuilder()
                req_id = uuid.uuid4().hex[:8]
                author_map = {}
                idx = 0

                # Уникальные авторы — ГЛОБАЛЬНО по всей пачке (не по каждой работе отдельно),
                # иначе автор, встречающийся в нескольких мультиавторских работах пачки,
                # получал бы отдельную (визуально задвоенную) кнопку на каждую работу.
                all_unique_authors = set()
                any_wid = None
                for file_id, members in multi_author_groups.items():
                    if any_wid is None:
                        any_wid = members[0][0]
                    for _, _, _, authors_list, _ in members:
                        all_unique_authors.update(authors_list)

                for author in sorted(all_unique_authors):
                    author_map[str(idx)] = {'wid': any_wid, 'author': author, 'type': 'single'}
                    builder.button(text=author, callback_data=f"sa_btn:{req_id}:{idx}")
                    idx += 1

                # Одна кнопка "Всех" на всю пачку, а не по одной на каждую работу.
                author_map[str(idx)] = {'wid': any_wid, 'type': 'all'}
                builder.button(text="✅ Всех", callback_data=f"sa_btn:{req_id}:{idx}")
                idx += 1

                builder.button(text="❌ Закрыть", callback_data=f"sa_btn:{req_id}:close")
                builder.adjust(2)

                state_manager.temp_scan_authors[req_id] = author_map
                state_manager.scan_menus_active.add(user_id)
                state_manager.register_menu(user_id)

                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=f"🔍 Для некоторых работ найдено несколько авторов.\n"
                             f"Выберите, кого добавить в архив для проверки:",
                        parse_mode="HTML",
                        reply_markup=builder.as_markup()
                    )
                except Exception as e:
                    logging.warning(f"Не удалось показать меню: {e}")
                    state_manager.scan_menus_active.discard(user_id)
                    asyncio.create_task(state_manager.resolve_menu(bot, user_id))
                    for wid_str, (out_path, filename, author) in user_files.items():
                        if os.path.exists(out_path):
                            state_manager.queue_file_for_zip_batch(
                                bot=bot, user_id=user_id, chat_id=chat_id,
                                file_path=out_path, filename=filename,
                                kind="scan", restart_timer=False
                            )
                            files_sent += 1
                    state_manager.pending_scan_ready_files.pop(user_id, None)

        if files_sent > 0 and not has_pending_menus_in_batch:
            state_manager._restart_batch_timer(bot, user_id, chat_id, ZIP_BATCH_IDLE_SECONDS, kind="scan")
        elif files_sent > 0:
            logging.info("📦 Есть нерешённые меню 'уже заменено?' в этой пачке — таймер архива отложен до ответа на все вопросы")

        # ----- 7. Финальный статус -----
        sorted_replacements = []
        for work_id, repl_dict in replacements_by_work.items():
            work = await db.get_work_by_id(work_id)
            if not work:
                continue
            work_name = work.get('filename', 'неизвестная')
            for pg_num_in_work in sorted(repl_dict.keys()):
                sorted_replacements.append(f"• Стр. {pg_num_in_work+1} в работе ➡️ {work_name}")

        pending_count = len([
            k for k, v in state_manager.pending_replacements.items()
            if v.get('task_dir') == task_dir
        ])
        # Листы, ожидающие подтверждения "уже заменено?", УЖЕ опознаны — они не должны
        # попадать в "Неопознанных", иначе получается противоречивая картина (один и тот же
        # лист одновременно "неопознан" и "ждёт подтверждения замены").
        unmatched = len(scan_pages) - len(processed_pages) - pending_count

        if has_pending_menus_in_batch:
            # Часть листов пачки ещё ждёт ответа "Да/Нет" — не показываем итоговую статистику
            # сейчас (она была бы неполной и вводящей в заблуждение), а копим её и покажем
            # ОДНИМ полным сообщением, когда пользователь ответит на все вопросы пачки
            # (см. _apply_replace_confirm_yes в handlers.py).
            state_manager.pending_replace_stats.setdefault(task_dir, []).extend(main_batch_stats)

            provisional_text = f"📦 Прямых совпадений: {len(replacements_by_work)} работ(ы) обновлено."
            if unmatched > 0:
                provisional_text += f"\n⚠️ Неопознанных листов: {unmatched}"
            provisional_text += (
                f"\n\n⏳ Ожидается подтверждение для {pending_count} листов. "
                f"Полная сводка придёт после вашего ответа на все вопросы."
            )
            wait_msg = await bot.send_message(chat_id=chat_id, text=provisional_text)
            state_manager.pending_wait_messages[task_dir] = (chat_id, wait_msg.message_id)
        else:
            status_text = f"📊 <b>Обработка завершена.</b> Обновлено работ: {len(replacements_by_work)}."

            if total_titles > 0:
                status_text += f"\n\n📋 Проверка титульных листов:\n"
                status_text += f"Всего титулов: {total_titles}, с подписью: {signed_titles}"
            else:
                status_text += "\n\nℹ️ Титульные листы не обнаружены."

            if sorted_replacements:
                status_text += "\n\n✅ <b>Замены:</b>\n" + "\n".join(sorted_replacements)

            if unmatched > 0:
                status_text += f"\n\n⚠️ Неопознанных листов: {unmatched}"

            await bot.send_message(chat_id=chat_id, text=status_text, parse_mode="HTML")

        if state_manager.open_menu_counts.get(user_id, 0) > 0:
            await state_manager._send_menu_reminder(bot, chat_id, user_id)

    except Exception as e:
        logging.error(f"Scan batch processing error:\n{traceback.format_exc()}")
        try:
            await bot.send_message(chat_id=chat_id, text=f"❌ Ошибка: {str(e) if str(e) else 'смотрите логи'}")
        except Exception:
            pass
        state_manager.scan_menus_active.discard(user_id)
    finally:
        state_manager.active_scan_batches.discard(task_dir)
        has_pending_repl = any(v.get('task_dir') == task_dir for v in state_manager.pending_replacements.values())
        if not has_pending_repl and user_id not in state_manager.scan_menus_active:
            if os.path.exists(task_dir):
                shutil.rmtree(task_dir, ignore_errors=True)
        if os.path.exists(batch_dir):
            shutil.rmtree(batch_dir, ignore_errors=True)
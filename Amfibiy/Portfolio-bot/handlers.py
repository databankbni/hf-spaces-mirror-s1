import os
import re
import shutil
import asyncio
import logging
import uuid
import traceback
from datetime import datetime
from collections import defaultdict

from aiogram import Router, F, Bot
from aiogram.types import (
    Message, CallbackQuery, FSInputFile,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from bson.objectid import ObjectId
from rapidfuzz import fuzz

import config
import db
import utils
import email_sender

# Импорты из модулей (без точек)
from batch_queues import state_manager, processing_queue, ZIP_BATCH_IDLE_SECONDS, ZIP_BATCH_REDUCED_SECONDS, WORK_BATCH_IDLE_SECONDS, SCAN_BATCH_IDLE_SECONDS
from work_processing import background_work_processing
from scan_processing import background_scan_batch_processing

router = Router()


async def safe_delete(message):
    """Аналогично safe_answer — повторно доставленный колбэк может пытаться удалить уже
    удалённое сообщение ('message to delete not found'). Не критично, просто игнорируем."""
    try:
        await message.delete()
    except TelegramBadRequest as e:
        logging.warning(f"⚠️ message.delete() не удался (вероятно, повторный колбэк): {e}")


async def safe_answer(call: CallbackQuery, *args, **kwargs):
    """
    Telegram иногда доставляет один и тот же callback дважды (ретрай вебхука, если наш
    ответ задержался). Вторая попытка ответить на уже отвеченный или просроченный query
    падает с TelegramBadRequest("query is too old...") и роняет обработку всего апдейта.
    Эта ошибка не критична — просто игнорируем её, а не валим весь хендлер.
    """
    try:
        await call.answer(*args, **kwargs)
    except TelegramBadRequest as e:
        logging.warning(f"⚠️ call.answer() не удался (устаревший/повторный callback): {e}")


class BotStates(StatesGroup):
    waiting_for_works = State()
    waiting_for_scans = State()
    choosing_subjects = State()
    choosing_author = State()


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def _transliterate_to_ascii(text: str) -> str:
    table = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    }
    result = []
    for ch in text:
        lower = ch.lower()
        if lower in table:
            translit = table[lower]
            result.append(translit.upper() if ch.isupper() and translit else translit)
        elif ch.isalnum() or ch in "._-":
            result.append(ch)
        else:
            result.append('_')
    out = ''.join(result)
    out = re.sub(r'_+', '_', out).strip('_')
    return out or "file"

def _batch_kind_label(kind: str) -> str:
    return "сканов" if kind == "scan" else "работ"

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

async def send_document_with_retry(message: Message, file_path: str, filename: str,
                                   retries: int = 3, delay: int = 2,
                                   kind: str = "work", restart_timer: bool = True):
    state_manager.queue_file_for_zip_batch(
        bot=message.bot,
        user_id=message.from_user.id,
        chat_id=message.chat.id,
        file_path=file_path,
        filename=filename,
        kind=kind,
        restart_timer=restart_timer
    )

async def force_flush_zip_batch_now(user_id: int, kind: str = "work"):
    key = (user_id, kind)
    batch = state_manager.pending_zip_batches.get(key)
    if batch and batch.get("timer_task") and not batch["timer_task"].done():
        batch["timer_task"].cancel()
    # Нужен доступ к боту, но в этой функции нет бота – лучше вызывать из контекста, где есть bot.
    # Мы не будем использовать эту функцию, оставим как заглушку.
    pass


# ========== ПРИВЯЗКА ПРЕЗЕНТАЦИЙ (вынесена в work_processing, но здесь оставим обёртку) ==========
async def try_link_presentations(tg_id: int, work_metadata: dict, work_ids: list):
    """Обёртка для вызова из обработчиков (если нужно) — делегируем в work_processing."""
    from work_processing import try_link_presentations as _try_link
    await _try_link(tg_id, work_metadata, work_ids)

async def link_presentation_to_works(pres_id: ObjectId, tg_id: int):
    from work_processing import link_presentation_to_works as _link
    await _link(pres_id, tg_id)

async def finalize_presentation_links(tg_id: int):
    presentations = await db.get_all_presentations(tg_id)
    if not presentations:
        return 0
    linked_count = 0
    for pres in presentations:
        if pres.get('linked_work_ids') and len(pres.get('linked_work_ids', [])) > 0:
            continue
        best_work_id = pres.get('best_work_id')
        if best_work_id:
            await db.link_presentation_to_best_work(pres['_id'])
            linked_count += 1
            work = await db.get_work_by_id(best_work_id)
            if work:
                logging.info(f"✅ Презентация {pres['filename']} привязана к работе {work['filename']} (лучший балл: {pres.get('best_match_score', 0)})")
    return linked_count


# ========== КОМАНДЫ ==========
@router.message(Command("start", "help"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    text = (
        "🤖 <b>Система управления портфолио</b>\n"
        "Я помогу вам собрать, структурировать и отправить работы по стандартам вашей кафедры.\n\n"
        "<b>Основные команды:</b>\n"
        "📥 /add_work — Загрузка учебных работ (ЛР, ПЗ, КР и т.д.). Отправляйте файлы по одному.\n"
        "🖨 /add_scan — Загрузка отсканированных документов. Сканы автоматически сопоставляются.\n"
        "📬 /zip_build — Финальная сборка: структурированный архив для отправки на кафедру.\n"
        "🗑 /delete_works — Удаление загруженных материалов по предметам.\n"
    )
    await message.answer(text, parse_mode="HTML")

@router.message(Command("add_work"))
async def cmd_add_work(message: Message, state: FSMContext):
    await state.set_state(BotStates.waiting_for_works)
    await message.answer("📥 Режим загрузки активен. Отправляйте документы.")

@router.message(Command("add_scan"))
async def cmd_add_scan(message: Message, state: FSMContext):
    await state.set_state(BotStates.waiting_for_scans)
    await message.answer("🖨 Режим приема сканов активен. Отправляйте файлы.")

@router.message(Command("delete_works"))
async def cmd_delete_works(message: Message):
    subjects = await db.get_unique_subjects(message.from_user.id)
    if not subjects:
        return await message.answer("ℹ️ Ваша база пуста.")
    builder = InlineKeyboardBuilder()
    for s in subjects:
        builder.button(text=f"🗑 {s}", callback_data=f"del_{s}")
    await message.answer("Выберите дисциплину для удаления:", reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("del_"))
async def callback_delete(call: CallbackQuery):
    subj = call.data.split("_")[1]
    await db.delete_works_by_subject(call.from_user.id, subj)
    await call.message.edit_text(f"✅ Работы по предмету {subj} удалены.")

@router.message(Command("zip_build"))
async def cmd_send_portfolio(message: Message, state: FSMContext):
    if await db.is_allowed_email_sender(message.from_user.id):
        builder = InlineKeyboardBuilder()
        builder.button(text="📤 Реальная отправка", callback_data="mode_sel:real")
        builder.button(text="🧪 Тестовый режим (на мою почту)", callback_data="mode_sel:test")
        builder.button(text="❌ Отмена", callback_data="cancel_zip")
        builder.adjust(1)
        await message.answer(
            "🧪 Вам доступен тестовый режим: полная имитация отправки на кафедру "
            "(те же кафедры и предметы), но письмо уходит на вашу личную почту вместо кафедры.\n\n"
            "Как отправляем?",
            reply_markup=builder.as_markup()
        )
        return
    await state.update_data(test_mode=False)
    await _show_department_list(message.answer, message.from_user.id)


async def _show_department_list(send_func, tg_id: int):
    builder = InlineKeyboardBuilder()
    departments = await db.get_unique_departments(tg_id)
    if not departments:
        departments = config.DEPARTMENTS
    for dept in departments:
        builder.button(text=dept, callback_data=f"dept_sel:{dept}")
    builder.button(text="❌ Отмена", callback_data="cancel_zip")
    builder.adjust(1)
    await send_func("Выберите кафедру для отправки:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("mode_sel:"))
async def callback_select_mode(call: CallbackQuery, state: FSMContext):
    mode = call.data.split(":")[1]
    await state.update_data(test_mode=(mode == "test"))
    prefix = "🧪 <b>Тестовый режим.</b> " if mode == "test" else ""
    builder = InlineKeyboardBuilder()
    departments = await db.get_unique_departments(call.from_user.id)
    if not departments:
        departments = config.DEPARTMENTS
    for dept in departments:
        builder.button(text=dept, callback_data=f"dept_sel:{dept}")
    builder.button(text="❌ Отмена", callback_data="cancel_zip")
    builder.adjust(1)
    await call.message.edit_text(
        f"{prefix}Выберите кафедру для отправки:", parse_mode="HTML", reply_markup=builder.as_markup()
    )
    await safe_answer(call)


# ========== ОБРАБОТЧИКИ ZIP-ПОСТРОЕНИЯ ==========
@router.callback_query(F.data.startswith("dept_sel:"))
async def callback_select_dept(call: CallbackQuery, state: FSMContext):
    dept = call.data.split(":")[1]
    subjects = await db.get_subjects_by_department(call.from_user.id, dept)
    if not subjects:
        subjects = await db.get_unique_subjects(call.from_user.id)
    if not subjects:
        await call.message.edit_text("⚠️ У вас пока нет загруженных работ для этой кафедры.")
        return
    await state.update_data(target_type="dept", target_val=dept, dept_strategy=dept, selected_subjects=[])
    builder = InlineKeyboardBuilder()
    for s in subjects:
        builder.button(text=f"⬜️ {s}", callback_data=f"subj_toggle:{s}")
    builder.button(text="✅ Далее", callback_data="proceed_to_authors")
    builder.button(text="⬅️ Назад", callback_data="back_to_depts")
    builder.adjust(1)
    await call.message.edit_text(f"Шаг 1: Выберите дисциплины ({dept}):", reply_markup=builder.as_markup())

@router.callback_query(F.data == "back_to_depts")
async def callback_back_to_depts(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    test_mode = data.get("test_mode", False)
    await state.clear()
    await state.update_data(test_mode=test_mode)
    prefix = "🧪 <b>Тестовый режим.</b> " if test_mode else ""
    builder = InlineKeyboardBuilder()
    departments = await db.get_unique_departments(call.from_user.id)
    if not departments:
        departments = config.DEPARTMENTS
    for dept in departments:
        builder.button(text=dept, callback_data=f"dept_sel:{dept}")
    builder.button(text="❌ Отмена", callback_data="cancel_zip")
    builder.adjust(1)
    await call.message.edit_text(f"{prefix}Выберите кафедру для отправки:", parse_mode="HTML", reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("subj_toggle:"))
async def callback_toggle_subj(call: CallbackQuery, state: FSMContext):
    subj = call.data.split(":")[1]
    data = await state.get_data()
    selected = data.get("selected_subjects", [])
    dept = data.get("target_val")
    strategy = data.get("dept_strategy", "")

    if strategy != "ИТиМС" and len(selected) >= 1 and subj not in selected:
        await safe_answer(call, "⚠️ Для этой кафедры можно выбрать только один предмет.", show_alert=True)
        return

    if subj in selected:
        selected.remove(subj)
    else:
        selected.append(subj)
    await state.update_data(selected_subjects=selected)
    subjects = await db.get_subjects_by_department(call.from_user.id, dept)
    if not subjects:
        subjects = await db.get_unique_subjects(call.from_user.id)
    builder = InlineKeyboardBuilder()
    for s in subjects:
        mark = "✅" if s in selected else "⬜️"
        builder.button(text=f"{mark} {s}", callback_data=f"subj_toggle:{s}")
    builder.button(text="✅ Далее", callback_data="proceed_to_authors")
    builder.button(text="⬅️ Назад", callback_data="back_to_depts")
    builder.adjust(1)
    await call.message.edit_reply_markup(reply_markup=builder.as_markup())
    await safe_answer(call)

@router.callback_query(F.data == "proceed_to_authors")
async def callback_proceed_to_authors(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected_subjects = data.get("selected_subjects", [])
    dept = data.get("target_val")
    if not selected_subjects:
        await safe_answer(call, "Выберите хотя бы один предмет!", show_alert=True)
        return
    tg_id = call.from_user.id
    unique_authors = set()
    for subject in selected_subjects:
        works = await db.get_works_by_subject(tg_id, subject, department_filter=dept)
        for work in works:
            if work.get('author'):
                unique_authors.add(work['author'])
    unique_authors = sorted(unique_authors)
    if not unique_authors:
        await call.message.edit_text("⚠️ Не найдено работ для выбранных дисциплин.")
        return
    builder = InlineKeyboardBuilder()
    for author in unique_authors:
        builder.button(text=f"👤 {author}", callback_data=f"author_sel:{author}")
    if len(unique_authors) > 1:
        builder.button(text="📦 Для всех авторов", callback_data="author_sel:all")
    builder.button(text="⬅️ Назад", callback_data=f"dept_sel:{dept}")
    builder.button(text="❌ Отмена", callback_data="cancel_zip")
    builder.adjust(1)
    await call.message.edit_text("Шаг 2: Выберите автора:", reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("author_sel:"))
async def callback_select_author(call: CallbackQuery, state: FSMContext):
    author_choice = call.data.split(":")[1]
    data = await state.get_data()
    selected_subjects = data.get("selected_subjects", [])
    dept = data.get("target_val")
    strategy = data.get("dept_strategy")
    filter_val = None if author_choice == "all" else author_choice
    await process_portfolio_building(call, state, selected_subjects, dept, strategy, author_filter=filter_val)

@router.callback_query(F.data == "cancel_zip")
async def callback_cancel_zip(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Создание архива отменено.")
    await safe_answer(call)


# ========== ПОСТРОЕНИЕ ПОРТФОЛИО (ZIP) ==========
def get_folder_name(w_type, strat):
    if w_type == "ЛР": return "Лабораторные работы"
    if w_type == "ПЗ": return "Практические занятия"
    if w_type in ["СРС", "ИЗ", "СР"]: return "Самостоятельные работы"
    if w_type == "ДКР": return "Домашняя контрольная работа"
    if w_type in ["КР", "КП"]:
        if strat == "ИСТ": return "Курсовая работа (проект)"
        if strat == "МЭС": return "Курсовой проект / работа"
        return "Курсовая работа" if w_type == "КР" else "Курсовой проект"
    if w_type == "УП": return "Учебная практика"
    if w_type == "ПП": return "Производственная практика"
    if not w_type or w_type == "РАБ":
        return "Проект"
    return f"Работы {w_type}"

async def process_portfolio_building(event, state, selected_subjects, dept, strategy, author_filter=None):
    msg = event.message
    tg_id = event.from_user.id
    status_msg = await msg.answer("📦 Начинаю сборку архива...")

    state_data = await state.get_data()
    test_mode = state_data.get("test_mode", False)

    real_target_email = config.DEPARTMENTS.get(dept, "unknown@test.com")
    if test_mode:
        target_email = getattr(config, "MY_EMAIL", "unknown@test.com")
    else:
        target_email = real_target_email

    if strategy != "ИТиМС" and len(selected_subjects) > 1:
        await status_msg.edit_text("⚠️ Для выбранной кафедры допустим только один предмет.\nПожалуйста, выберите один предмет.")
        subjects = await db.get_subjects_by_department(tg_id, dept)
        if not subjects:
            subjects = await db.get_unique_subjects(tg_id)
        builder = InlineKeyboardBuilder()
        for s in subjects:
            builder.button(text=f"⬜️ {s}", callback_data=f"subj_toggle:{s}")
        builder.button(text="✅ Далее", callback_data="proceed_to_authors")
        builder.button(text="⬅️ Назад", callback_data="back_to_depts")
        builder.adjust(1)
        await msg.answer("Шаг 1: Выберите дисциплины (только одну):", reply_markup=builder.as_markup())
        return

    task_id = str(uuid.uuid4())
    base_dir = os.path.join("temp", f"portfolio_{tg_id}_{task_id}")
    archive_base = os.path.join("temp", f"arch_{task_id}")

    try:
        os.makedirs(base_dir, exist_ok=True)

        # Презентации сравниваются с работами по мере загрузки (try_link_presentations),
        # но реальная привязка (linked_work_ids) раньше нигде не фиксировалась —
        # делаем это здесь, перед сборкой архива.
        await finalize_presentation_links(tg_id)

        all_presentations = await db.get_all_presentations(tg_id)
        pres_by_work = {}
        for pres in all_presentations:
            for linked_id in pres.get('linked_work_ids', []):
                pres_by_work.setdefault(str(linked_id), []).append(pres)

        all_works = []
        for subject in selected_subjects:
            works = await db.get_works_by_subject(tg_id, subject, author_filter=None, department_filter=dept)
            all_works.extend(works)
        if not all_works:
            await status_msg.edit_text("❌ Не найдено работ.")
            return

        first_work = all_works[0]
        group = first_work.get('group', 'БЕЗ_ГРУППЫ')

        authors_set = set()
        for work in all_works:
            auth = work.get('author')
            if auth:
                authors_set.add(auth)
        authors_list = sorted(authors_set) if author_filter is None or author_filter == "all" else [author_filter]

        archives_info = []
        total_size_bytes = 0

        for author in authors_list:
            author_works = [w for w in all_works if w.get('author') == author]
            if not author_works:
                continue

            author_dir = os.path.join(base_dir, author)
            os.makedirs(author_dir, exist_ok=True)

            if len(selected_subjects) == 1:
                subject_abbr = selected_subjects[0]
                if strategy == "ИСТ":
                    subject_line = f"{group}_{author}_{subject_abbr}"
                elif strategy == "МЭС":
                    subject_line = f"Портфолио_{group}_{subject_abbr}_{author}"
                elif strategy == "ИТиМС":
                    subject_line = f"Портфолио_{group}_{subject_abbr}_{author}"
                else:
                    subject_line = f"{group}_{author}_{subject_abbr}"
            else:
                subj_str = "_".join(selected_subjects)
                if strategy == "ИСТ":
                    subject_line = f"{group}_{author}_{subj_str}"
                elif strategy == "МЭС":
                    subject_line = f"Портфолио_{group}_{subj_str}_{author}"
                elif strategy == "ИТиМС":
                    subject_line = f"Портфолио_{group}_{subj_str}_{author}"
                else:
                    subject_line = f"{group}_{author}_{subj_str}"

            if strategy == "ИСТ":
                max_mb = 5
            elif strategy == "МЭС":
                max_mb = 10
            elif strategy == "ИТиМС":
                max_mb = 10
            else:
                max_mb = 10

            email_subject = subject_line

            for work in author_works:
                w_type = work.get('work_type', 'РАБ')
                num = work.get('work_number', '')
                subj_abbr = work.get('subject', 'Предмет')
                chosen_subj_name = work.get('full_subject', work.get('subject', 'Предмет')) if strategy in ["МЭС", "ИТиМС"] else subj_abbr
                type_folder = get_folder_name(w_type, strategy)
                subj_folder_name = re.sub(r'\s*-\s*', '-', chosen_subj_name)
                subj_folder_name = re.sub(r'[^\w\s-]', '', subj_folder_name).strip()
                folder_author = author
                path = os.path.join(author_dir, group, folder_author, subj_folder_name, type_folder)
                os.makedirs(path, exist_ok=True)
                clean_filename = work.get('filename', f"{group}_{folder_author}_{subj_abbr}_{w_type}{num}.pdf")
                clean_filename = re.sub(r'[\\/*?:"<>|]', '', clean_filename).strip()
                file_dest = os.path.join(path, clean_filename)
                await db.download_file(work['file_id'], file_dest)
                total_size_bytes += os.path.getsize(file_dest)

                work_id = str(work['_id'])
                if work_id in pres_by_work:
                    for pres in pres_by_work[work_id]:
                        pres_filename = pres.get('filename', 'presentation.pdf')
                        pres_dest = os.path.join(path, pres_filename)
                        await db.download_file(pres['file_id'], pres_dest)
                        total_size_bytes += os.path.getsize(pres_dest)

            safe_author = author.replace(' ', '_')
            zip_basename = f"{archive_base}_{safe_author}"
            zip_path = f"{zip_basename}.zip"

            try:
                await asyncio.to_thread(shutil.make_archive, zip_basename, 'zip', author_dir)
                if not os.path.exists(zip_path):
                    raise FileNotFoundError(f"Архив не создан: {zip_path}")
            except Exception as e:
                logging.error(f"Ошибка создания архива для {author}: {e}")
                await status_msg.edit_text(f"❌ Не удалось создать архив для {author}: {e}")
                continue

            final_zip_name = f"{subject_line}.zip"
            final_zip_name = re.sub(r'[\\/*?:"<>|]', '', final_zip_name)
            final_zip_path = os.path.join(os.path.dirname(zip_path), final_zip_name)
            try:
                os.rename(zip_path, final_zip_path)
            except Exception as e:
                logging.error(f"Ошибка переименования архива для {author}: {e}")
                final_zip_path = zip_path
                final_zip_name = os.path.basename(zip_path)

            total_mb = total_size_bytes / (1024 * 1024)
            if total_mb > max_mb:
                await status_msg.edit_text(f"📉 Общий вес {total_mb:.1f} МБ превышает лимит {max_mb} МБ. Оптимизирую...")
                for root, _, files in os.walk(author_dir):
                    for f in files:
                        if f.lower().endswith('.pdf'):
                            f_path = os.path.join(root, f)
                            c_path = f_path + ".tmp"
                            await utils.compress_pdf(f_path, c_path)
                            if os.path.exists(c_path):
                                os.remove(f_path)
                                os.rename(c_path, f_path)
                try:
                    os.remove(final_zip_path)
                except FileNotFoundError:
                    pass
                await asyncio.to_thread(shutil.make_archive, zip_basename, 'zip', author_dir)
                new_zip_path = f"{zip_basename}.zip"
                if os.path.exists(new_zip_path):
                    os.rename(new_zip_path, final_zip_path)

            if not os.path.exists(final_zip_path):
                logging.error(f"Архив не существует после всех операций: {final_zip_path}")
                await status_msg.edit_text(f"❌ Архив для {author} не создан.")
                continue

            archives_info.append((final_zip_path, final_zip_name, email_subject))

        for zip_path, zip_name, email_subj in archives_info:
            await event.bot.send_document(
                chat_id=tg_id,
                document=FSInputFile(zip_path, filename=zip_name)
            )

        email_key = uuid.uuid4().hex[:10]
        state_manager.pending_email_sends[email_key] = {
            'archives_info': archives_info,
            'target_email': target_email,
            'dept': dept,
            'tg_id': tg_id,
            'test_mode': test_mode,
        }

        if test_mode:
            recipient_line = (
                f"🧪 <b>Тестовый режим:</b> кафедра «{dept}», но письмо уйдёт на вашу почту.\n"
                f"<b>Кому (тест):</b> <code>{target_email}</code>\n"
                f"<i>(в реальной отправке ушло бы на {real_target_email})</i>\n"
            )
        else:
            recipient_line = (
                f"Отправить их на кафедру «{dept}»?\n"
                f"<b>Кому:</b> <code>{target_email}</code>\n"
            )
        review_text = (
            f"✅ <b>Архивы выше — для проверки.</b>\n\n"
            f"{recipient_line}"
            f"<b>Темы писем:</b>\n"
        )
        for subj in [info[2] for info in archives_info]:
            review_text += f"<code>{subj}</code>\n"

        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Да, отправить", callback_data=f"email_send_confirm:{email_key}:yes")
        builder.button(text="❌ Нет", callback_data=f"email_send_confirm:{email_key}:no")
        builder.adjust(2)
        state_manager.register_menu(tg_id)
        await status_msg.edit_text(review_text, parse_mode="HTML", reply_markup=builder.as_markup())

        # Меню выбора автора (Шаг 2) больше не нужно, раз архив уже собран — испаряем его,
        # чтобы не оставалось висеть в чате без дела.
        if hasattr(event, "message") and event.message and event.message.message_id != status_msg.message_id:
            asyncio.create_task(state_manager._fade_and_delete(event.bot, event.message.chat.id, event.message.message_id, delay=0.5))

    except Exception as e:
        await status_msg.edit_text(f"❌ Критическая ошибка: {str(e)}")
        logging.error(f"Portfolio error: {e}", exc_info=True)
        # При ошибке зип-файлы уже не нужны — подтверждать отправку нечего.
        for zip_path, _, _ in archives_info:
            if os.path.exists(zip_path):
                os.remove(zip_path)
    finally:
        if os.path.exists(base_dir):
            shutil.rmtree(base_dir, ignore_errors=True)
        await state.clear()


@router.callback_query(F.data.startswith("email_send_confirm:"))
async def callback_email_send_confirm(call: CallbackQuery):
    parts = call.data.split(":")
    email_key = parts[1]
    choice = parts[2]
    data = state_manager.pending_email_sends.pop(email_key, None)
    asyncio.create_task(state_manager.resolve_menu(call.bot, call.from_user.id))

    if not data:
        await _safe_edit_text(call.message, "❌ Данные устарели. Соберите архив заново через /zip_build.")
        await safe_answer(call)
        return

    archives_info = data['archives_info']
    target_email = data['target_email']
    dept = data['dept']
    test_mode = data.get('test_mode', False)

    if choice == "no":
        await _safe_edit_text(call.message, "❌ Архив не был выслан на кафедру.")
        for zip_path, _, _ in archives_info:
            if os.path.exists(zip_path):
                os.remove(zip_path)
        await safe_answer(call)
        return

    await safe_answer(call)
    await _safe_edit_text(call.message, "📧 Отправляю письма...")

    recipient_label = f"вашу почту (тест кафедры «{dept}»)" if test_mode else f"кафедру «{dept}»"
    items = [(zip_path, zip_name, subj) for zip_path, zip_name, subj in archives_info]
    results = await email_sender.send_multiple_attachments(
        to_email=target_email,
        to_name="" if test_mode else dept,
        items=items,
    )

    for zip_path, _, _ in archives_info:
        if os.path.exists(zip_path):
            os.remove(zip_path)

    ok_count = sum(1 for _, ok, _ in results if ok)
    fail_lines = [f"• {subj}: {err}" for subj, ok, err in results if not ok]

    if fail_lines:
        text = (
            f"⚠️ Отправлено {ok_count} из {len(results)} писем на {recipient_label} (<code>{target_email}</code>).\n\n"
            f"Не удалось отправить:\n" + "\n".join(fail_lines)
        )
    else:
        text = f"✅ Все письма ({ok_count}) успешно отправлены на {recipient_label} (<code>{target_email}</code>)."

    await _safe_edit_text(call.message, text, parse_mode="HTML")


# ========== ОБРАБОТЧИКИ ОЧЕРЕДЕЙ (ЗАГРУЗКА ФАЙЛОВ) ==========
@router.message(BotStates.waiting_for_works, F.document)
async def queue_work(message: Message):
    if message.document.file_size > 50 * 1024 * 1024:
        await message.answer("⚠️ Файл слишком большой (макс. 50 МБ).")
        return

    user_id = message.from_user.id
    chat_id = message.chat.id

    async with state_manager.get_batch_lock("work", user_id):
        batch = state_manager.pending_work_batches.get(user_id)
        if not batch:
            batch_dir = os.path.join("temp", f"work_batch_{user_id}_{uuid.uuid4().hex[:8]}")
            os.makedirs(batch_dir, exist_ok=True)
            status_msg = await message.answer("🔍 Первый документ принят. Формирую очередь...")
            batch = {
                "files": [],
                "batch_dir": batch_dir,
                "timer_task": None,
                "countdown_msg_id": None,
                "status_msg_id": status_msg.message_id,
                "manual_flush": False,
                "seen_file_ids": set(),
            }
            state_manager.pending_work_batches[user_id] = batch

        # Защита от повторной доставки того же апдейта Telegram (webhook retry): если
        # скачивание/обработка предыдущего апдейта заняли слишком много времени, Telegram может
        # прислать этот же документ ещё раз — без этой проверки файл добавлялся бы в очередь
        # второй раз и обрабатывался дважды параллельно (отсюда задвоенные сообщения о дубликатах).
        seen_file_ids = batch.setdefault("seen_file_ids", set())
        if message.document.file_unique_id in seen_file_ids:
            logging.info(f"⏭️ Повторная доставка файла {message.document.file_name} — пропускаю (уже в очереди)")
            return
        seen_file_ids.add(message.document.file_unique_id)

        file_path = os.path.join(batch["batch_dir"], f"{message.document.file_unique_id}_{message.document.file_name}")
        file_info = await message.bot.get_file(message.document.file_id)
        try:
            await download_file_with_retry(message.bot, file_info.file_path, file_path)
        except Exception as e:
            logging.error(f"Не удалось скачать файл работы: {e}")
            await message.answer(f"❌ Не удалось скачать файл: {e}")
            return

        if os.path.getsize(file_path) < 1000:
            await message.answer("❌ Файл скачан не полностью.")
            return

        batch["files"].append((file_path, message.document.file_name))
        state_manager._restart_work_timer(
            bot=message.bot,
            user_id=user_id,
            chat_id=chat_id,
            seconds=WORK_BATCH_IDLE_SECONDS
        )

@router.message(BotStates.waiting_for_scans, F.document)
async def queue_scan(message: Message):
    if message.document.file_size > 50 * 1024 * 1024:
        await message.answer("⚠️ Файл слишком большой (макс. 50 МБ).")
        return

    user_id = message.from_user.id
    chat_id = message.chat.id

    async with state_manager.get_batch_lock("scan", user_id):
        batch = state_manager.pending_scan_batches.get(user_id)
        if not batch:
            batch_dir = os.path.join("temp", f"scan_batch_{user_id}_{uuid.uuid4().hex[:8]}")
            os.makedirs(batch_dir, exist_ok=True)
            status_msg = await message.answer("🔍 Первый скан принят. Формирую очередь...")
            batch = {
                "files": [],
                "batch_dir": batch_dir,
                "timer_task": None,
                "countdown_msg_id": None,
                "status_msg_id": status_msg.message_id,
                "manual_flush": False,
                "seen_file_ids": set(),
            }
            state_manager.pending_scan_batches[user_id] = batch

        # Та же защита от повторной доставки апдейта, что и в queue_work — см. комментарий там.
        seen_file_ids = batch.setdefault("seen_file_ids", set())
        if message.document.file_unique_id in seen_file_ids:
            logging.info(f"⏭️ Повторная доставка скана {message.document.file_name} — пропускаю (уже в очереди)")
            return
        seen_file_ids.add(message.document.file_unique_id)

        scan_path = os.path.join(batch["batch_dir"], f"{message.document.file_unique_id}_{message.document.file_name}")
        file_info = await message.bot.get_file(message.document.file_id)
        try:
            await download_file_with_retry(message.bot, file_info.file_path, scan_path)
        except Exception as e:
            logging.error(f"Не удалось скачать скан: {e}")
            await message.answer(f"❌ Не удалось скачать файл: {e}")
            return

        if os.path.getsize(scan_path) < 1000:
            await message.answer("❌ Файл скачан не полностью.")
            return

        batch["files"].append(scan_path)
        state_manager._restart_scan_timer(
            bot=message.bot,
            user_id=user_id,
            chat_id=chat_id,
            seconds=SCAN_BATCH_IDLE_SECONDS
        )

@router.message(BotStates.waiting_for_scans, F.photo)
async def queue_scan_photo(message: Message):
    photo = message.photo[-1]
    if photo.file_size and photo.file_size > 50 * 1024 * 1024:
        await message.answer("⚠️ Файл слишком большой (макс. 50 МБ).")
        return

    user_id = message.from_user.id
    chat_id = message.chat.id
    state_manager.inc_processing(user_id)

    try:
        async with state_manager.get_batch_lock("scan", user_id):
            batch = state_manager.pending_scan_batches.get(user_id)
            if not batch:
                batch_dir = os.path.join("temp", f"scan_batch_{user_id}_{uuid.uuid4().hex[:8]}")
                os.makedirs(batch_dir, exist_ok=True)
                status_msg = await message.answer("🔍 Первое фото принято. Формирую очередь...")
                batch = {
                    "files": [],
                    "batch_dir": batch_dir,
                    "timer_task": None,
                    "countdown_msg_id": None,
                    "status_msg_id": status_msg.message_id,
                    "manual_flush": False
                }
                state_manager.pending_scan_batches[user_id] = batch

            fake_name = f"photo_{photo.file_unique_id}.jpg"
            scan_path = os.path.join(batch["batch_dir"], fake_name)
            file_info = await message.bot.get_file(photo.file_id)
            await download_file_with_retry(message.bot, file_info.file_path, scan_path)

            if os.path.getsize(scan_path) < 1000:
                await message.answer("❌ Файл скачан не полностью.")
                return

            batch["files"].append(scan_path)
            state_manager._restart_scan_timer(
                bot=message.bot,
                user_id=user_id,
                chat_id=chat_id,
                seconds=SCAN_BATCH_IDLE_SECONDS
            )
    except Exception as e:
        logging.error(f"Ошибка загрузки фото-скана: {e}")
        await message.answer(f"❌ Ошибка: {e}")
    finally:
        state_manager.dec_processing(user_id)


# ========== КОЛБЭКИ ВЫБОРА АВТОРА (для работ) ==========
@router.callback_query(F.data.startswith("author_work_sel:"))
async def callback_author_work_selection(call: CallbackQuery):
    choice = call.data.split(":")[1]
    user_id = call.from_user.id
    data = state_manager.temp_work_data.pop(user_id, None)
    asyncio.create_task(state_manager.resolve_menu(call.bot, user_id))
    if not data:
        await call.message.edit_text("❌ Данные устарели. Загрузите файл заново.")
        await safe_answer(call)
        return

    work_ids = data.get('work_ids', [])
    authors_list = data.get('authors_list', [])
    chat_id = data.get('chat_id', call.message.chat.id)
    msg_id = data.get('msg_id')
    task_dir = data.get('task_dir')
    is_duplicate = data.get('is_duplicate', False)
    final_filename = data.get('final_filename', 'work.pdf')

    # Удаляем меню
    await safe_delete(call.message)

    if choice == "close":
        if os.path.exists(task_dir):
            shutil.rmtree(task_dir, ignore_errors=True)
        await call.bot.send_message(chat_id=chat_id, text="❌ Работа не будет добавлена в архив.")
        await safe_answer(call)
        return

    if is_duplicate:
        # Обработка дубликата: добавляем выбранные копии в архив
        if choice == "all":
            sent = 0
            for wid in work_ids:
                work = await db.get_work_by_id(wid)
                if not work:
                    continue
                try:
                    tmp_dir = os.path.join("temp", f"dup_sel_{uuid.uuid4().hex[:8]}")
                    os.makedirs(tmp_dir, exist_ok=True)
                    tmp_file = os.path.join(tmp_dir, f"dup_{wid}.pdf")
                    await db.download_file(work['file_id'], tmp_file)
                    filename = work.get('filename', final_filename)
                    state_manager.queue_file_for_zip_batch(
                        bot=call.bot,
                        user_id=user_id,
                        chat_id=chat_id,
                        file_path=tmp_file,
                        filename=filename,
                        kind="work",
                        restart_timer=False
                    )
                    sent += 1
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                except Exception as e:
                    logging.error(f"Ошибка добавления дубликата {wid}: {e}")
            await call.message.answer(f"✅ Добавлены в архив копии для всех авторов ({sent} файлов).")
            state_manager._restart_batch_timer(
                bot=call.bot,
                user_id=user_id,
                chat_id=chat_id,
                seconds=ZIP_BATCH_REDUCED_SECONDS,
                kind="work"
            )
            if os.path.exists(task_dir):
                shutil.rmtree(task_dir, ignore_errors=True)
            await safe_answer(call)
            return

        try:
            idx = int(choice)
            if idx < 0 or idx >= len(work_ids):
                raise ValueError()
            wid = work_ids[idx]
            work = await db.get_work_by_id(wid)
            if not work:
                await call.message.answer("❌ Работа не найдена.")
                await safe_answer(call)
                return
            tmp_dir = os.path.join("temp", f"dup_sel_{uuid.uuid4().hex[:8]}")
            os.makedirs(tmp_dir, exist_ok=True)
            tmp_file = os.path.join(tmp_dir, f"dup_{wid}.pdf")
            await db.download_file(work['file_id'], tmp_file)
            filename = work.get('filename', final_filename)
            state_manager.queue_file_for_zip_batch(
                bot=call.bot,
                user_id=user_id,
                chat_id=chat_id,
                file_path=tmp_file,
                filename=filename,
                kind="work",
                restart_timer=True
            )
            await call.message.answer(f"✅ Добавлено в архив для {authors_list[idx]}.")
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception as e:
            await call.message.answer(f"❌ Ошибка: {e}")
        finally:
            if os.path.exists(task_dir):
                shutil.rmtree(task_dir, ignore_errors=True)
        await safe_answer(call)
        return

    # Обычный режим – сохранение новой работы
    if choice == "all":
        sent = 0
        for work_id in work_ids:
            work = await db.get_work_by_id(work_id)
            if not work:
                continue
            temp_file = os.path.join(task_dir, f"download_{work_id}.pdf")
            await db.download_file(work['file_id'], temp_file)
            state_manager.queue_file_for_zip_batch(
                bot=call.bot,
                user_id=user_id,
                chat_id=chat_id,
                file_path=temp_file,
                filename=work.get('filename', final_filename),
                kind="work",
                restart_timer=False
            )
            sent += 1
        await call.message.answer(f"✅ Добавлены в архив копии для всех авторов ({sent} файлов).")
        state_manager._restart_batch_timer(
            bot=call.bot,
            user_id=user_id,
            chat_id=chat_id,
            seconds=ZIP_BATCH_REDUCED_SECONDS,
            kind="work"
        )
        if os.path.exists(task_dir):
            shutil.rmtree(task_dir, ignore_errors=True)
        await safe_answer(call)
        return

    try:
        idx = int(choice)
        if idx < 0 or idx >= len(work_ids):
            raise ValueError()
        work_id = work_ids[idx]
        work = await db.get_work_by_id(work_id)
        if not work:
            await call.message.answer("❌ Работа не найдена в БД.")
            await safe_answer(call)
            return

        temp_file = os.path.join(task_dir, f"download_{work_id}.pdf")
        await db.download_file(work['file_id'], temp_file)
        state_manager.queue_file_for_zip_batch(
            bot=call.bot,
            user_id=user_id,
            chat_id=chat_id,
            file_path=temp_file,
            filename=work.get('filename', final_filename),
            kind="work",
            restart_timer=True
        )
        await call.message.answer(f"✅ Успешно сохранено для {authors_list[idx]}.")
        state_manager._restart_batch_timer(
            bot=call.bot,
            user_id=user_id,
            chat_id=chat_id,
            seconds=ZIP_BATCH_REDUCED_SECONDS,
            kind="work"
        )
    except Exception as e:
        await call.message.answer(f"❌ Ошибка: {e}")
    finally:
        if os.path.exists(task_dir):
            shutil.rmtree(task_dir, ignore_errors=True)
    await safe_answer(call)


# ========== КОЛБЭКИ ВЫБОРА АВТОРА ДЛЯ СКАНОВ ==========
@router.callback_query(F.data.startswith("sa_btn:"))
async def callback_scan_author_selection(call: CallbackQuery):
    parts = call.data.split(":")
    req_id = parts[1]
    idx_str = parts[2]
    user_id = call.from_user.id
    await safe_answer(call)

    author_map = state_manager.temp_scan_authors.pop(req_id, None)
    if not author_map:
        await safe_delete(call.message)
        return

    await safe_delete(call.message)

    if idx_str == "close":
        state_manager.scan_menus_active.discard(user_id)
        asyncio.create_task(state_manager.resolve_menu(call.bot, user_id))
        state_manager.pending_scan_ready_files.pop(user_id, None)
        state_manager._restart_batch_timer(
            bot=call.bot,
            user_id=user_id,
            chat_id=call.message.chat.id,
            seconds=ZIP_BATCH_IDLE_SECONDS,
            kind="scan"
        )
        return

    selection = author_map[idx_str]
    work = await db.get_work_by_id(selection['wid'])
    if not work:
        await call.message.answer("❌ Работа не найдена.")
        state_manager.scan_menus_active.discard(user_id)
        asyncio.create_task(state_manager.resolve_menu(call.bot, user_id))
        state_manager.pending_scan_ready_files.pop(user_id, None)
        return

    ready_files = state_manager.pending_scan_ready_files.get(user_id, {})
    if not ready_files:
        await call.message.answer("❌ Нет готовых файлов для отправки.")
        state_manager.scan_menus_active.discard(user_id)
        asyncio.create_task(state_manager.resolve_menu(call.bot, user_id))
        return

    if selection['type'] == 'all':
        sent = 0
        for wid_str, (file_path, filename, author) in ready_files.items():
            if os.path.exists(file_path):
                state_manager.queue_file_for_zip_batch(
                    bot=call.bot,
                    user_id=user_id,
                    chat_id=call.message.chat.id,
                    file_path=file_path,
                    filename=filename,
                    kind="scan",
                    restart_timer=False
                )
                sent += 1
        await call.message.answer(f"✅ Добавлены в архив копии для всех авторов ({sent} файлов).")
    else:
        author_name = selection['author']
        target_wid = None
        for wid_str, (file_path, filename, author) in ready_files.items():
            if author == author_name:
                target_wid = wid_str
                break
        if target_wid and os.path.exists(ready_files[target_wid][0]):
            state_manager.queue_file_for_zip_batch(
                bot=call.bot,
                user_id=user_id,
                chat_id=call.message.chat.id,
                file_path=ready_files[target_wid][0],
                filename=ready_files[target_wid][1],
                kind="scan",
                restart_timer=True
            )
            await call.message.answer(f"✅ Добавлен в архив файл для {author_name}.")
        else:
            await call.message.answer(f"❌ Файл для {author_name} не найден.")

    state_manager.pending_scan_ready_files.pop(user_id, None)
    state_manager.scan_menus_active.discard(user_id)
    asyncio.create_task(state_manager.resolve_menu(call.bot, user_id))
    state_manager._restart_batch_timer(
        bot=call.bot,
        user_id=user_id,
        chat_id=call.message.chat.id,
        seconds=ZIP_BATCH_REDUCED_SECONDS,
        kind="scan"
    )

    # Очистка временной папки
    if ready_files:
        first_path = next(iter(ready_files.values()))[0]
        task_dir = os.path.dirname(first_path)
        if os.path.exists(task_dir):
            has_repl = any(v.get('task_dir') == task_dir for v in state_manager.pending_replacements.values())
            if not has_repl:
                shutil.rmtree(task_dir, ignore_errors=True)


# ========== КОЛБЭКИ ПОДТВЕРЖДЕНИЯ ДУБЛИКАТОВ ==========
@router.callback_query(F.data.startswith("dup_confirm:"))
async def callback_dup_confirm(call: CallbackQuery):
    parts = call.data.split(":")
    dup_key = parts[1]
    choice = parts[2]
    data = state_manager.temp_work_data.pop(dup_key, None)
    if not data:
        await call.message.edit_text("❌ Данные устарели. Загрузите файл заново.")
        asyncio.create_task(state_manager._fade_and_delete(call.bot, call.message.chat.id, call.message.message_id, delay=3.0))
        await safe_answer(call)
        return

    work = data['work']
    parsed = data['parsed']
    chat_id = data.get('chat_id', call.message.chat.id)
    msg_id = data.get('msg_id')
    task_dir = data.get('task_dir')
    user_id = call.from_user.id
    asyncio.create_task(state_manager.resolve_menu(call.bot, user_id))

    if choice == "no":
        await call.message.edit_text("❌ Работа не будет добавлена в архив.")
        if os.path.exists(task_dir):
            shutil.rmtree(task_dir, ignore_errors=True)
        # Даже если эта конкретная работа не добавляется в архив, в очереди могли уже
        # накопиться другие НОВЫЕ файлы (добавленные с restart_timer=False в ожидании,
        # что таймер перезапустит последний). Если не перезапустить таймер здесь, эти
        # файлы так и останутся в очереди и архив никогда не будет отправлен.
        state_manager._restart_batch_timer(
            bot=call.bot,
            user_id=user_id,
            chat_id=chat_id,
            seconds=ZIP_BATCH_REDUCED_SECONDS,
            kind="work"
        )
        await safe_answer(call)
        return

    file_id = work.get('file_id')
    if not file_id:
        await call.message.edit_text("❌ Ошибка: у работы нет файла.")
        asyncio.create_task(state_manager._fade_and_delete(call.bot, call.message.chat.id, call.message.message_id, delay=3.0))
        await safe_answer(call)
        return

    authors = work.get('authors', [])
    if not authors:
        authors = [work.get('author') or "Неизвестный автор"]

    related = await db.get_related_works_for_scan(user_id, work['_id'])
    if not related:
        related = [work]
    work_ids = [rw['_id'] for rw in related]

    # Если несколько авторов – показываем меню выбора
    if len(authors) > 1:
        state_manager.temp_work_data[user_id] = {
            'work_ids': work_ids,
            'authors_list': authors,
            'metadata': parsed,
            'chat_id': chat_id,
            'msg_id': msg_id,
            'task_dir': task_dir,
            'final_filename': work.get('filename', 'work.pdf'),
            'is_duplicate': True
        }
        builder = InlineKeyboardBuilder()
        for idx, author in enumerate(authors):
            builder.button(text=author, callback_data=f"author_work_sel:{idx}")
        builder.button(text="✅ Всех", callback_data="author_work_sel:all")
        builder.button(text="❌ Закрыть", callback_data="author_work_sel:close")
        builder.adjust(2)
        state_manager.register_menu(user_id)
        await call.message.edit_text(
            "🔍 Найдено несколько авторов. Выберите, кого добавить в архив:",
            reply_markup=builder.as_markup()
        )
        
        if hasattr(state_manager, 'pending_work_batches') and user_id in state_manager.pending_work_batches:
            batch = state_manager.pending_work_batches[user_id]
            if batch.get("reminder_msg_id"):
                asyncio.create_task(state_manager._fade_and_delete(call.bot, call.message.chat.id, batch["reminder_msg_id"], delay=0))
                batch["reminder_msg_id"] = None

        state_manager.temp_work_data[user_id]['menu_msg_id'] = call.message.message_id

        asyncio.create_task(state_manager._send_menu_reminder(call.bot, call.message.chat.id, user_id))
        
        await safe_answer(call)
        return

    try:
        tmp_dir = os.path.join("temp", f"dup_download_{uuid.uuid4().hex[:8]}")
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_file = os.path.join(tmp_dir, f"dup_{work['_id']}.pdf")
        await db.download_file(file_id, tmp_file)
        filename = work.get('filename', f"{parsed.get('group')}_{parsed.get('author')}_{parsed.get('subject')}.pdf")
        state_manager.queue_file_for_zip_batch(
            bot=call.bot,
            user_id=user_id,
            chat_id=chat_id,
            file_path=tmp_file,
            filename=filename,
            kind="work",
            restart_timer=True
        )
        await call.message.edit_text("✅ Работа добавлена в архив для отправки.")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if os.path.exists(task_dir):
            shutil.rmtree(task_dir, ignore_errors=True)
    except Exception as e:
        await call.message.edit_text(f"❌ Не удалось добавить работу в архив: {e}")
        asyncio.create_task(state_manager._fade_and_delete(call.bot, call.message.chat.id, call.message.message_id, delay=3.0))
    await safe_answer(call)


# ========== КОЛБЭКИ ПОДТВЕРЖДЕНИЯ ЗАМЕНЫ СТРАНИЦ ==========
async def _safe_edit_text(message, text, **kwargs):
    """edit_text может упасть с 'message is not modified' (повторная доставка того же
    колбэка от Telegram) — это не критично, просто игнорируем."""
    try:
        await message.edit_text(text, **kwargs)
    except TelegramBadRequest as e:
        logging.warning(f"⚠️ edit_text не удался (вероятно, повторный колбэк): {e}")


@router.callback_query(F.data.startswith("replace_confirm:"))
async def callback_replace_confirm(call: CallbackQuery):
    parts = call.data.split(":")
    key = parts[1]
    choice = parts[2]
    data = state_manager.pending_replacements.pop(key, None)
    if not data:
        await safe_answer(call)
        await _safe_edit_text(call.message, "❌ Данные устарели. Попробуйте заново.")
        return

    # Отвечаем на callback СРАЗУ — иначе кнопка "висит" без реакции всё то время, пока идёт
    # скачивание файла, замена страниц и обновление БД (это может занимать много секунд).
    await safe_answer(call)

    task_dir = data.get('task_dir')
    user_id = data['user_id']
    asyncio.create_task(state_manager.resolve_menu(call.bot, user_id))

    def _batch_still_pending() -> bool:
        if task_dir in state_manager.active_scan_batches:
            # Цикл распознавания страниц этой пачки ещё не завершён — не все меню
            # "уже заменено?" вообще успели появиться, рано считать пачку разрешённой.
            return True
        if state_manager.active_replace_tasks.get(task_dir, 0) > 0:
            # Есть ещё фоновые задачи применения замены — запись в pending_replacements уже
            # удалена (она удаляется сразу при нажатии кнопки), но реальная работа
            # (скачивание/замена/апдейты БД) ещё не закончена.
            return True
        return any(v.get('task_dir') == task_dir for v in state_manager.pending_replacements.values())

    if choice == "no":
        await _safe_edit_text(call.message, "✅ Лист оставлен без изменений.")
        if task_dir and os.path.exists(task_dir) and not _batch_still_pending() and user_id not in state_manager.scan_menus_active:
            shutil.rmtree(task_dir, ignore_errors=True)
        await _finalize_batch_if_done(call.bot, call.message.chat.id, user_id, task_dir, _batch_still_pending)
        return

    # Мгновенная обратная связь — сам обработчик колбэка на этом ЗАВЕРШАЕТСЯ (не блокирует
    # ответ вебхука Telegram), а вся тяжёлая работа продолжается в фоновой задаче ниже.
    await _safe_edit_text(call.message, "⏳ Применяю замену...")
    state_manager.inc_replace_task(task_dir)
    asyncio.create_task(_apply_replace_confirm_yes(call, data, task_dir, _batch_still_pending))


async def _apply_replace_confirm_yes(call: CallbackQuery, data: dict, task_dir: str, _batch_still_pending):
    """
    Вся тяжёлая работа по применению подтверждённой замены страницы — вынесена в фоновую
    задачу из callback_replace_confirm, чтобы сам обработчик колбэка отвечал мгновенно и не
    держал открытым HTTP-ответ вебхука Telegram (это и вызывало повторные доставки того же
    апдейта при долгой обработке — отсюда "тугие кнопки" и задвоенные "Данные устарели").
    """
    work_id = data['work_id']
    page_num = data['page_num']
    page_path = data['page_path']
    work = data['work']
    user_id = data['user_id']
    scan_text = data.get('scan_text')

    # Если цикл распознавания страниц ЭТОЙ ЖЕ пачки сканов ещё не завершён — ждём. Иначе
    # применение замены (которое меняет file_id/replaced_pages работы) могло бы гоняться
    # параллельно с ещё бегущим циклом, который читает ту же работу по старому снимку —
    # отсюда и "случайные" перепутанные страницы/авторы в результате. Это безопасно ждать
    # здесь долго, т.к. мы уже в фоновой задаче и не блокируем ответ вебхука.
    wait_elapsed = 0.0
    while task_dir in state_manager.active_scan_batches and wait_elapsed < 180:
        await asyncio.sleep(1)
        wait_elapsed += 1
    if wait_elapsed >= 180:
        logging.warning(f"⚠️ Пачка {task_dir} не завершилась за 180с ожидания — применяю замену как есть")

    try:
        # Работу берём заново из БД, а не из устаревшего снимка data['work'], сделанного в момент
        # показа меню. Если на один и тот же work_id было два независимых запроса на замену
        # (например, два разных "уже заменённых" листа одной мультиавторской работы), снимок
        # мог устареть после первого подтверждения — и вторая замена накатывалась бы поверх
        # старого file_id, стирая первую замену. Берём актуальный файл прямо перед заменой.
        fresh_work = await db.get_work_by_id(work_id)
        if not fresh_work:
            fresh_work = work

        temp_dir = os.path.join("temp", f"replace_{uuid.uuid4().hex[:8]}")
        os.makedirs(temp_dir, exist_ok=True)
        orig_path = os.path.join(temp_dir, "original.pdf")
        out_path = os.path.join(temp_dir, "updated.pdf")

        await db.download_file(fresh_work['file_id'], orig_path)

        repl_dict = {page_num - 1: page_path}
        await asyncio.to_thread(utils.replace_specific_pages, orig_path, repl_dict, out_path)

        with open(out_path, "rb") as f:
            updated_bytes = f.read()

        related = await db.get_related_works_for_scan(user_id, work_id)
        if not related:
            related = [fresh_work]
        expected_authors = fresh_work.get('authors', [])
        if expected_authors and len(related) < len(expected_authors):
            logging.warning(
                f"⚠️ get_related_works_for_scan вернул {len(related)} записей, "
                f"а у работы {work_id} указано {len(expected_authors)} авторов ({expected_authors}) — "
                f"file_id-связка между копиями авторов, похоже, разорвана."
            )

        work_ids = [rw["_id"] for rw in related]
        new_replaced = fresh_work.get("replaced_pages", [])
        if page_num not in new_replaced:
            new_replaced.append(page_num)
            new_replaced.sort()

        first_work = related[0] if related else fresh_work
        await db.update_multiple_works_with_scan(
            work_ids=work_ids,
            file_bytes=updated_bytes,
            new_filename=first_work['filename'],
            new_replaced_pages=new_replaced,
        )

        # Обновляем текст этой страницы в pages, чтобы последующий текстовый поиск (в том
        # числе поиск страницы отзыва) сравнивался с АКТУАЛЬНЫМ содержимым, а не с текстом
        # старой, уже заменённой страницы, который иначе оставался бы в индексе навсегда.
        if scan_text:
            try:
                await db.update_pages_text(work_ids, page_num, scan_text)
            except Exception as e:
                logging.warning(f"⚠️ Не удалось обновить текст страницы в pages: {e}")

        # Основная работа (скачивание/замена/апдейты БД) сделана — снимаем себя со счётчика
        # активных фоновых задач ДО проверок "пачка ещё не разрешена" ниже (показ меню
        # авторов, перезапуск таймера архива), иначе эта же самая задача считала бы себя
        # "ещё не завершённой" и пачка никогда не выглядела бы полностью разрешённой.
        state_manager.dec_replace_task(task_dir)

        authors = fresh_work.get('authors', [])
        chat_id = call.message.chat.id

        # Статистика по подписи для титульного листа — как в первичной обработке, только
        # теперь и для замены уже существующей (дублирующейся) страницы, а не только при
        # первом распознавании. Раньше эта проверка при подтверждении замены не делалась вовсе.
        signature_note = ""
        has_sig = None
        if page_num == 1:
            try:
                with open(page_path, "rb") as f:
                    page_bytes = f.read()
                has_sig, reason, detail = await utils.detect_signature_async(scan_text or "", page_bytes)
                signature_note = "\n\n✅ Подпись найдена" if has_sig else "\n\n⚠️ Подпись не обнаружена"
            except Exception as e:
                logging.warning(f"⚠️ Не удалось проверить подпись при замене: {e}")

        # Копим статистику по всем подтверждённым заменам этой пачки — сводку покажем одним
        # сообщением, когда будет разрешено последнее меню (аналог финальной статистики
        # обычного потока, которой раньше для дублирующихся сканов не было вовсе).
        stats_list = state_manager.pending_replace_stats.setdefault(task_dir, [])
        stats_list.append({
            'page_num': page_num,
            'filename': fresh_work.get('filename', 'неизвестная'),
            'has_signature': has_sig,
        })

        if len(authors) > 1 and len(related) > 1:
            subject_name = fresh_work.get('full_subject') or fresh_work.get('subject') or 'неизвестный предмет'
            await _safe_edit_text(
                call.message,
                f"✅ Стр. {page_num} в работе заменена для всех авторов работы «Предмет: {subject_name}».{signature_note}"
            )

            # Копим файлы для меню выбора авторов вместо немедленного показа — если в этой же
            # пачке сканов есть ещё нерешённые "уже заменено?" запросы, дождёмся их всех и
            # покажем ОДНО общее меню в конце, а не отдельное окно на каждое "да".
            existing_ready = state_manager.pending_scan_ready_files.get(user_id, {})
            for rw in related:
                rw_author = rw.get('author') or (rw.get('authors') or ['Автор'])[0]
                existing_ready[str(rw['_id'])] = (out_path, rw.get('filename', first_work['filename']), rw_author)
            state_manager.pending_scan_ready_files[user_id] = existing_ready
            # Само меню выбора автора строится централизованно ниже (блок финализации),
            # когда выяснится, что пачка полностью разрешена — независимо от того, какая
            # именно ветка (эта, много-авторская, или одноавторская) была последней.
        else:
            # Один автор — ставим обновлённый файл в архив. Перезапускаем таймер сборки .zip
            # только если в этой же пачке не осталось других нерешённых меню — иначе таймер
            # (и сообщение "архив будет собран через ...") стартует раньше, чем пользователь
            # ответит на все вопросы по пачке.
            still_pending = _batch_still_pending()
            await _safe_edit_text(call.message, f"✅ Стр. {page_num} в работе успешно заменена в работе «{fresh_work.get('filename', 'неизвестная')}».{signature_note}")
            state_manager.queue_file_for_zip_batch(
                bot=call.bot,
                user_id=user_id,
                chat_id=chat_id,
                file_path=out_path,
                filename=first_work.get('filename', 'work.pdf'),
                kind="scan",
                restart_timer=not still_pending
            )

        if task_dir and os.path.exists(task_dir):
            has_repl = _batch_still_pending()
            if not has_repl and user_id not in state_manager.scan_menus_active:
                shutil.rmtree(task_dir, ignore_errors=True)

        # Если это было последнее меню пачки — показываем сводную статистику по всем
        # подтверждённым заменам (страницы + подписи), аналог финального сообщения
        # обычного (не-дублирующего) потока, которого для этого пути раньше не было.
        await _finalize_batch_if_done(call.bot, call.message.chat.id, user_id, task_dir, _batch_still_pending)
    except Exception as e:
        logging.error(f"Ошибка применения замены: {e}")
        state_manager.dec_replace_task(task_dir)
        await _safe_edit_text(call.message, f"❌ Ошибка замены: {e}")


async def _finalize_batch_if_done(bot, chat_id, user_id, task_dir, _batch_still_pending):
    """
    Если пачка полностью разрешена (нет больше нерешённых "уже заменено?" запросов и
    цикл распознавания завершён) — показывает сводную статистику по всем подтверждённым
    заменам и, если накопились файлы для меню выбора автора (из этой ветки confirm-потока
    ИЛИ из прямых совпадений основного цикла), показывает ОДНО общее меню.
    Вызывается и из "Да" (после фоновой замены), и из "Нет" — на случай, если именно
    отказ оказался последним нерешённым вопросом пачки.
    """
    if _batch_still_pending():
        return

    wait_msg_info = state_manager.pending_wait_messages.pop(task_dir, None)
    if wait_msg_info:
        wait_chat_id, wait_msg_id = wait_msg_info
        asyncio.create_task(state_manager._fade_and_delete(bot, wait_chat_id, wait_msg_id, delay=0.5))

    stats_list = state_manager.pending_replace_stats.pop(task_dir, [])
    if stats_list:
        total = len(stats_list)
        titles = [s for s in stats_list if s['page_num'] == 1]
        signed = len([s for s in titles if s['has_signature']])
        lines = [f"📊 <b>Подтверждённые замены обработаны.</b> Всего листов: {total}."]
        if titles:
            lines.append(f"\n📋 Проверка титульных листов:\nВсего титулов: {len(titles)}, с подписью: {signed}")
        lines.append("\n✅ <b>Замены:</b>")
        for s in sorted(stats_list, key=lambda x: x['page_num']):
            lines.append(f"• Стр. {s['page_num']} в работе ➡️ {s['filename']}")
        try:
            await bot.send_message(chat_id=chat_id, text="\n".join(lines), parse_mode="HTML")
        except Exception as e:
            logging.warning(f"⚠️ Не удалось отправить сводку по заменам: {e}")

    # Показываем меню выбора авторов, если что-то накопилось — из этой (много-
    # авторской) ветки confirm-потока ИЛИ из прямых совпадений основного цикла
    # (background_scan_batch_processing), которые тоже откладывали показ меню,
    # пока в пачке оставались нерешённые "уже заменено?" запросы.
    existing_ready = state_manager.pending_scan_ready_files.pop(user_id, None)
    if existing_ready:
        builder = InlineKeyboardBuilder()
        req_id = uuid.uuid4().hex[:8]
        author_map = {}
        b_idx = 0
        unique_authors = set()
        for wid_str, (_, _, author_name) in existing_ready.items():
            if author_name:
                unique_authors.add(author_name)
        any_wid = next(iter(existing_ready.keys()))
        for author_name in sorted(unique_authors):
            author_map[str(b_idx)] = {'wid': any_wid, 'author': author_name, 'type': 'single'}
            builder.button(text=author_name, callback_data=f"sa_btn:{req_id}:{b_idx}")
            b_idx += 1
        author_map[str(b_idx)] = {'wid': any_wid, 'type': 'all'}
        builder.button(text="✅ Всех", callback_data=f"sa_btn:{req_id}:{b_idx}")
        b_idx += 1
        builder.button(text="❌ Закрыть", callback_data=f"sa_btn:{req_id}:close")
        builder.adjust(2)

        state_manager.pending_scan_ready_files[user_id] = existing_ready
        state_manager.temp_scan_authors[req_id] = author_map
        state_manager.scan_menus_active.add(user_id)
        state_manager.register_menu(user_id)
        try:
            await bot.send_message(
                chat_id=chat_id,
                text="🔍 Замена применена. Выберите, кого добавить в архив:",
                reply_markup=builder.as_markup()
            )
        except Exception as e:
            logging.warning(f"⚠️ Не удалось показать меню выбора авторов: {e}")
            state_manager.pending_scan_ready_files.pop(user_id, None)


# ========== КОЛБЭКИ "ОТПРАВИТЬ СЕЙЧАС" ==========
@router.callback_query(F.data.startswith("send_now_btn:"))
async def callback_send_now_btn(call: CallbackQuery):
    kind = call.data.split(":")[1]
    user_id = call.from_user.id

    if kind == "work":
        batch = state_manager.pending_work_batches.get(user_id)
    else:
        batch = state_manager.pending_scan_batches.get(user_id)

    if batch and batch.get("timer_task") and not batch["timer_task"].done():
        batch["timer_task"].cancel()

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, запустить", callback_data=f"confirm_send_now:yes:{kind}")
    builder.button(text="❌ Нет, подождать", callback_data=f"confirm_send_now:no:{kind}")
    builder.adjust(1)

    text = "Запустить обработку досрочно?" if kind == "work" else "Сшить и распознать сканы досрочно?"
    try:
        await call.message.edit_text(text, reply_markup=builder.as_markup())
    except TelegramBadRequest:
        pass

@router.callback_query(F.data.startswith("confirm_send_now:"))
async def callback_confirm_send_now(call: CallbackQuery):
    parts = call.data.split(":")
    choice = parts[1]
    kind = parts[2] if len(parts) > 2 else "work"
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    if choice == "no":
        try:
            await call.message.edit_text("👌 Хорошо, продолжаю ждать остальные файлы.")
        except TelegramBadRequest:
            pass
        if kind == "work":
            state_manager._restart_work_timer(
                bot=call.bot,
                user_id=user_id,
                chat_id=chat_id,
                seconds=WORK_BATCH_IDLE_SECONDS
            )
        else:
            state_manager._restart_scan_timer(
                bot=call.bot,
                user_id=user_id,
                chat_id=chat_id,
                seconds=SCAN_BATCH_IDLE_SECONDS
            )
        return

    # Удаляем сообщение с кнопками
    await safe_delete(call.message)
    start_msg = await call.message.answer("📦 Запускаю досрочно...")
    asyncio.create_task(state_manager._fade_and_delete(call.bot, chat_id, start_msg.message_id, delay=2.5))

    if kind == "work":
        batch = state_manager.pending_work_batches.get(user_id)
        if batch:
            batch["manual_flush"] = True
            if batch.get("timer_task") and not batch["timer_task"].done():
                batch["timer_task"].cancel()
            if batch.get("countdown_msg_id"):
                try:
                    msg_id = batch["countdown_msg_id"]
                    await call.bot.delete_message(chat_id, msg_id)
                except Exception:
                    pass
                batch["countdown_msg_id"] = None
        await state_manager._flush_work_batch(call.bot, user_id, chat_id)
    else:
        batch = state_manager.pending_scan_batches.get(user_id)
        if batch:
            batch["manual_flush"] = True
            if batch.get("timer_task") and not batch["timer_task"].done():
                batch["timer_task"].cancel()
            if batch.get("countdown_msg_id"):
                try:
                    msg_id = batch["countdown_msg_id"]
                    await call.bot.delete_message(chat_id, msg_id)
                except Exception:
                    pass
                batch["countdown_msg_id"] = None
        await state_manager._flush_scan_batch(call.bot, user_id, chat_id)


# ========== КОЛБЭКИ "ОТПРАВИТЬ СЕЙЧАС" ДЛЯ ОБЩЕГО .ZIP-АРХИВА ==========
@router.callback_query(F.data.startswith("send_now_zip:"))
async def callback_send_now_zip_btn(call: CallbackQuery):
    kind = call.data.split(":")[1]
    user_id = call.from_user.id
    key = (user_id, kind)

    batch = state_manager.pending_zip_batches.get(key)
    if batch and batch.get("timer_task") and not batch["timer_task"].done():
        batch["timer_task"].cancel()

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, собрать", callback_data=f"confirm_send_now_zip:yes:{kind}")
    builder.button(text="❌ Нет, подождать", callback_data=f"confirm_send_now_zip:no:{kind}")
    builder.adjust(1)

    try:
        await call.message.edit_text("Собрать .zip-архив досрочно?", reply_markup=builder.as_markup())
    except TelegramBadRequest:
        pass

@router.callback_query(F.data.startswith("confirm_send_now_zip:"))
async def callback_confirm_send_now_zip(call: CallbackQuery):
    parts = call.data.split(":")
    choice = parts[1]
    kind = parts[2] if len(parts) > 2 else "work"
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    key = (user_id, kind)

    if choice == "no":
        try:
            await call.message.edit_text("👌 Хорошо, продолжаю ждать остальные файлы.")
        except TelegramBadRequest:
            pass
        state_manager._restart_batch_timer(
            bot=call.bot,
            user_id=user_id,
            chat_id=chat_id,
            seconds=ZIP_BATCH_IDLE_SECONDS,
            kind=kind
        )
        return

    await safe_delete(call.message)
    start_msg = await call.message.answer("📦 Собираю архив досрочно...")
    asyncio.create_task(state_manager._fade_and_delete(call.bot, chat_id, start_msg.message_id, delay=2.5))

    batch = state_manager.pending_zip_batches.get(key)
    if batch and batch.get("timer_task") and not batch["timer_task"].done():
        batch["timer_task"].cancel()
    await state_manager._flush_zip_batch(call.bot, user_id, chat_id, kind)


# ========== ВОРКЕР ОЧЕРЕДИ ==========
async def main_queue_worker(bot: Bot):
    logging.info("✅ [Очередь] Бесконечный асинхронный воркер запущен.")
    while True:
        try:
            task = await processing_queue.get()
            task_type = task.get('type')

            if task_type == 'work':
                # Запускаем обработку одной работы
                asyncio.create_task(background_work_processing(bot, task))
            elif task_type == 'scan_batch':
                asyncio.create_task(background_scan_batch_processing(bot, task))

        except Exception as e:
            logging.error(f"Критическая ошибка в цикле воркера очереди: {e}")
        finally:
            processing_queue.task_done()
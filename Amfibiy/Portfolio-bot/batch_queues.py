import os
import re
import shutil
import asyncio
import logging
import uuid
from aiogram import Bot
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton

processing_queue = asyncio.Queue()

ZIP_BATCH_IDLE_SECONDS = 30 
ZIP_BATCH_REDUCED_SECONDS = 45 
ZIP_COUNTDOWN_STEP_SECONDS = 5

# Отдельная, увеличенная задержка для сбора файлов работ через /add_work
# (чтобы не спамить уведомлениями при быстрой отправке нескольких файлов подряд).
WORK_BATCH_IDLE_SECONDS = 60

# Та же логика для /add_scan — задержка перед запуском сшивки сканов.
SCAN_BATCH_IDLE_SECONDS = 60

# Debounce-пауза перед отправкой (или пересозданием) счётчика "через N сек будет..."
# Нужна, чтобы при быстрой пачке файлов подряд успеть досчитать финальное число
# и отправить одно сообщение, а не по одному на каждый файл.
COUNTDOWN_DEBOUNCE_SECONDS = 2.5


class BotStateManager:
    def __init__(self):
        self.pending_work_batches = {}
        self.pending_scan_batches = {}
        self.pending_zip_batches = {}
        self.temp_work_data = {}
        self.active_processing_count = {}
        self.scan_menus_active = set()
        self.pending_replacements = {}
        self.temp_scan_authors = {}
        self.pending_scan_ready_files = {}
        self.menu_reminder_msgs = {}
        # Глобальный флаг: чтобы напоминание "Нажмите все меню" не дублировалось,
        # если сразу несколько батчей (work/scan/zip) одновременно ждут выбора.
        self.menu_reminder_active = set()
        # Счётчик одновременно открытых меню на пользователя (выбор автора,
        # подтверждение дубликата, подтверждение замены листа и т.д.).
        # Напоминание должно оставаться, пока не закрыты ВСЕ меню, а не первое попавшееся.
        self.open_menu_counts = {}

        # Множество task_dir пачек сканов, которые ещё обрабатываются (цикл по страницам не
        # завершён). Нужно, чтобы отличать "меню ещё не появились, потому что цикл не дошёл
        # до этой страницы" от "все меню пачки реально закрыты" — иначе меню выбора авторов
        # или таймер архива могли сработать раньше времени, пока не все "уже заменено?"
        # запросы вообще успели создаться.
        self.active_scan_batches = set()

        # Счётчик фоновых задач применения подтверждённой замены (_apply_replace_confirm_yes),
        # которые ещё выполняются, по task_dir. Запись в pending_replacements удаляется сразу
        # при нажатии кнопки — но сама тяжёлая работа (скачивание, замена, апдейты БД) продолжается
        # в фоне ещё какое-то время. Без этого счётчика "пачка полностью разрешена" могло
        # определяться преждевременно — архив уходил, пока другая замена ещё не сохранилась.
        self.active_replace_tasks = {}

        # Накопитель статистики по заменам, применённым через confirm-меню ("уже заменено?"),
        # по task_dir: список {page_num, filename, has_signature}. Раньше для этого потока
        # никакой сводной статистики не было вовсе — только отдельные сообщения по каждому
        # листу. Показываем сводку, когда последнее меню пачки разрешено.
        self.pending_replace_stats = {}

        # message_id сообщения "⏳ Ожидается подтверждение для N листов" по task_dir —
        # нужно, чтобы аккуратно "испарить" его, когда пользователь ответит на все меню
        # пачки, а не оставлять висеть в чате навсегда.
        self.pending_wait_messages = {}

        # Архивы, собранные командой /zip_build и ожидающие подтверждения реальной отправки
        # на почту (кафедра или личная тестовая почта) через Brevo API.
        self.pending_email_sends = {}

        # Per-user блокировки для сериализации создания/пополнения пачек файлов (work/scan).
        # Раньше при параллельной обработке апдейтов (после перехода на fire-and-forget
        # вебхук в bot.py) несколько файлов, присланных почти одновременно, могли пройти
        # проверку "есть ли уже пачка для этого пользователя" ОДНОВРЕМЕННО, оба увидеть "нет"
        # и создать каждый СВОЮ пачку — вторая просто перезаписывала первую в словаре, и файлы
        # из первой терялись навсегда (отсюда "скинул 9 файлов, увидел 7").
        self._batch_locks = {}

        def _get_batch_lock(kind: str, user_id: int) -> asyncio.Lock:
            key = (kind, user_id)
            lock = self._batch_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._batch_locks[key] = lock
            return lock

        self.get_batch_lock = _get_batch_lock

        def _inc_replace_task(task_dir: str):
            if not task_dir:
                return
            self.active_replace_tasks[task_dir] = self.active_replace_tasks.get(task_dir, 0) + 1

        def _dec_replace_task(task_dir: str):
            if not task_dir:
                return
            remaining = self.active_replace_tasks.get(task_dir, 0) - 1
            if remaining <= 0:
                self.active_replace_tasks.pop(task_dir, None)
            else:
                self.active_replace_tasks[task_dir] = remaining

        self.inc_replace_task = _inc_replace_task
        self.dec_replace_task = _dec_replace_task

        # Хранилище фоновых задач (чтобы не терять ссылки)
        self._background_tasks = set()

    def _track_task(self, coro):
        """Запускает задачу и сохраняет ссылку, чтобы избежать сборки мусора."""
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    def inc_processing(self, user_id: int):
        self.active_processing_count[user_id] = self.active_processing_count.get(user_id, 0) + 1

    def dec_processing(self, user_id: int):
        if self.active_processing_count.get(user_id, 0) > 0:
            self.active_processing_count[user_id] -= 1

    @staticmethod
    async def _fade_and_delete(bot: Bot, chat_id: int, message_id: int, delay: float = 2.0):
        await asyncio.sleep(delay)
        try:
            await bot.delete_message(chat_id, message_id)
        except Exception:
            pass

    @staticmethod
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
    
    def cancel_batch_timer(self, user_id: int, kind: str = "work"):
        key = (user_id, kind)
        batch = self.pending_zip_batches.get(key)
        if batch:
            if batch.get("timer_task") and not batch["timer_task"].done():
             batch["timer_task"].cancel()
            if batch.get("countdown_msg_id"):
                batch["countdown_msg_id"] = None

    def _batch_kind_label(self, kind: str) -> str:
        return "сканов" if kind == "scan" else "работ"

    async def _send_menu_reminder(self, bot: Bot, chat_id: int, user_id: int):
        if user_id in self.menu_reminder_active:
            # Уже показано (другим батчем) — не дублируем.
            return
        try:
            msg = await bot.send_message(
                chat_id=chat_id,
                text="<blockquote>⚠️ <b>Нажмите все меню</b>, чтобы завершить выбор и запустить процесс.</blockquote>",
                parse_mode="HTML"
            )
            self.menu_reminder_active.add(user_id)
            self.menu_reminder_msgs[user_id] = (chat_id, msg.message_id)
        except Exception:
            pass

    def register_menu(self, user_id: int):
        """Отмечает, что для пользователя открылось ещё одно меню (выбор автора,
        подтверждение дубликата, подтверждение замены листа и т.п.)."""
        self.open_menu_counts[user_id] = self.open_menu_counts.get(user_id, 0) + 1

    async def resolve_menu(self, bot: Bot, user_id: int):
        """Отмечает, что одно из открытых меню закрыто/обработано.
        Напоминание убирается, только когда закрыты ВСЕ меню пользователя."""
        remaining = self.open_menu_counts.get(user_id, 0) - 1
        if remaining <= 0:
            self.open_menu_counts.pop(user_id, None)
            await self.clear_menu_reminder(bot, user_id)
        else:
            self.open_menu_counts[user_id] = remaining

    async def clear_menu_reminder(self, bot: Bot, user_id: int):
        self.menu_reminder_active.discard(user_id)
        entry = self.menu_reminder_msgs.pop(user_id, None)
        if entry:
            chat_id, msg_id = entry
            self._track_task(self._fade_and_delete(bot, chat_id, msg_id, delay=0.3))

    # ---------- ZIP-БАТЧ (с токеном поколения) ----------
    async def _run_batch_countdown(self, bot: Bot, user_id: int, chat_id: int, seconds: int,
                                   generation: int, kind: str = "work"):
        key = (user_id, kind)
        batch = self.pending_zip_batches.get(key)
        if not batch or batch.get("generation") != generation:
            return

        await asyncio.sleep(COUNTDOWN_DEBOUNCE_SECONDS)
        batch = self.pending_zip_batches.get(key)
        if not batch or batch.get("generation") != generation:
            return

        remaining = seconds
        kind_label = self._batch_kind_label(kind)

        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📤 Отправить сейчас", callback_data=f"send_now_zip:{kind}")]
        ])

        async def update_timer_text(secs):
            # Проверяем токен при каждом обновлении
            cur_batch = self.pending_zip_batches.get(key)
            if not cur_batch or cur_batch.get("generation") != generation:
                return

            msg_text = f"📦 Через <b>{secs} сек.</b> будет собран общий .zip-архив из {len(batch['files'])} файла(ов) ({kind_label}). Отправьте ещё файл, чтобы добавить его."
            if batch.get("countdown_msg_id"):
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id, message_id=batch["countdown_msg_id"],
                        text=msg_text, parse_mode="HTML", reply_markup=markup
                    )
                    return
                except Exception as e:
                    if "message is not modified" not in str(e).lower():
                        batch["countdown_msg_id"] = None
                    else:
                        return

            if not batch.get("countdown_msg_id"):
                try:
                    count_msg = await bot.send_message(chat_id=chat_id, text=msg_text,
                                                       parse_mode="HTML", reply_markup=markup)
                    batch["countdown_msg_id"] = count_msg.message_id
                except Exception:
                    pass

        await update_timer_text(remaining)

        try:
            while remaining > 0:
                step = min(ZIP_COUNTDOWN_STEP_SECONDS, remaining)
                for _ in range(step):
                    await asyncio.sleep(1)
                    remaining -= 1

                    # Проверяем токен и активность
                    cur_batch = self.pending_zip_batches.get(key)
                    if not cur_batch or cur_batch.get("generation") != generation:
                        return

                    user_dup_pending = any(str(k).startswith(f"dup_{user_id}_") for k in self.temp_work_data.keys())
                    work_menu_pending = user_id in self.temp_work_data or user_dup_pending
                    if (self.active_processing_count.get(user_id, 0) > 0 or
                        work_menu_pending or user_id in self.scan_menus_active):
                        batch["pending_restart_seconds"] = remaining
                        # Напоминание шлём только если ждём именно меню работы —
                        # если ждём меню сканов, напоминание пришлёт сам scan_processing
                        # после своей финальной статистики (чтобы не обогнать её).
                        if work_menu_pending:
                            self._track_task(self._send_menu_reminder(bot, chat_id, user_id))
                        if batch.get("countdown_msg_id"):
                            self._track_task(self._fade_and_delete(bot, chat_id, batch["countdown_msg_id"], delay=0))
                            batch["countdown_msg_id"] = None
                        return

                    if remaining % 5 == 0 or remaining <= 0:
                        await update_timer_text(remaining)

                if remaining <= 0:
                    break
        except asyncio.CancelledError:
            return

        # Финальная проверка токена перед отправкой
        cur_batch = self.pending_zip_batches.get(key)
        if not cur_batch or cur_batch.get("generation") != generation:
            return

        if batch.get("countdown_msg_id"):
            self._track_task(self._fade_and_delete(bot, chat_id, batch["countdown_msg_id"], delay=1.0))
            batch["countdown_msg_id"] = None
        await self._flush_zip_batch(bot, user_id, chat_id, kind)

    def _restart_batch_timer(self, bot: Bot, user_id: int, chat_id: int,
                             seconds: int = ZIP_BATCH_IDLE_SECONDS, kind: str = "work"):
        key = (user_id, kind)
        batch = self.pending_zip_batches.get(key)
        if not batch:
            return

        user_dup_pending = any(str(k).startswith(f"dup_{user_id}_") for k in self.temp_work_data.keys())
        work_menu_pending = user_id in self.temp_work_data or user_dup_pending
        menus_pending = work_menu_pending or user_id in self.scan_menus_active

        if self.active_processing_count.get(user_id, 0) > 0 or menus_pending:
            batch["pending_restart_seconds"] = seconds
            # Напоминание шлём только если ждём меню работы (не сканов —
            # для сканов его пришлёт сам scan_processing после финальной статистики).
            if work_menu_pending:
                self._track_task(self._send_menu_reminder(bot, chat_id, user_id))
            return

        batch["menu_reminder_sent"] = False

        if batch.get("pending_restart_seconds"):
            seconds = batch.pop("pending_restart_seconds")

        # Отменяем старую задачу таймера (если есть)
        if batch.get("timer_task") and not batch["timer_task"].done():
            batch["timer_task"].cancel()

        # Увеличиваем поколение
        generation = batch.get("generation", 0) + 1
        batch["generation"] = generation

        # Удаляем старое сообщение таймера — новое будет отправлено после паузы
        # debounce (см. _run_batch_countdown), чтобы не спамить при быстрой пачке файлов.
        if batch.get("countdown_msg_id"):
            self._track_task(self._fade_and_delete(bot, chat_id, batch["countdown_msg_id"], delay=0))
            batch["countdown_msg_id"] = None

        # Запускаем новую задачу с новым поколением
        batch["timer_task"] = self._track_task(
            self._run_batch_countdown(bot, user_id, chat_id, seconds, generation, kind)
        )

    async def _flush_zip_batch(self, bot: Bot, user_id: int, chat_id: int, kind: str = "work"):
        key = (user_id, kind)
        batch = self.pending_zip_batches.pop(key, None)
        if not batch or not batch["files"]:
            return

        batch_dir = batch["batch_dir"]
        files = batch["files"]
        kind_label = self._batch_kind_label(kind)

        if batch.get("countdown_msg_id"):
            try:
                await self._fade_and_delete(bot, chat_id, batch["countdown_msg_id"], delay=2.0)
            except Exception:
                pass
            batch["countdown_msg_id"] = None

        zip_filename_base = f"Файлы_{uuid.uuid4().hex[:6]}"
        safe_ascii_name = self._transliterate_to_ascii(zip_filename_base)[:60]
        zip_path = os.path.join(batch_dir, f"{safe_ascii_name}.zip")

        try:
            import zipfile
            used_names = set()
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for file_path, filename in files:
                    if not os.path.exists(file_path):
                        continue
                    arcname = filename
                    if arcname in used_names:
                        base, ext = os.path.splitext(arcname)
                        n = 2
                        while f"{base} ({n}){ext}" in used_names:
                            n += 1
                        arcname = f"{base} ({n}){ext}"
                    used_names.add(arcname)
                    zf.write(file_path, arcname=arcname)
        except Exception as e:
            logging.error(f"Ошибка упаковки: {e}")
            await bot.send_message(chat_id=chat_id, text=f"❌ Ошибка архивации: {e}")
            shutil.rmtree(batch_dir, ignore_errors=True)
            return

        warning_text = (
            "<i><b>⚠️ Это не финальный архив для отправки на кафедру.</b> "
            f"Telegram обрезает русские имена, поэтому файлы ({kind_label}) упакованы в общий .zip.\n"
        )
        if kind == "work":
            warning_text += "Используйте /zip_build для финального архива.</i>"
        else:
            warning_text += "Финальный архив собирается через /zip_build.</i>"

        try:
            await bot.send_message(chat_id=chat_id, text=warning_text, parse_mode="HTML")
            document = FSInputFile(path=zip_path, filename=os.path.basename(zip_path))
            await bot.send_document(chat_id=chat_id, document=document, request_timeout=120)
        except Exception as e:
            logging.warning(f"Ошибка отправки zip: {e}")

        shutil.rmtree(batch_dir, ignore_errors=True)

    def queue_file_for_zip_batch(self, bot: Bot, user_id: int, chat_id: int,
                                 file_path: str, filename: str, kind: str = "work",
                                 restart_timer: bool = True):
        key = (user_id, kind)
        batch = self.pending_zip_batches.get(key)

        if batch is None:
            batch_dir = os.path.join("temp", f"zip_batch_{user_id}_{kind}_{uuid.uuid4().hex[:8]}")
            os.makedirs(batch_dir, exist_ok=True)
            batch = {
                "files": [],
                "batch_dir": batch_dir,
                "timer_task": None,
                "countdown_msg_id": None,
                "kind": kind,
                "generation": 0,
                "pending_restart_seconds": None,
                "menu_reminder_sent": False,
            }
            self.pending_zip_batches[key] = batch

        copy_name = f"src_{uuid.uuid4().hex}{os.path.splitext(file_path)[1]}"
        copy_path = os.path.join(batch["batch_dir"], copy_name)
        try:
            shutil.copy2(file_path, copy_path)
        except Exception:
            return
        batch["files"].append((copy_path, filename))

        if restart_timer:
            self._restart_batch_timer(bot, user_id, chat_id, ZIP_BATCH_IDLE_SECONDS, kind=kind)

    # ---------- СКАНЫ (с токеном поколения) ----------
    async def _run_scan_countdown(self, bot: Bot, user_id: int, chat_id: int,
                                  seconds: int, generation: int):
        batch = self.pending_scan_batches.get(user_id)
        if not batch or batch.get("generation") != generation:
            return

        await asyncio.sleep(COUNTDOWN_DEBOUNCE_SECONDS)
        batch = self.pending_scan_batches.get(user_id)
        if not batch or batch.get("generation") != generation:
            return

        remaining = seconds
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📤 Распознать сейчас", callback_data="send_now_btn:scan")]
        ])

        async def update_timer_text(secs):
            cur_batch = self.pending_scan_batches.get(user_id)
            if not cur_batch or cur_batch.get("generation") != generation:
                return
            msg_text = f"🖨 Через <b>{secs} сек.</b> {len(batch['files'])} скан(ов) будут сшиты. Отправьте ещё скан."
            if batch.get("countdown_msg_id"):
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id, message_id=batch["countdown_msg_id"],
                        text=msg_text, parse_mode="HTML", reply_markup=markup
                    )
                    return
                except Exception as e:
                    if "message is not modified" not in str(e).lower():
                        batch["countdown_msg_id"] = None
                    else:
                        return

            if not batch.get("countdown_msg_id"):
                try:
                    count_msg = await bot.send_message(chat_id=chat_id, text=msg_text,
                                                       parse_mode="HTML", reply_markup=markup)
                    batch["countdown_msg_id"] = count_msg.message_id
                except Exception:
                    pass

        await update_timer_text(remaining)

        try:
            while remaining > 0:
                step = min(ZIP_COUNTDOWN_STEP_SECONDS, remaining)
                for _ in range(step):
                    await asyncio.sleep(1)
                    remaining -= 1

                    cur_batch = self.pending_scan_batches.get(user_id)
                    if not cur_batch or cur_batch.get("generation") != generation:
                        return

                    user_repl = [k for k, v in self.pending_replacements.items() if v.get('user_id') == user_id]
                    if (self.active_processing_count.get(user_id, 0) > 0 or
                        user_id in self.scan_menus_active or user_repl):
                        batch["pending_restart_seconds"] = remaining
                        # Напоминание "Нажмите все меню" здесь больше НЕ шлём —
                        # это делает исключительно тот код, который реально создаёт
                        # меню (после отправки финальной статистики), иначе напоминание
                        # может прилететь раньше итогового сообщения.
                        if batch.get("countdown_msg_id"):
                            self._track_task(self._fade_and_delete(bot, chat_id, batch["countdown_msg_id"], delay=0))
                            batch["countdown_msg_id"] = None
                        return

                    if remaining % 5 == 0 or remaining <= 0:
                        await update_timer_text(remaining)

                if remaining <= 0:
                    break
        except asyncio.CancelledError:
            return

        cur_batch = self.pending_scan_batches.get(user_id)
        if not cur_batch or cur_batch.get("generation") != generation:
            return

        if batch.get("countdown_msg_id"):
            self._track_task(self._fade_and_delete(bot, chat_id, batch["countdown_msg_id"], delay=1.0))
            batch["countdown_msg_id"] = None
        await self._flush_scan_batch(bot, user_id, chat_id)

    def _restart_scan_timer(self, bot: Bot, user_id: int, chat_id: int,
                            seconds: int = ZIP_BATCH_IDLE_SECONDS):
        batch = self.pending_scan_batches.get(user_id)
        if not batch or batch.get("manual_flush", False):
            return

        user_repl = [k for k, v in self.pending_replacements.items() if v.get('user_id') == user_id]
        menus_pending = user_id in self.scan_menus_active or bool(user_repl)

        if self.active_processing_count.get(user_id, 0) > 0 or menus_pending:
            batch["pending_restart_seconds"] = seconds
            # Напоминание не шлём отсюда — см. комментарий выше.
            return

        batch["menu_reminder_sent"] = False

        if batch.get("pending_restart_seconds"):
            seconds = batch.pop("pending_restart_seconds")

        if batch.get("timer_task") and not batch["timer_task"].done():
            batch["timer_task"].cancel()

        generation = batch.get("generation", 0) + 1
        batch["generation"] = generation

        if batch.get("status_msg_id"):
            self._track_task(self._fade_and_delete(bot, chat_id, batch["status_msg_id"], delay=0))
            batch["status_msg_id"] = None

        # Удаляем старое сообщение таймера — новое отправится после debounce-паузы.
        if batch.get("countdown_msg_id"):
            self._track_task(self._fade_and_delete(bot, chat_id, batch["countdown_msg_id"], delay=0))
            batch["countdown_msg_id"] = None

        batch["timer_task"] = self._track_task(
            self._run_scan_countdown(bot, user_id, chat_id, seconds, generation)
        )

    async def _flush_scan_batch(self, bot: Bot, user_id: int, chat_id: int):
        batch = self.pending_scan_batches.pop(user_id, None)
        if not batch or not batch["files"]:
            return

        if batch.get("countdown_msg_id"):
            self._track_task(self._fade_and_delete(bot, chat_id, batch["countdown_msg_id"], delay=2.0))
            batch["countdown_msg_id"] = None

        msg = await bot.send_message(chat_id=chat_id, text="🔄 Начинаю процесс...")
        self._track_task(self._fade_and_delete(bot, chat_id, msg.message_id, delay=2.0))

        await processing_queue.put({
            'type': 'scan_batch', 'chat_id': chat_id, 'user_id': user_id,
            'msg_id': msg.message_id, 'files': batch["files"], 'batch_dir': batch["batch_dir"]
        })

    # ---------- РАБОТЫ (с токеном поколения) ----------
    async def _run_work_countdown(self, bot: Bot, user_id: int, chat_id: int,
                                  seconds: int, generation: int):
        batch = self.pending_work_batches.get(user_id)
        if not batch or batch.get("generation") != generation:
            return

        await asyncio.sleep(COUNTDOWN_DEBOUNCE_SECONDS)
        batch = self.pending_work_batches.get(user_id)
        if not batch or batch.get("generation") != generation:
            return

        remaining = seconds
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📤 Обработать сейчас", callback_data="send_now_btn:work")]
        ])

        async def update_timer_text(secs):
            cur_batch = self.pending_work_batches.get(user_id)
            if not cur_batch or cur_batch.get("generation") != generation:
                return
            msg_text = f"📚 Через <b>{secs} сек.</b> будет запущена обработка {len(batch['files'])} файла(ов) работ. Отправьте ещё файл."
            if batch.get("countdown_msg_id"):
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id, message_id=batch["countdown_msg_id"],
                        text=msg_text, parse_mode="HTML", reply_markup=markup
                    )
                    return
                except Exception as e:
                    if "message is not modified" not in str(e).lower():
                        batch["countdown_msg_id"] = None
                    else:
                        return

            if not batch.get("countdown_msg_id"):
                try:
                    count_msg = await bot.send_message(chat_id=chat_id, text=msg_text,
                                                       parse_mode="HTML", reply_markup=markup)
                    batch["countdown_msg_id"] = count_msg.message_id
                except Exception:
                    pass

        await update_timer_text(remaining)

        try:
            while remaining > 0:
                step = min(ZIP_COUNTDOWN_STEP_SECONDS, remaining)
                for _ in range(step):
                    await asyncio.sleep(1)
                    remaining -= 1

                    cur_batch = self.pending_work_batches.get(user_id)
                    if not cur_batch or cur_batch.get("generation") != generation:
                        return

                    work_menu_pending = user_id in self.temp_work_data
                    if (self.active_processing_count.get(user_id, 0) > 0 or
                        work_menu_pending or user_id in self.scan_menus_active):
                        batch["pending_restart_seconds"] = remaining
                        # Напоминание шлём только если ждём меню работы (не сканов —
                        # для сканов его пришлёт сам scan_processing после финальной статистики).
                        if work_menu_pending:
                            self._track_task(self._send_menu_reminder(bot, chat_id, user_id))
                        if batch.get("countdown_msg_id"):
                            self._track_task(self._fade_and_delete(bot, chat_id, batch["countdown_msg_id"], delay=0))
                            batch["countdown_msg_id"] = None
                        return

                    if remaining % 5 == 0 or remaining <= 0:
                        await update_timer_text(remaining)

                if remaining <= 0:
                    break
        except asyncio.CancelledError:
            return

        cur_batch = self.pending_work_batches.get(user_id)
        if not cur_batch or cur_batch.get("generation") != generation:
            return

        if batch.get("countdown_msg_id"):
            self._track_task(self._fade_and_delete(bot, chat_id, batch["countdown_msg_id"], delay=1.0))
            batch["countdown_msg_id"] = None
        await self._flush_work_batch(bot, user_id, chat_id)

    def _restart_work_timer(self, bot: Bot, user_id: int, chat_id: int,
                            seconds: int = ZIP_BATCH_IDLE_SECONDS):
        batch = self.pending_work_batches.get(user_id)
        if not batch:
            return

        work_menu_pending = user_id in self.temp_work_data
        if self.active_processing_count.get(user_id, 0) > 0 or work_menu_pending or user_id in self.scan_menus_active:
            batch["pending_restart_seconds"] = seconds
            # Напоминание шлём только если ждём меню работы (не сканов —
            # для сканов его пришлёт сам scan_processing после финальной статистики).
            if work_menu_pending:
                self._track_task(self._send_menu_reminder(bot, chat_id, user_id))
            return

        batch["menu_reminder_sent"] = False

        if batch.get("pending_restart_seconds"):
            seconds = batch.pop("pending_restart_seconds")

        if batch.get("timer_task") and not batch["timer_task"].done():
            batch["timer_task"].cancel()

        generation = batch.get("generation", 0) + 1
        batch["generation"] = generation

        if batch.get("status_msg_id"):
            self._track_task(self._fade_and_delete(bot, chat_id, batch["status_msg_id"], delay=0))
            batch["status_msg_id"] = None

        # Удаляем старое сообщение таймера — новое отправится после debounce-паузы,
        # чтобы при пачке файлов не было спама отдельными сообщениями.
        if batch.get("countdown_msg_id"):
            self._track_task(self._fade_and_delete(bot, chat_id, batch["countdown_msg_id"], delay=0))
            batch["countdown_msg_id"] = None

        batch["timer_task"] = self._track_task(
            self._run_work_countdown(bot, user_id, chat_id, seconds, generation)
        )

    async def _flush_work_batch(self, bot: Bot, user_id: int, chat_id: int):
        batch = self.pending_work_batches.pop(user_id, None)
        if not batch or not batch["files"]:
            return

        files_data = batch["files"]

        if batch.get("countdown_msg_id"):
            self._track_task(self._fade_and_delete(bot, chat_id, batch["countdown_msg_id"], delay=0))
            batch["countdown_msg_id"] = None

        start_msg = await bot.send_message(chat_id=chat_id, text=f"🔄 Начинаю обработку {len(files_data)} файлов...")
        self._track_task(self._fade_and_delete(bot, chat_id, start_msg.message_id, delay=2.0))

        for file_path, orig_filename in files_data:
            self.inc_processing(user_id)
            status_msg = await bot.send_message(chat_id=chat_id, text="⏳ Документ добавлен в очередь обработки...")

            await processing_queue.put({
                'type': 'work', 'chat_id': chat_id, 'user_id': user_id,
                'msg_id': status_msg.message_id, 'file_path': file_path, 'orig_filename': orig_filename
            })

state_manager = BotStateManager()
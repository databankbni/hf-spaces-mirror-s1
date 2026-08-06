import os
import config
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket
from bson.objectid import ObjectId
from rapidfuzz import fuzz
from pypdf import PdfReader
import shutil
import uuid
import io
import asyncio
import re
from datetime import datetime
import logging
from utils import extract_page_texts,normalize_author_name


client = None
db_instance = None

# Ваши коллекции, если они объявлены глобально:
pages_collection = None
subjects_collection = None
allowed_email_senders_collection = None
ocr_cache_collection = None

def get_fs_and_collections():
    global db_instance
    # На случай, если функция вызовется до init_indexes
    if db_instance is None:
        _init_motor()
    return (
        AsyncIOMotorGridFSBucket(db_instance),
        db_instance['users'],
        db_instance['works']
    )

# Внутренняя функция для безопасной инициализации пула
def _init_motor():
    global client, db_instance, pages_collection, subjects_collection, allowed_email_senders_collection, ocr_cache_collection
    if client is None:
        logging.info("🔌 Инициализация пула соединений MongoDB внутри живого Event Loop...")
        
        # БЕРЕМ ТОЧНЫЙ URI ИЗ ВАШЕГО CONFIG.PY
        client = AsyncIOMotorClient(config.MONGO_URI) 
        db_instance = client['TestDB']
        
        pages_collection = db_instance["pages"]
        subjects_collection = db_instance["subjects"]
        allowed_email_senders_collection = db_instance["allowed_email_senders"]
        ocr_cache_collection = db_instance["ocr_cache"]

_indexes_verified = False


async def init_indexes():
    global _indexes_verified
    # 2. ФИКС: Инициализируем базу строго в момент вызова функции внутри lifespan/startup
    _init_motor()

    # Индексы проверяем и создаём только ОДИН раз за время жизни процесса — раньше эта
    # функция вызывалась из каждой db-функции (несколько раз на каждую страницу скана),
    # и каждый раз заново делала 3 полных round-trip'а к MongoDB (~250-300мс каждый) —
    # это и было основной причиной общей медлительности при обработке сканов.
    if _indexes_verified:
        return

    logging.info("⏳ Проверка индексов MongoDB...")
    # Дальше идет ваш оригинальный асинхронный код проверки индексов...
    if pages_collection.name not in await db_instance.list_collection_names():
        await db_instance.create_collection("pages")
        
    indexes = await pages_collection.index_information()
    text_index_exists = False
    for idx_name, idx_def in indexes.items():
        if 'text' in str(idx_def.get('key', [])):
            text_index_exists = True
            break
    if not text_index_exists:
        await pages_collection.create_index([("text", "text")], default_language="russian")
        logging.info("DEBUG: Текстовый индекс для pages создан")
    if 'tg_id_1' not in indexes:
        await pages_collection.create_index("tg_id")
    if 'work_id_1' not in indexes:
        await pages_collection.create_index("work_id")

    subj_indexes = await subjects_collection.index_information()
    if 'tg_id_1_subject_1' not in subj_indexes:
        await subjects_collection.create_index([("tg_id", 1), ("subject", 1)], unique=True)
    logging.info("✅ Все индексы MongoDB успешно проверены!")
    _indexes_verified = True


def get_pages_collection():
    global pages_collection
    if pages_collection is None:
        _init_motor()
    return pages_collection

def get_subjects_collection():
    global subjects_collection
    if subjects_collection is None:
        _init_motor()
    return subjects_collection

# subjects: предмет ↔ кафедра
async def upsert_subject_department(tg_id: int, subject: str, department: str):
    if not subject or not department:
        return
    await subjects_collection.update_one(
        {"tg_id": tg_id, "subject": subject},
        {"$set": {"department": department, "updated_at": datetime.utcnow()}},
        upsert=True
    )

async def get_department_for_subject(tg_id: int, subject: str) -> str:
    doc = await subjects_collection.find_one({"tg_id": tg_id, "subject": subject})
    return (doc or {}).get("department", "")

async def get_subjects_map(tg_id: int) -> dict:
    cursor = subjects_collection.find({"tg_id": tg_id})
    docs = await cursor.to_list(length=None)
    return {d["subject"]: d.get("department", "") for d in docs}

async def get_unique_departments(tg_id: int) -> list:
    return await subjects_collection.distinct("department", {
        "tg_id": tg_id, "department": {"$exists": True, "$nin": [None, ""]}
    })

async def get_subjects_by_department(tg_id: int, department: str) -> list:
    cursor = subjects_collection.find({"tg_id": tg_id, "department": department})
    docs = await cursor.to_list(length=None)
    return [d["subject"] for d in docs]

async def get_user(tg_id: int):
    _, users_col, _ = get_fs_and_collections()
    return await users_col.find_one({"tg_id": tg_id})

async def get_work_by_id(work_id):
    _, _, works_collection = get_fs_and_collections()
    if isinstance(work_id, str):
        work_id = ObjectId(work_id)
    return await works_collection.find_one({"_id": work_id})

async def save_digital_work(metadata: dict, file_bytes: bytes, tg_id: int, selected_authors: list = None, custom_filename: str = None, is_presentation: bool = False, status: str = "digital_only"):
    fs, _, works_collection = get_fs_and_collections()
    authors = metadata.get('authors', [])
    if not authors:
        authors = ["Неизвестный автор"]

    if selected_authors is None or selected_authors == 'all':
        target_authors = authors
    else:
        target_authors = [a for a in authors if a in selected_authors]

    if not target_authors:
        target_authors = authors

    if custom_filename:
        base_filename = custom_filename
    else:
        base_filename = metadata.get('filename', 'work.pdf')

    file_id = await fs.upload_from_stream(base_filename, file_bytes)

    from utils import generate_safe_filename, extract_page_texts
    work_ids = []
    for author in target_authors:
        work_meta = metadata.copy()
        work_meta['tg_id'] = tg_id
        work_meta['author'] = author
        work_meta['file_id'] = file_id
        work_meta['status'] = status  # <-- используем переданный статус
        work_meta['replaced_pages'] = metadata.get('replaced_pages', [])
        if custom_filename:
            work_meta['filename'] = custom_filename
        else:
            work_meta['filename'] = generate_safe_filename(work_meta, specific_author=author)
        work_meta['is_presentation'] = is_presentation
        work_meta['linked_work_ids'] = []
        work_meta['best_match_score'] = 0.0
        work_meta['best_work_id'] = None
        work_meta.pop('_id', None)
        result = await works_collection.insert_one(work_meta)
        work_ids.append(result.inserted_id)

    if metadata.get('subject') and metadata.get('department'):
        await upsert_subject_department(tg_id, metadata['subject'], metadata['department'])

    page_texts = await extract_page_texts(file_bytes)
    for wid in work_ids:
        for page_num, text in page_texts:
            if text and text.strip():
                await pages_collection.update_one(
                    {"work_id": wid, "page_num": page_num},
                    {"$set": {"text": text, "tg_id": tg_id}},
                    upsert=True
                )
    return work_ids

# ---------- ФУНКЦИИ ДЛЯ ПРЕЗЕНТАЦИЙ ----------
async def get_all_presentations(tg_id: int) -> list:
    """Возвращает все презентации пользователя (включая уже привязанные)."""
    _, _, works_collection = get_fs_and_collections()
    cursor = works_collection.find({
        "tg_id": tg_id,
        "is_presentation": True,
    })
    return await cursor.to_list(length=None)

async def get_unlinked_presentations(tg_id: int) -> list:
    """Возвращает презентации, которые ещё не привязаны ни к одной работе."""
    _, _, works_collection = get_fs_and_collections()
    cursor = works_collection.find({
        "tg_id": tg_id,
        "is_presentation": True,
        "$or": [
            {"linked_work_ids": {"$exists": False}},
            {"linked_work_ids": {"$size": 0}}
        ]
    })
    return await cursor.to_list(length=None)

async def update_presentation_best_match(presentation_id, work_id, score):
    """Обновляет лучший балл и ID работы для презентации."""
    _, _, works_collection = get_fs_and_collections()
    pres = await works_collection.find_one({"_id": ObjectId(presentation_id)})
    if not pres:
        return
    current_best = pres.get('best_match_score', 0)
    if score > current_best:
        await works_collection.update_one(
            {"_id": ObjectId(presentation_id)},
            {"$set": {
                "best_match_score": score,
                "best_work_id": ObjectId(work_id)
            }}
        )
        return True  # обновлено
    return False

async def link_presentation_to_best_work(presentation_id):
    """Привязывает презентацию ко всем записям работы с наилучшим баллом."""
    _, _, works_collection = get_fs_and_collections()
    pres = await works_collection.find_one({"_id": ObjectId(presentation_id)})
    if not pres:
        return
    best_work_id = pres.get('best_work_id')
    if not best_work_id:
        return
    # Находим работу-оригинал
    best_work = await get_work_by_id(best_work_id)
    if not best_work:
        return
    file_id = best_work.get('file_id')
    if not file_id:
        return
    # Находим все записи с этим file_id (все авторы)
    all_work_records = await works_collection.find({"file_id": file_id}).to_list(length=None)
    if not all_work_records:
        return

    linked = pres.get('linked_work_ids', [])
    updated = False
    for work in all_work_records:
        wid = work['_id']
        if wid not in linked:
            linked.append(wid)
            updated = True

    if not updated:
        return

    # Обновляем метаданные презентации (берём из первой записи)
    first_work = all_work_records[0]
    metadata = {
        "subject": first_work.get("subject"),
        "full_subject": first_work.get("full_subject"),
        "group": first_work.get("group"),
        "department": first_work.get("department"),
        "work_type": first_work.get("work_type"),
        "work_number": first_work.get("work_number"),
        "authors": first_work.get("authors", []),
        "author": first_work.get("author"),
    }
    update_data = {
        "linked_work_ids": linked,
        "updated_at": datetime.utcnow()
    }
    if not pres.get('subject') or pres.get('subject') == 'Предмет' or pres.get('subject') is None:
        update_data.update(metadata)
    await works_collection.update_one(
        {"_id": ObjectId(presentation_id)},
        {"$set": update_data}
    )

async def get_work_metadata_for_linking(work_id):
    """Возвращает метаданные работы для привязки презентации."""
    work = await get_work_by_id(work_id)
    if not work:
        return None
    return {
        "subject": work.get("subject"),
        "full_subject": work.get("full_subject"),
        "group": work.get("group"),
        "department": work.get("department"),
        "work_type": work.get("work_type"),
        "work_number": work.get("work_number"),
        "authors": work.get("authors", []),
        "author": work.get("author"),
    }

async def get_work_full_text(work_id):
    """Возвращает полный текст работы, объединяя все страницы."""
    cursor = pages_collection.find({"work_id": ObjectId(work_id)})
    pages = await cursor.to_list(length=None)
    if not pages:
        return ""
    return " ".join([p.get("text", "") for p in pages])

# ----- Остальные функции (без изменений) -----
async def get_works_by_subject(tg_id: int, subject: str, author_filter: str = None, department_filter: str = None):
    _, _, works_collection = get_fs_and_collections()
    query = {"tg_id": tg_id, "subject": subject}
    if author_filter:
        query["author"] = author_filter
    if department_filter:
        query["department"] = department_filter
    cursor = works_collection.find(query)
    return await cursor.to_list(length=None)

async def get_all_user_works(tg_id: int, author_filter: str = None, department_filter: str = None):
    _, _, works_collection = get_fs_and_collections()
    query = {"tg_id": tg_id}
    if author_filter:
        query["author"] = author_filter
    if department_filter:
        query["department"] = department_filter
    cursor = works_collection.find(query)
    return await cursor.to_list(length=None)

async def find_matching_work(meta: dict, tg_id: int):
    _, _, works_collection = get_fs_and_collections()
    cursor = works_collection.find({"tg_id": tg_id, "status": "digital_only"})
    pending_works = await cursor.to_list(length=None)
    best_match = None
    highest_score = 0

    from utils import normalize_author_name
    for work in pending_works:
        if work.get('work_type') != meta.get('work_type'): continue
        score = 0
        db_num = str(work.get('work_number', '')).lstrip('0')
        meta_num = str(meta.get('work_number', '')).lstrip('0')
        if db_num and meta_num and db_num == meta_num: score += 40
        elif not db_num and not meta_num: score += 15

        db_auth = normalize_author_name(work.get('author', ''))
        meta_auth = normalize_author_name(meta.get('author', '')) if meta.get('author') else ''
        if db_auth and meta_auth:
            auth_sim = fuzz.partial_ratio(meta_auth, db_auth)
            if auth_sim > 80: score += 30
            elif auth_sim > 60: score += 15

        db_subj = work.get('subject', '').lower()
        meta_subj = meta.get('subject', '').lower()
        if db_subj and meta_subj:
            subj_sim = fuzz.token_sort_ratio(meta_subj, db_subj)
            if subj_sim > 75: score += 10
            elif db_subj in meta_subj or meta_subj in db_subj: score += 10

        db_grp = work.get('group', '').replace('-', '').lower()
        meta_grp = meta.get('group', '').replace('-', '').lower()
        if db_grp and meta_grp:
            grp_sim = fuzz.ratio(meta_grp, db_grp)
            if grp_sim > 85: score += 20

        if score >= 60 and score > highest_score:
            highest_score = score
            best_match = work

    return best_match

async def update_work_with_scan(work_id, file_bytes: bytes, new_filename: str, new_replaced_pages: list = None):
    fs, _, works_collection = get_fs_and_collections()
    work = await works_collection.find_one({"_id": work_id})
    if not work:
        raise ValueError("Работа не найдена")
    old_file_id = work['file_id']
    old_path = f"/tmp/old_{work_id}.pdf"
    new_path = f"/tmp/new_{work_id}.pdf"
    try:
        stream = await fs.open_download_stream(old_file_id)
        old_content = await stream.read()
        with open(old_path, "wb") as f:
            f.write(old_content)

        from utils import replace_specific_pages, extract_page_texts

        shutil.copy(old_path, new_path)
        with open(new_path, "rb") as f:
            new_file_id = await fs.upload_from_stream(new_filename, f.read())
        await fs.delete(old_file_id)

        existing_replaced = work.get("replaced_pages", [])
        if new_replaced_pages:
            merged_replaced = sorted(set(existing_replaced + new_replaced_pages))
        else:
            merged_replaced = existing_replaced

        reader = PdfReader(new_path)
        pages_total = len(reader.pages)
        status = "fully_replaced" if len(merged_replaced) == pages_total else "merged"

        await works_collection.update_one(
            {"_id": work_id},
            {"$set": {
                "status": status,
                "file_id": new_file_id,
                "pages_total": pages_total,
                "replaced_pages": merged_replaced,
                "updated_at": datetime.utcnow()
            }}
        )

        await pages_collection.delete_many({"work_id": work_id})

        gridout = await fs.open_download_stream(new_file_id)
        new_file_bytes = await gridout.read()

        page_texts = await extract_page_texts(new_file_bytes)
        for page_num, text in page_texts:
            if text and text.strip():
                await pages_collection.update_one(
                    {"work_id": work_id, "page_num": page_num},
                    {"$set": {"text": text, "tg_id": work['tg_id']}},
                    upsert=True
                )
    finally:
        if os.path.exists(old_path):
            os.remove(old_path)
        if os.path.exists(new_path):
            os.remove(new_path)

async def get_related_works_for_scan(tg_id: int, base_work_id) -> list:
    _, _, works_collection = get_fs_and_collections()
    base = await get_work_by_id(base_work_id)
    if not base:
        return []
    file_id = base.get('file_id')

    by_file_id = []
    if file_id:
        by_file_id = await works_collection.find({"tg_id": tg_id, "file_id": file_id}).to_list(length=None)

    # Подстраховка: file_id может разойтись между копиями авторов из-за старых багов
    # (замена в прошлом применялась не ко всем связанным work_id сразу — часть копий
    # "отвалилась" от общего файла). В таком случае поиск строго по file_id находит
    # меньше копий, чем реальных авторов ("не хватает одного автора" в меню). Поэтому
    # дополнительно ищем по метаданным (группа/предмет/тип/номер/кафедра) — они у всех
    # копий одной работы совпадают даже если file_id разошёлся — и объединяем результаты.
    meta_filter = {
        "tg_id": tg_id,
        "is_presentation": {"$ne": True},
        "group": base.get("group"),
        "subject": base.get("subject"),
        "work_type": base.get("work_type"),
        "work_number": base.get("work_number"),
        "department": base.get("department"),
    }
    by_meta = await works_collection.find(meta_filter).to_list(length=None)

    combined = {}
    for w in by_file_id + by_meta:
        combined[w["_id"]] = w
    result = list(combined.values())

    # Самовосстановление: если метаданные нашли БОЛЬШЕ копий, чем было по file_id —
    # значит связь действительно разошлась. Приводим все найденные копии к ОДНОМУ
    # file_id (берём file_id самой свежей по updated_at копии), чтобы в следующий раз
    # обычный поиск по file_id уже находил всех сразу, без повторной подстраховки.
    if len(result) > len(by_file_id) and len(result) > 1:
        newest = max(result, key=lambda w: w.get("updated_at") or datetime.min)
        target_file_id = newest.get("file_id")
        if target_file_id:
            for w in result:
                if w.get("file_id") != target_file_id:
                    await works_collection.update_one(
                        {"_id": w["_id"]}, {"$set": {"file_id": target_file_id}}
                    )
                    w["file_id"] = target_file_id
            logging.info(
                f"🔧 [AUTO-REPAIR] Восстановлена file_id-связка для {len(result)} копий "
                f"(группа={base.get('group')}, предмет={base.get('subject')})"
            )

    return result

async def find_exact_work(meta: dict, tg_id: int):
    _, _, works_collection = get_fs_and_collections()
    from utils import clean_group_name, normalize_author_name

    group_raw = meta.get("group")
    subject = meta.get("subject")
    work_type = meta.get("work_type")
    work_number = meta.get("work_number")
    authors = meta.get("authors", [])

    if not group_raw or not subject:
        return None

    group = clean_group_name(group_raw)

    query = {
        "tg_id": tg_id,
        "group": group,
        "subject": subject,
        "is_presentation": {"$ne": True},   # исключаем презентации
    }
    if work_type is not None:
        query["work_type"] = work_type
    else:
        query["work_type"] = None

    if work_number not in (None, "", "None"):
        query["work_number"] = str(work_number).lstrip('0')
    else:
        query["work_number"] = None

    for author in authors:
        norm_author = normalize_author_name(author)
        if norm_author:
            q = query.copy()
            q["author"] = norm_author
            result = await works_collection.find_one(q)
            if result:
                return result

    return None

async def get_unique_subjects(tg_id: int, author_filter: str = None, department_filter: str = None):
    _, _, works_collection = get_fs_and_collections()
    query = {"tg_id": tg_id}
    if author_filter:
        query["author"] = author_filter
    if department_filter:
        query["department"] = department_filter
    return await works_collection.distinct("subject", query)

async def download_file(file_id, dest_path):
    """
    Потоково скачивает файл из GridFS кусками (readchunk) напрямую на диск. Раньше весь
    файл читался в память целиком (`stream.read()`) перед записью — на больших работах
    (десятки страниц с картинками) это могло разом съедать много RAM, что критично на
    инстансах с ограниченной памятью (например, 512 МБ).
    """
    fs, _, _ = get_fs_and_collections()
    stream = await fs.open_download_stream(file_id)
    with open(dest_path, "wb") as f:
        while True:
            chunk = await stream.readchunk()
            if not chunk:
                break
            f.write(chunk)

async def delete_works_by_subject(tg_id: int, subject: str, author_filter: str = None):
    fs, _, works_collection = get_fs_and_collections()
    query = {"tg_id": tg_id, "subject": subject}
    if author_filter:
        query["author"] = author_filter
    works = await works_collection.find(query).to_list(length=None)
    for w in works:
        if 'file_id' in w:
            count = await works_collection.count_documents({"file_id": w['file_id']})
            if count <= 1:
                await fs.delete(w['file_id'])
        await pages_collection.delete_many({"work_id": w['_id']})
    await works_collection.delete_many(query)

async def replace_single_page(work_id: ObjectId, page_number: int, new_page_bytes: bytes) -> ObjectId:
    fs, _, works_collection = get_fs_and_collections()
    work = await works_collection.find_one({"_id": work_id})
    if not work:
        raise ValueError("Работа не найдена")
    old_file_id = work['file_id']
    temp_dir = f"/tmp/patch_{uuid.uuid4().hex}"
    os.makedirs(temp_dir, exist_ok=True)
    orig_path = os.path.join(temp_dir, "original.pdf")
    new_page_path = os.path.join(temp_dir, "new_page.pdf")
    out_path = os.path.join(temp_dir, "patched.pdf")
    try:
        stream = await fs.open_download_stream(old_file_id)
        content = await stream.read()
        with open(orig_path, "wb") as f:
            f.write(content)
        with open(new_page_path, "wb") as f:
            f.write(new_page_bytes)

        from utils import replace_specific_pages, extract_page_texts

        await asyncio.to_thread(
            replace_specific_pages,
            orig_path,
            {page_number - 1: new_page_path},
            out_path
        )
        with open(out_path, "rb") as f:
            new_file_id = await fs.upload_from_stream(work['filename'], f.read())
        await fs.delete(old_file_id)

        replaced_pages = work.get("replaced_pages", [])
        if page_number not in replaced_pages:
            replaced_pages.append(page_number)
            replaced_pages.sort()

        reader = PdfReader(out_path)
        pages_total = len(reader.pages)
        status = "fully_replaced" if len(replaced_pages) == pages_total else "partial"

        await works_collection.update_one(
            {"_id": work_id},
            {"$set": {
                "file_id": new_file_id,
                "replaced_pages": replaced_pages,
                "pages_total": pages_total,
                "status": status,
                "updated_at": datetime.utcnow()
            }}
        )

        with open(out_path, "rb") as f:
            new_bytes = f.read()
        await pages_collection.delete_many({"work_id": work_id})
        page_texts = await extract_page_texts(new_bytes)
        for pn, txt in page_texts:
            if txt and len(txt.strip()) > 20:
                await pages_collection.update_one(
                    {"work_id": work_id, "page_num": pn},
                    {"$set": {"text": txt, "tg_id": work['tg_id']}},
                    upsert=True
                )
        return new_file_id
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

async def find_page_by_text(tg_id: int, scan_text: str) -> tuple[ObjectId | None, int | None]:
    def _strip_boilerplate(text: str) -> str:
        """
        Убирает общую шаблонную шапку вуза (одинаковую практически на каждом титульном
        листе всех работ пользователя), которая иначе искусственно завышает fuzzy-скор
        между совершенно не связанными страницами и приводит к ложным совпадениям.
        """
        boilerplate_patterns = [
            r'министерств\w*\s+цифров\w*\s+развит\w*.{0,400}?информатики',
            r'фгбоу\s+во.{0,300}?сибгути',
        ]
        cleaned = text
        for pat in boilerplate_patterns:
            cleaned = re.sub(pat, ' ', cleaned, flags=re.IGNORECASE | re.DOTALL)
        return re.sub(r'\s+', ' ', cleaned).strip()

    await init_indexes()
    _, _, works_collection = get_fs_and_collections()
    presentation_ids = set(await works_collection.distinct(
        "_id", {"tg_id": tg_id, "is_presentation": True}
    ))

    pipeline = [
        {"$match": {"tg_id": tg_id, "$text": {"$search": scan_text}}},
        {"$addFields": {"score": {"$meta": "textScore"}}},
        {"$sort": {"score": -1}},
        {"$limit": 3}
    ]
    cursor = pages_collection.aggregate(pipeline)
    candidates = await cursor.to_list(length=3)
    best_work = None
    best_page = None
    best_score = 0
    for cand in candidates:
        if cand["work_id"] in presentation_ids:
            continue
        score = fuzz.token_sort_ratio(scan_text, cand["text"])
        if score > best_score and score > 60:
            best_score = score
            best_work = cand["work_id"]
            best_page = cand["page_num"]

    if best_work:
        return best_work, best_page

    # MongoDB $text требует совпадения токенов/стемминга и часто промахивается на плохом OCR
    # (рукописные подписи, кривой скан, повторное сканирование). Поэтому если текстовый поиск
    # ничего не дал — сравниваем напрямую со ВСЕМИ страницами пользователя по их
    # индивидуальному, "мягко извлечённому" тексту в pages. Это надёжнее, чем искать
    # по агрегированному тексту целой работы (там сравнение native-extraction конкретной
    # страницы с "идеальным" Gemini OCR скана и даёт систематические ошибки — работа
    # выбирается неверно или страница внутри неё угадывается почти наугад).
    #
    # ВАЖНО: без предфильтра $text это сравнение намного более рискованное — одинаковая
    # шапка вуза на каждом титульном листе и короткие générique подписи (типа "Рисунок 1")
    # искусственно завышают fuzzy-скор между СОВЕРШЕННО не связанными страницами. Поэтому
    # здесь используем более строгий порог и убираем общую шаблонную шапку перед сравнением.
    scan_stripped = _strip_boilerplate(scan_text)
    if len(scan_stripped) < 40:
        # Слишком короткий/неинформативный текст — сравнивать вслепую со всеми страницами
        # опасно (почти гарантированные ложные совпадения), лучше честно не найти.
        return None, None

    cursor = pages_collection.find({"tg_id": tg_id})
    all_pages = await cursor.to_list(length=None)
    STRICT_THRESHOLD = 82
    for cand in all_pages:
        if cand["work_id"] in presentation_ids:
            continue
        p_text = cand.get("text", "")
        if not p_text or len(p_text) < 40:
            continue
        p_stripped = _strip_boilerplate(p_text)
        score = fuzz.token_sort_ratio(scan_stripped, p_stripped)
        if score > best_score and score > STRICT_THRESHOLD:
            best_score = score
            best_work = cand["work_id"]
            best_page = cand["page_num"]

    if best_work:
        logging.info(f"📄 [PAGE SEARCH] Найдено прямым fuzzy-перебором страниц (без $text): work={best_work}, page={best_page}, score={best_score}")

    return best_work, best_page

async def find_page_by_text_with_metadata(tg_id: int, scan_text: str, metadata: dict) -> tuple[ObjectId | None, int | None]:
    await init_indexes()
    _, _, works_collection = get_fs_and_collections()
    work_filter = {"tg_id": tg_id, "is_presentation": {"$ne": True}}
    if metadata.get("subject"):
        work_filter["subject"] = metadata["subject"]
    if metadata.get("work_type"):
        work_filter["work_type"] = metadata["work_type"]
    if metadata.get("work_number"):
        work_filter["work_number"] = metadata["work_number"]
    works = await works_collection.find(work_filter).to_list(length=None)
    if not works:
        return None, None
    work_ids = [w["_id"] for w in works]
    pipeline = [
        {"$match": {"work_id": {"$in": work_ids}, "$text": {"$search": scan_text}}},
        {"$addFields": {"score": {"$meta": "textScore"}}},
        {"$sort": {"score": -1}},
        {"$limit": 5}
    ]
    cursor = pages_collection.aggregate(pipeline)
    candidates = await cursor.to_list(length=5)
    best_work = None
    best_page = None
    best_score = 0
    for cand in candidates:
        score = fuzz.token_sort_ratio(scan_text, cand["text"])
        if score > best_score and score > 60:
            best_score = score
            best_work = cand["work_id"]
            best_page = cand["page_num"]
    return best_work, best_page

async def find_work_by_aggregated_content(tg_id: int, scan_text: str, hint_group: str = None, hint_author: str = None, is_review_page: bool = False) -> tuple[ObjectId | None, int | None]:
    await init_indexes()
    _, _, works_collection = get_fs_and_collections()

    works = await works_collection.find({"tg_id": tg_id, "is_presentation": {"$ne": True}}).to_list(length=None)
    if not works:
        return None, None

    work_ids = [w["_id"] for w in works]
    works_by_id = {w["_id"]: w for w in works}

    cursor = pages_collection.find({"work_id": {"$in": work_ids}})
    all_pages = await cursor.to_list(length=None)

    pages_by_work = {}
    for page in all_pages:
        pages_by_work.setdefault(page["work_id"], []).append(page)

    scan_text_lower = (scan_text or "").lower()

    if is_review_page and (not hint_group or not hint_author):
        group_match = re.search(r'(?:гр\.?|группа)\s*([А-ЯЁA-Z]{2,4}[-\s]?\d{2,4}[А-ЯЁA-Z]?)', scan_text, re.IGNORECASE)
        if group_match:
            raw_group = group_match.group(1).upper().replace(" ", "-")
            if len(raw_group) >= 2 and raw_group[-1].isdigit():
                hint_group = raw_group[:-1] + 'Б'
            else:
                hint_group = raw_group
            logging.info(f"📄 [REVIEW] Извлечена группа: {raw_group} → нормализовано: {hint_group}")
        author_match = re.search(r'([А-ЯЁ][а-яё]+)\s+([А-ЯЁ])\.?\s*([А-ЯЁ])?\.?', scan_text)
        if author_match:
            hint_author = f"{author_match.group(1)} {author_match.group(2)}{author_match.group(3) or ''}".replace('.', '')
            logging.info(f"📄 [REVIEW] Извлечён автор: {hint_author}")

    scored_works = []

    for wid, pages in pages_by_work.items():
        work = works_by_id.get(wid)
        if not work:
            continue

        full_text = " ".join(p.get("text", "") for p in pages)
        score = fuzz.WRatio(scan_text_lower, full_text.lower())

        work_group = (work.get("group") or "").lower()
        work_author = (work.get("author") or "").lower()

        if work_group and work_group in scan_text_lower:
            score += 20
        if work_author and any(part in scan_text_lower for part in work_author.split() if len(part) > 2):
            score += 20
        if hint_group and work_group and hint_group.lower() == work_group:
            score += 15
        if hint_author and work_author and hint_author.lower() in work_author:
            score += 15

        if is_review_page:
            subject = (work.get("subject") or "").lower()
            full_subject = (work.get("full_subject") or "").lower()
            if subject and subject in scan_text_lower:
                score += 30
            if full_subject and full_subject != subject and full_subject in scan_text_lower:
                score += 50

            scan_words = set(re.findall(r'[а-яА-Яa-zA-Z]{5,}', scan_text_lower))
            full_words = set(re.findall(r'[а-яА-Яa-zA-Z]{5,}', full_text.lower()))
            common_words = scan_words & full_words
            if common_words:
                word_bonus = len(common_words) * 5
                score += word_bonus
                logging.info(f"📄 [REVIEW] Общих слов (дл.>4): {len(common_words)}, бонус +{word_bonus}")

            for kw in ["курсовой", "курсовая", "лабораторная", "практическая", "индивидуальная"]:
                if kw in scan_text_lower:
                    score += 10
                    break

        scored_works.append((score, wid))

    if not scored_works:
        logging.info("📄 Агрегированный поиск: нет работ для сравнения")
        return None, None

    scored_works.sort(key=lambda x: x[0], reverse=True)
    best_score, best_work = scored_works[0]

    best_work_obj = works_by_id.get(best_work)
    best_filename = best_work_obj.get('filename', 'unknown') if best_work_obj else 'unknown'
    logging.info(f"📄 Агрегированный поиск: лучшая работа {best_work} ({best_filename}), score={best_score}")

    if len(scored_works) > 1:
        second_score = scored_works[1][0]
        if best_score - second_score < 15:
            if hint_group or hint_author:
                for wid, pages in pages_by_work.items():
                    work = works_by_id.get(wid)
                    if not work:
                        continue
                    work_group = (work.get("group") or "").lower()
                    work_author = (work.get("author") or "").lower()
                    if hint_group and work_group == hint_group.lower() and hint_author and work_author == hint_author.lower():
                        best_work = wid
                        logging.info(f"📄 Агрегированный поиск: выбрана работа по метаданным {best_work}")
                        break
                else:
                    logging.info("📄 Агрегированный поиск: не удалось найти работу по метаданным")
                    return None, None
            else:
                logging.info("📄 Агрегированный поиск: слишком маленькая разница и нет подсказок")
                return None, None

    threshold = 30 if is_review_page else 45
    if best_score < threshold and not (hint_group or hint_author):
        logging.info(f"📄 Агрегированный поиск: score {best_score} ниже порога {threshold}")
        return None, None

    work = works_by_id.get(best_work)
    # Раньше уже заменённые страницы (replaced_pages) полностью исключались из кандидатов —
    # из-за этого при повторном сканировании уже заменённого листа поиск не находил его
    # среди страниц работы (он был "невидим"), считал лист новым/неопознанным и либо
    # прикреплял OCR к случайной другой странице той же работы (портя её), либо создавал
    # лишний, будто задублированный запрос на замену другой страницы. Показ диалога
    # "уже заменено — заменить?" делается позже, в scan_processing.py, по факту найденного
    # page_num — сам поиск не должен прятать эти страницы.
    candidate_pages = pages_by_work.get(best_work, [])
    if not candidate_pages:
        logging.info("📄 Агрегированный поиск: нет доступных страниц для замены")
        return None, None

    if is_review_page:
        logging.info(f"📄 [REVIEW] Поиск страницы отзыва среди {len(candidate_pages)} страниц")

        def _dehyphenate(text: str) -> str:
            # OCR часто переносит слово по дефису на границе строки: "руководи- теля",
            # "Разработ- ка". После обычной нормализации пробелов это остаётся как
            # "руководи- теля" и ломает поиск цельной фразы "отзыв руководителя".
            return re.sub(r'(\w)-\s+(\w)', r'\1\2', text)

        for p in candidate_pages:
            p_text = (p.get("text") or "").lower()
            clean_text = _dehyphenate(re.sub(r'\s+', ' ', p_text).strip())
            if "отзыв руководителя" in clean_text:
                logging.info(f"📄 [REVIEW] Найдена страница с точной фразой 'отзыв руководителя': {p['page_num']}")
                return best_work, p["page_num"]

        for p in candidate_pages:
            p_text = (p.get("text") or "").lower()
            clean_text = _dehyphenate(re.sub(r'\s+', ' ', p_text).strip())
            if "отзыв руководител" in clean_text:
                logging.info(f"📄 [REVIEW] Найдена страница с частичной фразой 'отзыв руководител': {p['page_num']}")
                return best_work, p["page_num"]

        best_page = None
        best_total_score = 0
        for p in candidate_pages:
            p_text = _dehyphenate((p.get("text") or "").lower())
            if not p_text:
                continue
            fuzzy_score = fuzz.token_sort_ratio(scan_text, p_text)
            keyword_bonus = 0
            if "отзыв" in p_text:
                keyword_bonus += 20
            if "руководитель" in p_text:
                keyword_bonus += 20
            if "отзыв руководителя" in p_text:
                keyword_bonus += 40
            elif "отзыв руководител" in p_text:
                keyword_bonus += 30
            total_score = fuzzy_score + keyword_bonus
            if total_score > best_total_score:
                best_total_score = total_score
                best_page = p["page_num"]
        if best_page is not None and best_total_score > 50:
            logging.info(f"📄 [REVIEW] Выбрана страница по комбинированному скору: {best_page}, total={best_total_score}")
            return best_work, best_page

        keywords = {"отзыв": 5, "руководитель": 5, "рецензия": 3, "оценка": 2, "преподаватель": 2}
        best_kw_page = None
        best_kw_score = 0
        for p in candidate_pages:
            p_text = (p.get("text") or "").lower()
            kw_score = 0
            for kw, weight in keywords.items():
                if kw in p_text:
                    kw_score += weight
            if kw_score > best_kw_score:
                best_kw_score = kw_score
                best_kw_page = p["page_num"]
        if best_kw_page is not None and best_kw_score > 3:
            logging.info(f"📄 [REVIEW] Выбрана страница по отдельным ключевым словам: {best_kw_page}, score={best_kw_score}")
            return best_work, best_kw_page

        logging.warning(
            f"📄 [REVIEW] Не удалось найти подходящую страницу среди {len(candidate_pages)} "
            f"по тексту работы {best_work} — не гадаем номер страницы, считаем ненайденным."
        )
        return None, None

    best_page = None
    best_fuzzy_score = 0
    for p in candidate_pages:
        p_text = p.get("text", "")
        if not p_text:
            continue
        score = fuzz.token_sort_ratio(scan_text, p_text)
        if score > best_fuzzy_score:
            best_fuzzy_score = score
            best_page = p["page_num"]
    if best_page is not None and best_fuzzy_score > 40:
        logging.info(f"📄 Агрегированный поиск: выбрана страница по fuzzy-сходству: {best_page}, score={best_fuzzy_score}")
        return best_work, best_page

    logging.info(
        f"📄 Агрегированный поиск: сходство по тексту страниц низкое (best={best_fuzzy_score}) "
        f"среди {len(candidate_pages)} страниц работы {best_work} — не гадаем номер страницы, считаем ненайденным."
    )
    return None, None

async def migrate_works():
    _, _, works_collection = get_fs_and_collections()
    fs, _, _ = get_fs_and_collections()
    async for work in works_collection.find({"replaced_pages": {"$exists": False}}):
        temp_path = f"/tmp/migrate_{work['_id']}.pdf"
        try:
            stream = await fs.open_download_stream(work['file_id'])
            content = await stream.read()
            with open(temp_path, "wb") as f:
                f.write(content)
            reader = PdfReader(temp_path)
            pages_total = len(reader.pages)
            status = work.get("status", "digital_only")
            await works_collection.update_one(
                {"_id": work["_id"]},
                {"$set": {"replaced_pages": [], "pages_total": pages_total, "status": status}}
            )
        except Exception as e:
            print(f"Migration error for {work['_id']}: {e}")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

async def is_allowed_email_sender(tg_id: int) -> bool:
    """
    Проверяет, разрешено ли этому tg_id отправлять архив на личную (тестовую) почту.
    Бутстрап: если коллекция пуста и в config.py задан MY_TG_ID — считаем его разрешённым
    и сразу сохраняем в коллекцию, чтобы дальше проверка шла только по БД.
    """
    await init_indexes()
    doc = await allowed_email_senders_collection.find_one({"tg_id": tg_id})
    if doc:
        return True

    my_tg_id = getattr(config, "MY_TG_ID", None)
    if my_tg_id and int(my_tg_id) == int(tg_id):
        count = await allowed_email_senders_collection.count_documents({})
        if count == 0:
            await allowed_email_senders_collection.insert_one({"tg_id": tg_id})
        return True
    return False


async def add_allowed_email_sender(tg_id: int):
    """Добавляет tg_id в список доверенных отправителей на личную почту."""
    await init_indexes()
    await allowed_email_senders_collection.update_one(
        {"tg_id": tg_id}, {"$set": {"tg_id": tg_id}}, upsert=True
    )


async def get_cached_ocr(content_hash: str) -> str | None:
    """
    Возвращает ранее сохранённый результат Gemini OCR для страницы с данным хэшем
    содержимого, если он уже есть в кэше — иначе None. Это чисто техническая
    оптимизация: один и тот же физический скан (байт-в-байт), отправленный повторно
    (например, при повторном тестировании), не должен заново дёргать Gemini — прошлый
    результат не изменится, а лимит запросов (RPD) тратится впустую.
    """
    await init_indexes()
    doc = await ocr_cache_collection.find_one({"content_hash": content_hash})
    return doc.get("text") if doc else None


async def save_cached_ocr(content_hash: str, text: str):
    """Сохраняет результат Gemini OCR в кэш по хэшу содержимого страницы."""
    if not text:
        return
    await init_indexes()
    await ocr_cache_collection.update_one(
        {"content_hash": content_hash},
        {"$set": {"content_hash": content_hash, "text": text, "cached_at": datetime.utcnow()}},
        upsert=True,
    )


async def update_pages_text(work_ids: list, page_num: int, new_text: str):
    """
    Обновляет "мягко извлечённый" текст конкретной страницы в pages после того, как эта
    страница была заменена сканом. Без этого текст в pages навсегда остаётся от СТАРОГО
    содержимого — и последующий текстовый поиск по этой странице либо промахивается, либо
    (что хуже) даёт неверные совпадения, потому что сравнивает новый скан со старым текстом.
    """
    await init_indexes()
    _, _, works_collection = get_fs_and_collections()
    if not work_ids or not new_text:
        return

    # Все связанные работы (авторы) принадлежат одному пользователю — достаточно одного
    # запроса tg_id по первой работе вместо отдельного запроса на каждого автора.
    tg_id_doc = await works_collection.find_one({"_id": work_ids[0]}, {"tg_id": 1})
    tg_id_val = tg_id_doc.get("tg_id") if tg_id_doc else None

    await asyncio.gather(*[
        pages_collection.update_one(
            {"work_id": wid, "page_num": page_num},
            {"$set": {"text": new_text, "tg_id": tg_id_val, "work_id": wid, "page_num": page_num}},
            upsert=True
        )
        for wid in work_ids
    ])


async def update_multiple_works_with_scan(work_ids: list, file_bytes: bytes, new_filename: str, new_replaced_pages: list = None):
    fs, _, works_collection = get_fs_and_collections()
    if not work_ids:
        return

    new_file_id = await fs.upload_from_stream(new_filename, file_bytes)

    first_work = await works_collection.find_one({"_id": work_ids[0]})
    if not first_work:
        raise ValueError("Первая работа не найдена")

    old_file_id = first_work['file_id']
    existing_replaced = first_work.get("replaced_pages", [])
    if new_replaced_pages:
        merged_replaced = sorted(set(existing_replaced + new_replaced_pages))
    else:
        merged_replaced = existing_replaced

    tmp_path = f"/tmp/scan_upd_{uuid.uuid4().hex}.pdf"
    try:
        with open(tmp_path, "wb") as f:
            f.write(file_bytes)
        reader = PdfReader(tmp_path)
        pages_total = len(reader.pages)
        status = "fully_replaced" if len(merged_replaced) == pages_total else "merged"
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    for wid in work_ids:
        await works_collection.update_one(
            {"_id": wid},
            {"$set": {
                "file_id": new_file_id,
                "pages_total": pages_total,
                "replaced_pages": merged_replaced,
                "status": status,
                "updated_at": datetime.utcnow()
            }}
        )

    try:
        await fs.delete(old_file_id)
    except Exception as e:
        logging.warning(f"Не удалось удалить старый файл {old_file_id}: {e}")

    page_texts = await extract_page_texts(file_bytes)
    for wid in work_ids:
        await pages_collection.delete_many({"work_id": wid})
        for page_num, text in page_texts:
            if text and text.strip():
                await pages_collection.update_one(
                    {"work_id": wid, "page_num": page_num},
                    {"$set": {"text": text, "tg_id": first_work['tg_id']}},
                    upsert=True
                )

async def ping() -> bool:
    global db_instance
    if db_instance is None:
        _init_motor()
    try:
        await db_instance.command('ping')
        return True
    except Exception as e:
        logging.error(f"MongoDB ping failed: {e}")
        return False
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import database as db_mod
import scraper as scr
import translator_utils as tr
import edge_tts
import re
from datetime import datetime
from contextlib import asynccontextmanager
from slugify import slugify
import random
from routes.auth import router as auth_router
from routes.user import router as user_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Hệ thống Convert đã sẵn sàng với 1.4 triệu cụm từ!")
    # Đảm bảo nạp từ điển vào RAM từ đây
    tr.translator.load_all_dicts()
    await db_mod.connect()
    yield
    try:
        await scr.close_browser()
    except Exception as e:
        print(f"⚠️ Lỗi khi đóng browser context: {e}")
    await db_mod.disconnect()
    print("💤 Hệ thống đang đóng...")

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"success": True, "message": "FastAPI backend is running."}

app.include_router(auth_router)
app.include_router(user_router)

class TranslationRequest(BaseModel):
    url: str

def format_chapter_url(url: str) -> str:
    url = url.strip()
    if url.endswith(".htm"):
        return url.rsplit('.', 1)[0] + "/"
    if not url.endswith("/"):
        return url + "/"
    return url


def generate_unique_slug(title: str) -> str:
    base_slug = slugify(title)
    suffix = str(random.randint(1000, 9999))  # 4 số ngẫu nhiên
    return f"{base_slug}-{suffix}"


@app.get("/books")
async def api_list_books(
    slug: Optional[str] = None,
    source_url: Optional[str] = None,
    id: Optional[str] = None,
    limit: int = 12,
    skip: int = 0,
    q: Optional[str] = None,
):
    try:
        if slug:
            book = await db_mod.client.book.find_unique(where={"slug": slug})
            if not book:
                return {"success": True, "data": []}
            source_url_value = getattr(book, "source_url", None) if not isinstance(book, dict) else book["source_url"]
            chapters_count = await db_mod.client.chapter.count(where={"book_source_url": source_url_value})
            return {"success": True, "data": [db_mod.serialize_book_row(book, chapters_count)]}

        if source_url:
            book = await db_mod.client.book.find_unique(where={"source_url": source_url})
            if not book:
                return {"success": True, "data": []}
            source_url_value = getattr(book, "source_url", None) if not isinstance(book, dict) else book["source_url"]
            chapters_count = await db_mod.client.chapter.count(where={"book_source_url": source_url_value})
            return {"success": True, "data": [db_mod.serialize_book_row(book, chapters_count)]}

        if id:
            book = await db_mod.client.book.find_unique(where={"id": id})
            if not book:
                return {"success": True, "data": []}
            source_url_value = getattr(book, "source_url", None) if not isinstance(book, dict) else book["source_url"]
            chapters_count = await db_mod.client.chapter.count(where={"book_source_url": source_url_value})
            return {"success": True, "data": [db_mod.serialize_book_row(book, chapters_count)]}

        where_clause = {}
        if q and q.strip():
            where_clause = {
                "OR": [
                    {"title_vi": {"contains": q, "mode": "insensitive"}},
                    {"title_en": {"contains": q, "mode": "insensitive"}},
                ]
            }

        books = await db_mod.client.book.find_many(
            where=where_clause,
            order={"updatedAt": "desc"},
            skip=skip,
            take=limit,
        )

        payload = []
        for book in books:
            source_url_value = getattr(book, "source_url", None) if not isinstance(book, dict) else book["source_url"]
            chapters_count = await db_mod.client.chapter.count(where={"book_source_url": source_url_value})
            payload.append(db_mod.serialize_book_row(book, chapters_count))

        total = await db_mod.client.book.count(where=where_clause)
        return {"success": True, "data": payload, "total": total, "limit": limit, "skip": skip}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/books/search")
async def api_search_books(q: str = Query(...)):
    return await api_list_books(q=q, limit=10, skip=0)


@app.get("/chapters")
async def api_list_chapters(book: Optional[str] = None):
    if not book:
        raise HTTPException(status_code=400, detail="Missing book parameter")

    try:
        chapters = await db_mod.client.chapter.find_many(
            where={"book_source_url": book},
            order={"chapter_no": "asc"},
        )
        return {"success": True, "data": [db_mod.serialize_chapter_row(ch) for ch in chapters]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- CÁC API ENDPOINTS GIỮ NGUYÊN ---

# --- PHẦN SỬA ĐỔI CHO ĐỌC TRUYỆN & TTS ---

def build_paragraphs_from_raw_content(raw_content: str) -> list[str]:
    raw_lines = [p.strip() for p in raw_content.split('\n') if p.strip()]
    translated_paragraphs = []

    for line in raw_lines:
        translated = tr.translate_text(line)
        if not re.match(r'^\d{4}-\d{2}-\d{2}', translated):
            translated_paragraphs.append(translated)

    return translated_paragraphs


async def resolve_chapter_content(url: str) -> tuple[list[str], str]:
    cached_content = await db_mod.get_chapter_content_by_url(url)
    if cached_content:
        paragraphs = [p.strip() for p in cached_content.splitlines() if p.strip()]
        return paragraphs, "db"

    if "sangtacviet" in url:
        raw_content = await scr.scrape_stv_chapter_content(url)
    else:
        raw_content = await scr.scrape_chapter_content(url)

    if not raw_content:
        raise HTTPException(status_code=400, detail="Không lấy được nội dung.")

    paragraphs = build_paragraphs_from_raw_content(raw_content)
    await db_mod.save_chapter_content(url, paragraphs)
    return paragraphs, "crawler"


@app.post("/get-chapter-content")
async def api_get_content(request: TranslationRequest):
    try:
        paragraphs, source = await resolve_chapter_content(request.url)
        return {
            "success": True,
            "paragraphs": paragraphs,
            "source": source,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stream-chapter-audio")
async def api_stream_audio(
    text: str = Query(...), 
    rate: str = Query("+0%"), 
    voice: str = Query("vi-VN-NamMinhNeural")
):
    # FIX LỖI UBUNTU: Biến dấu cách (do URL decode nhầm) thành dấu +
    rate_clean = rate.replace(" ", "+").strip()
    
    # Đảm bảo luôn có dấu + hoặc - ở đầu
    if not rate_clean.startswith("+") and not rate_clean.startswith("-"):
        rate_clean = "+" + rate_clean

    try:
        communicate = edge_tts.Communicate(text, voice, rate=rate_clean)
        async def audio_generator():
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    yield chunk["data"]
        return StreamingResponse(audio_generator(), media_type="audio/mpeg")
    except Exception as e:
        print(f"❌ Lỗi TTS: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- Cập nhật endpoint /get-basic-info ---
@app.post("/get-basic-info")
async def api_get_info(request: TranslationRequest):
    print(f"🔍 Đang lấy thông tin: {request.url}")
    
    if "sangtacviet.com" in request.url.lower():
        # Dùng logic mới cho STV (Không cần dịch qua tr.translate_text)
        raw = await scr.scrape_stv_basic_info(request.url)
        if not raw: raise HTTPException(status_code=400, detail="Lỗi nguồn STV")
        
        book_data = {
            "source_url": request.url,
            "title_vi": raw.get('title_vi'),
            "author_vi": raw.get('author_vi'),
            "description_vi": raw.get('description_vi'),
            "cover_url": raw.get('cover_url', ''),
            "status": "info_only",
            "updated_at": datetime.now().isoformat(),
            "slug": generate_unique_slug(raw.get('title_vi'))
        }
    else:
        # GIỮ NGUYÊN LOGIC CŨ CỦA PHONG CHO SHUBA
        raw = await scr.scrape_basic_info(request.url)
        if not raw: raise HTTPException(status_code=400, detail="Không lấy được dữ liệu.")
        title_translated = tr.translate_text(raw.get('title_cn', ''))
        book_data = {
            "source_url": request.url,
            "title_vi": title_translated,
            "author_vi": tr.translate_text(raw.get('author_cn', '')),
            "description_vi": tr.translate_text(raw.get('description_cn', ''), limit=1000),
            "cover_url": raw.get('cover_url', ''),
            "status": "info_only",
            "updated_at": datetime.now().isoformat(),
            "slug": generate_unique_slug(title_translated)
        }
    
    await db_mod.save_book(book_data)
    return {"success": True, "data": book_data}

# --- Cập nhật endpoint /get-chapters ---
@app.post("/get-chapters")
async def api_get_chapters(request: TranslationRequest):
    if "sangtacviet.com" in request.url.lower():
        raw_chapters = await scr.scrape_stv_chapters(request.url)
        is_stv = True
    else:
        chapter_url = format_chapter_url(request.url)
        raw_chapters = await scr.scrape_chapters(chapter_url)
        is_stv = False

    if not raw_chapters:
        raise HTTPException(status_code=400, detail="Không lấy được danh sách chương.")
    
    try:
        translated_chapters = []
        for index, ch in enumerate(raw_chapters):
            # Nếu là STV thì lấy title_vi trực tiếp, nếu không thì dịch title_cn
            title_final = ch.get('title_vi') if is_stv else tr.translate_text(ch.get('title_cn', ''))
            
            translated_chapters.append({
                "chapter_no": index + 1,
                "title_vi": title_final,
                "url": ch.get('url', ''),
                "slug": generate_unique_slug(title_final)
            })
        
        await db_mod.save_chapters(request.url, translated_chapters)
        return {"success": True, "total": len(translated_chapters), "chapters": translated_chapters}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

@app.get("/get-qidian-rank")
async def api_get_qidian_rank(
    type: str = "yuepiao", 
    chn: int = -1,          # Đổi mặc định thành -1 để khớp với mục "Tất Cả" mới cập nhật
    page: int = 1,          # Bổ sung tham số phân trang page
    year: str = None,       # Bổ sung bộ lọc năm động
    month: str = None       # Bổ sung bộ lọc tháng động
):
    """
    Endpoint xử lý dữ liệu In-Memory (RAM):
    - Nhận tham số loại BXH (type), ID Thể loại (chn), phân trang (page) và thời gian (year, month).
    - Gọi hàm cào đa năng từ scraper.py để lấy mảng chữ Hán thô theo thời gian chỉ định.
    - Chạy qua bộ dịch thuật Aho-Corasick có sẵn trong RAM để Việt hóa.
    - Định dạng lại tên trường (camelCase) và bọc dữ liệu chuẩn theo thiết kế Frontend.
    """
    try:
        # 1. Gọi hàm cào từ scraper.py, chuyển tiếp toàn bộ tham số bộ lọc thời gian và phân trang
        raw_data = await scr.scrape_qidian_ranking(
            category_id=type, 
            chn_id=chn, 
            page=page, 
            year=year, 
            month=month
        )
        
        if not raw_data:
            return {
                "success": False, 
                "data": {"data": []}, 
                "message": "Không tìm thấy hoặc lỗi cào dữ liệu từ nguồn gốc."
            }

        translated_results = []
        
        for book in raw_data:
            # 2. Đưa qua bộ dịch thuật Aho-Corasick đã được map sẵn trong RAM từ lúc khởi động hệ thống
            title_vi = tr.translate_text(book['title_cn'])
            author_vi = tr.translate_text(book['author_cn'])
            category_vi = tr.translate_text(book['category_cn'])
            desc_vi = tr.translate_text(book['desc_cn'], limit=500)  # Giới hạn độ dài mô tả cho gọn UI
            
            # 3. Tạo cấu trúc key phẳng, chuẩn camelCase khớp 100% với file page.tsx của Next.js
            translated_results.append({
                "rank": getattr(book, 'rank', None) if not isinstance(book, dict) else book['rank'],
                "title": title_vi if title_vi else (getattr(book, 'title_cn', None) if not isinstance(book, dict) else book['title_cn']),
                "title_cn": getattr(book, 'title_cn', None) if not isinstance(book, dict) else book['title_cn'],
                "author": author_vi if author_vi else "Ẩn danh",
                "category": category_vi if category_vi else "Chưa phân loại",
                "intro": desc_vi if desc_vi else "Chưa có tóm tắt cốt truyện...",
                "coverUrl": getattr(book, 'cover_url', None) if not isinstance(book, dict) else book['cover_url'],
                "sourceUrl": getattr(book, 'source_url', None) if not isinstance(book, dict) else book['source_url'],
                "slug": generate_unique_slug(title_vi if title_vi else (getattr(book, 'title_cn', None) if not isinstance(book, dict) else book['title_cn']))
            })

        # 4. Bọc đúng 2 lớp .data.data để tương thích hoàn toàn với logic check bên Next.js
        return {
            "success": True,
            "data": {
                "data": translated_results
            }
        }

    except Exception as e:
        print(f"🔥 Lỗi nghiêm trọng tại API BXH Qidian: {e}")
        raise HTTPException(status_code=500, detail=str(e))
"""
FastAPI backend — Thư viện tài liệu RAG.

Endpoints:
  POST /index               → Index thư mục Google Drive (incremental)
  POST /index/stream        → Giống /index nhưng stream tiến độ qua SSE
  GET  /library             → Danh sách toàn bộ tài liệu trong thư viện
  GET  /library/stats       → Thống kê thư viện (số tài liệu, loại, trang)
  GET  /library/{doc_name}  → Chi tiết + mục lục tài liệu cụ thể
  POST /query               → Hỏi đáp (tự động chọn luồng: library/overview/detail)
  POST /diagnostic-report   → Báo cáo phân tích chuyên sâu, không dùng RAG
  POST /web_search          → Tìm kiếm trên internet
  GET  /health              → Trạng thái server
"""

from __future__ import annotations

import json
import logging
import shutil
import time
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import unquote

import numpy as np
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from chunking import chunk_pdf_hierarchical
from config import GDRIVE_INDEX_FOLDER_ID, PDF_BATCH_SIZE, TEMP_PDF_DIR
from drive_sync import (clear_drive_index, clear_local_index,
                        pull_index_from_drive, push_index_to_drive)
from embedding import embed_texts
from ingest_drive import iter_pdfs_from_drive
from query import (answer_diagnostic_report, answer_question,
                   answer_question_stream, web_search_question)
from vector_store import get_store, reset_store

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def cleanup_temp_pdfs() -> None:
    """Xóa PDF tạm sau khi index/sync để tránh phình disk runtime."""
    try:
        if TEMP_PDF_DIR.exists():
            shutil.rmtree(TEMP_PDF_DIR)
        TEMP_PDF_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("cleanup: đã xóa PDF tạm trong %s", TEMP_PDF_DIR)
    except Exception:
        logger.exception("cleanup: không xóa được PDF tạm")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if GDRIVE_INDEX_FOLDER_ID:
        logger.info("startup: đang tải index từ Google Drive...")
        ok = pull_index_from_drive()
        logger.info("startup: pull index %s", "thành công" if ok else "không có dữ liệu / bỏ qua")
    else:
        logger.info("startup: GDRIVE_INDEX_FOLDER_URL chưa cấu hình, bỏ qua tải index từ Google Drive")
    yield


app = FastAPI(title="Library RAG API", version="2.0.0", lifespan=lifespan)


@app.middleware("http")
async def log_request_time(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    logger.info("%-6s %-30s → %d  %.3fs",
                request.method, request.url.path, response.status_code,
                time.perf_counter() - t0)
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.options("/{rest_of_path:path}")
async def preflight(rest_of_path: str, request: Request):
    return JSONResponse(content={}, headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization, Accept",
    })


# ── Schemas ────────────────────────────────────────────────────────────────────

class IndexRequest(BaseModel):
    google_drive_folder_url: str
    public: bool = True


class IndexResponse(BaseModel):
    message: str
    indexed_files: int
    skipped_files: int
    total_chunks: int


class HistoryMessage(BaseModel):
    role: str
    content: str


class QueryRequest(BaseModel):
    question: str
    k: int = Field(default=5, ge=1, le=20)
    history: list[HistoryMessage] = Field(default_factory=list)


class DiagnosticReportRequest(BaseModel):
    question: str
    history: list[HistoryMessage] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class QueryResponse(BaseModel):
    answer: str
    sources: list[dict]
    needs_web_search: bool = False


# ── Index endpoints ────────────────────────────────────────────────────────────

@app.post("/index", response_model=IndexResponse)
async def index_folder(req: IndexRequest):
    """Index toàn bộ PDF từ thư mục Google Drive. File đã index sẽ được bỏ qua."""
    store = get_store()
    indexed_count = 0
    skipped_count = 0
    total_chunks = 0
    batch_chunks = []
    batch_embeddings_list = []

    try:
        for pdf_path, file_name in iter_pdfs_from_drive(req.google_drive_folder_url, public=req.public):
            if store.is_indexed(file_name):
                logger.info("Bỏ qua (đã index): %s", file_name)
                skipped_count += 1
                continue

            logger.info("── Index: %s", file_name)
            t_chunk = time.perf_counter()
            chunks, doc_meta = chunk_pdf_hierarchical(Path(pdf_path), file_name)
            logger.info("  [chunk] %d chunks, %d trang | %.2fs",
                        len(chunks), doc_meta.page_count, time.perf_counter() - t_chunk)
            if not chunks:
                logger.warning("Không trích xuất được text: %s", file_name)
                skipped_count += 1
                continue

            t_emb = time.perf_counter()
            embeddings = embed_texts([c.text for c in chunks])
            logger.info("  [embed-total] %d vectors | %.2fs",
                        len(chunks), time.perf_counter() - t_emb)
            batch_chunks.extend(chunks)
            batch_embeddings_list.append(embeddings)
            total_chunks += len(chunks)
            indexed_count += 1

            # Lưu metadata tài liệu vào catalog
            store.upsert_document(file_name, doc_meta)

            if indexed_count % PDF_BATCH_SIZE == 0:
                store.add_chunks(batch_chunks, np.vstack(batch_embeddings_list))
                store.save()
                batch_chunks = []
                batch_embeddings_list = []

        if batch_chunks:
            store.add_chunks(batch_chunks, np.vstack(batch_embeddings_list))
            store.save()

        # Push lên Drive mỗi lần index — đảm bảo Drive luôn có bản mới nhất
        push_index_to_drive()

    except Exception as exc:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        cleanup_temp_pdfs()

    return IndexResponse(
        message="Indexing hoàn tất",
        indexed_files=indexed_count,
        skipped_files=skipped_count,
        total_chunks=total_chunks,
    )


@app.post("/index/clear")
async def clear_index():
    """Xóa toàn bộ dữ liệu index local và remote Drive đã cấu hình."""
    local_deleted = clear_local_index()
    reset_store()
    remote_deleted = clear_drive_index() if GDRIVE_INDEX_FOLDER_ID else 0
    return {
        "message": "Đã xóa index local và Drive.",
        "local_deleted": local_deleted,
        "remote_deleted": remote_deleted,
    }


@app.post("/index/stream")
async def index_folder_stream(req: IndexRequest):
    """Stream tiến độ index qua Server-Sent Events."""
    def generate():
        store = get_store()
        indexed_count = 0
        skipped_count = 0
        total_chunks = 0
        batch_chunks = []
        batch_embeddings_list = []

        try:
            for pdf_path, file_name in iter_pdfs_from_drive(req.google_drive_folder_url, public=req.public):
                if store.is_indexed(file_name):
                    skipped_count += 1
                    yield f"data: {json.dumps({'status': 'skipped', 'file': file_name, 'indexed': indexed_count, 'skipped': skipped_count, 'chunks_so_far': total_chunks}, ensure_ascii=False)}\n\n"
                    continue

                yield f"data: {json.dumps({'status': 'processing', 'file': file_name, 'indexed': indexed_count, 'skipped': skipped_count, 'chunks_so_far': total_chunks}, ensure_ascii=False)}\n\n"

                logger.info("── Index: %s", file_name)
                t_chunk = time.perf_counter()
                chunks, doc_meta = chunk_pdf_hierarchical(Path(pdf_path), file_name)
                logger.info("  [chunk] %d chunks, %d trang | %.2fs",
                            len(chunks), doc_meta.page_count, time.perf_counter() - t_chunk)
                if not chunks:
                    logger.warning("Không trích xuất được text: %s", file_name)
                    skipped_count += 1
                    yield f"data: {json.dumps({'status': 'skipped', 'reason': 'no_text', 'file': file_name, 'indexed': indexed_count, 'skipped': skipped_count, 'chunks_so_far': total_chunks}, ensure_ascii=False)}\n\n"
                    continue

                t_emb = time.perf_counter()
                embeddings = embed_texts([c.text for c in chunks])
                logger.info("  [embed-total] %d vectors | %.2fs",
                            len(chunks), time.perf_counter() - t_emb)
                batch_chunks.extend(chunks)
                batch_embeddings_list.append(embeddings)
                total_chunks += len(chunks)
                indexed_count += 1

                store.upsert_document(file_name, doc_meta)

                if indexed_count % PDF_BATCH_SIZE == 0:
                    store.add_chunks(batch_chunks, np.vstack(batch_embeddings_list))
                    store.save()
                    batch_chunks = []
                    batch_embeddings_list = []

            if batch_chunks:
                store.add_chunks(batch_chunks, np.vstack(batch_embeddings_list))
                store.save()

            # Push lên Drive mỗi lần index — báo cho UI biết để hiển thị tiến trình
            yield f"data: {json.dumps({'status': 'syncing', 'file': '', 'indexed': indexed_count, 'skipped': skipped_count, 'chunks_so_far': total_chunks}, ensure_ascii=False)}\n\n"
            push_index_to_drive()
            cleanup_temp_pdfs()

            yield f"data: {json.dumps({'status': 'done', 'message': 'Indexing hoàn tất', 'indexed_files': indexed_count, 'skipped_files': skipped_count, 'total_chunks': total_chunks}, ensure_ascii=False)}\n\n"

        except Exception as exc:
            logger.error(traceback.format_exc())
            cleanup_temp_pdfs()
            yield f"data: {json.dumps({'status': 'error', 'detail': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/index/upload", response_model=IndexResponse)
async def index_upload(files: list[UploadFile] = File(...)):
    """Index PDF tải lên trực tiếp từ thiết bị. Hỗ trợ nhiều file cùng lúc."""
    import tempfile
    store = get_store()
    indexed_count = 0
    skipped_count = 0
    total_chunks = 0
    batch_chunks = []
    batch_embeddings_list = []

    logger.info("index_upload: nhận %d file", len(files))
    try:
        for upload in files:
            file_name = Path(upload.filename or "unnamed.pdf").name
            logger.info("index_upload: xử lý %s", file_name)
            if not file_name.lower().endswith(".pdf"):
                logger.warning("Bỏ qua (không phải PDF): %s", file_name)
                skipped_count += 1
                continue
            if store.is_indexed(file_name):
                logger.info("Bỏ qua (đã index): %s", file_name)
                skipped_count += 1
                continue

            content = await upload.read()
            if not content:
                logger.warning("File rỗng (0 bytes): %s — bỏ qua", file_name)
                skipped_count += 1
                continue

            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(content)
                tmp_path = Path(tmp.name)

            try:
                logger.info("── Index (upload): %s | %.1f KB", file_name, tmp_path.stat().st_size / 1024)
                chunks, doc_meta = chunk_pdf_hierarchical(tmp_path, file_name)
                if not chunks:
                    logger.warning("Không trích xuất được text: %s", file_name)
                    skipped_count += 1
                    continue

                embeddings = embed_texts([c.text for c in chunks])
                batch_chunks.extend(chunks)
                batch_embeddings_list.append(embeddings)
                total_chunks += len(chunks)
                indexed_count += 1
                store.upsert_document(file_name, doc_meta)

                if indexed_count % PDF_BATCH_SIZE == 0:
                    store.add_chunks(batch_chunks, np.vstack(batch_embeddings_list))
                    store.save()
                    batch_chunks = []
                    batch_embeddings_list = []
            finally:
                tmp_path.unlink(missing_ok=True)

        if batch_chunks:
            store.add_chunks(batch_chunks, np.vstack(batch_embeddings_list))
            store.save()

        push_index_to_drive()

    except Exception as exc:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        cleanup_temp_pdfs()

    return IndexResponse(
        message="Indexing hoàn tất",
        indexed_files=indexed_count,
        skipped_files=skipped_count,
        total_chunks=total_chunks,
    )


# ── Library endpoints ──────────────────────────────────────────────────────────

@app.get("/library")
async def list_library():
    """Danh sách toàn bộ tài liệu đã index trong thư viện."""
    store = get_store()
    docs = store.get_all_documents()
    return {"total": len(docs), "documents": docs}


@app.get("/library/stats")
async def library_stats():
    """Thống kê thư viện: số tài liệu, phân loại, tổng trang."""
    store = get_store()
    return store.get_library_stats()


@app.get("/library/{doc_name:path}")
async def get_document(doc_name: str):
    """Chi tiết và mục lục của một tài liệu. doc_name là tên file (có thể có khoảng trắng)."""
    name = unquote(doc_name)
    store = get_store()
    doc = store.get_document(name)
    if doc is None:
        # Thử tìm theo từ khóa
        doc = store.find_document_by_keyword(name)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy tài liệu: {name}")
    return doc


# ── Query endpoint ─────────────────────────────────────────────────────────────

@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    """
    Hỏi đáp thư viện. Tự động chọn luồng:
    - Câu hỏi thư viện → trả trực tiếp từ DB
    - Tóm tắt/mục lục → dùng L1+L2 chunk
    - Câu hỏi chi tiết → RAG đầy đủ với trích dẫn
    """
    try:
        history = [{"role": m.role, "content": m.content} for m in req.history]
        result = answer_question(req.question, k=req.k, history=history)
        return QueryResponse(**result)
    except Exception as exc:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/diagnostic-report", response_model=QueryResponse)
async def diagnostic_report(req: DiagnosticReportRequest):
    """Tạo báo cáo phân tích chuyên sâu từ prompt hồ sơ bệnh nhân, không dùng luồng RAG /query."""
    try:
        history = [{"role": m.role, "content": m.content} for m in req.history]
        result = answer_diagnostic_report(req.question, history=history, metadata=req.metadata)
        return QueryResponse(**result)
    except Exception as exc:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/query/stream")
async def query_stream(req: QueryRequest):
    """Streaming /query qua SSE — yield delta token-by-token rồi sources cuối cùng."""
    history = [{"role": m.role, "content": m.content} for m in req.history]

    def generate():
        try:
            for event in answer_question_stream(req.question, k=req.k, history=history):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            logger.error(traceback.format_exc())
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/web_search", response_model=QueryResponse)
async def web_search(req: QueryRequest):
    """Tìm kiếm câu hỏi trên internet qua DeepSeek web search."""
    try:
        result = web_search_question(req.question)
        return QueryResponse(**result)
    except Exception as exc:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/")
async def root():
    return {
        "service": "Library RAG API",
        "version": "2.0.0",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
async def health():
    store = get_store()
    stats = store.get_library_stats()
    return {"status": "ok", **stats}


@app.post("/drive/authorize")
async def drive_authorize():
    """Chạy OAuth flow lần đầu — mở browser, lưu token để các lần sau tự dùng."""
    try:
        from drive_auth import authorize_oauth
        creds = authorize_oauth(
            scopes=["https://www.googleapis.com/auth/drive"],
            headless=False,
        )
        return {"status": "ok", "has_refresh_token": bool(creds.refresh_token)}
    except Exception as exc:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(exc))

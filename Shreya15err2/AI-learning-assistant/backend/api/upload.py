import os
import uuid
import shutil
from fastapi import APIRouter, UploadFile, File, HTTPException
from services.ocr_service import extract_text_from_pdf
from database.chroma import store_document
from utils.text_processing import clean_text, chunk_text, remove_duplicates, merge_short_chunks
from models.schemas import UploadResponse

router = APIRouter()

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.post("/upload", response_model=UploadResponse)
async def upload_pdf(file: UploadFile = File(...)):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    document_id = str(uuid.uuid4())
    safe_filename = f"{document_id}_{file.filename}"
    save_path = os.path.join(UPLOAD_DIR, safe_filename)

    try:
        with open(save_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

    try:
        raw_text, page_count = extract_text_from_pdf(save_path)
    except Exception as e:
        if os.path.exists(save_path):
            os.remove(save_path)
        raise HTTPException(status_code=500, detail=f"OCR failed: {str(e)}")

    cleaned = clean_text(raw_text)
    chunks = chunk_text(cleaned, chunk_size=500, overlap=50)
    chunks = remove_duplicates(chunks)
    chunks = merge_short_chunks(chunks)

    if not chunks:
        if os.path.exists(save_path):
            os.remove(save_path)
        raise HTTPException(status_code=422, detail="No text could be extracted from this PDF")

    try:
        stored_chunks = store_document(
            document_id=document_id,
            filename=file.filename,
            chunks=chunks
        )
    except Exception as e:
        if os.path.exists(save_path):
            os.remove(save_path)
        raise HTTPException(status_code=500, detail=f"Database storage failed: {str(e)}")

    return UploadResponse(
        message="PDF uploaded and processed successfully",
        document_id=document_id,
        filename=file.filename,
        chunks=stored_chunks,
        pages=page_count
    )

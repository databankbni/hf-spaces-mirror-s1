import os
import shutil
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, TTSJob
from app.schemas import TTSJobResponse
from app.services.job_service import JobService
from app.services.audio_service import AudioService
from app.utils.auth import get_user_or_api_key
from app.config import settings

router = APIRouter(prefix="/v1/asr", tags=["ASR (Speech-to-Text)"])

@router.post("", response_model=TTSJobResponse)
async def create_asr_job(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_user_or_api_key)
):
    """
    Tải lên một file âm thanh và khởi tạo một tác vụ ASR (Speech-to-Text).
    """
    AudioService.ensure_directories()
    
    # 1. Generate unique file name and temporary upload path
    temp_id = f"asr_temp_{uuid.uuid4().hex[:8]}"
    filename = file.filename or f"{temp_id}_raw"
    ext = os.path.splitext(filename)[1] or ".bin"
    upload_temp_path = os.path.join(settings.uploads_dir, f"{temp_id}_raw{ext}")
    
    # 2. Save uploaded file to temp path
    try:
        with open(upload_temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Không thể lưu file âm thanh tải lên: {e}"
        )
        
    # 3. Standardize to mono WAV format
    target_filename = f"{temp_id}.wav"
    try:
        # Standardize and save into voice_samples directory or uploads directory
        saved_path, duration, sample_rate = AudioService.process_and_save_upload(
            upload_temp_path, target_filename
        )
        # Move standardized file to uploads directory instead
        final_dest = os.path.join(settings.uploads_dir, target_filename)
        if os.path.exists(saved_path):
            shutil.move(saved_path, final_dest)
        else:
            final_dest = saved_path
            
        if os.path.exists(upload_temp_path):
            os.remove(upload_temp_path)
            
    except Exception as e:
        if os.path.exists(upload_temp_path):
            os.remove(upload_temp_path)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Định dạng tệp âm thanh không hợp lệ hoặc lỗi xử lý: {e}"
        )
        
    # 4. Create Job
    try:
        # We pass final_dest which is the temporary file path of the WAV file on gateway disk
        job = JobService.create_asr_job(
            db=db,
            ref_audio_path=final_dest,
            user_id=current_user.id
        )
        # Rename the file on disk to match the actual job.id
        actual_dest = os.path.join(settings.uploads_dir, f"{job.id}.wav")
        shutil.move(final_dest, actual_dest)
        job.ref_audio_path = actual_dest
        db.commit()
        
        return TTSJobResponse(
            job_id=job.id,
            status=job.status,
            message=job.message
        )
    except Exception as e:
        if os.path.exists(final_dest):
            os.remove(final_dest)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Lỗi tạo ASR Job: {e}"
        )

@router.get("/jobs/{job_id}/audio")
def get_asr_audio(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_user_or_api_key)
):
    """
    Phát lại file âm thanh gốc đã tải lên của một ASR Job.
    """
    job = db.query(TTSJob).filter(TTSJob.id == job_id, TTSJob.user_id == current_user.id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy Job {job_id}"
        )
        
    if not job.ref_audio_path or not os.path.exists(job.ref_audio_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tệp âm thanh gốc không tồn tại trên máy chủ."
        )
        
    return FileResponse(
        job.ref_audio_path,
        media_type="audio/wav",
        filename=f"asr_{job_id}.wav",
        content_disposition_type="inline"
    )

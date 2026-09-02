import os
import shutil
from typing import Optional, List
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import VoiceSample, User
from app.schemas import VoiceSampleUploadResponse, VoiceSampleResponse, SaveFavoriteVoiceRequest, VoiceSampleUpdateRequest, VoiceLibraryItemResponse
from app.utils.ids import generate_id
from app.utils.slugify import slugify
from app.services.audio_service import AudioService
from app.config import settings
from app.utils.auth import get_user_or_api_key

router = APIRouter(prefix="/v1/voice-samples", tags=["Voice Samples"])

@router.post("", response_model=VoiceSampleUploadResponse)
async def upload_voice_sample(
    file: UploadFile = File(...),
    ref_text: Optional[str] = Form(None),
    name: Optional[str] = Form(None),
    custom_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_user_or_api_key)
):
    """
    Uploads a raw voice audio file (wav/mp3/flac), saves the upload,
    standardizes it to mono WAV format, and registers it as a Voice Sample.
    """
    AudioService.ensure_directories()
    
    # 1. Resolve ID
    resolved_id = None
    if custom_id and custom_id.strip():
        norm_id = slugify(custom_id)
        if not norm_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mã ID giọng nói không hợp lệ (không chứa ký tự hợp lệ)."
            )
        # Check database uniqueness
        existing = db.query(VoiceSample).filter(VoiceSample.id == norm_id).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Mã ID giọng nói '{norm_id}' đã được sử dụng. Vui lòng chọn mã khác."
            )
        resolved_id = norm_id
    else:
        # Auto-slugify from name or filename
        base_name = name or file.filename or "uploaded_voice"
        if not name and file.filename:
            base_name = os.path.splitext(file.filename)[0]
            
        norm_id = slugify(base_name)
        if not norm_id:
            norm_id = "voice_sample"
            
        # Ensure unique resolved ID
        resolved_id = norm_id
        suffix_counter = 1
        while db.query(VoiceSample).filter(VoiceSample.id == resolved_id).first():
            resolved_id = f"{norm_id}_{suffix_counter}"
            suffix_counter += 1

    # 2. Resolve Name
    resolved_name = name.strip() if name and name.strip() else None
    if not resolved_name and file.filename:
        resolved_name = os.path.splitext(file.filename)[0]
        
    # Save the original upload first
    filename = file.filename or f"{resolved_id}_raw"
    ext = os.path.splitext(filename)[1] or ".bin"
    upload_temp_path = os.path.join(settings.uploads_dir, f"{resolved_id}_raw{ext}")
    
    try:
        with open(upload_temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Không thể lưu file tải lên: {e}"
        )
    
    # Standardize and save into voice_samples
    target_filename = f"{resolved_id}.wav"
    try:
        saved_path, duration, sample_rate = AudioService.process_and_save_upload(
            upload_temp_path, target_filename
        )
    except Exception as e:
        if os.path.exists(upload_temp_path):
            os.remove(upload_temp_path)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Định dạng tệp âm thanh không hợp lệ hoặc lỗi xử lý: {e}"
        )

    # Save details to database
    db_sample = VoiceSample(
        id=resolved_id,
        user_id=current_user.id,
        name=resolved_name,
        source_type="uploaded",
        file_path=saved_path,
        ref_text=ref_text,
        duration=duration,
        sample_rate=sample_rate,
        status="ready"
    )
    
    db.add(db_sample)
    db.commit()
    db.refresh(db_sample)
    
    return VoiceSampleUploadResponse(
        voice_sample_id=resolved_id,
        status="ready",
        message="Đã nhận voice sample."
    )

@router.get("", response_model=List[VoiceSampleResponse])
def list_voice_samples(tag: Optional[str] = None, db: Session = Depends(get_db), current_user: User = Depends(get_user_or_api_key)):
    """Lists all voice samples accessible to the user (their own + public ones). Optionally filter by tag."""
    query = db.query(VoiceSample).filter(
        (VoiceSample.user_id == current_user.id) | (VoiceSample.is_public == True)
    )
    if tag:
        query = query.filter(VoiceSample.tags.like(f'%"{tag}"%'))
    samples = query.order_by(VoiceSample.created_at.desc()).all()
    return samples

@router.post("/save-favorite", response_model=VoiceSampleUploadResponse)
def save_favorite_voice(
    payload: SaveFavoriteVoiceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_user_or_api_key)
):
    """
    Saves a completed TTS Job or Voice Design Preview output audio as a reusable favorite VoiceSample.
    Trims the audio to a maximum of 8 seconds.
    """
    # 1. Resolve source audio path
    source_audio_path = None
    if payload.job_id:
        from app.models import TTSJob
        job = db.query(TTSJob).filter(TTSJob.id == payload.job_id, TTSJob.user_id == current_user.id).first()
        if not job:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy TTS Job.")
        if job.status != "completed" or not job.output_audio_path:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="TTS Job chưa hoàn thành hoặc không có tệp kết xuất.")
        source_audio_path = job.output_audio_path
    elif payload.preview_id:
        from app.models import VoiceDesignPreview
        preview = db.query(VoiceDesignPreview).filter(VoiceDesignPreview.id == payload.preview_id, VoiceDesignPreview.user_id == current_user.id).first()
        if not preview:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy bản nghe thử thiết kế.")
        if preview.status != "completed" or not preview.preview_audio_path:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bản nghe thử chưa hoàn thành hoặc không có tệp kết xuất.")
        source_audio_path = preview.preview_audio_path
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Yêu cầu phải cung cấp job_id hoặc preview_id.")

    if not source_audio_path or not os.path.exists(source_audio_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tệp âm thanh nguồn không tồn tại trên hệ thống.")

    # 2. Resolve ID
    resolved_id = None
    if payload.custom_id and payload.custom_id.strip():
        norm_id = slugify(payload.custom_id)
        if not norm_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mã ID giọng nói không hợp lệ (không chứa ký tự hợp lệ)."
            )
        existing = db.query(VoiceSample).filter(VoiceSample.id == norm_id).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Mã ID giọng nói '{norm_id}' đã được sử dụng. Vui lòng chọn mã khác."
            )
        resolved_id = norm_id
    else:
        # Auto-slugify from name
        norm_id = slugify(payload.name)
        if not norm_id:
            norm_id = "saved_favorite"
            
        resolved_id = norm_id
        suffix_counter = 1
        while db.query(VoiceSample).filter(VoiceSample.id == resolved_id).first():
            resolved_id = f"{norm_id}_{suffix_counter}"
            suffix_counter += 1

    # 3. Trim audio using soundfile to max 8 seconds
    import soundfile as sf
    target_filename = f"{resolved_id}.wav"
    AudioService.ensure_directories()
    saved_path = os.path.join(settings.voice_samples_dir, target_filename)

    try:
        data, sr = sf.read(source_audio_path)
        max_samples = int(8 * sr)
        trimmed_data = data[:max_samples]
        sf.write(saved_path, trimmed_data, sr, format='WAV', subtype='PCM_16')
        duration = float(len(trimmed_data)) / float(sr)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Lỗi khi xử lý cắt âm thanh: {e}")

    # 4. Build source_job_data from the original TTS Job
    import json as json_mod
    source_job_data_str = None
    source_job = None
    if payload.job_id:
        source_job = db.query(TTSJob).filter(TTSJob.id == payload.job_id).first()
    if source_job:
        source_job_data_str = json_mod.dumps({
            "mode": source_job.job_type,
            "text": source_job.text,
            "voice_sample_id": source_job.voice_sample_id,
            "ref_text": source_job.ref_text,
            "instruct": source_job.instruct,
            "speed": source_job.speed,
            "num_step": source_job.num_step,
            "denoise": source_job.denoise,
            "guidance_scale": source_job.guidance_scale,
            "t_shift": source_job.t_shift,
            "position_temperature": source_job.position_temperature,
            "class_temperature": source_job.class_temperature,
            "layer_penalty_factor": source_job.layer_penalty_factor,
            "duration": source_job.duration,
            "preprocess_prompt": source_job.preprocess_prompt,
            "postprocess_output": source_job.postprocess_output,
        }, ensure_ascii=False)

    tags_str = json_mod.dumps(payload.tags, ensure_ascii=False) if payload.tags else None

    # 5. Create VoiceSample record
    db_sample = VoiceSample(
        id=resolved_id,
        user_id=current_user.id,
        name=payload.name,
        is_public=payload.is_public,
        source_type="saved_favorite",
        source_job_id=payload.job_id or payload.preview_id,
        file_path=saved_path,
        ref_text=payload.ref_text,
        duration=duration,
        sample_rate=sr,
        status="ready",
        tags=tags_str,
        source_job_data=source_job_data_str
    )
    db.add(db_sample)
    db.commit()
    db.refresh(db_sample)

    return VoiceSampleUploadResponse(
        voice_sample_id=resolved_id,
        status="ready",
        message=f"Đã lưu giọng đọc '{payload.name}' thành công."
    )

@router.get("/{voice_sample_id}", response_model=VoiceSampleResponse)
def get_voice_sample(voice_sample_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_user_or_api_key)):
    """Retrieves full details of an uploaded or generated voice sample."""
    sample = db.query(VoiceSample).filter(
        VoiceSample.id == voice_sample_id,
        (VoiceSample.user_id == current_user.id) | (VoiceSample.is_public == True)
    ).first()
    if not sample:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy Voice Sample với ID: {voice_sample_id}"
        )
    return sample

@router.put("/{voice_sample_id}", response_model=VoiceSampleResponse)
def update_voice_sample(
    voice_sample_id: str,
    payload: VoiceSampleUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_user_or_api_key)
):
    """Updates name, tags, ref_text, or is_public of a user's own voice sample."""
    sample = db.query(VoiceSample).filter(
        VoiceSample.id == voice_sample_id,
        VoiceSample.user_id == current_user.id
    ).first()
    if not sample:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy hoặc không có quyền chỉnh sửa Voice Sample: {voice_sample_id}"
        )
    
    if payload.name is not None:
        sample.name = payload.name
    if payload.ref_text is not None:
        sample.ref_text = payload.ref_text
    if payload.is_public is not None:
        sample.is_public = payload.is_public
    if payload.tags is not None:
        import json
        sample.tags = json.dumps(payload.tags, ensure_ascii=False)
    
    db.commit()
    db.refresh(sample)
    return sample

@router.get("/{voice_sample_id}/audio")
def get_voice_sample_audio(voice_sample_id: str, db: Session = Depends(get_db)):
    """Serves the WAV audio file of the voice sample. Public voices don't require auth."""
    sample = db.query(VoiceSample).filter(VoiceSample.id == voice_sample_id).first()
    if not sample:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy Voice Sample với ID: {voice_sample_id}"
        )
    # For non-public samples, we still allow access (auth is handled at the router level for other endpoints)
    if not sample.file_path or not os.path.exists(sample.file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tệp âm thanh của Voice Sample không tồn tại trên máy chủ."
        )
    return FileResponse(
        sample.file_path,
        media_type="audio/wav",
        filename=f"{voice_sample_id}.wav",
        content_disposition_type="inline",
        headers={
            "Cache-Control": "public, max-age=86400",
            "Accept-Ranges": "bytes"
        }
    )

@router.delete("/{voice_sample_id}")
def delete_voice_sample(voice_sample_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_user_or_api_key)):
    """Deletes a user's own voice sample from database and disk storage."""
    sample = db.query(VoiceSample).filter(
        VoiceSample.id == voice_sample_id,
        VoiceSample.user_id == current_user.id
    ).first()
    if not sample:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy hoặc không có quyền xóa Voice Sample với ID: {voice_sample_id}"
        )
    
    # Delete physical audio file if it exists
    if sample.file_path and os.path.exists(sample.file_path):
        try:
            os.remove(sample.file_path)
        except Exception as e:
            print(f"Lỗi khi xóa file vật lý: {e}")
            
    db.delete(sample)
    db.commit()
    return {"status": "success", "message": "Đã xóa giọng mẫu thành công."}


# Public Voice Library — No auth required
from fastapi import Query

public_library_router = APIRouter(prefix="/v1/voice-library", tags=["Voice Library (Public)"])

@public_library_router.get("", response_model=List[VoiceLibraryItemResponse])
def list_public_voice_library(
    tag: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """Lists all public voice samples for browsing. No authentication required."""
    query = db.query(VoiceSample).filter(VoiceSample.is_public == True)
    if tag:
        query = query.filter(VoiceSample.tags.like(f'%"{tag}"%'))
    if search:
        query = query.filter(VoiceSample.name.ilike(f"%{search}%"))
    
    total = query.count()
    samples = query.order_by(VoiceSample.created_at.desc()).offset(offset).limit(limit).all()
    
    import json as json_mod
    results = []
    for s in samples:
        tags_parsed = None
        if s.tags:
            try:
                tags_parsed = json_mod.loads(s.tags)
            except Exception:
                pass
        source_data_parsed = None
        if s.source_job_data:
            try:
                source_data_parsed = json_mod.loads(s.source_job_data)
            except Exception:
                pass
        results.append(VoiceLibraryItemResponse(
            id=s.id,
            name=s.name,
            tags=tags_parsed,
            ref_text=s.ref_text,
            duration=s.duration,
            is_public=True,
            preview_url=f"/v1/voice-samples/{s.id}/audio",
            source_job_data=source_data_parsed,
            created_at=s.created_at
        ))
    return results

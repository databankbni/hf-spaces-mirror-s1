import os
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import TTSJob, User
from app.schemas import TTSJobCreate, TTSJobResponse
from app.services.job_service import JobService
from app.utils.auth import get_user_or_api_key

router = APIRouter(prefix="/v1/tts/jobs", tags=["TTS"])

@router.post("", response_model=TTSJobResponse)
def create_tts_job(payload: TTSJobCreate, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_user_or_api_key)):
    """
    Creates a TTS job based on:
    - clone_voice: Requires voice_sample_id.
    - auto_voice: Automatically generated voice.
    - voice_design: Generates speech using an instruct prompt.
    """
    try:
        job = JobService.create_tts_job(
            db=db,
            mode=payload.mode,
            text=payload.text,
            voice_sample_id=payload.voice_sample_id,
            ref_text=payload.ref_text,
            instruct=payload.instruct,
            public_api_url=str(request.base_url).rstrip("/"),
            speed=payload.speed,
            num_step=payload.num_step,
            user_id=current_user.id,
            denoise=payload.denoise,
            guidance_scale=payload.guidance_scale,
            t_shift=payload.t_shift,
            position_temperature=payload.position_temperature,
            class_temperature=payload.class_temperature,
            layer_penalty_factor=payload.layer_penalty_factor,
            duration=payload.duration,
            preprocess_prompt=payload.preprocess_prompt,
            postprocess_output=payload.postprocess_output,
            audio_chunk_duration=payload.audio_chunk_duration,
            audio_chunk_threshold=payload.audio_chunk_threshold,
            with_alignment=payload.with_alignment,
            language=payload.language,
            pad_duration=payload.pad_duration,
            fade_duration=payload.fade_duration
        )
        return TTSJobResponse(
            job_id=job.id,
            status=job.status,
            message=job.message
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Lỗi tạo TTS Job: {e}"
        )

@router.get("/{job_id}")
def get_tts_job(job_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_user_or_api_key)):
    """Retrieves status and details of a specific TTS job."""
    job = db.query(TTSJob).filter(TTSJob.id == job_id, TTSJob.user_id == current_user.id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy TTS Job {job_id}"
        )
    audio_url = f"{settings.API_BASE_URL}/v1/tts/jobs/{job.id}/audio" if job.status == "completed" else None
    return {
        "job_id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "message": job.message,
        "progress": job.progress,
        "audio_url": audio_url,
        "cdn_audio_url": getattr(job, "cdn_audio_url", None) if job.status == "completed" else None,
        "error_message": job.error_message,
        "created_at": job.created_at,
        "updated_at": job.updated_at
    }

@router.get("/{job_id}/audio")
def get_tts_audio(job_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_user_or_api_key)):
    """Serves the completed TTS generated WAV file using FileResponse."""
    job = db.query(TTSJob).filter(TTSJob.id == job_id, TTSJob.user_id == current_user.id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy TTS Job {job_id}"
        )
        
    if job.status != "completed" or not job.output_audio_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tệp âm thanh TTS chưa hoàn tất hoặc không tồn tại."
        )
        
    if not os.path.exists(job.output_audio_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tệp âm thanh không tồn tại trên máy chủ."
        )
        
    return FileResponse(
        job.output_audio_path,
        media_type="audio/wav",
        filename=f"tts_{job_id}.wav",
        content_disposition_type="inline",
        headers={
            "Cache-Control": "public, max-age=86400",
            "Accept-Ranges": "bytes"
        }
    )

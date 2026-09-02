import os
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import VoiceDesignPreview, User
from app.schemas import (
    VoiceDesignPreviewCreate,
    VoiceDesignPreviewResponse,
    VoiceDesignPreviewDetail,
    AcceptPreviewResponse
)
from app.services.job_service import JobService
from app.utils.auth import get_user_or_api_key

router = APIRouter(prefix="/v1/voice-design/previews", tags=["Voice Design Previews"])

@router.post("", response_model=VoiceDesignPreviewResponse)
def create_voice_design_preview(
    payload: VoiceDesignPreviewCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_user_or_api_key)
):
    """
    Creates a voice design request, maps Vietnamese terms to instruct tags,
    sets up a preview profile, and queues a preview job.
    """
    try:
        preview, job = JobService.create_voice_design_preview(
            db, payload.voice_request, payload.preview_text, str(request.base_url).rstrip("/"),
            speed=payload.speed, num_step=payload.num_step,
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
            audio_chunk_threshold=payload.audio_chunk_threshold
        )
        return VoiceDesignPreviewResponse(
            preview_id=preview.id,
            job_id=job.id,
            status=job.status,
            message=job.message
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Lỗi tạo voice design preview: {e}"
        )

@router.get("/{preview_id}", response_model=VoiceDesignPreviewDetail)
def get_preview_info(preview_id: str, response: Response, db: Session = Depends(get_db), current_user: User = Depends(get_user_or_api_key)):
    """Fetches details and current processing state of a voice design preview."""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    preview = db.query(VoiceDesignPreview).filter(VoiceDesignPreview.id == preview_id, VoiceDesignPreview.user_id == current_user.id).first()
    if not preview:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy Voice Design Preview với ID: {preview_id}"
        )
    return preview

@router.get("/{preview_id}/audio")
def get_preview_audio(preview_id: str, response: Response, db: Session = Depends(get_db), current_user: User = Depends(get_user_or_api_key)):
    """Serves the generated WAV preview audio file using FileResponse."""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    preview = db.query(VoiceDesignPreview).filter(VoiceDesignPreview.id == preview_id, VoiceDesignPreview.user_id == current_user.id).first()
    if not preview:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy Voice Design Preview với ID: {preview_id}"
        )
    
    if preview.status != "completed" or not preview.preview_audio_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tệp âm thanh nghe thử chưa hoàn thành hoặc không có."
        )
        
    if not os.path.exists(preview.preview_audio_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tệp âm thanh không tồn tại trên bộ lưu trữ của máy chủ."
        )
        
    return FileResponse(
        preview.preview_audio_path,
        media_type="audio/wav",
        filename=f"preview_{preview_id}.wav",
        content_disposition_type="inline"
    )

@router.post("/{preview_id}/accept", response_model=AcceptPreviewResponse)
def accept_voice_preview(preview_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_user_or_api_key)):
    """
    Accepts the generated preview voice, clones/copies its audio file to voice_samples,
    and returns a ready-to-use voice_sample_id.
    """
    try:
        # Check ownership of preview
        preview = db.query(VoiceDesignPreview).filter(VoiceDesignPreview.id == preview_id, VoiceDesignPreview.user_id == current_user.id).first()
        if not preview:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy Voice Design Preview với ID: {preview_id}"
            )
            
        sample = JobService.accept_preview(db, preview_id, user_id=current_user.id)
        return AcceptPreviewResponse(
            voice_sample_id=sample.id,
            status="ready",
            message="Đã tạo voice sample từ preview."
        )
    except HTTPException as e:
        raise e
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Lỗi hệ thống khi chấp nhận bản nghe thử: {e}"
        )

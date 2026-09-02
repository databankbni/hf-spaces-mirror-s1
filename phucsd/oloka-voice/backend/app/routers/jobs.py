from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import TTSJob, User
from app.schemas import JobStatusResponse
from app.utils.auth import get_user_or_api_key

router = APIRouter(prefix="/v1/jobs", tags=["Generic Jobs"])

def _build_job_response(job: TTSJob) -> JobStatusResponse:
    audio_url = None
    if job.status == "completed":
        if job.job_type == "voice_design_preview" and job.preview_id:
            audio_url = f"/v1/voice-design/previews/{job.preview_id}/audio"
        else:
            audio_url = f"/v1/tts/jobs/{job.id}/audio"
            
    import json
    alignment_data = None
    if job.alignment:
        try:
            alignment_data = json.loads(job.alignment)
        except Exception:
            pass

    processing_time = None
    if job.completed_at and job.started_at:
        processing_time = (job.completed_at - job.started_at).total_seconds()
        
    queue_time = None
    if job.started_at:
        queue_time = (job.started_at - job.created_at).total_seconds()
        
    total_time = None
    if job.completed_at:
        total_time = (job.completed_at - job.created_at).total_seconds()

    mode_val = "clone_voice"
    if job.job_type == "auto_voice":
        mode_val = "auto_voice"
    elif job.job_type in ["voice_design_tts", "voice_design_preview"]:
        mode_val = "voice_design"

    params_data = {
        "mode": mode_val,
        "text": job.text,
        "voice_sample_id": job.voice_sample_id,
        "ref_text": job.ref_text,
        "instruct": job.instruct,
        "speed": job.speed,
        "num_step": job.num_step,
        "denoise": job.denoise,
        "guidance_scale": job.guidance_scale,
        "t_shift": job.t_shift,
        "position_temperature": job.position_temperature,
        "class_temperature": job.class_temperature,
        "layer_penalty_factor": job.layer_penalty_factor,
        "duration": job.duration,
        "preprocess_prompt": job.preprocess_prompt,
        "postprocess_output": job.postprocess_output,
        "audio_chunk_duration": job.audio_chunk_duration,
        "audio_chunk_threshold": job.audio_chunk_threshold,
        "with_alignment": job.with_alignment,
        "language": job.language,
        "pad_duration": job.pad_duration,
        "fade_duration": job.fade_duration
    }
    params_data = {k: v for k, v in params_data.items() if v is not None}

    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        message=job.message,
        progress=job.progress,
        audio_url=audio_url,
        error_message=job.error_message,
        worker_id=job.worker_id,
        job_type=job.job_type,
        text=job.text,
        created_at=job.created_at,
        alignment=alignment_data,
        started_at=job.started_at,
        completed_at=job.completed_at,
        processing_time=processing_time,
        queue_time=queue_time,
        total_time=total_time,
        params=params_data
    )

from typing import Optional, Union, List, Any
from app.schemas import JobStatusResponse, PaginatedJobsResponse, BatchJobStatusRequest

@router.get("", response_model=Any)
def list_jobs(
    response: Response,
    page: Optional[int] = None,
    page_size: Optional[int] = 15,
    job_type: Optional[str] = None,
    status_filter: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_user_or_api_key)
):
    """
    Returns list of jobs belonging to the current user with optional pagination, category filtering, and search.
    """
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    
    query = db.query(TTSJob).filter(TTSJob.user_id == current_user.id)

    # Filtering by job_type (category)
    if job_type and job_type != "all":
        if job_type == "clone_voice":
            query = query.filter(TTSJob.job_type == "clone_voice")
        elif job_type == "auto_voice":
            query = query.filter(TTSJob.job_type == "auto_voice")
        elif job_type == "voice_design":
            query = query.filter(TTSJob.job_type.in_(["voice_design_preview", "voice_design_tts"]))
        elif job_type == "video_dubbing":
            query = query.filter(TTSJob.job_type.in_(["separate_audio", "dub_segments"]))
            
    # Filtering by status
    if status_filter and status_filter != "all":
        if status_filter == "failed":
            query = query.filter(TTSJob.status == "failed")
        elif status_filter == "completed":
            query = query.filter(TTSJob.status == "completed")
        elif status_filter == "running":
            query = query.filter(TTSJob.status.notin_(["completed", "failed"]))

    # Search by job_id or text content
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(
            (TTSJob.id.ilike(term)) | (TTSJob.text.ilike(term)) | (TTSJob.instruct.ilike(term))
        )

    query = query.order_by(TTSJob.created_at.desc())

    if page is not None:
        p = max(1, page)
        ps = max(1, min(100, page_size or 15))
        total = query.count()
        total_pages = (total + ps - 1) // ps if total > 0 else 1
        jobs = query.offset((p - 1) * ps).limit(ps).all()
        
        return PaginatedJobsResponse(
            items=[_build_job_response(job) for job in jobs],
            total=total,
            page=p,
            page_size=ps,
            total_pages=total_pages
        )

    # Legacy unpaginated fallback
    jobs = query.all()
    return [_build_job_response(job) for job in jobs]

@router.post("/batch", response_model=dict[str, JobStatusResponse])
def get_batch_jobs_status(
    payload: BatchJobStatusRequest,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_user_or_api_key)
):
    """
    Query the status of multiple jobs in a single request.
    Returns a dictionary mapping job_id to its detailed status.
    """
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    if not payload.job_ids:
        return {}
    
    jobs = db.query(TTSJob).filter(
        TTSJob.id.in_(payload.job_ids),
        TTSJob.user_id == current_user.id
    ).all()
    
    return {job.id: _build_job_response(job) for job in jobs}

@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str, response: Response, db: Session = Depends(get_db), current_user: User = Depends(get_user_or_api_key)):
    """
    Polled generic job status endpoint returning current state, progress rate,
    any error messages, and the resolved audio download URL upon completion for the user's job.
    """
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    job = db.query(TTSJob).filter(TTSJob.id == job_id, TTSJob.user_id == current_user.id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy Job với ID: {job_id}"
        )
    return _build_job_response(job)

@router.delete("/{job_id}")
def delete_job(job_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_user_or_api_key)):
    """
    Xóa/Hủy một tác vụ khỏi hàng chờ hoặc lịch sử. Nếu tác vụ có file âm thanh kết quả,
    file đó cũng sẽ được dọn dẹp khỏi disk.
    """
    import os
    job = db.query(TTSJob).filter(TTSJob.id == job_id, TTSJob.user_id == current_user.id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy Job với ID: {job_id}"
        )
    
    # Dọn dẹp file âm thanh đầu ra nếu có
    if job.output_audio_path and os.path.exists(job.output_audio_path):
        try:
            os.remove(job.output_audio_path)
        except Exception as e:
            print(f"Lỗi xóa file âm thanh đầu ra: {e}")
            
    # Dọn dẹp file preview thiết kế giọng nếu có
    if job.job_type == "voice_design_preview" and job.preview_id:
        from app.models import VoiceDesignPreview
        preview = db.query(VoiceDesignPreview).filter(VoiceDesignPreview.id == job.preview_id).first()
        if preview:
            if preview.preview_audio_path and os.path.exists(preview.preview_audio_path):
                try:
                    os.remove(preview.preview_audio_path)
                except Exception as e:
                    print(f"Lỗi xóa file preview: {e}")
            db.delete(preview)

    db.delete(job)
    db.commit()
    return {"status": "success", "message": f"Đã xóa tác vụ {job_id} thành công."}

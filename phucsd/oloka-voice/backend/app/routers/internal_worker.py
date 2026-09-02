import os
import shutil
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import TTSJob, VoiceSample
from app.schemas import (
    WorkerRegisterRequest,
    WorkerHeartbeatRequest,
    WorkerShutdownRequest,
    WorkerJobStatusUpdateRequest,
    WorkerNextJobResponse,
    WorkerJobPayload,
    WorkerASRResultRequest
)
from app.security import verify_worker_token
from app.services.worker_session_service import WorkerSessionService
from app.services.job_service import JobService
from app.config import settings

# Apply verify_worker_token to all endpoints in this router
router = APIRouter(
    prefix="/v1/internal",
    tags=["Worker Internal"],
    dependencies=[Depends(verify_worker_token)]
)

@router.post("/workers/register")
def register_worker(payload: WorkerRegisterRequest, db: Session = Depends(get_db)):
    """Registers a worker's session or updates its ready state."""
    WorkerSessionService.register_worker(
        db=db,
        worker_id=payload.worker_id,
        status=payload.status,
        message=payload.message
    )
    return {"message": "Worker registered successfully"}

@router.post("/workers/heartbeat")
def worker_heartbeat(payload: WorkerHeartbeatRequest, db: Session = Depends(get_db)):
    """Logs a heartbeat update from an active worker, maintaining its live status."""
    WorkerSessionService.heartbeat(
        db=db,
        worker_id=payload.worker_id,
        status=payload.status,
        current_job_id=payload.current_job_id,
        message=payload.message
    )
    return {"status": "ok"}

@router.get("/jobs/next", response_model=WorkerNextJobResponse)
def get_next_job(worker_id: str, request: Request, db: Session = Depends(get_db), token: str = Depends(verify_worker_token)):
    """
    Called by workers to pull the oldest pending job.
    Locks the job, updates its state, and compiles parameters (including ref audio downloads).
    """
    # Resolve user from token
    from app.models import User
    user = db.query(User).filter(User.api_key == token).first()
    user_id = user.id if user else None

    job = JobService.get_next_job(db, worker_id, user_id=user_id)
    if not job:
        return WorkerNextJobResponse(job=None, message="No pending job")

    # Construct public ref audio URL if there is a sample ID or path associated
    ref_audio_url = None
    base_url = settings.PUBLIC_API_BASE_URL
    if not base_url:
        proto = request.headers.get("x-forwarded-proto", str(request.base_url).split("://")[0])
        host = request.headers.get("x-forwarded-host", str(request.base_url).split("://")[-1].rstrip("/"))
        base_url = f"{proto}://{host}"

    if job.voice_sample_id:
        ref_audio_url = f"{base_url}/v1/internal/files/voice-samples/{job.voice_sample_id}"
    elif job.ref_audio_path:
        ref_audio_url = f"{base_url}/v1/internal/jobs/{job.id}/ref-audio"

    output_kind = "preview" if job.job_type == "voice_design_preview" else "tts"

    payload = WorkerJobPayload(
        job_id=job.id,
        job_type=job.job_type,
        text=job.text,
        instruct=job.instruct,
        ref_audio_url=ref_audio_url,
        ref_text=job.ref_text,
        output_kind=output_kind,
        speed=job.speed,
        num_step=job.num_step,
        denoise=job.denoise,
        guidance_scale=job.guidance_scale,
        t_shift=job.t_shift,
        position_temperature=job.position_temperature,
        class_temperature=job.class_temperature,
        layer_penalty_factor=job.layer_penalty_factor,
        duration=job.duration,
        preprocess_prompt=job.preprocess_prompt,
        postprocess_output=job.postprocess_output,
        audio_chunk_duration=job.audio_chunk_duration,
        audio_chunk_threshold=job.audio_chunk_threshold,
        with_alignment=job.with_alignment
    )

    return WorkerNextJobResponse(job=payload, message="Job assigned")

@router.post("/jobs/{job_id}/status")
def update_job_status(
    job_id: str,
    payload: WorkerJobStatusUpdateRequest,
    db: Session = Depends(get_db)
):
    """Updates a job's progress parameters or reports an execution error from a worker."""
    try:
        JobService.update_job_status(
            db=db,
            job_id=job_id,
            status=payload.status,
            message=payload.message,
            progress=payload.progress,
            error_message=payload.error_message
        )
        return {"status": "success"}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )

@router.post("/jobs/{job_id}/output")
async def upload_job_output(
    job_id: str,
    file: UploadFile = File(...),
    alignment: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """
    Receives generated audio file from the worker, copies it to the designated storage path,
    marks the job as completed, and returns the media download URL.
    """
    job = db.query(TTSJob).filter(TTSJob.id == job_id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy Job {job_id}"
        )

    # Special handling for Video Dubbing sub-tasks
    if job.job_type in ["separate_audio", "dub_segments"]:
        from app.models import VideoDubbingJob, SystemSetting
        from app.services.video_dubbing_service import VideoDubbingService
        import zipfile
        import soundfile as sf
        import json

        is_sep = job.job_type == "separate_audio"
        prefix = "sep_" if is_sep else "dub_"
        dub_job_id = job_id.replace(prefix, "")
        
        dub_job = db.query(VideoDubbingJob).filter(VideoDubbingJob.id == dub_job_id).first()
        if not dub_job:
            raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ lồng tiếng video tương ứng.")

        job_dir = os.path.join(settings.dubbing_dir, dub_job_id)
        os.makedirs(job_dir, exist_ok=True)
        zip_path = os.path.join(job_dir, f"{job_id}.zip")

        try:
            with open(zip_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            
            # Unzip contents
            if is_sep:
                VideoDubbingService.log_to_job(dub_job_id, "[KAGGLE] Nhận tệp ZIP kết quả tách âm thanh từ Kaggle Worker. Tiến hành giải nén...")
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(job_dir)
                
                # Check files exist
                vocals_path = os.path.join(job_dir, "vocals.wav")
                bgm_path = os.path.join(job_dir, "bgm.wav")
                if not os.path.exists(vocals_path) or not os.path.exists(bgm_path):
                    # Fallback if names differ or not separated
                    for f_name in os.listdir(job_dir):
                        if "vocal" in f_name.lower() and f_name.endswith(".wav"):
                            shutil.move(os.path.join(job_dir, f_name), vocals_path)
                        elif any(k in f_name.lower() for k in ["bgm", "music", "no_vocal"]) and f_name.endswith(".wav"):
                            shutil.move(os.path.join(job_dir, f_name), bgm_path)
                    
                    if not os.path.exists(vocals_path):
                        shutil.copy2(dub_job.original_audio_path, vocals_path)
                    if not os.path.exists(bgm_path):
                        bgm_path = None

                VideoDubbingService.log_to_job(dub_job_id, f"[KAGGLE] Giải nén thành công. Vocals: {vocals_path}, BGM: {bgm_path}")
                dub_job.vocals_audio_path = vocals_path
                dub_job.bgm_audio_path = bgm_path
                db.commit()

                # Set job as complete
                JobService.complete_job_output(db, job_id, zip_path)
                
                # Trigger next stage (ASR/Transcription)
                from app.routers.video_dubbing import trigger_transcription_stage
                trigger_transcription_stage(dub_job_id, db)
                
            else:
                VideoDubbingService.log_to_job(dub_job_id, "[KAGGLE] Nhận tệp ZIP chứa các segment audio lồng tiếng từ Kaggle. Tiến hành giải nén...")
                # final dubbing segments ZIP
                segments_dir = os.path.join(job_dir, "segments")
                os.makedirs(segments_dir, exist_ok=True)
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(segments_dir)

                dub_job.status = "mixing_audio"
                dub_job.progress = 70
                dub_job.message = "Đang lồng ghép các đoạn dịch và nhạc nền..."
                db.commit()

                # Load duration
                orig_info = sf.info(dub_job.original_audio_path)
                duration = orig_info.duration

                all_extracted_files = []
                for root, _, files in os.walk(segments_dir):
                    for f in files:
                        all_extracted_files.append(os.path.join(root, f))
                VideoDubbingService.log_to_job(dub_job_id, f"[KAGGLE] Đã giải nén {len(all_extracted_files)} tệp trong segments_dir: {[os.path.basename(f) for f in all_extracted_files[:15]]}")

                # Compile vocal track
                translated_list = json.loads(dub_job.translated_subtitles or "[]")
                segments_payload = []
                for idx, seg in enumerate(translated_list):
                    seg_id = seg.get("id", idx + 1)
                    possible_names = [
                        f"segment_{seg_id}.wav", f"seg_{seg_id}.wav", f"{seg_id}.wav",
                        f"segment_{idx+1}.wav", f"seg_{idx+1}.wav", f"{idx+1}.wav"
                    ]
                    found_wav = None
                    for p_name in possible_names:
                        for f_path in all_extracted_files:
                            if os.path.basename(f_path).lower() == p_name.lower():
                                found_wav = f_path
                                break
                        if found_wav:
                            break

                    if found_wav and os.path.exists(found_wav):
                        segments_payload.append({
                            "start": seg["start"],
                            "end": seg.get("end"),
                            "file_path": found_wav
                        })
                    else:
                        VideoDubbingService.log_to_job(dub_job_id, f"[WARNING] Không tìm thấy tệp WAV lồng tiếng cho phân đoạn #{seg_id} (ID: {seg_id})")

                dubbed_vocals_path = os.path.join(job_dir, "dubbed_vocals.wav")
                VideoDubbingService.log_to_job(dub_job_id, f"[KAGGLE] Đang ghép {len(segments_payload)}/{len(translated_list)} tệp audio lồng tiếng thành một track chính...")
                VideoDubbingService.assemble_dubbed_vocal(segments_payload, dubbed_vocals_path, duration)
                VideoDubbingService.log_to_job(dub_job_id, f"[KAGGLE] Ghép track vocals lồng tiếng thành công: {dubbed_vocals_path}")

                # Mux with video
                output_video_path = os.path.join(job_dir, "output_dubbed.mp4")
                dub_job.status = "muxing_video"
                dub_job.progress = 85
                db.commit()

                vocal_v = getattr(dub_job, "vocals_volume", None) if getattr(dub_job, "vocals_volume", None) is not None else 1.0
                bgm_v = getattr(dub_job, "bgm_volume", None) if getattr(dub_job, "bgm_volume", None) is not None else 0.4
                VideoDubbingService.log_to_job(dub_job_id, f"[KAGGLE] Đang trộn nhạc nền BGM (vol={bgm_v}) & vocals lồng tiếng mới (vol={vocal_v}), đóng gói video thành phẩm bằng FFmpeg...")
                VideoDubbingService.mix_and_mux_video(
                    video_path=dub_job.input_file_path,
                    bgm_path=dub_job.bgm_audio_path,
                    vocal_path=dubbed_vocals_path,
                    output_path=output_video_path,
                    vocal_vol=vocal_v,
                    bgm_vol=bgm_v
                )

                dub_job.output_video_path = output_video_path
                dub_job.status = "completed"
                dub_job.progress = 100
                dub_job.message = "Lồng tiếng video thành công!"
                db.commit()
                VideoDubbingService.log_to_job(dub_job_id, f"[KAGGLE] Đóng gói video thành công. File: {output_video_path}. Quy trình hoàn tất!")

                # Set job as complete
                JobService.complete_job_output(db, job_id, zip_path)

            if os.path.exists(zip_path):
                os.remove(zip_path)

            return {"status": "completed"}
            
        except Exception as e:
            VideoDubbingService.log_to_job(dub_job_id, f"LỖI KHI XỬ LÝ KẾT QUẢ KAGGLE: {e}")
            dub_job.status = "failed"
            dub_job.progress = 100
            dub_job.error_message = str(e)
            dub_job.message = "Có lỗi xảy ra khi xử lý kết quả từ Kaggle."
            db.commit()
            if os.path.exists(zip_path):
                os.remove(zip_path)
            raise HTTPException(status_code=500, detail=str(e))

    # Determine destination folder and path
    if job.job_type == "voice_design_preview" and job.preview_id:
        os.makedirs(settings.previews_dir, exist_ok=True)
        dest_path = os.path.join(settings.previews_dir, f"{job.preview_id}.wav")
        audio_url = f"/v1/voice-design/previews/{job.preview_id}/audio"
    else:
        os.makedirs(settings.outputs_dir, exist_ok=True)
        dest_path = os.path.join(settings.outputs_dir, f"{job_id}.wav")
        audio_url = f"/v1/tts/jobs/{job_id}/audio"

    try:
        with open(dest_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Lỗi ghi tệp đầu ra: {e}"
        )

    # Finalize job in db
    JobService.complete_job_output(db, job_id, dest_path, alignment=alignment)

    return {
        "status": "completed",
        "audio_url": audio_url
    }

@router.post("/jobs/{job_id}/asr")
def upload_asr_result(
    job_id: str,
    payload: WorkerASRResultRequest,
    db: Session = Depends(get_db)
):
    """Receives transcribed text and timestamps from the worker and completes the ASR job."""
    try:
        alignment_str = None
        if payload.alignment is not None:
            if isinstance(payload.alignment, str):
                alignment_str = payload.alignment
            else:
                import json
                alignment_str = json.dumps(payload.alignment)

        JobService.complete_asr_job(
            db=db,
            job_id=job_id,
            text=payload.text,
            alignment=alignment_str,
            duration=payload.duration
        )

        # Video Dubbing ASR callback integration
        if job_id.startswith("asr_"):
            dub_job_id = job_id.replace("asr_", "")
            from app.routers.video_dubbing import trigger_translation_stage
            trigger_translation_stage(dub_job_id, payload.text, alignment_str, db)

        return {"status": "success"}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )

@router.post("/workers/shutdown")
def worker_shutdown(payload: WorkerShutdownRequest, db: Session = Depends(get_db)):
    """Logs the worker shutdown event, setting its status to stopped."""
    WorkerSessionService.shutdown_worker(
        db=db,
        worker_id=payload.worker_id,
        reason=payload.reason
    )
    return {"message": "Worker shutdown logged successfully"}

@router.get("/files/voice-samples/{voice_sample_id}")
def download_voice_sample_file(voice_sample_id: str, db: Session = Depends(get_db)):
    """Serves the voice sample WAV file to the worker for voice cloning reference."""
    sample = db.query(VoiceSample).filter(VoiceSample.id == voice_sample_id).first()
    if not sample:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy Voice Sample với ID: {voice_sample_id}"
        )
        
    if not os.path.exists(sample.file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tệp âm thanh tham chiếu không tồn tại trên máy chủ."
        )
        
    return FileResponse(
        sample.file_path,
        media_type="audio/wav",
        filename=f"ref_{voice_sample_id}.wav"
    )

@router.get("/jobs/{job_id}/ref-audio")
def download_job_ref_audio(job_id: str, db: Session = Depends(get_db)):
    """Serves the temporary reference WAV file to the worker for voice cloning reference."""
    job = db.query(TTSJob).filter(TTSJob.id == job_id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy Job với ID: {job_id}"
        )
        
    if not job.ref_audio_path or not os.path.exists(job.ref_audio_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tệp âm thanh tham chiếu không tồn tại trên máy chủ."
        )
        
    return FileResponse(
        job.ref_audio_path,
        media_type="audio/wav",
        filename=f"ref_{job_id}.wav"
    )



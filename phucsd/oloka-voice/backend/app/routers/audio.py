import os
import time
import asyncio
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User, TTSJob
from app.services.job_service import JobService
from app.utils.auth import get_user_or_api_key

router = APIRouter(prefix="/v1/audio", tags=["Audio (OpenAI Compatible)"])

class SpeechRequest(BaseModel):
    model: str
    input: str
    voice: str
    response_format: Optional[str] = "mp3"
    ref_text: Optional[str] = None
    speed: Optional[float] = 1.0
    num_step: Optional[int] = 32
    denoise: Optional[bool] = True
    guidance_scale: Optional[float] = 2.0
    t_shift: Optional[float] = 0.1
    position_temperature: Optional[float] = 5.0
    class_temperature: Optional[float] = 0.0
    layer_penalty_factor: Optional[float] = 5.0
    duration: Optional[float] = None
    preprocess_prompt: Optional[bool] = True
    postprocess_output: Optional[bool] = True
    audio_chunk_duration: Optional[float] = 15.0
    audio_chunk_threshold: Optional[float] = 30.0
    with_alignment: Optional[bool] = Field(False, description="Nếu true, hệ thống chặn đồng bộ và trả về kết quả JSON chứa thông tin thời gian khớp từng từ (alignment) thay vì file âm thanh thô.")

@router.post("/speech")
async def text_to_speech(
    payload: SpeechRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_user_or_api_key)
):
    """
    OpenAI-compatible speech endpoint. Synthesizes text into speech.
    Resolves `voice` as:
    1. A voice_sample_id (if it starts with 'usr_' or 'vsp_' or matches UUID).
    2. An instruct prompt (if it contains multiple words or description terms).
    3. Auto voice (otherwise).
    """
    # 1. Resolve voice parameters
    mode = "auto_voice"
    voice_sample_id = None
    instruct = None
    
    voice_val = payload.voice.strip()
    
    # Check if voice_val is a voice sample ID
    import re
    is_uuid = bool(re.match(r'^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$', voice_val))
    if voice_val.startswith("usr_") or voice_val.startswith("vsp_") or is_uuid:
        mode = "clone_voice"
        voice_sample_id = voice_val
    elif "," in voice_val or " " in voice_val or any(desc in voice_val.lower() for desc in ["male", "female", "accent", "elderly", "teenager", "whisper", "adult"]):
        mode = "voice_design"
        instruct = voice_val
    else:
        # Check if the user has a voice sample with this exact name or ID in DB
        from app.models import VoiceSample
        db_sample = db.query(VoiceSample).filter(
            (VoiceSample.id == voice_val) | (VoiceSample.name == voice_val),
            VoiceSample.user_id == current_user.id
        ).first()
        if db_sample:
            mode = "clone_voice"
            voice_sample_id = db_sample.id
        else:
            # Fallback to voice design with the voice name as instruct, or auto voice
            mode = "voice_design"
            instruct = voice_val

    # 2. Use user specified values or defaults
    num_step = payload.num_step if payload.num_step is not None else 32
    
    # 3. Create the TTS Job
    try:
        job = JobService.create_tts_job(
            db=db,
            mode=mode,
            text=payload.input,
            voice_sample_id=voice_sample_id,
            ref_text=payload.ref_text,
            instruct=instruct,
            public_api_url=str(request.base_url).rstrip("/"),
            speed=payload.speed,
            num_step=num_step,
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
            with_alignment=payload.with_alignment
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Lỗi khởi tạo TTS Job: {e}"
        )

    # 4. Poll synchronously until completed or failed
    if os.environ.get("APP_ENV") == "testing":
        # Fast-track job for testing to avoid background worker poll block
        from app.services.audio_service import AudioService
        from app.services.mock_worker import MockWorker
        import json
        AudioService.ensure_directories()
        out_path = os.path.abspath(os.path.join(settings.outputs_dir, f"{job.id}.wav"))
        MockWorker._generate_sine_wav(out_path)
        
        alignment_str = None
        if payload.with_alignment:
            words = (payload.input or "").split()
            if words:
                word_dur = 3.0 / len(words)
                alignment_list = []
                curr_time = 0.0
                for w in words:
                    clean_w = w.strip(".,!?\"'")
                    alignment_list.append({
                        "word": clean_w,
                        "start": round(curr_time, 3),
                        "end": round(curr_time + word_dur, 3)
                    })
                    curr_time += word_dur
                alignment_str = json.dumps(alignment_list)

        JobService.complete_job_output(db, job.id, out_path, alignment=alignment_str)
        db.refresh(job)

    max_wait = 180  # 3 minutes maximum timeout
    start_time = time.time()
    while time.time() - start_time < max_wait:
        db.refresh(job)
        if job.status == "completed":
            break
        elif job.status == "failed":
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Xử lý TTS thất bại: {job.error_message}"
            )
        # Sleep for a bit before checking again
        await asyncio.sleep(0.5)
    else:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Quá thời gian chờ xử lý âm thanh từ GPU worker (Timeout 3 phút)."
        )

    # 5. Serve the audio file
    if not job.output_audio_path or not os.path.exists(job.output_audio_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tệp âm thanh kết quả không tồn tại."
        )

    if payload.with_alignment:
        import json
        import soundfile as sf
        
        duration = 0.0
        try:
            info = sf.info(job.output_audio_path)
            duration = info.duration
        except Exception:
            pass
            
        alignment_data = []
        if job.alignment:
            try:
                alignment_data = json.loads(job.alignment)
            except Exception:
                pass
                
        base_url = str(request.base_url).rstrip("/")
        audio_url = f"{base_url}/v1/tts/jobs/{job.id}/audio"
        
        return {
            "status": "completed",
            "audioUrl": audio_url,
            "duration": round(duration, 2),
            "alignment": alignment_data
        }

    media_type = "audio/wav"
    filename = f"speech_{job.id}.wav"
    if payload.response_format == "mp3":
        media_type = "audio/mpeg"
        filename = f"speech_{job.id}.mp3"
    
    return FileResponse(
        job.output_audio_path,
        media_type=media_type,
        filename=filename,
        content_disposition_type="inline"
    )

@router.get("/voices")
def list_voices(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_user_or_api_key)
):
    """Lists available voices (voice samples uploaded by user + pre-defined presets)."""
    from app.models import VoiceSample
    samples = db.query(VoiceSample).filter(VoiceSample.user_id == current_user.id).all()
    
    voices = []
    # Add user voice samples
    for s in samples:
        voices.append({
            "voice_id": s.id,
            "name": s.name,
            "mode": "clone_voice",
            "description": f"Giọng nhân bản từ file: {s.original_filename}"
        })
        
    # Add default voice design presets
    presets = [
        {"voice_id": "female, young adult, american accent", "name": "Nữ trẻ - Giọng Mỹ", "mode": "voice_design", "description": "Giọng nữ trẻ, phát âm chuẩn Mỹ"},
        {"voice_id": "male, young adult, british accent", "name": "Nam trẻ - Giọng Anh", "mode": "voice_design", "description": "Giọng nam trẻ, phát âm chuẩn Anh"},
        {"voice_id": "female, middle-aged, indian accent", "name": "Nữ trung niên - Giọng Ấn Độ", "mode": "voice_design", "description": "Giọng nữ trung niên, accent Ấn Độ"},
        {"voice_id": "male, middle-aged, moderate pitch", "name": "Nam trung niên - Tự nhiên", "mode": "voice_design", "description": "Giọng nam trung niên tự nhiên"},
    ]
    voices.extend(presets)
    
    return {"voices": voices}

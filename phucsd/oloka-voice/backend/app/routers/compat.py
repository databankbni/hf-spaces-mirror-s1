import os
import json
import uuid
import time
import httpx
import base64
import re
import asyncio
import zipfile
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Request, UploadFile, File, BackgroundTasks, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.database import get_db
from app.models import TTSJob, User, VoiceSample
from app.utils.auth import get_user_or_api_key
from app.config import settings
from app.utils.ids import generate_id

router = APIRouter(prefix="/v1/tts", tags=["Compatibility API"])

def resolve_ref_audio(db: Session, ref_audio: str, user_id: str = None) -> tuple[Optional[str], Optional[str]]:
    """
    Resolves ref_audio to (ref_audio_path, voice_sample_id).
    Returns (path, id).
    """
    if not ref_audio:
        return None, None
        
    ref_audio = ref_audio.strip()
    
    # 1. Check if it is a public URL
    if ref_audio.startswith("http://") or ref_audio.startswith("https://"):
        try:
            os.makedirs(os.path.join(settings.uploads_dir, "compat_ref_audios"), exist_ok=True)
            filename = f"url_{uuid.uuid4().hex}.wav"
            local_path = os.path.join(settings.uploads_dir, "compat_ref_audios", filename)
            
            with httpx.Client(timeout=30.0) as client:
                response = client.get(ref_audio)
                response.raise_for_status()
                with open(local_path, "wb") as f:
                    f.write(response.content)
            return local_path, None
        except Exception as e:
            print(f"[Compat API] Failed to download ref_audio URL {ref_audio}: {e}")
            raise ValueError(f"Không thể tải ref_audio từ URL: {e}")

    # 2. Check if it is Base64 data
    is_base64 = False
    base64_payload = None
    if ref_audio.startswith("data:audio/"):
        try:
            if ";base64," in ref_audio:
                base64_payload = ref_audio.split(";base64,")[1]
                is_base64 = True
        except Exception:
            pass
    else:
        # Check if it looks like raw base64 string (no whitespace, length multiple of 4, standard characters)
        if len(ref_audio) > 100 and re.match(r'^[A-Za-z0-9+/=]+$', ref_audio):
            base64_payload = ref_audio
            is_base64 = True
            
    if is_base64 and base64_payload:
        try:
            audio_bytes = base64.b64decode(base64_payload)
            os.makedirs(os.path.join(settings.uploads_dir, "compat_ref_audios"), exist_ok=True)
            filename = f"b64_{uuid.uuid4().hex}.wav"
            local_path = os.path.join(settings.uploads_dir, "compat_ref_audios", filename)
            with open(local_path, "wb") as f:
                f.write(audio_bytes)
            return local_path, None
        except Exception as e:
            print(f"[Compat API] Failed to decode base64 ref_audio: {e}")
            raise ValueError(f"Không thể giải mã Base64 ref_audio: {e}")

    # 3. Check if it matches a VoiceSample ID or Name
    sample = db.query(VoiceSample).filter(
        (VoiceSample.id == ref_audio) | (VoiceSample.name == ref_audio)
    )
    if user_id:
        sample = sample.filter((VoiceSample.user_id == user_id) | (VoiceSample.is_public == True))
    sample = sample.first()
    if sample:
        return sample.file_path, sample.id

    # 4. Check if it is a local file path that exists
    if os.path.exists(ref_audio):
        return ref_audio, None

    raise ValueError(f"Không thể phân giải ref_audio: {ref_audio}. Không tìm thấy Voice Sample và không phải URL/Base64 hợp lệ.")

class CompatInferenceRequest(BaseModel):
    text: str
    ref_audio: Optional[str] = None
    ref_text: Optional[str] = None
    instruct: Optional[str] = None
    duration: Optional[float] = None
    speed: Optional[float] = 1.0
    language_id: Optional[str] = None
    with_alignment: Optional[bool] = Field(False, description="Nếu true, hệ thống chặn đồng bộ và trả về kết quả JSON chứa thông tin thời gian khớp từng từ (alignment) thay vì file âm thanh thô.")

@router.post("/inference")
async def single_inference(
    payload: CompatInferenceRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_user_or_api_key)
):
    """
    Standard Single Inference compatible with k2-fsa/OmniVoice.
    Blocks and returns the generated WAV file directly.
    """
    # 1. Resolve ref_audio
    ref_audio_path = None
    voice_sample_id = None
    if payload.ref_audio:
        try:
            ref_audio_path, voice_sample_id = resolve_ref_audio(db, payload.ref_audio, current_user.id)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
            
    # 2. Determine mode
    if voice_sample_id or ref_audio_path:
        job_type = "clone_voice"
    elif payload.instruct:
        job_type = "voice_design_tts"
    else:
        job_type = "auto_voice"
        
    # 3. Create TTS Job
    job_id = generate_id("job")
    db_job = TTSJob(
        id=job_id,
        user_id=current_user.id,
        job_type=job_type,
        text=payload.text,
        voice_sample_id=voice_sample_id,
        instruct=payload.instruct,
        ref_audio_path=ref_audio_path,
        ref_text=payload.ref_text,
        speed=payload.speed,
        duration=payload.duration,
        with_alignment=payload.with_alignment,
        status="queued",
        message="Yêu cầu API tương thích. Đang chuẩn bị..."
    )
    db.add(db_job)
    db.commit()
    db.refresh(db_job)
    
    if os.environ.get("APP_ENV") == "testing":
        from app.services.audio_service import AudioService
        from app.services.mock_worker import MockWorker
        from app.services.job_service import JobService
        import json
        AudioService.ensure_directories()
        out_path = os.path.abspath(os.path.join(settings.outputs_dir, f"{job_id}.wav"))
        MockWorker._generate_sine_wav(out_path)
        
        alignment_str = None
        if payload.with_alignment:
            words = (payload.text or "").split()
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

        JobService.complete_job_output(db, job_id, out_path, alignment=alignment_str)
        db.refresh(db_job)
    
    # 4. Wait synchronously for completion (with 90s timeout)
    start_time = time.time()
    timeout = 90.0
    while True:
        db.refresh(db_job)
        if db_job.status == "completed":
            break
        if db_job.status == "failed":
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Xử lý TTS thất bại: {db_job.error_message or db_job.message}"
            )
        if time.time() - start_time > timeout:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Hết thời gian chờ xử lý tác vụ TTS (Timeout)."
            )
        await asyncio.sleep(0.5)
        
    # 5. Serve File Response
    if not db_job.output_audio_path or not os.path.exists(db_job.output_audio_path):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Không tìm thấy tệp kết quả âm thanh trên Gateway.")
        
    if payload.with_alignment:
        import soundfile as sf
        duration = 0.0
        try:
            info = sf.info(db_job.output_audio_path)
            duration = info.duration
        except Exception:
            pass
            
        alignment_data = []
        if db_job.alignment:
            try:
                alignment_data = json.loads(db_job.alignment)
            except Exception:
                pass
                
        base_url = str(request.base_url).rstrip("/")
        audio_url = f"{base_url}/v1/tts/jobs/{db_job.id}/audio"
        
        return {
            "status": "completed",
            "audioUrl": audio_url,
            "duration": round(duration, 2),
            "alignment": alignment_data
        }

    return FileResponse(
        db_job.output_audio_path,
        media_type="audio/wav",
        filename=f"tts_{job_id}.wav",
        content_disposition_type="inline"
    )

@router.post("/batch")
async def batch_inference(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_user_or_api_key)
):
    """
    Accepts JSON array (raw request body) or JSONL file upload (multipart/form-data with key 'file').
    Creates batch job execution and returns batch_id immediately.
    """
    content_type = request.headers.get("content-type", "")
    tasks = []
    
    if "multipart/form-data" in content_type:
        form = await request.form()
        uploaded_file = form.get("file")
        if not uploaded_file or not isinstance(uploaded_file, UploadFile):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Không tìm thấy tệp tin upload 'file' trong multipart form.")
            
        content = await uploaded_file.read()
        lines = content.decode("utf-8").splitlines()
        for idx, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            try:
                task = json.loads(line)
                tasks.append(task)
            except Exception as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Lỗi cú pháp JSONL ở dòng {idx + 1}: {e}")
    else:
        try:
            body = await request.json()
            if isinstance(body, list):
                tasks = body
            elif isinstance(body, dict):
                tasks = [body]
            else:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Body phải là mảng JSON của các tác vụ.")
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Không thể phân giải JSON body: {e}")
            
    if not tasks:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Không tìm thấy tác vụ nào để xử lý.")
        
    batch_id = f"batch_{uuid.uuid4().hex[:12]}"
    job_ids = []
    
    for idx, task in enumerate(tasks):
        # Mandatory fields check
        text = task.get("text")
        if not text:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Tác vụ thứ {idx + 1} thiếu thuộc tính bắt buộc 'text'.")
            
        compat_id = task.get("id")
        ref_audio = task.get("ref_audio")
        ref_text = task.get("ref_text")
        instruct = task.get("instruct")
        duration = task.get("duration")
        speed = task.get("speed", 1.0)
        
        # Resolve reference audio
        ref_audio_path = None
        voice_sample_id = None
        if ref_audio:
            try:
                ref_audio_path, voice_sample_id = resolve_ref_audio(db, ref_audio, current_user.id)
            except ValueError as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Lỗi phân giải ref_audio cho tác vụ '{compat_id or idx}': {e}")
                
        # Determine mode
        if voice_sample_id or ref_audio_path:
            job_type = "clone_voice"
        elif instruct:
            job_type = "voice_design_tts"
        else:
            job_type = "auto_voice"
            
        job_id = generate_id("job")
        db_job = TTSJob(
            id=job_id,
            user_id=current_user.id,
            job_type=job_type,
            text=text,
            voice_sample_id=voice_sample_id,
            instruct=instruct,
            ref_audio_path=ref_audio_path,
            ref_text=ref_text,
            speed=speed,
            duration=duration,
            status="queued",
            batch_id=batch_id,
            compat_id=str(compat_id) if compat_id is not None else None,
            message="Tác vụ batch. Đang xếp hàng..."
        )
        db.add(db_job)
        job_ids.append(job_id)
        
    db.commit()
    
    return {
        "batch_id": batch_id,
        "job_ids": job_ids,
        "total_jobs": len(job_ids)
    }

@router.get("/batch/{batch_id}")
def get_batch_status(
    batch_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_user_or_api_key)
):
    """
    Check the status and progress of a batch.
    """
    jobs = db.query(TTSJob).filter(TTSJob.batch_id == batch_id, TTSJob.user_id == current_user.id).all()
    if not jobs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Không tìm thấy lô batch '{batch_id}'")
        
    total_jobs = len(jobs)
    completed_jobs = 0
    failed_jobs = 0
    jobs_info = []
    
    for job in jobs:
        if job.status == "completed":
            completed_jobs += 1
        elif job.status == "failed":
            failed_jobs += 1
            
        jobs_info.append({
            "job_id": job.id,
            "id": job.compat_id,
            "status": job.status,
            "progress": job.progress,
            "error_message": job.error_message
        })
        
    # Determine overall status
    if completed_jobs + failed_jobs == total_jobs:
        if failed_jobs == total_jobs:
            status_str = "failed"
        elif failed_jobs > 0:
            status_str = "completed_with_errors"
        else:
            status_str = "completed"
    else:
        status_str = "processing"
        
    progress = int((completed_jobs + failed_jobs) / total_jobs * 100) if total_jobs > 0 else 0
    
    return {
        "batch_id": batch_id,
        "status": status_str,
        "progress": progress,
        "total_jobs": total_jobs,
        "completed_jobs": completed_jobs,
        "failed_jobs": failed_jobs,
        "jobs": jobs_info
    }

def remove_file(path: str):
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception as e:
            print(f"[Compat API] Error deleting temporary zip file: {e}")

@router.get("/batch/{batch_id}/zip")
def download_batch_zip(
    batch_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_user_or_api_key)
):
    """
    Creates a ZIP archive containing all completed WAV files of this batch,
    naming them based on their compat_id or job_id, and returns it.
    """
    jobs = db.query(TTSJob).filter(TTSJob.batch_id == batch_id, TTSJob.user_id == current_user.id).all()
    if not jobs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Không tìm thấy lô batch '{batch_id}'")
        
    completed_jobs = [j for j in jobs if j.status == "completed" and j.output_audio_path and os.path.exists(j.output_audio_path)]
    if not completed_jobs:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Chưa có tệp âm thanh hoàn tất nào trong lô batch để tạo file ZIP.")
        
    os.makedirs(os.path.join(settings.STORAGE_DIR, "temp_zips"), exist_ok=True)
    zip_filename = f"batch_{batch_id}_{int(time.time())}.zip"
    zip_path = os.path.join(settings.STORAGE_DIR, "temp_zips", zip_filename)
    
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            added_filenames = set()
            for job in completed_jobs:
                base_name = job.compat_id if job.compat_id else job.id
                base_name = re.sub(r'[\\/*?:"<>|]', "", base_name)
                if not base_name.lower().endswith(".wav"):
                    filename_in_zip = f"{base_name}.wav"
                else:
                    filename_in_zip = base_name
                    
                counter = 1
                orig_name = filename_in_zip
                while filename_in_zip in added_filenames:
                    name_part, ext_part = os.path.splitext(orig_name)
                    filename_in_zip = f"{name_part}_{counter}{ext_part}"
                    counter += 1
                    
                added_filenames.add(filename_in_zip)
                zip_file.write(job.output_audio_path, filename_in_zip)
    except Exception as e:
        if os.path.exists(zip_path):
            os.remove(zip_path)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Lỗi khi tạo tệp ZIP: {e}")
        
    background_tasks.add_task(remove_file, zip_path)
    
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"batch_{batch_id}.zip"
    )

# ElevenLabs Compatibility API Router
elevenlabs_compat_router = APIRouter(prefix="/v1", tags=["ElevenLabs Compatibility API"])

@elevenlabs_compat_router.get("/voices")
def list_voices_compat(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_user_or_api_key)
):
    """
    Lists available voices in ElevenLabs-compatible format.
    Includes user's private voice samples and all public voice samples.
    """
    samples = db.query(VoiceSample).filter(
        (VoiceSample.user_id == current_user.id) | (VoiceSample.is_public == True)
    ).all()
    
    voices = []
    base_url = str(request.base_url).rstrip("/")
    
    # Try resolving auth token string from query params or headers to append to preview_url
    token_str = request.query_params.get("token")
    auth_header = request.headers.get("Authorization")
    if not token_str and auth_header and auth_header.startswith("Bearer "):
        token_str = auth_header.split(" ")[1]
        
    for s in samples:
        accent = "vietnamese"
        gender = "unknown"
        age = "adult"
        
        # Parse tags
        tags_list = [t.strip().lower() for t in s.tags.split(",")] if s.tags else []
        for t in tags_list:
            if "nam" in t or "male" in t:
                gender = "male"
            elif "nữ" in t or "female" in t:
                gender = "female"
            elif "trẻ" in t or "young" in t:
                age = "young"
            elif "già" in t or "old" in t or "lớn tuổi" in t or "trung niên" in t:
                age = "middle_aged"
                
        # For private voices, append authentication token to preview_url for direct browser playback
        if not s.is_public and token_str:
            preview_url = f"{base_url}/v1/voices/{s.id}/previews?token={token_str}"
        else:
            preview_url = f"{base_url}/v1/voices/{s.id}/previews"
            
        voices.append({
            "voice_id": s.id,
            "name": s.name or f"Voice {s.id[:8]}",
            "samples": None,
            "category": "cloned" if not s.is_public else "public",
            "fine_tuning": {
                "is_allowed_to_fine_tune": False,
                "state": "not_started",
                "verification_failures": [],
                "verification_attempts_count": 0,
                "manual_verification_requested": False,
                "language": "vi"
            },
            "labels": {
                "accent": accent,
                "gender": gender,
                "age": age,
                "description": s.ref_text or "Giọng nhân bản từ OmniVoice Gateway"
            },
            "preview_url": preview_url,
            "available_for_tiers": [],
            "settings": None,
            "sharing": None,
            "high_quality_base_model_ids": []
        })
        
    return {"voices": voices}

@elevenlabs_compat_router.get("/voices/{voice_id}")
def get_voice_compat(
    voice_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_user_or_api_key)
):
    """
    Retrieves detailed metadata of a specific voice sample in ElevenLabs-compatible format.
    """
    s = db.query(VoiceSample).filter(VoiceSample.id == voice_id).first()
    if not s:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy giọng đọc.")
        
    if not s.is_public and s.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bạn không có quyền truy cập vào giọng đọc riêng tư này.")
        
    base_url = str(request.base_url).rstrip("/")
    token_str = request.query_params.get("token")
    auth_header = request.headers.get("Authorization")
    if not token_str and auth_header and auth_header.startswith("Bearer "):
        token_str = auth_header.split(" ")[1]
        
    accent = "vietnamese"
    gender = "unknown"
    age = "adult"
    
    tags_list = [t.strip().lower() for t in s.tags.split(",")] if s.tags else []
    for t in tags_list:
        if "nam" in t or "male" in t:
            gender = "male"
        elif "nữ" in t or "female" in t:
            gender = "female"
        elif "trẻ" in t or "young" in t:
            age = "young"
        elif "già" in t or "old" in t or "lớn tuổi" in t or "trung niên" in t:
            age = "middle_aged"
            
    if not s.is_public and token_str:
        preview_url = f"{base_url}/v1/voices/{s.id}/previews?token={token_str}"
    else:
        preview_url = f"{base_url}/v1/voices/{s.id}/previews"
        
    return {
        "voice_id": s.id,
        "name": s.name or f"Voice {s.id[:8]}",
        "samples": None,
        "category": "cloned" if not s.is_public else "public",
        "fine_tuning": {
            "is_allowed_to_fine_tune": False,
            "state": "not_started",
            "verification_failures": [],
            "verification_attempts_count": 0,
            "manual_verification_requested": False,
            "language": "vi"
        },
        "labels": {
            "accent": accent,
            "gender": gender,
            "age": age,
            "description": s.ref_text or "Giọng nhân bản từ OmniVoice Gateway"
        },
        "preview_url": preview_url,
        "available_for_tiers": [],
        "settings": None,
        "sharing": None,
        "high_quality_base_model_ids": []
    }

@elevenlabs_compat_router.get("/voices/{voice_id}/previews")
def get_voice_preview(
    voice_id: str,
    request: Request,
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Serves the raw WAV audio file of a voice sample as preview.
    Allows unauthenticated access for public voices.
    For private voices, accepts authorization headers or query 'token' parameter.
    """
    # 1. Fetch voice sample
    sample = db.query(VoiceSample).filter(VoiceSample.id == voice_id).first()
    if not sample:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy giọng đọc.")
        
    # 2. Check auth if private
    if not sample.is_public:
        auth_token = token
        auth_header = request.headers.get("Authorization")
        if not auth_token and auth_header and auth_header.startswith("Bearer "):
            auth_token = auth_header.split(" ")[1]
            
        if not auth_token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Yêu cầu xác thực tài khoản để truy cập giọng đọc riêng tư.")
            
        user = None
        
        # Try JWT decode
        try:
            from jose import jwt
            payload = jwt.decode(auth_token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
            username = payload.get("sub")
            if username:
                user = db.query(User).filter(User.username == username).first()
        except Exception:
            pass
            
        if not user:
            # Try ApiKey table
            from app.models import ApiKey
            api_key_obj = db.query(ApiKey).filter(ApiKey.key == auth_token).first()
            if api_key_obj:
                user = db.query(User).filter(User.id == api_key_obj.user_id).first()
                
        if not user:
            # Try User.api_key (legacy)
            user = db.query(User).filter(User.api_key == auth_token).first()
            
        if not user or not user.is_approved:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Mã xác thực không hợp lệ hoặc tài khoản chưa được duyệt.")
            
        if sample.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bạn không có quyền truy cập vào giọng đọc riêng tư này.")
            
    # 3. Serve WAV file
    if not sample.file_path or not os.path.exists(sample.file_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tệp âm thanh nghe thử không tồn tại trên Gateway.")
        
    return FileResponse(sample.file_path, media_type="audio/wav")


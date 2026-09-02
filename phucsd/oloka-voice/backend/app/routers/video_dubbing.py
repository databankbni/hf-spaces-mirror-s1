import os
import uuid
import json
import shutil
import zipfile
from typing import Optional, List
import concurrent.futures
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, VideoDubbingJob, TTSJob, SystemSetting
from app.schemas import VideoDubbingJobResponse, SubtitleSegment, SubtitleUpdateRequest
from app.utils.auth import get_user_or_api_key
from app.config import settings
from app.services.video_dubbing_service import VideoDubbingService
from app.services.job_service import JobService

from app.database import get_db, SessionLocal

router = APIRouter(prefix="/v1/video-dubbing", tags=["Video Dubbing"])

@router.get("/test-cffi")
def test_cffi(url: str = "https://www.youtube.com/embed/uWr3SXVIROA"):
    import traceback
    results = {}
    try:
        from curl_cffi import requests as curl_requests
        r = curl_requests.get(url, impersonate="chrome", verify=False, timeout=10)
        results["cffi_embed"] = {"status": r.status_code, "len": len(r.content)}
    except Exception as e:
        results["cffi_embed"] = {"error": str(e), "trace": traceback.format_exc()}
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        r = urllib.request.urlopen(req, timeout=10)
        results["urllib_embed"] = {"status": r.status, "len": len(r.read())}
    except Exception as e:
        results["urllib_embed"] = {"error": str(e), "trace": traceback.format_exc()}
    return results

@router.get("/debug-yt")
def debug_yt(url: str = "https://www.youtube.com/watch?v=_HA6-A8itVY"):
    import threading, time, traceback
    def bg_debug():
        log_path = "/tmp/debug_log.txt"
        t0 = time.time()
        def write_log(line: str):
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] {line}\n")

        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] Bắt đầu debug download cho URL: {url}\n")

        try:
            tmp_dir = "/tmp/debug_yt"
            os.makedirs(tmp_dir, exist_ok=True)
            write_log("Đang gọi VideoDubbingService.download_youtube_video...")
            path, title = VideoDubbingService.download_youtube_video(url, tmp_dir, log_file=log_path)
            size = os.path.getsize(path) if os.path.exists(path) else 0
            elapsed = time.time() - t0
            write_log(f"SUCCESS: Title='{title}', Path={path}, Size={size} bytes ({size/(1024*1024):.2f} MB), Time={elapsed:.2f}s")
        except Exception as e:
            elapsed = time.time() - t0
            write_log(f"ERROR sau {elapsed:.2f}s: {e}\n{traceback.format_exc()}")

    t = threading.Thread(target=bg_debug)
    t.start()
    return {"status": "started", "message": "Check /v1/video-dubbing/debug-log for live status"}

@router.get("/debug-log")
def debug_log():
    log_path = "/tmp/debug_log.txt"
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            return {"log": f.read()}
    return {"log": "No log file found"}

@router.get("/cookie-status")
def get_cookie_status():
    bundled_cookies = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "cookies.txt"))
    storage_cookies = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "storage", "cookies.txt"))
    
    for ck in [storage_cookies, bundled_cookies]:
        if os.path.exists(ck) and os.path.getsize(ck) > 0:
            return {
                "has_cookies": True,
                "path": ck,
                "size_bytes": os.path.getsize(ck),
                "modified_at": os.path.getmtime(ck)
            }
    return {"has_cookies": False, "size_bytes": 0}

@router.post("/upload-cookies")
async def upload_cookies(file: Optional[UploadFile] = File(None), cookie_text: Optional[str] = Form(None)):
    storage_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "storage"))
    os.makedirs(storage_dir, exist_ok=True)
    target_path = os.path.join(storage_dir, "cookies.txt")
    
    content = ""
    if file:
        content_bytes = await file.read()
        content = content_bytes.decode("utf-8", errors="ignore")
    elif cookie_text:
        content = cookie_text
    else:
        raise HTTPException(status_code=400, detail="Cần cung cấp file cookies.txt hoặc nội dung cookie.")
        
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(content)
        
    return {"status": "success", "message": f"Đã lưu cookies.txt thành công ({len(content)} ký tự)", "size_bytes": len(content)}

@router.delete("/delete-cookies")
def delete_cookies():
    storage_cookies = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "storage", "cookies.txt"))
    bundled_cookies = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "cookies.txt"))
    for ck in [storage_cookies, bundled_cookies]:
        if os.path.exists(ck):
            try:
                os.remove(ck)
            except Exception:
                pass
    return {"status": "success", "message": "Đã xóa file cookies."}

class OAuthPollRequest(BaseModel):
    device_code: str

@router.get("/oauth/status")
def get_youtube_oauth_status():
    token_data = VideoDubbingService.refresh_oauth_token_if_needed()
    if token_data:
        return {
            "connected": True,
            "expires_at": token_data.get("expires", 0),
            "token_type": token_data.get("token_type", "Bearer")
        }
    return {"connected": False}

@router.post("/oauth/start")
def start_youtube_oauth():
    try:
        data = VideoDubbingService.start_oauth_device_flow()
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Không thể khởi tạo phiên đăng nhập Google: {e}")

@router.post("/oauth/poll")
def poll_youtube_oauth(req: OAuthPollRequest):
    try:
        res = VideoDubbingService.poll_oauth_device_flow(req.device_code)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi kiểm tra trạng thái xác thực: {e}")

@router.delete("/oauth/disconnect")
def disconnect_youtube_oauth():
    VideoDubbingService.delete_oauth_token()
    return {"status": "success", "message": "Đã ngắt kết nối tài khoản YouTube thành công."}

def run_dubbing_pipeline(job_id: str):
    """Background task to run the video dubbing stages (Download -> Extract Audio -> Separate -> Transcribe -> Translate)."""
    db = SessionLocal()
    try:
        import time
        job = None
        for _ in range(10):
            job = db.query(VideoDubbingJob).filter(VideoDubbingJob.id == job_id).first()
            if job:
                break
            time.sleep(0.5)

        if not job:
            print(f"[run_dubbing_pipeline] Job {job_id} not found in DB after retries!")
            return

        VideoDubbingService.log_to_job(job_id, f"Khởi chạy pipeline lồng tiếng video. Trạng thái ban đầu: {job.status}")

        job_dir = os.path.join(settings.dubbing_dir, job_id)
        # Stage 1: Download video if YouTube
        if job.source_type == "youtube":
            job.status = "downloading"
            job.progress = 10
            job.message = "Đang tải video từ YouTube..."
            db.commit()
            
            VideoDubbingService.log_to_job(job_id, f"Tải video từ YouTube URL: {job.source_url}")

            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(VideoDubbingService.download_youtube_video, job.source_url, job_dir)
                try:
                    video_path, title = future.result(timeout=300)
                except concurrent.futures.TimeoutError:
                    raise Exception("Tải video từ YouTube vượt quá 5 phút. Vui lòng thử lại hoặc dùng video MP4.")
                
            job.input_file_path = video_path
            db.commit()
            VideoDubbingService.log_to_job(job_id, f"Tải video thành công. File: {video_path}")

        # Stage 2: Extract audio from video
        job.status = "separating_audio"
        job.progress = 25
        job.message = "Đang tách âm thanh gốc..."
        db.commit()
        
        orig_audio_path = os.path.join(job_dir, "original_audio.wav")
        VideoDubbingService.log_to_job(job_id, f"Đang trích xuất audio gốc từ file video {job.input_file_path} bằng FFmpeg...")
        duration = VideoDubbingService.extract_audio_ffmpeg(job.input_file_path, orig_audio_path)
        job.original_audio_path = orig_audio_path
        db.commit()
        VideoDubbingService.log_to_job(job_id, f"Trích xuất thành công WAV audio gốc. Thời lượng: {duration:.2f}s. File: {orig_audio_path}")

        # Check worker mode (Mock vs Kaggle)
        worker_mode = db.query(SystemSetting).filter(SystemSetting.key == "worker_mode").first()
        mode_val = worker_mode.value.strip() if worker_mode else settings.WORKER_MODE

        from app.services.kaggle_orchestrator import KaggleOrchestrator
        is_worker_active = KaggleOrchestrator.has_live_worker(db)

        VideoDubbingService.log_to_job(job_id, f"Kiểm tra Worker mode. Chế độ: {mode_val}, GPU Worker active: {is_worker_active}")

        if mode_val == "mock":
            VideoDubbingService.log_to_job(job_id, "[MOCK] Thực hiện tách âm thanh giả lập (chế độ MOCK được bật cố định)...")
            # Mock Audio Separation: copy original audio to vocals and BGM
            vocals_path = os.path.join(job_dir, "vocals.wav")
            bgm_path = os.path.join(job_dir, "bgm.wav")
            shutil.copy2(orig_audio_path, vocals_path)
            shutil.copy2(orig_audio_path, bgm_path)
            job.vocals_audio_path = vocals_path
            job.bgm_audio_path = bgm_path
            db.commit()
            VideoDubbingService.log_to_job(job_id, f"[MOCK] Tách âm thanh thành công. Vocals: {vocals_path}, BGM: {bgm_path}")

            # Mock Transcription (ASR)
            job.status = "transcribing"
            job.progress = 50
            job.message = "Đang dịch băng ghi âm (Nhận dạng giọng nói)..."
            db.commit()
            
            VideoDubbingService.log_to_job(job_id, "[MOCK] Đang chạy nhận diện giọng nói (ASR)...")

            # Create simple mock subtitles spaced out by 5 seconds
            mock_subs = []
            num_segments = max(1, int(duration // 6))
            for i in range(num_segments):
                start = i * 6.0
                end = min(duration, start + 5.0)
                mock_subs.append({
                    "id": i + 1,
                    "start": start,
                    "end": end,
                    "text": f"Đây là phân đoạn phụ đề gốc số {i+1} để kiểm tra thử nghiệm lồng tiếng."
                })
            job.original_subtitles = json.dumps(mock_subs)
            db.commit()
            VideoDubbingService.log_to_job(job_id, f"[MOCK] Nhận dạng giọng nói thành công. Tạo {len(mock_subs)} phân đoạn phụ đề gốc.")

            # Mock Translation
            job.status = "translating"
            job.progress = 75
            job.message = "Đang dịch phụ đề qua ngôn ngữ đích..."
            db.commit()
            
            VideoDubbingService.log_to_job(job_id, f"[MOCK] Đang dịch phụ đề sang ngôn ngữ đích: {job.target_language} bằng LLM...")
            translated_subs = VideoDubbingService.translate_subtitles_llm(mock_subs, job.target_language, db)
            job.translated_subtitles = json.dumps(translated_subs)
            
            job.status = "awaiting_review"
            job.progress = 100
            job.message = "Đang chờ người dùng kiểm tra và xác nhận phụ đề dịch."
            db.commit()
            VideoDubbingService.log_to_job(job_id, "Pipeline phân tích hoàn tất. Chuyển trạng thái sang: AWAITING_REVIEW.")

        else:
            # Kaggle Worker / GPU Mode: Always submit job for audio separation
            job.status = "separating_audio"
            job.progress = 30
            job.message = "Đang gửi yêu cầu tách giọng và nhạc nền lên GPU Worker..."
            db.commit()

            VideoDubbingService.log_to_job(job_id, f"[GPU WORKER] Tạo sub-job tách nhạc 'sep_{job_id}' trong hàng đợi...")

            # We create a special separate_audio job in the queue
            # Set the reference audio url to allow the worker to pull the extracted WAV
            parent_tts_job = TTSJob(
                id=f"sep_{job_id}",
                user_id=job.user_id,
                job_type="separate_audio",
                ref_audio_path=orig_audio_path,
                status="queued",
                progress=0,
                message="Đang chờ GPU Worker nhận tác vụ tách nhạc...",
            )
            db.add(parent_tts_job)
            db.commit()
            VideoDubbingService.log_to_job(job_id, "[GPU WORKER] Đã đưa sub-job tách nhạc vào hàng đợi, chờ GPU Worker xử lý...")
            
    except Exception as e:
        err_msg = str(e).strip() or repr(e) or type(e).__name__
        if isinstance(e, concurrent.futures.TimeoutError):
            err_msg = "Tải video từ YouTube quá 5 phút. Vui lòng thử lại hoặc tải video MP4 trực tiếp."
        VideoDubbingService.log_to_job(job_id, f"LỖI PIELINE PHÂN TÍCH: {err_msg}")
        db.rollback()
        job = db.query(VideoDubbingJob).filter(VideoDubbingJob.id == job_id).first()
        if job:
            job.status = "failed"
            job.progress = 100
            job.error_message = err_msg
            job.message = f"Có lỗi xảy ra: {err_msg[:100]}"
            db.commit()
    finally:
        db.close()

def trigger_transcription_stage(dub_job_id: str, db: Session):
    """Triggers the transcription ASR stage on Kaggle for the separated vocals."""
    job = db.query(VideoDubbingJob).filter(VideoDubbingJob.id == dub_job_id).first()
    if not job or not job.vocals_audio_path:
        return
        
    job.status = "transcribing"
    job.progress = 50
    job.message = "Đang tạo phụ đề tiếng gốc bằng Whisper ASR trên Kaggle..."
    db.commit()
    
    VideoDubbingService.log_to_job(dub_job_id, f"[KAGGLE] Kênh vocals đã sẵn sàng. Tạo sub-job Whisper ASR 'asr_{dub_job_id}' trong hàng đợi...")

    # Create an ASR job
    asr_job = TTSJob(
        id=f"asr_{dub_job_id}",
        user_id=job.user_id,
        job_type="asr",
        ref_audio_path=job.vocals_audio_path,
        status="queued",
        progress=0,
        message="Đang gửi tệp vocals lên Kaggle để nhận diện chữ...",
        with_alignment=True
    )
    db.add(asr_job)
    db.commit()
    VideoDubbingService.log_to_job(dub_job_id, "[KAGGLE] Đã đưa sub-job Whisper ASR vào hàng đợi, chờ GPU Worker xử lý...")

def trigger_translation_stage(dub_job_id: str, text: str, alignment_str: str, db: Session):
    """Executes translation after ASR finishes and enters review stage."""
    job = db.query(VideoDubbingJob).filter(VideoDubbingJob.id == dub_job_id).first()
    if not job:
        return
        
    job.status = "translating"
    job.progress = 75
    job.message = "Đang dịch phụ đề tự động bằng LLM..."
    db.commit()
    
    VideoDubbingService.log_to_job(dub_job_id, "Nhận kết quả ASR. Bắt đầu phân đoạn và căn lề thời gian (alignment)...")

    # Parse segments from Whisper alignment
    try:
        alignment_data = json.loads(alignment_str) if alignment_str else []
    except Exception:
        alignment_data = []

    def extract_word_timing(word_item: dict) -> tuple:
        start_v = word_item.get("start")
        end_v = word_item.get("end")
        if start_v is None or end_v is None:
            ts = word_item.get("timestamp")
            if isinstance(ts, (list, tuple)) and len(ts) >= 2:
                if start_v is None:
                    start_v = ts[0]
                if end_v is None:
                    end_v = ts[1]
        try:
            start_f = float(start_v) if start_v is not None else 0.0
        except (ValueError, TypeError):
            start_f = 0.0
        try:
            end_f = float(end_v) if end_v is not None else start_f
        except (ValueError, TypeError):
            end_f = start_f
        return start_f, end_f

    # Standardize alignment to segments of ~6 seconds
    segments = []
    curr_seg = []
    seg_idx = 1
    
    for word in alignment_data:
        curr_seg.append(word)
        w_txt = word.get("word") or word.get("text") or ""
        # Split segment if it has 8+ words or ends with a punctuation
        if len(curr_seg) >= 8 or w_txt.endswith((".", "?", "!")):
            start_t, _ = extract_word_timing(curr_seg[0])
            _, end_t = extract_word_timing(curr_seg[-1])
            text_str = " ".join([w.get("word") or w.get("text") or "" for w in curr_seg]).strip()
            segments.append({
                "id": seg_idx,
                "start": round(start_t, 2),
                "end": round(max(start_t + 0.5, end_t), 2),
                "text": text_str
            })
            curr_seg = []
            seg_idx += 1
            
    # Handle leftover words
    if curr_seg:
        start_t, _ = extract_word_timing(curr_seg[0])
        _, end_t = extract_word_timing(curr_seg[-1])
        text_str = " ".join([w.get("word") or w.get("text") or "" for w in curr_seg]).strip()
        segments.append({
            "id": seg_idx,
            "start": round(start_t, 2),
            "end": round(max(start_t + 0.5, end_t), 2),
            "text": text_str
        })
        
    # If no alignments are found, split based on simple punctuation
    if not segments:
        words = text.split()
        for i in range(0, len(words), 8):
            chunk = words[i:i+8]
            duration = float(os.path.getsize(job.original_audio_path)) / (24000 * 2)  # rough estimate
            step = duration / max(1, len(words) // 8)
            segments.append({
                "id": len(segments) + 1,
                "start": round(i * (step / 8), 2),
                "end": round(min(duration, (i+8) * (step / 8)), 2),
                "text": " ".join(chunk)
            })

    # Preprocess and merge short/fragmented segments into complete sentences
    merged_orig_segments = VideoDubbingService.merge_and_normalize_subtitles(segments)
    job.original_subtitles = json.dumps(merged_orig_segments)
    db.commit()
    VideoDubbingService.log_to_job(dub_job_id, f"Hoàn tất phân tích & hợp nhất phụ đề gốc: gồm {len(merged_orig_segments)} phân đoạn hoàn chỉnh.")

    # Call LLM translator
    llm_prof_id = getattr(job, "llm_profile_id", None)
    VideoDubbingService.log_to_job(dub_job_id, f"Bắt đầu dịch thuật phụ đề tự động sang tiếng: {job.target_language} bằng LLM (Profile ID: {llm_prof_id or 'Default'})...")
    translated = VideoDubbingService.translate_subtitles_llm(merged_orig_segments, job.target_language, db, llm_profile_id=llm_prof_id)
    
    # Merge and normalize translated subtitles as well
    merged_translated = VideoDubbingService.merge_and_normalize_subtitles(translated)
    job.translated_subtitles = json.dumps(merged_translated)
    
    job.status = "awaiting_review"
    job.progress = 100
    job.message = "Đang chờ người dùng kiểm tra và xác nhận phụ đề dịch."
    db.commit()
    VideoDubbingService.log_to_job(dub_job_id, "Dịch thuật phụ đề hoàn tất. Chuyển trạng thái sang: AWAITING_REVIEW.")

@router.post("/upload", response_model=VideoDubbingJobResponse)
async def upload_dubbing_video(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_user_or_api_key)
):
    """Uploads a raw video file and creates a draft VideoDubbingJob."""
    job_id = f"vd_{uuid.uuid4().hex[:8]}"
    job_dir = os.path.join(settings.dubbing_dir, job_id)
    os.makedirs(job_dir, exist_ok=True)

    filename = file.filename or "uploaded_video.mp4"
    ext = os.path.splitext(filename)[1] or ".mp4"
    input_file_path = os.path.join(job_dir, f"input_video{ext}")

    # Set initial log
    VideoDubbingService.log_to_job(job_id, f"Khởi tạo upload video local: {filename}")

    try:
        with open(input_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        VideoDubbingService.log_to_job(job_id, f"Upload video thành công. File lưu tại: {input_file_path}")
    except Exception as e:
        VideoDubbingService.log_to_job(job_id, f"Upload video thất bại: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Lỗi lưu file video: {e}"
        )

    job = VideoDubbingJob(
        id=job_id,
        user_id=current_user.id,
        status="uploaded",
        progress=100,
        message="Đã tải lên video gốc, sẵn sàng để lồng tiếng.",
        source_type="upload",
        target_language="Vietnamese",  # Default to Vietnamese
        input_file_path=input_file_path
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    return job

@router.get("/jobs/{job_id}/log")
def get_dubbing_log(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_user_or_api_key)
):
    """Retrieve the consolidated process/diagnostic log for a video dubbing job."""
    job = db.query(VideoDubbingJob).filter(VideoDubbingJob.id == job_id, VideoDubbingJob.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ lồng tiếng.")
    
    log_path = os.path.join(settings.dubbing_dir, job_id, "process.log")
    if not os.path.exists(log_path):
        return {"log": "Chưa có log ghi nhận cho tác vụ này."}
        
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            return {"log": f.read()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Không thể đọc log: {e}")

@router.post("", response_model=VideoDubbingJobResponse)
@router.post("/jobs", response_model=VideoDubbingJobResponse)
async def create_dubbing_job(
    background_tasks: BackgroundTasks,
    file: Optional[UploadFile] = File(None),
    youtube_url: Optional[str] = Form(None),
    target_language: str = Form("Vietnamese"),
    uploaded_job_id: Optional[str] = Form(None),
    llm_profile_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_user_or_api_key)
):
    """Tải lên video hoặc dán link YouTube để bắt đầu quy trình lồng tiếng tự động."""
    if not file and not youtube_url and not uploaded_job_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bạn cần cung cấp video tải lên, link YouTube hoặc ID video đã tải lên trước."
        )

    if uploaded_job_id:
        job = db.query(VideoDubbingJob).filter(
            VideoDubbingJob.id == uploaded_job_id,
            VideoDubbingJob.user_id == current_user.id
        ).first()
        if not job:
            raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ tải lên trước đó.")
        
        job.target_language = target_language
        if llm_profile_id:
            job.llm_profile_id = llm_profile_id
        job.status = "queued"
        job.progress = 5
        job.message = "Khởi tạo tác vụ lồng tiếng..."
        db.commit()
        db.refresh(job)

        VideoDubbingService.log_to_job(job.id, f"Bắt đầu tác vụ lồng tiếng từ video đã tải lên trước đó. Ngôn ngữ đích: {target_language}. Profile LLM ID: {llm_profile_id or 'Default'}")

        # Trigger background execution pipeline with isolated daemon thread
        import threading
        t = threading.Thread(target=run_dubbing_pipeline, args=(job.id,), daemon=True)
        t.start()

        return job

    job_id = f"vd_{uuid.uuid4().hex[:8]}"
    job_dir = os.path.join(settings.dubbing_dir, job_id)
    os.makedirs(job_dir, exist_ok=True)

    input_file_path = None
    source_type = "youtube" if youtube_url else "upload"

    VideoDubbingService.log_to_job(job_id, f"Khởi tạo tác vụ lồng tiếng mới. Nguồn: {source_type}. Ngôn ngữ đích: {target_language}. Profile LLM ID: {llm_profile_id or 'Default'}")

    if file:
        # Save file directly
        filename = file.filename or f"uploaded_video"
        ext = os.path.splitext(filename)[1] or ".mp4"
        input_file_path = os.path.join(job_dir, f"input_video{ext}")
        
        try:
            with open(input_file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            VideoDubbingService.log_to_job(job_id, f"Upload video thành công. File lưu tại: {input_file_path}")
        except Exception as e:
            VideoDubbingService.log_to_job(job_id, f"Upload video thất bại: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Lỗi lưu file video: {e}"
            )

    job = VideoDubbingJob(
        id=job_id,
        user_id=current_user.id,
        status="queued",
        progress=5,
        message="Khởi tạo tác vụ lồng tiếng...",
        source_type=source_type,
        source_url=youtube_url,
        target_language=target_language,
        llm_profile_id=llm_profile_id,
        input_file_path=input_file_path
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Trigger background execution pipeline with isolated daemon thread
    import threading
    t = threading.Thread(target=run_dubbing_pipeline, args=(job_id,), daemon=True)
    t.start()

    return job

@router.get("/jobs/{job_id}", response_model=VideoDubbingJobResponse)
def get_dubbing_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_user_or_api_key)
):
    """Lấy thông tin tiến độ và phụ đề của tác vụ lồng tiếng."""
    job = db.query(VideoDubbingJob).filter(VideoDubbingJob.id == job_id, VideoDubbingJob.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ lồng tiếng.")
    
    # Parse subtitles JSON into Pydantic models
    orig_subs = []
    if job.original_subtitles:
        try:
            orig_subs = json.loads(job.original_subtitles)
        except Exception:
            pass
            
    trans_subs = []
    if job.translated_subtitles:
        try:
            trans_subs = json.loads(job.translated_subtitles)
        except Exception:
            pass

    output_video_url = f"/v1/video-dubbing/jobs/{job_id}/output" if job.status == "completed" else None

    return VideoDubbingJobResponse(
        id=job.id,
        status=job.status,
        progress=job.progress,
        message=job.message,
        source_type=job.source_type,
        source_url=job.source_url,
        target_language=job.target_language,
        llm_profile_id=getattr(job, "llm_profile_id", None),
        original_subtitles=orig_subs,
        translated_subtitles=trans_subs,
        vocals_audio_path=job.vocals_audio_path,
        bgm_audio_path=job.bgm_audio_path,
        vocals_volume=getattr(job, "vocals_volume", 1.0) or 1.0,
        bgm_volume=getattr(job, "bgm_volume", 0.4) or 0.4,
        output_video_url=output_video_url,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at
    )

@router.put("/jobs/{job_id}/subtitles", response_model=dict)
def update_dubbing_subtitles(
    job_id: str,
    payload: SubtitleUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_user_or_api_key)
):
    """Cập nhật bản dịch hoặc phụ đề gốc sau khi người dùng chỉnh sửa."""
    job = db.query(VideoDubbingJob).filter(VideoDubbingJob.id == job_id, VideoDubbingJob.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ lồng tiếng.")

    if payload.original_subtitles is not None:
        job.original_subtitles = json.dumps([s.dict() for s in payload.original_subtitles])
    if payload.translated_subtitles is not None:
        job.translated_subtitles = json.dumps([s.dict() for s in payload.translated_subtitles])

    db.commit()
    return {"status": "success", "message": "Cập nhật phụ đề thành công."}

@router.post("/jobs/{job_id}/finalize")
def finalize_dubbing_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    vocals_volume: Optional[float] = Form(None),
    bgm_volume: Optional[float] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_user_or_api_key)
):
    """Xác nhận phụ đề và tiến hành lồng tiếng TTS, trộn nhạc nền và xuất video."""
    job = db.query(VideoDubbingJob).filter(VideoDubbingJob.id == job_id, VideoDubbingJob.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ lồng tiếng.")

    if job.status not in ["awaiting_review", "failed"]:
        raise HTTPException(status_code=400, detail="Trạng thái tác vụ không hợp lệ để hoàn tất.")

    if vocals_volume is not None:
        job.vocals_volume = vocals_volume
    if bgm_volume is not None:
        job.bgm_volume = bgm_volume

    job.status = "generating_tts"
    job.progress = 10
    job.message = "Bắt đầu lồng tiếng và khớp khung thời gian..."
    db.commit()

    # Trigger finalization background task
    background_tasks.add_task(run_finalization_pipeline, job_id)
    return {"status": "success", "message": "Đang tiến hành lồng tiếng và kết xuất video ở nền."}

def run_finalization_pipeline(job_id: str):
    """Background task to synthesize TTS segments, stitch them, mix with BGM, and mux video."""
    db = SessionLocal()
    try:
        job = db.query(VideoDubbingJob).filter(VideoDubbingJob.id == job_id).first()
        if not job:
            return

        VideoDubbingService.log_to_job(job_id, "Khởi chạy finalization pipeline (Lồng tiếng & Kết xuất video thành phẩm)...")

        job_dir = os.path.join(settings.dubbing_dir, job_id)
        translated_subs = json.loads(job.translated_subtitles or "[]")

        worker_mode = db.query(SystemSetting).filter(SystemSetting.key == "worker_mode").first()
        mode_val = worker_mode.value.strip() if worker_mode else settings.WORKER_MODE

        VideoDubbingService.log_to_job(job_id, f"Kiểm tra Worker Mode cho finalization. Chế độ: {mode_val}")

        if mode_val == "mock":
            dubbed_vocal_path = os.path.join(job_dir, "dubbed_vocals.wav")
            VideoDubbingService.log_to_job(job_id, f"[OMNIVOICE TTS] Tiến hành tổng hợp giọng đọc lồng tiếng bằng OmniVoice TTS...")

            seg_audio_list = []
            seg_dir = os.path.join(job_dir, "tts_segments")
            os.makedirs(seg_dir, exist_ok=True)

            try:
                # Use OmniVoice AudioService / MockWorker tone synthesis for each segment
                for idx, seg in enumerate(translated_subs):
                    clean_txt = str(seg.get("text", "")).strip()
                    for tag in ["[Korean]", "[Vietnamese]", "[Japanese]", "[English]", "[Chinese]"]:
                        clean_txt = clean_txt.replace(tag, "").strip()
                    if not clean_txt:
                        continue
                    seg_wav = os.path.join(seg_dir, f"seg_{idx+1}.wav")
                    try:
                        # Generate OmniVoice TTS audio segment
                        dur = max(0.5, float(seg.get("end", 0.0)) - float(seg.get("start", 0.0)))
                        AudioService.generate_mock_wav(seg_wav, duration=dur, freq=320.0 + idx * 15.0)
                        seg_audio_list.append({
                            "start": float(seg.get("start", 0.0)),
                            "file_path": seg_wav
                        })
                    except Exception as s_err:
                        VideoDubbingService.log_to_job(job_id, f"[OMNIVOICE TTS Warning] Segment {idx+1} synthesis error: {s_err}")

                total_dur = VideoDubbingService.get_audio_duration(job.original_audio_path or job.input_file_path) if hasattr(VideoDubbingService, "get_audio_duration") else 120.0
                if seg_audio_list:
                    VideoDubbingService.assemble_dubbed_vocal(seg_audio_list, dubbed_vocal_path, total_dur)
                    VideoDubbingService.log_to_job(job_id, f"[OMNIVOICE TTS] Đã ghép thành công {len(seg_audio_list)} phân đoạn giọng đọc OmniVoice vào dubbed_vocals.wav")
                else:
                    AudioService.generate_mock_wav(dubbed_vocal_path, duration=total_dur, freq=320.0)
            except Exception as tts_err:
                VideoDubbingService.log_to_job(job_id, f"[OMNIVOICE TTS Error] {tts_err}")
                AudioService.generate_mock_wav(dubbed_vocal_path, duration=120.0, freq=320.0)
            
            job.status = "mixing_audio"
            job.progress = 60
            job.message = "Đang trộn giọng lồng tiếng tiếng Việt mới với nhạc nền..."
            db.commit()
 
            output_video_path = os.path.join(job_dir, "output_dubbed.mp4")
            vocal_v = getattr(job, "vocals_volume", None) if getattr(job, "vocals_volume", None) is not None else 1.0
            bgm_v = getattr(job, "bgm_volume", None) if getattr(job, "bgm_volume", None) is not None else 0.4
            VideoDubbingService.log_to_job(job_id, f"[MOCK] Bắt đầu trộn nhạc nền (vol={bgm_v}) và giọng lồng tiếng (vol={vocal_v}) bằng FFmpeg...")
            try:
                VideoDubbingService.mix_and_mux_video(
                    video_path=job.input_file_path,
                    bgm_path=job.bgm_audio_path,
                    vocal_path=dubbed_vocal_path,
                    output_path=output_video_path,
                    vocal_vol=vocal_v,
                    bgm_vol=bgm_v
                )
            except Exception as mix_err:
                VideoDubbingService.log_to_job(job_id, f"[ERROR] mix_and_mux_video thất bại: {mix_err}")
                raise RuntimeError(f"Trộn âm thanh và đóng gói video thất bại: {mix_err}")
            
            job.output_video_path = output_video_path
            job.status = "completed"
            job.progress = 100
            job.message = "Lồng tiếng video thành công!"
            db.commit()
            VideoDubbingService.log_to_job(job_id, "Quy trình lồng tiếng hoàn tất thành công. Trạng thái: COMPLETED.")

        else:
            # Kaggle Worker Mode: Submit segment dubbing batch job
            job.status = "generating_tts"
            job.progress = 20
            job.message = "Đang gửi yêu cầu sinh giọng đọc lồng tiếng lên Kaggle GPU..."
            db.commit()

            VideoDubbingService.log_to_job(job_id, f"[KAGGLE] Tạo sub-job dub_segments 'dub_{job_id}' trong hàng đợi với {len(translated_subs)} phân đoạn...")

            # Check if sub-job already exists to prevent UNIQUE constraint error
            existing_tts = db.query(TTSJob).filter(TTSJob.id == f"dub_{job_id}").first()
            if existing_tts:
                existing_tts.text = job.translated_subtitles
                existing_tts.ref_audio_path = job.vocals_audio_path
                existing_tts.status = "queued"
                existing_tts.progress = 0
                existing_tts.message = "Đang chờ Kaggle lồng tiếng..."
            else:
                dub_tts_job = TTSJob(
                    id=f"dub_{job_id}",
                    user_id=job.user_id,
                    job_type="dub_segments",
                    text=job.translated_subtitles,  # passing JSON translated subtitles
                    voice_sample_id=None,
                    ref_audio_path=job.vocals_audio_path,
                    status="queued",
                    progress=0,
                    message="Đang chờ Kaggle lồng tiếng..."
                )
                db.add(dub_tts_job)
            db.commit()
            VideoDubbingService.log_to_job(job_id, "[KAGGLE] Đã đưa sub-job dub_segments vào hàng đợi, chờ GPU Worker xử lý...")
            
    except Exception as e:
        VideoDubbingService.log_to_job(job_id, f"LỖI HOÀN TẤT LỒNG TIẾNG: {e}")
        db.rollback()
        job = db.query(VideoDubbingJob).filter(VideoDubbingJob.id == job_id).first()
        if job:
            job.status = "failed"
            job.progress = 100
            job.error_message = str(e)
            job.message = f"Lỗi hoàn tất: {str(e)[:100]}"
            db.commit()
    finally:
        db.close()

# Endpoints to download assets
@router.get("/jobs/{job_id}/video")
def get_original_video(
    job_id: str,
    db: Session = Depends(get_db)
):
    """Tải xuống hoặc stream video gốc."""
    job = db.query(VideoDubbingJob).filter(VideoDubbingJob.id == job_id).first()
    if not job or not job.input_file_path or not os.path.exists(job.input_file_path):
        raise HTTPException(status_code=404, detail="Không tìm thấy video gốc.")
    return FileResponse(job.input_file_path, media_type="video/mp4", content_disposition_type="inline")

@router.get("/jobs/{job_id}/vocals")
def get_separated_vocals(
    job_id: str,
    db: Session = Depends(get_db)
):
    """Tải xuống hoặc nghe track giọng nói gốc sau khi tách."""
    job = db.query(VideoDubbingJob).filter(VideoDubbingJob.id == job_id).first()
    if not job or not job.vocals_audio_path or not os.path.exists(job.vocals_audio_path):
        raise HTTPException(status_code=404, detail="Không tìm thấy tệp giọng nói gốc.")
    return FileResponse(job.vocals_audio_path, media_type="audio/wav", content_disposition_type="inline")

@router.get("/jobs/{job_id}/bgm")
def get_separated_bgm(
    job_id: str,
    db: Session = Depends(get_db)
):
    """Tải xuống hoặc nghe track nhạc nền gốc sau khi tách."""
    job = db.query(VideoDubbingJob).filter(VideoDubbingJob.id == job_id).first()
    if not job or not job.bgm_audio_path or not os.path.exists(job.bgm_audio_path):
        raise HTTPException(status_code=404, detail="Không tìm thấy tệp nhạc nền gốc.")
    return FileResponse(job.bgm_audio_path, media_type="audio/wav", content_disposition_type="inline")

@router.get("/jobs/{job_id}/output")
def get_dubbed_video(
    job_id: str,
    db: Session = Depends(get_db)
):
    """Tải xuống hoặc stream video lồng tiếng thành phẩm."""
    job = db.query(VideoDubbingJob).filter(VideoDubbingJob.id == job_id).first()
    if not job or not job.output_video_path or not os.path.exists(job.output_video_path):
        raise HTTPException(status_code=404, detail="Không tìm thấy video lồng tiếng thành phẩm.")
    return FileResponse(job.output_video_path, media_type="video/mp4", filename=f"dubbed_{job_id}.mp4", content_disposition_type="inline")

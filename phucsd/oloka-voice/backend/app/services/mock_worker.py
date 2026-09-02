import os
import time
import math
import wave
import struct
import threading
from datetime import datetime
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import TTSJob, VoiceDesignPreview, VoiceSample
from app.config import settings
from app.services.audio_service import AudioService
from app.services.job_service import JobService

class MockWorker:
    _thread: threading.Thread = None
    _stop_event = threading.Event()

    @staticmethod
    def start():
        """Starts the Mock Worker polling loop in a background thread."""
        if MockWorker._thread is not None and MockWorker._thread.is_alive():
            return
        
        MockWorker._stop_event.clear()
        MockWorker._thread = threading.Thread(target=MockWorker._loop, daemon=True)
        MockWorker._thread.start()
        print("[MockWorker] Background mock worker thread started successfully.")

    @staticmethod
    def stop():
        """Stops the Mock Worker polling loop."""
        MockWorker._stop_event.set()
        if MockWorker._thread:
            MockWorker._thread.join(timeout=5)
            print("[MockWorker] Background mock worker thread stopped.")

    @staticmethod
    def _loop():
        """Polling loop running in the background thread."""
        while not MockWorker._stop_event.is_set():
            db = SessionLocal()
            try:
                # Poll oldest queued or starting_worker jobs
                job = db.query(TTSJob).filter(
                    TTSJob.status.in_(["queued", "starting_worker"])
                ).order_by(TTSJob.created_at.asc()).first()
                
                if job:
                    MockWorker._process_job(db, job)
            except Exception as e:
                print(f"[MockWorker] Error in loop: {e}")
            finally:
                db.close()
            
            # Poll every 2 seconds
            time.sleep(2)

    @staticmethod
    def _process_job(db: Session, job: TTSJob):
        """Simulates processing transitions and output writing for a single job."""
        job_id = job.id
        print(f"[MockWorker] Picked up job {job_id} of type {job.job_type}")
        
        # Check if job is separate_audio
        if job.job_type == "separate_audio":
            import shutil
            MockWorker._update_job(db, job_id, "separating_audio", "Đang chạy Demucs tách nhạc và lời (Giả lập)...", 50)
            time.sleep(2.0)
            
            dub_job_id = job_id.replace("sep_", "")
            from app.services.video_dubbing_service import VideoDubbingService
            VideoDubbingService.log_to_job(dub_job_id, "[MOCK WORKER] Bắt đầu tách nhạc giả lập...")

            job_dir = os.path.join(settings.dubbing_dir, dub_job_id)
            os.makedirs(job_dir, exist_ok=True)
            
            vocals_path = os.path.join(job_dir, "vocals.wav")
            bgm_path = os.path.join(job_dir, "bgm.wav")
            
            # Generate mock files
            if job.ref_audio_path and os.path.exists(job.ref_audio_path):
                shutil.copy2(job.ref_audio_path, vocals_path)
                shutil.copy2(job.ref_audio_path, bgm_path)
            else:
                MockWorker._generate_sine_wav(vocals_path, duration_sec=5.0)
                MockWorker._generate_sine_wav(bgm_path, duration_sec=5.0)
                
            from app.models import VideoDubbingJob
            dub_job = db.query(VideoDubbingJob).filter(VideoDubbingJob.id == dub_job_id).first()
            if dub_job:
                dub_job.vocals_audio_path = vocals_path
                dub_job.bgm_audio_path = bgm_path
                db.commit()
                
            VideoDubbingService.log_to_job(dub_job_id, "[MOCK WORKER] Tách nhạc hoàn tất. Kích hoạt Whisper ASR...")
            JobService.complete_job_output(db, job_id, vocals_path)
            
            from app.routers.video_dubbing import trigger_transcription_stage
            trigger_transcription_stage(dub_job_id, db)
            return

        # Check if job is dub_segments
        if job.job_type == "dub_segments":
            dub_job_id = job_id.replace("dub_", "")
            from app.services.video_dubbing_service import VideoDubbingService
            VideoDubbingService.log_to_job(dub_job_id, "[MOCK WORKER] Bắt đầu sinh giọng lồng tiếng từng phân đoạn (Giả lập)...")

            MockWorker._update_job(db, job_id, "generating_tts", "Đang sinh giọng lồng tiếng từng phân đoạn (Giả lập)...", 40)
            time.sleep(2.0)
            
            job_dir = os.path.join(settings.dubbing_dir, dub_job_id)
            segments_dir = os.path.join(job_dir, "segments")
            os.makedirs(segments_dir, exist_ok=True)
            
            import json
            import soundfile as sf
            from app.models import VideoDubbingJob
            
            dub_job = db.query(VideoDubbingJob).filter(VideoDubbingJob.id == dub_job_id).first()
            if not dub_job:
                JobService.update_job_status(db, job_id, "failed", "Không tìm thấy VideoDubbingJob", 100, "Missing parent job")
                return
                
            # Compile mock files for segments
            segments = json.loads(job.text or "[]")
            segments_payload = []
            for seg in segments:
                seg_wav_name = f"segment_{seg['id']}.wav"
                seg_wav_path = os.path.join(segments_dir, seg_wav_name)
                # Generate standard sine wav for segment duration
                dur = seg["end"] - seg["start"]
                MockWorker._generate_sine_wav(seg_wav_path, duration_sec=dur)
                segments_payload.append({
                    "start": seg["start"],
                    "file_path": seg_wav_path
                })
                
            VideoDubbingService.log_to_job(dub_job_id, "[MOCK WORKER] Sinh giọng hoàn tất. Bắt đầu trộn nhạc và đóng gói video...")
            MockWorker._update_job(db, job_id, "mixing_audio", "Đang lồng ghép giọng nói và nhạc nền (Giả lập)...", 70)
            time.sleep(1.0)
            
            # Load duration
            orig_info = sf.info(dub_job.original_audio_path)
            duration = orig_info.duration
            
            # Assemble vocal track
            dubbed_vocals_path = os.path.join(job_dir, "dubbed_vocals.wav")
            from app.services.video_dubbing_service import VideoDubbingService
            VideoDubbingService.assemble_dubbed_vocal(segments_payload, dubbed_vocals_path, duration)
            
            # Mux
            output_video_path = os.path.join(job_dir, "output_dubbed.mp4")
            VideoDubbingService.mix_and_mux_video(
                video_path=dub_job.input_file_path,
                bgm_path=dub_job.bgm_audio_path,
                vocal_path=dubbed_vocals_path,
                output_path=output_video_path
            )
            
            dub_job.output_video_path = output_video_path
            dub_job.status = "completed"
            dub_job.progress = 100
            dub_job.message = "Lồng tiếng video thành công!"
            db.commit()
            
            VideoDubbingService.log_to_job(dub_job_id, f"[MOCK WORKER] Trộn nhạc & đóng gói video thành công tại: {output_video_path}. Quy trình hoàn tất!")
            JobService.complete_job_output(db, job_id, output_video_path)
            return

        # Check if job is ASR
        if job.job_type == "asr":
            dub_job_id = job_id.replace("asr_", "")
            from app.services.video_dubbing_service import VideoDubbingService
            VideoDubbingService.log_to_job(dub_job_id, "[MOCK WORKER] Bắt đầu nhận dạng giọng nói ASR Whisper (giả lập)...")

            # Step 1: Loading Model (30%)
            MockWorker._update_job(db, job_id, "loading_model", "Đang tải mô hình ASR (Giả lập)...", 30)
            time.sleep(1.5)
            
            # Step 2: Transcribing (70%)
            MockWorker._update_job(db, job_id, "transcribing", "Đang nhận dạng giọng nói (Giả lập)...", 70)
            time.sleep(2.0)
            
            # Step 3: Complete
            try:
                mock_text = "Xin chào mọi người. Chào mừng các bạn đã đến với OmniVoice Gateway Playground."
                words = mock_text.split()
                
                # Mock word-level timestamps (Karaoke chunks)
                import json
                mock_chunks = []
                curr_time = 0.5
                for w in words:
                    # clean word
                    clean_w = w.strip(".,!?\"'")
                    dur = 0.35 + (0.05 * (len(clean_w) % 3))
                    mock_chunks.append({
                        "word": clean_w,
                        "start": round(curr_time, 2),
                        "end": round(curr_time + dur, 2)
                    })
                    curr_time += dur + 0.08
                
                alignment_str = json.dumps(mock_chunks)
                VideoDubbingService.log_to_job(dub_job_id, "[MOCK WORKER] Nhận dạng giọng nói ASR thành công.")
                JobService.complete_asr_job(db, job_id, mock_text, alignment=alignment_str)
                print(f"[MockWorker] ASR job {job_id} completed successfully. Text: {mock_text}")
                
                # Video Dubbing ASR callback integration
                if job_id.startswith("asr_"):
                    from app.routers.video_dubbing import trigger_translation_stage
                    trigger_translation_stage(dub_job_id, mock_text, alignment_str, db)
            except Exception as e:
                error_msg = f"Mock ASR processing failed: {e}"
                VideoDubbingService.log_to_job(dub_job_id, f"[MOCK WORKER] LỖI ASR: {error_msg}")
                JobService.update_job_status(db, job_id, "failed", "Lỗi nhận dạng âm thanh giả lập", 100, error_msg)
                print(f"[MockWorker] ASR job {job_id} failed: {error_msg}")
            return

        # Step 1: Preparing Input / Booting Worker (10%)
        MockWorker._update_job(db, job_id, "booting_kaggle", "Đang khởi động Kaggle Worker (Giả lập)...", 10)
        time.sleep(1.5)
        
        # Step 2: Loading Model (30%)
        MockWorker._update_job(db, job_id, "loading_model", "Đang tải mô hình OmniVoice (Giả lập)...", 30)
        time.sleep(1.5)
        
        # Step 3: Generating/Cloning Audio (60%)
        msg = "Đang clone giọng nói..." if job.job_type == "clone_voice" else "Đang thiết kế giọng và tạo bản nghe thử..."
        MockWorker._update_job(db, job_id, "generating_audio", msg, 60)
        time.sleep(2.0)
        
        # Step 4: Exporting WAV (90%)
        MockWorker._update_job(db, job_id, "exporting_wav", "Đang kết xuất tệp WAV...", 90)
        time.sleep(1.0)
        
        # Step 5: Completed
        # Prepare output filename and path
        AudioService.ensure_directories()
        
        if job.job_type == "voice_design_preview" and job.preview_id:
            output_path = os.path.abspath(os.path.join(settings.previews_dir, f"{job.preview_id}.wav"))
        else:
            output_path = os.path.abspath(os.path.join(settings.outputs_dir, f"{job_id}.wav"))
            
        try:
            duration_sec = 3.0
            if job.duration and job.duration > 0:
                duration_sec = job.duration
            elif job.speed and job.speed > 0:
                duration_sec = max(0.5, 3.0 / job.speed)

            import json
            MockWorker._generate_sine_wav(output_path, duration_sec=duration_sec)
            
            alignment_str = None
            if job.with_alignment:
                words = (job.text or "").split()
                if words:
                    word_dur = duration_sec / len(words)
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

            # Register success using JobService
            JobService.complete_job_output(db, job_id, output_path, alignment=alignment_str)
            print(f"[MockWorker] Job {job_id} completed successfully. Audio saved to {output_path} ({duration_sec:.1f}s)")
        except Exception as e:
            error_msg = f"Mock audio generation failed: {e}"
            JobService.update_job_status(db, job_id, "failed", "Lỗi xử lý âm thanh giả lập", 100, error_msg)
            print(f"[MockWorker] Job {job_id} failed: {error_msg}")

    @staticmethod
    def _update_job(db: Session, job_id: str, status: str, message: str, progress: int):
        """Helper to update a job state in a thread-safe manner."""
        # Query again to avoid detached session issues
        JobService.update_job_status(db, job_id, status, message, progress)

    @staticmethod
    def _generate_sine_wav(filepath: str, duration_sec: float = 3.0, sample_rate: int = 24000):
        """Generates a valid playable mono 24000Hz WAV file with a pleasant soft beep."""
        with wave.open(filepath, "wb") as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)   # 16-bit
            wav_file.setframerate(sample_rate)
            
            num_frames = int(duration_sec * sample_rate)
            # Create a 330Hz sine wave (soft tone E4)
            frequency = 330.0
            
            for i in range(num_frames):
                # Apply envelope to prevent clicking (fade-in & fade-out)
                envelope = 1.0
                if i < 2000:
                    envelope = float(i) / 2000.0  # fade-in
                elif i > num_frames - 2000:
                    envelope = float(num_frames - i) / 2000.0  # fade-out
                
                t = float(i) / float(sample_rate)
                # Compute sine value
                val = int(24000.0 * envelope * math.sin(2.0 * math.pi * frequency * t))
                # Pack as 16-bit little endian signed integer
                data = struct.pack("<h", val)
                wav_file.writeframesraw(data)

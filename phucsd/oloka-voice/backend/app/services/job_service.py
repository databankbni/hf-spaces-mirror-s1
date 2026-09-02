import os
import shutil
import soundfile as sf
from typing import Optional, List
from sqlalchemy.orm import Session
from datetime import datetime
from app.models import TTSJob, VoiceDesignPreview, VoiceSample
from app.utils.ids import generate_id
from app.config import settings
import threading
from sqlalchemy import or_, and_
from app.services.kaggle_orchestrator import KaggleOrchestrator

_job_allocation_lock = threading.Lock()

class JobService:
    @staticmethod
    def map_vietnamese_request_to_instruct(voice_request: str) -> str:
        """
        Maps a Vietnamese voice design description into valid OmniVoice English instruct tags.
        If the input is already an English instruct sequence (e.g. comma-separated tags), it is preserved.
        """
        req_lower = voice_request.lower().strip()
        
        # 1. If it doesn't contain Vietnamese diacritics and matches typical English keywords, pass it through directly
        vietnamese_chars = "àáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệđìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵ"
        has_vietnamese = any(c in vietnamese_chars for c in req_lower)
        
        english_keywords = ["male", "female", "child", "young", "adult", "middle", "elderly", "pitch", "whisper", "accent", "laughter", "giggle"]
        has_english_keyword = any(kw in req_lower for kw in english_keywords)
        
        if not has_vietnamese and (has_english_keyword or "," in req_lower):
            # Clean and return the comma-separated English instruct tags
            parts = [p.strip() for p in voice_request.split(",") if p.strip()]
            if parts:
                return ", ".join(parts)
            return req_lower

        # 2. Otherwise, map Vietnamese description to standard English instruct tags
        instructs = []

        # Gender
        if "nữ" in req_lower:
            instructs.append("female")
        elif "nam" in req_lower:
            instructs.append("male")

        # Age group
        if "trẻ em" in req_lower or "con nít" in req_lower or "bé" in req_lower:
            instructs.append("child")
        elif "thiếu niên" in req_lower:
            instructs.append("teenager")
        elif "trẻ" in req_lower or "thanh niên" in req_lower:
            instructs.append("young adult")
        elif "trung niên" in req_lower:
            instructs.append("middle-aged")
        elif "già" in req_lower or "lớn tuổi" in req_lower or "lão" in req_lower:
            instructs.append("elderly")

        # Pitch/Tone
        if "trầm" in req_lower or "thấp" in req_lower:
            instructs.append("low pitch")
        elif "cao" in req_lower:
            instructs.append("high pitch")
        elif "vừa" in req_lower or "bình thường" in req_lower:
            instructs.append("moderate pitch")

        # Style
        if "thì thầm" in req_lower or "nhẹ nhàng" in req_lower or "nói nhỏ" in req_lower:
            instructs.append("whisper")
        if "cười" in req_lower:
            instructs.append("laughter")

        # Accents
        if "giọng mỹ" in req_lower or "tiếng mỹ" in req_lower or "accent mỹ" in req_lower:
            instructs.append("american accent")
        elif "giọng anh" in req_lower or "tiếng anh" in req_lower or "accent anh" in req_lower:
            instructs.append("british accent")
        elif "giọng ấn" in req_lower or "accent ấn" in req_lower:
            instructs.append("indian accent")

        # Fallback defaults if empty
        if not instructs:
            instructs = ["female", "young adult"]

        return ", ".join(instructs)

    @staticmethod
    def create_voice_design_preview(
        db: Session,
        voice_request: str,
        preview_text: str,
        public_api_url: str = None,
        speed: float = 1.0,
        num_step: int = 32,
        user_id: str = None,
        denoise: bool = True,
        guidance_scale: float = 2.0,
        t_shift: float = 0.1,
        position_temperature: float = 5.0,
        class_temperature: float = 0.0,
        layer_penalty_factor: float = 5.0,
        duration: float = None,
        preprocess_prompt: bool = True,
        postprocess_output: bool = True,
        audio_chunk_duration: float = 15.0,
        audio_chunk_threshold: float = 30.0,
        language: str = None,
        pad_duration: float = None,
        fade_duration: float = None
    ) -> tuple[VoiceDesignPreview, TTSJob]:
        """Creates a VoiceDesignPreview entry and triggers a background preview TTS job."""
        preview_id = generate_id("vd")
        job_id = generate_id("job")
        
        instruct = JobService.map_vietnamese_request_to_instruct(voice_request)

        # Create VoiceDesignPreview
        db_preview = VoiceDesignPreview(
            id=preview_id,
            user_id=user_id,
            voice_request=voice_request,
            instruct=instruct,
            preview_text=preview_text,
            status="queued"
        )
        db.add(db_preview)

        # Create TTSJob
        db_job = TTSJob(
            id=job_id,
            user_id=user_id,
            job_type="voice_design_preview",
            text=preview_text,
            preview_id=preview_id,
            instruct=instruct,
            speed=speed,
            num_step=num_step,
            denoise=denoise,
            guidance_scale=guidance_scale,
            t_shift=t_shift,
            position_temperature=position_temperature,
            class_temperature=class_temperature,
            layer_penalty_factor=layer_penalty_factor,
            duration=duration,
            preprocess_prompt=preprocess_prompt,
            postprocess_output=postprocess_output,
            audio_chunk_duration=audio_chunk_duration,
            audio_chunk_threshold=audio_chunk_threshold,
            language=language,
            pad_duration=pad_duration,
            fade_duration=fade_duration,
            status="queued",
            message="Đã nhận yêu cầu thiết kế giọng."
        )
        db.add(db_job)
        db.commit()
        db.refresh(db_preview)
        db.refresh(db_job)

        return db_preview, db_job

    @staticmethod
    def create_tts_job(
        db: Session,
        mode: str,
        text: str,
        voice_sample_id: str = None,
        instruct: str = None,
        public_api_url: str = None,
        speed: float = 1.0,
        num_step: int = 32,
        user_id: str = None,
        denoise: bool = True,
        guidance_scale: float = 2.0,
        t_shift: float = 0.1,
        position_temperature: float = 5.0,
        class_temperature: float = 0.0,
        layer_penalty_factor: float = 5.0,
        duration: float = None,
        preprocess_prompt: bool = True,
        postprocess_output: bool = True,
        audio_chunk_duration: float = 15.0,
        audio_chunk_threshold: float = 30.0,
        ref_text: str = None,
        with_alignment: bool = False,
        language: str = None,
        pad_duration: float = None,
        fade_duration: float = None
    ) -> TTSJob:
        """Creates a TTS job based on the chosen mode (clone_voice, auto_voice, voice_design)."""
        job_id = generate_id("job")
        
        ref_audio_path = None
        ref_text_val = None
        job_type = mode

        if mode == "clone_voice":
            if not voice_sample_id:
                raise ValueError("voice_sample_id là bắt buộc trong mode clone_voice")
            
            sample = db.query(VoiceSample).filter(VoiceSample.id == voice_sample_id).first()
            if not sample:
                raise ValueError(f"Không tìm thấy Voice Sample với ID {voice_sample_id}")
            
            ref_audio_path = sample.file_path
            ref_text_val = ref_text if ref_text is not None else sample.ref_text
        elif mode == "auto_voice":
            job_type = "auto_voice"
        elif mode == "voice_design":
            job_type = "voice_design_tts"
            if not instruct:
                instruct = "female, young adult"
        else:
            raise ValueError(f"Chế độ TTS không hợp lệ: {mode}")

        db_job = TTSJob(
            id=job_id,
            user_id=user_id,
            job_type=job_type,
            text=text,
            voice_sample_id=voice_sample_id,
            instruct=instruct,
            ref_audio_path=ref_audio_path,
            ref_text=ref_text_val,
            speed=speed,
            num_step=num_step,
            denoise=denoise,
            guidance_scale=guidance_scale,
            t_shift=t_shift,
            position_temperature=position_temperature,
            class_temperature=class_temperature,
            layer_penalty_factor=layer_penalty_factor,
            duration=duration,
            preprocess_prompt=preprocess_prompt,
            postprocess_output=postprocess_output,
            audio_chunk_duration=audio_chunk_duration,
            audio_chunk_threshold=audio_chunk_threshold,
            with_alignment=with_alignment,
            language=language,
            pad_duration=pad_duration,
            fade_duration=fade_duration,
            status="queued",
            message="Đã nhận yêu cầu. Đang chuẩn bị đầu vào..."
        )
        db.add(db_job)
        db.commit()
        db.refresh(db_job)

        return db_job

    @staticmethod
    def get_next_job(db: Session, worker_id: str, user_id: str = None) -> Optional[TTSJob]:
        """Locks the oldest queued job for the requested worker and updates status to preparing_input."""
        with _job_allocation_lock:
            # Find jobs that are:
            # - General queued (no worker_id/starting restriction) OR
            # - Assigned to this specific worker during its booting state
            query = db.query(TTSJob).filter(
                or_(
                    TTSJob.status == "queued",
                    and_(
                        TTSJob.status.in_(["starting_worker", "queued_kaggle"]),
                        TTSJob.worker_id == worker_id
                    )
                )
            )
            if user_id:
                query = query.filter(TTSJob.user_id == user_id)
                
            job = query.order_by(TTSJob.created_at.asc()).first()

            if not job:
                return None

            # Lock the job
            job.status = "preparing_input"
            job.worker_id = worker_id
            job.message = "Đang chuẩn bị dữ liệu đầu vào trên Worker..."
            job.started_at = datetime.utcnow()
            db.commit()
            db.refresh(job)
            return job

    @staticmethod
    def update_job_status(db: Session, job_id: str, status: str, message: str = None, progress: int = 0, error_message: str = None) -> TTSJob:
        """Updates a job's status parameters, synchronizing it with previews if applicable."""
        job = db.query(TTSJob).filter(TTSJob.id == job_id).first()
        if not job:
            raise ValueError(f"Không tìm thấy Job {job_id}")

        job.status = status
        if message:
            job.message = message
        job.progress = progress
        if error_message:
            job.error_message = error_message
        
        if status in ["completed", "failed"]:
            job.completed_at = datetime.utcnow()
        
        # Sync preview status if it's a preview job
        if job.job_type == "voice_design_preview" and job.preview_id:
            preview = db.query(VoiceDesignPreview).filter(VoiceDesignPreview.id == job.preview_id).first()
            if preview:
                if status == "failed":
                    preview.status = "failed"
                elif status == "completed":
                    preview.status = "completed"
                else:
                    preview.status = "processing"

        db.commit()
        db.refresh(job)
        return job

    @staticmethod
    def complete_job_output(db: Session, job_id: str, local_output_path: str, alignment: Optional[str] = None) -> TTSJob:
        """Completes a job, persists output paths, and handles target conversions."""
        job = db.query(TTSJob).filter(TTSJob.id == job_id).first()
        if not job:
            raise ValueError(f"Không tìm thấy Job {job_id}")

        # Update job fields
        job.status = "completed"
        job.message = "Hoàn tất"
        job.progress = 100
        job.output_audio_path = local_output_path
        if alignment:
            job.alignment = alignment
        
        job.completed_at = datetime.utcnow()

        # Upload audio to S3 CDN Storage for instant playback
        try:
            from app.services.s3_storage_service import s3_storage_service
            filename = f"{job_id}.wav"
            if local_output_path.endswith(".mp3"):
                filename = f"{job_id}.mp3"
            cdn_url = s3_storage_service.upload_audio_to_s3_cdn(local_output_path, filename)
            if cdn_url:
                job.cdn_audio_url = cdn_url
        except Exception as upload_err:
            print(f"[JobService] S3 CDN upload warning: {upload_err}")
        
        # Sync and copy to preview if it's a voice design preview
        if job.job_type == "voice_design_preview" and job.preview_id:
            preview = db.query(VoiceDesignPreview).filter(VoiceDesignPreview.id == job.preview_id).first()
            if preview:
                preview.status = "completed"
                preview.preview_audio_path = local_output_path
        
        db.commit()
        db.refresh(job)
        return job

    @staticmethod
    def accept_preview(db: Session, preview_id: str, user_id: str = None) -> VoiceSample:
        """Takes a completed preview audio and registers it as a reusable cloned VoiceSample."""
        preview = db.query(VoiceDesignPreview).filter(VoiceDesignPreview.id == preview_id).first()
        if not preview:
            raise ValueError(f"Không tìm thấy Voice Design Preview {preview_id}")

        if preview.status != "completed" or not preview.preview_audio_path or not os.path.exists(preview.preview_audio_path):
            raise ValueError(f"Bản nghe thử {preview_id} chưa sẵn sàng hoặc không tồn tại audio file.")

        # Create new VoiceSample ID
        sample_id = f"vs_from_{preview_id}"
        
        # Determine paths
        AudioService.ensure_directories()
        dest_filename = f"{sample_id}.wav"
        dest_path = os.path.join(settings.voice_samples_dir, dest_filename)

        # Copy WAV file to voice_samples folder
        shutil.copy2(preview.preview_audio_path, dest_path)

        # Read metadata using soundfile if possible
        duration = None
        sample_rate = None
        try:
            info = sf.info(dest_path)
            duration = info.duration
            sample_rate = info.samplerate
        except Exception:
            duration = 5.0
            sample_rate = 24000

        # Save voice sample entry
        sample = VoiceSample(
            id=sample_id,
            user_id=user_id or preview.user_id,
            source_type="voice_design_preview",
            file_path=dest_path,
            ref_text=preview.preview_text,
            duration=duration,
            sample_rate=sample_rate,
            status="ready"
        )
        
        db.add(sample)
        preview.accepted_sample_id = sample_id
        db.commit()
        
        db.refresh(sample)
        db.refresh(preview)
        
        return sample

    @staticmethod
    def create_asr_job(db: Session, ref_audio_path: str, user_id: str = None) -> TTSJob:
        """Creates an ASR (Speech-to-Text) job in queued state."""
        job_id = generate_id("job")
        
        db_job = TTSJob(
            id=job_id,
            user_id=user_id,
            job_type="asr",
            ref_audio_path=ref_audio_path,
            status="queued",
            message="Đã nhận yêu cầu ASR. Đang chờ Worker..."
        )
        db.add(db_job)
        db.commit()
        db.refresh(db_job)

        # Trigger Kaggle orchestrator to ensure notebook is running
        try:
            KaggleOrchestrator.ensure_worker_running(db)
        except Exception as e:
            print(f"[JobService] Warning triggering worker: {e}")

        return db_job

    @staticmethod
    def complete_asr_job(db: Session, job_id: str, text: str, alignment: Optional[str] = None, duration: Optional[float] = None) -> TTSJob:
        """Completes an ASR (Speech-to-Text) job, saving the transcribed text and word chunks."""
        job = db.query(TTSJob).filter(TTSJob.id == job_id).first()
        if not job:
            raise ValueError(f"Không tìm thấy Job {job_id}")

        job.status = "completed"
        job.message = "Hoàn tất nhận dạng giọng nói"
        job.progress = 100
        job.text = text
        job.completed_at = datetime.utcnow()
        if duration is not None:
            job.duration = duration
        
        # Save alignment as JSON string if not already
        import json
        if alignment:
            try:
                # Ensure it is valid JSON
                if isinstance(alignment, str):
                    json.loads(alignment)
                    job.alignment = alignment
            except Exception:
                pass
        
        db.commit()
        db.refresh(job)
        return job

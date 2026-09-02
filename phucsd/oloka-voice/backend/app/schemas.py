from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Optional, Any, List
from datetime import datetime
import json as _json

class HealthResponse(BaseModel):
    status: str
    app: str

class VoiceSampleUploadResponse(BaseModel):
    voice_sample_id: str
    status: str
    message: str

class VoiceSampleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    source_type: str
    ref_text: Optional[str] = None
    duration: Optional[float] = None
    sample_rate: Optional[int] = None
    status: str
    created_at: datetime
    name: Optional[str] = None
    is_public: bool = False
    source_job_id: Optional[str] = None
    tags: Optional[list[str]] = None
    source_job_data: Optional[dict[str, Any]] = None

    @field_validator("tags", mode="before")
    @classmethod
    def parse_tags(cls, v: Any) -> Any:
        if isinstance(v, str):
            try:
                return _json.loads(v)
            except Exception:
                return None
        return v

    @field_validator("source_job_data", mode="before")
    @classmethod
    def parse_source_job_data(cls, v: Any) -> Any:
        if isinstance(v, str):
            try:
                return _json.loads(v)
            except Exception:
                return None
        return v

class SaveFavoriteVoiceRequest(BaseModel):
    job_id: Optional[str] = None
    preview_id: Optional[str] = None
    name: str = Field(..., max_length=100)
    is_public: bool = False
    ref_text: str
    custom_id: Optional[str] = Field(None, max_length=50)
    tags: Optional[list[str]] = None


class VoiceSampleUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    tags: Optional[list[str]] = None
    ref_text: Optional[str] = None
    is_public: Optional[bool] = None

class VoiceLibraryItemResponse(BaseModel):
    id: str
    name: Optional[str] = None
    tags: Optional[list[str]] = None
    ref_text: Optional[str] = None
    duration: Optional[float] = None
    is_public: bool = True
    preview_url: str
    source_job_data: Optional[dict[str, Any]] = None
    created_at: datetime


class VoiceDesignPreviewCreate(BaseModel):
    voice_request: str
    preview_text: str
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

class VoiceDesignPreviewResponse(BaseModel):
    preview_id: str
    job_id: str
    status: str
    message: str

class VoiceDesignPreviewDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    voice_request: str
    instruct: str
    preview_text: str
    preview_audio_path: Optional[str] = None
    accepted_sample_id: Optional[str] = None
    status: str
    created_at: datetime

class AcceptPreviewResponse(BaseModel):
    voice_sample_id: str
    status: str
    message: str

class TTSJobCreate(BaseModel):
    mode: str  # "clone_voice" | "auto_voice" | "voice_design"
    text: str
    voice_sample_id: Optional[str] = None
    ref_text: Optional[str] = None
    instruct: Optional[str] = None
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
    with_alignment: Optional[bool] = Field(False, description="Yêu cầu xuất kèm mốc thời gian (alignment) từng từ để làm phụ đề.")
    language: Optional[str] = None
    pad_duration: Optional[float] = None
    fade_duration: Optional[float] = None

class TTSJobResponse(BaseModel):
    job_id: str
    status: str
    message: str

class BatchJobStatusRequest(BaseModel):
    job_ids: List[str] = Field(..., description="Danh sách các mã job_id cần lấy trạng thái")

class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    message: Optional[str] = None
    progress: int
    audio_url: Optional[str] = None
    cdn_audio_url: Optional[str] = None
    error_message: Optional[str] = None
    worker_id: Optional[str] = None
    job_type: Optional[str] = None
    text: Optional[str] = None
    created_at: Optional[datetime] = None
    alignment: Optional[Any] = Field(None, description="Danh sách mốc thời gian khớp từ tương ứng dạng JSON array [{\"word\": \"...\", \"start\": 0.0, \"end\": 0.5}] (Chỉ có khi with_alignment=True)")
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    processing_time: Optional[float] = None
    queue_time: Optional[float] = None
    total_time: Optional[float] = None
    params: Optional[dict[str, Any]] = None

class PaginatedJobsResponse(BaseModel):
    items: List[JobStatusResponse]
    total: int
    page: int
    page_size: int
    total_pages: int

# Worker related schemas
class WorkerRegisterRequest(BaseModel):
    worker_id: str
    status: str
    message: Optional[str] = None

class WorkerHeartbeatRequest(BaseModel):
    worker_id: str
    status: str
    current_job_id: Optional[str] = None
    message: Optional[str] = None

class WorkerShutdownRequest(BaseModel):
    worker_id: str
    reason: str

class WorkerJobStatusUpdateRequest(BaseModel):
    status: str
    message: Optional[str] = None
    progress: int = 0
    error_message: Optional[str] = None

class WorkerASRResultRequest(BaseModel):
    text: str
    alignment: Optional[Any] = None
    duration: Optional[float] = None

class WorkerJobPayload(BaseModel):
    job_id: str
    job_type: str
    text: Optional[str] = None
    instruct: Optional[str] = None
    ref_audio_url: Optional[str] = None
    ref_text: Optional[str] = None
    output_kind: str  # "preview" or "tts"
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
    with_alignment: Optional[bool] = Field(False, description="Yêu cầu worker trích xuất và tải lên mốc thời gian (alignment) từng từ.")

class WorkerNextJobResponse(BaseModel):
    job: Optional[WorkerJobPayload] = None
    message: str


class SubtitleSegment(BaseModel):
    id: int
    start: float
    end: float
    text: str

class VideoDubbingJobResponse(BaseModel):
    id: str
    status: str
    progress: int
    message: Optional[str] = None
    source_type: str
    source_url: Optional[str] = None
    target_language: str
    llm_profile_id: Optional[str] = None
    original_subtitles: Optional[List[SubtitleSegment]] = None
    translated_subtitles: Optional[List[SubtitleSegment]] = None
    vocals_audio_path: Optional[str] = None
    bgm_audio_path: Optional[str] = None
    vocals_volume: Optional[float] = 1.0
    bgm_volume: Optional[float] = 0.4
    output_video_url: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

class LLMProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    provider: str
    api_key: Optional[str] = None
    model: str
    custom_endpoint: Optional[str] = None
    thinking_effort: str
    is_active: bool
    last_test_status: str
    last_test_message: Optional[str] = None
    last_tested_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

class LLMProfileCreateRequest(BaseModel):
    name: str
    provider: str = "gemini"
    api_key: Optional[str] = ""
    model: str = "gemini-2.5-flash"
    custom_endpoint: Optional[str] = ""
    thinking_effort: str = "none"
    is_active: bool = False

class LLMProfileUpdateRequest(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    custom_endpoint: Optional[str] = None
    thinking_effort: Optional[str] = None
    is_active: Optional[bool] = None

class TestLLMProfileResponse(BaseModel):
    status: str
    message: str
    latency_ms: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)

class SubtitleUpdateRequest(BaseModel):
    original_subtitles: Optional[List[SubtitleSegment]] = None
    translated_subtitles: Optional[List[SubtitleSegment]] = None

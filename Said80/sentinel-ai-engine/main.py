"""
AI Detector - Python ML Server
Serves all ML models via FastAPI:
  POST /predict/ar    — Arabic text detection (AraBERT)
  POST /predict/en    — English text detection (DistilBERT)
  POST /predict/image — Image detection (EfficientNet-B0)
  POST /predict/audio — Audio detection (Wav2Vec2 + torchaudio)

Audio requirements:
  - Accepts .wav / .mp3
  - Converts to mono, 16000 Hz
  - Splits into ≤3-second chunks
  - Runs inference on each chunk, averages probabilities
"""

import os
import io
import math
import tempfile
import logging
import subprocess
from contextlib import asynccontextmanager

import cv2
import imageio_ffmpeg
import torch
import torch.nn as nn
import torchaudio
import torchaudio.models as torchaudio_models
import torchvision.models as torchvision_models
from torchvision import transforms
from PIL import Image
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

from huggingface_hub import hf_hub_download, snapshot_download

# ─── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

AR_MODEL_PATH  = os.path.join(BASE_DIR, "final_arabert_ai_detector/content/drive/MyDrive/final_arabert_ai_detector")
EN_MODEL_PATH  = os.path.join(BASE_DIR, "english_model_final/content/english_model_final")
IMG_MODEL_PATH = os.path.join(BASE_DIR, "image_model_final_v1.pt")
AUD_MODEL_PATH = os.path.join(BASE_DIR, "best_asv_model.pt")

# ─── Constants ─────────────────────────────────────────────────────────────────
TARGET_SR       = 16000          # Target sample rate (Hz)
CHUNK_SEC       = 3              # Max chunk length in seconds
CHUNK_SAMPLES   = TARGET_SR * CHUNK_SEC   # 48 000 samples

# ─── Audio model definition ────────────────────────────────────────────────────
class AudioSpoofDetector(nn.Module):
    """
    Wav2Vec2-base (torchaudio) + 2-layer classifier head.
    Trained on ASVspoof dataset: index 0 = bonafide/real, index 1 = spoof/AI.
    """
    def __init__(self):
        super().__init__()
        self.wav2vec = torchaudio_models.wav2vec2_base()
        self.classifier = nn.Sequential(
            nn.Linear(768, 128),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(128, 2),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: [batch, num_samples]
        features, _ = self.wav2vec(x)      # [batch, seq_len, 768]
        pooled = features.mean(dim=1)       # [batch, 768]
        return self.classifier(pooled)      # [batch, 2]


# ─── Model holders (loaded once at startup) ────────────────────────────────────
models_store: dict = {}


def download_models_from_hub():
    repo_id = "Said80/sentinel-ai-models"
    
    # 1. Download Audio Model
    if not os.path.exists(AUD_MODEL_PATH):
        log.info("Downloading Audio Model from HF Hub...")
        hf_hub_download(repo_id=repo_id, filename="best_asv_model.pt", local_dir=BASE_DIR)
        
    # 2. Download Image Model
    if not os.path.exists(IMG_MODEL_PATH):
        log.info("Downloading Image Model from HF Hub...")
        hf_hub_download(repo_id=repo_id, filename="image_model_final_v1.pt", local_dir=BASE_DIR)
        
    # 3. Download English Text Model files
    log.info("Checking English text model files...")
    snapshot_download(
        repo_id=repo_id,
        allow_patterns=["english_model_final/**/*"],
        local_dir=BASE_DIR
    )
    
    # 4. Download Arabic Text Model files
    log.info("Checking Arabic text model files...")
    snapshot_download(
        repo_id=repo_id,
        allow_patterns=["final_arabert_ai_detector/**/*"],
        local_dir=BASE_DIR
    )


def load_all_models():
    # Ensure models are downloaded locally first
    try:
        download_models_from_hub()
    except Exception as e:
        log.error(f"Failed to download models from Hugging Face Hub: {e}")
        log.info("Attempting to load models from local disk...")

    log.info("Loading Arabic text model …")
    ar_tokenizer = AutoTokenizer.from_pretrained(AR_MODEL_PATH)
    ar_model = AutoModelForSequenceClassification.from_pretrained(AR_MODEL_PATH)
    ar_model.eval()
    models_store["ar_tokenizer"] = ar_tokenizer
    models_store["ar_model"]     = ar_model
    log.info("Arabic model ready ✓")

    log.info("Loading English text model …")
    en_tokenizer = AutoTokenizer.from_pretrained(EN_MODEL_PATH)
    en_model = AutoModelForSequenceClassification.from_pretrained(EN_MODEL_PATH)
    en_model.eval()
    models_store["en_tokenizer"] = en_tokenizer
    models_store["en_model"]     = en_model
    log.info("English model ready ✓")

    log.info("Loading image model …")
    image_data = torch.load(IMG_MODEL_PATH, map_location="cpu", weights_only=False)
    img_model = torchvision_models.efficientnet_b0(num_classes=2)
    img_model.load_state_dict(image_data["model_state_dict"])
    img_model.eval()
    models_store["img_model"]       = img_model
    models_store["img_class_names"] = image_data.get("class_names", ["FAKE", "REAL"])
    log.info("Image model ready ✓ | classes: %s", models_store["img_class_names"])

    log.info("Loading audio model …")
    audio_model = AudioSpoofDetector()
    audio_state = torch.load(AUD_MODEL_PATH, map_location="cpu", weights_only=False)
    audio_model.load_state_dict(audio_state)
    audio_model.eval()
    models_store["audio_model"] = audio_model
    log.info("Audio model ready ✓")


# ─── Image transform ───────────────────────────────────────────────────────────
IMAGE_TRANSFORM = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std=[0.229, 0.224, 0.225]),
])


# ─── App lifecycle ─────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    load_all_models()
    yield
    models_store.clear()

app = FastAPI(title="AI Detector ML Server", version="1.0.0", lifespan=lifespan)


# ─── Schemas ───────────────────────────────────────────────────────────────────
class TextRequest(BaseModel):
    text: str


class DetectionResponse(BaseModel):
    is_ai: bool
    ai_probability: float
    confidence: float
    language: str = ""
    details: str  = ""


# ─── Helpers ───────────────────────────────────────────────────────────────────
def _extract_frames_in_memory(video_path: str, max_frames: int = 5) -> list:
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        cap.release()
        return []
    
    # Calculate step size to select max_frames evenly
    step = max(1, total_frames // max_frames)
    frames = []
    
    for i in range(max_frames):
        frame_idx = i * step
        if frame_idx >= total_frames:
            break
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        success, frame = cap.read()
        if not success:
            break
        # Convert BGR (OpenCV) to RGB (PIL)
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb_frame)
        frames.append(pil_img)
        
    cap.release()
    return frames


def _extract_audio_from_video(video_path: str, output_audio_path: str):
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg_exe,
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        output_audio_path,
        "-y"
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)


def _text_predict(text: str, model, tokenizer, ai_index: int, language: str) -> DetectionResponse:
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
    with torch.no_grad():
        logits = model(**inputs).logits
    probs = torch.softmax(logits, dim=-1)[0]
    ai_prob     = float(probs[ai_index])
    is_ai       = ai_prob >= 0.5
    confidence  = float(probs.max())
    return DetectionResponse(
        is_ai=is_ai,
        ai_probability=round(ai_prob, 4),
        confidence=round(confidence, 4),
        language=language,
        details=f"Analyzed with {language.upper()} model.",
    )


def _load_audio_mono_16k(data: bytes, suffix: str) -> torch.Tensor:
    """
    Load raw audio bytes → mono float32 waveform at 16 000 Hz.
    Uses soundfile, pydub, or torchaudio for maximum compatibility.
    Returns tensor of shape [num_samples].
    """
    # Configure pydub converter to use imageio_ffmpeg
    try:
        from pydub import AudioSegment
        import imageio_ffmpeg
        AudioSegment.converter = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        log.warning(f"Could not configure pydub ffmpeg path: {e}")

    waveform = None
    sr = None
    ext = suffix.lower() if suffix else ""

    # 1. Try soundfile (best for WAV/FLAC, avoids torchaudio backend bugs)
    if ext in [".wav", ".flac"]:
        try:
            import soundfile as sf
            data_np, sr = sf.read(io.BytesIO(data))
            waveform = torch.tensor(data_np, dtype=torch.float32)
            if len(waveform.shape) > 1:
                # Average multi-channel audio to mono
                waveform = waveform.mean(dim=-1)
            log.info(f"Successfully loaded {ext} with soundfile: shape={waveform.shape}, sr={sr}")
        except Exception as e:
            log.warning(f"soundfile failed to load WAV: {e}. Trying other backends.")

    # 2. Try pydub (handles MP3, webm, and wav if soundfile fails)
    if waveform is None:
        try:
            from pydub import AudioSegment
            fmt = ext.replace(".", "") if ext else None
            audio_seg = AudioSegment.from_file(io.BytesIO(data), format=fmt)
            audio_seg = audio_seg.set_frame_rate(TARGET_SR).set_channels(1)
            raw = audio_seg.raw_data
            waveform = torch.frombuffer(raw, dtype=torch.int16).float() / 32768.0
            sr = TARGET_SR
            log.info(f"Successfully loaded audio with pydub: shape={waveform.shape}, sr={sr}")
        except Exception as e:
            log.warning(f"pydub failed to load: {e}. Trying torchaudio.")

    # 3. Final fallback: torchaudio native load
    if waveform is None:
        try:
            buf = io.BytesIO(data)
            waveform, sr = torchaudio.load(buf)
            if waveform.shape[0] > 1:
                waveform = waveform.mean(dim=0, keepdim=True)
            waveform = waveform.squeeze(0)
            log.info(f"Successfully loaded audio with torchaudio: shape={waveform.shape}, sr={sr}")
        except Exception as e:
            log.error(f"All audio loading backends failed: {e}")
            raise HTTPException(status_code=400, detail=f"Failed to load audio: {e}")

    # Resample if needed
    if sr != TARGET_SR:
        try:
            resampler = torchaudio.transforms.Resample(orig_freq=sr, new_freq=TARGET_SR)
            waveform = resampler(waveform.unsqueeze(0)).squeeze(0)
            log.info(f"Resampled audio from {sr} to {TARGET_SR}")
        except Exception as e:
            log.error(f"Resampling failed: {e}")
            raise HTTPException(status_code=400, detail=f"Failed to resample audio: {e}")

    return waveform  # shape: [num_samples]


def _chunk_audio(waveform: torch.Tensor) -> list[torch.Tensor]:
    """Split waveform into ≤3-second chunks; pad the last chunk if needed."""
    total = waveform.shape[0]
    n_chunks = max(1, math.ceil(total / CHUNK_SAMPLES))
    chunks = []
    for i in range(n_chunks):
        start = i * CHUNK_SAMPLES
        end   = start + CHUNK_SAMPLES
        chunk = waveform[start:end]
        if chunk.shape[0] < CHUNK_SAMPLES:
            pad = torch.zeros(CHUNK_SAMPLES - chunk.shape[0])
            chunk = torch.cat([chunk, pad])
        chunks.append(chunk)
    return chunks


# ─── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "models_loaded": list(models_store.keys())}


@app.post("/predict/ar", response_model=DetectionResponse)
async def predict_arabic(req: TextRequest):
    """Detect AI-generated Arabic text using AraBERT."""
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text is empty")
    # Arabic model: index 0 = human, index 1 = AI
    return _text_predict(req.text, models_store["ar_model"], models_store["ar_tokenizer"],
                         ai_index=1, language="ar")


@app.post("/predict/en", response_model=DetectionResponse)
async def predict_english(req: TextRequest):
    """Detect AI-generated English text using DistilBERT."""
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text is empty")
    # English model: index 1 = AI, index 0 = human
    return _text_predict(req.text, models_store["en_model"], models_store["en_tokenizer"],
                         ai_index=1, language="en")


@app.post("/predict/image", response_model=DetectionResponse)
async def predict_image(file: UploadFile = File(...)):
    """Detect AI-generated images using EfficientNet-B0."""
    allowed = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported image type: {ext}")

    data = await file.read()
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot open image: {e}")

    tensor = IMAGE_TRANSFORM(img).unsqueeze(0)  # [1, 3, 224, 224]
    with torch.no_grad():
        logits = models_store["img_model"](tensor)
    probs = torch.softmax(logits, dim=-1)[0]

    class_names = models_store["img_class_names"]   # ['FAKE', 'REAL']
    fake_index  = class_names.index("FAKE") if "FAKE" in class_names else 0
    ai_prob     = float(probs[fake_index])
    is_ai       = ai_prob >= 0.5
    confidence  = float(probs.max())

    return DetectionResponse(
        is_ai=is_ai,
        ai_probability=round(ai_prob, 4),
        confidence=round(confidence, 4),
        language="image",
        details=f"EfficientNet-B0 image analysis. FAKE={probs[fake_index]:.4f} REAL={probs[1-fake_index]:.4f}",
    )


@app.post("/predict/audio", response_model=DetectionResponse)
async def predict_audio(file: UploadFile = File(...)):
    """
    Detect AI-generated / spoofed audio using Wav2Vec2.
    - Accepts .wav and .mp3
    - Converts to mono 16 000 Hz
    - Splits into ≤3-second chunks; runs inference on each
    - Returns average AI probability across all chunks
    """
    allowed = {".wav", ".mp3"}
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported audio type: {ext}. Use .wav or .mp3")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty audio file")

    try:
        waveform = _load_audio_mono_16k(data, ext)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to load audio: {e}")

    chunks = _chunk_audio(waveform)
    log.info("Audio: %d samples → %d chunk(s) of %d samples", waveform.shape[0], len(chunks), CHUNK_SAMPLES)

    audio_model = models_store["audio_model"]
    chunk_probs = []

    with torch.no_grad():
        for chunk in chunks:
            inp    = chunk.unsqueeze(0)              # [1, 48000]
            logits = audio_model(inp)                # [1, 2]
            probs  = torch.softmax(logits, dim=-1)   # [1, 2]
            # index 0 = bonafide/real, index 1 = spoof/AI
            ai_p   = float(probs[0][1])
            chunk_probs.append(ai_p)

    avg_ai_prob = sum(chunk_probs) / len(chunk_probs)
    is_ai       = avg_ai_prob >= 0.5
    confidence  = abs(avg_ai_prob - 0.5) * 2          # 0→uncertain, 1→very confident

    return DetectionResponse(
        is_ai=is_ai,
        ai_probability=round(avg_ai_prob, 4),
        confidence=round(confidence, 4),
        language="audio",
        details=(
            f"Wav2Vec2 analysis | {len(chunks)} chunk(s) | "
            f"avg AI prob={avg_ai_prob:.4f} | "
            f"chunk probs={[round(p,3) for p in chunk_probs]}"
        ),
    )


@app.post("/predict/video", response_model=DetectionResponse)
async def predict_video(file: UploadFile = File(...)):
    """
    Detect AI-generated/deepfake video by analyzing:
    - 5 frames extracted evenly (via EfficientNet-B0 image model)
    - Audio track (via Wav2Vec2 audio model)
    """
    allowed = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported video type: {ext}")

    # Write video to a temporary file
    temp_video_fd, temp_video_path = tempfile.mkstemp(suffix=ext)
    try:
        with os.fdopen(temp_video_fd, 'wb') as tmp:
            tmp.write(await file.read())

        # 1. Extract and predict on frames
        frames = _extract_frames_in_memory(temp_video_path, max_frames=5)
        img_probs = []
        if frames:
            img_model = models_store["img_model"]
            class_names = models_store["img_class_names"]
            fake_index  = class_names.index("FAKE") if "FAKE" in class_names else 0
            
            for frame in frames:
                tensor = IMAGE_TRANSFORM(frame).unsqueeze(0)
                with torch.no_grad():
                    logits = img_model(tensor)
                probs = torch.softmax(logits, dim=-1)[0]
                img_probs.append(float(probs[fake_index]))

        # 2. Extract and predict on audio
        has_audio = False
        aud_prob = 0.0
        audio_wav_path = None
        
        try:
            # Create a temp file for wav
            temp_wav_fd, audio_wav_path = tempfile.mkstemp(suffix=".wav")
            os.close(temp_wav_fd) # Close handle so subprocess can write
            
            _extract_audio_from_video(temp_video_path, audio_wav_path)
            
            if os.path.exists(audio_wav_path) and os.path.getsize(audio_wav_path) > 0:
                with open(audio_wav_path, 'rb') as f:
                    audio_data = f.read()
                
                waveform = _load_audio_mono_16k(audio_data, ".wav")
                chunks = _chunk_audio(waveform)
                
                audio_model = models_store["audio_model"]
                chunk_probs = []
                with torch.no_grad():
                    for chunk in chunks:
                        inp = chunk.unsqueeze(0)
                        logits = audio_model(inp)
                        probs = torch.softmax(logits, dim=-1)
                        # index 0 = bonafide/real, index 1 = spoof/AI
                        chunk_probs.append(float(probs[0][1]))
                
                if chunk_probs:
                    aud_prob = sum(chunk_probs) / len(chunk_probs)
                    has_audio = True
        except Exception as ae_err:
            log.warning(f"Audio extraction / detection failed or no audio track: {ae_err}")
            has_audio = False
        finally:
            if audio_wav_path and os.path.exists(audio_wav_path):
                try:
                    os.remove(audio_wav_path)
                except Exception:
                    pass

        # 3. Combine results
        if img_probs and has_audio:
            avg_img_prob = sum(img_probs) / len(img_probs)
            ai_prob = max(avg_img_prob, aud_prob)
            is_ai = ai_prob >= 0.5
            confidence = abs(ai_prob - 0.5) * 2
            details = (
                f"Multimodal video analysis | "
                f"Visual AI Prob={avg_img_prob:.4f} (5 frames) | "
                f"Audio AI Prob={aud_prob:.4f} | "
                f"Decision = MAX(Visual, Audio)"
            )
        elif img_probs:
            avg_img_prob = sum(img_probs) / len(img_probs)
            ai_prob = avg_img_prob
            is_ai = ai_prob >= 0.5
            confidence = abs(ai_prob - 0.5) * 2
            details = f"Video analysis (visuals only) | AI Prob={avg_img_prob:.4f} (5 frames)"
        elif has_audio:
            ai_prob = aud_prob
            is_ai = ai_prob >= 0.5
            confidence = abs(ai_prob - 0.5) * 2
            details = f"Video analysis (audio only) | AI Prob={aud_prob:.4f}"
        else:
            raise HTTPException(status_code=400, detail="Unable to extract video frames or audio track.")

        return DetectionResponse(
            is_ai=is_ai,
            ai_probability=round(ai_prob, 4),
            confidence=round(confidence, 4),
            language="video",
            details=details,
        )

    finally:
        if os.path.exists(temp_video_path):
            try:
                os.remove(temp_video_path)
            except Exception:
                pass
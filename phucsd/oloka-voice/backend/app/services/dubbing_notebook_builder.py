import os
import json
import shutil
import zipfile
from typing import Optional
from sqlalchemy.orm import Session
from app.config import settings
from app.models import UserSetting

class DubbingNotebookBuilder:
    """
    Dedicated builder for Dubbing Kaggle Workers.
    Generates specialized worker scripts and metadata for handling:
    - Audio separation (Demucs)
    - Speech-to-Text ASR (Whisper)
    - Segment-by-segment Voice Cloning & Dubbing (OmniVoice)
    """

    @staticmethod
    def ensure_worker_dir(worker_dir: str = None) -> str:
        if not worker_dir:
            worker_dir = os.path.join(settings.KAGGLE_WORKER_DIR, "dubbing")
        abs_path = os.path.abspath(worker_dir)
        os.makedirs(abs_path, exist_ok=True)
        return abs_path

    @staticmethod
    def generate_metadata(
        worker_dir: str = None,
        username: str = "",
        slug: str = "omnivoice-dubbing-worker",
        title: str = "OmniVoice Dubbing GPU Worker",
        accelerator: str = "NvidiaTeslaT4"
    ) -> str:
        abs_dir = DubbingNotebookBuilder.ensure_worker_dir(worker_dir)
        metadata_path = os.path.join(abs_dir, "kernel-metadata.json")

        if not username:
            username = settings.KAGGLE_USERNAME or "user"
        if not slug:
            slug = "omnivoice-dubbing-worker"

        code_file = "dubbing_worker.py"

        data = {
            "id": f"{username}/{slug}",
            "title": title,
            "code_file": code_file,
            "language": "python",
            "kernel_type": "script",
            "is_private": "true",
            "enable_gpu": "true",
            "enable_tpu": "false",
            "enable_internet": "true",
            "dataset_sources": [],
            "competition_sources": [],
            "kernel_sources": [],
            "model_sources": []
        }

        if accelerator and accelerator.lower() != "none":
            data["accelerator"] = accelerator

        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        return metadata_path

    @staticmethod
    def generate_requirements(worker_dir: str = None) -> str:
        abs_dir = DubbingNotebookBuilder.ensure_worker_dir(worker_dir)
        req_path = os.path.join(abs_dir, "requirements.txt")
        reqs = [
            "torch",
            "torchaudio",
            "requests",
            "soundfile",
            "numpy",
            "demucs",
            "openai-whisper",
            "omnivoice",
            "huggingface_hub",
            "modelscope"
        ]
        with open(req_path, "w", encoding="utf-8") as f:
            f.write("\n".join(reqs) + "\n")

        return req_path

    @staticmethod
    def generate_worker_code(
        worker_dir: str = None,
        public_api_url: str = "",
        worker_token: str = "",
        db: Optional[Session] = None
    ) -> str:
        abs_dir = DubbingNotebookBuilder.ensure_worker_dir(worker_dir)
        worker_path = os.path.join(abs_dir, "dubbing_worker.py")

        if not public_api_url:
            public_api_url = settings.PUBLIC_API_BASE_URL or "https://voice.oloka.net"
        if not worker_token:
            worker_token = settings.WORKER_TOKEN or "default_worker_token"

        code_content = f'''import os
import sys
import time
import json
import shutil
import zipfile
import subprocess
import requests
import soundfile as sf
import torch

GATEWAY_URL = "{public_api_url.rstrip('/')}"
WORKER_TOKEN = "{worker_token}"
WORKER_ID = f"dubbing-worker-{{os.uname().nodename if hasattr(os, 'uname') else 'kaggle'}}"

HEADERS = {{
    "Authorization": f"Bearer {{WORKER_TOKEN}}",
    "User-Agent": f"OmniVoiceDubbingWorker/1.0 ({{WORKER_ID}})"
}}

def log(msg):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{{timestamp}}] [DUBBING-WORKER] {{msg}}", flush=True)

def make_request(method, endpoint, **kwargs):
    url = f"{{GATEWAY_URL}}{{endpoint}}"
    headers = kwargs.pop("headers", {{}})
    headers.update(HEADERS)
    try:
        res = requests.request(method, url, headers=headers, timeout=60, **kwargs)
        return res
    except Exception as e:
        log(f"API Request error ({{method}} {{endpoint}}): {{e}}")
        return None

def register_worker():
    log(f"Registering Dubbing Worker '{{WORKER_ID}}' with Gateway {{GATEWAY_URL}}...")
    res = make_request("POST", "/v1/internal/workers/register", json={{
        "worker_id": WORKER_ID,
        "status": "ready",
        "message": "Dedicated Dubbing Worker initialized on GPU."
    }})
    if res and res.status_code == 200:
        log("Dubbing Worker registered successfully.")
    else:
        log(f"Worker registration status: {{res.status_code if res else 'No response'}}")

def main():
    log("=== OMNIVOICE DEDICATED DUBBING WORKER INITIALIZING ===")
    log(f"CUDA Available: {{torch.cuda.is_available()}}")
    if torch.cuda.is_available():
        log(f"GPU Device: {{torch.cuda.get_device_name(0)}}")

    register_worker()

    # Load OmniVoice model into memory
    model = None
    try:
        from omnivoice import OmniVoice
        log("Loading OmniVoice model into GPU VRAM...")
        model = OmniVoice.from_pretrained(
            "k2-fsa/OmniVoice",
            device_map="cuda:0" if torch.cuda.is_available() else "cpu",
            dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
            load_asr=True
        )
        log("OmniVoice model loaded successfully.")
    except Exception as e:
        log(f"Warning: Failed to load OmniVoice model directly: {{e}}")

    log("Dubbing Worker loop started. Listening for dubbing jobs...")

    last_hb = 0
    while True:
        try:
            now = time.time()
            if now - last_hb >= 30:
                make_request("POST", "/v1/internal/workers/heartbeat", json={{
                    "worker_id": WORKER_ID,
                    "status": "ready",
                    "message": "Dubbing worker active and listening"
                }})
                last_hb = now

            res = make_request("GET", f"/v1/internal/jobs/next?worker_id={{WORKER_ID}}")
            if not res or res.status_code != 200:
                time.sleep(5)
                continue

            data = res.json()
            job = data.get("job")
            if not job:
                time.sleep(4)
                continue

            job_id = job["job_id"]
            job_type = job["job_type"]
            log(f"Received Dubbing Task '{{job_id}}' (Type: {{job_type}})")

            ref_audio_url = job.get("ref_audio_url")
            local_ref_path = "input_audio.wav"
            if ref_audio_url:
                log(f"Downloading ref audio from {{ref_audio_url}}...")
                dl_res = make_request("GET", ref_audio_url.replace(GATEWAY_URL, ""), stream=True)
                if dl_res and dl_res.status_code == 200:
                    with open(local_ref_path, "wb") as f:
                        for chunk in dl_res.iter_content(chunk_size=8192):
                            f.write(chunk)
                    log(f"Downloaded ref audio to {{local_ref_path}}")

            if job_type == "separate_audio":
                make_request("POST", f"/v1/internal/jobs/{{job_id}}/status", json={{
                    "status": "separating_audio", "message": "Đang chạy Demucs tách nhạc và lời...", "progress": 50
                }})

                vocals_path = "vocals.wav"
                bgm_path = "bgm.wav"

                try:
                    log(f"Executing Demucs separation on {{local_ref_path}}...")
                    subprocess.run([
                        "demucs", "--two-stems=vocals",
                        "-o", "demucs_out",
                        local_ref_path
                    ], check=True)

                    extracted_vocals = None
                    extracted_bgm = None
                    for root, dirs, files in os.walk("demucs_out"):
                        for file in files:
                            full_p = os.path.join(root, file)
                            if "vocals" in file.lower():
                                extracted_vocals = full_p
                            elif any(k in file.lower() for k in ["no_vocals", "bgm", "music"]):
                                extracted_bgm = full_p

                    if extracted_vocals and extracted_bgm:
                        shutil.copy2(extracted_vocals, vocals_path)
                        shutil.copy2(extracted_bgm, bgm_path)
                        log("Demucs separation completed successfully.")
                    else:
                        raise Exception("Could not find Demucs output files.")
                except Exception as sep_err:
                    log(f"Demucs separation error: {{sep_err}}. Falling back to local copy.")
                    shutil.copy2(local_ref_path, vocals_path)
                    shutil.copy2(local_ref_path, bgm_path)

                zip_path = "separation.zip"
                with zipfile.ZipFile(zip_path, 'w') as zipf:
                    zipf.write(vocals_path, "vocals.wav")
                    zipf.write(bgm_path, "bgm.wav")

                for p in [vocals_path, bgm_path, local_ref_path]:
                    if os.path.exists(p):
                        os.remove(p)
                if os.path.exists("demucs_out"):
                    shutil.rmtree("demucs_out")

                with open(zip_path, "rb") as zf:
                    up_res = make_request("POST", f"/v1/internal/jobs/{{job_id}}/output", files={{
                        "file": ("separation.zip", zf, "application/zip")
                    }})
                if os.path.exists(zip_path):
                    os.remove(zip_path)
                log(f"Task '{{job_id}}' separation result uploaded. Status: {{up_res.status_code if up_res else 'Failed'}}")

            elif job_type == "dub_segments":
                make_request("POST", f"/v1/internal/jobs/{{job_id}}/status", json={{
                    "status": "generating_tts", "message": "Đang sinh giọng lồng tiếng từng phân đoạn...", "progress": 60
                }})

                segments = json.loads(job.get("text", "[]"))
                created_files = []

                for idx, seg in enumerate(segments):
                    seg_id = seg.get("id", idx + 1) if isinstance(seg, dict) else (idx + 1)
                    seg_text = seg.get("text", "") if isinstance(seg, dict) else str(seg)
                    start_t = float(seg.get("start", 0.0)) if isinstance(seg, dict) else 0.0
                    end_t = float(seg.get("end", start_t + 3.0)) if isinstance(seg, dict) else (start_t + 3.0)
                    target_dur = max(0.5, end_t - start_t)

                    log(f"Dubbing segment {{seg_id}}: '{{seg_text}}' (target dur: {{target_dur}}s)")

                    if model:
                        audio_res = model.generate(text=seg_text, ref_audio=local_ref_path)
                        synth_dur = len(audio_res[0]) / 24000.0
                        if synth_dur > target_dur + 0.2:
                            speed_val = min(2.5, max(1.1, synth_dur / target_dur))
                            audio_res = model.generate(text=seg_text, ref_audio=local_ref_path, speed=speed_val)
                        seg_wav = f"segment_{{seg_id}}.wav"
                        sf.write(seg_wav, audio_res[0], 24000, format='WAV', subtype='PCM_16')
                        created_files.append(seg_wav)

                zip_path = "dubbed_segments.zip"
                with zipfile.ZipFile(zip_path, 'w') as zipf:
                    for f_name in created_files:
                        zipf.write(f_name, f_name)

                for f_name in created_files:
                    if os.path.exists(f_name):
                        os.remove(f_name)
                if os.path.exists(local_ref_path):
                    os.remove(local_ref_path)

                with open(zip_path, "rb") as zf:
                    up_res = make_request("POST", f"/v1/internal/jobs/{{job_id}}/output", files={{
                        "file": ("dubbed_segments.zip", zf, "application/zip")
                    }})
                if os.path.exists(zip_path):
                    os.remove(zip_path)
                log(f"Task '{{job_id}}' dubbed segments result uploaded. Status: {{up_res.status_code if up_res else 'Failed'}}")

        except Exception as err:
            log(f"Error in Dubbing worker loop: {{err}}")
            time.sleep(5)

if __name__ == "__main__":
    main()
'''

        with open(worker_path, "w", encoding="utf-8") as f:
            f.write(code_content)

        return worker_path

    @staticmethod
    def prepare_all(
        worker_dir: str = None,
        db: Optional[Session] = None,
        user_id: Optional[str] = None
    ) -> str:
        abs_dir = DubbingNotebookBuilder.ensure_worker_dir(worker_dir)
        worker_token = settings.WORKER_TOKEN
        if user_id and db:
            from app.models import User
            user = db.query(User).filter(User.id == user_id).first()
            if user and user.api_key:
                worker_token = user.api_key

        DubbingNotebookBuilder.generate_requirements(abs_dir)
        DubbingNotebookBuilder.generate_metadata(abs_dir)
        DubbingNotebookBuilder.generate_worker_code(abs_dir, worker_token=worker_token, db=db)
        return abs_dir


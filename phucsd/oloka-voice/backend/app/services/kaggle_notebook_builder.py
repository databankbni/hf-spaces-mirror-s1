import os
import json
from app.config import settings

class KaggleNotebookBuilder:
    @staticmethod
    def ensure_worker_dir(worker_dir: str) -> str:
        """Ensures that the kaggle worker directory exists and returns its absolute path."""
        worker_dir_abs = os.path.abspath(worker_dir)
        os.makedirs(worker_dir_abs, exist_ok=True)
        return worker_dir_abs

    @staticmethod
    def generate_metadata(worker_dir: str, username: str, slug: str, title: str, accelerator: str = None) -> str:
        """Generates or updates kernel-metadata.json from configurations."""
        metadata_path = os.path.join(worker_dir, "kernel-metadata.json")
        
        dataset_sources = []
        # Check settings for Kaggle credentials to dynamically check datasets
        if settings.KAGGLE_USERNAME and settings.KAGGLE_KEY:
            try:
                # Set temporary env variables for the kaggle library
                os.environ["KAGGLE_USERNAME"] = settings.KAGGLE_USERNAME
                os.environ["KAGGLE_KEY"] = settings.KAGGLE_KEY
                
                from kaggle.api.kaggle_api_extended import KaggleApi
                api = KaggleApi()
                api.authenticate()
                
                # Check which of the target datasets is available and accessible
                candidates = [
                    "phcnguynhukendykerry/omnivoice-original-2",
                    "phcnguynhukendykerry/omnivoice-original",
                    f"{username}/omnivoice-model",
                    f"{username}/omnivoice"
                ]
                for dataset_ref in candidates:
                    try:
                        status = api.dataset_status(dataset_ref)
                        if status:
                            dataset_sources.append(dataset_ref)
                            print(f"[KaggleNotebookBuilder] Auto-detected Kaggle dataset: {dataset_ref} (status: {status}). Adding to dataset_sources.")
                            break
                    except Exception:
                        continue
            except Exception as ex:
                print(f"[KaggleNotebookBuilder] Info: Kaggle API dataset status check skipped: {ex}")
                
        # If no dataset was found via API, fallback to default
        if not dataset_sources:
            dataset_sources = ["phcnguynhukendykerry/omnivoice-original-2"]

        # Build metadata structure
        metadata = {
            "id": f"{username}/{slug}",
            "title": title,
            "code_file": "omnivoice_worker.py",
            "language": "python",
            "kernel_type": "script",
            "is_private": True,
            "enable_gpu": True,
            "enable_internet": True,
            "dataset_sources": dataset_sources,
            "kernel_sources": [],
            "competition_sources": []
        }
        
        # Map accelerator values to Kaggle API expected format
        mapped_acc = "NvidiaTeslaT4"
        if accelerator:
            acc_lower = accelerator.lower()
            if "p100" in acc_lower:
                mapped_acc = "NvidiaTeslaP100"
            elif "t4" in acc_lower:
                mapped_acc = "NvidiaTeslaT4"
            else:
                mapped_acc = accelerator
        
        metadata["machine_shape"] = mapped_acc
        metadata["accelerator"] = mapped_acc
        
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
            
        print(f"[KaggleNotebookBuilder] Generated metadata at: {metadata_path}")
        return metadata_path

    @staticmethod
    def generate_requirements(worker_dir: str) -> str:
        """Generates or updates the requirements.txt file."""
        req_path = os.path.join(worker_dir, "requirements.txt")
        req_content = "omnivoice\nsoundfile\nrequests\nfaster-whisper\n"
        
        with open(req_path, "w", encoding="utf-8") as f:
            f.write(req_content)
            
        print(f"[KaggleNotebookBuilder] Generated requirements.txt at: {req_path}")
        return req_path

    @staticmethod
    def generate_worker_code(worker_dir: str, job=None, public_api_url: str = "", worker_token: str = "", is_daemon: bool = True, db=None) -> str:
        """Generates the omnivoice_worker.py Python script containing the OmniVoice batch or daemon generation logic."""
        worker_path = os.path.join(worker_dir, "omnivoice_worker.py")
        
        if not worker_token:
            worker_token = settings.WORKER_TOKEN or "default_secure_worker_token_12345"

        hf_token = ""
        if db:
            from app.models import SystemSetting
            db_hf = db.query(SystemSetting).filter(SystemSetting.key == "hf_token").first()
            if db_hf and db_hf.value.strip():
                hf_token = db_hf.value.strip()
        if not hf_token:
            hf_token = settings.HF_TOKEN

        if is_daemon:
            worker_id = None
            if job:
                if isinstance(job, dict):
                    worker_id = job.get("worker_id")
                else:
                    worker_id = getattr(job, "worker_id", None)
            if not worker_id:
                if "worker-2" in worker_dir or "worker_2" in worker_dir:
                    worker_id = "worker_2"
                else:
                    worker_id = "worker_1"
            idle_timeout = settings.WORKER_IDLE_TIMEOUT_SECONDS
            if db:
                from app.models import SystemSetting
                db_idle = db.query(SystemSetting).filter(SystemSetting.key == "kaggle_idle_timeout_seconds").first()
                if db_idle and db_idle.value.strip():
                    try:
                        idle_timeout = int(db_idle.value.strip())
                    except ValueError:
                        pass
            poll_interval = settings.WORKER_POLL_INTERVAL_SECONDS
            
            # Optimized Daemon script template
            code = f"""import os
import sys
import time
import uuid
import tempfile
import traceback
import requests
import warnings
import shutil
import zipfile
import json
import subprocess
from urllib.parse import urlparse

os.environ["CUDA_MODULE_LOADING"] = "LAZY"
os.environ["PYTHONWARNINGS"] = "ignore"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
os.environ["HF_HUB_DISABLE_XET"] = "1"
os.environ["HF_HUB_ETAG_TIMEOUT"] = "15"
os.environ["HF_TOKEN"] = {repr(hf_token)}
os.environ["HUGGING_FACE_HUB_TOKEN"] = {repr(hf_token)}
warnings.filterwarnings("ignore")

def ensure_dependencies():
    \"\"\"Dynamically checks and installs required packages inside the Kaggle environment if missing.\"\"\"
    missing = []
    try:
        import omnivoice
    except ImportError:
        missing.append("omnivoice")
    try:
        import soundfile
    except ImportError:
        missing.append("soundfile")
    try:
        import modelscope
    except ImportError:
        missing.append("modelscope")
    try:
        import sentencepiece
    except ImportError:
        missing.append("sentencepiece")
    try:
        import tiktoken
    except ImportError:
        missing.append("tiktoken")
    try:
        import faster_whisper
    except ImportError:
        missing.append("faster-whisper")
        
    if missing:
        import subprocess
        print(f"Installing missing dependencies: {{', '.join(missing)}}")
        try:
            # Install packages silently with fast flags
            subprocess.check_call([
                sys.executable, "-m", "pip", "install", "-q", 
                "--no-cache-dir", "--prefer-binary", 
                "--no-warn-script-location"
            ] + missing)
            print("Dependencies installed successfully.")
        except Exception as e:
            print(f"Failed to install dependencies: {{e}}")
            sys.exit(1)

# Ensure dependencies are available before anything else runs
ensure_dependencies()

import torch
import soundfile as sf
from omnivoice import OmniVoice

PUBLIC_API_BASE_URL = {repr(public_api_url)}.rstrip("/")
WORKER_TOKEN = {repr(worker_token)}
WORKER_ID = {repr(worker_id)}
IDLE_TIMEOUT = {idle_timeout}
POLL_INTERVAL = {poll_interval}

HEADERS = {{
    "Authorization": f"Bearer {{WORKER_TOKEN}}"
}}

def log(msg: str):
    print(f"[{{time.strftime('%Y-%m-%d %H:%M:%S')}}] [Worker-{{WORKER_ID}}] {{msg}}")
    sys.stdout.flush()

def make_request(method: str, path: str, **kwargs) -> requests.Response:
    url = f"{{PUBLIC_API_BASE_URL}}{{path}}"
    if "headers" in kwargs:
        kwargs["headers"].update(HEADERS)
    else:
        kwargs["headers"] = HEADERS.copy()
    return requests.request(method, url, **kwargs)

WHISPER_MODEL = None

def levenshtein_ratio(s1, s2):
    if len(s1) == 0 or len(s2) == 0:
        return 0.0
    if s1 == s2:
        return 1.0
    matrix = [[0] * (len(s2) + 1) for _ in range(len(s1) + 1)]
    for i in range(len(s1) + 1):
        matrix[i][0] = i
    for j in range(len(s2) + 1):
        matrix[0][j] = j
    for i in range(1, len(s1) + 1):
        for j in range(1, len(s2) + 1):
            cost = 0 if s1[i-1] == s2[j-1] else 1
            matrix[i][j] = min(matrix[i-1][j] + 1, matrix[i][j-1] + 1, matrix[i-1][j-1] + cost)
    max_len = max(len(s1), len(s2))
    return 1.0 - (matrix[len(s1)][len(s2)] / max_len)

def get_whisper_model():
    global WHISPER_MODEL
    if WHISPER_MODEL is None:
        log("Loading Whisper model for word alignment...")
        from faster_whisper import WhisperModel
        import torch
        
        # Try GPU first
        if torch.cuda.is_available():
            try:
                log("Attempting to load WhisperModel on GPU (cuda)...")
                WHISPER_MODEL = WhisperModel("small", device="cuda", compute_type="float16")
                log("Whisper model loaded on GPU successfully.")
                return WHISPER_MODEL
            except Exception as gpu_err:
                log(f"Warning: Failed to load WhisperModel on GPU: {{gpu_err}}. Falling back to CPU...")
                
        # Fallback to CPU
        try:
            log("Attempting to load WhisperModel on CPU...")
            WHISPER_MODEL = WhisperModel("small", device="cpu", compute_type="int8")
            log("Whisper model loaded on CPU successfully.")
        except Exception as cpu_err:
            log(f"Error: Failed to load WhisperModel on CPU: {{cpu_err}}")
            raise cpu_err
            
    return WHISPER_MODEL

def align_words(original_words, transcribed_words, audio_duration):
    n = len(original_words)
    m = len(transcribed_words)
    if n == 0:
        return []
    if m == 0:
        return None
    
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    parent = [[None] * (m + 1) for _ in range(n + 1)]
    
    for i in range(1, n + 1):
        dp[i][0] = dp[i-1][0] + 1.0
        parent[i][0] = (i-1, 0, "skip_orig")
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j-1] + 1.0
        parent[0][j] = (0, j-1, "skip_trans")
        
    for i in range(1, n + 1):
        orig_w = original_words[i-1].lower().strip(".,!?\\"'`”“_-;:*()[]{{}}<>")
        for j in range(1, m + 1):
            trans_w = transcribed_words[j-1]["word"].lower().strip(".,!?\\"'`”“_-;:*()[]{{}}<>")
            
            ratio = levenshtein_ratio(orig_w, trans_w)
            if ratio >= 0.7:
                match_cost = 0.0
            elif ratio >= 0.4:
                match_cost = 0.5
            else:
                match_cost = 1.0
                
            cost_match = dp[i-1][j-1] + match_cost
            cost_skip_orig = dp[i-1][j] + 1.0
            cost_skip_trans = dp[i][j-1] + 1.0
            
            min_cost = min(cost_match, cost_skip_orig, cost_skip_trans)
            dp[i][j] = min_cost
            
            if min_cost == cost_match:
                parent[i][j] = (i-1, j-1, "match")
            elif min_cost == cost_skip_orig:
                parent[i][j] = (i-1, j, "skip_orig")
            else:
                parent[i][j] = (i, j-1, "skip_trans")
                
    i, j = n, m
    matches = dict()
    while i > 0 or j > 0:
        p = parent[i][j]
        if p is None:
            break
        pi, pj, op = p
        if op == "match":
            matches[pi] = pj
        i, j = pi, pj
        
    aligned = []
    matched_times = []
    for idx in range(n):
        if idx in matches:
            t_word = transcribed_words[matches[idx]]
            start = max(0.0, min(t_word["start"], audio_duration))
            end = max(start, min(t_word["end"], audio_duration))
            matched_times.append((idx, start, end))
            
    if not matched_times:
        return None
        
    first_matched_idx, first_start, first_end = matched_times[0]
    last_matched_idx, last_start, last_end = matched_times[-1]
    
    matched_lookup = dict()
    for idx, start, end in matched_times:
        matched_lookup[idx] = (start, end)
        
    for idx in range(n):
        if idx in matched_lookup:
            start, end = matched_lookup[idx]
            aligned.append(dict(
                word=original_words[idx],
                start=round(start, 3),
                end=round(end, 3)
            ))
        elif idx < first_matched_idx:
            total_chars = sum(len(original_words[k]) for k in range(first_matched_idx)) or 1
            chars_before = sum(len(original_words[k]) for k in range(idx))
            start = first_start * (chars_before / total_chars)
            word_dur = first_start * (len(original_words[idx]) / total_chars)
            end = start + word_dur
            aligned.append(dict(
                word=original_words[idx],
                start=round(start, 3),
                end=round(end, 3)
            ))
        elif idx > last_matched_idx:
            rem_chars = sum(len(original_words[k]) for k in range(last_matched_idx + 1, n)) or 1
            chars_before = sum(len(original_words[k]) for k in range(last_matched_idx + 1, idx))
            rem_duration = audio_duration - last_end
            start = last_end + rem_duration * (chars_before / rem_chars)
            word_dur = rem_duration * (len(original_words[idx]) / rem_chars)
            end = start + word_dur
            aligned.append(dict(
                word=original_words[idx],
                start=round(start, 3),
                end=round(end, 3)
            ))
        else:
            pre_idx = -1
            pre_start = 0.0
            pre_end = 0.0
            for o_idx, start, end in matched_times:
                if o_idx < idx:
                    pre_idx = o_idx
                    pre_start = start
                    pre_end = end
                else:
                    break
                    
            succ_idx = -1
            succ_start = 0.0
            succ_end = 0.0
            for o_idx, start, end in matched_times:
                if o_idx > idx:
                    succ_idx = o_idx
                    succ_start = start
                    succ_end = end
                    break
                    
            gap_chars = sum(len(original_words[k]) for k in range(pre_idx + 1, succ_idx)) or 1
            chars_before = sum(len(original_words[k]) for k in range(pre_idx + 1, idx))
            gap_duration = succ_start - pre_end
            
            start = pre_end + gap_duration * (chars_before / gap_chars)
            word_dur = gap_duration * (len(original_words[idx]) / gap_chars)
            end = start + word_dur
            
            aligned.append(dict(
                word=original_words[idx],
                start=round(start, 3),
                end=round(end, 3)
            ))
            
    return aligned

def main():
    if not PUBLIC_API_BASE_URL:
        print("ERROR: PUBLIC_API_BASE_URL is not set. Exiting.")
        sys.exit(1)

    log(f"Starting Kaggle Worker Daemon. Gateway: {{PUBLIC_API_BASE_URL}}")
    
    # 1. Register starting
    try:
        make_request(
            "POST", 
            "/v1/internal/workers/register", 
            json={{"worker_id": WORKER_ID, "status": "starting", "message": "OmniVoice worker starting up..."}}
        )
    except Exception as e:
        print(f"Failed to register startup with gateway: {{e}}")
        sys.exit(1)

    # 2. Load OmniVoice
    log("Loading OmniVoice model into memory...")
    try:
        # Send heartbeat reporting loading_model status
        make_request(
            "POST", 
            "/v1/internal/workers/heartbeat", 
            json={{"worker_id": WORKER_ID, "status": "loading_model", "message": "Loading model weights..."}}
        )

        model_dir = None
        model_loaded = False
        
        # 1. First priority: Original Hugging Face Hub (direct download)
        try:
            log("Attempting to load model from Hugging Face Hub...")
            model = OmniVoice.from_pretrained(
                "k2-fsa/OmniVoice",
                device_map="cuda:0",
                dtype=torch.float16,
                load_asr=True,
            )
            log("OmniVoice model loaded successfully from Hugging Face Hub.")
            model_loaded = True
        except Exception as hf_err:
            log(f"Warning: Failed to load from Hugging Face Hub (CDN issue?): {{hf_err}}")
            model_loaded = False
        
        # 2. Second priority: Mounted Kaggle Dataset (Fallback)
        if not model_loaded:
            if os.path.exists("/kaggle/input"):
                for root, dirs, files in os.walk("/kaggle/input"):
                    if "model.safetensors" in files and "config.json" in files:
                        if not root.endswith("audio_tokenizer"):
                            model_dir = root
                            log(f"Found mounted model weights at: {{model_dir}}. Loading instantly...")
                            break
        
        # 3. Third priority: ModelScope fallback (Stable alternative source if HF is down)
        if not model_loaded and not model_dir:
            try:
                from modelscope import snapshot_download
                log("Falling back to ModelScope to download model weights...")
                model_dir = snapshot_download("k2-fsa/OmniVoice")
                log(f"Model weights loaded locally via ModelScope at: {{model_dir}}")
            except Exception as ms_err:
                log(f"CRITICAL: Failed to download from ModelScope: {{ms_err}}")
                model_dir = "k2-fsa/OmniVoice"

        # Load from model_dir if it was not loaded from Hugging Face directly
        if not model_loaded:
            # Check if tokenizer files are missing from model_dir
            tokenizer_json = os.path.join(model_dir, "tokenizer.json")
            tokenizer_config = os.path.join(model_dir, "tokenizer_config.json")
            if not os.path.exists(tokenizer_json) or not os.path.exists(tokenizer_config):
                log("Tokenizer files are missing from local directory. Merging with downloaded tokenizer files...")
                temp_model_dir = tempfile.mkdtemp()
                # Create symbolic links to all files in model_dir
                for f in os.listdir(model_dir):
                    src_file = os.path.join(model_dir, f)
                    dst_file = os.path.join(temp_model_dir, f)
                    if os.path.isfile(src_file):
                        try:
                            os.symlink(src_file, dst_file)
                        except Exception:
                            shutil.copy2(src_file, dst_file)
                # Download missing tokenizer files from Hugging Face Hub (or ModelScope fallback)
                for filename in ["tokenizer.json", "tokenizer_config.json"]:
                    dst_file = os.path.join(temp_model_dir, filename)
                    if not os.path.exists(dst_file):
                        success = False
                        # 1. Try Hugging Face first
                        try:
                            log(f"Downloading {{filename}} from Hugging Face...")
                            res = requests.get(f"https://huggingface.co/k2-fsa/OmniVoice/resolve/main/{{filename}}", timeout=30)
                            if res.status_code == 200:
                                with open(dst_file, "wb") as out_f:
                                    out_f.write(res.content)
                                success = True
                                log(f"Successfully downloaded {{filename}} from Hugging Face.")
                            else:
                                log(f"Warning: Failed to download {{filename}} from HF (status: {{res.status_code}})")
                        except Exception as dl_err:
                            log(f"Warning: Failed to download {{filename}} from HF: {{dl_err}}")
                        
                        # 2. Try ModelScope fallback
                        if not success:
                            try:
                                log(f"Attempting to download {{filename}} from ModelScope...")
                                from modelscope.hub.file_download import model_file_download
                                cache_file = model_file_download("k2-fsa/OmniVoice", file_path=filename)
                                if cache_file and os.path.exists(cache_file):
                                    shutil.copy2(cache_file, dst_file)
                                    success = True
                                    log(f"Successfully retrieved {{filename}} from ModelScope.")
                            except Exception as ms_dl_err:
                                log(f"Warning: Failed to download {{filename}} from ModelScope: {{ms_dl_err}}")
                                
                        if not success:
                            raise FileNotFoundError(f"Tokenizer file '{{filename}}' is missing and could not be downloaded from Hugging Face or ModelScope. Aborting.")
                model_dir = temp_model_dir

            model = OmniVoice.from_pretrained(
                model_dir,
                device_map="cuda:0",
                dtype=torch.float16,
                load_asr=True,
            )
            log("OmniVoice model loaded successfully from local path.")
        log("OmniVoice model loaded successfully.")
    except Exception as e:
        log(f"CRITICAL ERROR loading OmniVoice model: {{e}}")
        try:
            make_request(
                "POST", 
                "/v1/internal/workers/register", 
                json={{"worker_id": WORKER_ID, "status": "failed", "message": f"Model load failed: {{str(e)}}"}}
            )
        except Exception:
            pass
        sys.exit(1)

    # Register as Ready
    make_request(
        "POST", 
        "/v1/internal/workers/register", 
        json={{"worker_id": WORKER_ID, "status": "ready", "message": "OmniVoice model ready for requests."}}
    )

    idle_seconds = 0
    log("Entering job polling loop...")
    
    while True:
        try:
            # Send heartbeat
            make_request(
                "POST",
                "/v1/internal/workers/heartbeat",
                json={{"worker_id": WORKER_ID, "status": "idle", "message": f"Worker polling. Idle time: {{idle_seconds}}s"}}
            )

            # Poll for job
            response = make_request("GET", f"/v1/internal/jobs/next?worker_id={{WORKER_ID}}")
            if response.status_code == 401:
                log("Unauthorized (401). Worker token invalid. Exiting.")
                break
                
            if response.status_code != 200:
                log(f"Warning: Poll returned status code {{response.status_code}}")
                time.sleep(POLL_INTERVAL)
                idle_seconds += POLL_INTERVAL
                continue

            data = response.json()
            job = data.get("job")

            if not job:
                # No job available
                time.sleep(POLL_INTERVAL)
                idle_seconds += POLL_INTERVAL
                if idle_seconds >= IDLE_TIMEOUT:
                    log(f"Idle timeout of {{IDLE_TIMEOUT}}s reached. Initiating shutdown.")
                    make_request(
                        "POST", 
                        "/v1/internal/workers/shutdown", 
                        json={{"worker_id": WORKER_ID, "reason": "idle_timeout"}}
                    )
                    break
                continue

            # Reset idle counter on job receipt
            idle_seconds = 0
            job_id = job["job_id"]
            job_type = job["job_type"]
            log(f"Processing job {{job_id}} ({{job_type}})")

            # Report busy status
            make_request(
                "POST",
                "/v1/internal/workers/heartbeat",
                json={{"worker_id": WORKER_ID, "status": "busy", "current_job_id": job_id, "message": f"Running {{job_type}}"}}
            )

            # Update job status: loading_model
            make_request(
                "POST",
                f"/v1/internal/jobs/{{job_id}}/status",
                json={{"status": "loading_model", "message": "Đang tải OmniVoice...", "progress": 30}}
            )

            # Process job based on type
            try:
                local_ref_path = None
                ref_audio_url = job.get("ref_audio_url")
                
                if job_type in ["clone_voice", "asr", "separate_audio", "dub_segments"] and ref_audio_url:
                    make_request(
                        "POST",
                        f"/v1/internal/jobs/{{job_id}}/status",
                        json={{"status": "preparing_input", "message": "Đang tải tệp âm thanh...", "progress": 45}}
                    )
                    
                    # Securely download voice sample file using the parsed URL path
                    parsed_ref = urlparse(ref_audio_url)
                    ref_path = parsed_ref.path
                    if parsed_ref.query:
                        ref_path = ref_path + "?" + parsed_ref.query
                    res = make_request("GET", ref_path, stream=True)
                    if res.status_code == 200:
                        temp_fd, local_ref_path = tempfile.mkstemp(suffix=".wav")
                        os.close(temp_fd)
                        with open(local_ref_path, "wb") as f:
                            for chunk in res.iter_content(chunk_size=8192):
                                f.write(chunk)
                        log(f"Downloaded audio to {{local_ref_path}}")
                    else:
                        raise Exception(f"Failed to download audio from gateway: {{res.status_code}} - {{res.text}}")

                # Handle separate_audio job type directly
                if job_type == "separate_audio":
                    make_request(
                        "POST",
                        f"/v1/internal/jobs/{{job_id}}/status",
                        json={{"status": "separating_audio", "message": "Đang chạy Demucs tách nhạc và lời...", "progress": 60}}
                    )
                    
                    vocals_path = "vocals.wav"
                    bgm_path = "bgm.wav"
                    
                    try:
                        import subprocess
                        import sys
                        
                        # Try importing demucs or install
                        try:
                            import demucs
                        except ImportError:
                            log("Installing demucs dynamically...")
                            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "demucs"])
                            
                        # Run demucs
                        log(f"Running demucs on {{local_ref_path}}...")
                        subprocess.run([
                            "demucs", "--two-stems=vocals",
                            "-o", "demucs_out",
                            local_ref_path
                        ], check=True)
                        
                        # Find the output files
                        extracted_vocals = None
                        extracted_no_vocals = None
                        for root, dirs, files in os.walk("demucs_out"):
                            for file in files:
                                if file.endswith(".wav"):
                                    full_p = os.path.join(root, file)
                                    if "vocals" in file.lower():
                                        extracted_vocals = full_p
                                    elif any(k in file.lower() for k in ["no_vocals", "bgm", "music"]):
                                        extracted_no_vocals = full_p
                                        
                        if extracted_vocals and extracted_no_vocals:
                            shutil.copy2(extracted_vocals, vocals_path)
                            shutil.copy2(extracted_no_vocals, bgm_path)
                            log("Demucs audio separation successful.")
                        else:
                            raise Exception("Could not locate demucs output files.")
                            
                    except Exception as sep_err:
                        log(f"Warning: Audio separation failed: {{sep_err}}. Falling back to mock separation.")
                        shutil.copy2(local_ref_path, vocals_path)
                        shutil.copy2(local_ref_path, bgm_path)

                    # Zip vocals and bgm
                    zip_path = "separation.zip"
                    with zipfile.ZipFile(zip_path, 'w') as zipf:
                        zipf.write(vocals_path, "vocals.wav")
                        zipf.write(bgm_path, "bgm.wav")
                        
                    # Clean up
                    for path_to_del in [vocals_path, bgm_path, local_ref_path]:
                        if path_to_del and os.path.exists(path_to_del):
                            os.remove(path_to_del)
                    if os.path.exists("demucs_out"):
                        shutil.rmtree("demucs_out")
                        
                    # Upload zip
                    with open(zip_path, "rb") as zip_f:
                        files = {{"file": ("separation.zip", zip_f, "application/zip")}}
                        upload_res = make_request(
                            "POST",
                            f"/v1/internal/jobs/{{job_id}}/output",
                            files=files
                        )
                        
                    if upload_res.status_code == 200:
                        log(f"Successfully uploaded job {{job_id}} separation output.")
                    else:
                        raise Exception(f"Failed to upload separation output: {{upload_res.status_code}} - {{upload_res.text}}")
                        
                    if os.path.exists(zip_path):
                        os.remove(zip_path)
                    continue

                # Handle dub_segments job type directly
                if job_type == "dub_segments":
                    make_request(
                        "POST",
                        f"/v1/internal/jobs/{{job_id}}/status",
                        json={{"status": "generating_tts", "message": "Đang sinh giọng lồng tiếng từng phân đoạn...", "progress": 60}}
                    )
                    
                    segments = json.loads(job["text"])
                    zip_path = "dubbed_segments.zip"
                    
                    created_files = []
                    
                    for idx, seg in enumerate(segments):
                        seg_id = seg.get("id", idx + 1) if isinstance(seg, dict) else (idx + 1)
                        seg_text = seg.get("text", "") if isinstance(seg, dict) else str(seg)
                        start_t = float(seg.get("start", 0.0)) if isinstance(seg, dict) else 0.0
                        end_t = float(seg.get("end", start_t + 3.0)) if isinstance(seg, dict) else (start_t + 3.0)
                        target_dur = max(0.5, end_t - start_t)
                        
                        log(f"Dubbing segment {{seg_id}}: '{{seg_text}}' (target duration: {{target_dur}}s)")
                        
                        # Generate first try
                        audio_res = model.generate(
                            text=seg_text,
                            ref_audio=local_ref_path,
                        )
                        
                        # Check duration
                        synth_dur = len(audio_res[0]) / 24000.0
                        log(f"Segment {{seg_id}} synthesized duration: {{synth_dur}}s")
                        
                        # If too long, speed it up
                        if synth_dur > target_dur + 0.2:
                            speed_val = min(2.5, max(1.1, synth_dur / target_dur))
                            log(f"Re-generating segment {{seg_id}} with speed={{speed_val}}...")
                            audio_res = model.generate(
                                text=seg_text,
                                ref_audio=local_ref_path,
                                speed=speed_val
                            )
                        
                        seg_wav_name = f"segment_{{seg_id}}.wav"
                        sf.write(seg_wav_name, audio_res[0], 24000, format='WAV', subtype='PCM_16')
                        created_files.append(seg_wav_name)
                        
                    # Zip all
                    with zipfile.ZipFile(zip_path, 'w') as zipf:
                        for f_name in created_files:
                            zipf.write(f_name, f_name)
                            
                    # Clean up
                    for f_name in created_files:
                        if os.path.exists(f_name):
                            os.remove(f_name)
                    if local_ref_path and os.path.exists(local_ref_path):
                        os.remove(local_ref_path)
                        
                    # Upload
                    with open(zip_path, "rb") as zip_f:
                        files = {{"file": ("dubbed_segments.zip", zip_f, "application/zip")}}
                        upload_res = make_request(
                            "POST",
                            f"/v1/internal/jobs/{{job_id}}/output",
                            files=files
                        )
                        
                    if upload_res.status_code == 200:
                        log(f"Successfully uploaded job {{job_id}} dubbed segments output.")
                    else:
                        raise Exception(f"Failed to upload dubbed segments output: {{upload_res.status_code}} - {{upload_res.text}}")
                        
                    if os.path.exists(zip_path):
                        os.remove(zip_path)
                    continue

                # Handle ASR job type directly
                if job_type == "asr":
                    make_request(
                        "POST",
                        f"/v1/internal/jobs/{{job_id}}/status",
                        json={{"status": "transcribing", "message": "Đang nhận dạng giọng nói...", "progress": 70}}
                    )
                    
                    log(f"Transcribing audio {{local_ref_path}}...")
                    asr_res = model._asr_pipe(local_ref_path, return_timestamps="word")
                    transcribed_text = asr_res.get("text", "").strip()
                    chunks = asr_res.get("chunks", [])
                    
                    chunks_json = json.dumps(chunks)
                    
                    log(f"ASR complete. Text: {{transcribed_text}}")
                    
                    if local_ref_path and os.path.exists(local_ref_path):
                        os.remove(local_ref_path)
                        
                    upload_res = make_request(
                        "POST",
                        f"/v1/internal/jobs/{{job_id}}/asr",
                        json={{"text": transcribed_text, "alignment": chunks_json}}
                    )
                    if upload_res.status_code == 200:
                        log(f"Successfully uploaded job {{job_id}} ASR results.")
                    else:
                        raise Exception(f"Failed to upload ASR result to gateway: {{upload_res.status_code}} - {{upload_res.text}}")
                    continue

                make_request(
                    "POST",
                    f"/v1/internal/jobs/{{job_id}}/status",
                    json={{"status": "generating_audio", "message": "Đang xử lý âm thanh...", "progress": 70}}
                )

                # Build generate arguments
                generate_args = {{
                    "text": job["text"]
                }}
                
                if job_type == "clone_voice":
                    generate_args["ref_audio"] = local_ref_path
                    if job.get("ref_text"):
                        generate_args["ref_text"] = job["ref_text"]
                elif job_type in ["voice_design_preview", "voice_design_tts"]:
                    generate_args["instruct"] = job.get("instruct")
                elif job_type != "auto_voice":
                    raise Exception(f"Unknown job type: {{job_type}}")
                
                optional_keys = [
                    "num_step", "denoise", "guidance_scale", "t_shift",
                    "position_temperature", "class_temperature", "layer_penalty_factor",
                    "duration", "speed", "preprocess_prompt", "postprocess_output",
                    "audio_chunk_duration", "audio_chunk_threshold",
                    "language", "pad_duration", "fade_duration"
                ]
                for key in optional_keys:
                    if key in job and job[key] is not None:
                        generate_args[key] = job[key]

                log(f"Calling model.generate with arguments: {{list(generate_args.keys())}}")
                audio_result = model.generate(**generate_args)

                # Clean up local ref path if exists
                if local_ref_path and os.path.exists(local_ref_path):
                    os.remove(local_ref_path)

                # Export WAV
                make_request(
                    "POST",
                    f"/v1/internal/jobs/{{job_id}}/status",
                    json={{"status": "exporting_wav", "message": "Đang xuất WAV...", "progress": 90}}
                )
                
                temp_out_fd, local_out_path = tempfile.mkstemp(suffix=".wav")
                os.close(temp_out_fd)
                
                sf.write(local_out_path, audio_result[0], 24000, format='WAV', subtype='PCM_16')
                log(f"Generated audio saved to {{local_out_path}}")

                # Generate word alignments
                alignment_str = None
                if job.get("with_alignment"):
                    log("Generating word alignment...")
                    alignment_list = None
                    try:
                        log("Attempting precise word alignment using faster-whisper...")
                        w_model = get_whisper_model()
                        log(f"Transcribing audio {{local_out_path}} with word timestamps...")
                        
                        # Dynamic language detection
                        job_text = job.get("text") or ""
                        vi_chars = set("áàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵđ")
                        is_vi = any(c in vi_chars for c in job_text.lower())
                        lang = "vi" if is_vi else None
                        log(f"Language detection: is_vi={{is_vi}}, using language_param={{lang}}")
                        
                        duration_sec = len(audio_result[0]) / 24000.0
                        
                        segments, info = w_model.transcribe(
                            local_out_path, 
                            word_timestamps=True,
                            language=lang
                        )
                        
                        transcribed_words = []
                        for segment in segments:
                            if segment.words:
                                for w in segment.words:
                                    transcribed_words.append(dict(
                                        word=w.word.strip(),
                                        start=w.start,
                                        end=w.end
                                    ))
                        
                        log(f"Whisper transcribed {{len(transcribed_words)}} words.")
                        
                        original_words = job_text.split()
                        if original_words and transcribed_words:
                            alignment_list = align_words(original_words, transcribed_words, duration_sec)
                            if alignment_list:
                                log(f"Successfully aligned {{len(alignment_list)}} original words with Whisper timestamps.")
                    except Exception as whisper_err:
                        log(f"Warning: Precise alignment failed: {{whisper_err}}. Falling back to proportional spacing.")
                        log(traceback.format_exc())
                        
                    # Fallback to proportional spacing
                    if not alignment_list:
                        words = (job.get("text") or "").split()
                        if words:
                            duration_sec = len(audio_result[0]) / 24000.0
                            word_dur = duration_sec / len(words)
                            alignment_list = []
                            curr_time = 0.0
                            for w in words:
                                clean_w = w.strip(".,!?\\"'")
                                alignment_list.append(dict(
                                    word=clean_w,
                                    start=round(curr_time, 3),
                                    end=round(curr_time + word_dur, 3)
                                ))
                                curr_time += word_dur
                                
                    if alignment_list:
                        alignment_str = json.dumps(alignment_list)
                        log(f"Generated alignment data: {{len(alignment_list)}} words")

                # Upload output WAV along with any alignment data
                data_payload = {{}}
                if alignment_str:
                    data_payload["alignment"] = alignment_str

                with open(local_out_path, "rb") as out_file:
                    files = {{"file": (f"{{job_id}}.wav", out_file, "audio/wav")}}
                    upload_res = make_request(
                        "POST", 
                        f"/v1/internal/jobs/{{job_id}}/output", 
                        files=files,
                        data=data_payload
                    )
                    
                if upload_res.status_code == 200:
                    log(f"Successfully uploaded job {{job_id}} output audio.")
                else:
                    raise Exception(f"Failed to upload audio to gateway: {{upload_res.status_code}} - {{upload_res.text}}")

                if os.path.exists(local_out_path):
                    os.remove(local_out_path)

            except Exception as inner_e:
                err_str = str(inner_e)
                trace = traceback.format_exc()
                log(f"Error executing job {{job_id}}: {{err_str}}\\n{{trace}}")
                
                make_request(
                    "POST",
                    f"/v1/internal/jobs/{{job_id}}/status",
                    json={{
                        "status": "failed",
                        "message": "Lỗi xử lý âm thanh.",
                        "progress": 100,
                        "error_message": f"{{err_str}}\\n{{trace}}"
                    }}
                )

        except Exception as e:
            log(f"Network or loop error: {{e}}")
            time.sleep(POLL_INTERVAL)

    log("Worker execution finished.")

if __name__ == '__main__':
    main()
"""
        else:
            # Fallback values for job parameters
            # Fallback values for job parameters
            job_params = {
                "id": "test_push",
                "job_type": "auto_voice",
                "text": "Xin chào, đây là bản thử nghiệm đẩy kết nối Kaggle.",
                "ref_text": None,
                "instruct": None,
                "voice_sample_id": None,
                "speed": 1.0,
                "num_step": 32,
                "denoise": True,
                "guidance_scale": 2.0,
                "t_shift": 0.1,
                "position_temperature": 5.0,
                "class_temperature": 0.0,
                "layer_penalty_factor": 5.0,
                "duration": None,
                "preprocess_prompt": True,
                "postprocess_output": True,
                "audio_chunk_duration": 15.0,
                "audio_chunk_threshold": 30.0,
                "language": None,
                "pad_duration": None,
                "fade_duration": None
            }

            if job:
                if isinstance(job, dict):
                    for k in job_params.keys():
                        if k in job:
                            job_params[k] = job[k]
                else:
                    for k in job_params.keys():
                        attr_val = getattr(job, k if k != "id" else "id", None)
                        if attr_val is not None:
                            job_params[k] = attr_val

            job_id = job_params["id"]
            job_type = job_params["job_type"]
            text = job_params["text"]
            ref_text = job_params["ref_text"]
            instruct = job_params["instruct"]
            voice_sample_id = job_params["voice_sample_id"]
            speed = job_params["speed"]
            num_step = job_params["num_step"]
            denoise = job_params["denoise"]
            guidance_scale = job_params["guidance_scale"]
            t_shift = job_params["t_shift"]
            position_temperature = job_params["position_temperature"]
            class_temperature = job_params["class_temperature"]
            layer_penalty_factor = job_params["layer_penalty_factor"]
            duration = job_params["duration"]
            preprocess_prompt = job_params["preprocess_prompt"]
            postprocess_output = job_params["postprocess_output"]
            audio_chunk_duration = job_params["audio_chunk_duration"]
            audio_chunk_threshold = job_params["audio_chunk_threshold"]
            language = job_params["language"]
            pad_duration = job_params["pad_duration"]
            fade_duration = job_params["fade_duration"]

            ref_audio_url = None
            if voice_sample_id:
                base_url = public_api_url or settings.PUBLIC_API_BASE_URL
                ref_audio_url = f"{base_url.rstrip('/')}/v1/internal/files/voice-samples/{voice_sample_id}"

            # Pure Python batch execution script template
            code = f"""import os
import sys
import time
import uuid
import tempfile
import traceback
import requests
import warnings
import shutil
import zipfile
import json
import subprocess
from urllib.parse import urlparse

os.environ["CUDA_MODULE_LOADING"] = "LAZY"
os.environ["PYTHONWARNINGS"] = "ignore"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
os.environ["HF_HUB_DISABLE_XET"] = "1"
os.environ["HF_HUB_ETAG_TIMEOUT"] = "15"
os.environ["HF_TOKEN"] = {repr(hf_token)}
os.environ["HUGGING_FACE_HUB_TOKEN"] = {repr(hf_token)}
warnings.filterwarnings("ignore")

def ensure_dependencies():
    \"\"\"Dynamically checks and installs required packages inside the Kaggle environment if missing.\"\"\"
    missing = []
    try:
        import omnivoice
    except ImportError:
        missing.append("omnivoice")
    try:
        import soundfile
    except ImportError:
        missing.append("soundfile")
    try:
        import modelscope
    except ImportError:
        missing.append("modelscope")
    try:
        import sentencepiece
    except ImportError:
        missing.append("sentencepiece")
    try:
        import tiktoken
    except ImportError:
        missing.append("tiktoken")
    try:
        import faster_whisper
    except ImportError:
        missing.append("faster-whisper")
        
    if missing:
        import subprocess
        print(f"Installing missing dependencies: {{', '.join(missing)}}")
        try:
            # Install packages silently with fast flags
            subprocess.check_call([
                sys.executable, "-m", "pip", "install", "-q", 
                "--no-cache-dir", "--prefer-binary", 
                "--no-warn-script-location"
            ] + missing)
            print("Dependencies installed successfully.")
        except Exception as e:
            print(f"Failed to install dependencies: {{e}}")
            sys.exit(1)

# Ensure dependencies are available before anything else runs
ensure_dependencies()

import torch
import soundfile as sf
from omnivoice import OmniVoice

JOB_ID = {repr(job_id)}
JOB_TYPE = {repr(job_type)}
TEXT = {repr(text)}
REF_AUDIO_URL = {repr(ref_audio_url)}
REF_TEXT = {repr(ref_text)}
INSTRUCT = {repr(instruct)}
SPEED = {speed}
NUM_STEP = {num_step}
DENOISE = {denoise}
GUIDANCE_SCALE = {guidance_scale}
T_SHIFT = {t_shift}
POSITION_TEMPERATURE = {position_temperature}
CLASS_TEMPERATURE = {class_temperature}
LAYER_PENALTY_FACTOR = {layer_penalty_factor}
DURATION = {duration}
PREPROCESS_PROMPT = {preprocess_prompt}
POSTPROCESS_OUTPUT = {postprocess_output}
AUDIO_CHUNK_DURATION = {audio_chunk_duration}
AUDIO_CHUNK_THRESHOLD = {audio_chunk_threshold}
LANGUAGE = {repr(language)}
PAD_DURATION = {pad_duration}
FADE_DURATION = {fade_duration}
WORKER_TOKEN = {repr(worker_token)}

def main():
    print(f"Starting Kaggle Batch Worker for Job {{JOB_ID}} ({{JOB_TYPE}})")
    sys.stdout.flush()
    
    local_ref_path = None
    if JOB_TYPE in ["clone_voice", "asr"] and REF_AUDIO_URL:
        print(f"Downloading audio from {{REF_AUDIO_URL}}...")
        sys.stdout.flush()
        headers = {{}}
        if WORKER_TOKEN:
            headers["Authorization"] = f"Bearer {{WORKER_TOKEN}}"
        
        try:
            res = requests.get(REF_AUDIO_URL, headers=headers, stream=True)
            if res.status_code == 200:
                local_ref_path = "ref_audio.wav"
                with open(local_ref_path, "wb") as f:
                    for chunk in res.iter_content(chunk_size=8192):
                        f.write(chunk)
                print(f"Downloaded reference voice sample successfully to {{local_ref_path}}")
            else:
                print(f"Failed to download reference audio: {{res.status_code}} - {{res.text}}")
                sys.exit(1)
        except Exception as e:
            print(f"Error downloading reference audio: {{e}}")
            sys.exit(1)

    print("Loading OmniVoice model...")
    sys.stdout.flush()
    try:
        model_dir = None
        model_loaded = False
        
        # 1. First priority: Original Hugging Face Hub (direct download)
        try:
            print("Attempting to load model from Hugging Face Hub...")
            sys.stdout.flush()
            model = OmniVoice.from_pretrained(
                "k2-fsa/OmniVoice",
                device_map="cuda:0",
                dtype=torch.float16,
                load_asr=True,
            )
            print("OmniVoice model loaded successfully from Hugging Face Hub.")
            sys.stdout.flush()
            model_loaded = True
        except Exception as hf_err:
            print(f"Warning: Failed to load from Hugging Face Hub (CDN issue?): {{hf_err}}")
            sys.stdout.flush()
            model_loaded = False
        
        # 2. Second priority: Mounted Kaggle Dataset (Fallback)
        if not model_loaded:
            if os.path.exists("/kaggle/input"):
                for root, dirs, files in os.walk("/kaggle/input"):
                    if "model.safetensors" in files and "config.json" in files:
                        if not root.endswith("audio_tokenizer"):
                            model_dir = root
                            print(f"Found mounted model weights at: {{model_dir}}. Loading instantly...")
                            sys.stdout.flush()
                            break
        
        # 3. Third priority: ModelScope fallback (Stable alternative source if HF is down)
        if not model_loaded and not model_dir:
            try:
                from modelscope import snapshot_download
                print("Falling back to ModelScope to download model weights...")
                sys.stdout.flush()
                model_dir = snapshot_download("k2-fsa/OmniVoice")
                print(f"Model weights loaded locally via ModelScope at: {{model_dir}}")
                sys.stdout.flush()
            except Exception as ms_err:
                print(f"CRITICAL: Failed to download from ModelScope: {{ms_err}}")
                sys.stdout.flush()
                model_dir = "k2-fsa/OmniVoice"

        # Load from model_dir if it was not loaded from Hugging Face directly
        if not model_loaded:
            # Check if tokenizer files are missing from model_dir
            tokenizer_json = os.path.join(model_dir, "tokenizer.json")
            tokenizer_config = os.path.join(model_dir, "tokenizer_config.json")
            if not os.path.exists(tokenizer_json) or not os.path.exists(tokenizer_config):
                print("Tokenizer files are missing from local directory. Merging with downloaded tokenizer files...")
                sys.stdout.flush()
                import tempfile
                import shutil
                temp_model_dir = tempfile.mkdtemp()
                # Create symbolic links to all files in model_dir
                for f in os.listdir(model_dir):
                    src_file = os.path.join(model_dir, f)
                    dst_file = os.path.join(temp_model_dir, f)
                    if os.path.isfile(src_file):
                        try:
                            os.symlink(src_file, dst_file)
                        except Exception:
                            shutil.copy2(src_file, dst_file)
                # Download missing tokenizer files from Hugging Face Hub (or ModelScope fallback)
                for filename in ["tokenizer.json", "tokenizer_config.json"]:
                    dst_file = os.path.join(temp_model_dir, filename)
                    if not os.path.exists(dst_file):
                        success = False
                        # 1. Try Hugging Face first
                        try:
                            print(f"Downloading {{filename}} from Hugging Face...")
                            sys.stdout.flush()
                            res = requests.get(f"https://huggingface.co/k2-fsa/OmniVoice/resolve/main/{{filename}}", timeout=30)
                            if res.status_code == 200:
                                with open(dst_file, "wb") as out_f:
                                    out_f.write(res.content)
                                success = True
                                print(f"Successfully downloaded {{filename}} from Hugging Face.")
                                sys.stdout.flush()
                            else:
                                print(f"Warning: Failed to download {{filename}} from HF (status: {{res.status_code}})")
                                sys.stdout.flush()
                        except Exception as dl_err:
                            print(f"Warning: Failed to download {{filename}} from HF: {{dl_err}}")
                            sys.stdout.flush()
                        
                        # 2. Try ModelScope fallback
                        if not success:
                            try:
                                print(f"Attempting to download {{filename}} from ModelScope...")
                                sys.stdout.flush()
                                from modelscope.hub.file_download import model_file_download
                                cache_file = model_file_download("k2-fsa/OmniVoice", file_path=filename)
                                if cache_file and os.path.exists(cache_file):
                                    import shutil
                                    shutil.copy2(cache_file, dst_file)
                                    success = True
                                    print(f"Successfully retrieved {{filename}} from ModelScope.")
                                    sys.stdout.flush()
                            except Exception as ms_dl_err:
                                print(f"Warning: Failed to download {{filename}} from ModelScope: {{ms_dl_err}}")
                                sys.stdout.flush()
                                
                        if not success:
                            raise FileNotFoundError(f"Tokenizer file '{{filename}}' is missing and could not be downloaded from Hugging Face or ModelScope. Aborting.")
                model_dir = temp_model_dir

            model = OmniVoice.from_pretrained(
                model_dir,
                device_map="cuda:0",
                dtype=torch.float16,
                load_asr=True,
            )
            print("OmniVoice model loaded successfully from local path.")
            sys.stdout.flush()
        print("OmniVoice model loaded successfully.")
    except Exception as e:
        print(f"CRITICAL ERROR loading OmniVoice model: {{e}}")
        sys.stdout.flush()
        sys.exit(1)

    print("Generating audio...")
    sys.stdout.flush()
    try:
        if JOB_TYPE == "asr":
            if not local_ref_path:
                raise Exception("Missing audio path for ASR")
            print(f"Transcribing audio {{local_ref_path}}...")
            sys.stdout.flush()
            
            asr_res = model._asr_pipe(local_ref_path, return_timestamps="word")
            transcribed_text = asr_res.get("text", "").strip()
            chunks = asr_res.get("chunks", [])
            
            import json
            chunks_json = json.dumps(chunks)
            
            print(f"ASR complete. Text: {{transcribed_text}}")
            sys.stdout.flush()
            
            if local_ref_path and os.path.exists(local_ref_path):
                os.remove(local_ref_path)
                
            headers = {{}}
            if WORKER_TOKEN:
                headers["Authorization"] = f"Bearer {{WORKER_TOKEN}}"
                
            res = requests.post(
                f"{{PUBLIC_API_URL}}/v1/internal/jobs/{{JOB_ID}}/asr",
                headers=headers,
                json={{"text": transcribed_text, "alignment": chunks_json}}
            )
            if res.status_code == 200:
                print("ASR result uploaded successfully.")
                sys.stdout.flush()
                sys.exit(0)
            else:
                print(f"Failed to upload ASR result: {{res.status_code}} - {{res.text}}")
                sys.stdout.flush()
                sys.exit(1)

        generate_args = {{
            "text": TEXT
        }}
        
        if JOB_TYPE == "clone_voice":
            if not local_ref_path:
                raise Exception("Missing reference audio path for clone_voice")
            print(f"Generating voice cloning for: {{TEXT}}")
            generate_args["ref_audio"] = local_ref_path
            if REF_TEXT:
                generate_args["ref_text"] = REF_TEXT
        elif JOB_TYPE in ["voice_design_preview", "voice_design_tts"]:
            print(f"Generating voice design for: {{TEXT}} with instruct: {{INSTRUCT}}")
            generate_args["instruct"] = INSTRUCT
        elif JOB_TYPE == "auto_voice":
            print(f"Generating auto voice for: {{TEXT}}")
        else:
            raise Exception(f"Unknown job type: {{JOB_TYPE}}")

        # Add optional parameter inputs if they are not None
        params_map = {{
            "num_step": NUM_STEP,
            "denoise": DENOISE,
            "guidance_scale": GUIDANCE_SCALE,
            "t_shift": T_SHIFT,
            "position_temperature": POSITION_TEMPERATURE,
            "class_temperature": CLASS_TEMPERATURE,
            "layer_penalty_factor": LAYER_PENALTY_FACTOR,
            "duration": DURATION,
            "speed": SPEED,
            "preprocess_prompt": PREPROCESS_PROMPT,
            "postprocess_output": POSTPROCESS_OUTPUT,
            "audio_chunk_duration": AUDIO_CHUNK_DURATION,
            "audio_chunk_threshold": AUDIO_CHUNK_THRESHOLD,
            "language": LANGUAGE,
            "pad_duration": PAD_DURATION,
            "fade_duration": FADE_DURATION
        }}
        for key, val in params_map.items():
            if val is not None:
                generate_args[key] = val

        print(f"Calling model.generate with arguments: {{list(generate_args.keys())}}")
        audio_result = model.generate(**generate_args)

        # Save to output.wav in the current directory (which is /kaggle/working/ output folder)
        output_filename = "output.wav"
        sf.write(output_filename, audio_result[0], 24000, format='WAV', subtype='PCM_16')
        print(f"Generated audio saved successfully to {{output_filename}}")
        sys.stdout.flush()

    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"Generation failed: {{e}}\\n{{error_trace}}")
        sys.stdout.flush()
        sys.exit(1)

if __name__ == '__main__':
    main()
"""

        with open(worker_path, "w", encoding="utf-8") as f:
            f.write(code)
            
        print(f"[KaggleNotebookBuilder] Generated worker script at: {worker_path}")
        return worker_path

    @staticmethod
    def prepare_all(job=None, db=None, public_api_url: str = None, is_daemon: bool = True, user_id: str = None) -> str:
        """
        Runs the full prepare pipeline: ensures directory,
        writes requirements.txt, kernel-metadata.json, and omnivoice_worker.py.
        Returns the absolute path of the worker directory.
        """
        if not user_id and job:
            if isinstance(job, dict):
                user_id = job.get("user_id")
            else:
                user_id = getattr(job, "user_id", None)

        # Resolve settings/DB configs
        from app.services.kaggle_orchestrator import KaggleOrchestrator
        username, _, kernel_ref, worker_dir = KaggleOrchestrator.get_credentials(db, user_id)
        
        # Resolve public_api_url dynamically if not passed
        if not public_api_url:
            public_api_url = settings.PUBLIC_API_BASE_URL
            
        # Hugging Face Space auto-detection
        if not public_api_url and os.environ.get("SPACE_HOST"):
            public_api_url = f"https://{os.environ.get('SPACE_HOST')}"
            print(f"[KaggleNotebookBuilder] Auto-detected Hugging Face Space Host URL: {public_api_url}")
            
        # Resolve accelerator settings
        accelerator = settings.KAGGLE_ACCELERATOR
        if db:
            from app.models import SystemSetting
            db_acc = db.query(SystemSetting).filter(SystemSetting.key == "kaggle_accelerator").first()
            if db_acc and db_acc.value.strip():
                accelerator = db_acc.value.strip()
                
            if user_id:
                from app.models import UserSetting
                u_acc = db.query(UserSetting).filter(UserSetting.user_id == user_id, UserSetting.key == "kaggle_accelerator").first()
                if u_acc and u_acc.value.strip():
                    accelerator = u_acc.value.strip()
        
        # Construct dynamic slug and directory based on worker_id
        worker_id = None
        if job:
            if isinstance(job, dict):
                worker_id = job.get("worker_id")
            else:
                worker_id = getattr(job, "worker_id", None)
                
        if worker_id == "worker_2":
            slug = "omnivoice-worker-2"
            worker_dir = f"{worker_dir}-2"
        else:
            slug = "omnivoice-worker-1"
            worker_dir = f"{worker_dir}-1"
            
        title = slug.replace("-", " ").title()

        worker_dir_abs = KaggleNotebookBuilder.ensure_worker_dir(worker_dir)
        KaggleNotebookBuilder.generate_requirements(worker_dir_abs)
        KaggleNotebookBuilder.generate_metadata(worker_dir_abs, username, slug, title, accelerator)
        
        # Resolve worker token as user API key if applicable
        worker_token = settings.WORKER_TOKEN
        if user_id and db:
            from app.models import User
            user = db.query(User).filter(User.id == user_id).first()
            if user and user.api_key:
                worker_token = user.api_key

        # Generate worker script with embedded credentials and API URLs
        KaggleNotebookBuilder.generate_worker_code(worker_dir_abs, job, public_api_url, worker_token, is_daemon=is_daemon, db=db)
        
        return worker_dir_abs

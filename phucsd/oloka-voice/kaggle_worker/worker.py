import os
import sys
import time
import uuid
import tempfile
import traceback
import requests
import json
import zipfile
import shutil

def ensure_dependencies():
    """Dynamically checks and installs required packages inside the Kaggle environment if missing."""
    missing = []
    try:
        import omnivoice
    except ImportError:
        missing.append("omnivoice")
    try:
        import soundfile
    except ImportError:
        missing.append("soundfile")
        
    if missing:
        import subprocess
        print(f"Installing missing dependencies: {', '.join(missing)}")
        try:
            # Install packages silently
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q"] + missing)
            print("Dependencies installed successfully.")
        except Exception as e:
            print(f"Failed to install dependencies: {e}")
            sys.exit(1)

# Ensure dependencies are available before anything else runs
ensure_dependencies()

import soundfile as sf

# Load configuration
PUBLIC_API_BASE_URL = 'http://localhost:6458'.rstrip("/")
WORKER_TOKEN = 'default_secure_worker_token_12345'
WORKER_ID = 'kaggle_worker_d9c20d'
IDLE_TIMEOUT = int(os.environ.get("WORKER_IDLE_TIMEOUT_SECONDS", "600"))
POLL_INTERVAL = int(os.environ.get("WORKER_POLL_INTERVAL_SECONDS", "3"))

HEADERS = {
    "Authorization": f"Bearer {WORKER_TOKEN}"
}

def log(msg: str):
    print(f"[{datetime_str()}] [Worker-{WORKER_ID}] {msg}")
    sys.stdout.flush()

def datetime_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")

def make_request(method: str, path: str, **kwargs) -> requests.Response:
    url = f"{PUBLIC_API_BASE_URL}{path}"
    if "headers" in kwargs:
        kwargs["headers"].update(HEADERS)
    else:
        kwargs["headers"] = HEADERS
    return requests.request(method, url, **kwargs)

def main():
    if not PUBLIC_API_BASE_URL:
        print("ERROR: PUBLIC_API_BASE_URL environment variable is not set. Exiting.")
        sys.exit(1)

    log(f"Starting Kaggle Worker. Gateway: {PUBLIC_API_BASE_URL}")
    
    # 1. Register starting
    try:
        make_request(
            "POST", 
            "/v1/internal/workers/register", 
            json={"worker_id": WORKER_ID, "status": "starting", "message": "OmniVoice worker starting up..."}
        )
    except Exception as e:
        print(f"Failed to register startup with gateway: {e}. Check network connection or PUBLIC_API_BASE_URL.")
        sys.exit(1)

    # 2. Load OmniVoice
    log("Loading OmniVoice model into memory...")
    try:
        import torch
        from omnivoice import OmniVoice

        # Send heartbeat reporting loading_model status
        make_request(
            "POST", 
            "/v1/internal/workers/heartbeat", 
            json={"worker_id": WORKER_ID, "status": "loading_model", "message": "Loading model weights..."}
        )

        model = OmniVoice.from_pretrained(
            "k2-fsa/OmniVoice",
            device_map="cuda:0",
            dtype=torch.float16,
            load_asr=True,
        )
        log("OmniVoice model loaded successfully.")
    except Exception as e:
        error_trace = traceback.format_exc()
        log(f"CRITICAL ERROR loading OmniVoice model: {e}")
        try:
            make_request(
                "POST", 
                "/v1/internal/workers/register", 
                json={"worker_id": WORKER_ID, "status": "failed", "message": f"Model load failed: {str(e)}"}
            )
        except Exception:
            pass
        sys.exit(1)

    # Register as Ready
    make_request(
        "POST", 
        "/v1/internal/workers/register", 
        json={"worker_id": WORKER_ID, "status": "ready", "message": "OmniVoice model ready for requests."}
    )

    idle_seconds = 0
    log("Entering job polling loop...")
    
    while True:
        try:
            # Send heartbeat
            make_request(
                "POST",
                "/v1/internal/workers/heartbeat",
                json={"worker_id": WORKER_ID, "status": "idle", "message": f"Worker polling. Idle time: {idle_seconds}s"}
            )

            # Poll for job
            response = make_request("GET", f"/v1/internal/jobs/next?worker_id={WORKER_ID}")
            if response.status_code == 401:
                log("Unauthorized (401). Worker token invalid. Exiting.")
                break
                
            if response.status_code != 200:
                log(f"Warning: Poll returned status code {response.status_code}")
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
                    log(f"Idle timeout of {IDLE_TIMEOUT}s reached. Initiating shutdown.")
                    make_request(
                        "POST", 
                        "/v1/internal/workers/shutdown", 
                        json={"worker_id": WORKER_ID, "reason": "idle_timeout"}
                    )
                    break
                continue

            # Reset idle counter on job receipt
            idle_seconds = 0
            job_id = job["job_id"]
            job_type = job["job_type"]
            log(f"Processing job {job_id} ({job_type})")

            # Report busy status
            make_request(
                "POST",
                "/v1/internal/workers/heartbeat",
                json={"worker_id": WORKER_ID, "status": "busy", "current_job_id": job_id, "message": f"Running {job_type}"}
            )

            # Update job status: loading_model
            make_request(
                "POST",
                f"/v1/internal/jobs/{job_id}/status",
                json={"status": "loading_model", "message": "Đang tải OmniVoice...", "progress": 30}
            )

            # Process job based on type
            try:
                local_ref_path = None
                ref_audio_url = job.get("ref_audio_url")
                
                if job_type == "dub_segments":
                    make_request(
                        "POST",
                        f"/v1/internal/jobs/{job_id}/status",
                        json={"status": "generating_audio", "message": "Đang tổng hợp từng đoạn thoại bằng OmniVoice...", "progress": 50}
                    )
                    translated_subs = json.loads(job["text"])
                    temp_dir = tempfile.mkdtemp(prefix="dub_segs_")
                    
                    # Download reference audio for voice cloning if available
                    if ref_audio_url:
                        res = make_request("GET", ref_audio_url.replace(PUBLIC_API_BASE_URL, ""), stream=True)
                        if res.status_code == 200:
                            temp_fd, local_ref_path = tempfile.mkstemp(suffix=".wav")
                            os.close(temp_fd)
                            with open(local_ref_path, "wb") as f:
                                for chunk in res.iter_content(chunk_size=8192):
                                    f.write(chunk)

                    for seg in translated_subs:
                        clean_t = str(seg.get("text", "")).strip()
                        if not clean_t:
                            continue
                        seg_args = {"text": clean_t}
                        # Do not force English speaker ref_audio onto Vietnamese text to avoid English accent prompt bleed!
                        # Only use ref_audio if explicitly provided as a native target voice sample
                        if local_ref_path and os.path.exists(local_ref_path) and job.get("use_voice_clone"):
                            seg_args["ref_audio"] = local_ref_path
                        
                        log(f"Synthesizing segment {seg['id']} via OmniVoice: '{clean_t[:30]}...'")
                        seg_res = model.generate(**seg_args)
                        seg_out_path = os.path.join(temp_dir, f"segment_{seg['id']}.wav")
                        sf.write(seg_out_path, seg_res[0], 24000, format='WAV', subtype='PCM_16')

                    if local_ref_path and os.path.exists(local_ref_path):
                        os.remove(local_ref_path)

                    # Pack into ZIP
                    zip_fd, zip_path = tempfile.mkstemp(suffix=".zip")
                    os.close(zip_fd)
                    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_f:
                        for f_name in os.listdir(temp_dir):
                            zip_f.write(os.path.join(temp_dir, f_name), arcname=f_name)

                    make_request(
                        "POST",
                        f"/v1/internal/jobs/{job_id}/status",
                        json={"status": "exporting_wav", "message": "Đang hoàn tất gói âm thanh OmniVoice...", "progress": 90}
                    )

                    with open(zip_path, "rb") as out_file:
                        files = {"file": (f"{job_id}.zip", out_file, "application/zip")}
                        upload_res = make_request("POST", f"/v1/internal/jobs/{job_id}/output", files=files)

                    shutil.rmtree(temp_dir, ignore_errors=True)
                    if os.path.exists(zip_path):
                        os.remove(zip_path)
                    
                    if upload_res.status_code == 200:
                        log(f"Successfully uploaded dub_segments output for {job_id}.")
                    else:
                        raise Exception(f"Failed to upload dub_segments output: {upload_res.status_code} - {upload_res.text}")
                    return

                if job_type == "clone_voice" and ref_audio_url:
                    make_request(
                        "POST",
                        f"/v1/internal/jobs/{job_id}/status",
                        json={"status": "preparing_input", "message": "Đang tải tệp âm thanh tham chiếu...", "progress": 45}
                    )
                    
                    # Securely download voice sample file
                    res = make_request("GET", ref_audio_url.replace(PUBLIC_API_BASE_URL, ""), stream=True)
                    if res.status_code == 200:
                        temp_fd, local_ref_path = tempfile.mkstemp(suffix=".wav")
                        os.close(temp_fd)
                        with open(local_ref_path, "wb") as f:
                            for chunk in res.iter_content(chunk_size=8192):
                                f.write(chunk)
                        log(f"Downloaded reference voice sample to {local_ref_path}")
                    else:
                        raise Exception(f"Failed to download reference audio from gateway: {res.status_code} - {res.text}")

                make_request(
                    "POST",
                    f"/v1/internal/jobs/{job_id}/status",
                    json={"status": "generating_audio", "message": "Đang xử lý âm thanh...", "progress": 70}
                )

                # Build generate arguments
                generate_args = {
                    "text": job["text"]
                }
                
                if job_type == "clone_voice":
                    generate_args["ref_audio"] = local_ref_path
                    if job.get("ref_text"):
                        generate_args["ref_text"] = job["ref_text"]
                elif job_type in ["voice_design_preview", "voice_design_tts"]:
                    generate_args["instruct"] = job.get("instruct")
                elif job_type != "auto_voice":
                    raise Exception(f"Unknown job type: {job_type}")
                
                # Check for optional OmniVoice parameters in job payload
                optional_keys = [
                    "num_step", "denoise", "guidance_scale", "t_shift",
                    "position_temperature", "class_temperature", "layer_penalty_factor",
                    "duration", "speed", "preprocess_prompt", "postprocess_output",
                    "audio_chunk_duration", "audio_chunk_threshold"
                ]
                for key in optional_keys:
                    if key in job and job[key] is not None:
                        generate_args[key] = job[key]

                log(f"Calling model.generate with arguments: {list(generate_args.keys())}")
                audio_result = model.generate(**generate_args)

                # Clean up local ref path if exists
                if local_ref_path and os.path.exists(local_ref_path):
                    os.remove(local_ref_path)

                # Export WAV
                make_request(
                    "POST",
                    f"/v1/internal/jobs/{job_id}/status",
                    json={"status": "exporting_wav", "message": "Đang xuất WAV...", "progress": 90}
                )
                
                temp_out_fd, local_out_path = tempfile.mkstemp(suffix=".wav")
                os.close(temp_out_fd)
                
                sf.write(local_out_path, audio_result[0], 24000, format='WAV', subtype='PCM_16')
                log(f"Generated audio saved to {local_out_path}")

                # Generate proportional word alignments if requested to save GPU/CPU by default
                alignment_str = None
                if job.get("with_alignment"):
                    words = (job.get("text") or "").split()
                    if words:
                        duration_sec = len(audio_result[0]) / 24000.0
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
                        log(f"Generated alignment data: {len(alignment_list)} words")

                # Upload output WAV along with any alignment data
                data_payload = {}
                if alignment_str:
                    data_payload["alignment"] = alignment_str

                with open(local_out_path, "rb") as out_file:
                    files = {"file": (f"{job_id}.wav", out_file, "audio/wav")}
                    upload_res = make_request(
                        "POST", 
                        f"/v1/internal/jobs/{job_id}/output", 
                        files=files,
                        data=data_payload
                    )
                    
                if upload_res.status_code == 200:
                    log(f"Successfully uploaded job {job_id} output audio.")
                else:
                    raise Exception(f"Failed to upload audio to gateway: {upload_res.status_code} - {upload_res.text}")

                if os.path.exists(local_out_path):
                    os.remove(local_out_path)

            except Exception as inner_e:
                err_str = str(inner_e)
                trace = traceback.format_exc()
                log(f"Error executing job {job_id}: {err_str}\n{trace}")
                
                make_request(
                    "POST",
                    f"/v1/internal/jobs/{job_id}/status",
                    json={
                        "status": "failed",
                        "message": "Lỗi xử lý âm thanh.",
                        "progress": 100,
                        "error_message": f"{err_str}\n{trace}"
                    }
                )

        except Exception as e:
            log(f"Network or loop error: {e}")
            time.sleep(POLL_INTERVAL)

    log("Worker execution finished.")

if __name__ == "__main__":
    main()

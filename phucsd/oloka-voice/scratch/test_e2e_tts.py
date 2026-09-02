import os
import sys
import time
import requests
import subprocess

# Backend HF Space base URL
API_BASE = "https://phucsd-omnivoice-gateway-backend.hf.space"
KAGGLE_USER = "phcnguynhukendykerry"
KAGGLE_KEY = "a783ab314abae18f4d109589699bd437"

# Set credentials locally too for Kaggle CLI checks
os.environ["KAGGLE_USERNAME"] = KAGGLE_USER
os.environ["KAGGLE_KEY"] = KAGGLE_KEY
os.environ["PYTHONUTF8"] = "1"

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")
    sys.stdout.flush()

def check_kaggle_status_cli():
    cmd = [sys.executable, "-c", "from kaggle.cli import main; main()", "kernels", "status", f"{KAGGLE_USER}/omnivoice-worker"]
    res = subprocess.run(cmd, capture_output=True, text=True, shell=False)
    return res.stdout.strip()

def main():
    log("=== 1. Setting Kaggle credentials on backend ===")
    settings_payload = {
        "kaggle_username": KAGGLE_USER,
        "kaggle_key": KAGGLE_KEY,
        "kaggle_kernel_ref": f"{KAGGLE_USER}/omnivoice-worker",
        "kaggle_kernel_slug": "omnivoice-worker",
        "kaggle_kernel_title": "Omnivoice Worker",
        "kaggle_accelerator": "NvidiaTeslaT4"
    }
    
    r = requests.post(f"{API_BASE}/v1/settings", json=settings_payload)
    if r.status_code == 200:
        log("Backend settings updated successfully: " + str(r.json()))
    else:
        log(f"Failed to update settings: {r.status_code} - {r.text}")
        sys.exit(1)

    log("\n=== 2. Testing Kaggle connection from backend ===")
    r = requests.post(f"{API_BASE}/v1/settings/test-kaggle")
    if r.status_code == 200:
        res = r.json()
        log(f"Backend test-kaggle: {res}")
        if not res.get("success"):
            sys.exit(1)
    else:
        log(f"Failed test-kaggle endpoint: {r.status_code} - {r.text}")
        sys.exit(1)

    log("\n=== 3. Creating a new TTS Job (auto_voice) ===")
    job_payload = {
        "mode": "auto_voice",
        "text": "Xin chào, đây là bản thử nghiệm từ robot Omnivoice, chạy trên hệ thống GPU T4 x2 của Kaggle."
    }
    r = requests.post(f"{API_BASE}/v1/tts/jobs", json=job_payload)
    if r.status_code == 200:
        job_data = r.json()
        job_id = job_data["job_id"]
        log(f"TTS Job created! ID: {job_id}, Initial Status: {job_data['status']}")
    else:
        log(f"Failed to create job: {r.status_code} - {r.text}")
        sys.exit(1)

    log("\n=== 4. Polling Job status and Kaggle Kernel status ===")
    log("Starting polling loop (every 10 seconds)...")
    
    start_time = time.time()
    last_kernel_status = ""
    
    while True:
        # Check job status from backend
        job_res = requests.get(f"{API_BASE}/v1/tts/jobs/{job_id}")
        if job_res.status_code != 200:
            log(f"Error fetching job status: {job_res.status_code}")
            time.sleep(10)
            continue
            
        job_info = job_res.json()
        status = job_info["status"]
        message = job_info["message"]
        progress = job_info["progress"]
        err_msg = job_info.get("error_message")
        
        # Check Kaggle CLI kernel status
        k_status = check_kaggle_status_cli()
        if k_status != last_kernel_status:
            log(f"Kaggle Kernel Status Changed: {k_status}")
            last_kernel_status = k_status
            
        log(f"Job Status: {status} | Progress: {progress}% | Msg: {message}")
        if err_msg:
            log(f"Error Message: {err_msg}")
            
        if status == "completed":
            log("\n=== SUCCESS! Job completed successfully! ===")
            audio_url = f"{API_BASE}/v1/tts/jobs/{job_id}/audio"
            log(f"Download audio at: {audio_url}")
            break
        elif status == "failed":
            log("\n=== FAILED! Job failed. ===")
            break
            
        # Timeout after 20 minutes
        if time.time() - start_time > 1200:
            log("\n=== TIMEOUT! Job took too long. ===")
            break
            
        time.sleep(10)

if __name__ == "__main__":
    main()

import os
import sys
import time
import requests
import traceback

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

import torch
import soundfile as sf
from omnivoice import OmniVoice

JOB_ID = 'job_59b7d0df8607'
JOB_TYPE = 'auto_voice'
TEXT = 'Xin chào! Đây là bản tin chạy thử nghiệm hoàn toàn tự động từ hệ thống Kaggle Batch Worker. Âm thanh được tạo thành công!'
REF_AUDIO_URL = None
REF_TEXT = None
INSTRUCT = None
WORKER_TOKEN = 'default_secure_worker_token_12345'

def main():
    print(f"Starting Kaggle Batch Worker for Job {JOB_ID} ({JOB_TYPE})")
    sys.stdout.flush()
    
    local_ref_path = None
    if JOB_TYPE == "clone_voice" and REF_AUDIO_URL:
        print(f"Downloading reference voice sample from {REF_AUDIO_URL}...")
        sys.stdout.flush()
        headers = {}
        if WORKER_TOKEN:
            headers["Authorization"] = f"Bearer {WORKER_TOKEN}"
        
        try:
            res = requests.get(REF_AUDIO_URL, headers=headers, stream=True)
            if res.status_code == 200:
                local_ref_path = "ref_audio.wav"
                with open(local_ref_path, "wb") as f:
                    for chunk in res.iter_content(chunk_size=8192):
                        f.write(chunk)
                print(f"Downloaded reference voice sample successfully to {local_ref_path}")
            else:
                print(f"Failed to download reference audio: {res.status_code} - {res.text}")
                sys.exit(1)
        except Exception as e:
            print(f"Error downloading reference audio: {e}")
            sys.exit(1)

    print("Loading OmniVoice model...")
    sys.stdout.flush()
    try:
        model = OmniVoice.from_pretrained(
            "k2-fsa/OmniVoice",
            device_map="cuda:0",
            dtype=torch.float16,
            load_asr=True,
        )
        print("OmniVoice model loaded successfully.")
    except Exception as e:
        print(f"CRITICAL ERROR loading OmniVoice model: {e}")
        sys.stdout.flush()
        sys.exit(1)

    print("Generating audio...")
    sys.stdout.flush()
    try:
        audio_result = None
        if JOB_TYPE == "clone_voice":
            if not local_ref_path:
                raise Exception("Missing reference audio path for clone_voice")
            print(f"Generating voice cloning for: {TEXT}")
            audio_result = model.generate(
                text=TEXT,
                ref_audio=local_ref_path,
                ref_text=REF_TEXT,
            )
        elif JOB_TYPE in ["voice_design_preview", "voice_design_tts"]:
            print(f"Generating voice design for: {TEXT} with instruct: {INSTRUCT}")
            audio_result = model.generate(
                text=TEXT,
                instruct=INSTRUCT,
            )
        elif JOB_TYPE == "auto_voice":
            print(f"Generating auto voice for: {TEXT}")
            audio_result = model.generate(
                text=TEXT,
            )
        else:
            raise Exception(f"Unknown job type: {JOB_TYPE}")

        # Save to output.wav in the current directory (which is /kaggle/working/ output folder)
        output_filename = "output.wav"
        sf.write(output_filename, audio_result[0], 24000, format='WAV', subtype='PCM_16')
        print(f"Generated audio saved successfully to {output_filename}")
        sys.stdout.flush()

    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"Generation failed: {e}\n{error_trace}")
        sys.stdout.flush()
        sys.exit(1)

if __name__ == '__main__':
    main()

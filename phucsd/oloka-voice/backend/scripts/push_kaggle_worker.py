import os
import sys
import subprocess

# Add backend directory to Python path for importing app
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import settings
from app.services.kaggle_orchestrator import KaggleOrchestrator

def main():
    print("=== OMNIVOICE KAGGLE WORKER PUSH ===")
    
    # 1. Load credentials
    username, key, kernel_ref, worker_dir = KaggleOrchestrator.get_credentials()
    
    if not username or not key:
        print("ERROR: Kaggle credentials not configured. Please run prepare script or set .env.")
        sys.exit(1)
        
    worker_dir_abs = os.path.abspath(worker_dir)
    accelerator = settings.KAGGLE_ACCELERATOR
    timeout = settings.KAGGLE_TIMEOUT_SECONDS
    
    print(f"Worker Folder: {worker_dir_abs}")
    print(f"Kernel Reference: {username}/{settings.KAGGLE_KERNEL_SLUG}")
    print(f"Accelerator: {accelerator}")
    print(f"Push Timeout: {timeout} seconds")
    
    # Prepare subprocess environment
    env = os.environ.copy()
    env["KAGGLE_USERNAME"] = username
    env["KAGGLE_KEY"] = key
    env["PYTHONUTF8"] = "1"
    
    # Construct CLI command
    cmd = [sys.executable, "-c", "from kaggle.cli import main; main()", "kernels", "push", "-p", worker_dir_abs, "--timeout", str(timeout)]


        
    print(f"\nRunning command: {' '.join(cmd)}")
    print("Waiting for Kaggle to process request...")
    
    try:
        res = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            shell=False
        )
        stdout, stderr = res.communicate()
        
        if res.returncode == 0:
            print("\nSUCCESS: Kaggle worker pushed successfully!")
            print(f"Response: {stdout.strip()}")
        else:
            print(f"\nERROR: Kaggle push failed (exit code {res.returncode})")
            print(f"Stderr details: {stderr.strip()}")
            sys.exit(1)
    except Exception as e:
        print(f"\nException occurred during push: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

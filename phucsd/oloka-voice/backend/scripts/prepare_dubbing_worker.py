import os
import sys

# Add backend directory to Python path for importing app
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import settings
from app.services.dubbing_notebook_builder import DubbingNotebookBuilder
from app.services.kaggle_orchestrator import KaggleOrchestrator

def main():
    print("=== OMNIVOICE DEDICATED DUBBING WORKER PREPARATION ===")
    
    username, key, kernel_ref, worker_dir = KaggleOrchestrator.get_credentials()
    
    slug = "omnivoice-dubbing-worker"
    title = "OmniVoice Dedicated Dubbing Worker"
    
    errors = []
    if not settings.PUBLIC_API_BASE_URL:
        errors.append("PUBLIC_API_BASE_URL")
    if not settings.WORKER_TOKEN:
        errors.append("WORKER_TOKEN")
        
    if errors:
        print(f"ERROR: Missing required configurations in env or DB: {', '.join(errors)}")
        sys.exit(1)
        
    print(f"Validated settings successfully.")
    print(f"Public API Base URL: {settings.PUBLIC_API_BASE_URL}")
    
    try:
        worker_dir_abs = DubbingNotebookBuilder.prepare_all()
        print("\nSUCCESS: Dedicated Dubbing Kaggle worker directory prepared successfully!")
        print(f"Target Directory: {worker_dir_abs}")
    except Exception as e:
        print(f"\nFATAL ERROR during dubbing worker preparation: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

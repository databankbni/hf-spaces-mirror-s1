import os
import sys

# Add backend directory to Python path for importing app
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import settings
from app.services.kaggle_notebook_builder import KaggleNotebookBuilder
from app.services.kaggle_orchestrator import KaggleOrchestrator

def main():
    print("=== OMNIVOICE KAGGLE WORKER PREPARATION ===")
    
    # 1. Validate environment variables
    # Read settings/DB credentials
    username, key, kernel_ref, worker_dir = KaggleOrchestrator.get_credentials()
    
    slug = settings.KAGGLE_KERNEL_SLUG
    title = settings.KAGGLE_KERNEL_TITLE
    
    errors = []
    if not username:
        errors.append("KAGGLE_USERNAME")
    if not key:
        errors.append("KAGGLE_KEY")
    if not settings.PUBLIC_API_BASE_URL:
        errors.append("PUBLIC_API_BASE_URL")
    if not settings.WORKER_TOKEN:
        errors.append("WORKER_TOKEN")
        
    if errors:
        print(f"ERROR: Missing required configurations in env or DB: {', '.join(errors)}")
        print("Please configure them in your .env file or database settings.")
        sys.exit(1)
        
    print(f"Validated settings successfully.")
    print(f"Kaggle Username: {username}")
    print(f"Kaggle Kernel Slug: {slug}")
    print(f"Kaggle Kernel Title: {title}")
    print(f"Worker Directory: {worker_dir}")
    print(f"Public API Base URL: {settings.PUBLIC_API_BASE_URL}")
    
    # 2. Run builder
    try:
        worker_dir_abs = KaggleNotebookBuilder.prepare_all()
        print("\nSUCCESS: Kaggle worker directory prepared successfully!")
        print(f"Target Directory: {worker_dir_abs}")
    except Exception as e:
        print(f"\nFATAL ERROR during preparation: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

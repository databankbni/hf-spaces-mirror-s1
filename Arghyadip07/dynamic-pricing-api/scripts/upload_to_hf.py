import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from huggingface_hub import HfApi
from src.core.settings import settings
from src.core.settings import settings

def main():
    token = os.getenv("HF_TOKEN")
    if not token:
        print("HF_TOKEN not found in environment!")
        return
        
    api = HfApi(token=token)
    repo_id = "Arghyadip07/dynamic-pricing-api"
    
    files_to_upload = [
        "artifacts/lingam_causal_graph.dot",
        "artifacts/lingam_causal_graph.png"
    ]
    
    for file_path in files_to_upload:
        if os.path.exists(file_path):
            print(f"Uploading {file_path}...")
            api.upload_file(
                path_or_fileobj=file_path,
                path_in_repo=file_path,
                repo_id=repo_id,
                repo_type="space"
            )
            print(f"Successfully uploaded {file_path}")
        else:
            print(f"File not found: {file_path}")

if __name__ == "__main__":
    main()

import os
import shutil
from huggingface_hub import HfApi

def deploy():
    hf_token = os.environ.get("HF_TOKEN")
    hf_space = os.environ.get("HF_SPACE")
    
    if not hf_token or not hf_space:
        print("HF_TOKEN or HF_SPACE environment variables are not set. Skipping deployment.")
        return
        
    print(f"Starting deployment to Hugging Face Space: {hf_space}")
    
    # 1. Copy Dockerfile.hf to Dockerfile
    if os.path.exists("Dockerfile.hf"):
        shutil.copy("Dockerfile.hf", "Dockerfile")
        print("Copied Dockerfile.hf to Dockerfile")
    else:
        print("Warning: Dockerfile.hf not found.")
        
    # 2. Modify README.md in place (prepend frontmatter)
    readme_path = "README.md"
    if os.path.exists(readme_path):
        with open(readme_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        # Check if frontmatter already exists to avoid prepending multiple times
        frontmatter = (
            "---\n"
            "title: CustomerCore API\n"
            "emoji: 🚀\n"
            "colorFrom: blue\n"
            "colorTo: indigo\n"
            "sdk: docker\n"
            "app_port: 7860\n"
            "pinned: false\n"
            "---\n"
        )
        if not content.startswith("---"):
            new_content = frontmatter + content
            with open(readme_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            print("Prepended Hugging Face metadata to README.md")
        else:
            print("README.md already has frontmatter. Skipping modification.")
    else:
        print("Warning: README.md not found.")
        
    # 3. Upload to Hugging Face Spaces
    api = HfApi()
    
    ignore_patterns = [
        ".git/*",
        ".git",
        ".venv/*",
        ".venv",
        "__pycache__/*",
        "__pycache__",
        "*.pyc",
        ".pytest_cache/*",
        ".pytest_cache",
        ".ruff_cache/*",
        ".ruff_cache",
        "mlruns/*",
        "mlruns",
        "mlruns.db",
        "*.duckdb",
        "*.db",
        "logs/*",
        "logs",
        "*.log",
        "scratch/*",
        "scratch",
        "customercore_v*.docx",
        "customercore_v*.js",
        ".env",
        ".env.*",
        "BUILD_GUIDE.md",
        "CustomerCore_Progress_Summary.md"
    ]
    
    print("Uploading folder contents to HF Space...")
    try:
        api.upload_folder(
            folder_path=".",
            repo_id=hf_space,
            repo_type="space",
            token=hf_token,
            ignore_patterns=ignore_patterns
        )
        print("Successfully deployed to Hugging Face Spaces!")
    except Exception as e:
        print(f"Error uploading to Hugging Face: {e}")
        raise e

if __name__ == "__main__":
    deploy()

import os
import time
import requests
from typing import Optional
from app.config import settings

class S3StorageService:
    _hf_api = None
    _dataset_repo_id = "phucsd/omnivoice-audio-storage"

    @classmethod
    def get_hf_api(cls):
        if cls._hf_api is None:
            from huggingface_hub import HfApi
            token = os.environ.get("HF_TOKEN") or getattr(settings, "HF_TOKEN", None)
            cls._hf_api = HfApi(token=token) if token else HfApi()
            # Ensure dataset repo exists
            try:
                cls._hf_api.create_repo(
                    repo_id=cls._dataset_repo_id,
                    repo_type="dataset",
                    exist_ok=True,
                    private=False
                )
            except Exception as e:
                print(f"[S3StorageService] Repo init warning: {e}")
        return cls._hf_api

    @classmethod
    def upload_audio_to_s3_cdn(cls, local_path: str, filename: str) -> Optional[str]:
        """
        Uploads audio file directly to Hugging Face Dataset S3 LFS Storage.
        Returns direct AWS CloudFront / S3 CDN URL for instant playback bypassing FastAPI container.
        """
        if not local_path or not os.path.exists(local_path):
            return None

        try:
            api = cls.get_hf_api()
            repo_path = f"audio/{filename}"

            # Upload to HF S3 / LFS Storage
            api.upload_file(
                path_or_fileobj=local_path,
                path_in_repo=repo_path,
                repo_id=cls._dataset_repo_id,
                repo_type="dataset"
            )

            # Get direct CDN S3 URL
            dataset_url = f"https://huggingface.co/datasets/{cls._dataset_repo_id}/resolve/main/{repo_path}"
            
            # Resolve to direct AWS CloudFront S3 CDN edge link if possible
            try:
                res = requests.get(dataset_url, allow_redirects=False, timeout=5)
                if res.status_code in [301, 302] and res.headers.get("Location"):
                    return res.headers.get("Location")
            except Exception:
                pass

            return dataset_url

        except Exception as e:
            print(f"[S3StorageService ERROR] Failed to upload {filename} to S3 CDN: {e}")
            return None

s3_storage_service = S3StorageService()

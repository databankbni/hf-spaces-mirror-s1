"""
Step 5: Upload files to Google Cloud Storage
=============================================
Usage:
  python step5_upload_to_gcs.py  # runs test upload
"""

import os
from google.cloud import storage
from google.api_core.exceptions import GoogleAPIError


def upload_to_gcs(source_file_path: str, bucket_name: str, destination_blob_name: str) -> bool:
    try:
        # === HUGGINGFACE PERSONAL ACCOUNT BYPASS ===
        gcp_json_str = os.environ.get("GCP_PERSONAL_CREDENTIALS_JSON")
        if gcp_json_str:
            import tempfile
            temp_creds_path = os.path.join(tempfile.gettempdir(), "gcp_adc.json")
            with open(temp_creds_path, "w", encoding="utf-8") as f:
                f.write(gcp_json_str)
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = temp_creds_path
            
        # When using Personal Credentials, GCP requires a Project ID for billing/routing.
        # It defaults to 'insightsprod' (the BigQuery project) or whatever is in GOOGLE_CLOUD_PROJECT
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "insightsprod")
        storage_client = storage.Client(project=project_id)
        
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(destination_blob_name)

        print(f"Uploading '{source_file_path}' to 'gs://{bucket_name}/{destination_blob_name}'...")
        blob.upload_from_filename(source_file_path)
        print(f"SUCCESS: Uploaded to 'gs://{bucket_name}/{destination_blob_name}'")
        return True

    except GoogleAPIError as api_error:
        import traceback
        print(f"GCP API Error:\n{traceback.format_exc()}")
        return False
    except FileNotFoundError:
        import traceback
        print(f"Local Error: File '{source_file_path}' not found.\n{traceback.format_exc()}")
        return False
    except Exception as e:
        import traceback
        print(f"Unexpected error: {e}\n{traceback.format_exc()}")
        return False


if __name__ == "__main__":
    from env_config import get_config
    cfg = get_config()

    print(f"--- Test upload to {cfg.GCS_BUCKET} ---")
    test_path = "test_config_dummy.yaml"
    with open(test_path, "w") as f:
        f.write("name: test_configuration\npurpose: testing_gcs_upload\n")

    upload_to_gcs(test_path, cfg.GCS_BUCKET, f"{cfg.GCS_BASE_PATH}/company_yamls/test_config_dummy.yaml")

    if os.path.exists(test_path):
        os.remove(test_path)

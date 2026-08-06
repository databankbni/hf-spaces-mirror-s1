"""
GCS Upload
==========
Upload business logic and/or yaml directories to GCS for a company.

Usage:
  python gcs_upload.py --env dev --email demo+us@sarasanalytics.com --logic-dir ./logic --yaml-dir ./yamls
"""

import sys
import argparse
from pathlib import Path

from env_config import get_config, add_env_arg
from step5_upload_to_gcs import upload_to_gcs
from step3_get_token import get_auth_token


def upload_directory(company_id: str, local_dir: str, gcs_base_path: str, env: str = None):
    cfg = get_config(env)
    dir_path = Path(local_dir)
    if not dir_path.exists() or not dir_path.is_dir():
        print(f"Error: Directory '{local_dir}' does not exist or is not a directory.")
        return False

    success_count = 0
    total_count = 0

    for file_path in dir_path.rglob("*"):
        if file_path.is_file():
            total_count += 1
            file_name = file_path.name
            destination_blob_name = f"{gcs_base_path}/{company_id}/{file_name}"
            result = upload_to_gcs(str(file_path), cfg.GCS_BUCKET, destination_blob_name)
            if result:
                success_count += 1

    print(f"\n[Summary] Uploaded {success_count}/{total_count} files from '{local_dir}' to '{gcs_base_path}/{company_id}/'")
    return success_count == total_count


def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Upload company logic and yaml files to GCS")
    add_env_arg(parser)
    parser.add_argument("--email", required=True, help="User email to get company_id from token")
    parser.add_argument("--password", default=None, help="User password (default from env config)")
    parser.add_argument("--logic-dir", help="Local directory containing business logic files")
    parser.add_argument("--yaml-dir", help="Local directory containing yaml files")
    args = parser.parse_args()

    cfg = get_config(args.env)

    if not args.logic_dir and not args.yaml_dir:
        print("Please provide at least one directory: --logic-dir or --yaml-dir")
        sys.exit(1)

    password = args.password or cfg.DEFAULT_PASSWORD

    print(f"\n=== Getting Company ID from Auth Token ===")
    auth_result = get_auth_token(args.email, password, env=args.env)

    if not auth_result.get("success"):
        print(f"\nError: {auth_result.get('error')}")
        sys.exit(1)

    company_id = auth_result.get("company_id")
    if not company_id:
        print("\nError: Token did not contain a 'companyId'.")
        sys.exit(1)

    print(f"\n=== Uploading for Company ID: {company_id} ===")

    if args.logic_dir:
        print(f"\n>>> Uploading Business Logic from: {args.logic_dir}")
        upload_directory(str(company_id), args.logic_dir, f"{cfg.GCS_BASE_PATH}/company_business_logic", env=args.env)

    if args.yaml_dir:
        print(f"\n>>> Uploading YAML files from: {args.yaml_dir}")
        upload_directory(str(company_id), args.yaml_dir, f"{cfg.GCS_BASE_PATH}/company_yamls", env=args.env)

    print("\n=== Upload Complete ===")


if __name__ == "__main__":
    main()

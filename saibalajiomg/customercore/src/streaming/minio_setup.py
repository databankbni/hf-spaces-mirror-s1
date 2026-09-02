"""
src/streaming/minio_setup.py

Creates the MinIO bucket and folder structure for the lakehouse.
Run once before starting any pipeline.

Run: python -m src.streaming.minio_setup
"""

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

# ── MinIO connection ──────────────────────────────────────────
MINIO_ENDPOINT = "http://localhost:9000"
MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "minioadmin"
BUCKET = "customercore-lake"

# ── Bronze/Silver/Gold prefix structure ───────────────────────
PREFIXES = [
    "bronze/tickets/",
    "bronze/billing/",
    "bronze/product/",
    "bronze/incidents/",
    "silver/tickets/",
    "silver/billing/",
    "silver/product/",
    "silver/incidents/",
    "gold/",
]


def get_client():
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def setup():
    client = get_client()

    # Create bucket if it doesn't exist
    try:
        client.head_bucket(Bucket=BUCKET)
        print(f"[OK] Bucket '{BUCKET}' already exists")
    except ClientError:
        client.create_bucket(Bucket=BUCKET)
        print(f"[CREATED] Bucket '{BUCKET}'")

    # Create folder structure by writing empty marker objects
    for prefix in PREFIXES:
        client.put_object(Bucket=BUCKET, Key=prefix, Body=b"")
        print(f"  [OK] {BUCKET}/{prefix}")

    print(f"\nLakehouse structure ready at MinIO: {MINIO_ENDPOINT}")
    print("Browse at: http://localhost:9001 (user: minioadmin / pass: minioadmin)")


if __name__ == "__main__":
    setup()

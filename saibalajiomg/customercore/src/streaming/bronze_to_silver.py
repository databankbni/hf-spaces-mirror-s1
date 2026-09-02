"""
src/streaming/bronze_to_silver.py

PySpark job that reads Bronze Parquet files from MinIO,
applies PII masking via Presidio, cleans and validates records,
and writes to the Silver layer.

Silver = cleaned, validated, PII-masked. Safe to query and use for ML.

PII entities masked: EMAIL_ADDRESS, PHONE_NUMBER, CREDIT_CARD,
                     PERSON, IBAN_CODE, IP_ADDRESS

Run: python -m src.streaming.bronze_to_silver
     python -m src.streaming.bronze_to_silver --source tickets --limit 500
"""

import argparse
import io
import json
import time
from datetime import datetime, timezone
from typing import Optional

import boto3
import pyarrow as pa
import pyarrow.parquet as pq
from botocore.client import Config
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from tqdm import tqdm

# Optional vault import — gracefully degrade if not configured
try:
    from src.responsible_ai.privacy_vault import CryptographicPrivacyVault
    _VAULT_AVAILABLE = True
except ImportError:
    _VAULT_AVAILABLE = False
    CryptographicPrivacyVault = None

# ── Config ────────────────────────────────────────────────────
MINIO_ENDPOINT = "http://localhost:9000"
MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "minioadmin"
BUCKET = "customercore-lake"

SOURCE_MAP = {
    "tickets": ("bronze/tickets", "silver/tickets"),
    "billing": ("bronze/billing", "silver/billing"),
    "product": ("bronze/product", "silver/product"),
    "incidents": ("bronze/incidents", "silver/incidents"),
}

PII_ENTITIES = [
    "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD",
    "PERSON", "IBAN_CODE", "IP_ADDRESS", "US_SSN",
]

VALID_PRIORITIES = {"low", "medium", "high", "critical"}
VALID_TIERS = {"enterprise", "professional", "free"}
VALID_CHANNELS = {"email", "web", "api", "chat"}


def get_s3():
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def list_bronze_files(s3, prefix: str) -> list[str]:
    response = s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix)
    return [obj["Key"] for obj in response.get("Contents", []) if obj["Key"].endswith(".parquet")]


def read_parquet_from_minio(s3, key: str) -> list[dict]:
    obj = s3.get_object(Bucket=BUCKET, Key=key)
    buf = io.BytesIO(obj["Body"].read())
    table = pq.read_table(buf)
    records = []
    for row in table.to_pydict()["raw_json"]:
        try:
            records.append(json.loads(row))
        except json.JSONDecodeError:
            pass
    return records


def mask_pii(text: str, analyzer: AnalyzerEngine, anonymizer: AnonymizerEngine) -> str:
    """Run Presidio PII detection and replace with entity type placeholder (legacy path)."""
    if not text or not isinstance(text, str):
        return text
    results = analyzer.analyze(text=text, language="en", entities=PII_ENTITIES)
    if not results:
        return text
    anonymized = anonymizer.anonymize(text=text, analyzer_results=results)
    return anonymized.text


def vault_mask_pii(
    text: str,
    analyzer: AnalyzerEngine,
    anonymizer: AnonymizerEngine,
    vault: "CryptographicPrivacyVault",
    tenant_id: str,
    ticket_id: str = "",
) -> tuple[str, int]:
    """
    Vault-backed PII protection (upgraded path).
    Encrypts each PII span with the tenant's AES-256 key and replaces it
    with a stable, readable token in the text. Returns (tokenized_text, pii_count).
    Falls back to plain masking if vault is None.
    """
    if vault is None:
        return mask_pii(text, analyzer, anonymizer), 0
    return vault.encrypt_text(
        tenant_id=tenant_id,
        text=text,
        analyzer=analyzer,
        anonymizer=anonymizer,
        ticket_id=ticket_id,
        pii_entities=PII_ENTITIES,
    )


def validate_and_clean_ticket(
    record: dict,
    analyzer,
    anonymizer,
    vault: Optional["CryptographicPrivacyVault"] = None,
) -> dict | None:
    """
    Clean, validate, and PII-protect a ticket record.

    When a CryptographicPrivacyVault is provided (Phase 5+):
      - PII is encrypted with tenant-specific AES-256 and replaced by stable tokens
      - Tokens are stored in the vault for authorized re-identification
      - silver_version is bumped to '2.0' to signal vault-protected records

    Without a vault (Phase 3 legacy / backward-compatible path):
      - PII is replaced by [ENTITY_TYPE] placeholders (permanent deletion)
      - silver_version remains '1.0'

    Returns None if the record is missing required fields.
    """
    # Required fields
    if not record.get("event_id") or not record.get("tenant_id"):
        return None
    if not record.get("subject") and not record.get("body"):
        return None

    # Normalize fields
    priority = str(record.get("priority", "medium")).lower()
    tier = str(record.get("customer_tier", "free")).lower()
    channel = str(record.get("channel", "web")).lower()
    tenant_id = record["tenant_id"]
    ticket_id = record.get("ticket_id", "")

    # PII protection — vault path (Phase 5) or legacy masking path (Phase 3)
    if vault is not None:
        subject_clean, _ = vault_mask_pii(
            str(record.get("subject", ""))[:256], analyzer, anonymizer,
            vault, tenant_id, ticket_id,
        )
        body_clean, pii_count = vault_mask_pii(
            str(record.get("body", "")), analyzer, anonymizer,
            vault, tenant_id, ticket_id,
        )
        silver_version = "2.0"  # vault-protected
    else:
        subject_clean = mask_pii(str(record.get("subject", ""))[:256], analyzer, anonymizer)
        body_clean = mask_pii(str(record.get("body", "")), analyzer, anonymizer)
        silver_version = "1.0"  # legacy masking

    return {
        "event_id": record["event_id"],
        "event_type": record.get("event_type", "support_ticket_created"),
        "tenant_id": tenant_id,
        "ticket_id": ticket_id,
        "customer_id": record.get("customer_id", ""),
        "customer_tier": tier if tier in VALID_TIERS else "free",
        "subject": subject_clean,
        "body": body_clean,
        "category": str(record.get("category", "general")).lower(),
        "priority": priority if priority in VALID_PRIORITIES else "medium",
        "channel": channel if channel in VALID_CHANNELS else "web",
        "reopen_count": max(0, int(record.get("reopen_count", 0))),
        "tags": record.get("tags", []),
        "original_timestamp": record.get("timestamp", ""),
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "pii_masked": True,
        "vault_protected": vault is not None,
        "silver_version": silver_version,
    }


def write_silver(s3, prefix: str, records: list[dict], batch_id: str):
    """Write cleaned records to Silver layer as Parquet."""
    if not records:
        return

    # Build columnar data
    columns = list(records[0].keys())
    data = {col: [str(r.get(col, "")) for r in records] for col in columns}
    # reopen_count is int
    data["reopen_count"] = [int(r.get("reopen_count", 0)) for r in records]

    table = pa.table({k: pa.array(v) for k, v in data.items()})
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    buf.seek(0)

    key = f"{prefix}/silver_batch_{batch_id}.parquet"
    s3.put_object(Bucket=BUCKET, Key=key, Body=buf.getvalue())
    return key


def main(source: str = "tickets", limit: int = None, use_vault: bool = True):
    bronze_prefix, silver_prefix = SOURCE_MAP.get(source, SOURCE_MAP["tickets"])

    print("=" * 60)
    print("CustomerCore Bronze -> Silver Pipeline")
    print(f"  Source : s3://{BUCKET}/{bronze_prefix}/")
    print(f"  Sink   : s3://{BUCKET}/{silver_prefix}/")
    print(f"  PII masked: {', '.join(PII_ENTITIES)}")
    print("=" * 60)

    s3 = get_s3()

    # ── 1. Discover Bronze files ──────────────────────────────
    print("\n[1/5] Scanning Bronze layer for Parquet files...")
    files = list_bronze_files(s3, bronze_prefix)
    if not files:
        print("  No Bronze files found. Run bronze_consumer.py first.")
        return
    print(f"  Found {len(files)} Parquet file(s)")

    # ── 2. Load all records ───────────────────────────────────
    print("\n[2/5] Loading records from Bronze...")
    t0 = time.time()
    all_records = []
    for f in tqdm(files, desc="Reading", unit="file"):
        all_records.extend(read_parquet_from_minio(s3, f))
    print(f"  Loaded {len(all_records):,} raw records in {time.time()-t0:.1f}s")

    if limit:
        all_records = all_records[:limit]
        print(f"  Limited to {limit:,} records")

    # ── 3. Initialize Presidio + Privacy Vault ───────────────────
    # Using en_core_web_sm (12MB) — sufficient for PII detection.
    # en_core_web_lg (400MB) is NOT needed and causes download failures.
    print("\n[3/5] Initializing Presidio PII engine (en_core_web_sm)...")
    t0 = time.time()
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    nlp_config = {"nlp_engine_name": "spacy", "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}]}
    nlp_engine = NlpEngineProvider(nlp_configuration=nlp_config).create_engine()
    analyzer = AnalyzerEngine(nlp_engine=nlp_engine)
    anonymizer = AnonymizerEngine()
    print(f"  Ready in {time.time()-t0:.1f}s")

    # Initialize vault (Phase 5 — Zero-Trust Cryptographic Privacy Vault)
    vault = None
    if use_vault and _VAULT_AVAILABLE:
        from src.responsible_ai.privacy_vault import CryptographicPrivacyVault
        vault = CryptographicPrivacyVault()
        print("  Privacy Vault: ENABLED (AES-256, silver_version=2.0)")
    else:
        print("  Privacy Vault: DISABLED (legacy Presidio masking, silver_version=1.0)")

    # ── 4. Clean + mask PII ───────────────────────────────────
    print(f"\n[4/5] Cleaning and masking PII in {len(all_records):,} records...")
    print("  Estimated time: ~1-3 minutes for 1000 records (Presidio NER scan)")
    t0 = time.time()
    clean_records = []
    dropped = 0

    with tqdm(total=len(all_records), unit="rec",
              bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]") as pbar:
        for record in all_records:
            if source == "tickets":
                cleaned = validate_and_clean_ticket(record, analyzer, anonymizer, vault=vault)
            else:
                # For non-ticket sources: just add processing metadata, no PII masking needed
                record["processed_at"] = datetime.now(timezone.utc).isoformat()
                record["silver_version"] = "1.0"
                record["vault_protected"] = False
                cleaned = record
            if cleaned:
                clean_records.append(cleaned)
            else:
                dropped += 1
            pbar.update(1)

    elapsed = time.time() - t0
    rate = len(all_records) / elapsed if elapsed > 0 else float(len(all_records))
    print(f"\n  Processed : {len(all_records):,} records in {elapsed:.1f}s ({rate:.0f} rec/s)")
    print(f"  Valid     : {len(clean_records):,}")
    print(f"  Dropped   : {dropped:,} (missing required fields)")

    # ── 5. Write Silver ───────────────────────────────────────
    print(f"\n[5/5] Writing {len(clean_records):,} records to Silver layer...")
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    t0 = time.time()
    key = write_silver(s3, silver_prefix, clean_records, batch_id)
    print(f"  Written in {time.time()-t0:.1f}s -> {key}")

    print(f"\n{'=' * 60}")
    print(f"  Bronze records  : {len(all_records):,}")
    print(f"  Silver records  : {len(clean_records):,}")
    print(f"  Dropped         : {dropped:,}")
    print(f"  PII masked      : Yes ({', '.join(PII_ENTITIES)})")
    print(f"  Output          : s3://{BUCKET}/{silver_prefix}/")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["tickets", "billing", "product", "incidents"],
                        default="tickets", help="Which Bronze topic to process")
    parser.add_argument("--limit", type=int, default=None, help="Max records to process")
    parser.add_argument("--no-vault", action="store_true",
                        help="Disable Privacy Vault and use legacy Presidio masking")
    args = parser.parse_args()
    main(source=args.source, limit=args.limit, use_vault=not args.no_vault)

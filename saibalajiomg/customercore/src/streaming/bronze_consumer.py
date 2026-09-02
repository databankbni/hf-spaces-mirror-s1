"""
src/streaming/bronze_consumer.py

Reads from all 4 Redpanda topics and writes raw messages to MinIO
as the Bronze layer (unmodified, append-only Parquet files).

Bronze = raw data exactly as received. Nothing is changed.
If something goes wrong downstream, we always have the original.

Run: python -m src.streaming.bronze_consumer --batch-size 1000
     Ctrl+C to stop gracefully.
"""

import argparse
import io
import json
import signal
import time
from collections import defaultdict
from datetime import datetime, timezone

import boto3
import pyarrow as pa
import pyarrow.parquet as pq
from botocore.client import Config
from confluent_kafka import Consumer, KafkaError
from tqdm import tqdm

# ── Config ────────────────────────────────────────────────────
BROKER = "localhost:9092"
GROUP_ID = "bronze-consumer-group"
TOPICS = ["support-tickets", "billing-events", "product-events", "incident-events"]
BUCKET = "customercore-lake"
TOPIC_TO_PREFIX = {
    "support-tickets": "bronze/tickets",
    "billing-events": "bronze/billing",
    "product-events": "bronze/product",
    "incident-events": "bronze/incidents",
}

MINIO_ENDPOINT = "http://localhost:9000"
MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "minioadmin"

running = True


def signal_handler(sig, frame):
    global running
    print("\n[STOP] Graceful shutdown triggered...")
    running = False


signal.signal(signal.SIGINT, signal_handler)


def get_s3():
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def write_batch_to_bronze(s3, topic: str, records: list[dict]) -> str:
    """Write a batch of raw records to MinIO as a Parquet file."""
    prefix = TOPIC_TO_PREFIX[topic]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    key = f"{prefix}/batch_{timestamp}.parquet"

    # Convert to Arrow table — all values as strings to preserve raw format
    rows = [{"raw_json": json.dumps(r), "ingested_at": datetime.now(timezone.utc).isoformat()} for r in records]
    table = pa.table({
        "raw_json": pa.array([r["raw_json"] for r in rows], type=pa.string()),
        "ingested_at": pa.array([r["ingested_at"] for r in rows], type=pa.string()),
    })

    buf = io.BytesIO()
    pq.write_table(table, buf)
    buf.seek(0)
    s3.put_object(Bucket=BUCKET, Key=key, Body=buf.getvalue())
    return key


def main(batch_size: int = 500, timeout_seconds: int = 30):
    print("=" * 60)
    print("CustomerCore Bronze Consumer")
    print(f"Topics : {', '.join(TOPICS)}")
    print(f"Sink   : MinIO s3://{BUCKET}/bronze/")
    print(f"Batch  : {batch_size} messages per Parquet file")
    print("Press Ctrl+C to stop gracefully")
    print("=" * 60)

    consumer = Consumer({
        "bootstrap.servers": BROKER,
        "group.id": GROUP_ID,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": True,
    })
    consumer.subscribe(TOPICS)
    s3 = get_s3()

    buffers: dict[str, list] = defaultdict(list)
    total_written = 0
    files_written = 0
    start = time.time()
    last_message_time = time.time()

    print(f"\nListening for messages (will auto-stop after {timeout_seconds}s silence)...\n")
    pbar = tqdm(unit="msg", desc="Consumed", bar_format="{desc}: {n_fmt} msgs | Files: {postfix}")
    pbar.set_postfix_str("0")

    try:
        while running:
            msg = consumer.poll(timeout=1.0)

            # Auto-stop if silent for timeout_seconds
            if time.time() - last_message_time > timeout_seconds:
                print(f"\n[INFO] No messages for {timeout_seconds}s — flushing and stopping.")
                break

            if msg is None:
                continue
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    print(f"[ERROR] {msg.error()}")
                continue

            last_message_time = time.time()
            topic = msg.topic()
            try:
                value = json.loads(msg.value().decode())
                buffers[topic].append(value)
                total_written += 1
                pbar.update(1)
            except json.JSONDecodeError:
                continue

            # Flush buffer when batch is full
            if len(buffers[topic]) >= batch_size:
                key = write_batch_to_bronze(s3, topic, buffers[topic])
                files_written += 1
                pbar.set_postfix_str(str(files_written))
                buffers[topic] = []

        # Flush remaining partial batches
        print("\nFlushing remaining buffers...")
        for topic, records in buffers.items():
            if records:
                key = write_batch_to_bronze(s3, topic, records)
                files_written += 1
                print(f"  [FLUSHED] {len(records)} records -> {key}")

    finally:
        pbar.close()
        consumer.close()

    elapsed = time.time() - start
    print(f"\n{'=' * 60}")
    print(f"  Total consumed : {total_written:,} messages")
    print(f"  Parquet files  : {files_written}")
    print(f"  Duration       : {elapsed:.1f}s")
    print(f"  Sink           : s3://{BUCKET}/bronze/")
    print("  Browse MinIO   : http://localhost:9001")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=500, help="Messages per Parquet file")
    parser.add_argument("--timeout", type=int, default=30, help="Stop after N seconds of silence")
    args = parser.parse_args()
    main(batch_size=args.batch_size, timeout_seconds=args.timeout)

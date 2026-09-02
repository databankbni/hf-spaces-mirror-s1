"""
src/streaming/data_loader.py

Multi-Dataset CustomerCore Data Loader
Downloads multiple open-source customer support datasets from Hugging Face
and publishes enriched events to Redpanda topics with progress tracking.

== Datasets (all open-source, no scraping, no API keys, legal in EU/Germany) ==
  1. bitext/Bitext-customer-support-llm-chatbot-training-dataset
       26,872 rows | CDLA-Sharing-1.0 | SaaS customer support Q&A (English)
       Categories: billing, account, orders, technical, etc.

  2. bitext/Bitext-retail-banking-llm-chatbot-training-dataset
       25,545 rows | CDLA-Sharing-1.0 | B2B banking/financial support Q&A (English)
       Categories: card, loan, account, transfer, compliance, etc.

  3. mteb/amazon_massive_intent [de, fr, es]
       11,514 rows x 3 languages = 34,542 rows | Apache 2.0
       Real customer voice assistant intent utterances in German, French, Spanish
       Intents map to: alarm, calendar, email, audio, transport, shopping, etc.
       Source: Amazon MASSIVE (Fitzgerald et al., 2022)

  Total: ~87,000 rows across 4 languages (en, de, fr, es)

== Multi-Language Strategy ==
  A B2B SaaS platform serving EU customers receives tickets in German, French,
  Spanish, Portuguese etc. Single-language support degrades classification accuracy
  by 15-40% and is not acceptable for GDPR-compliant EU platforms.
  MASSIVE gives us real customer utterances in each language — not translations.

== Run ==
  python -m src.streaming.data_loader                            # all sources (default)
  python -m src.streaming.data_loader --sources customer         # SaaS English only
  python -m src.streaming.data_loader --sources banking          # Banking English only
  python -m src.streaming.data_loader --sources massive          # Multilingual only
  python -m src.streaming.data_loader --sources all              # Everything ~87k rows
  python -m src.streaming.data_loader --limit 500 --sources all  # Quick test
"""

import argparse
import json
import random
import time
import uuid
from datetime import datetime, timezone

from confluent_kafka import Producer
from datasets import load_dataset
from tqdm import tqdm

# ── Config ────────────────────────────────────────────────────
BROKER = "localhost:9092"
TOPIC = "support-tickets"

DATASET_CONFIGS = {
    "customer": {
        "id": "bitext/Bitext-customer-support-llm-chatbot-training-dataset",
        "license": "CDLA-Sharing-1.0",
        "domain": "saas_support",
        "text_field": "instruction",
        "response_field": "response",
        "category_field": "category",
        "tags_field": "tags",
        "language": "en",
    },
    "banking": {
        "id": "bitext/Bitext-retail-banking-llm-chatbot-training-dataset",
        "license": "CDLA-Sharing-1.0",
        "domain": "financial_support",
        "text_field": "instruction",
        "response_field": "response",
        "category_field": "category",
        "tags_field": "tags",
        "language": "en",
    },
}

# Multilingual MASSIVE configs (per language — Apache 2.0, no scraping)
MASSIVE_LANGUAGES = {
    "de": {"name": "German",   "mteb_config": "de"},
    "fr": {"name": "French",   "mteb_config": "fr"},
    "es": {"name": "Spanish",  "mteb_config": "es"},
}

# ── Enrichment pools (makes data multi-tenant) ────────────────
TENANTS = ["acme-corp", "globex-inc", "initech-ltd", "umbrella-co", "stark-tech"]
TIERS = ["enterprise", "professional", "free"]
CHANNELS = ["email", "web", "api", "chat"]

PRIORITY_MAP = {
    # SaaS support categories
    "ACCOUNT": ["medium", "high"],
    "BILLING": ["high", "high", "critical"],
    "CANCEL": ["high", "critical"],
    "CONTACT": ["low", "medium"],
    "DELIVERY": ["medium", "high"],
    "FEEDBACK": ["low", "medium"],
    "INVOICE": ["high", "critical"],
    "NEWSLETTER": ["low"],
    "ORDER": ["medium", "high"],
    "PAYMENT": ["high", "critical"],
    "REFUND": ["high", "high", "critical"],
    "REVIEW": ["low", "medium"],
    "SHIPPING": ["medium", "high"],
    "SUBSCRIPTION": ["medium", "high"],
    "SUPPORT": ["medium", "high"],
    # Banking categories
    "CARD": ["high", "critical"],
    "LOAN": ["medium", "high"],
    "TRANSFER": ["high", "critical"],
    "COMPLIANCE": ["high", "critical"],
    "MORTGAGE": ["medium", "high"],
    "SAVINGS": ["low", "medium"],
    "FRAUD": ["critical", "critical"],
}


def delivery_report(err, msg):
    if err is not None:
        print(f"\n  [ERROR] Delivery failed: {err}")


def enrich(row: dict, domain: str, license_str: str) -> dict:
    """
    Normalize a raw Bitext row into a CustomerCore ticket event.
    Both Bitext datasets share the same column schema (instruction / response / category).
    Domain tag differentiates SaaS support from financial support in downstream analysis.
    """
    category = str(row.get("category", "SUPPORT")).upper()
    tier = random.choice(TIERS)
    priority_pool = PRIORITY_MAP.get(category[:8], ["low", "medium", "high"])
    if tier == "enterprise":
        priority_pool = [p for p in priority_pool if p in ("high", "critical")] or ["high"]

    tags_raw = row.get("tags", "")
    tags = [t.strip() for t in str(tags_raw).split(",") if t.strip()] if tags_raw else []

    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "support_ticket_created",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tenant_id": random.choice(TENANTS),
        "ticket_id": f"TKT-{random.randint(10000, 99999)}",
        "customer_id": f"CUST-{random.randint(1000, 99999)}",
        "customer_tier": tier,
        "subject": str(row.get("instruction", ""))[:120],
        "body": str(row.get("instruction", "")),
        "suggested_response": str(row.get("response", "")),
        "category": category.lower(),
        "priority": random.choice(priority_pool),
        "channel": random.choice(CHANNELS),
        "reopen_count": random.randint(0, 2),
        "tags": tags,
        "source_domain": domain,
        "source": f"huggingface:bitext-{domain}",
        "license": license_str,
        "language": "en",
        "is_multilingual": False,
    }


def enrich_massive(row: dict, language: str, lang_name: str) -> dict:
    """
    Normalize an Amazon MASSIVE intent row into a CustomerCore ticket event.

    MASSIVE rows have: id, label, label_text, text, lang
    label_text = intent name (e.g. 'alarm_set', 'email_query', 'calendar_remove')
    text = the customer utterance in the target language

    Maps MASSIVE intents to support categories:
      alarm/reminder/calendar -> account
      email/messaging         -> account
      audio/music/podcast     -> product
      transport/travel        -> order
      shopping                -> order
      iot/smart_home          -> technical
      weather/datetime/news   -> general
    """
    INTENT_TO_CATEGORY = {
        "alarm": "account", "reminder": "account", "calendar": "account",
        "email": "account", "messaging": "account", "social": "account",
        "audio": "technical", "music": "technical", "podcast": "technical",
        "play": "technical", "iot": "technical", "smart": "technical",
        "transport": "order", "travel": "order", "lists": "order",
        "shopping": "order", "takeaway": "order", "cooking": "order",
        "weather": "general", "datetime": "general", "news": "general",
        "qa": "general", "recommendation": "general", "general": "general",
    }

    intent = str(row.get("label_text", "general")).lower()
    category = "general"
    for key, cat in INTENT_TO_CATEGORY.items():
        if key in intent:
            category = cat
            break

    tier = random.choice(TIERS)
    priority_pool = ["low", "medium", "medium", "high"]

    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "support_ticket_created",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tenant_id": random.choice(TENANTS),
        "ticket_id": f"TKT-{random.randint(10000, 99999)}",
        "customer_id": f"CUST-{random.randint(1000, 99999)}",
        "customer_tier": tier,
        "subject": str(row.get("text", ""))[:120],
        "body": str(row.get("text", "")),
        "suggested_response": "",
        "category": category,
        "priority": random.choice(priority_pool),
        "channel": random.choice(CHANNELS),
        "reopen_count": 0,
        "tags": [intent.replace("_", "-")],
        "source_domain": "multilingual_intent",
        "source": f"huggingface:amazon-massive-{language}",
        "license": "Apache-2.0",
        "language": language,
        "language_name": lang_name,
        "is_multilingual": True,
        "intent": intent,
    }


def load_sources(sources: str) -> tuple[list, dict]:
    """
    Download and concatenate the requested dataset sources.
    Returns (list_of_(row, enrich_fn) tuples, dict of source->count).
    """
    all_rows = []
    total_per_source = {}

    bitext_sources = []
    load_massive = False

    if sources == "all":
        bitext_sources = list(DATASET_CONFIGS.items())
        load_massive = True
    elif sources == "massive":
        load_massive = True
    elif sources in DATASET_CONFIGS:
        bitext_sources = [(sources, DATASET_CONFIGS[sources])]
    else:
        raise ValueError(
            f"Unknown source '{sources}'. "
            f"Choose from: {list(DATASET_CONFIGS.keys()) + ['massive', 'all']}"
        )

    # Load Bitext English datasets
    for name, cfg in bitext_sources:
        print(f"\n  Downloading: {cfg['id']}")
        print(f"  License    : {cfg['license']} | Language: English")
        t0 = time.time()
        ds = load_dataset(cfg["id"], split="train")
        elapsed = time.time() - t0
        print(f"  Downloaded : {len(ds):,} rows in {elapsed:.1f}s")
        total_per_source[name] = len(ds)
        for row in ds:
            all_rows.append((row, cfg["domain"], cfg["license"], "bitext", "en", "English"))

    # Load multilingual MASSIVE datasets
    if load_massive:
        for lang_code, lang_cfg in MASSIVE_LANGUAGES.items():
            lang_name = lang_cfg["name"]
            mteb_config = lang_cfg["mteb_config"]
            print(f"\n  Downloading: mteb/amazon_massive_intent [{lang_code} - {lang_name}]")
            print(f"  License    : Apache-2.0 | Language: {lang_name}")
            t0 = time.time()
            ds = load_dataset("mteb/amazon_massive_intent", mteb_config, split="train")
            elapsed = time.time() - t0
            print(f"  Downloaded : {len(ds):,} rows in {elapsed:.1f}s")
            total_per_source[f"massive_{lang_code}"] = len(ds)
            for row in ds:
                all_rows.append((row, "multilingual_intent", "Apache-2.0", "massive", lang_code, lang_name))

    return all_rows, total_per_source


def main(limit: int = None, delay: float = 0.0, sources: str = "all"):
    print("=" * 65)
    print("CustomerCore Multi-Language Data Loader")
    print("Sources: Bitext SaaS + Banking (EN) + Amazon MASSIVE (DE/FR/ES)")
    print("License: CDLA-Sharing-1.0 + Apache-2.0 | Legal in EU/Germany")
    print("=" * 65)

    # ── 1. Download datasets ──────────────────────────────────
    print("\n[1/3] Downloading datasets from Hugging Face...")
    time.time()
    all_rows, source_counts = load_sources(sources)

    print("\n  Source breakdown:")
    for src, count in source_counts.items():
        print(f"    {src:18s}: {count:,} rows")
    total = len(all_rows)
    print(f"  {'TOTAL':18s}: {total:,} rows")

    if limit:
        random.shuffle(all_rows)
        all_rows = all_rows[:limit]
        print(f"\n  Limited to {len(all_rows):,} rows for this run")

    # ── 2. Connect to Redpanda ────────────────────────────────
    print(f"\n[2/3] Connecting to Redpanda at {BROKER}...")
    producer = Producer({
        "bootstrap.servers": BROKER,
        "queue.buffering.max.messages": 10000,
        "batch.num.messages": 500,
    })
    print("      Connected.")

    # ── 3. Publish with progress bar ──────────────────────────
    print(f"\n[3/3] Publishing {len(all_rows):,} events to '{TOPIC}'...")
    print(f"      Estimated time: {len(all_rows) * 0.001:.0f}–{len(all_rows) * 0.003:.0f} seconds")

    failed = 0
    lang_counts: dict[str, int] = {}
    t0 = time.time()
    with tqdm(
        total=len(all_rows),
        unit="msg",
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]"
    ) as pbar:
        # Each tuple: (row, domain, license_str, source_type, lang_code, lang_name)
        for row, domain, license_str, source_type, lang_code, lang_name in all_rows:
            if source_type == "bitext":
                event = enrich(row, domain, license_str)
            else:  # massive
                event = enrich_massive(row, lang_code, lang_name)

            lang_counts[lang_code] = lang_counts.get(lang_code, 0) + 1

            producer.produce(
                topic=TOPIC,
                key=event["ticket_id"].encode(),
                value=json.dumps(event).encode(),
                callback=lambda err, msg: None if not err else None,
            )
            producer.poll(0)
            pbar.update(1)
            if delay:
                time.sleep(delay)

    producer.flush()
    elapsed = time.time() - t0
    sent = len(all_rows) - failed

    print(f"\n{'=' * 65}")
    print(f"  Published   : {sent:,} events")
    print(f"  Failed      : {failed}")
    print(f"  Duration    : {elapsed:.1f}s  ({len(all_rows)/elapsed:.0f} msg/s)")
    print(f"  Topic       : {TOPIC}")
    print(f"  Sources     : {sources}")
    print("  Language breakdown:")
    for lang, count in sorted(lang_counts.items()):
        print(f"    {lang}: {count:,} rows")
    print(f"{'=' * 65}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CustomerCore Multi-Language HuggingFace loader")
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Max rows to load (default: all ~87k combined)"
    )
    parser.add_argument(
        "--delay", type=float, default=0.0,
        help="Delay between messages in seconds"
    )
    parser.add_argument(
        "--sources",
        choices=["all", "customer", "banking", "massive"],
        default="all",
        help="Which dataset sources to load (default: all = EN+DE+FR+ES)"
    )
    args = parser.parse_args()
    main(limit=args.limit, delay=args.delay, sources=args.sources)


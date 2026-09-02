"""
ticket_producer.py
Generates realistic synthetic support ticket events and publishes
them to the Redpanda 'support-tickets' topic.

Run: python -m src.streaming.producers.ticket_producer
"""

import json
import random
import time
import uuid
from datetime import datetime, timezone
from confluent_kafka import Producer

# ── Configuration ────────────────────────────────────────────
BROKER = "localhost:9092"
TOPIC = "support-tickets"

# ── Synthetic data pools ──────────────────────────────────────
TENANTS = ["acme-corp", "globex-inc", "initech-ltd", "umbrella-co", "stark-tech"]
CUSTOMER_TIERS = ["enterprise", "professional", "free"]
CATEGORIES = ["billing", "technical", "account", "product", "general"]
SUBJECTS = [
    "Cannot log in to my account",
    "Invoice amount is incorrect",
    "API is returning 500 errors",
    "Feature not working as documented",
    "Need to update billing details",
    "Performance issues on dashboard",
    "Integration with Slack is broken",
    "Export to CSV is not working",
    "Account suspension — urgent",
    "Pricing plan question",
]
BODIES = [
    "We have been experiencing this issue since yesterday morning. Our entire team is blocked.",
    "I have already tried clearing cache and logging out but the problem persists.",
    "This is critically impacting our production system. Please escalate immediately.",
    "Our enterprise contract says this should be resolved within 2 hours. Please help.",
    "This worked fine last week but suddenly stopped after the update.",
    "I have attached screenshots. Our clients are complaining and we need a fix now.",
    "The error message says 'Internal Server Error' but gives no further detail.",
    "Our billing department flagged an overcharge of $2,400 on this month's invoice.",
]


def delivery_report(err, msg):
    """Callback fired when a message is confirmed delivered or failed."""
    if err is not None:
        print(f"  [ERROR] Delivery failed: {err}")
    else:
        print(f"  [OK] ticket {msg.key().decode()} -> partition {msg.partition()}")


def make_ticket() -> dict:
    """Build a single realistic synthetic ticket event."""
    tenant = random.choice(TENANTS)
    tier = random.choice(CUSTOMER_TIERS)
    # Enterprise customers get higher base priority weighting
    priority_pool = (
        ["critical", "high", "high", "medium"]
        if tier == "enterprise"
        else ["high", "medium", "medium", "low"]
    )
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "support_ticket_created",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tenant_id": tenant,
        "ticket_id": f"TKT-{random.randint(10000, 99999)}",
        "customer_id": f"CUST-{random.randint(1000, 9999)}",
        "customer_tier": tier,
        "subject": random.choice(SUBJECTS),
        "body": random.choice(BODIES),
        "category": random.choice(CATEGORIES),
        "priority": random.choice(priority_pool),
        "channel": random.choice(["email", "web", "api", "chat"]),
        "reopen_count": random.randint(0, 3),
        "tags": random.sample(["urgent", "billing", "api", "performance", "auth"], k=random.randint(0, 3)),
    }


def main(num_events: int = 20, delay_seconds: float = 0.5):
    producer = Producer({"bootstrap.servers": BROKER})
    print(f"Publishing {num_events} ticket events to '{TOPIC}'...")

    for i in range(num_events):
        event = make_ticket()
        producer.produce(
            topic=TOPIC,
            key=event["ticket_id"].encode(),
            value=json.dumps(event).encode(),
            callback=delivery_report,
        )
        producer.poll(0)
        time.sleep(delay_seconds)

    producer.flush()
    print(f"\nDone. {num_events} tickets published to '{TOPIC}'.")


if __name__ == "__main__":
    main()

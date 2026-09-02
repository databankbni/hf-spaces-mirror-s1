"""
product_producer.py
Generates synthetic product feedback events and publishes them
to the Redpanda 'product-events' topic.

Run: python -m src.streaming.producers.product_producer
"""

import json
import random
import time
import uuid
from datetime import datetime, timezone
from confluent_kafka import Producer

BROKER = "localhost:9092"
TOPIC = "product-events"

TENANTS = ["acme-corp", "globex-inc", "initech-ltd", "umbrella-co", "stark-tech"]
FEATURES = [
    "dashboard", "reporting", "api", "integrations",
    "mobile-app", "export", "notifications", "search", "admin-panel",
]
EVENT_TYPES = [
    "feature_request",
    "bug_report",
    "usability_complaint",
    "performance_feedback",
    "feature_praise",
]
SENTIMENTS = ["positive", "neutral", "negative", "very_negative"]


def delivery_report(err, msg):
    if err is not None:
        print(f"  [ERROR] Delivery failed: {err}")
    else:
        print(f"  [OK] product {msg.key().decode()} -> partition {msg.partition()}")


def make_product_event() -> dict:
    tenant = random.choice(TENANTS)
    event_type = random.choice(EVENT_TYPES)
    sentiment = (
        "positive" if event_type == "feature_praise"
        else random.choice(SENTIMENTS)
    )
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tenant_id": tenant,
        "customer_id": f"CUST-{random.randint(1000, 9999)}",
        "feature": random.choice(FEATURES),
        "sentiment": sentiment,
        "sentiment_score": round(random.uniform(-1.0, 1.0), 3),
        "satisfaction_rating": random.randint(1, 10),
        "body": f"Feedback on {random.choice(FEATURES)}: {event_type.replace('_', ' ')}.",
        "source": random.choice(["in-app", "nps-survey", "support-ticket", "email"]),
    }


def main(num_events: int = 12, delay_seconds: float = 0.3):
    producer = Producer({"bootstrap.servers": BROKER})
    print(f"Publishing {num_events} product events to '{TOPIC}'...")

    for _ in range(num_events):
        event = make_product_event()
        producer.produce(
            topic=TOPIC,
            key=event["event_id"].encode(),
            value=json.dumps(event).encode(),
            callback=delivery_report,
        )
        producer.poll(0)
        time.sleep(delay_seconds)

    producer.flush()
    print(f"\nDone. {num_events} product events published to '{TOPIC}'.")


if __name__ == "__main__":
    main()

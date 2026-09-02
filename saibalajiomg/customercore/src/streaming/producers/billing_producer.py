"""
billing_producer.py
Generates synthetic billing event messages and publishes them
to the Redpanda 'billing-events' topic.

Run: python -m src.streaming.producers.billing_producer
"""

import json
import random
import time
import uuid
from datetime import datetime, timezone
from confluent_kafka import Producer

BROKER = "localhost:9092"
TOPIC = "billing-events"

TENANTS = ["acme-corp", "globex-inc", "initech-ltd", "umbrella-co", "stark-tech"]
EVENT_TYPES = [
    "payment_failed",
    "invoice_dispute",
    "subscription_downgrade",
    "overcharge_reported",
    "payment_method_expired",
    "refund_requested",
]
CURRENCIES = ["USD", "EUR", "GBP"]


def delivery_report(err, msg):
    if err is not None:
        print(f"  [ERROR] Delivery failed: {err}")
    else:
        print(f"  [OK] billing {msg.key().decode()} -> partition {msg.partition()}")


def make_billing_event() -> dict:
    tenant = random.choice(TENANTS)
    amount = round(random.uniform(49.0, 4999.0), 2)
    event_type = random.choice(EVENT_TYPES)
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tenant_id": tenant,
        "customer_id": f"CUST-{random.randint(1000, 9999)}",
        "invoice_id": f"INV-{random.randint(100000, 999999)}",
        "amount": amount,
        "currency": random.choice(CURRENCIES),
        "plan": random.choice(["free", "professional", "enterprise"]),
        "failure_code": random.choice(["insufficient_funds", "card_declined", "expired_card", None]),
        "retry_count": random.randint(0, 3),
        "notes": f"Automated billing event: {event_type} for tenant {tenant}",
    }


def main(num_events: int = 15, delay_seconds: float = 0.3):
    producer = Producer({"bootstrap.servers": BROKER})
    print(f"Publishing {num_events} billing events to '{TOPIC}'...")

    for _ in range(num_events):
        event = make_billing_event()
        producer.produce(
            topic=TOPIC,
            key=event["invoice_id"].encode(),
            value=json.dumps(event).encode(),
            callback=delivery_report,
        )
        producer.poll(0)
        time.sleep(delay_seconds)

    producer.flush()
    print(f"\nDone. {num_events} billing events published to '{TOPIC}'.")


if __name__ == "__main__":
    main()

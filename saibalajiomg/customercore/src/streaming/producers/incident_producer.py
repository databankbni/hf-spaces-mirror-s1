"""
incident_producer.py
Generates synthetic system incident events and publishes them
to the Redpanda 'incident-events' topic.

These events simulate what the Incident Agent monitors — when
many tickets share the same error pattern it is flagged as a P1/P2.

Run: python -m src.streaming.producers.incident_producer
"""

import json
import random
import time
import uuid
from datetime import datetime, timezone
from confluent_kafka import Producer

BROKER = "localhost:9092"
TOPIC = "incident-events"

TENANTS = ["acme-corp", "globex-inc", "initech-ltd", "umbrella-co", "stark-tech"]
SERVICES = ["auth-service", "api-gateway", "billing-service", "data-pipeline", "notification-service"]
SEVERITIES = ["P1", "P2", "P3", "P4"]
STATUSES = ["detected", "investigating", "mitigating", "resolved"]
ERROR_PATTERNS = [
    "HTTP 500 spike across all endpoints",
    "Login failure rate exceeded 40%",
    "Database connection pool exhausted",
    "Message queue consumer lag > 100k",
    "Memory usage above 95% on all nodes",
    "Stripe webhook delivery failures",
    "Email delivery service timeout",
    "Search index out of sync",
]


def delivery_report(err, msg):
    if err is not None:
        print(f"  [ERROR] Delivery failed: {err}")
    else:
        print(f"  [OK] incident {msg.key().decode()} -> partition {msg.partition()}")


def make_incident_event() -> dict:
    severity = random.choice(SEVERITIES)
    affected_tenants = random.sample(TENANTS, k=random.randint(1, len(TENANTS)))
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "incident_detected",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "incident_id": f"INC-{random.randint(1000, 9999)}",
        "severity": severity,
        "status": random.choice(STATUSES),
        "affected_service": random.choice(SERVICES),
        "affected_tenants": affected_tenants,
        "affected_tenant_count": len(affected_tenants),
        "error_pattern": random.choice(ERROR_PATTERNS),
        "ticket_count": random.randint(5, 200),   # how many tickets triggered this
        "error_rate": round(random.uniform(0.05, 0.95), 3),
        "mean_time_to_detect_minutes": random.randint(1, 30),
        "on_call_engineer": f"engineer_{random.randint(1, 10)}@company.com",
        "auto_escalated": severity in ["P1", "P2"],
    }


def main(num_events: int = 10, delay_seconds: float = 0.5):
    producer = Producer({"bootstrap.servers": BROKER})
    print(f"Publishing {num_events} incident events to '{TOPIC}'...")

    for _ in range(num_events):
        event = make_incident_event()
        producer.produce(
            topic=TOPIC,
            key=event["incident_id"].encode(),
            value=json.dumps(event).encode(),
            callback=delivery_report,
        )
        producer.poll(0)
        time.sleep(delay_seconds)

    producer.flush()
    print(f"\nDone. {num_events} incident events published to '{TOPIC}'.")


if __name__ == "__main__":
    main()

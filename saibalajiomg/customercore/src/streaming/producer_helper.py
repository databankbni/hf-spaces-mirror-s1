import json
import logging
import os
from datetime import datetime, timezone
from confluent_kafka import Producer

logger = logging.getLogger("customercore.producer_helper")

_PRODUCER = None

def get_producer() -> Producer | None:
    """
    Lazily initialize and return the Kafka/Redpanda Producer singleton.
    Configured with fast fail timeouts to prevent blocking API request threads.
    """
    global _PRODUCER
    if _PRODUCER is not None:
        return _PRODUCER
    
    broker = os.environ.get("REDPANDA_BROKER", "localhost:9092")
    
    # Fast check: try to open a socket to the broker to see if it is reachable
    try:
        import socket
        host, port = broker.split(":")
        s = socket.create_connection((host, int(port)), timeout=0.1)
        s.close()
    except Exception as exc:
        logger.warning(f"Redpanda broker at {broker} is unreachable: {exc}. Disabling producer.")
        return None

    try:
        # Fast-fail configuration if Redpanda broker is not reachable
        _PRODUCER = Producer({
            "bootstrap.servers": broker,
            "socket.timeout.ms": 1000,
            "message.timeout.ms": 2000,
        })
        logger.info(f"Initialized Redpanda Producer on {broker}")
        return _PRODUCER
    except Exception as exc:
        logger.warning(f"Failed to initialize Redpanda Producer on {broker}: {exc}")
        return None

def publish_ticket_event(
    ticket_id: str,
    tenant_id: str,
    customer_id: str,
    customer_tier: str,
    channel: str,
    text: str
) -> bool:
    """
    Publish a support ticket event to the Redpanda 'support-tickets' topic.
    Returns True if successfully produced/enqueued, False if Redpanda is offline.
    """
    producer = get_producer()
    if producer is None:
        return False
        
    event = {
        "event_id": ticket_id,
        "event_type": "support_ticket_created",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tenant_id": tenant_id,
        "ticket_id": ticket_id,
        "customer_id": customer_id,
        "customer_tier": customer_tier,
        "subject": text[:120],
        "body": text,
        "category": "general",
        "priority": "medium",
        "channel": channel,
        "reopen_count": 0,
        "tags": [],
    }
    
    try:
        topic = os.environ.get("REDPANDA_TICKET_TOPIC", "support-tickets")
        producer.produce(
            topic=topic,
            key=ticket_id.encode("utf-8"),
            value=json.dumps(event).encode("utf-8"),
        )
        # Flush/poll to ensure the message queue is triggered
        producer.poll(0)
        logger.info(f"Enqueued ticket event {ticket_id} to topic {topic}")
        return True
    except Exception as exc:
        logger.warning(f"Failed to produce ticket event {ticket_id} to Redpanda: {exc}")
        return False

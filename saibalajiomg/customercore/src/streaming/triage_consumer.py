import asyncio
import json
import logging
import os
import signal
from confluent_kafka import Consumer, KafkaError
from src.api.routers.triage import _run_triage
from src.db.repository import TicketRepository, TicketRecord

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("customercore.triage_consumer")

BROKER = os.environ.get("REDPANDA_BROKER", "localhost:9092")
TOPIC = os.environ.get("REDPANDA_TICKET_TOPIC", "support-tickets")
GROUP_ID = os.environ.get("REDPANDA_TRIAL_GROUP", "triage-consumer-group")

running = True

def signal_handler(sig, frame):
    global running
    logger.info("Graceful shutdown triggered...")
    running = False

# Listen to terminate signals
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

async def consume_loop():
    consumer = Consumer({
        "bootstrap.servers": BROKER,
        "group.id": GROUP_ID,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": True,
    })
    
    consumer.subscribe([TOPIC])
    logger.info(f"Subscribed to topic '{TOPIC}' on broker '{BROKER}' (group: '{GROUP_ID}')")
    
    try:
        while running:
            # Poll for new messages using an executor to avoid blocking the asyncio event loop
            msg = await asyncio.to_thread(consumer.poll, 1.0)
            if msg is None:
                continue
                
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    logger.error(f"Kafka error: {msg.error()}")
                continue
                
            try:
                payload = msg.value().decode("utf-8")
                event = json.loads(payload)
                logger.info(f"Received ticket event key={msg.key().decode('utf-8') if msg.key() else 'None'}")
                
                # Extract fields from the event JSON
                tenant_id = event.get("tenant_id")
                ticket_id = event.get("ticket_id") or event.get("event_id")
                body = event.get("body") or event.get("subject") or ""
                customer_id = event.get("customer_id") or "unknown"
                customer_tier = event.get("customer_tier") or "free"
                channel = event.get("channel") or "web"
                
                if not tenant_id or not ticket_id:
                    logger.warning(f"Skipping event missing critical fields: tenant_id={tenant_id}, ticket_id={ticket_id}")
                    continue
                
                # Ensure the ticket exists in the Supabase db (or the in-memory store in test environment)
                repo = TicketRepository(tenant_id)
                existing = await repo.get(ticket_id)
                if not existing:
                    logger.info(f"Creating new ticket {ticket_id} in database...")
                    record = TicketRecord(
                        id=ticket_id,
                        tenant_id=tenant_id,
                        customer_id=customer_id,
                        channel=channel,
                        raw_text=body,
                        status="pending",
                    )
                    await repo.create(record)
                    await repo.write_audit(
                        actor="system",
                        action="ticket.created",
                        ticket_id=ticket_id,
                        details={"channel": channel, "customer_tier": customer_tier, "via": "streaming_triage_consumer"},
                    )
                
                # Run the triage agent asynchronously to avoid blocking the message consumer thread
                asyncio.create_task(
                    _run_triage(
                        ticket_id=ticket_id,
                        text=body,
                        customer_id=customer_id,
                        tenant_id=tenant_id,
                        customer_tier=customer_tier,
                        channel=channel,
                    )
                )
                logger.info(f"Dispatched async triage worker task for ticket {ticket_id}")
                
            except Exception as exc:
                logger.exception(f"Error processing Redpanda message: {exc}")
                
    finally:
        consumer.close()
        logger.info("Redpanda consumer closed gracefully.")

def main():
    logger.info("=" * 60)
    logger.info("CustomerCore Real-Time Streaming Triage Consumer")
    logger.info("Press Ctrl+C to terminate...")
    logger.info("=" * 60)
    
    try:
        asyncio.run(consume_loop())
    except KeyboardInterrupt:
        logger.info("Shutdown complete.")

if __name__ == "__main__":
    main()

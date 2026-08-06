"""
whatsapp_alerts.py — Send WhatsApp alerts for HIGH-confidence predictions via CallMeBot.

One-time self-setup (done once by you in WhatsApp):
  1. Save +34 644 60 49 11 as a contact named "CallMeBot"
  2. Send "I allow callmebot to send me messages" to that number
  3. You receive an API key back (e.g. 123456)
  4. Set env vars: WHATSAPP_PHONE=91XXXXXXXXXX  WHATSAPP_APIKEY=123456

No extra packages needed — uses requests (already a dependency).
"""
from __future__ import annotations
import logging
import os
import urllib.parse

logger = logging.getLogger(__name__)

_CALLMEBOT_URL = "https://api.callmebot.com/whatsapp.php"


def _build_message(pred: dict) -> str:
    ticker = pred.get("ticker", "?").replace(".NS", "")
    direction = pred.get("direction", "?")
    confidence = pred.get("confidence", "?")
    tf = pred.get("timeframe", "?")
    entry = pred.get("entry_price") or pred.get("current_price")
    lo = pred.get("target_price_lo")
    hi = pred.get("target_price_hi")
    stop = pred.get("stop_loss")

    parts = [f"{ticker} | {direction} {confidence} | {tf}"]
    if entry:
        parts.append(f"Entry ₹{entry:.0f}")
    if lo and hi:
        parts.append(f"Target ₹{lo:.0f}–{hi:.0f}")
    if stop:
        parts.append(f"Stop ₹{stop:.0f}")
    return " | ".join(parts)


def send_prediction_alert(pred: dict) -> bool:
    """
    Send a WhatsApp message for a HIGH-confidence prediction.
    No-ops silently if WHATSAPP_PHONE or WHATSAPP_APIKEY are not set.
    Returns True if the message was sent successfully.
    """
    phone = os.environ.get("WHATSAPP_PHONE", "").strip()
    apikey = os.environ.get("WHATSAPP_APIKEY", "").strip()
    if not phone or not apikey:
        return False

    if (pred.get("confidence") or "").upper() != "HIGH":
        return False

    text = _build_message(pred)
    try:
        import requests
        resp = requests.get(
            _CALLMEBOT_URL,
            params={"phone": phone, "text": text, "apikey": apikey},
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info("WhatsApp alert sent: %s", text)
            return True
        logger.warning("WhatsApp alert HTTP %d: %s", resp.status_code, resp.text[:200])
        return False
    except Exception as e:
        logger.warning("WhatsApp alert failed: %s", e)
        return False


def send_bulk_alerts(predictions: list[dict]) -> int:
    """Send alerts for all HIGH-confidence predictions. Returns count sent."""
    sent = 0
    for pred in predictions:
        if send_prediction_alert(pred):
            sent += 1
    return sent

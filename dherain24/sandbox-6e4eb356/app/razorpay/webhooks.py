import hmac
import hashlib
from typing import Optional
from app.core.config import settings

def verify_webhook_signature(body: bytes, signature: Optional[str], secret: Optional[str] = None) -> bool:
    """
    Verifies the X-Razorpay-Signature header against the raw request body.
    Razorpay generates an HMAC-SHA256 digest of the raw webhook payload.
    """
    if not signature:
        return False

    webhook_secret = secret or settings.RAZORPAY_WEBHOOK_SECRET
    if not webhook_secret:
        return False

    expected_signature = hmac.new(
        key=webhook_secret.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_signature, signature)

def generate_test_signature(body: bytes, secret: Optional[str] = None) -> str:
    """Helper for generating test signatures in automated test suites."""
    webhook_secret = secret or settings.RAZORPAY_WEBHOOK_SECRET or "rri_rzp_sec_9942a1"
    return hmac.new(
        key=webhook_secret.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha256,
    ).hexdigest()

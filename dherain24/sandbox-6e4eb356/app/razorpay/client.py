import logging
import httpx
from typing import Dict, Any, Optional
from app.core.config import settings

logger = logging.getLogger(__name__)

class RazorpayGatewayError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None, error_data: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_data = error_data or {}

class RazorpayClient:
    def __init__(self):
        self.key_id = settings.RAZORPAY_KEY_ID
        self.key_secret = settings.RAZORPAY_KEY_SECRET
        self.base_url = "https://api.razorpay.com/v1"

    def _get_auth(self) -> Optional[tuple]:
        if self.key_id and self.key_secret:
            return (self.key_id, self.key_secret)
        return None

    async def create_payment_link(
        self,
        amount: float,
        description: str,
        customer_name: str,
        customer_email: str,
        customer_contact: Optional[str] = None,
        reference_id: Optional[str] = None,
        simulate_failure: bool = False,
    ) -> Dict[str, Any]:
        """
        Creates a Razorpay Payment Link in Test Mode.
        Amounts in Razorpay are in paise (e.g. ₹500.00 = 50000 paise).
        """
        if simulate_failure:
            logger.warning("Simulating Razorpay gateway 500 outage.")
            raise RazorpayGatewayError("Razorpay API Gateway unavailable (500 Internal Server Error)", status_code=500)

        auth = self._get_auth()
        if not auth:
            # Fallback mock for offline / local test without network
            logger.info("Using mock Razorpay Payment Link generator (no keys provided).")
            return {
                "id": f"plink_mock_{reference_id or '001'}",
                "short_url": f"https://rzp.io/i/mock_{reference_id or '001'}",
                "status": "created",
                "amount": int(amount * 100),
                "currency": "INR",
                "reference_id": reference_id,
            }

        payload = {
            "amount": int(amount * 100),
            "currency": "INR",
            "accept_partial": False,
            "description": description,
            "customer": {
                "name": customer_name,
                "email": customer_email,
                "contact": customer_contact or "+919999999999",
            },
            "notify": {
                "sms": True,
                "email": True,
            },
            "reference_id": reference_id,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/payment_links",
                    auth=auth,
                    json=payload,
                )
                if response.status_code in [200, 201]:
                    return response.json()
                else:
                    error_json = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
                    raise RazorpayGatewayError(
                        f"Razorpay error ({response.status_code}): {response.text}",
                        status_code=response.status_code,
                        error_data=error_json,
                    )
        except httpx.RequestError as e:
            logger.error(f"Network error connecting to Razorpay: {e}")
            raise RazorpayGatewayError(f"Network connection failure: {str(e)}")

    async def fetch_payment(self, payment_id: str) -> Dict[str, Any]:
        auth = self._get_auth()
        if not auth:
            return {
                "id": payment_id,
                "status": "captured",
                "amount": 2500000,
                "currency": "INR",
            }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/payments/{payment_id}",
                    auth=auth,
                )
                if response.status_code == 200:
                    return response.json()
                else:
                    raise RazorpayGatewayError(
                        f"Failed to fetch payment: {response.text}",
                        status_code=response.status_code,
                    )
        except httpx.RequestError as e:
            raise RazorpayGatewayError(f"Network connection failure: {str(e)}")

razorpay_client = RazorpayClient()

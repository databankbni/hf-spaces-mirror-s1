import os
import httpx
from dotenv import load_dotenv

load_dotenv()

class AIGateway:
    def __init__(self):
        """এআই গেটওয়ে ইনিশিয়ালাইজেশন"""
        self.timeout = 30.0

    async def forward_request(self, endpoint: str, payload: dict, api_key: str = None) -> dict:
        """এক্সটার্নাল বা ইন্টারনাল এআই মডেলের কাছে সিকিউরড রিকোয়েস্ট ফরওয়ার্ড করার ফাংশন"""
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(endpoint, json=payload, headers=headers, timeout=self.timeout)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                return {
                    "success": False,
                    "error": f"HTTP error occurred: {e.response.status_code}",
                    "details": e.response.text
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": f"An unexpected error occurred: {str(e)}"
                }

# গ্লোবাল ইনস্ট্যান্স
ai_gateway = AIGateway()

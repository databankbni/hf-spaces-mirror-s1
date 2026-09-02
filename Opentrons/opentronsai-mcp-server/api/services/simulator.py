"""
Protocol Simulator Service.
Simulates Opentrons protocols using the HuggingFace Space simulator.
"""

import uuid
import requests
from typing import Optional

from api.settings import Settings


class ProtocolSimulator:
    """Simulates Opentrons protocols using the external HuggingFace Space simulator."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.url = settings.simulator_url

    def simulate(self, protocol: str) -> str:
        """
        Simulate a Python protocol using the Opentrons HuggingFace Space.

        Args:
            protocol: Python protocol code to simulate

        Returns:
            Simulation result message
        """
        protocol_name = f"{uuid.uuid4()}.py"
        data = {"name": protocol_name, "content": protocol}
        hf_token: str = self.settings.huggingface_api_key.get_secret_value()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {hf_token}"
        }

        try:
            response = requests.post(self.url, json=data, headers=headers, timeout=120)

            if response.status_code != 200:
                body = response.text.strip()
                if body.lstrip().startswith("<!") or "text/html" in (
                    response.headers.get("content-type") or ""
                ):
                    return (
                        f"Simulator unavailable: HTTP {response.status_code} HTML response "
                        f"from {self.url} (check HUGGINGFACE_API_KEY access and SIMULATOR_URL)"
                    )
                return f"Simulation Error: {body}"

            response_data = response.json()

            if "error_message" in response_data:
                return f"Protocol Error: {response_data['error_message']}"
            elif "protocol_name" in response_data:
                return f"Simulation Success: {response_data['run_status']}"
            else:
                return "Unexpected response from simulator"

        except requests.Timeout:
            return "Simulation timed out after 120 seconds"
        except requests.RequestException as e:
            return f"Simulation request failed: {str(e)}"
        except Exception as e:
            return f"Simulation failed: {str(e)}"

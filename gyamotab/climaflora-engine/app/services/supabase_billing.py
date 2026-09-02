from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException

from app.config import Settings


class SupabaseBillingStore:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.client = client or httpx.AsyncClient(timeout=12.0)

    def _headers(self, key: str, bearer: str | None = None) -> dict[str, str]:
        headers = {"apikey": key, "Content-Type": "application/json"}
        headers["Authorization"] = f"Bearer {bearer or key}"
        return headers

    async def authenticate(self, token: str) -> dict[str, Any]:
        if not self.settings.supabase_url or not self.settings.supabase_anon_key:
            raise HTTPException(503, "Authentication is not configured")
        response = await self.client.get(
            f"{self.settings.supabase_url.rstrip('/')}/auth/v1/user",
            headers=self._headers(self.settings.supabase_anon_key, token),
        )
        if response.status_code != 200:
            raise HTTPException(401, "Invalid or expired session")
        return response.json()

    async def profile(self, user_id: str) -> dict[str, Any]:
        response = await self._rest_get(
            "climaflora_profiles", {"id": f"eq.{user_id}", "select": "*"}
        )
        rows = response.json()
        return rows[0] if rows else {"id": user_id, "plan": "FREE", "billing_status": None}

    async def profile_by_customer(self, customer_id: str) -> dict[str, Any] | None:
        response = await self._rest_get(
            "climaflora_profiles", {"stripe_customer_id": f"eq.{customer_id}", "select": "*"}
        )
        rows = response.json()
        return rows[0] if rows else None

    async def update_profile(self, user_id: str, values: dict[str, Any]) -> None:
        response = await self.client.patch(
            f"{self.settings.supabase_url.rstrip('/')}/rest/v1/climaflora_profiles",
            params={"id": f"eq.{user_id}"},
            headers={**self._service_headers(), "Prefer": "return=minimal"},
            json=values,
        )
        self._raise_service_error(response)

    async def generate_magic_link(self, email: str, redirect_to: str) -> tuple[str, str]:
        response = await self.client.post(
            f"{self.settings.supabase_url.rstrip('/')}/auth/v1/admin/generate_link",
            headers=self._service_headers(),
            json={
                "type": "magiclink",
                "email": email,
                "options": {"redirectTo": redirect_to},
            },
        )
        self._raise_service_error(response)
        payload = response.json()
        properties = payload.get("properties") or {}
        user = payload.get("user") or properties.get("user") or {}
        user_id = user.get("id")
        action_link = properties.get("action_link") or payload.get("action_link")
        if not user_id or not action_link:
            raise HTTPException(503, "Supabase did not return a login link")
        await self.ensure_profile(str(user_id))
        return str(user_id), str(action_link)

    async def ensure_profile(self, user_id: str) -> None:
        """Repair the rare Auth user that exists without its public profile."""
        existing = await self._rest_get(
            "climaflora_profiles", {"id": f"eq.{user_id}", "select": "id"}
        )
        if existing.json():
            return
        response = await self.client.post(
            f"{self.settings.supabase_url.rstrip('/')}/rest/v1/climaflora_profiles",
            params={"on_conflict": "id"},
            headers={
                **self._service_headers(),
                "Prefer": "resolution=ignore-duplicates,return=minimal",
            },
            json={"id": user_id, "plan": "FREE", "role": "USER"},
        )
        self._raise_service_error(response)

    async def sostagora_grant(self, wordpress_user_id: int) -> dict[str, Any] | None:
        response = await self._rest_get(
            "climaflora_sostagora_grants",
            {"wordpress_user_id": f"eq.{wordpress_user_id}", "select": "*"},
        )
        rows = response.json()
        return rows[0] if rows else None

    async def upsert_sostagora_grant(self, values: dict[str, Any]) -> None:
        response = await self.client.post(
            f"{self.settings.supabase_url.rstrip('/')}/rest/v1/climaflora_sostagora_grants",
            params={"on_conflict": "wordpress_user_id"},
            headers={
                **self._service_headers(),
                "Prefer": "resolution=merge-duplicates,return=minimal",
            },
            json=values,
        )
        self._raise_service_error(response)

    async def claim_event(self, event_id: str, event_type: str, created: int | None) -> bool:
        response = await self.client.post(
            f"{self.settings.supabase_url.rstrip('/')}/rest/v1/climaflora_billing_events",
            headers={**self._service_headers(), "Prefer": "return=minimal"},
            json={"stripe_event_id": event_id, "event_type": event_type, "stripe_created": created},
        )
        if response.status_code == 409:
            return False
        self._raise_service_error(response)
        return True

    async def complete_event(self, event_id: str, error: str | None = None) -> None:
        values = {"processed": error is None, "processing_error": error}
        response = await self.client.patch(
            f"{self.settings.supabase_url.rstrip('/')}/rest/v1/climaflora_billing_events",
            params={"stripe_event_id": f"eq.{event_id}"},
            headers={**self._service_headers(), "Prefer": "return=minimal"},
            json=values,
        )
        self._raise_service_error(response)

    async def _rest_get(self, table: str, params: dict[str, str]) -> httpx.Response:
        response = await self.client.get(
            f"{self.settings.supabase_url.rstrip('/')}/rest/v1/{table}",
            params=params,
            headers=self._service_headers(),
        )
        self._raise_service_error(response)
        return response

    def _service_headers(self) -> dict[str, str]:
        if not self.settings.supabase_service_role_key:
            raise HTTPException(503, "Billing datastore is not configured")
        return self._headers(self.settings.supabase_service_role_key)

    @staticmethod
    def _raise_service_error(response: httpx.Response) -> None:
        if response.status_code >= 400:
            raise HTTPException(503, "Billing datastore unavailable")

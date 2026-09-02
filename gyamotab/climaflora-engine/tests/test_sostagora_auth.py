from __future__ import annotations

import hashlib

import pytest

from app.routers.sostagora_auth import SostagoraIdentity, _grant_values, _sync_identity


class FakeStore:
    def __init__(self, grant=None):
        self.grant = grant
        self.upserted = None
        self.updated = None

    async def sostagora_grant(self, wordpress_user_id):
        return self.grant

    async def upsert_sostagora_grant(self, values):
        self.upserted = values

    async def update_profile(self, user_id, values):
        self.updated = (user_id, values)


def identity(active: bool = True) -> SostagoraIdentity:
    return SostagoraIdentity(
        wordpress_user_id=42,
        email="CLIENT@EXAMPLE.COM",
        active=active,
        access_level="sostagora" if active else "none",
        issued_at=1_787_570_000,
    )


def test_grant_stores_only_a_normalized_email_hash():
    values = _grant_values(identity())
    assert values["email_hash"] == hashlib.sha256(b"client@example.com").hexdigest()
    assert "email" not in values
    assert values["active"] is True


@pytest.mark.asyncio
async def test_sync_revokes_a_linked_user_without_touching_stripe_state():
    store = FakeStore({"supabase_user_id": "user-123"})
    user_id = await _sync_identity(identity(active=False), store)

    assert user_id == "user-123"
    assert store.upserted["active"] is False
    assert store.updated[0] == "user-123"
    assert store.updated[1]["sostagora_access"] is False
    assert "plan" not in store.updated[1]
    assert "billing_status" not in store.updated[1]


@pytest.mark.asyncio
async def test_sync_keeps_an_unlinked_grant_pending():
    store = FakeStore()
    user_id = await _sync_identity(identity(active=True), store)

    assert user_id is None
    assert store.upserted["wordpress_user_id"] == 42
    assert store.updated is None

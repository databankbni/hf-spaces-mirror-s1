import pytest
from pydantic import ValidationError

from app.config import Settings
from app.routers.billing import CheckoutRequest, _apply_event, _price_map, _price_to_plan
from app.services.entitlements import Plan


def settings() -> Settings:
    return Settings(
        stripe_price_plus_monthly="price_plus_m",
        stripe_price_plus_yearly="price_plus_y",
        stripe_price_pro_monthly="price_pro_m",
        stripe_price_pro_yearly="price_pro_y",
    )


def test_price_ids_are_server_controlled():
    configured = settings()
    assert _price_map(configured)[("PLUS", "monthly")] == "price_plus_m"
    assert _price_to_plan(configured, "price_pro_y") == (Plan.PRO, "yearly")
    assert _price_to_plan(configured, "price_attacker") == (Plan.FREE, None)


def test_checkout_requires_current_legal_acceptance():
    with pytest.raises(ValidationError):
        CheckoutRequest(plan="PLUS", interval="monthly")

    payload = CheckoutRequest(
        plan="PRO",
        interval="yearly",
        legal_version="2026-08-24",
        terms_accepted=True,
        immediate_service_requested=True,
    )
    assert payload.legal_version == "2026-08-24"


class FakeStore:
    def __init__(self):
        self.updated = None

    async def update_profile(self, user_id, values):
        self.updated = (user_id, values)

    async def profile_by_customer(self, customer_id):
        return None


@pytest.mark.asyncio
async def test_subscription_event_syncs_known_price():
    store = FakeStore()
    event = {
        "type": "customer.subscription.updated",
        "data": {"object": {
            "id": "sub_1", "customer": "cus_1", "status": "active",
            "metadata": {"climaflora_user_id": "user_1"},
            "items": {"data": [{"price": {"id": "price_plus_y"}}]},
            "current_period_end": 123456, "cancel_at_period_end": False,
        }},
    }
    await _apply_event(event, store, settings())
    user_id, values = store.updated
    assert user_id == "user_1"
    assert values["plan"] == "PLUS"
    assert values["billing_interval"] == "yearly"
    assert values["billing_status"] == "active"
    assert values["current_period_end"] == "1970-01-02T10:17:36+00:00"


@pytest.mark.asyncio
async def test_unknown_price_never_grants_paid_access():
    store = FakeStore()
    event = {
        "type": "customer.subscription.created",
        "data": {"object": {
            "id": "sub_bad", "customer": "cus_1", "status": "active",
            "metadata": {"climaflora_user_id": "user_1"},
            "items": {"data": [{"price": {"id": "price_untrusted"}}]},
        }},
    }
    await _apply_event(event, store, settings())
    assert store.updated[1]["plan"] == "FREE"

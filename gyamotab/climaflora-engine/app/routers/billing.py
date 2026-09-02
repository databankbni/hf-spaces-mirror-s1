from __future__ import annotations

import logging
import secrets
import string
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.services.entitlements import Plan, entitlements_for
from app.services.supabase_billing import SupabaseBillingStore

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/billing", tags=["billing"])


class CheckoutRequest(BaseModel):
    plan: Literal["PLUS", "PRO"]
    interval: Literal["monthly", "yearly"]
    legal_version: Literal["2026-08-24"]
    terms_accepted: Literal[True]
    immediate_service_requested: Literal[True]


class SessionResponse(BaseModel):
    url: str


SettingsDep = Annotated[Settings, Depends(get_settings)]


def _bearer(authorization: Annotated[str | None, Header()] = None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Authentication required")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(401, "Authentication required")
    return token


def _configured(settings: Settings) -> None:
    if not settings.billing_enabled:
        raise HTTPException(503, "Billing is not enabled")
    if not settings.stripe_restricted_key:
        raise HTTPException(503, "Stripe is not configured")


def _stripe_client(settings: Settings) -> stripe.StripeClient:
    _configured(settings)
    return stripe.StripeClient(settings.stripe_restricted_key)


def _price_map(settings: Settings) -> dict[tuple[str, str], str]:
    return {
        ("PLUS", "monthly"): settings.stripe_price_plus_monthly,
        ("PLUS", "yearly"): settings.stripe_price_plus_yearly,
        ("PRO", "monthly"): settings.stripe_price_pro_monthly,
        ("PRO", "yearly"): settings.stripe_price_pro_yearly,
    }


def _price_to_plan(settings: Settings, price_id: str | None) -> tuple[Plan, str | None]:
    for (plan, interval), configured_id in _price_map(settings).items():
        if configured_id and secrets.compare_digest(configured_id, price_id or ""):
            return Plan(plan), interval
    return Plan.FREE, None


async def _identity(token: str, settings: Settings) -> tuple[dict[str, Any], SupabaseBillingStore]:
    store = SupabaseBillingStore(settings)
    return await store.authenticate(token), store


@router.get("/catalog")
def catalog(settings: SettingsDep) -> dict[str, Any]:
    """Public product copy; Stripe Price IDs intentionally stay server-side."""
    return {
        "currency": "EUR",
        "plans": [
            {"code": "FREE", "name": "Découverte", "monthly": 0, "yearly": 0},
            {"code": "PLUS", "name": "Plus", "monthly": 890, "yearly": 9700},
            {"code": "PRO", "name": "Pro", "monthly": 1790, "yearly": 19700},
        ],
        "checkout_available": bool(settings.billing_enabled),
        "tax_note": "Le montant final et les taxes applicables sont confirmés dans Stripe Checkout.",
    }


@router.get("/me")
async def billing_me(
    token: Annotated[str, Depends(_bearer)], settings: SettingsDep
) -> dict[str, Any]:
    user, store = await _identity(token, settings)
    profile = await store.profile(user["id"])
    access = entitlements_for(
        profile.get("plan"),
        profile.get("billing_status"),
        bool(profile.get("sostagora_access")),
    )
    return {
        "plan": access.plan,
        "subscription_status": profile.get("billing_status"),
        "interval": profile.get("billing_interval"),
        "period_end": profile.get("current_period_end"),
        "cancel_at_period_end": bool(profile.get("cancel_at_period_end")),
        "subscription_management": (
            "stripe"
            if profile.get("stripe_customer_id")
            else "sostagora"
            if profile.get("sostagora_access")
            else None
        ),
        "entitlements": access.public_dict(),
    }


@router.post("/checkout", response_model=SessionResponse)
async def create_checkout(
    payload: CheckoutRequest,
    token: Annotated[str, Depends(_bearer)],
    settings: SettingsDep,
) -> SessionResponse:
    user, store = await _identity(token, settings)
    profile = await store.profile(user["id"])
    price_id = _price_map(settings).get((payload.plan, payload.interval), "")
    if not price_id:
        raise HTTPException(503, "This billing option is not configured")

    suffix = "".join(secrets.choice(string.ascii_lowercase) for _ in range(8))
    accepted_at = datetime.now(UTC).isoformat()
    legal_metadata = {
        "climaflora_user_id": user["id"],
        "legal_version": payload.legal_version,
        "terms_accepted": "true",
        "immediate_service_requested": "true",
        "legal_accepted_at": accepted_at,
    }
    params: dict[str, Any] = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": settings.billing_success_url,
        "cancel_url": settings.billing_cancel_url,
        "client_reference_id": user["id"],
        "customer_email": user.get("email"),
        "subscription_data": {"metadata": legal_metadata},
        "metadata": {**legal_metadata, "requested_plan": payload.plan},
        "integration_identifier": f"climaflora_{suffix}",
    }
    if profile.get("stripe_customer_id"):
        params.pop("customer_email", None)
        params["customer"] = profile["stripe_customer_id"]
    session = _stripe_client(settings).v1.checkout.sessions.create(params)
    if not session.url:
        raise HTTPException(502, "Stripe did not return a checkout URL")
    return SessionResponse(url=session.url)


@router.post("/portal", response_model=SessionResponse)
async def create_portal(
    token: Annotated[str, Depends(_bearer)], settings: SettingsDep
) -> SessionResponse:
    user, store = await _identity(token, settings)
    profile = await store.profile(user["id"])
    customer = profile.get("stripe_customer_id")
    if not customer:
        raise HTTPException(409, "No Stripe customer is associated with this account")
    params: dict[str, Any] = {"customer": customer, "return_url": settings.billing_cancel_url}
    if settings.stripe_customer_portal_configuration:
        params["configuration"] = settings.stripe_customer_portal_configuration
    session = _stripe_client(settings).v1.billing_portal.sessions.create(params)
    return SessionResponse(url=session.url)


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(request: Request, settings: SettingsDep) -> dict[str, Any]:
    _configured(settings)
    if not settings.stripe_webhook_secret:
        raise HTTPException(503, "Stripe webhook is not configured")
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, signature, settings.stripe_webhook_secret)
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise HTTPException(400, "Invalid Stripe webhook") from exc

    event_data = event.to_dict_recursive() if hasattr(event, "to_dict_recursive") else dict(event)
    store = SupabaseBillingStore(settings)
    event_id = event_data["id"]
    if not await store.claim_event(event_id, event_data["type"], event_data.get("created")):
        return {"received": True, "duplicate": True}
    try:
        await _apply_event(event_data, store, settings)
        await store.complete_event(event_id)
    except Exception as exc:
        logger.exception("Stripe event %s failed", event_id)
        await store.complete_event(event_id, type(exc).__name__)
        raise
    return {"received": True}


async def _apply_event(event: dict[str, Any], store: SupabaseBillingStore, settings: Settings) -> None:
    event_type = event["type"]
    obj = event["data"]["object"]
    if event_type == "checkout.session.completed":
        user_id = obj.get("client_reference_id") or obj.get("metadata", {}).get("climaflora_user_id")
        if user_id:
            await store.update_profile(
                user_id,
                {"stripe_customer_id": obj.get("customer"), "stripe_subscription_id": obj.get("subscription")},
            )
        return
    if event_type.startswith("customer.subscription."):
        items = obj.get("items", {}).get("data", [])
        price_id = items[0].get("price", {}).get("id") if items else None
        plan, interval = _price_to_plan(settings, price_id)
        user_id = obj.get("metadata", {}).get("climaflora_user_id")
        if not user_id:
            profile = await store.profile_by_customer(obj.get("customer", ""))
            user_id = profile and profile.get("id")
        if not user_id:
            raise RuntimeError("Stripe subscription is not linked to a ClimaFlora user")
        period_end = obj.get("current_period_end")
        period_end_iso = (
            datetime.fromtimestamp(period_end, UTC).isoformat()
            if isinstance(period_end, (int, float))
            else None
        )
        await store.update_profile(
            user_id,
            {
                "plan": plan.value,
                "stripe_customer_id": obj.get("customer"),
                "stripe_subscription_id": obj.get("id"),
                "subscription_price_id": price_id,
                "billing_status": obj.get("status"),
                "billing_interval": interval,
                "current_period_end": period_end_iso,
                "cancel_at_period_end": bool(obj.get("cancel_at_period_end")),
            },
        )
    # invoice events are intentionally retained in the idempotency ledger. Access
    # changes only from subscription state, avoiding premature grants from invoices.

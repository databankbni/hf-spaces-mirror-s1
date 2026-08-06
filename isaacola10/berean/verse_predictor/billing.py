"""Stripe billing: checkout, customer portal, and webhook handling.

Keys come from the app-key vault (admin console) with env-var fallbacks —
see store.KNOWN_APP_KEYS. Nothing here is required for the app to run: when
Stripe isn't configured, endpoints report "billing not configured" and the
rest of Verseo works normally.

Plans: free (default) → plus → speaker. The Stripe price IDs for the paid
plans are stored in the vault (stripe_price_plus / stripe_price_speaker).
"""
import store

PLANS = ("free", "plus", "speaker")


def _stripe():
    import stripe

    key = store.get_app_key("stripe_secret_key")
    if not key:
        return None
    stripe.api_key = key
    return stripe


def is_configured() -> bool:
    return bool(store.get_app_key("stripe_secret_key"))


def price_for_plan(plan: str) -> str:
    if plan == "plus":
        return store.get_app_key("stripe_price_plus")
    if plan == "speaker":
        return store.get_app_key("stripe_price_speaker")
    return ""


def plan_for_price(price_id: str) -> str:
    if price_id and price_id == store.get_app_key("stripe_price_plus"):
        return "plus"
    if price_id and price_id == store.get_app_key("stripe_price_speaker"):
        return "speaker"
    return ""


def create_checkout(user: dict, plan: str, origin: str) -> str:
    """Create a subscription Checkout Session; returns the redirect URL."""
    stripe = _stripe()
    if stripe is None:
        raise RuntimeError("Billing is not configured (no Stripe secret key).")
    price = price_for_plan(plan)
    if not price:
        raise RuntimeError(f"No Stripe price configured for the '{plan}' plan.")

    kwargs = dict(
        mode="subscription",
        line_items=[{"price": price, "quantity": 1}],
        success_url=f"{origin}/?billing=success",
        cancel_url=f"{origin}/pricing?billing=cancelled",
        client_reference_id=user["id"],
        metadata={"user_id": user["id"], "plan": plan},
        subscription_data={"metadata": {"user_id": user["id"], "plan": plan}},
    )
    existing = (store.get_user(user["id"]) or {}).get("stripe_customer_id")
    if existing:
        kwargs["customer"] = existing
    elif user.get("email"):
        kwargs["customer_email"] = user["email"]
    session = stripe.checkout.Session.create(**kwargs)
    return session.url


def create_portal(user: dict, origin: str) -> str:
    """Customer portal for managing/cancelling the subscription."""
    stripe = _stripe()
    if stripe is None:
        raise RuntimeError("Billing is not configured (no Stripe secret key).")
    customer = (store.get_user(user["id"]) or {}).get("stripe_customer_id")
    if not customer:
        raise RuntimeError("No billing profile yet — subscribe first.")
    session = stripe.billing_portal.Session.create(
        customer=customer, return_url=f"{origin}/"
    )
    return session.url


def verify_webhook(payload: bytes, signature: str):
    """Verify + parse a webhook. Returns the event dict or raises."""
    import stripe

    secret = store.get_app_key("stripe_webhook_secret")
    if not secret:
        raise RuntimeError("Webhook secret not configured.")
    return stripe.Webhook.construct_event(payload, signature, secret)


def apply_event(event: dict):
    """Apply a (verified) Stripe event to our records. Idempotent.

    Separated from HTTP handling so it can be unit-tested with plain dicts.
    """
    etype = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}

    if etype == "checkout.session.completed":
        meta = obj.get("metadata") or {}
        user_id = meta.get("user_id") or obj.get("client_reference_id") or ""
        plan = meta.get("plan") or "plus"
        customer = obj.get("customer") or ""
        email = (obj.get("customer_details") or {}).get("email") or ""
        if user_id:
            store.set_user_billing(
                user_id, plan=plan, status="active",
                stripe_customer_id=customer or None,
            )
        store.record_payment(
            stripe_id=obj.get("id", ""), user_id=user_id, email=email,
            amount=int(obj.get("amount_total") or 0),
            currency=obj.get("currency") or "usd",
            status="paid", description=f"Checkout — {plan}",
        )

    elif etype in ("invoice.paid", "invoice.payment_succeeded"):
        customer = obj.get("customer") or ""
        user = store.get_user_by_customer(customer) if customer else None
        store.record_payment(
            stripe_id=obj.get("id", ""),
            user_id=(user or {}).get("id", ""),
            email=obj.get("customer_email") or (user or {}).get("email", ""),
            amount=int(obj.get("amount_paid") or 0),
            currency=obj.get("currency") or "usd",
            status="paid", description="Subscription invoice",
        )

    elif etype == "customer.subscription.updated":
        customer = obj.get("customer") or ""
        user = store.get_user_by_customer(customer) if customer else None
        if user:
            items = ((obj.get("items") or {}).get("data")) or []
            price_id = ((items[0].get("price") or {}).get("id")) if items else ""
            plan = plan_for_price(price_id) or (obj.get("metadata") or {}).get("plan") or user["plan"]
            status = obj.get("status") or "active"
            if status in ("canceled", "unpaid", "incomplete_expired"):
                store.set_user_billing(user["id"], plan="free", status=status)
            else:
                store.set_user_billing(user["id"], plan=plan, status=status)

    elif etype == "customer.subscription.deleted":
        customer = obj.get("customer") or ""
        user = store.get_user_by_customer(customer) if customer else None
        if user:
            store.set_user_billing(user["id"], plan="free", status="canceled")

# ═══════════════════════════════════════════════════════════════
# KOMBAZ CREDITS — Wallet API router
# Mount this into app.py with:  app.include_router(wallet_router)
# ═══════════════════════════════════════════════════════════════
#
# Environment variables required (set as HF Space secrets, never commit):
#   SUPABASE_URL              — https://xxxx.supabase.co
#   SUPABASE_SERVICE_ROLE_KEY — service_role key (server-only, NEVER expose to browser)
#   GUMROAD_WEBHOOK_SECRET    — shared secret you set in Gumroad's ping settings
#
# Closed-loop rules enforced here (keep these — they're what keeps this
# unlicensed under Israeli payment-services law):
#   1. No endpoint ever converts credits back to real money.
#   2. No endpoint transfers credits between two different users.
#   3. Every write is idempotent (source+reference_id) so a webhook retry
#      or double-click never double-credits or double-charges.

import os
import hmac
import hashlib
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from postgrest.exceptions import APIError
import httpx

wallet_router = APIRouter(prefix="/api/wallet", tags=["wallet"])

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
GUMROAD_WEBHOOK_SECRET = os.environ.get("GUMROAD_WEBHOOK_SECRET", "")

SB_HEADERS = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json",
}


async def get_current_user_id(request: Request) -> str:
    """Verify the Supabase JWT sent by the frontend and return the user id.
    Reuses the same Supabase Auth you already run for KOMBAZ SYNTH — no new
    auth system needed."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    token = auth_header.split(" ", 1)[1]
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={"apikey": SUPABASE_SERVICE_KEY, "Authorization": f"Bearer {token}"},
        )
    if r.status_code != 200:
        raise HTTPException(401, "invalid or expired session")
    return r.json()["id"]


async def _sb_insert_ledger_row(user_id: str, amount_cents: int, kind: str,
                                 source: str, reference_id: str | None,
                                 description: str):
    """Insert one ledger row. Relies on the unique (source, reference_id)
    index for idempotency — a duplicate webhook simply gets a 409 from
    Postgres, which we swallow as 'already processed'."""
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{SUPABASE_URL}/rest/v1/wallet_ledger",
            headers={**SB_HEADERS, "Prefer": "return=representation"},
            json={
                "user_id": user_id,
                "amount_cents": amount_cents,
                "kind": kind,
                "source": source,
                "reference_id": reference_id,
                "description": description,
            },
        )
    if r.status_code == 409:
        return {"already_processed": True}
    if r.status_code >= 300:
        raise HTTPException(500, f"ledger write failed: {r.text}")
    return r.json()


async def _sb_get_balance(user_id: str) -> int:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SUPABASE_URL}/rest/v1/wallet_balances",
            headers=SB_HEADERS,
            params={"user_id": f"eq.{user_id}", "select": "balance_cents"},
        )
    rows = r.json()
    return rows[0]["balance_cents"] if rows else 0


@wallet_router.get("/balance")
async def get_balance(user_id: str = Depends(get_current_user_id)):
    cents = await _sb_get_balance(user_id)
    return {"balance_ils": cents / 100.0, "balance_cents": cents}


@wallet_router.get("/history")
async def get_history(user_id: str = Depends(get_current_user_id), limit: int = 50):
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SUPABASE_URL}/rest/v1/wallet_ledger",
            headers=SB_HEADERS,
            params={
                "user_id": f"eq.{user_id}",
                "select": "amount_cents,kind,source,description,created_at",
                "order": "created_at.desc",
                "limit": str(limit),
            },
        )
    return r.json()


class SpendRequest(BaseModel):
    amount_ils: float          # positive number, e.g. 25.00
    source: str                # 'academy' | 'synth-store' | 'market-stall'
    reference_id: str          # your own order/course id — for idempotency
    description: str


@wallet_router.post("/spend")
async def spend(body: SpendRequest, user_id: str = Depends(get_current_user_id)):
    if body.amount_ils <= 0:
        raise HTTPException(400, "amount_ils must be positive")
    cents = round(body.amount_ils * 100)
    balance = await _sb_get_balance(user_id)
    if balance < cents:
        raise HTTPException(402, "insufficient credit balance")
    result = await _sb_insert_ledger_row(
        user_id, -cents, "spend", body.source, body.reference_id, body.description
    )
    new_balance = await _sb_get_balance(user_id)
    return {"ok": True, "spent_ils": body.amount_ils, "new_balance_ils": new_balance / 100.0,
            "ledger": result}


# ─── Gumroad webhook: real-money top-up → credit ───────────────────────
# In Gumroad: Settings → Advanced → Ping URL → set to
#   https://<your-space>.hf.space/api/wallet/gumroad-webhook
# Sell a "KOMBAZ Credits ₪100 top-up" style product; the webhook credits
# the buyer's wallet automatically. The buyer must be logged in and have
# entered their kombaz account email at Gumroad checkout — match on email.

def _verify_gumroad_signature(raw_body: bytes, signature: str) -> bool:
    if not GUMROAD_WEBHOOK_SECRET:
        return True  # no secret configured — skip verification (dev only)
    expected = hmac.new(GUMROAD_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


@wallet_router.post("/gumroad-webhook")
async def gumroad_webhook(request: Request):
    raw = await request.body()
    form = await request.form()
    signature = request.headers.get("x-gumroad-signature", "")
    if not _verify_gumroad_signature(raw, signature):
        raise HTTPException(401, "bad signature")

    sale_id = form.get("sale_id")
    email = form.get("email")
    price_cents = int(form.get("price", "0"))  # Gumroad sends price in cents
    if not sale_id or not email or price_cents <= 0:
        raise HTTPException(400, "malformed webhook payload")

    # Look up the kombaz user by email via Supabase Auth admin API
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SUPABASE_URL}/auth/v1/admin/users",
            headers=SB_HEADERS,
            params={"email": email},
        )
    users = r.json().get("users", [])
    if not users:
        # Buyer paid but has no kombaz account yet — log for manual reconciliation
        # rather than silently dropping real money.
        raise HTTPException(202, f"no kombaz account for {email} — needs manual credit")
    user_id = users[0]["id"]

    result = await _sb_insert_ledger_row(
        user_id=user_id,
        amount_cents=price_cents,
        kind="topup",
        source="gumroad",
        reference_id=sale_id,
        description=f"Gumroad top-up, sale {sale_id}",
    )
    return {"ok": True, "credited_cents": price_cents, "ledger": result}

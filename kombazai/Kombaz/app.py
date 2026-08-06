"""
KOMBAZ SYNTH — backend (FastAPI)
Serves the static index.html and provides the Stripe Checkout + Supabase
Auth endpoints. Requires a Hugging Face Space with SDK = "docker" (a
Static space cannot run this file or read Secrets — Secrets are only
injected into a running container's environment).
"""
import os
import json
import logging
from contextlib import asynccontextmanager
import stripe
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("kombaz")

# Reads directly from the Hugging Face Space's Secrets (injected as env
# vars into the container) — never hardcode these values in the file.
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")

SUPABASE_URL = os.environ.get("SUPABASE_URL") or os.environ.get("VITE_SUPABASE_URL")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("VITE_SUPABASE_ANON_KEY")            # safe client-side, RLS-protected
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")       # server-only, bypasses RLS — never expose
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL")                        # not currently used in Python logic —
                                                                     # admin detection lives in the Supabase
                                                                     # trigger (supabase_setup.sql), which is
                                                                     # the actual source of truth for who gets
                                                                     # permanent Pro. Checked at startup below
                                                                     # only so a missing/mismatched value shows
                                                                     # up in the logs rather than failing silently.

# Local, file-based riff storage — the existing Dockerfile already sets
# up DATA_DIR=/app/data with the right permissions.
DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
RECORDINGS_DIR = os.path.join(DATA_DIR, "recordings")
os.makedirs(RECORDINGS_DIR, exist_ok=True)

# Server-side client, using the SERVICE key so it can flip is_pro after a
# real payment regardless of RLS. Never send this client's key to the browser.
supabase: Client | None = (
    create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    if SUPABASE_URL and SUPABASE_SERVICE_KEY else None
)


def check_environment():
    """Prints a quick, readable summary of which required Secrets are
    actually present at container startup, so a missing one shows up
    immediately in the HF Space logs instead of surfacing later as a
    confusing 500 somewhere deep in a request. ADMIN_EMAIL is checked
    the same way as everything else here — logged if missing, never
    raised — so a first deploy without it set yet still comes up fine;
    it just won't have an admin account auto-granted Pro until it's added."""
    required = {
        "SUPABASE_URL": SUPABASE_URL,
        "SUPABASE_KEY": SUPABASE_SERVICE_KEY,   # the key that actually matters server-side
        "STRIPE_SECRET_KEY": stripe.api_key,
        "STRIPE_WEBHOOK_SECRET": STRIPE_WEBHOOK_SECRET,
        "STRIPE_PRICE_ID": STRIPE_PRICE_ID,
        "ADMIN_EMAIL": ADMIN_EMAIL,
    }
    for name, value in required.items():
        if value:
            log.info(f"[ENV OK] {name}")
        else:
            log.warning(f"[ENV MISSING] {name}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup — on_event("startup") is deprecated in current FastAPI;
    # this is the modern replacement. Nothing needed on shutdown, so
    # everything runs before the yield and the function just ends.
    check_environment()
    yield


app = FastAPI(lifespan=lifespan)


def site_url_from_request(request: Request) -> str:
    """Build an absolute base URL (scheme + host) from the incoming
    request itself, rather than requiring a separate SITE_URL secret.
    Stripe's success_url/cancel_url need a fully-qualified URL — a bare
    relative path isn't guaranteed to be accepted. Hugging Face Spaces
    (and virtually every reverse proxy) set X-Forwarded-Proto, so this
    correctly reports "https" even though the container itself only
    ever sees a plain HTTP connection from the proxy. Falls back to the
    request's own scheme for local testing without a proxy in front."""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("host", request.url.netloc)
    return f"{proto}://{host}"


def get_user_id_from_auth_header(request: Request) -> str:
    """Extracts the Supabase user ID from a Bearer token in the
    Authorization header, verifying it against Supabase's own Auth
    server (not just decoding it locally) — the recommended approach
    per Supabase's own Python API docs."""
    if not supabase:
        raise HTTPException(500, "Supabase is not configured on the server (missing Secrets).")
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "You need to be signed in first.")
    token = auth_header[len("Bearer "):]
    try:
        user_response = supabase.auth.get_user(token)
    except Exception:
        raise HTTPException(401, "Your session has expired — please sign in again.")
    user = getattr(user_response, "user", None)
    if not user:
        raise HTTPException(401, "Your session has expired — please sign in again.")
    return user.id


@app.get("/api/recordings")
async def list_recordings():
    """Returns the saved riff names as a plain JSON array (an empty one
    if there are none yet) — index.html's refreshRiffList() expects
    exactly this shape. Previously this route didn't exist at all,
    which is a real 404 on every page load, not just a harmless one."""
    try:
        names = sorted(
            f[:-5] for f in os.listdir(RECORDINGS_DIR) if f.endswith(".json")
        )
    except OSError:
        names = []
    return JSONResponse(names)


@app.post("/api/recordings")
async def save_recording(request: Request):
    body = await request.json()
    name = body.get("name")
    if not name:
        raise HTTPException(400, "A recording needs a name.")
    safe_name = "".join(c for c in name if c.isalnum() or c in "-_ ").strip()
    if not safe_name:
        raise HTTPException(400, "That name isn't usable as a filename.")
    path = os.path.join(RECORDINGS_DIR, safe_name + ".json")
    with open(path, "w") as f:
        json.dump(body, f)
    return JSONResponse({"saved": safe_name})


@app.get("/api/recordings/{name}")
async def get_recording(name: str):
    safe_name = "".join(c for c in name if c.isalnum() or c in "-_ ").strip()
    path = os.path.join(RECORDINGS_DIR, safe_name + ".json")
    if not os.path.isfile(path):
        raise HTTPException(404, "No recording with that name.")
    with open(path) as f:
        return JSONResponse(json.load(f))


@app.get("/config")
async def get_config():
    """Public, non-secret configuration the frontend needs to talk to
    Supabase directly (sign-up/sign-in, reading its own profile row).
    The anon key is DESIGNED to be public — it can only do what Row
    Level Security explicitly allows. This is a different trust level
    entirely from STRIPE_SECRET_KEY or SUPABASE_SERVICE_KEY, which must
    never appear here or anywhere in the frontend."""
    return JSONResponse({
        "supabaseUrl": SUPABASE_URL,
        "supabaseAnonKey": SUPABASE_ANON_KEY,
    })


@app.post("/create-checkout-session")
async def create_checkout_session(request: Request):
    if not stripe.api_key or not STRIPE_PRICE_ID:
        raise HTTPException(500, "Stripe is not configured on the server (missing Secrets).")
    user_id = get_user_id_from_auth_header(request)
    site_url = site_url_from_request(request)
    try:
        session = stripe.checkout.Session.create(
            mode="subscription",              # yearly subscription, per your plan
            line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
            success_url=f"{site_url}/?upgrade=success&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{site_url}/?upgrade=cancelled",
            # allow_promotion_codes lets you run discount codes later
            # without touching this code again
            allow_promotion_codes=True,
            # ties this checkout session to the signed-in Supabase user,
            # so verify-session below knows whose profile to update
            client_reference_id=user_id,
        )
    except stripe.StripeError as e:
        raise HTTPException(400, str(e))
    return JSONResponse({"url": session.url})


@app.get("/verify-session")
async def verify_session(session_id: str):
    """
    Confirms with Stripe itself that this checkout session actually
    completed, rather than trusting the presence of ?upgrade=success in
    the URL (which anyone could type in manually). If it's genuinely
    paid, persists is_pro=true on that user's own profile row in
    Supabase — using the SERVICE key, which bypasses RLS specifically
    so this one server-side action can do what the user themselves
    isn't allowed to (see supabase_setup.sql: no user-facing update
    policy exists for profiles, on purpose).
    """
    if not stripe.api_key:
        raise HTTPException(500, "Stripe is not configured on the server (missing Secrets).")
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except stripe.StripeError as e:
        raise HTTPException(400, str(e))
    is_paid = session.status == "complete" and session.payment_status in ("paid", "no_payment_required")
    if is_paid and session.client_reference_id and supabase:
        try:
            supabase.table("profiles").update({
                "is_pro": True,
                "stripe_customer_id": session.customer,
            }).eq("id", session.client_reference_id).execute()
        except Exception as e:
            # the payment itself succeeded — don't hide that — but flag
            # that persisting Pro status failed, so it can be fixed
            # manually rather than silently lost
            raise HTTPException(500, f"Payment succeeded, but saving Pro status failed: {e}")
    return JSONResponse({"valid": is_paid})


@app.post("/api/webhook")
async def stripe_webhook(request: Request):
    """
    The authoritative payment-confirmation path. Unlike /verify-session
    (which only runs if the user's browser actually makes it back to
    the success page), Stripe calls this directly, server-to-server,
    the moment a payment completes — so Pro status gets granted even if
    the browser crashes or the tab gets closed right after paying.

    Signature verification uses stripe.SignatureVerificationError (the
    top-level reference) rather than stripe.error.SignatureVerificationError —
    the nested .error submodule has been unreliable across recent
    stripe-python versions (it was briefly inaccessible, then restored
    in v14+), while the top-level alias has stayed stable throughout.
    """
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(500, "Stripe webhook is not configured on the server (missing STRIPE_WEBHOOK_SECRET).")
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except ValueError:
        raise HTTPException(400, "Invalid webhook payload.")
    except stripe.SignatureVerificationError:
        raise HTTPException(400, "Invalid webhook signature.")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        user_id = session.get("client_reference_id")
        if user_id and supabase:
            try:
                supabase.table("profiles").update({
                    "is_pro": True,
                    "stripe_customer_id": session.get("customer"),
                }).eq("id", user_id).execute()
            except Exception as e:
                # Stripe retries webhooks that don't return 2xx — returning
                # 500 here is deliberate so a transient Supabase hiccup gets
                # retried automatically rather than silently lost.
                raise HTTPException(500, f"Failed to update Pro status: {e}")

    return JSONResponse({"received": True})


def _find_existing_path(*candidates):
    """Returns the first candidate path that actually exists on disk, or
    None if none do. Checking existence explicitly — and only ever
    calling FileResponse on a path we've already confirmed is real — is
    the whole fix here: FileResponse doesn't validate its path when
    constructed, only when Starlette actually tries to send it, and by
    then a missing file surfaces as an unhandled RuntimeError (a 500),
    not a clean 404."""
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


@app.api_route("/manifest.webmanifest", methods=["GET", "HEAD"])
async def serve_manifest():
    app_dir = os.path.dirname(os.path.abspath(__file__))
    found = _find_existing_path(
        os.path.join(app_dir, "manifest.webmanifest"),
        os.path.join(app_dir, "static", "manifest.webmanifest"),
    )
    if not found:
        raise HTTPException(404, "manifest.webmanifest not found on the server.")
    return FileResponse(found, media_type="application/manifest+json")


@app.api_route("/icon-{size}.png", methods=["GET", "HEAD"])
async def serve_icons(size: str):
    app_dir = os.path.dirname(os.path.abspath(__file__))
    filename = f"icon-{size}.png"
    found = _find_existing_path(
        os.path.join(app_dir, filename),
        os.path.join(app_dir, "static", filename),
    )
    if not found:
        raise HTTPException(404, f"{filename} not found on the server.")
    return FileResponse(found, media_type="image/png")


# Serve the app itself — index.html plus anything else in this folder.
# Keep this AFTER the API routes so they aren't shadowed by the static
# file handler.
app.mount("/", StaticFiles(directory=".", html=True), name="static")

if __name__ == "__main__":
    # matches the existing Dockerfile's CMD ["python", "app.py"] — HF
    # Docker Spaces expect the app listening on port 7860
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)

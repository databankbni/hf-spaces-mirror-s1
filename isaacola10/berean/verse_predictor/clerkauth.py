"""Verify Clerk session tokens on the backend.

The frontend signs users in with Clerk (email/password, magic link, or social
providers configured in the Clerk dashboard) and sends the active session
token as `Authorization: Bearer <jwt>`. We verify it here via Clerk's JWKS
endpoint (RS256), derived from the publishable key's embedded Frontend API
domain. Session tokens carry minimal claims (just `sub`, the Clerk user id),
so email/display name are looked up from Clerk's Backend API and cached
briefly to avoid a network round trip on every request.
"""
import base64
import os
import time

CLERK_PUBLISHABLE_KEY = (
    os.environ.get("CLERK_PUBLISHABLE_KEY")
    or os.environ.get("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "")
)
CLERK_SECRET_KEY = os.environ.get("CLERK_SECRET_KEY", "")


def _issuer_from_publishable_key(pk: str) -> str:
    """pk_(test|live)_<base64("<frontend-api-domain>$")> -> https://<domain>"""
    try:
        _, _, encoded = pk.split("_", 2)
        padded = encoded + "=" * (-len(encoded) % 4)
        domain = base64.b64decode(padded).decode().rstrip("$")
        return f"https://{domain}" if domain else ""
    except Exception:  # noqa: BLE001
        return ""


CLERK_ISSUER = _issuer_from_publishable_key(CLERK_PUBLISHABLE_KEY)

_jwks_client = None
_jwks_checked = 0.0
_profile_cache: dict[str, tuple[float, dict]] = {}
_PROFILE_TTL = 300


def is_configured() -> bool:
    return bool(CLERK_SECRET_KEY and CLERK_ISSUER)


def _get_jwks_client():
    global _jwks_client, _jwks_checked
    if _jwks_client is not None or not CLERK_ISSUER:
        return _jwks_client
    if time.time() - _jwks_checked < 60:
        return None
    _jwks_checked = time.time()
    try:
        from jwt import PyJWKClient

        _jwks_client = PyJWKClient(f"{CLERK_ISSUER}/.well-known/jwks.json", cache_keys=True)
    except Exception:  # noqa: BLE001
        _jwks_client = None
    return _jwks_client


def verify_token(token: str) -> dict | None:
    """Return the JWT claims if the token is a valid Clerk session token."""
    token = (token or "").strip()
    if not token or token.count(".") != 2:
        return None
    import jwt

    client = _get_jwks_client()
    if client is None:
        return None
    try:
        key = client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token, key.key, algorithms=["RS256"],
            issuer=CLERK_ISSUER, options={"verify_aud": False},
        )
    except Exception:  # noqa: BLE001
        return None


def _fetch_profile(user_id: str) -> dict:
    cached = _profile_cache.get(user_id)
    if cached and time.time() - cached[0] < _PROFILE_TTL:
        return cached[1]
    info = {"email": "", "name": ""}
    if CLERK_SECRET_KEY and user_id:
        try:
            import requests

            r = requests.get(
                f"https://api.clerk.com/v1/users/{user_id}",
                headers={"Authorization": f"Bearer {CLERK_SECRET_KEY}"},
                timeout=5,
            )
            if r.ok:
                data = r.json()
                emails = data.get("email_addresses") or []
                primary_id = data.get("primary_email_address_id")
                primary = next(
                    (e["email_address"] for e in emails if e.get("id") == primary_id), None
                )
                info["email"] = primary or (emails[0]["email_address"] if emails else "")
                info["name"] = " ".join(
                    filter(None, [data.get("first_name"), data.get("last_name")])
                ).strip()
        except Exception:  # noqa: BLE001
            pass
    _profile_cache[user_id] = (time.time(), info)
    return info


def user_from_claims(claims: dict) -> dict:
    """Extract id / email / display name for a verified Clerk session."""
    user_id = claims.get("sub", "")
    profile = _fetch_profile(user_id) if user_id else {"email": "", "name": ""}
    return {"id": user_id, "email": profile["email"], "name": profile["name"]}

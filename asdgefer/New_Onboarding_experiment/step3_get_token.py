"""
Step 3: Get Auth Token
======================
- DEV:        Auto-login via Firebase REST API (has API key)
- TEST/PROD:  Asks user to paste bearer token from browser network tab

Usage:
  python step3_get_token.py --env dev --email demo+test@sarasanalytics.com --password Test@1234
  python step3_get_token.py --env test --token <paste-token-here>
"""

import sys
import json
import base64
import argparse
import requests

from env_config import get_config, add_env_arg

# ── Module-level cache for manual tokens ─────────────────────────────
# So the token is asked ONCE and reused across step3, step4, warehouse, etc.
_cached_manual_tokens = {}   # env_name -> token string


def get_auth_token(email: str, password: str, env: str = None, manual_token: str = None) -> dict:
    """
    Get a bearer token. Two modes:

    1. Firebase auto-login (dev) — uses email + password + Firebase API key
    2. Manual token (test/prod) — user pastes token from browser, we decode it

    The manual_token can be passed directly, or set via set_manual_token() before calling.
    """
    cfg = get_config(env)

    # ── Manual token mode (test/prod) ────────────────────────────────
    if cfg.REQUIRES_MANUAL_TOKEN:
        token = manual_token or _cached_manual_tokens.get(cfg.env_name)

        if not token:
            print(f"\n[Step 3] [{cfg.env_name.upper()}] Firebase auto-login not available.")
            print(f"[Step 3] Please paste the Super Admin bearer token from your browser.")
            print(f"[Step 3] (Network tab -> any API call -> Authorization header -> copy the token after 'Bearer ')\n")
            token = input("  Paste token: ").strip()
            if token.lower().startswith("bearer "):
                token = token[7:]

        if not token:
            return _fail("No token provided")

        # Cache it for reuse within this run
        _cached_manual_tokens[cfg.env_name] = token

        # Decode JWT to extract userId, companyId
        jwt_payload = _decode_jwt(token)
        if not jwt_payload:
            return _fail("Could not decode the pasted token. Make sure it's a valid JWT.")

        print(f"[Step 3] [{cfg.env_name.upper()}] Token accepted!")
        print(f"[Step 3] Email:      {jwt_payload.get('email', 'N/A')}")
        print(f"[Step 3] User ID:    {jwt_payload.get('userId', 'N/A')}")
        print(f"[Step 3] Company ID: {jwt_payload.get('companyId', 'N/A')}")
        print(f"[Step 3] Roles:      {jwt_payload.get('saras_claims', [])}")

        return {
            "success": True,
            "id_token": token,
            "refresh_token": None,
            "user_id": jwt_payload.get("userId"),
            "company_id": jwt_payload.get("companyId"),
            "firebase_uid": jwt_payload.get("user_id"),
            "expires_in": 3600,
            "jwt_payload": jwt_payload,
            "error": None,
        }

    # ── Firebase auto-login (dev) ────────────────────────────────────
    print(f"\n[Step 3] [{cfg.env_name}] Signing in as: {email}")

    payload = {
        "email": email,
        "password": password,
        "returnSecureToken": True,
    }

    try:
        response = requests.post(
            cfg.FIREBASE_SIGNIN_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )

        if response.status_code == 200:
            data = response.json()
            id_token = data["idToken"]
            refresh_token = data.get("refreshToken", "")
            expires_in = data.get("expiresIn", "3600")

            jwt_payload = _decode_jwt(id_token)

            print(f"[Step 3] Sign-in successful!")
            print(f"[Step 3] Firebase UID: {data.get('localId')}")
            print(f"[Step 3] User ID:      {jwt_payload.get('userId', 'N/A')}")
            print(f"[Step 3] Company ID:   {jwt_payload.get('companyId', 'N/A')}")
            print(f"[Step 3] Expires in:   {expires_in} seconds")

            return {
                "success": True,
                "id_token": id_token,
                "refresh_token": refresh_token,
                "user_id": jwt_payload.get("userId"),
                "company_id": jwt_payload.get("companyId"),
                "firebase_uid": data.get("localId"),
                "expires_in": int(expires_in),
                "jwt_payload": jwt_payload,
                "error": None,
            }
        else:
            error_data = response.json()
            error_msg = error_data.get("error", {}).get("message", "Unknown error")
            print(f"[Step 3] Failed: {error_msg}")
            return _fail(error_msg)

    except requests.exceptions.RequestException as e:
        print(f"[Step 3] Network error: {e}")
        return _fail(str(e))


def set_manual_token(env: str, token: str):
    """Pre-set a manual token so get_auth_token() won't prompt for it."""
    cfg = get_config(env)
    if token.lower().startswith("bearer "):
        token = token[7:]
    _cached_manual_tokens[cfg.env_name] = token


def refresh_token(refresh_tok: str, env: str = None) -> dict:
    cfg = get_config(env)
    print("[Step 3] Refreshing token...")

    response = requests.post(
        cfg.FIREBASE_REFRESH_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_tok,
        },
        timeout=30,
    )

    if response.status_code == 200:
        data = response.json()
        return {
            "success": True,
            "id_token": data["id_token"],
            "refresh_token": data["refresh_token"],
            "expires_in": int(data["expires_in"]),
            "error": None,
        }
    else:
        error_msg = response.json().get("error", {}).get("message", "Unknown")
        return {"success": False, "error": error_msg}


def _fail(error_msg: str) -> dict:
    return {
        "success": False,
        "id_token": None,
        "refresh_token": None,
        "user_id": None,
        "company_id": None,
        "firebase_uid": None,
        "expires_in": 0,
        "jwt_payload": None,
        "error": error_msg,
    }


def _decode_jwt(token: str) -> dict:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        payload_b64 = parts[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        return json.loads(payload_bytes)
    except Exception:
        return {}


def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Step 3: Get Auth Token")
    add_env_arg(parser)
    parser.add_argument("--email", help="Account email (dev only)")
    parser.add_argument("--password", help="Account password (dev only)")
    parser.add_argument("--token", help="Paste bearer token directly (test/prod)")
    parser.add_argument("--raw", action="store_true", help="Print only the bearer token")
    parser.add_argument("--refresh", default=None, help="Use refresh token (dev only)")
    args = parser.parse_args()

    if args.refresh:
        result = refresh_token(args.refresh, env=args.env)
    else:
        result = get_auth_token(
            email=args.email or "",
            password=args.password or "",
            env=args.env,
            manual_token=args.token,
        )

    if not result["success"]:
        print(f"\n  FAILED: {result['error']}")
        sys.exit(1)

    if args.raw:
        print(result["id_token"])
        return

    print(f"\n{'='*60}")
    print(f"  Token ready! User ID: {result.get('user_id')}, Company ID: {result.get('company_id')}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()

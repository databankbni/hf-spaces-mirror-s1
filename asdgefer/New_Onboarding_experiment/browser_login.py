"""
Browser Login - Token Capture via Playwright
=============================================
Opens the Saras IQ portal, logs in with given credentials,
and captures the bearer token from network traffic.

Works for ALL environments (dev/test/prod) — no Firebase API key needed.
This is how we get tokens when Firebase REST API is unavailable.

Usage:
  python browser_login.py --env test --email user@example.com --password Test@1234
"""

import sys
import json
import base64
import time
import argparse
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from env_config import get_config, add_env_arg


def login_and_capture_token(
    email: str,
    password: str,
    env: str = None,
    headless: bool = False,
    timeout_seconds: int = 60,
) -> dict:
    """
    Opens the IQ portal login page, fills email+password, clicks sign in,
    and intercepts network requests to capture the bearer token.

    Returns:
        {
            "success": True/False,
            "id_token": "eyJhbG...",
            "user_id": 4147,
            "company_id": 3440,
            "email": "user@example.com",
            "error": None or "error message"
        }
    """
    cfg = get_config(env)
    portal_url = cfg.PORTAL_LOGIN_URL

    if not portal_url:
        return {"success": False, "error": f"No PORTAL_LOGIN_URL configured for {cfg.env_name}"}

    print(f"\n[Browser Login] [{cfg.env_name.upper()}] Opening {portal_url}")
    print(f"[Browser Login] Email: {email}")

    result = {
        "success": False,
        "id_token": None,
        "user_id": None,
        "company_id": None,
        "email": email,
        "error": None,
    }

    captured_token = {"token": None}  # mutable container for closure

    def on_request(request):
        """Intercept outgoing requests and look for Authorization: Bearer header."""
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer ") and not captured_token["token"]:
            token = auth_header[7:]
            # Make sure it's a real JWT (3 parts)
            if token.count(".") == 2 and len(token) > 100:
                captured_token["token"] = token
                print(f"[Browser Login] Captured bearer token from request to: {request.url[:80]}...")

    def on_response(response):
        """Intercept Firebase signInWithPassword response to get the idToken."""
        if "identitytoolkit" in response.url and "signInWithPassword" in response.url:
            try:
                body = response.json()
                if body.get("idToken"):
                    captured_token["token"] = body["idToken"]
                    print(f"[Browser Login] Captured token from Firebase sign-in response!")
            except Exception:
                pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, args=["--start-maximized"])
        context = browser.new_context(viewport=None)
        page = context.new_page()

        # Listen for network traffic
        page.on("request", on_request)
        page.on("response", on_response)

        try:
            # Navigate to portal
            print(f"[Browser Login] Navigating to portal...")
            page.goto(portal_url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
            page.wait_for_timeout(3000)

            # Find and fill email field
            print(f"[Browser Login] Looking for email input...")
            email_filled = False
            email_selectors = [
                'input[type="email"]',
                'input[name="email"]',
                'input[placeholder*="email" i]',
                'input[placeholder*="Email" i]',
                'input[formcontrolname="email"]',
                'input[id*="email" i]',
            ]
            for selector in email_selectors:
                try:
                    el = page.locator(selector).first
                    if el.is_visible(timeout=3000):
                        el.click()
                        el.fill(email)
                        email_filled = True
                        print(f"[Browser Login] Filled email field")
                        break
                except Exception:
                    continue

            if not email_filled:
                # Fallback: try all visible text inputs
                inputs = page.locator('input[type="text"], input:not([type])').all()
                for inp in inputs:
                    try:
                        if inp.is_visible(timeout=1000):
                            inp.fill(email)
                            email_filled = True
                            print(f"[Browser Login] Filled email (fallback)")
                            break
                    except Exception:
                        continue

            if not email_filled:
                result["error"] = "Could not find email input field on login page"
                return result

            # Find and fill password field
            print(f"[Browser Login] Looking for password input...")
            pw_filled = False
            pw_selectors = [
                'input[type="password"]',
                'input[name="password"]',
                'input[placeholder*="password" i]',
                'input[formcontrolname="password"]',
            ]
            for selector in pw_selectors:
                try:
                    el = page.locator(selector).first
                    if el.is_visible(timeout=3000):
                        el.click()
                        el.fill(password)
                        pw_filled = True
                        print(f"[Browser Login] Filled password field")
                        break
                except Exception:
                    continue

            if not pw_filled:
                result["error"] = "Could not find password input field on login page"
                return result

            page.wait_for_timeout(500)

            # Click sign in button
            print(f"[Browser Login] Looking for Sign In button...")
            sign_in_clicked = False
            btn_selectors = [
                'button:has-text("Sign In")',
                'button:has-text("Login")',
                'button:has-text("Log In")',
                'button:has-text("Sign in")',
                'button[type="submit"]',
                'sa-button:has-text("Sign In")',
                'sa-button:has-text("Login")',
                'input[type="submit"]',
            ]
            for selector in btn_selectors:
                try:
                    btn = page.locator(selector).first
                    if btn.is_visible(timeout=2000):
                        btn.click()
                        sign_in_clicked = True
                        print(f"[Browser Login] Clicked Sign In!")
                        break
                except Exception:
                    continue

            if not sign_in_clicked:
                # Try pressing Enter as fallback
                page.keyboard.press("Enter")
                print(f"[Browser Login] Pressed Enter (fallback)")

            # Wait for login to complete and token to be captured
            print(f"[Browser Login] Waiting for login to complete...")
            max_wait = 20  # seconds
            for i in range(max_wait):
                if captured_token["token"]:
                    break
                page.wait_for_timeout(1000)
                if i % 5 == 4:
                    print(f"[Browser Login] Still waiting... ({i+1}s)")

            if captured_token["token"]:
                token = captured_token["token"]
                result["id_token"] = token
                result["success"] = True

                # Decode JWT to extract userId, companyId
                try:
                    payload_b64 = token.split(".")[1]
                    padding = 4 - len(payload_b64) % 4
                    if padding != 4:
                        payload_b64 += "=" * padding
                    payload = json.loads(base64.urlsafe_b64decode(payload_b64))
                    result["user_id"] = payload.get("userId")
                    result["company_id"] = payload.get("companyId")
                    print(f"[Browser Login] SUCCESS!")
                    print(f"  Email      : {payload.get('email', 'N/A')}")
                    print(f"  User ID    : {result['user_id']}")
                    print(f"  Company ID : {result['company_id']}")
                except Exception as e:
                    print(f"[Browser Login] Token captured but could not decode JWT: {e}")
            else:
                result["error"] = "Login completed but no bearer token was captured from network traffic"
                print(f"[Browser Login] FAILED: No token captured after {max_wait}s")

        except PWTimeout as e:
            result["error"] = f"Timeout: {e}"
            print(f"[Browser Login] Timeout: {e}")
        except Exception as e:
            result["error"] = str(e)
            print(f"[Browser Login] Error: {e}")
        finally:
            print("[Browser Login] Closing browser in 2 seconds...")
            page.wait_for_timeout(2000)
            context.close()
            browser.close()

    return result


def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Login via browser and capture bearer token")
    add_env_arg(parser)
    parser.add_argument("--email", required=True, help="Email to login with")
    parser.add_argument("--password", default=None, help="Password (default from env config)")
    parser.add_argument("--headless", action="store_true", help="Run browser without UI")
    args = parser.parse_args()

    cfg = get_config(args.env)
    password = args.password or cfg.DEFAULT_PASSWORD

    result = login_and_capture_token(
        email=args.email,
        password=password,
        env=args.env,
        headless=args.headless,
    )

    if result["success"]:
        print(f"\n{'='*50}")
        print(f"  SUCCESS! Token captured.")
        print(f"  Token (first 50 chars): {result['id_token'][:50]}...")
        print(f"{'='*50}")
    else:
        print(f"\n  FAILED: {result['error']}")
        sys.exit(1)


if __name__ == "__main__":
    main()

"""
Step 2: Email Verification + Password Setup
============================================
Uses Playwright to:
  1. Open Outlook Web and login
  2. Find the verification email from notifications@sarasanalytics.com
  3. Extract the "Confirm Email" link
  4. Navigate to the verification URL
  5. Fill password and submit

Usage:
  python step2_verify_email.py --env dev --email demo+poc2test@sarasanalytics.com
  python step2_verify_email.py --env dev --email demo+poc2test@sarasanalytics.com --password MyPass@123
"""

import sys
import os
import re
import time
import argparse
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from env_config import get_config, add_env_arg

OUTLOOK_URL = "https://outlook.office.com/mail/"


def verify_and_set_password(
    target_email: str,
    password: str = None,
    outlook_email: str = None,
    outlook_pw: str = None,
    headless: bool = False,
    timeout_seconds: int = 60,
    env: str = None,
) -> dict:
    cfg = get_config(env)
    password = password or cfg.DEFAULT_PASSWORD
    outlook_email = outlook_email or cfg.OUTLOOK_EMAIL
    outlook_pw = outlook_pw or cfg.OUTLOOK_PASSWORD

    print(f"\n[Step 2] [{cfg.env_name}] Verifying email for: {target_email}")
    print(f"[Step 2] Password to set: {password}")

    result = {
        "success": False,
        "verification_url": None,
        "error": None,
    }

    with sync_playwright() as p:
        # STEALTH MODULE: Erase Headless Bot Fingerprints & Optimize for Linux Containers (Prevent OOM memory crashes)
        stealth_args = [
            "--start-maximized",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-site-isolation-trials",
            "--window-size=1920,1080",
        ]
        
        browser = p.chromium.launch(
            headless=headless, 
            args=stealth_args,
            ignore_default_args=["--enable-automation"]
        )
        
        auth_file = "outlook_auth.json"
        use_session = os.path.exists(auth_file)
        
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            storage_state=auth_file if use_session else None,
            user_agent=user_agent
        )
        
        # --- THE CLOUDFLARE STEALTH PAYLOAD ---
        # Cloudflare Turnstile's JS Challenge specifically identifies Linux Docker Containers
        # by testing if WebGL, Chrome plugins, and 'window.chrome' objects organically exist.
        # We physically inject synthetic hardware identities into the JS Engine to pass the bot scores!
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){} };
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 1 });
            Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
            Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
            Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });

            // Realistic screen dimensions
            Object.defineProperty(screen, 'width', { get: () => 1920 });
            Object.defineProperty(screen, 'height', { get: () => 1080 });
            Object.defineProperty(screen, 'availWidth', { get: () => 1920 });
            Object.defineProperty(screen, 'availHeight', { get: () => 1040 });
            Object.defineProperty(screen, 'colorDepth', { get: () => 24 });
            window.outerWidth = 1920;
            window.outerHeight = 1080;

            // Notification permission (real browsers have this)
            if (!window.Notification) {
                window.Notification = { permission: 'default' };
            }

            // Remove Playwright/automation traces from Error stacks
            const originalError = Error;
            function PatchedError(...args) {
                const err = new originalError(...args);
                Object.defineProperty(err, 'stack', {
                    get: function() { return originalError.prototype.stack; }
                });
                return err;
            }

            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {
                if (parameter === 37445) return 'Intel Inc.';
                if (parameter === 37446) return 'Intel Iris OpenGL Engine';
                return getParameter(parameter);
            };
        """)

        page = context.new_page()

        if use_session:
            print("[Step 2] Using Cached Outlook Session (outlook_auth.json) - Bypassing Captchas!")

        try:
            verification_url = _find_verification_email(page, target_email, timeout_seconds, outlook_email, outlook_pw, use_session)

            if not verification_url:
                result["error"] = "Could not find verification email or extract link"
                return result

            result["verification_url"] = verification_url
            print(f"\n[Step 2] Verification URL found!")
            print(f"[Step 2] URL: {verification_url[:100]}...")

            # === REST API ULTRA-PATIENT APPROACH ===
            oob_code, api_key = _extract_firebase_tokens(verification_url)
            rest_success = False
            if oob_code and api_key:
                print(f"[Step 2] Extracted oobCode: {oob_code[:20]}... and apiKey dynamically!")
                rest_success = _rest_verify_and_set_password(page, oob_code, api_key, target_email, password)

            if rest_success:
                result["success"] = True
                print(f"\n[Step 2] Email verified and password set via REST API ULTRA-PATIENT protocol!")
            else:
                result["error"] = "REST API Ultra-Patient method failed. Cloudflare Fallback aborted to prevent dead-links."
                print("\n[Step 2] Email verification failed completely (REST timed out).")

        except PWTimeout as e:
            result["error"] = f"Timeout: {e}"
            print(f"\n[Step 2] Timeout error: {e}")
        except Exception as e:
            result["error"] = str(e)
            print(f"\n[Step 2] Error: {e}")
        finally:
            print("[Step 2] Closing browser in 3 seconds...")
            time.sleep(3)
            context.close()

    return result


def _find_verification_email(page, target_email: str, timeout_seconds: int, outlook_email: str, outlook_pw: str, use_session: bool = False) -> str:
    timeout_ms = timeout_seconds * 1000

    print("[Step 2] Opening Outlook Web...")
    page.goto(OUTLOOK_URL, wait_until="domcontentloaded", timeout=timeout_ms)

    if use_session:
        print("[Step 2] Session Loaded. Re-routing directly to inbox!")
        print("[Step 2] Waiting 20 seconds for verification email to be physically delivered to the inbox...")
        page.wait_for_timeout(20000)
    else:
        # Outlook Microsoft Authentication Flow
        try:
            email_input = page.locator('input[type="email"], input[name="loginfmt"]')
            email_input.wait_for(state="visible", timeout=15000)

            print(f"[Step 2] Providing Outlook Email: {outlook_email}")
            email_input.fill(outlook_email)
            page.keyboard.press("Enter")

            pw_input = page.locator('input[type="password"], input[name="passwd"]')
            pw_input.wait_for(state="visible", timeout=15000)

            print("[Step 2] Providing Outlook Password...")
            pw_input.fill(outlook_pw)
            page.keyboard.press("Enter")

            try:
                stay_signed_in_btn = page.locator('input[type="submit"][value="Yes"], button:has-text("Yes"), input[id="idSIButton9"]')
                stay_signed_in_btn.wait_for(state="visible", timeout=5000)
                try:
                    dont_show_cb = page.locator('input[name="DontShowAgain"]')
                    if dont_show_cb.is_visible(timeout=1000):
                        dont_show_cb.click()
                except Exception:
                    pass
                stay_signed_in_btn.click()
                print("[Step 2] Accepted 'Stay signed in' prompt.")
            except PWTimeout:
                pass

            try:
                secondary_btn = page.locator('a[id="CancelLinkButton"], button:has-text("Skip for now"), button:has-text("Done"), input[value="Done"], button:has-text("Next")')
                if secondary_btn.is_visible(timeout=3000):
                    secondary_btn.first.click()
                    print("[Step 2] Handled secondary Microsoft setup prompt.")
                    page.wait_for_timeout(2000)
            except Exception:
                pass

        except PWTimeout:
            print("[Step 2] Could not find initial Microsoft login. Assuming already logged in.")

    print("[Step 2] Waiting for Outlook inbox to load...")
    page.wait_for_timeout(5000)

    # ── Search & click the verification email ──
    # Each round re-submits the search (Outlook index may take time to catch up).
    # Round 1-3: specific query  |  Round 4-6: broader fallback query
    specific_query = f"from:notifications@sarasanalytics.com {target_email}"
    broad_query = f"from:notifications@sarasanalytics.com verify"
    max_rounds = 6

    email_clicked = False

    for round_num in range(1, max_rounds + 1):
        query = specific_query if round_num <= 3 else broad_query
        wait_before = 10 if round_num > 1 else 0  # give indexer time on retries

        if wait_before:
            print(f"[Step 2] Waiting {wait_before}s for Outlook index to catch up...")
            page.wait_for_timeout(wait_before * 1000)

        print(f"[Step 2] Search round {round_num}/{max_rounds}: {query}")

        # Locate or activate the search box
        search_input = page.locator('input[aria-label*="Search"], input[placeholder*="Search"], input[type="search"]').first
        try:
            search_input.wait_for(state="visible", timeout=5000)
        except Exception:
            try:
                search_btn = page.locator('[aria-label="Search"][role="button"]').first
                search_btn.click()
                page.wait_for_timeout(1000)
                search_input = page.locator('input[aria-label*="Search"], input[placeholder*="Search"], input[type="search"]').first
                search_input.wait_for(state="visible", timeout=5000)
            except Exception:
                pass

        # Submit the search
        try:
            search_input.click()
            page.wait_for_timeout(300)
            page.keyboard.press("Control+A")
            page.keyboard.press("Delete")
            page.wait_for_timeout(300)
            search_input.fill(query)
            page.keyboard.press("Enter")
            print("[Step 2] Search submitted, waiting for results...")
            page.wait_for_timeout(6000)
        except Exception as e:
            print(f"[Step 2] Search submission failed: {e}")
            continue

        # Check results
        try:
            email_items = page.locator('div[role="row"], [role="option"], [aria-label*="Saras Analytics"]').all()
            print(f"[Step 2] Found {len(email_items)} emails in results")
        except Exception:
            email_items = []

        if len(email_items) == 0:
            continue

        # Log first few results
        for i, email_item in enumerate(email_items[:5]):
            try:
                item_text = email_item.text_content(timeout=2000)
                print(f"[Step 2]   [{i}] {item_text[:100]}...")
            except Exception:
                pass

        # Try to click a matching email
        for i, email_item in enumerate(email_items):
            try:
                item_text = email_item.text_content(timeout=1500).lower()
                
                # Check for highly specific verification email indicators to avoid accidentally clicking older conversations
                is_match = False
                if any(kw in item_text for kw in ["suspect sender", "email verification", "verify your email"]):
                    is_match = True
                elif "verify" in item_text and "saras" in item_text:
                    is_match = True
                    
                if is_match:
                    print(f"[Step 2] Found exactly matching verification email #{i}: {item_text[:80]}...")
                    email_item.click()
                    page.wait_for_timeout(2000)
                    email_clicked = True
                    break
            except Exception:
                pass

        # If no keyword match but results exist, take the first one
        if not email_clicked and len(email_items) > 0:
            print(f"[Step 2] No keyword match — clicking first result...")
            try:
                email_items[0].click()
                page.wait_for_timeout(2000)
                email_clicked = True
            except Exception:
                pass

        if email_clicked:
            break

    if not email_clicked:
        print("[Step 2] Could not find or click confirmation email after all search rounds")
        return None

    # Extract the confirmation link
    print("[Step 2] Waiting for Microsoft Outlook to stream the email payload into the browser (Cloud environments can be slow)...")
    page.wait_for_timeout(15000)

    # Playwright's synchronous layout selectors cause massive memory spikes in heavy SPAs.
    # We bypass this completely using the native JS Engine.

    print("[Step 2] Scanning email via God Mode Extractor (16GB RAM Multi-Pass)...")
    try:
        import urllib.parse
        import base64
        import re

        def validate_and_decrypt_link(raw_url):
            if not raw_url: return None
            href = raw_url.replace("&amp;", "&")
            
            # Perfect unencrypted match
            if "accounts.sarasanalytics.com" in href and ("verify" in href.lower() or "code=" in href.lower() or "custom?" in href.lower()):
                return href
                
            # Sophos Wrap Decryption
            if "protection.sophos.com" in href:
                parsed = urllib.parse.urlparse(href)
                qs = urllib.parse.parse_qs(parsed.query)
                if "u" in qs:
                    raw_u = qs["u"][0]
                    b64_url = urllib.parse.unquote(raw_u).replace("-", "+").replace("_", "/")
                    b64_url += "=" * ((4 - len(b64_url) % 4) % 4)
                    try:
                        dec_url = base64.b64decode(b64_url).decode('utf-8', errors='ignore')
                        if "accounts.sarasanalytics.com" in dec_url or "verify" in dec_url.lower() or "custom?" in dec_url.lower():
                            return href
                    except Exception:
                        pass
            return None

        final_url = None

        # PASS 1: Native DOM Locator (Flawlessly bypasses Outlook's random string line-breaks)
        if not final_url:
            a_links = page.locator("a").all()
            print(f"[Step 2] [DEBUG] Found {len(a_links)} <a> elements in DOM. Inspecting...")
            for link in a_links:
                try:
                    href = link.get_attribute("href", timeout=1000)
                    final_url = validate_and_decrypt_link(href)
                    if final_url: 
                        print(f"[Step 2] URL locked via Native Playwright DOM Traversal.")
                        break
                except Exception:
                    continue

        # PASS 2: Bare-Metal Regex String Match (Flawlessly bypasses Shadow DOM invisibility)
        if not final_url:
            page_source = page.content()
            all_raw_urls = re.findall(r'https://[^\s"\'<>]+', page_source, re.IGNORECASE)
            print(f"[Step 2] [DEBUG] Extracted {len(all_raw_urls)} raw URLs via Regex. Decrypting...")
            for raw_url in all_raw_urls:
                final_url = validate_and_decrypt_link(raw_url)
                if final_url:
                    print(f"[Step 2] URL locked via HTML Raw DOM Regex Sweep: {raw_url[:80]}...")
                    break

        if final_url:
            print(f"[Step 2] Confirmation URL successfully locked on: {final_url[:100]}...")
            return final_url

    except Exception as e:
        import traceback
        print(f"\n[Step 2] 💥 FATAL CRASH IN SCANNING ENGINE 💥")
        traceback.print_exc()
        print(f"[Step 2] Scanning engine error: {e}\n")

    print("[Step 2] Could not find confirmation link in email")
    return None



# ─────────────────────────────────────────────────────────────

def _set_password(page, verification_url: str, password: str, timeout_seconds: int):
    timeout_ms = timeout_seconds * 1000

    import urllib.parse
    import base64
    
    if "protection.sophos.com" in verification_url:
        parsed = urllib.parse.urlparse(verification_url)
        qs = urllib.parse.parse_qs(parsed.query)
        if "u" in qs:
            try:
                raw_u = qs["u"][0]
                print(f"[Step 2] Raw Sophos payload: {raw_u[:50]}...")
                
                # Sophos sometimes returns URL-encoded string or URL-safe base64 (-_)
                b64_url = urllib.parse.unquote(raw_u)
                b64_url = b64_url.replace("-", "+").replace("_", "/")
                
                # Force strictly valid base64 padding
                b64_url += "=" * ((4 - len(b64_url) % 4) % 4)
                
                verification_url = base64.b64decode(b64_url).decode('utf-8', errors='ignore')
                print(f"[Step 2] Sophos Firewall Bypassed! Extracted RAW Backend URL: {verification_url[:100]}...")
            except Exception as e:
                import traceback
                print(f"[Step 2] Warning: Sophos decryption failed: {e}\n{traceback.format_exc()}")

    print(f"\n[Step 2] Navigating directly to raw verification page...")
    page.goto(verification_url, wait_until="domcontentloaded", timeout=timeout_ms)

    # === CLOUDFLARE CHALLENGE BYPASS LOOP ===
    # Cloudflare serves a JS challenge page that auto-redirects after verification.
    # The old code tried ONCE and gave up. We now loop patiently for up to 90 seconds,
    # continuously simulating human behavior and retrying navigation if needed.

    import time as _time
    import random

    cf_deadline = _time.time() + 90
    cf_check = 0
    cloudflare_cleared = False
    has_clicked_link = False
    navigation_retries = 0

    print("[Step 2] Waiting for Cloudflare JS challenge to resolve (up to 90s)...")

    while _time.time() < cf_deadline:
        cf_check += 1

        # Continuous organic mouse movement (Cloudflare scores mouse entropy)
        try:
            x = random.randint(80, 1400)
            y = random.randint(80, 900)
            page.mouse.move(x, y)
            page.wait_for_timeout(random.randint(150, 400))
            # Occasional click on empty space (mimics human idle behavior)
            if cf_check % 4 == 0:
                page.mouse.click(random.randint(200, 800), random.randint(200, 600))
        except Exception:
            pass

        # Read current page state
        try:
            body_text = page.locator("body").inner_text(timeout=5000).lower()
        except Exception:
            body_text = ""

        # SUCCESS: Verification page content detected
        if any(kw in body_text for kw in ["password", "verified", "get started", "confirm password", "your email is verified", "set your password"]):
            print(f"[Step 2] Cloudflare cleared! Verification page loaded (check #{cf_check})")
            cloudflare_cleared = True
            break

        # Detect Cloudflare challenge indicators
        is_cf_page = any(indicator in body_text for indicator in [
            "checking your browser",
            "just a moment",
            "attention required",
            "enable javascript",
            "ray id",
            "click here if you are not",
        ])

        if is_cf_page:
            if cf_check <= 3:
                print(f"[Step 2] Cloudflare JS challenge active (check #{cf_check}). Waiting for auto-redirect...")

            # After ~9 seconds of waiting, start clicking "Click here" link
            if cf_check >= 3 and not has_clicked_link:
                try:
                    click_link = page.get_by_text("Click here", exact=False).first
                    if click_link.is_visible(timeout=1000):
                        click_link.click()
                        has_clicked_link = True
                        print(f"[Step 2] Clicked 'Click here' manual redirect (check #{cf_check})")
                        try:
                            page.wait_for_load_state("domcontentloaded", timeout=10000)
                        except Exception:
                            pass
                        continue
                except Exception:
                    pass

            # Every ~15 seconds, re-navigate to the URL (Cloudflare may have set cf_clearance cookie)
            if cf_check % 5 == 0 and navigation_retries < 4:
                navigation_retries += 1
                has_clicked_link = False
                print(f"[Step 2] Re-navigating to verification URL (retry #{navigation_retries})...")
                try:
                    page.goto(verification_url, wait_until="domcontentloaded", timeout=30000)
                except Exception:
                    pass
                # Fresh mouse sweep after re-navigation
                try:
                    for mx, my in [(100, 150), (400, 300), (800, 500), (1100, 700)]:
                        page.mouse.move(mx + random.randint(-20, 20), my + random.randint(-20, 20))
                        page.wait_for_timeout(random.randint(200, 500))
                    page.mouse.click(600, 400)
                except Exception:
                    pass
                continue

            page.wait_for_timeout(3000)
            continue

        # Not Cloudflare and not the form — page might still be loading/transitioning
        page.wait_for_timeout(3000)

    if not cloudflare_cleared:
        # Final debug snapshot before giving up
        try:
            page.screenshot(path="CLOUDFLARE_FINAL_STATE.png", full_page=True)
            print("[Step 2] DEBUG: Saved CLOUDFLARE_FINAL_STATE.png")
        except Exception:
            pass
        try:
            final_text = page.locator("body").inner_text(timeout=3000)
            print(f"[Step 2] DEBUG: Final page text: {final_text[:500]}")
        except Exception:
            pass
        print("[Step 2] WARNING: Cloudflare may not have fully cleared. Attempting password form anyway...")

    print("[Step 2] Waiting for password form...")
    try:
        verified_msg = page.locator('text="Your email is verified"')
        verified_msg.wait_for(state="visible", timeout=5000)
        print("[Step 2] Email confirmed successfully! Setting up password...")
    except Exception:
        print("[Step 2] Confirmation message not distinctly found, natively continuing with password setup...")

    # The UI inherently expects "Password" and "Confirm Password".
    # Because we possess absolute DOM authority, we will systematically rip through 
    # all password boxes concurrently and violently fill them both perfectly!
    password_filled = False
    
    try:
        # Aggressively locate every single visible password bracket
        pw_inputs = page.locator('input[type="password"]').all()
        if len(pw_inputs) > 0:
            for index, pw_field in enumerate(pw_inputs):
                if pw_field.is_visible(timeout=2000):
                    pw_field.click()
                    pw_field.fill(password)
                    print(f"[Step 2] Successfully filled Password Box #{index+1}")
            password_filled = True
            
            # Submitting the Application
            print("[Step 2] Searching for 'Get Started' Submission Button...")
            get_started = page.locator('button:has-text("Get Started"), button:has-text("Submit"), button:has-text("Save")').first
            if get_started.is_visible(timeout=4000):
                get_started.click()
                print("[Step 2] Violently clicked 'Get Started'!")
            else:
                pw_inputs[-1].press("Enter")
                print("[Step 2] 'Get Started' button not distinct. Automatically pressed Enter key.")
                
            # Allow the server sequence to seamlessly digest the payload
            page.wait_for_timeout(5000)
    except Exception as e:
        print(f"[Step 2] Password box extraction fault: {e}")

    if not password_filled:
        # ABSOLUTE DEBUGGING
        print("\n==== ERROR DEBUG: PAGE CONTENT DUMP ====")
        try:
            print(page.locator("body").inner_text()[:1500])
        except Exception:
            try:
                print(page.content()[:1500])
            except Exception:
                print("Could not dump page content.")
        print("========================================")
        try:
            page.screenshot(path="ERROR_DUMP_VERIFY_PAGE.png", full_page=True)
            print("\n[Step 2] CRITICAL: A visual screenshot of the broken page was saved to 'C:\\Projects\\All-Env-Onboard\\ERROR_DUMP_VERIFY_PAGE.png'")
        except Exception as e:
            print(f"[Step 2] Failed to take screenshot: {e}")
        
        raise Exception("Could not find password input field. See ERROR_DUMP_VERIFY_PAGE.png for visual state.")

    confirm_selectors = [
        'input[placeholder="Confirm Password"]',
        'input[type="password"]:nth-of-type(2)',
        'input[formcontrolname="confirmPassword"]',
    ]

    confirm_filled = False
    for selector in confirm_selectors:
        try:
            cf_field = page.locator(selector).first
            if cf_field.is_visible(timeout=3000):
                cf_field.click()
                cf_field.fill(password)
                confirm_filled = True
                print(f"[Step 2] Filled 'Confirm Password'")
                break
        except Exception:
            continue

    if not confirm_filled:
        pw_inputs = page.locator('input[type="password"]').all()
        if len(pw_inputs) >= 2:
            pw_inputs[1].fill(password)
            confirm_filled = True
            print(f"[Step 2] Filled confirm password (fallback)")

    if not confirm_filled:
        raise Exception("Could not find confirm password input field")

    page.wait_for_timeout(500)

    submit_selectors = [
        'button:has-text("Get Started")',
        'sa-button:has-text("Get Started")',
        'sa-button label:has-text("Get Started")',
        'button[type="submit"]',
    ]

    clicked = False
    for selector in submit_selectors:
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=3000):
                btn.click()
                clicked = True
                print(f"[Step 2] Clicked 'Get Started'!")
                break
        except Exception:
            continue

    if not clicked:
        raise Exception("Could not find 'Get Started' button")

    print("[Step 2] Waiting for confirmation (5 seconds)...")
    page.wait_for_timeout(5000)

    try:
        page.reload(timeout=15000, wait_until="load")
        page.wait_for_timeout(3000)
    except Exception as e:
        print(f"[Step 2] Warning during refresh: {e}")

    current_url = page.url
    print(f"[Step 2] Current page after refresh: {current_url}")

    if "login" in current_url or "dashboard" in current_url or "auth" in current_url:
        print("[Step 2] Redirected to login/dashboard -- password setup complete!")
    else:
        print("[Step 2] Page after submit -- check if successful")


def main():
    parser = argparse.ArgumentParser(description="Step 2: Verify Email & Set Password")
    add_env_arg(parser)
    parser.add_argument("--email", required=True, help="The email address to verify")
    parser.add_argument("--password", default=None, help="Password to set (default from env config)")
    parser.add_argument("--headless", action="store_true", help="Run browser without UI")
    parser.add_argument("--timeout", type=int, default=60, help="Timeout in seconds (default: 60)")
    args = parser.parse_args()

    result = verify_and_set_password(
        target_email=args.email,
        password=args.password,
        headless=args.headless,
        timeout_seconds=args.timeout,
        env=args.env,
    )

    if result["success"]:
        print(f"\n{'='*50}")
        print(f"  SUCCESS! Email verified & password set.")
        print(f"  Next: Run step3_get_token.py --email {args.email}")
        print(f"{'='*50}\n")
    else:
        print(f"\n  FAILED: {result['error']}")
        sys.exit(1)


if __name__ == "__main__":
    main()

# ─────────────────────────────────────────────────────────────
# REST API APPROACH: Bypass Cloudflare entirely using Firebase
# ─────────────────────────────────────────────────────────────

def _extract_firebase_tokens(verification_url):
    import urllib.parse
    import base64

    url = verification_url
    if "protection.sophos.com" in url:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        if "u" in qs:
            try:
                raw_u = qs["u"][0]
                b64_url = urllib.parse.unquote(raw_u).replace("-", "+").replace("_", "/")
                b64_url += "=" * ((4 - len(b64_url) % 4) % 4)
                url = base64.b64decode(b64_url).decode('utf-8', errors='ignore')
            except Exception:
                return None, None

    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    codes = qs.get("oobCode", [])
    keys = qs.get("apiKey", [])
    return (codes[0] if codes else None, keys[0] if keys else None)

def _rest_verify_and_set_password(page, oob_code, api_key, email, password):
    import requests as http_req

    if not api_key:
        return False

    base = "https://identitytoolkit.googleapis.com/v1"

    print("[Step 2] [REST] Verifying email via Firebase REST API (bypassing Cloudflare)...")
    try:
        resp = http_req.post(f"{base}/accounts:update?key={api_key}", json={"oobCode": oob_code}, timeout=15)
    except Exception as e:
        print(f"[Step 2] [REST] Network error during verification: {e}")
        return False

    if resp.status_code != 200:
        print(f"[Step 2] [REST] Email verification failed: {resp.status_code} - {resp.text[:300]}")
        return False

    data = resp.json()
    print(f"[Step 2] [REST] Email verified successfully! (localId={data.get('localId')})")

    id_token = data.get("idToken")
    if id_token:
        print("[Step 2] [REST] Got idToken from verification response - setting password directly...")
        try:
            pw_resp = http_req.post(f"{base}/accounts:update?key={api_key}", json={"idToken": id_token, "password": password, "returnSecureToken": True}, timeout=15)
            if pw_resp.status_code == 200:
                print("[Step 2] [REST] Password set directly via idToken! Done!")
                return True
        except Exception:
            pass

    print("[Step 2] [REST] Sending password reset email to set the password...")
    try:
        reset_resp = http_req.post(f"{base}/accounts:sendOobCode?key={api_key}", json={"requestType": "PASSWORD_RESET", "email": email}, timeout=15)
    except Exception as e:
        print(f"[Step 2] [REST] Network error sending reset email: {e}")
        return False

    if reset_resp.status_code != 200:
        print(f"[Step 2] [REST] Failed to send reset email: {reset_resp.status_code} - {reset_resp.text[:300]}")
        return False

    print("[Step 2] [REST] Password reset email sent! Launching ULTRA-PATIENT Outlook Loop...")
    reset_code = _find_password_reset_code(page, email)
    if not reset_code:
        print("[Step 2] [REST] Could not find password reset email in Outlook after exhaustive wait.")
        return False

    print("[Step 2] [REST] Applying password reset with new password...")
    try:
        apply_resp = http_req.post(f"{base}/accounts:resetPassword?key={api_key}", json={"oobCode": reset_code, "newPassword": password}, timeout=15)
    except Exception as e:
        print(f"[Step 2] [REST] Network error applying reset: {e}")
        return False

    if apply_resp.status_code != 200:
        print(f"[Step 2] [REST] Password reset failed: {apply_resp.status_code} - {apply_resp.text[:300]}")
        return False

    print("[Step 2] [REST] Password set successfully via Firebase REST API!")
    return True

def _find_password_reset_code(page, target_email):
    import re
    OUTLOOK_URL = "https://outlook.office.com/mail/"
    
    # Force navigate back to inbox root to clear any cached states
    page.goto(OUTLOOK_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(10000)
    
    search_query = f"reset password {target_email}"
    print(f"[Step 2] [REST] Starting ULTRA-PATIENT search loop for: {search_query}")
    
    # MAXIMUM 15 ATTEMPTS (up to ~4-5 minutes elapsed physically waiting)
    MAX_ATTEMPTS = 15
    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"\n[Step 2] [REST] Search Attempt [{attempt}/{MAX_ATTEMPTS}] - Waiting for Microsoft Exchange Servers...")
        
        try:
            # Re-verify search box exists
            search_input = page.locator('input[aria-label*="Search"], input[placeholder*="Search"], input[type="search"]').first
            search_input.wait_for(state="visible", timeout=10000)
            
            search_input.click()
            page.keyboard.press("Control+A")
            page.keyboard.press("Delete")
            page.wait_for_timeout(1000) # Wait for UI to un-cache previous result tree
            
            search_input.fill(search_query)
            page.keyboard.press("Enter")
            print(f"[Step 2] [REST] Search sent. Giving UI 8 seconds to render results.")
            page.wait_for_timeout(8000)
            
            # Read Results
            # Strict locators specifically for the Email List area, excluding the Microsoft UI Profile Header
            email_items = page.locator('div[role="row"], [role="option"]').all()
            if len(email_items) == 0:
                print(f"[Step 2] [REST] Index Empty. Waiting 10s before retry.")
                page.wait_for_timeout(10000)
                continue
            
            print(f"[Step 2] [REST] FOUND {len(email_items)} EMAILS! Inspecting for 'reset' string...")
            
            found_email = False
            for item in email_items:
                if "reset" in item.text_content(timeout=1000).lower() or "saras" in item.text_content(timeout=1000).lower():
                    print("[Step 2] [REST] Target Acquired. Clicking Email...")
                    try:
                        item.click(timeout=3000)
                    except Exception:
                        continue
                    page.wait_for_timeout(5000)
                    found_email = True
                    break
                    
            if not found_email:
                if len(email_items) > 0:
                    try:
                        email_items[0].click(timeout=3000)
                    except Exception:
                        pass
                    page.wait_for_timeout(5000)
                    found_email = True
                    
            if not found_email:
                 page.wait_for_timeout(10000)
                 continue
                 
            # Extract Reset Link
            print("[Step 2] [REST] Deep DOM Scan for the reset URL...")
            page_source = page.content()
            for frame in page.frames:
                try:
                    page_source += "\n" + frame.content()
                except Exception:
                    pass
                    
            all_urls = re.findall(r'https://[^\s"\'<>]+', page_source, re.IGNORECASE)
            
            for raw_url in all_urls:
                url = raw_url.replace("&amp;", "&")
                code = _extract_oob_from_reset_url(url)
                if code:
                    print(f"[Step 2] [REST] ULTRA-PATIENT Engine Successfully Locked oobCode: {code[:15]}...!")
                    return code
                    
            print("[Step 2] [REST] Clicked email, but could not regex the specific Sophos/Identity link. Retry index poll...")
            page.wait_for_timeout(5000)
            
        except Exception as e:
            print(f"[Step 2] [REST] Error during polling attempt {attempt}: {e}")
            page.wait_for_timeout(5000)
            
    print("[Step 2] [REST] EXHAUSTED ALL 15 ATTEMPTS. SECOND EMAIL DID NOT ARRIVE. FATAL STOP.")
    return None

def _extract_oob_from_reset_url(url):
    import urllib.parse
    import base64

    if "protection.sophos.com" in url:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        if "u" in qs:
            try:
                raw_u = qs["u"][0]
                b64_url = urllib.parse.unquote(raw_u).replace("-", "+").replace("_", "/")
                b64_url += "=" * ((4 - len(b64_url) % 4) % 4)
                url = base64.b64decode(b64_url).decode('utf-8', errors='ignore')
            except Exception:
                return None

    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    codes = qs.get("oobCode", [])
    if codes:
        if "verify" not in url.lower():
            return codes[0]
    return None

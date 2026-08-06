import os

file_path = r"c:\Projects\All-Env-Onboard\step2_verify_email.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Replace the try logic
old_logic = """            # === PURE PLAYWRIGHT APPROACH ===
            print("[Step 2] Routing directly to Browser method to solve Cloudflare...")
            _set_password(page, verification_url, password, timeout_seconds)
            result["success"] = True
            print(f"\\n[Step 2] Email verified and password set via browser!")"""

new_logic = """            # === REST API ULTRA-PATIENT APPROACH ===
            oob_code, api_key = _extract_firebase_tokens(verification_url)
            rest_success = False
            if oob_code and api_key:
                print(f"[Step 2] Extracted oobCode: {oob_code[:20]}... and apiKey dynamically!")
                rest_success = _rest_verify_and_set_password(page, oob_code, api_key, target_email, password)

            if rest_success:
                result["success"] = True
                print(f"\\n[Step 2] Email verified and password set via REST API ULTRA-PATIENT protocol!")
            else:
                result["error"] = "REST API Ultra-Patient method failed. Cloudflare Fallback aborted to prevent dead-links."
                print("\\n[Step 2] Email verification failed completely (REST timed out).")"""

if old_logic in content:
    content = content.replace(old_logic, new_logic)
    print("Logic chunk 1 replaced.")
else:
    print("WARNING: Logic chunk 1 not found.")

# 2. Append the REST API logic
rest_logic = """
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
        print(f"\\n[Step 2] [REST] Search Attempt [{attempt}/{MAX_ATTEMPTS}] - Waiting for Microsoft Exchange Servers...")
        
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
            email_items = page.locator('div[role="row"], [role="option"], [aria-label*="Saras Analytics"]').all()
            if len(email_items) == 0:
                print(f"[Step 2] [REST] Index Empty. Waiting 10s before retry.")
                page.wait_for_timeout(10000)
                continue
            
            print(f"[Step 2] [REST] FOUND {len(email_items)} EMAILS! Inspecting for \"reset\" string...")
            
            found_email = False
            for item in email_items:
                if "reset" in item.text_content(timeout=1000).lower() or "saras" in item.text_content(timeout=1000).lower():
                    print("[Step 2] [REST] Target Acquired. Clicking Email...")
                    item.click()
                    page.wait_for_timeout(5000)
                    found_email = True
                    break
                    
            if not found_email:
                if len(email_items) > 0:
                    email_items[0].click()
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
                    page_source += "\\n" + frame.content()
                except Exception:
                    pass
                    
            all_urls = re.findall(r'https://[^\\s"\\\'<>]+', page_source, re.IGNORECASE)
            
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
"""

content += rest_logic

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
print("Saved step2_verify_email.py with ultra-patient logic appended.")

import os
import re

file_path = r"c:\Projects\All-Env-Onboard\step2_verify_email.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Replace the try/catch logic
legacy_logic = """            # PRIMARY: Try REST API approach (completely bypasses Cloudflare)
            oob_code, api_key = _extract_firebase_tokens(verification_url)
            rest_success = False
            if oob_code and api_key:
                print(f"[Step 2] Extracted oobCode: {oob_code[:20]}... and apiKey dynamically!")
                rest_success = _rest_verify_and_set_password(page, oob_code, api_key, target_email, password)

            if rest_success:
                result["success"] = True
                print(f"\\n[Step 2] Email verified and password set via REST API (Cloudflare bypassed)!")
            else:
                # FALLBACK: Browser approach (faces Cloudflare)
                if oob_code:
                    print("[Step 2] REST API approach did not fully succeed. Falling back to browser...")
                _set_password(page, verification_url, password, timeout_seconds)
                result["success"] = True
                print(f"\\n[Step 2] Email verified and password set via browser!")"""

new_logic = """            # === PURE PLAYWRIGHT APPROACH ===
            print("[Step 2] Routing directly to Browser method to solve Cloudflare...")
            _set_password(page, verification_url, password, timeout_seconds)
            result["success"] = True
            print(f"\\n[Step 2] Email verified and password set via browser!")"""

if legacy_logic in content:
    content = content.replace(legacy_logic, new_logic)
    print("Logic chunk 1 replaced.")
else:
    print("Logic chunk 1 not found.")

# 2. Chop out the 300-line REST logic
match = re.search(r'(# ─────────────────────────────────────────────────────────────\n# REST API APPROACH.*?)\n# ─────────────────────────────────────────────────────────────\n\ndef _set_password', content, flags=re.DOTALL)
if match:
    content = content.replace(match.group(1), "")
    print("Logic chunk 2 (REST API functions) pruned.")
else:
    print("Logic chunk 2 not found.")

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
print("Saved step2_verify_email.py")

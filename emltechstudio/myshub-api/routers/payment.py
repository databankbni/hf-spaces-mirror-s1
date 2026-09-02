"""Payment Router for MyShub API"""
from fastapi import APIRouter, HTTPException, Request, Header
from fastapi.responses import HTMLResponse
from datetime import datetime, timedelta, timezone
import os
import ast
import asyncio
from typing import Dict, Optional

from utils.db_private import get_shop_meta_by_email, get_shop_meta_by_slug, update_shop_meta, get_user_by_email, get_all_shops_meta
from utils.db_public import get_shop_content
from utils.security import verify_password

router = APIRouter()

payment_intents: Dict[str, dict] = {}

# ═══════════════════════════════════════════════════════════════════
# AUTO-EXPIRE LOGIC
# ═══════════════════════════════════════════════════════════════════

def auto_expire_shop(shop: dict) -> dict:
   """
   Check if a shop's subscription has expired. If yes, downgrade to free.
   Returns the (possibly updated) shop dict.
   """
   if shop.get("plan") == "free":
       return shop
   
   expires_at = shop.get("expires_at")
   if not expires_at:
       return shop
   
   try:
       expiry = datetime.fromisoformat(expires_at)
       now = datetime.now(timezone.utc)
       
       if expiry < now:
           email = shop["email"]
           update_shop_meta(email, {
               "plan": "free",
               "sub_type": "",
               "status": "active",
               "expires_at": None
           })
           # Update in-memory dict so callers see the change immediately
           shop["plan"] = "free"
           shop["sub_type"] = ""
           shop["expires_at"] = None
           print(f"[AUTO-EXPIRE] Downgraded {email} to Free (expired {expires_at})")
   except Exception as e:
       print(f"[AUTO-EXPIRE] Error checking expiry for {shop.get('email')}: {e}")
   
   return shop


async def run_expiry_check() -> int:
   """
   Check ALL shops and downgrade expired ones. Returns count of downgraded shops.
   """
   shops = get_all_shops_meta()
   expired_count = 0
   
   for shop in shops:
       original_plan = shop.get("plan")
       updated_shop = auto_expire_shop(shop)
       
       # If it was downgraded, count it
       if updated_shop.get("plan") == "free" and original_plan != "free":
           expired_count += 1
   
   return expired_count


async def expiry_scheduler():
   """
   Background task that runs immediately on startup, then every 30 minutes.
   """
   # Run immediately on startup
   print("[EXPIRY-SCHEDULER] Running initial expiry check on startup...")
   count = await run_expiry_check()
   print(f"[EXPIRY-SCHEDULER] Initial check complete. Downgraded {count} expired shops.")
   
   # Then loop every 30 minutes
   while True:
       await asyncio.sleep(30 * 60)  # 30 minutes = 1800 seconds
       try:
           print("[EXPIRY-SCHEDULER] Running periodic expiry check...")
           count = await run_expiry_check()
           print(f"[EXPIRY-SCHEDULER] Periodic check complete. Downgraded {count} expired shops.")
       except Exception as e:
           print(f"[EXPIRY-SCHEDULER] Error during periodic check: {e}")


# ═══════════════════════════════════════════════════════════════════
# PAYMENT INTENTS
# ═══════════════════════════════════════════════════════════════════

def create_payment_intent(email: str, plan: str) -> dict:
   email_lower = email.lower().strip()
   expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
   key = f"{email_lower}_{plan}"
   payment_intents[key] = {
       "email": email_lower,
       "plan": plan,
       "expires_at": expires_at,
       "used": False
   }
   return payment_intents[key]


def get_valid_intent(email: str, plan: str) -> Optional[dict]:
   email_lower = email.lower().strip()
   key = f"{email_lower}_{plan}"
   intent = payment_intents.get(key)
   if intent and not intent["used"] and intent["expires_at"] > datetime.now(timezone.utc):
       return intent
   return None


def mark_intent_used(email: str, plan: str):
   email_lower = email.lower().strip()
   key = f"{email_lower}_{plan}"
   if key in payment_intents:
       payment_intents[key]["used"] = True


def is_allowed_referer(request: Request) -> bool:
   referer = request.headers.get("referer", "")
   if not referer:
       return False
   allowed_domains = ["selar.co", "selar.com", "myshub.site", "localhost", "127.0.0.1"]
   for domain in allowed_domains:
       if domain in referer.lower():
           return True
   return False


SELAR_PRO_MANUAL = os.getenv("SELAR_PRO")
SELAR_PREMIUM_MANUAL = os.getenv("SELAR_PREMIUM")

PLANS = {
   "free": {
       "name": "Free",
       "price_ngn": 0,
       "price_usd": 0,
       "period": "Forever",
       "description": "Get started with your professional hub",
       "features": [
           "5 social platforms",
           "3 custom links",
           "Default layout & colors",
           "Catalog link button (Selar, Shopify, Sheets, etc.)",
           "Basic visit count",
           "Community support"
       ],
       "not_included": [
           "Brand colors",
           "Custom fonts",
           "Gradients",
           "No ads",
           "Analytics dashboard"
       ]
   },
   "pro": {
       "name": "Pro",
       "price_ngn": 1500,
       "price_usd": 5,
       "period": "per month",
       "description": "Brand your hub and remove ads",
       "features": [
           "10 social platforms",
           "10 custom links",
           "Brand colors — pick primary + secondary",
           "2 custom fonts",
           "No ads — clean footer",
           "Daily analytics + referrers",
           "Email support",
           "Powered by MyShub footer (small)"
       ],
       "not_included": [
           "Gradient colors",
           "Unlimited custom links",
           "White-label (remove MyShub branding)",
           "Priority support"
       ]
   },
   "premium": {
       "name": "Premium",
       "price_ngn": 3500,
       "price_usd": 10,
       "period": "per month",
       "description": "Full control, white-label, priority support",
       "features": [
           "Unlimited social platforms",
           "Unlimited custom links",
           "Gradient colors — blend 2+ colors",
           "Unlimited custom fonts",
           "White-label — no MyShub branding at all",
           "Full analytics + export",
           "Priority support + feedback form",
           "No ads — completely clean"
       ],
       "not_included": []
   }
}


def get_business_name(shop: dict) -> str:
   """Get business name from shop metadata or public content."""
   # Try public content first
   content = get_shop_content(shop.get("slug", ""))
   if content:
       return content.get("business_name", "Your Shop")
   return "Your Shop"


def success_page(shop: dict, plan: str, expires_at: str) -> str:
   business_name = get_business_name(shop)
   slug = shop["slug"]
   shop_url = f"https://myshub.site/{slug}"
   plan_name = PLANS.get(plan, {}).get("name", plan.upper())
   return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Payment Successful — MyShub</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet"/>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
:root{{--brand:#2563eb;--success:#10b981;--bg:#f8fafc;--card:#fff;--text:#0f172a;--text2:#475569;--border:#e2e8f0}}
body{{font-family:'Inter',sans-serif;background:linear-gradient(135deg,#dbeafe,#ede9fe);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}}
.card{{background:var(--card);border-radius:24px;padding:48px 40px;max-width:480px;width:100%;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,.08);border:1px solid var(--border)}}
.check{{width:72px;height:72px;background:linear-gradient(135deg,var(--success),#059669);border-radius:50%;display:flex;align-items:center;justify-content:center;margin:0 auto 24px;font-size:2rem;color:#fff}}
.badge{{display:inline-flex;align-items:center;gap:6px;background:#d1fae5;color:#065f46;padding:6px 16px;border-radius:50px;font-size:.75rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;margin-bottom:16px}}
h1{{font-size:1.6rem;font-weight:800;color:var(--text);margin-bottom:8px}}
p.sub{{color:var(--text2);font-size:1rem;margin-bottom:32px;line-height:1.6}}
.detail{{background:var(--bg);border-radius:16px;padding:20px;text-align:left;margin-bottom:24px}}
.detail-row{{display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid var(--border);font-size:.9rem}}
.detail-row:last-child{{border-bottom:none}}
.detail-row span:first-child{{color:var(--text2)}}
.detail-row span:last-child{{font-weight:600;color:var(--text)}}
.btn{{display:inline-flex;align-items:center;gap:8px;padding:14px 28px;background:var(--brand);color:#fff;border:none;border-radius:50px;font-weight:700;font-size:1rem;text-decoration:none;transition:all .3s;cursor:pointer}}
.btn:hover{{transform:translateY(-2px);box-shadow:0 8px 24px rgba(37,99,235,.3)}}
.btn-outline{{background:#fff;color:var(--brand);border:2px solid var(--brand);margin-left:12px}}
.btn-outline:hover{{background:var(--brand);color:#fff}}
.footer{{margin-top:24px;font-size:.8rem;color:#94a3b8}}
</style>
</head>
<body>
<div class="card">
<div class="check">✓</div>
<div class="badge">Payment Confirmed</div>
<h1>Welcome to {plan_name}!</h1>
<p class="sub">Your shop is now live with all {plan_name} features unlocked.</p>
<div class="detail">
<div class="detail-row"><span>Business</span><span>{business_name}</span></div>
<div class="detail-row"><span>Plan</span><span>{plan_name}</span></div>
<div class="detail-row"><span>Valid Until</span><span>{expires_at[:10]}</span></div>
<div class="detail-row"><span>Shop URL</span><span>myshub.site/{slug}</span></div>
</div>
<div>
<a href="{shop_url}" class="btn" target="_blank">View Your Shop →</a>
<a href="https://myshub.site/app.html" class="btn btn-outline">Go to Dashboard</a>
</div>
<div class="footer">MyShub by EML Tech Studio</div>
</div>
</body>
</html>"""


def error_page(message: str, show_form: bool = False) -> str:
   form_html = ""
   if show_form:
       form_html = """
<div style="margin-top:24px;">
<p style="color:#475569;font-size:.9rem;margin-bottom:12px;">Enter the email you used to register your shop:</p>
<input type="email" id="email" placeholder="your@email.com" style="width:100%;padding:12px 16px;border:2px solid #e2e8f0;border-radius:12px;font-size:1rem;outline:none;margin-bottom:12px;"/>
<button class="btn" onclick="retry()" style="width:100%;">Try Again</button>
<div id="msg" style="margin-top:12px;color:#ef4444;font-size:.9rem;display:none;"></div>
</div>
<script>
async function retry() {
const email = document.getElementById('email').value.trim();
if (!email) return;
const params = new URLSearchParams(window.location.search);
const plan = params.get('plan') || 'pro';
window.location.href = '/payment/activate/pro?email=' + encodeURIComponent(email) + '&plan=' + plan;
}
</script>
"""
   return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Activation Issue — MyShub</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet"/>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Inter',sans-serif;background:#fef2f2;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}}
.card{{background:#fff;border-radius:24px;padding:48px 40px;max-width:480px;width:100%;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,.08);border:1px solid #fecaca}}
.icon{{width:72px;height:72px;background:linear-gradient(135deg,#ef4444,#dc2626);border-radius:50%;display:flex;align-items:center;justify-content:center;margin:0 auto 24px;font-size:2rem;color:#fff}}
h1{{font-size:1.4rem;font-weight:800;color:#0f172a;margin-bottom:12px}}
p{{color:#475569;font-size:1rem;line-height:1.6;margin-bottom:8px}}
.btn{{display:inline-flex;align-items:center;gap:8px;padding:14px 28px;background:#2563eb;color:#fff;border:none;border-radius:50px;font-weight:700;font-size:1rem;text-decoration:none;cursor:pointer;margin-top:16px}}
</style>
</head>
<body>
<div class="card">
<div class="icon">!</div>
<h1>Activation Issue</h1>
<p>{message}</p>
{form_html}
<div style="margin-top:24px;font-size:.8rem;color:#94a3b8;">
Need help? Contact <a href="mailto:emltechstudio@gmail.com" style="color:#2563eb;">emltechstudio@gmail.com</a>
</div>
</div>
</body>
</html>"""


@router.get("/plans")
def get_plans():
   return {
       "success": True,
       "plans": {
           "free": {**PLANS["free"], "payment_link": None},
           "pro": {**PLANS["pro"], "payment_link": SELAR_PRO_MANUAL},
           "premium": {**PLANS["premium"], "payment_link": SELAR_PREMIUM_MANUAL}
       }
   }


@router.post("/create-intent")
def create_intent(request: Request, email: str = Header(...), password: str = Header(...)):
   user = get_user_by_email(email.lower().strip())
   if not user or not verify_password(password, user.get("password_hash", "")):
       raise HTTPException(status_code=401, detail="Invalid credentials")
   params = dict(request.query_params)
   plan = params.get("plan")
   if not plan or plan not in ["pro", "premium"]:
       raise HTTPException(status_code=400, detail="Valid plan (pro/premium) required")
   create_payment_intent(email, plan)
   return {"success": True, "message": "Intent created. You may now proceed to payment."}


@router.get("/activate/{plan}", response_class=HTMLResponse)
def activate_plan(request: Request, plan: str):
   if not is_allowed_referer(request):
       return HTMLResponse("<h1>403 Forbidden</h1><p>Invalid request source.</p>", status_code=403)
   if plan not in ["pro", "premium"]:
       return HTMLResponse(error_page(f"Invalid plan '{plan}'. Choose pro or premium."))

   params = dict(request.query_params)
   email = params.get("email", "").lower().strip()
   if not email:
       return HTMLResponse(error_page(
           "We couldn't find your email. Please enter the email you used to register your shop.",
           show_form=True
       ))

   shop = get_shop_meta_by_email(email)
   if not shop:
       return HTMLResponse(error_page(
           f"No shop found for <strong>{email}</strong>. Make sure you entered the same email you used when creating your shop.",
           show_form=True
       ))

   intent = get_valid_intent(email, plan)
   if not intent:
       return HTMLResponse(error_page(
           "This activation link is not valid or has expired. Please initiate the upgrade from your dashboard (the link expires after 1 hour)."
       ))

   expires_at = (datetime.now(timezone.utc) + timedelta(days=31)).isoformat()
   update_shop_meta(email, {
       "plan": plan,
       "sub_type": "manual",
       "status": "active",
       "expires_at": expires_at
   })
   mark_intent_used(email, plan)
   return HTMLResponse(success_page(shop, plan, expires_at))


@router.post("/admin/upgrade")
def admin_upgrade(
   identifier: str,
   plan: str,
   days: int = 31,
   x_admin_key: str = Header(...)
):
   ADMIN_KEY = os.getenv("ADMIN_KEY", "myshub-admin-2026")
   if x_admin_key != ADMIN_KEY:
       raise HTTPException(status_code=403, detail="Invalid admin key.")
   if plan not in ["free", "pro", "premium"]:
       raise HTTPException(status_code=400, detail="Invalid plan. Must be free, pro, or premium.")

   shop = get_shop_meta_by_email(identifier.lower().strip())
   if not shop:
       shop = get_shop_meta_by_slug(identifier.lower().strip())
   if not shop:
       raise HTTPException(status_code=404, detail="Shop not found by email or slug.")

   email = shop["email"]
   if plan == "free":
       update_shop_meta(email, {
           "plan": "free",
           "sub_type": "",
           "status": "active",
           "expires_at": None
       })
       return {"success": True, "message": f"Downgraded {email} to Free."}
   else:
       expires_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
       update_shop_meta(email, {
           "plan": plan,
           "sub_type": "admin",
           "status": "active",
           "expires_at": expires_at
       })
       return {
           "success": True,
           "message": f"Upgraded {email} to {plan.upper()} for {days} days.",
           "expires_at": expires_at
       }


@router.post("/activate/manual")
def activate_manual(request: Request):
   params = dict(request.query_params)
   email = params.get("email", "").lower().strip()
   plan = params.get("plan", "").lower().strip()
   if not email or not plan:
       return {"success": False, "message": "Missing email or plan."}
   if plan not in ["pro", "premium"]:
       return {"success": False, "message": "Invalid plan."}
   shop = get_shop_meta_by_email(email)
   if not shop:
       return {"success": False, "message": "No shop found."}
   expires_at = (datetime.now(timezone.utc) + timedelta(days=31)).isoformat()
   update_shop_meta(email, {
       "plan": plan,
       "sub_type": "manual",
       "status": "active",
       "expires_at": expires_at
   })
   return {
       "success": True,
       "message": f"Upgraded to {plan.upper()}!",
       "plan": plan,
       "expires_at": expires_at,
       "slug": shop["slug"]
   }


@router.post("/expire-check")
def check_expiry(x_admin_key: str = Header(...)):
   ADMIN_KEY = os.getenv("ADMIN_KEY", "myshub-admin-2026")
   if x_admin_key != ADMIN_KEY:
       raise HTTPException(status_code=403, detail="Invalid admin key.")
   
   all_shops = get_all_shops_meta()
   now = datetime.now(timezone.utc)
   expired_count = 0
   
   for shop in all_shops:
       if shop.get("plan") == "free":
           continue
       expires_at = shop.get("expires_at")
       if not expires_at:
           continue
       try:
           expiry = datetime.fromisoformat(expires_at)
           if expiry < now:
               update_shop_meta(shop["email"], {
                   "plan": "free",
                   "sub_type": "",
                   "expires_at": None
               })
               expired_count += 1
       except:
           continue
   
   return {
       "success": True,
       "expired_downgraded": expired_count,
       "message": f"{expired_count} expired shops downgraded to Free."
   }

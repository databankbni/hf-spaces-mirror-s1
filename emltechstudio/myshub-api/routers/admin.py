from fastapi import APIRouter, HTTPException, Header, Depends
from datetime import datetime, timedelta, timezone
import os
import hashlib
import secrets
import math
from typing import Optional

import jwt
if not hasattr(jwt, 'encode'):
    raise ImportError("Wrong 'jwt' package installed. Run: pip uninstall jwt && pip install PyJWT>=2.8.0")

from utils.db import (
    get_shop_by_slug,
    update_shop,
    get_shop_by_email,
    get_admin,
    create_admin,
    update_admin,
    delete_admin,
    list_admins,
    create_staff_key,
    use_staff_key,
    list_staff_keys,
    flush_all,
    get_shop_index,
    get_user_by_email,
    get_feedback,
    delete_feedback,
    create_notification,       # NEW for broadcast
    get_notifications,         # NEW for listing
    _ensure_private_loaded,    # for push
    _users,                    # for push
)
from routers.notifications import check_milestones, check_expiry_warning
from routers.analytics import get_platform_analytics, get_discover_analytics

router = APIRouter()

ADMIN_KEY = os.getenv("ADMIN_KEY", "myshub-admin-2026")
JWT_SECRET = os.getenv("JWT_SECRET", "your-strong-jwt-secret-change-me")
JWT_ALGORITHM = "HS256"

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password: str, hashed: str) -> bool:
    return hash_password(password) == hashed

def create_jwt(email: str, role: str) -> str:
    return jwt.encode(
        {
            "sub": email,
            "role": role,
            "exp": datetime.now(timezone.utc) + timedelta(hours=8),
            "iat": datetime.now(timezone.utc)
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM
    )

def decode_jwt(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=403, detail="Invalid token")

async def get_current_admin(authorization: str = Header(...)) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=403, detail="Invalid authorization header")
    token = authorization[7:]
    payload = decode_jwt(token)
    email = payload.get("sub")
    role = payload.get("role")
    if not email:
        raise HTTPException(status_code=403, detail="Invalid token")
    admin = get_admin(email)
    if not admin or not admin.get("active", True):
        raise HTTPException(status_code=403, detail="Admin not found or inactive")
    return {"email": email, "role": role, "admin": admin}

def require_role(required_role: str):
    async def dependency(current=Depends(get_current_admin)):
        role_priority = {"viewer": 1, "editor": 2, "admin": 3, "super": 4}
        if role_priority.get(current["role"], 0) < role_priority.get(required_role, 0):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current
    return dependency

# ─── Public endpoints ────────────────────────────────────────────────────────
@router.post("/login")
async def admin_login(credentials: dict):
    email = credentials.get("email", "").lower().strip()
    password = credentials.get("password", "")
    admin_key = credentials.get("admin_key")

    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password required")

    if admin_key is not None:
        if admin_key == ADMIN_KEY:
            existing = get_admin(email)
            if existing:
                if not verify_password(password, existing["password"]):
                    raise HTTPException(status_code=401, detail="Invalid credentials")
                if not existing.get("active", True):
                    raise HTTPException(status_code=403, detail="Account disabled")
                token = create_jwt(email, existing["role"])
                return {"token": token, "role": existing["role"], "email": email}
            else:
                ok = create_admin(email, hash_password(password), "super", created_by="system")
                if not ok:
                    raise HTTPException(status_code=409, detail="Admin already exists")
                token = create_jwt(email, "super")
                return {"token": token, "role": "super", "email": email}
        else:
            raise HTTPException(status_code=401, detail="Invalid admin_key")

    admin = get_admin(email)
    if not admin or not verify_password(password, admin["password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not admin.get("active", True):
        raise HTTPException(status_code=403, detail="Account disabled")
    token = create_jwt(email, admin["role"])
    return {"token": token, "role": admin["role"], "email": email}

@router.post("/register")
async def admin_register(data: dict):
    email = data.get("email", "").lower().strip()
    password = data.get("password")
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password required")

    admin_key = data.get("admin_key")
    if admin_key is not None:
        if admin_key == ADMIN_KEY:
            if get_admin(email):
                raise HTTPException(status_code=400, detail="Email already registered")
            ok = create_admin(email, hash_password(password), "super", created_by="system")
            if not ok:
                raise HTTPException(status_code=409, detail="Admin creation failed")
            token = create_jwt(email, "super")
            return {
                "success": True,
                "message": "Super admin account created.",
                "token": token,
                "role": "super",
                "email": email
            }
        else:
            raise HTTPException(status_code=401, detail="Invalid admin_key")

    key = data.get("key")
    if not key:
        raise HTTPException(status_code=400, detail="Missing key (staff key or admin_key required)")

    key_data = use_staff_key(key)
    if not key_data:
        raise HTTPException(status_code=400, detail="Invalid or already used staff key")

    role = key_data["role"]
    if get_admin(email):
        raise HTTPException(status_code=400, detail="Email already registered")

    ok = create_admin(email, hash_password(password), role, created_by=key_data["created_by"])
    if not ok:
        raise HTTPException(status_code=409, detail="Admin creation failed")

    token = create_jwt(email, role)
    return {
        "success": True,
        "message": "Admin account created.",
        "token": token,
        "role": role,
        "email": email
    }

# ─── Authenticated endpoints ─────────────────────────────────────────────────
@router.get("/me")
async def get_me(current=Depends(get_current_admin)):
    return {"email": current["email"], "role": current["role"]}

def _parse_shop_json(raw):
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            import json
            return json.loads(raw)
        except Exception:
            try:
                import ast
                return ast.literal_eval(raw)
            except Exception:
                return {}
    return {}

def sanitize_json(obj):
    if isinstance(obj, dict):
        return {k: sanitize_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_json(i) for i in obj]
    elif isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    return obj

@router.get("/analytics")
async def analytics(
    current=Depends(require_role("viewer")),
    period: str = "30d"
):
    """Admin-only platform analytics from the central module.

    The central response is augmented with the legacy admin fields so the
    existing admin dashboard remains compatible during the migration.
    """
    platform = get_platform_analytics(period)
    platform["discover"] = get_discover_analytics(period)
    visitor_countries = platform.get("countries", {})

    all_shops = list(get_shop_index().values())
    plan_breakdown = {
        plan: sum(1 for shop in all_shops if shop.get("plan", "free") == plan)
        for plan in ("free", "pro", "premium")
    }
    status_breakdown = {
        status: sum(1 for shop in all_shops if shop.get("status", "active") == status)
        for status in ("active", "expired", "flagged", "pending")
    }
    shop_countries = {}
    daily_signups = {}
    for shop in all_shops:
        country = shop.get("country", "Unknown") or "Unknown"
        shop_countries[country] = shop_countries.get(country, 0) + 1
        signup_day = str(shop.get("created_at", ""))[:10]
        if signup_day:
            daily_signups[signup_day] = daily_signups.get(signup_day, 0) + 1

    daily_rows = platform.get("daily", [])
    daily_visits = {
        str(row.get("date")): int(row.get("page_views", 0) or 0)
        for row in daily_rows if row.get("date")
    }
    weekly_visits = {}
    monthly_visits = {}
    yearly_visits = {}
    for day_key, count in daily_visits.items():
        try:
            parsed = datetime.strptime(day_key, "%Y-%m-%d")
            iso_year, iso_week, _ = parsed.isocalendar()
            week_key = f"{iso_year}-W{iso_week:02d}"
            weekly_visits[week_key] = weekly_visits.get(week_key, 0) + count
        except Exception:
            pass
        monthly_visits[day_key[:7]] = monthly_visits.get(day_key[:7], 0) + count
        yearly_visits[day_key[:4]] = yearly_visits.get(day_key[:4], 0) + count

    top_shops_by_visits = sorted(
        [shop for shop in all_shops if int(shop.get("visit_count", 0) or 0) > 0],
        key=lambda shop: int(shop.get("visit_count", 0) or 0),
        reverse=True,
    )[:10]
    referral_code_to_shop = {
        str(shop.get("referral_code")).strip().upper(): shop
        for shop in all_shops if shop.get("referral_code")
    }
    referral_counts = {}
    for shop in all_shops:
        referred_by = str(shop.get("referred_by", "")).strip().upper()
        if referred_by:
            referral_counts[referred_by] = referral_counts.get(referred_by, 0) + 1
    top_shops_by_referrals = []
    for code, count in sorted(referral_counts.items(), key=lambda item: item[1], reverse=True)[:10]:
        referred_shop = referral_code_to_shop.get(code)
        if referred_shop:
            top_shops_by_referrals.append({
                "slug": referred_shop.get("slug", ""),
                "email": referred_shop.get("email", ""),
                "referral_code": code,
                "referrals": count,
            })

    platform.update({
        "total_shops": len(all_shops),
        "total_visits": sum(int(shop.get("visit_count", 0) or 0) for shop in all_shops),
        "plan_breakdown": plan_breakdown,
        "status_breakdown": status_breakdown,
        "countries": shop_countries,
        "directory_countries": shop_countries,
        "visitor_countries": visitor_countries,
        "daily_signups": daily_signups,
        "daily_visits": daily_visits,
        "weekly_visits": weekly_visits,
        "monthly_visits": monthly_visits,
        "yearly_visits": yearly_visits,
        "top_shops_by_visits": [
            {"slug": shop.get("slug", ""), "visits": int(shop.get("visit_count", 0) or 0), "plan": shop.get("plan", "free")}
            for shop in top_shops_by_visits
        ],
        "top_shops_by_referrals": top_shops_by_referrals,
        "estimated_monthly_revenue_ngn": (plan_breakdown["pro"] * 1500) + (plan_breakdown["premium"] * 3500),
        "referral_stats": {
            "total_referral_codes": len(referral_code_to_shop),
            "total_referred": sum(referral_counts.values()),
        },
    })
    return sanitize_json(platform)

@router.get("/shops")
async def list_shops(
    search: Optional[str] = None,
    plan: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
    current=Depends(require_role("viewer"))
):
    index = get_shop_index()
    all_shops = list(index.values())
    filtered = []

    for s in all_shops:
        if search:
            search_lower = search.lower()
            if search_lower not in s.get("business_name", "").lower() and search_lower not in s.get("slug", "").lower():
                continue
        if plan and s.get("plan") != plan:
            continue
        if status and s.get("status") != status:
            continue
        filtered.append(s)

    start = (page - 1) * limit
    end = start + limit
    total = len(filtered)
    shops = filtered[start:end]

    return {"total": total, "page": page, "limit": limit, "shops": shops}

@router.get("/shop/{slug_or_email}")
async def get_shop_details(slug_or_email: str, current=Depends(require_role("viewer"))):
    shop = get_shop_by_email(slug_or_email.lower())
    if not shop:
        shop = get_shop_by_slug(slug_or_email.lower())
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    shop_json = _parse_shop_json(shop.get("shop_json", {}))
    shop["shop_json"] = shop_json
    return sanitize_json(shop)

@router.post("/shop/{slug_or_email}/upgrade")
async def upgrade_shop(
    slug_or_email: str,
    data: dict,
    current=Depends(require_role("editor"))
):
    plan = data.get("plan")
    days = data.get("days", 31)

    if plan not in ["free", "pro", "premium"]:
        raise HTTPException(status_code=400, detail="Invalid plan")

    shop = get_shop_by_email(slug_or_email.lower())
    if not shop:
        shop = get_shop_by_slug(slug_or_email.lower())
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    slug = shop["slug"]

    if plan == "free":
        update_shop(slug, {"plan": "free", "sub_type": "", "expires_at": None})
    else:
        expires_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
        update_shop(slug, {"plan": plan, "sub_type": "admin", "expires_at": expires_at, "status": "active"})

    return {"success": True, "message": f"Shop upgraded to {plan.upper()}"}

@router.post("/shop/{slug_or_email}/status")
async def set_shop_status(
    slug_or_email: str,
    data: dict,
    current=Depends(require_role("editor"))
):
    status = data.get("status")
    if status not in ["active", "expired", "flagged"]:
        raise HTTPException(status_code=400, detail="Invalid status")

    shop = get_shop_by_email(slug_or_email.lower())
    if not shop:
        shop = get_shop_by_slug(slug_or_email.lower())
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    update_shop(shop["slug"], {"status": status})
    return {"success": True, "message": f"Shop status set to {status}"}

@router.post("/shop/{slug_or_email}/reset-password")
async def reset_shop_password(slug_or_email: str, current=Depends(require_role("editor"))):
    shop = get_shop_by_email(slug_or_email.lower())
    if not shop:
        shop = get_shop_by_slug(slug_or_email.lower())
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    reset_token = secrets.token_urlsafe(32)
    reset_link = f"https://myshub.site/reset-password?token={reset_token}&email={shop['email']}"
    return {"success": True, "reset_link": reset_link}

# ─── Admin management (super only) ───────────────────────────────────────────
@router.get("/admins")
async def list_all_admins(current=Depends(require_role("super"))):
    admins = list_admins()
    for a in admins:
        a.pop("password", None)
    return {"admins": admins}

@router.post("/admins")
async def create_new_admin(data: dict, current=Depends(require_role("super"))):
    email = data.get("email", "").lower().strip()
    password = data.get("password")
    role = data.get("role", "viewer")

    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password required")
    if role not in ["viewer", "editor", "admin"]:
        raise HTTPException(status_code=400, detail="Invalid role")
    if get_admin(email):
        raise HTTPException(status_code=400, detail="Admin already exists")

    ok = create_admin(email, hash_password(password), role, created_by=current["email"])
    if not ok:
        raise HTTPException(status_code=409, detail="Admin creation failed")
    return {"success": True, "message": f"Admin {email} created with role {role}"}

@router.delete("/admins/{email}")
async def delete_admin_account(email: str, current=Depends(require_role("super"))):
    email_lower = email.lower().strip()
    if email_lower == current["email"]:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    if not delete_admin(email_lower):
        raise HTTPException(status_code=404, detail="Admin not found")
    return {"success": True, "message": f"Admin {email} deleted"}

@router.get("/staff-keys")
async def get_staff_keys(current=Depends(require_role("super"))):
    keys = list_staff_keys()
    return {"staff_keys": keys}

@router.post("/staff-keys")
async def generate_staff_key(data: dict, current=Depends(require_role("super"))):
    role = data.get("role", "viewer")
    if role not in ["viewer", "editor"]:
        raise HTTPException(status_code=400, detail="Role must be viewer or editor")
    key = create_staff_key(current["email"], role)
    return {"success": True, "key": key, "role": role}

# ─── Referral payouts ───────────────────────────────────────────────────────
@router.get("/referral-payouts")
async def referral_payouts(current=Depends(require_role("viewer"))):
    index = get_shop_index()
    all_shops = list(index.values())
    payouts = []

    for shop_meta in all_shops:
        code = shop_meta.get("referral_code", "")
        if not code:
            continue
        code_str = str(code).strip().upper()
        referred = []
        for s in all_shops:
            referred_by_raw = s.get("referred_by", "")
            referred_by_str = str(referred_by_raw).strip().upper()
            if referred_by_str == code_str:
                referred.append(s)
        active_referred = [s for s in referred if s.get("status") == "active"]
        if referred:
            payouts.append(sanitize_json({
                "email": shop_meta.get("email", ""),
                "referral_code": code_str,
                "total_referred": len(referred),
                "active_referred": len(active_referred),
                "commission_due": len(active_referred) * 450
            }))

    return sanitize_json({
        "success": True,
        "total_payouts": len(payouts),
        "total_commission": sum(p["commission_due"] for p in payouts),
        "payouts": payouts
    })

# ─── Feedback ─────────────────────────────────────────────────────────────
@router.get("/feedback")
async def list_feedback(current=Depends(require_role("viewer"))):
    all_feedback = get_feedback()
    all_feedback.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {"total": len(all_feedback), "feedback": all_feedback}

@router.delete("/feedback/{feedback_id}")
async def remove_feedback(feedback_id: str, current=Depends(require_role("editor"))):
    success = delete_feedback(feedback_id)
    if not success:
        raise HTTPException(status_code=404, detail="Feedback not found")
    return {"success": True, "message": "Feedback deleted."}

# ─── Notifications (NEW) ───────────────────────────────────────────────────
@router.post("/notifications/broadcast")
async def broadcast_notification(
    data: dict,
    current=Depends(require_role("editor"))
):
    title = data.get("title")
    message = data.get("message")
    target = data.get("target", "ALL")  # "ALL" or specific email

    if not title or not message:
        raise HTTPException(status_code=400, detail="Title and message required")

    notification = {
        "email": target,
        "type": "broadcast",
        "title": title,
        "message": message,
        "read": False,
        "data": {},
    }

    created = create_notification(notification)

    # Optionally send web push if VAPID is configured
    try:
        from routers.notifications import _send_push_broadcast, _send_push_to_user
        if target == "ALL":
            _send_push_broadcast(title, message)
        else:
            user = get_user_by_email(target)
            if user and user.get("push_subscription"):
                _send_push_to_user(user["push_subscription"], title, message)
    except Exception as e:
        print(f"Push error (non-fatal): {e}")

    return {"success": True, "notification_id": created["id"]}

@router.get("/notifications")
async def list_recent_notifications(current=Depends(require_role("viewer"))):
    # Return most recent 20 notifications (all users)
    _ensure_private_loaded()
    all_notifs = get_notifications("ALL")  # get all + ALL
    all_notifs.extend(get_notifications(current["email"]))  # include admin's own
    # deduplicate by id
    seen = set()
    unique = []
    for n in all_notifs:
        if n["id"] not in seen:
            seen.add(n["id"])
            unique.append(n)
    unique.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {"notifications": unique[:20]}
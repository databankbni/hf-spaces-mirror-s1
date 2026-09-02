from fastapi import APIRouter, HTTPException, Header, UploadFile, File, Request, Query
from pydantic import BaseModel
from datetime import datetime, timezone
from typing import List, Optional
import ast
import aiohttp
import os
import math
import requests
import json
import re

from utils.db import (
    get_shop_by_slug, update_shop, get_user_by_email, update_user,
    get_shop_index, update_index
)
from utils.security import verify_password
from routers.analytics import record_shop_view, record_shop_clicks, get_shop_analytics, period_allowed_for_plan

IMGBB_KEY = os.getenv("IMGBB_KEY")

router = APIRouter()

class EditShopRequest(BaseModel):
    email: str
    password: str
    new_email: Optional[str] = None
    business_name: Optional[str] = None
    tagline: Optional[str] = None
    description: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    category: Optional[str] = None
    logo_url: Optional[str] = None
    catalog_url: Optional[str] = None

    socials: Optional[dict] = None
    custom_links: Optional[list] = None
    brand_primary: Optional[str] = None
    brand_secondary: Optional[str] = None
    gradient: Optional[bool] = None
    gradient_colors: Optional[list] = None
    heading_font: Optional[str] = None
    body_font: Optional[str] = None
    # NEW FIELDS
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    qr_code_url: Optional[str] = None
    country: Optional[str] = None


class ClickItem(BaseModel):
    type: str
    detail: str
    count: int = 1

class ClickBatch(BaseModel):
    clicks: List[ClickItem]

def parse_shop_json(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return ast.literal_eval(raw)
        except Exception:
            try:
                return json.loads(raw)
            except Exception:
                return {}
    return {}

def _ensure_nested_structure(shop_json: dict) -> dict:
    if "contact" not in shop_json and ("phone" in shop_json or "email" in shop_json or "location" in shop_json):
        shop_json["contact"] = {
            "phone": shop_json.get("phone", ""),
            "whatsapp": shop_json.get("whatsapp", ""),
            "email": shop_json.get("email", ""),
            "location": shop_json.get("location", "")
        }
    if "catalog" not in shop_json and "catalog_url" in shop_json:
        shop_json["catalog"] = {
            "url": shop_json.get("catalog_url", "")
        }
    return shop_json

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

def safe_shop_data(shop: dict) -> dict:
    """Return shop data with FLAT shop_json for frontend compatibility."""
    shop_json = parse_shop_json(shop.get("shop_json", "{}"))
    shop_json = _ensure_nested_structure(shop_json)

    contact = shop_json.get("contact", {})
    catalog = shop_json.get("catalog", {})

    flat_shop_json = {
        "business_name": shop_json.get("business_name", ""),
        "tagline": shop_json.get("tagline", ""),
        "description": shop_json.get("description", ""),
        "logo_url": shop_json.get("logo_url", ""),
        "category": shop_json.get("category", ""),
        "state": shop_json.get("state", ""),
        "city": shop_json.get("city", ""),
        "country": shop_json.get("country", "") or shop.get("country", ""),
        "brand_colors": shop_json.get("brand_colors", {}),
        "typography": shop_json.get("typography", {}),
        "socials": shop_json.get("socials", {}),
        "custom_links": shop_json.get("custom_links", []),
        "analytics": shop_json.get("analytics", {}),
        "phone": contact.get("phone", ""),
        "whatsapp": contact.get("whatsapp", ""),
        "email": contact.get("email", ""),
        "location": contact.get("location", ""),
        "catalog_url": catalog.get("url", ""),
        "lat": shop_json.get("lat"),
        "lng": shop_json.get("lng"),
        "qr_code_url": shop_json.get("qr_code_url", ""),
    }

    result = {
        "slug": shop["slug"],
        "plan": shop.get("plan", "free"),
        "status": shop.get("status", "active"),
        "country": shop.get("country", ""),
        "referral_code": shop.get("referral_code", ""),
        "visit_count": shop.get("visit_count", 0),
        "created_at": shop.get("created_at", ""),
        "expires_at": shop.get("expires_at", ""),
        "shop_json": flat_shop_json
    }
    return sanitize_json(result)

PLAN_LIMITS = {
    "free": {"socials": 5, "custom_links": 2, "brand_colors": False, "gradients": False, "fonts": False, "media": False},
    "pro": {"socials": 10, "custom_links": 10, "brand_colors": True, "gradients": False, "fonts": True, "media": True},
    "premium": {"socials": 999, "custom_links": 999, "brand_colors": True, "gradients": True, "fonts": True, "media": True}
}

def enforce_plan(plan: str, current: dict, updates: dict) -> dict:
    """Reject only newly introduced plan violations, not unchanged stored data.

    The edit form submits the current profile so ordinary edits remain complete.
    A downgraded shop may also legitimately contain older data above its new
    limit. That unchanged data must remain editable until the owner changes it.
    """
    limits = PLAN_LIMITS.get(str(plan or "free").lower(), PLAN_LIMITS["free"])
    errors = []
    current_socials = current.get("socials") or {}
    current_links = current.get("custom_links") or []
    current_brand = current.get("brand_colors") or {}
    current_typography = current.get("typography") or {}

    if "socials" in updates and updates["socials"] is not None:
        submitted_socials = updates["socials"]
        if len(submitted_socials) > limits["socials"] and submitted_socials != current_socials:
            errors.append(f"Socials limit: {limits['socials']}")

    if "custom_links" in updates and updates["custom_links"] is not None:
        submitted_links = updates["custom_links"]
        if len(submitted_links) > limits["custom_links"] and submitted_links != current_links:
            errors.append(f"Custom links limit: {limits['custom_links']}")

    if not limits["brand_colors"]:
        brand_changed = (
            (updates.get("brand_primary") is not None and updates.get("brand_primary") != current_brand.get("primary"))
            or (updates.get("brand_secondary") is not None and updates.get("brand_secondary") != current_brand.get("secondary"))
        )
        if brand_changed:
            errors.append("Brand colors are Pro/Premium features.")

    if updates.get("gradient") and not limits["gradients"]:
        errors.append("Gradients are Premium features.")

    if not limits["fonts"]:
        font_changed = (
            (updates.get("heading_font") is not None and updates.get("heading_font") != current_typography.get("heading_font"))
            or (updates.get("body_font") is not None and updates.get("body_font") != current_typography.get("body_font"))
        )
        if font_changed:
            errors.append("Custom fonts are Pro/Premium features.")

    if errors:
        return {"success": False, "message": "Plan limit exceeded.", "errors": errors}
    return None

def _verify_user(email: str, password: str):
    user = get_user_by_email(email.lower().strip())
    if not user:
        raise HTTPException(status_code=404, detail="No account found.")
    if not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect password.")
    return user

# ═══════════════════════════════════════════════════════════════════
# IP & ANALYTICS HELPERS
# ═══════════════════════════════════════════════════════════════════

def get_visitor_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

def get_country_from_ip(ip_address: str) -> str:
    try:
        if ip_address in ("127.0.0.1", "localhost", "::1") or ip_address.startswith(("192.168.", "10.", "172.")):
            return "Local"
        if ip_address == "unknown":
            return "Unknown"
        response = requests.get(
            f"http://ip-api.com/json/{ip_address}?fields=country",
            timeout=3
        )
        data = response.json()
        return data.get("country", "Unknown")
    except Exception:
        return "Unknown"

def log_visit_analytics(shop: dict, request: Request, is_owner_preview: bool = False):
    """Compatibility wrapper; the central implementation lives in analytics.py."""
    try:
        return record_shop_view(shop, request, is_owner_preview=is_owner_preview)
    except Exception:
        # Analytics must never break a public shop request.
        return shop

# ═══════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

@router.post("/upload-logo")
async def upload_logo(
    file: UploadFile = File(...),
    email: str = Header(...),
    password: str = Header(...)
):
    """Upload logo as base64 and store directly in shop_json."""
    user = _verify_user(email, password)

    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image.")

    content = await file.read()
    if len(content) > 2 * 1024 * 1024:  # 2MB max for base64
        raise HTTPException(status_code=400, detail="Logo must be under 2MB.")

    # Convert to base64 data URL
    import base64
    b64 = base64.b64encode(content).decode('utf-8')
    mime_type = file.content_type
    data_url = f"data:{mime_type};base64,{b64}"

    # Find user's shop and update logo
    shop = None
    for slug, meta in get_shop_index().items():
        if meta.get("email") == email.lower().strip():
            shop = get_shop_by_slug(slug)
            break

    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    # Update shop_json with logo
    shop_json = parse_shop_json(shop.get("shop_json", "{}"))
    shop_json["logo_url"] = data_url

    # Instant update to public dataset
    update_shop(shop["slug"], {"shop_json": shop_json})

    return {"success": True, "logo_url": data_url}

@router.post("/upload")
async def upload_image(file: UploadFile = File(...), email: str = Header(...)):
    """Legacy ImgBB upload for other images."""
    if not IMGBB_KEY:
        raise HTTPException(status_code=500, detail="Image upload not configured.")
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image.")
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image must be under 5MB.")

    try:
        async with aiohttp.ClientSession() as session:
            form = aiohttp.FormData()
            form.add_field("image", content, filename=file.filename)
            async with session.post(
                f"https://api.imgbb.com/1/upload?key={IMGBB_KEY}",
                data=form
            ) as resp:
                if resp.status != 200:
                    raise HTTPException(status_code=500, detail="ImgBB upload failed.")
                data = await resp.json()
                if not data.get("success"):
                    raise HTTPException(status_code=400, detail="Upload rejected by ImgBB.")
                return {"success": True, "url": data["data"]["url"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload error: {str(e)}")

@router.get("/live/{slug}")
def get_live_shop(slug: str, request: Request):
    """Public shop page — tracks REAL visitor analytics."""
    shop = get_shop_by_slug(slug.lower().strip())
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found.")

    if shop.get("status") != "active":
        raise HTTPException(status_code=403, detail="This shop is currently deactivated.")

    log_visit_analytics(shop, request, is_owner_preview=False)
    # Reload after analytics persistence so the response contains the latest data.
    refreshed = get_shop_by_slug(slug.lower().strip()) or shop
    return safe_shop_data(refreshed)

@router.get("/preview/{slug}")
def get_preview_shop(
    slug: str,
    email: str = Header(None),
    password: str = Header(None),
    email_q: str = Query(None, alias="email"),
    password_q: str = Query(None, alias="password")
):
    """Owner preview — does NOT count as a visit."""
    email = (email or email_q or "").strip().lower()
    password = password or password_q or ""
    if not email or not password:
        raise HTTPException(status_code=422, detail="Email and password required")
    user = _verify_user(email, password)
    shop = get_shop_by_slug(slug.lower().strip())
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found.")
    if shop["email"] != user["email"]:
        raise HTTPException(status_code=403, detail="You do not own this shop.")
    return safe_shop_data(shop)

@router.get("/analytics/{slug}")
def get_shop_analytics_endpoint(
    slug: str,
    period: str = Query("30d"),
    email: str = Header(None),
    password: str = Header(None),
    email_q: str = Query(None, alias="email"),
    password_q: str = Query(None, alias="password")
):
    """Owner-only, period-aware analytics response from analytics.py."""
    email = (email or email_q or "").strip().lower()
    password = password or password_q or ""
    if not email or not password:
        raise HTTPException(status_code=422, detail="Email and password required")
    user = _verify_user(email, password)
    shop = get_shop_by_slug(slug.lower().strip())
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found.")
    if shop.get("email", "").lower() != user.get("email", "").lower():
        raise HTTPException(status_code=403, detail="You do not own this shop.")
    plan = str(shop.get("plan", "free") or "free").lower()
    if not period_allowed_for_plan(period, plan):
        raise HTTPException(status_code=403, detail="This analytics period is not available on your current plan.")
    analytics = get_shop_analytics(slug, period=period)
    if analytics is None:
        raise HTTPException(status_code=404, detail="Shop analytics not found.")
    return sanitize_json(analytics)

@router.get("/status/{slug}")
def get_shop_status(slug: str):
    shop = get_shop_by_slug(slug.lower().strip())
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found.")
    return sanitize_json({"slug": slug, "plan": shop.get("plan", "free"), "status": shop.get("status", "active"), "expires_at": shop.get("expires_at", "")})

@router.put("/edit/{slug}")
@router.post("/edit/{slug}")
@router.put("/edit")
@router.post("/edit")
def edit_shop(data: EditShopRequest, slug: Optional[str] = None):
    email = data.email.lower().strip()
    user = _verify_user(email, data.password)
    
    if not slug:
        for s, meta in get_shop_index().items():
            if meta.get("email") == email:
                slug = s
                break
    
    if not slug:
        raise HTTPException(status_code=404, detail="Shop not found for this user.")
        
    shop = get_shop_by_slug(slug.lower().strip())
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found.")
    if shop["email"] != email:
        raise HTTPException(status_code=403, detail="You do not own this shop.")

    requested_email = (data.new_email or "").lower().strip()
    email_changed = bool(requested_email and requested_email != email)
    if email_changed:
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", requested_email):
            raise HTTPException(status_code=422, detail="Enter a valid email address.")
        existing_user = get_user_by_email(requested_email)
        if existing_user:
            raise HTTPException(status_code=409, detail="That email is already in use.")

    current = parse_shop_json(shop.get("shop_json", "{}"))
    current = _ensure_nested_structure(current)
    plan = shop.get("plan", "free")

    updates = data.dict(exclude_unset=True)
    enforcement = enforce_plan(plan, current, updates)
    if enforcement:
        return sanitize_json(enforcement)

    if data.business_name is not None: current["business_name"] = data.business_name
    if data.tagline is not None: current["tagline"] = data.tagline
    if data.description is not None: current["description"] = data.description
    if data.category is not None: current["category"] = data.category
    if data.state is not None: current["state"] = data.state
    if data.city is not None: current["city"] = data.city
    if data.country is not None: 
        current["country"] = data.country
        update_shop(slug, {"country": data.country})

    current.setdefault("contact", {})
    if data.phone is not None: current["contact"]["phone"] = data.phone
    if data.location is not None: current["contact"]["location"] = data.location
    if email_changed: current["contact"]["email"] = requested_email

    current.setdefault("catalog", {})
    if data.catalog_url is not None: 
        current["catalog"]["url"] = data.catalog_url
            


    if data.socials is not None: current["socials"] = data.socials
    if data.custom_links is not None: current["custom_links"] = data.custom_links

    current.setdefault("brand_colors", {})
    if data.brand_primary is not None: current["brand_colors"]["primary"] = data.brand_primary
    if data.brand_secondary is not None: current["brand_colors"]["secondary"] = data.brand_secondary
    if data.gradient is not None: current["brand_colors"]["gradient"] = data.gradient
    if data.gradient_colors is not None: current["brand_colors"]["gradient_colors"] = data.gradient_colors

    current.setdefault("typography", {})
    if data.heading_font is not None: current["typography"]["heading_font"] = data.heading_font
    if data.body_font is not None: current["typography"]["body_font"] = data.body_font

    if data.latitude is not None: current["lat"] = data.latitude
    if data.longitude is not None: current["lng"] = data.longitude
    if data.qr_code_url is not None: current["qr_code_url"] = data.qr_code_url

    # Keep the private login record, public owner metadata, shop contact email,
    # and index email coordinated when the authenticated owner changes email.
    if email_changed:
        updated_user = update_user(email, {"email": requested_email})
        if not updated_user:
            raise HTTPException(status_code=500, detail="Could not update the account email.")

    # Instant update to public dataset
    updated_shop = update_shop(slug, {"shop_json": current, **({"email": requested_email} if email_changed else {})})
    if email_changed:
        update_index(slug, {"email": requested_email})

    return sanitize_json({
        "success": True,
        "message": "Shop and account updated successfully." if email_changed else "Shop updated successfully.",
        "shop_json": current,
        "plan": plan,
        "email": requested_email if email_changed else email
    })

@router.post("/click/{slug}")
def log_clicks(slug: str, batch: ClickBatch, request: Request):
    """Compatibility route; click persistence is centralized in analytics.py."""
    shop = get_shop_by_slug(slug.lower().strip())
    if not shop or shop.get("plan") == "free":
        return {"status": "ok"}
    try:
        record_shop_clicks(slug, batch.clicks, request=request)
    except Exception as exc:
        # Click analytics must not break navigation or button actions.
        print(f"[Shop] click analytics error: {exc}")
    return {"status": "ok"}

@router.get("/referrals")
def get_referrals(email: str = Header(...), password: str = Header(...)):
    user = _verify_user(email, password)
    ref = str(user.get("referral_code", "")).strip().upper()

    all_shops = list(get_shop_index().values())
    referred = [s for s in all_shops if str(s.get("referred_by", "")).strip().upper() == ref]
    active_referred = [s for s in referred if s.get("status") == "active"]

    return sanitize_json({
        "referral_code": ref,
        "total_referred": len(referred),
        "active_referred": len(active_referred),
        "estimated_commission": len(active_referred) * 450
    })

@router.post("/{slug}/deactivate")
def deactivate_shop(slug: str, email: str = Header(...), password: str = Header(...)):
    user = _verify_user(email, password)
    shop = get_shop_by_slug(slug.lower().strip())
    if not shop or shop["email"] != user["email"]: raise HTTPException(status_code=403, detail="Unauthorized")
    update_shop(slug, {"status": "expired"})
    return {"success": True, "message": "Your shop has been deactivated."}

@router.post("/{slug}/reactivate")
def reactivate_shop(slug: str, email: str = Header(...), password: str = Header(...)):
    user = _verify_user(email, password)
    shop = get_shop_by_slug(slug.lower().strip())
    if not shop or shop["email"] != user["email"]: raise HTTPException(status_code=403, detail="Unauthorized")
    update_shop(slug, {"status": "active"})
    return {"success": True, "message": "Your shop is live again."}

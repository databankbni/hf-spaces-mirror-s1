"""Auth Router — User registration, login, password recovery"""
import os
import re
import json
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr
from typing import List, Optional
import requests

from utils.security import hash_password, verify_password, generate_referral_code
from utils.db import (
    get_user_by_email, create_user, update_user,
    get_shop_by_slug, create_shop, get_shop_index, add_to_index
)

router = APIRouter()

# ── IP Country Detection ───────────────────────────────────────────
def get_country_from_ip(ip_address: str) -> str:
    """Detect country from IP using free ip-api.com"""
    try:
        if ip_address in ("127.0.0.1", "localhost", "::1") or ip_address.startswith(("192.168.", "10.", "172.")):
            return "Local"
        response = requests.get(
            f"http://ip-api.com/json/{ip_address}?fields=country,countryCode",
            timeout=3
        )
        data = response.json()
        return data.get("country", "")
    except Exception:
        return ""

# ── Slug Helpers ────────────────────────────────────────────────────
SLUG_PATTERN = re.compile(r"^[a-z0-9-]+$")

def is_valid_slug(slug: str) -> bool:
    if not slug or len(slug) < 2 or len(slug) > 50:
        return False
    return bool(SLUG_PATTERN.match(slug))

def generate_slug_suggestions(base: str, count: int = 3) -> list:
    """Generate alternative slug suggestions when preferred is taken."""
    suggestions = []
    base = re.sub(r"[^a-z0-9-]", "-", base.lower().strip()).strip("-")
    if not base:
        base = "shop"

    # Try adding numbers
    for i in range(1, count + 1):
        sug = f"{base}-{i}"
        if not get_shop_by_slug(sug):
            suggestions.append(sug)
        if len(suggestions) >= count:
            break

    # Try adding random suffix
    import secrets
    while len(suggestions) < count:
        suffix = secrets.token_hex(2)
        sug = f"{base}-{suffix}"
        if not get_shop_by_slug(sug):
            suggestions.append(sug)

    return suggestions[:count]

def resolve_slug(business_name: str, preferred_slug: str = "") -> tuple:
    """Returns (slug, was_preferred_used, suggestions_if_taken)"""
    if preferred_slug and is_valid_slug(preferred_slug):
        if not get_shop_by_slug(preferred_slug):
            return preferred_slug, True, []
        # Preferred taken — generate fallback + suggestions
        fallback = re.sub(r"[^a-z0-9-]", "-", business_name.lower().strip()).strip("-")
        code = generate_referral_code()
        fallback = f"{fallback}-{code[-4:].lower()}"
        suggestions = generate_slug_suggestions(preferred_slug)
        return fallback, False, suggestions

    # Auto-generate from business name
    slug = re.sub(r"[^a-z0-9-]", "-", business_name.lower().strip()).strip("-")
    if get_shop_by_slug(slug):
        code = generate_referral_code()
        slug = f"{slug}-{code[-4:].lower()}"
    return slug, False, []

# ── Pydantic Models ─────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    business_name: str
    description: str = ""
    tagline: str = ""
    phone: str = ""
    location: str = ""
    country: str = ""
    state: str = ""
    city: str = ""
    category: str = ""
    catalog_url: str = ""
    referred_by: str = ""
    security_questions: List[dict]
    socials: dict = {}
    # NEW FIELDS
    preferred_slug: str = ""       # User's custom slug choice
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    qr_code_url: str = ""         # Frontend can fill later

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class SecurityQuestionsRequest(BaseModel):
    email: EmailStr

class VerifySecurityAnswerRequest(BaseModel):
    email: EmailStr
    question: str
    answer: str

class ResetRequest(BaseModel):
    email: EmailStr
    security_question: str = ""
    security_answer: str = ""
    new_password: str = ""
    # Fallback aliases for frontend compatibility
    question: str = ""
    answer: str = ""
    password: str = ""

    def model_post_init(self, __context):
        if not self.security_question and self.question:
            self.security_question = self.question
        if not self.security_answer and self.answer:
            self.security_answer = self.answer
        if not self.new_password and self.password:
            self.new_password = self.password

class CheckSlugRequest(BaseModel):
    slug: str

# ── Endpoints ───────────────────────────────────────────────────────
@router.post("/register")
def register(request: Request, data: RegisterRequest):
    existing_user = get_user_by_email(data.email)
    if existing_user:
        raise HTTPException(status_code=409, detail="Email already registered.")

    password_hash = hash_password(data.password)
    referral_code = generate_referral_code()

    # Handle referred_by
    referred_by = data.referred_by.strip()
    if referred_by:
        all_shops = list(get_shop_index().values())
        found = False
        for s in all_shops:
            if s.get("referral_code", "") == referred_by:
                found = True
                break
        if not found:
            referred_by = ""

    # Detect country from IP if not provided
    country = data.country.strip()
    if not country:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
        else:
            ip = request.client.host
        country = get_country_from_ip(ip)

    # Resolve slug (preferred or auto-generated)
    slug, used_preferred, suggestions = resolve_slug(data.business_name, data.preferred_slug)

    # Build shop_json with nested structure
    shop_json = {
        "business_name": data.business_name,
        "tagline": data.tagline,
        "description": data.description,
        "logo_url": "",
        "category": data.category,
        "state": data.state,
        "city": data.city,
        "brand_colors": {
            "primary": "#1e40af",
            "secondary": "#ffffff",
            "gradient": False,
            "gradient_colors": ["#1e40af", "#3b82f6"],
        },
        "typography": {
            "heading_font": "Poppins",
            "body_font": "Open Sans",
        },
        "contact": {
            "phone": data.phone,
            "whatsapp": "",
            "email": data.email,
            "location": data.location,
        },
        "catalog": {
            "url": data.catalog_url
        },
        "socials": data.socials,
        "custom_links": [],
        # NEW: lat/lng/qr
        "lat": data.latitude,
        "lng": data.longitude,
        "qr_code_url": data.qr_code_url,
        "analytics": {
            "visit_count": 0,
            "daily_visits": {},
            "referrers": {},
            "devices": {"mobile": 0, "desktop": 0, "tablet": 0},
            "countries": {},
            "daily_countries": {},
            "clicks": {
                "catalog": 0,
                "whatsapp": 0,
                "socials": {},
                "custom_links": {},
            },
        },
    }

    user_data = {
        "email": data.email,
        "password_hash": password_hash,
        "security_questions": data.security_questions,
        "country": country,
        "referral_code": referral_code,
        "referred_by": referred_by,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "push_subscription": None,
    }
    create_user(user_data)

    shop_data = {
        "email": data.email,
        "slug": slug,
        "plan": "free",
        "status": "active",
        "country": country,
        "referral_code": referral_code,
        "referred_by": referred_by,
        "expires_at": "",
        "shop_json": shop_json,
    }
    create_shop(shop_data)

    return {
        "message": "User registered successfully.",
        "referral_code": referral_code,
        "slug": slug,
        "preferred_slug_used": used_preferred,
        "slug_suggestions": suggestions if not used_preferred and data.preferred_slug else [],
    }

@router.post("/login")
def login(data: LoginRequest):
    user = get_user_by_email(data.email)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    if not verify_password(data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    # Get shop from index
    shop = None
    for s in get_shop_index().values():
        if s.get("email") == data.email.lower().strip():
            shop = s
            break

    return {
        "message": "Login successful.",
        "email": user["email"],
        "slug": shop.get("slug", "") if shop else "",
        "plan": shop.get("plan", "") if shop else "",
        "status": shop.get("status", "") if shop else "",
    }

@router.get("/security-questions")
def get_security_questions(email: str):
    user = get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    questions = user.get("security_questions", [])
    return {"questions": [q.get("question", "") for q in questions]}

@router.post("/verify-security-answer")
def verify_security_answer(data: VerifySecurityAnswerRequest):
    user = get_user_by_email(data.email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    questions = user.get("security_questions", [])
    for q in questions:
        if q.get("question") == data.question and q.get("answer") == data.answer:
            return {"verified": True}
    raise HTTPException(status_code=401, detail="Incorrect answer.")

@router.post("/reset-password")
def reset_password(data: ResetRequest):
    user = get_user_by_email(data.email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if not data.security_question or not data.security_answer:
        raise HTTPException(status_code=422, detail="Security question and answer required.")
    if not data.new_password:
        raise HTTPException(status_code=422, detail="New password required.")
    questions = user.get("security_questions", [])
    matched = False
    for q in questions:
        if q.get("question") == data.security_question and q.get("answer") == data.security_answer:
            matched = True
            break
    if not matched:
        raise HTTPException(status_code=401, detail="Incorrect security answer.")
    update_user(data.email, {"password_hash": hash_password(data.new_password)})
    return {"message": "Password reset successful."}

# ── NEW: Check Slug Availability ──────────────────────────────────────
@router.get("/check-slug")
def check_slug(slug: str):
    """Check if a slug is available. Returns suggestions if taken."""
    slug = slug.lower().strip()
    if not is_valid_slug(slug):
        raise HTTPException(status_code=400, detail="Invalid slug. Use only lowercase letters, numbers, and hyphens (2-50 chars).")

    existing = get_shop_by_slug(slug)
    if existing:
        suggestions = generate_slug_suggestions(slug)
        return {
            "available": False,
            "message": f"Slug '{slug}' is already taken.",
            "suggestions": suggestions
        }

    return {
        "available": True,
        "message": f"Slug '{slug}' is available.",
        "suggestions": []
    }

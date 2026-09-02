from __future__ import annotations

import json
import math
import re
import unicodedata
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query

from utils.db import get_shop_index

router = APIRouter()

# The ranking order is intentional: paid visibility is respected, while relevance,
# proximity, and activity still influence the result within the plan tier.
PLAN_RANK = {"premium": 3, "pro": 2, "free": 1}
PLAN_LABELS = {"premium": "Premium", "pro": "Pro", "free": "Free"}

STOP_WORDS = {
    "a", "an", "and", "at", "for", "from", "in", "near", "of", "on", "the",
    "to", "around", "with", "me", "shop", "shops", "business", "businesses",
    "find", "show", "looking", "search", "please", "want", "where", "is",
}

# Common language variations are normalized to the category values stored by shops.
CATEGORY_ALIASES = {
    "churches": "church",
    "church": "church",
    "ministries": "ministry",
    "ministry": "ministry",
    "makeup": "makeup",
    "cosmetics": "beauty",
    "beauty products": "beauty",
    "hair": "haircare",
    "hairs": "haircare",
    "barbers": "barber",
    "barbering": "barber",
    "restaurants": "food",
    "restaurant": "food",
    "foods": "food",
    "fashion stores": "fashion",
    "fashion store": "fashion",
    "tech companies": "tech",
    "technology": "tech",
    "real estate": "real estate",
    "real estates": "real estate",
}


def normalize_text(value: Any) -> str:
    """Return a comparison-friendly representation of a value."""
    if value is None:
        return ""
    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    value = value.casefold().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def singularize(value: str) -> str:
    value = normalize_text(value)
    if value.endswith("ies") and len(value) > 4:
        return value[:-3] + "y"
    if value.endswith("ches") and len(value) > 5:
        return value[:-2]
    if value.endswith("ses") and len(value) > 4:
        return value[:-2]
    if value.endswith("s") and not value.endswith("ss") and len(value) > 3:
        return value[:-1]
    return value


def canonical_category(value: Any) -> str:
    normalized = normalize_text(value)
    if normalized in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[normalized]
    return singularize(normalized)


def parse_json_object(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def first_value(*values: Any, default: Any = "") -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return default


def _nested_shop_json(meta: Dict[str, Any]) -> Dict[str, Any]:
    nested = parse_json_object(meta.get("shop_json"))
    if not nested and isinstance(meta.get("data"), dict):
        nested = meta["data"]
    return nested


def normalize_shop(slug: str, raw_meta: Any) -> Dict[str, Any]:
    """Normalize both the current index shape and older nested shop records."""
    meta = raw_meta if isinstance(raw_meta, dict) else {}
    nested = _nested_shop_json(meta)
    contact = nested.get("contact") if isinstance(nested.get("contact"), dict) else {}
    typography = nested.get("typography") if isinstance(nested.get("typography"), dict) else {}
    analytics = nested.get("analytics") if isinstance(nested.get("analytics"), dict) else {}

    plan = normalize_text(first_value(meta.get("plan"), nested.get("plan"), default="free"))
    if plan not in PLAN_RANK:
        plan = "free"

    category = first_value(meta.get("category"), nested.get("category"), default="")
    country = first_value(meta.get("country"), nested.get("country"), default="")
    state = first_value(meta.get("state"), nested.get("state"), default="")
    city = first_value(meta.get("city"), nested.get("city"), default="")
    latitude = first_value(meta.get("lat"), meta.get("latitude"), nested.get("lat"), nested.get("latitude"))
    longitude = first_value(meta.get("lng"), meta.get("longitude"), nested.get("lng"), nested.get("longitude"))

    try:
        latitude = float(latitude) if latitude not in (None, "") else None
    except (TypeError, ValueError):
        latitude = None
    try:
        longitude = float(longitude) if longitude not in (None, "") else None
    except (TypeError, ValueError):
        longitude = None

    visit_count = first_value(
        meta.get("visit_count"), meta.get("views"), analytics.get("visit_count"), analytics.get("views"), default=0
    )
    try:
        visit_count = max(0, int(visit_count or 0))
    except (TypeError, ValueError):
        visit_count = 0

    click_count = first_value(
        meta.get("click_count"), analytics.get("click_count"), analytics.get("total_clicks"), default=0
    )
    try:
        click_count = max(0, int(click_count or 0))
    except (TypeError, ValueError):
        click_count = 0

    created_at = first_value(meta.get("created_at"), nested.get("created_at"), default="")
    return {
        "slug": str(slug).strip().lower(),
        "status": normalize_text(first_value(meta.get("status"), nested.get("status"), default="active")),
        "plan": plan,
        "business_name": str(first_value(meta.get("business_name"), nested.get("business_name"), default=slug)).strip(),
        "tagline": str(first_value(meta.get("tagline"), nested.get("tagline"), default="")).strip(),
        "description": str(first_value(meta.get("description"), nested.get("description"), default="")).strip(),
        "category": str(category).strip(),
        "category_key": canonical_category(category),
        "country": str(country).strip(),
        "state": str(state).strip(),
        "city": str(city).strip(),
        "location": str(first_value(meta.get("location"), contact.get("location"), nested.get("location"), default="")).strip(),
        "lat": latitude,
        "lng": longitude,
        "logo_url": str(first_value(meta.get("logo_url"), nested.get("logo_url"), default="")).strip(),
        "visit_count": visit_count,
        "click_count": click_count,
        "created_at": created_at,
        "body_font": typography.get("body_font", ""),
    }


def active_shops() -> List[Dict[str, Any]]:
    index = get_shop_index() or {}
    shops: List[Dict[str, Any]] = []
    for slug, raw_meta in index.items():
        shop = normalize_shop(str(slug), raw_meta)
        if shop["status"] == "active":
            shops.append(shop)
    return shops


def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate the great-circle distance between two coordinates in kilometres."""
    radius = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    a = min(1.0, max(0.0, a))
    return radius * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def _known_values(shops: Iterable[Dict[str, Any]]) -> Dict[str, List[str]]:
    shops = list(shops)
    return {
        "countries": sorted({s["country"] for s in shops if s["country"]}, key=normalize_text),
        "states": sorted({s["state"] for s in shops if s["state"]}, key=normalize_text),
        "cities": sorted({s["city"] for s in shops if s["city"]}, key=normalize_text),
        "categories": sorted({s["category"] for s in shops if s["category"]}, key=normalize_text),
    }


def _find_known_location(text: str, values: List[str]) -> Optional[str]:
    text_key = normalize_text(text)
    candidates = sorted(values, key=lambda v: len(normalize_text(v)), reverse=True)
    for value in candidates:
        value_key = normalize_text(value)
        if value_key and re.search(rf"\b{re.escape(value_key)}\b", text_key):
            return value
    return None


def parse_search_intent(query: Optional[str], shops: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Interpret common human search phrases without depending on exact wording."""
    raw = (query or "").strip()
    text = normalize_text(raw)
    known = _known_values(shops)
    near_me = bool(re.search(r"\bnear me\b|\baround me\b|\bclose to me\b", text))

    detected_country = _find_known_location(text, known["countries"])
    detected_state = _find_known_location(text, known["states"])
    detected_city = _find_known_location(text, known["cities"])

    detected_category = None
    category_candidates: List[Tuple[int, str, str]] = []
    for category in known["categories"]:
        category_key = canonical_category(category)
        if not category_key:
            continue
        category_candidates.append((len(category_key.split()), category, category_key))
    for alias, canonical in CATEGORY_ALIASES.items():
        category_candidates.append((len(alias.split()), alias, canonical))
    for _, phrase, canonical in sorted(category_candidates, reverse=True):
        if re.search(rf"\b{re.escape(normalize_text(phrase))}\b", text):
            detected_category = canonical
            break

    location_tokens = [normalize_text(x) for x in (detected_country, detected_state, detected_city) if x]
    category_tokens = set(normalize_text(detected_category or "").split())
    remaining = text
    for token in location_tokens:
        remaining = re.sub(rf"\b{re.escape(token)}\b", " ", remaining)
    if detected_category:
        for phrase, canonical in CATEGORY_ALIASES.items():
            if canonical == detected_category:
                remaining = re.sub(rf"\b{re.escape(normalize_text(phrase))}\b", " ", remaining)
        remaining = re.sub(rf"\b{re.escape(normalize_text(detected_category))}\b", " ", remaining)
    remaining = re.sub(r"\bnear me\b|\baround me\b|\bclose to me\b", " ", remaining)
    terms = [t for t in normalize_text(remaining).split() if t not in STOP_WORDS and t not in category_tokens]

    return {
        "raw": raw,
        "near_me": near_me,
        "category": detected_category,
        "country": detected_country,
        "state": detected_state,
        "city": detected_city,
        "terms": terms,
    }


def _location_matches(shop: Dict[str, Any], country: Optional[str], state: Optional[str], city: Optional[str]) -> bool:
    checks = ((country, "country"), (state, "state"), (city, "city"))
    for requested, field in checks:
        if requested and normalize_text(shop.get(field)) != normalize_text(requested):
            return False
    return True


def _category_matches(shop_category: str, requested: Optional[str]) -> bool:
    return not requested or canonical_category(shop_category) == canonical_category(requested)


def _resolve_legacy_location(location: Optional[str], shops: List[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    if not location:
        return None, None, None
    value = location.strip()
    if value.lower().startswith("country:"):
        return value.split(":", 1)[1].strip(), None, None
    if value.lower().startswith("state:"):
        return None, value.split(":", 1)[1].strip(), None
    if value.lower().startswith("city:"):
        return None, None, value.split(":", 1)[1].strip()
    known = _known_values(shops)
    return (
        _find_known_location(value, known["countries"]),
        _find_known_location(value, known["states"]),
        _find_known_location(value, known["cities"]),
    )


def _activity_score(shop: Dict[str, Any]) -> float:
    return math.log10(shop["visit_count"] + 1) * 6 + math.log10(shop["click_count"] + 1) * 8


def _created_timestamp(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _safe_result(shop: Dict[str, Any], score: float, relevance: float, distance: Optional[float], reasons: List[str]) -> Dict[str, Any]:
    location_parts = [part for part in (shop["city"], shop["state"], shop["country"]) if part]
    member_since = str(shop["created_at"] or "")[:10]
    return {
        "slug": shop["slug"],
        "shop_url": f"https://myshub.site/{shop['slug']}",
        "business_name": shop["business_name"],
        "tagline": shop["tagline"],
        "description": shop["description"],
        "short_description": shop["description"][:220],
        "category": shop["category"],
        "country": shop["country"],
        "state": shop["state"],
        "city": shop["city"],
        "location_label": ", ".join(location_parts),
        "logo_url": shop["logo_url"],
        "plan": shop["plan"],
        "plan_label": PLAN_LABELS[shop["plan"]],
        "visit_count": shop["visit_count"],
        "click_count": shop["click_count"],
        "member_since": member_since,
        "distance": round(distance, 2) if distance is not None else None,
        "distance_label": f"{distance:.1f} km away" if distance is not None else "",
        "relevance": round(relevance, 3),
        "match_reasons": reasons,
        "score": round(score, 3),
    }


def _run_search(
    *,
    q: Optional[str],
    category: Optional[str],
    country: Optional[str],
    state: Optional[str],
    city: Optional[str],
    location: Optional[str],
    plan: Optional[str],
    lat: Optional[float],
    lng: Optional[float],
    radius: float,
    near_me: bool,
    mode: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    # FastAPI resolves Query objects during HTTP requests. Unwrapping their defaults
    # also keeps internal calls and isolated tests deterministic.
    def unwrap(value: Any) -> Any:
        return getattr(value, "default", value)

    q = unwrap(q)
    category = unwrap(category)
    country = unwrap(country)
    state = unwrap(state)
    city = unwrap(city)
    location = unwrap(location)
    plan = unwrap(plan)
    lat = unwrap(lat)
    lng = unwrap(lng)
    radius = unwrap(radius)
    near_me = unwrap(near_me)
    mode = unwrap(mode)

    shops = active_shops()
    intent = parse_search_intent(q, shops)
    legacy_country, legacy_state, legacy_city = _resolve_legacy_location(location, shops)

    country = country or legacy_country or intent["country"]
    state = state or legacy_state or intent["state"]
    city = city or legacy_city or intent["city"]
    requested_category = category or intent["category"]
    near_me_mode = bool(near_me or intent["near_me"] or (lat is not None and lng is not None))

    if not (0.1 <= radius <= 500):
        raise HTTPException(status_code=422, detail="radius must be between 0.1 and 500 kilometres.")
    if near_me_mode and (lat is None or lng is None):
        raise HTTPException(status_code=422, detail="Near Me search requires latitude and longitude.")
    if plan and normalize_text(plan) not in PLAN_RANK:
        raise HTTPException(status_code=422, detail="plan must be free, pro, or premium.")

    query_terms = intent["terms"]
    results: List[Dict[str, Any]] = []
    for shop in shops:
        if plan and shop["plan"] != normalize_text(plan):
            continue
        if not _category_matches(shop["category"], requested_category):
            continue
        if not _location_matches(shop, country, state, city):
            continue

        distance = None
        if lat is not None and lng is not None and shop["lat"] is not None and shop["lng"] is not None:
            distance = haversine(lat, lng, shop["lat"], shop["lng"])
        if near_me_mode:
            if distance is None or distance > radius:
                continue

        haystack = " ".join(
            normalize_text(shop.get(field))
            for field in ("business_name", "tagline", "description", "category", "country", "state", "city", "slug")
        )
        relevance = 0.0
        reasons: List[str] = []
        if q:
            if requested_category:
                relevance += 30
                reasons.append("category match")
            if country or state or city:
                relevance += 25
                reasons.append("location match")
            for term in query_terms:
                if term in normalize_text(shop["business_name"]):
                    relevance += 24
                    reasons.append("business name match")
                elif term in haystack:
                    relevance += 8
                    reasons.append("keyword match")
            if not requested_category and not (country or state or city) and not query_terms:
                if normalize_text(q) not in haystack:
                    continue
            elif query_terms and not any(term in haystack for term in query_terms):
                continue
        if near_me_mode:
            relevance += max(0.0, (radius - (distance or radius)) / radius * 20)
            reasons.append("near you")

        if mode == "trending":
            relevance += _activity_score(shop)
            reasons.append("recent activity")

        plan_score = PLAN_RANK[shop["plan"]] * 100
        activity_score = _activity_score(shop)
        proximity_score = max(0.0, radius - (distance or radius)) if near_me_mode else 0.0
        score = plan_score + relevance + activity_score + proximity_score
        results.append(_safe_result(shop, score, relevance, distance, sorted(set(reasons))))

    if mode == "trending":
        results.sort(
            key=lambda item: (
                PLAN_RANK.get(item["plan"], 1),
                item["score"],
                item["visit_count"],
            ),
            reverse=True,
        )
    elif near_me_mode:
        results.sort(key=lambda item: (PLAN_RANK.get(item["plan"], 1), item["relevance"], -(item["distance"] if item["distance"] is not None else 999999)), reverse=True)
    else:
        results.sort(key=lambda item: (PLAN_RANK.get(item["plan"], 1), item["relevance"], item["score"], item["business_name"].casefold()), reverse=True)

    return results, {
        "query": intent,
        "filters": {"category": requested_category or "", "country": country or "", "state": state or "", "city": city or ""},
        "near_me": near_me_mode,
        "radius": radius,
        "mode": mode,
    }


@router.get("/discover/search")
@router.get("/search")
def search_shops(
    q: Optional[str] = Query(None, description="Natural-language query, for example 'churches in Olambe'"),
    category: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    location: Optional[str] = Query(None, description="Legacy compatibility parameter: country/state:/city:"),
    plan: Optional[str] = Query(None),
    lat: Optional[float] = Query(None),
    lng: Optional[float] = Query(None),
    near_me: bool = Query(False),
    radius: float = Query(50.0, description="Near Me radius in kilometres"),
    mode: str = Query("search", pattern="^(search|trending)$"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    results, context = _run_search(
        q=q, category=category, country=country, state=state, city=city, location=location,
        plan=plan, lat=lat, lng=lng, radius=radius, near_me=near_me, mode=mode,
    )
    total = len(results)
    start = (page - 1) * limit
    paginated = results[start:start + limit]
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "pages": math.ceil(total / limit) if total else 0,
        "has_more": start + limit < total,
        "results": paginated,
        **context,
    }


@router.get("/discover/trending")
@router.get("/trending")
def trending_shops(
    category: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    lat: Optional[float] = Query(None),
    lng: Optional[float] = Query(None),
    near_me: bool = Query(False),
    radius: float = Query(50.0),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    return search_shops(
        category=category, country=country, state=state, city=city,
        lat=lat, lng=lng, near_me=near_me, radius=radius, mode="trending",
        page=page, limit=limit,
    )


@router.get("/discover/categories")
@router.get("/categories")
def get_categories():
    shops = active_shops()
    options: Dict[str, Dict[str, Any]] = {}
    for shop in shops:
        name = shop["category"]
        if not name:
            continue
        key = normalize_text(name)
        options.setdefault(key, {"name": name, "count": 0})["count"] += 1
    ordered = sorted(options.values(), key=lambda item: normalize_text(item["name"]))
    return {
        "categories": [item["name"] for item in ordered],
        "category_options": ordered,
        "total": len(ordered),
    }


@router.get("/discover/locations")
@router.get("/locations")
def get_locations():
    shops = active_shops()
    countries: Dict[str, Dict[str, Any]] = {}
    states: Dict[Tuple[str, str], Dict[str, Any]] = {}
    cities: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    for shop in shops:
        country = shop["country"]
        state = shop["state"]
        city = shop["city"]
        if country:
            countries.setdefault(normalize_text(country), {"name": country, "count": 0})["count"] += 1
        if state:
            key = (normalize_text(country), normalize_text(state))
            states.setdefault(key, {"name": state, "country": country, "count": 0})["count"] += 1
        if city:
            key = (normalize_text(country), normalize_text(state), normalize_text(city))
            cities.setdefault(key, {"name": city, "state": state, "country": country, "count": 0})["count"] += 1

    country_options = sorted(countries.values(), key=lambda item: normalize_text(item["name"]))
    state_options = sorted(states.values(), key=lambda item: normalize_text(f"{item['country']} {item['name']}"))
    city_options = sorted(cities.values(), key=lambda item: normalize_text(f"{item['country']} {item['state']} {item['name']}"))
    return {
        # Name arrays preserve compatibility with the current frontend.
        "countries": [item["name"] for item in country_options],
        "states": [item["name"] for item in state_options],
        "cities": [item["name"] for item in city_options],
        # Option objects are used by the richer frontend for counts and dependencies.
        "country_options": country_options,
        "state_options": state_options,
        "city_options": city_options,
        "total_active_shops": len(shops),
    }

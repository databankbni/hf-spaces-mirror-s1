from fastapi import APIRouter, HTTPException, Query
from typing import Optional
import math

from utils.db import get_shop_index, get_shop_by_slug

router = APIRouter()

def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate distance in km between two points using Haversine formula."""
    R = 6371.0  # Earth radius in km
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

@router.get("/search")
def search_shops(
    q: Optional[str] = Query(None, description="Search query"),
    category: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    plan: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    """Search and filter shops from the RAM index."""
    index = get_shop_index()
    results = []

    for slug, meta in index.items():
        # Only active shops in discover
        if meta.get("status") != "active":
            continue

        # Search query filter
        if q:
            q_lower = q.lower()
            searchable = " ".join([
                meta.get("business_name", ""),
                meta.get("tagline", ""),
                meta.get("description", ""),
                meta.get("category", ""),
                slug,
            ]).lower()
            if q_lower not in searchable:
                continue

        # Category filter
        if category and meta.get("category", "").lower() != category.lower():
            continue

        # Country filter
        if country and meta.get("country", "").lower() != country.lower():
            continue

        # State filter
        if state and meta.get("state", "").lower() != state.lower():
            continue

        # CITY filter
        if city and meta.get("city", "").lower() != city.lower():
            continue

        # Plan filter
        if plan and meta.get("plan", "") != plan.lower():
            continue

        results.append({
            "slug": slug,
            "business_name": meta.get("business_name", ""),
            "tagline": meta.get("tagline", ""),
            "description": meta.get("description", ""),
            "category": meta.get("category", ""),
            "country": meta.get("country", ""),
            "state": meta.get("state", ""),
            "city": meta.get("city", ""),
            "plan": meta.get("plan", "free"),
            "visit_count": meta.get("visit_count", 0),
            "created_at": meta.get("created_at", ""),
        })

    # Sort by visit_count desc (trending) then created_at desc
    results.sort(key=lambda x: (-x["visit_count"], x["created_at"]), reverse=False)

    total = len(results)
    start = (page - 1) * limit
    end = start + limit
    paginated = results[start:end]

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "results": paginated
    }

@router.get("/featured")
def get_featured_shops(
    limit: int = Query(10, ge=1, le=50),
    category: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
):
    """Get featured/premium shops."""
    index = get_shop_index()
    featured = []

    for slug, meta in index.items():
        if meta.get("status") != "active":
            continue
        if meta.get("plan") not in ["pro", "premium"]:
            continue
        if category and meta.get("category", "").lower() != category.lower():
            continue
        if country and meta.get("country", "").lower() != country.lower():
            continue

        featured.append({
            "slug": slug,
            "business_name": meta.get("business_name", ""),
            "tagline": meta.get("tagline", ""),
            "description": meta.get("description", ""),
            "category": meta.get("category", ""),
            "country": meta.get("country", ""),
            "plan": meta.get("plan", ""),
            "visit_count": meta.get("visit_count", 0),
        })

    # Sort by plan priority (premium first) then visits
    plan_priority = {"premium": 0, "pro": 1}
    featured.sort(key=lambda x: (plan_priority.get(x["plan"], 2), -x["visit_count"]))

    return {"featured": featured[:limit]}

@router.get("/trending")
def get_trending_shops(
    limit: int = Query(10, ge=1, le=50),
    category: Optional[str] = Query(None),
):
    """Get trending shops by visit count."""
    index = get_shop_index()
    trending = []

    for slug, meta in index.items():
        if meta.get("status") != "active":
            continue
        if meta.get("visit_count", 0) == 0:
            continue
        if category and meta.get("category", "").lower() != category.lower():
            continue

        trending.append({
            "slug": slug,
            "business_name": meta.get("business_name", ""),
            "tagline": meta.get("tagline", ""),
            "visit_count": meta.get("visit_count", 0),
            "plan": meta.get("plan", "free"),
            "country": meta.get("country", ""),
        })

    trending.sort(key=lambda x: -x["visit_count"])
    return {"trending": trending[:limit]}

@router.get("/categories")
def get_categories():
    """Get all unique categories from the index."""
    index = get_shop_index()
    categories = set()
    for meta in index.values():
        cat = meta.get("category", "").strip()
        if cat:
            categories.add(cat)
    return {"categories": sorted(list(categories))}

@router.get("/locations")
def get_locations():
    """Get all unique countries, states, LGAs from the index."""
    index = get_shop_index()
    countries = set()
    states = set()
    lgas = set()

    for meta in index.values():
        c = meta.get("country", "").strip()
        s = meta.get("state", "").strip()
        l = meta.get("lga", "").strip()
        if c: countries.add(c)
        if s: states.add(s)
        if l: lgas.add(l)

    return {
        "countries": sorted(list(countries)),
        "states": sorted(list(states)),
        "lgas": sorted(list(lgas)),
    }

@router.get("/{slug}")
def get_discover_shop(slug: str):
    """Get full shop data for discover page preview."""
    shop = get_shop_by_slug(slug)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    if shop.get("status") != "active":
        raise HTTPException(status_code=403, detail="Shop is not active")

    shop_json = shop.get("shop_json", {})
    if isinstance(shop_json, str):
        try:
            import json
            shop_json = json.loads(shop_json)
        except:
            shop_json = {}

    return {
        "slug": slug,
        "business_name": shop_json.get("business_name", ""),
        "tagline": shop_json.get("tagline", ""),
        "description": shop_json.get("description", ""),
        "logo_url": shop_json.get("logo_url", ""),
        "category": shop_json.get("category", ""),
        "country": shop.get("country", ""),
        "state": shop_json.get("state", ""),
        "city": shop_json.get("city", ""),
        "plan": shop.get("plan", "free"),
        "visit_count": shop.get("visit_count", 0),
        "catalog_url": shop_json.get("catalog", {}).get("url", "") if isinstance(shop_json.get("catalog"), dict) else "",
        "socials": shop_json.get("socials", {}),
    }

# ═══════════════════════════════════════════════════════════════════
# NEW: NEARBY SEARCH (Haversine)
# ═══════════════════════════════════════════════════════════════════

@router.get("/nearby")
def nearby_shops(
    lat: float = Query(..., description="User latitude"),
    lng: float = Query(..., description="User longitude"),
    radius_km: float = Query(10.0, ge=0.5, le=500, description="Search radius in km"),
    limit: int = Query(20, ge=1, le=100),
    category: Optional[str] = Query(None),
    plan: Optional[str] = Query(None),
):
    """Find active shops near a given lat/lng using Haversine formula. Zero-cost, no external API."""
    index = get_shop_index()
    results = []

    for slug, meta in index.items():
        # Only active shops
        if meta.get("status") != "active":
            continue

        # Must have lat/lng
        shop_lat = meta.get("lat")
        shop_lng = meta.get("lng")
        if shop_lat is None or shop_lng is None:
            continue

        # Category filter
        if category and meta.get("category", "").lower() != category.lower():
            continue

        # Plan filter
        if plan and meta.get("plan", "") != plan.lower():
            continue

        distance = haversine(lat, lng, float(shop_lat), float(shop_lng))
        if distance <= radius_km:
            results.append({
                "slug": slug,
                "business_name": meta.get("business_name", ""),
                "tagline": meta.get("tagline", ""),
                "category": meta.get("category", ""),
                "plan": meta.get("plan", "free"),
                "visit_count": meta.get("visit_count", 0),
                "distance_km": round(distance, 2),
                "country": meta.get("country", ""),
                "state": meta.get("state", ""),
                "city": meta.get("city", ""),
            })

    # Sort by distance ascending
    results.sort(key=lambda x: x["distance_km"])

    return {
        "total": len(results),
        "radius_km": radius_km,
        "user_location": {"lat": lat, "lng": lng},
        "results": results[:limit]
    }

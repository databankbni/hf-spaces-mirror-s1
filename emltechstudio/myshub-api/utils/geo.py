"""Geolocation utilities for MyShub API"""
import math
from typing import Optional


def haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate distance in kilometers between two coordinates."""
    R = 6371  # Earth's radius in km

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lng = math.radians(lng2 - lng1)

    a = (math.sin(delta_lat / 2) ** 2 +
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lng / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def get_country_from_ip(ip_address: str) -> str:
    """Get country from IP using free ip-api.com (no key needed)."""
    import requests
    try:
        if ip_address in ("127.0.0.1", "localhost", "::1") or ip_address.startswith(("192.168.", "10.", "172.")):
            return "Local"
        if ip_address == "unknown":
            return "Unknown"

        response = requests.get(
            f"http://ip-api.com/json/{ip_address}?fields=country,countryCode,status",
            timeout=3
        )
        data = response.json()
        if data.get("status") == "success":
            return data.get("country", "Unknown")
        return "Unknown"
    except Exception:
        return "Unknown"


def get_visitor_ip(request) -> str:
    """Extract real visitor IP from request headers."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

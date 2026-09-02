#!/usr/bin/env python3
"""Keyless real-world reference data: air quality, geocoding, quakes, holidays, indicators.

Built off the per-route revenue measurement of 2026-07-29, which only became readable once
`x402_route_stats.py --report` was fixed (it had matched nothing and reported "0 paid" for
every route while 509 paid calls sat in the file). What it then showed:

    /stocks   66 paid    /weather 66 paid    <- the two best-selling routes we have
    /lightning /lido /raydium /coinpaprika   ~58 paid each, 29-35% of challenges converted
    everything else in the catalog           2 paid, ~1.4%

Neither top seller is crypto, let alone security. The catalog is built around token safety
and the buyers are paying for **general-purpose real-world data**. So this module extends
in that direction instead of adding another chain reading.

Open-Meteo is deliberately over-represented: it already powers `/weather`, our joint best
seller, so its sibling APIs are the closest thing to a proven upstream we have.

Every upstream is free and needs no API key, so each route is pure margin. They all talk to
FIXED hosts — the caller supplies a place name, country code or bounding box, never a URL —
so webdata_routes.py's SSRF guard does not apply here.

Priced by the caller, not here: tokenguard mounts these at PRICE, which is **$0.02** (the
Bazaar median for our categories), not the $0.01 this module's own default suggests. Read
the live 402 challenge for the real number rather than trusting either.

A dead upstream raises 502, and the x402 middleware only settles a 2xx, so a caller is
never billed for an empty answer.

Mount with:
    from worlddata_routes import router as _wd_router, route_specs as _wd_route_specs
    app.include_router(_wd_router, prefix="/world")
    world_specs = _wd_route_specs(prefix="/world", price=PRICE)
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

UA = ("Mozilla/5.0 (compatible; world-data/1.0; "
      "+https://eltociear-tokenguard.hf.space)")
TIMEOUT = 20.0

OPEN_METEO_AQ = "https://air-quality-api.open-meteo.com/v1/air-quality"
OPEN_METEO_GEO = "https://geocoding-api.open-meteo.com/v1/search"
OPEN_METEO_ELEV = "https://api.open-meteo.com/v1/elevation"
USGS = "https://earthquake.usgs.gov/fdsnws/event/1/query"
NAGER = "https://date.nager.at/api/v3"
WORLDBANK = "https://api.worldbank.org/v2"

# World Bank indicator codes are unguessable, so the common ones get short aliases.
INDICATORS = {
    "gdp": "NY.GDP.MKTP.CD",
    "gdp_per_capita": "NY.GDP.PCAP.CD",
    "population": "SP.POP.TOTL",
    "inflation": "FP.CPI.TOTL.ZG",
    "unemployment": "SL.UEM.TOTL.ZS",
    "life_expectancy": "SP.DYN.LE00.IN",
    "co2_per_capita": "EN.GHG.CO2.PC.CE.AR5",
    "internet_users": "IT.NET.USER.ZS",
}


async def _json(url: str, params: dict = None):
    """GET JSON, retrying once on a transport failure.

    The retry is not defensive padding — api.worldbank.org is measurably erratic from here.
    Timing the SAME query repeatedly: 0.6s, 0.6s, 10.8s, 20.3s. It is not slow per country,
    it is randomly slow, and a flat 20s timeout sits right on that edge — which is how a
    real paid call for DE/gdp 502'd and then succeeded immediately on identical input.

    So the second attempt DOUBLES the timeout rather than just repeating it; retrying at the
    same 20s would have failed the 20.3s case twice. A non-200 is never retried — that is
    the upstream answering, and it will answer the same way again.
    """
    import httpx
    last = None
    for timeout in (TIMEOUT, TIMEOUT * 2):
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                r = await client.get(url, params=params or {}, headers={"User-Agent": UA})
            break
        except Exception as e:
            last = e
    else:
        raise HTTPException(502, f"upstream unreachable: {type(last).__name__}")
    if r.status_code != 200:
        raise HTTPException(502, f"upstream returned HTTP {r.status_code}")
    try:
        return r.json()
    except Exception:
        raise HTTPException(502, "upstream did not return JSON")


async def _resolve(place: str):
    """Place name -> (lat, lon, label). Callers should not have to know coordinates."""
    data = await _json(OPEN_METEO_GEO, {"name": place, "count": 1, "format": "json"})
    hits = data.get("results") or []
    if not hits:
        raise HTTPException(404, f"could not geocode {place!r}")
    h = hits[0]
    label = ", ".join(x for x in (h.get("name"), h.get("admin1"), h.get("country")) if x)
    return h["latitude"], h["longitude"], label


async def _coords(req):
    """Accept either explicit lat/lon or a place name, and report which was used."""
    if req.latitude is not None and req.longitude is not None:
        return float(req.latitude), float(req.longitude), None
    if not req.location:
        raise HTTPException(400, "provide either location, or both latitude and longitude")
    return await _resolve(req.location.strip())


class PointRequest(BaseModel):
    location: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class GeocodeRequest(BaseModel):
    name: str
    count: Optional[int] = 5


class QuakeRequest(BaseModel):
    min_magnitude: Optional[float] = 4.5
    days: Optional[int] = 1
    limit: Optional[int] = 20
    location: Optional[str] = None
    radius_km: Optional[float] = 500.0


class HolidayRequest(BaseModel):
    country: str
    year: Optional[int] = None


class IndicatorRequest(BaseModel):
    country: str
    indicator: Optional[str] = "gdp"
    years: Optional[int] = 5


@router.post("/airquality")
async def air_quality(req: PointRequest):
    """Current air quality for a place: PM2.5/PM10, ozone, NO2, and both AQI scales."""
    lat, lon, label = await _coords(req)
    fields = ("pm2_5,pm10,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone,"
              "us_aqi,european_aqi,dust,uv_index")
    data = await _json(OPEN_METEO_AQ, {"latitude": lat, "longitude": lon,
                                       "current": fields, "timezone": "auto"})
    cur = data.get("current") or {}
    units = data.get("current_units") or {}
    aqi = cur.get("us_aqi")
    # The number alone is not actionable; the EPA band is what a caller acts on.
    band = None
    if isinstance(aqi, (int, float)):
        for ceiling, name in ((50, "Good"), (100, "Moderate"),
                              (150, "Unhealthy for Sensitive Groups"),
                              (200, "Unhealthy"), (300, "Very Unhealthy")):
            if aqi <= ceiling:
                band = name
                break
        else:
            band = "Hazardous"
    return {"location": label or req.location, "latitude": lat, "longitude": lon,
            "observed_at": cur.get("time"), "us_aqi": aqi, "us_aqi_category": band,
            "european_aqi": cur.get("european_aqi"),
            "pollutants": {k: cur.get(k) for k in
                           ("pm2_5", "pm10", "carbon_monoxide", "nitrogen_dioxide",
                            "sulphur_dioxide", "ozone", "dust")},
            "uv_index": cur.get("uv_index"), "units": units,
            "fetched_at": datetime.utcnow().isoformat() + "Z"}


@router.post("/geocode")
async def geocode(req: GeocodeRequest):
    """Resolve a place name to coordinates, country, timezone and population."""
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    count = max(1, min(int(req.count or 5), 20))
    data = await _json(OPEN_METEO_GEO, {"name": name, "count": count, "format": "json"})
    hits = data.get("results") or []
    if not hits:
        raise HTTPException(404, f"no match for {name!r}")
    return {"query": name, "count": len(hits), "results": [
        {"name": h.get("name"), "country": h.get("country"),
         "country_code": h.get("country_code"), "admin1": h.get("admin1"),
         "latitude": h.get("latitude"), "longitude": h.get("longitude"),
         "elevation_m": h.get("elevation"), "timezone": h.get("timezone"),
         "population": h.get("population")} for h in hits],
        "fetched_at": datetime.utcnow().isoformat() + "Z"}


@router.post("/earthquakes")
async def earthquakes(req: QuakeRequest):
    """Recent earthquakes from the USGS feed, worldwide or within a radius of a place."""
    from datetime import timedelta
    days = max(1, min(int(req.days or 1), 30))
    params = {"format": "geojson", "orderby": "magnitude",
              "limit": max(1, min(int(req.limit or 20), 100)),
              "minmagnitude": float(req.min_magnitude if req.min_magnitude is not None else 4.5),
              "starttime": (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")}
    centre = None
    if req.location:
        lat, lon, centre = await _resolve(req.location.strip())
        params.update({"latitude": lat, "longitude": lon,
                       "maxradiuskm": max(1.0, min(float(req.radius_km or 500), 20000.0))})
    data = await _json(USGS, params)
    out = []
    for f in data.get("features", []):
        p = f.get("properties") or {}
        coords = (f.get("geometry") or {}).get("coordinates") or [None, None, None]
        out.append({"magnitude": p.get("mag"), "place": p.get("place"),
                    "time": datetime.utcfromtimestamp(p["time"] / 1000).isoformat() + "Z"
                            if p.get("time") else None,
                    "depth_km": coords[2], "longitude": coords[0], "latitude": coords[1],
                    "tsunami": bool(p.get("tsunami")), "felt_reports": p.get("felt"),
                    "url": p.get("url")})
    return {"count": len(out), "days": days, "min_magnitude": params["minmagnitude"],
            "centre": centre, "earthquakes": out,
            "fetched_at": datetime.utcnow().isoformat() + "Z"}


@router.post("/holidays")
async def holidays(req: HolidayRequest):
    """Public holidays for a country and year — what an agent needs to reason about dates."""
    code = (req.country or "").strip().upper()
    if len(code) != 2:
        raise HTTPException(400, "country must be a 2-letter ISO code, e.g. JP")
    year = int(req.year or datetime.utcnow().year)
    if not 1975 <= year <= 2100:
        raise HTTPException(400, "year out of range")
    data = await _json(f"{NAGER}/PublicHolidays/{year}/{code}")
    if not isinstance(data, list):
        raise HTTPException(502, "upstream returned an unexpected shape")
    today = datetime.utcnow().strftime("%Y-%m-%d")
    return {"country": code, "year": year, "count": len(data),
            "holidays": [{"date": h.get("date"), "name": h.get("name"),
                          "local_name": h.get("localName"), "nationwide": h.get("global"),
                          "counties": h.get("counties"), "types": h.get("types"),
                          "past": bool(h.get("date") and h["date"] < today)} for h in data],
            "fetched_at": datetime.utcnow().isoformat() + "Z"}


@router.post("/indicators")
async def indicators(req: IndicatorRequest):
    """World Bank country statistics: GDP, population, inflation and friends over time."""
    code = (req.country or "").strip()
    if not 2 <= len(code) <= 3:
        raise HTTPException(400, "country must be an ISO 2- or 3-letter code, e.g. JP or JPN")
    key = (req.indicator or "gdp").strip().lower()
    # Accept a raw World Bank code too, so the alias table is a convenience not a cage.
    ind = INDICATORS.get(key, req.indicator if "." in (req.indicator or "") else None)
    if not ind:
        raise HTTPException(400, f"unknown indicator {req.indicator!r}; "
                                 f"use one of {sorted(INDICATORS)} or a World Bank code")
    years = max(1, min(int(req.years or 5), 60))
    data = await _json(f"{WORLDBANK}/country/{code}/indicator/{ind}",
                       {"format": "json", "per_page": years})
    # World Bank replies [metadata, rows]; an error reply is a single dict-bearing list.
    if not isinstance(data, list) or len(data) < 2 or not isinstance(data[1], list):
        raise HTTPException(404, f"no data for {code}/{ind}")
    rows = [{"year": r.get("date"), "value": r.get("value")} for r in data[1]]
    latest = next((r for r in rows if r["value"] is not None), None)
    meta = (data[1][0] or {}) if data[1] else {}
    return {"country": (meta.get("country") or {}).get("value") or code,
            "country_code": meta.get("countryiso3code"),
            "indicator": (meta.get("indicator") or {}).get("value") or ind,
            "indicator_code": ind, "alias": key if key in INDICATORS else None,
            "latest": latest, "series": rows,
            "fetched_at": datetime.utcnow().isoformat() + "Z"}


@router.post("/elevation")
async def elevation(req: PointRequest):
    """Ground elevation in metres for a place or coordinate pair."""
    lat, lon, label = await _coords(req)
    data = await _json(OPEN_METEO_ELEV, {"latitude": lat, "longitude": lon})
    vals = data.get("elevation") or []
    if not vals:
        raise HTTPException(502, "upstream returned no elevation")
    return {"location": label or req.location, "latitude": lat, "longitude": lon,
            "elevation_m": vals[0], "fetched_at": datetime.utcnow().isoformat() + "Z"}


# GET/POST/HEAD: this is a free diagnostic and the crawler fleet POSTs it. Registered
# GET-only it answered 405, which tells a prober the path is not there at all. Its
# full path is also in mcp_http.FREE_PATHS so tokenguard's blanket POST sweep cannot
# turn a diagnostic into a paid route.
@router.api_route("/selftest", methods=["GET", "POST", "HEAD"])
async def world_selftest():
    """FREE. Per-upstream reachability for every backend behind these routes.

    Same reasoning as the other selftests: a paid route cannot be exercised without paying,
    so this is the only way to tell a dead upstream from a broken parser. Returns latency
    and a boolean only, never a payload, so it gives away nothing the paid routes sell.
    """
    import time
    checks = {
        "open-meteo-air-quality": (OPEN_METEO_AQ, {"latitude": 35.68, "longitude": 139.69,
                                                   "current": "pm2_5"}),
        "open-meteo-geocoding": (OPEN_METEO_GEO, {"name": "Osaka", "count": 1}),
        "open-meteo-elevation": (OPEN_METEO_ELEV, {"latitude": 35.68, "longitude": 139.69}),
        "usgs-earthquakes": (USGS, {"format": "geojson", "limit": 1, "minmagnitude": 4.5}),
        "nager-holidays": (f"{NAGER}/PublicHolidays/{datetime.utcnow().year}/JP", None),
        "worldbank-indicators": (f"{WORLDBANK}/country/JP/indicator/SP.POP.TOTL",
                                 {"format": "json", "per_page": 1}),
    }
    out = {}
    for name, (url, params) in checks.items():
        t0 = time.monotonic()
        try:
            data = await _json(url, params)
            out[name] = {"ok": bool(data), "ms": int((time.monotonic() - t0) * 1000)}
        except HTTPException as e:
            out[name] = {"ok": False, "error": str(e.detail)[:80],
                         "ms": int((time.monotonic() - t0) * 1000)}
        except Exception as e:
            out[name] = {"ok": False, "error": type(e).__name__,
                         "ms": int((time.monotonic() - t0) * 1000)}
    return {"upstreams": out, "usable": sum(1 for v in out.values() if v.get("ok")),
            "checked_at": datetime.utcnow().isoformat() + "Z"}


def route_specs(prefix: str = "", price: str = "$0.01"):
    """(path, price, description, input_example, input_schema, output_example) per route."""
    p = prefix.rstrip("/")

    def s(props, required):
        return {"properties": props, "required": required}

    place = {"location": {"type": "string", "description": "Place name, e.g. 'Tokyo' — geocoded for you"},
             "latitude": {"type": "number", "description": "Latitude (use instead of location)"},
             "longitude": {"type": "number", "description": "Longitude (use instead of location)"}}
    return [
        (p + "/airquality", price,
         "How breathable is the air in this place right now? Current PM2.5, PM10, ozone, NO2, "
         "SO2, CO and dust plus both the US and European AQI, and the US AQI band ('Good', "
         "'Unhealthy') so the number is directly actionable. Takes a place name, not coordinates",
         {"location": "Tokyo"}, s(place, []),
         {"location": "Tokyo, Japan", "us_aqi": 42, "us_aqi_category": "Good",
          "european_aqi": 18, "pollutants": {"pm2_5": 9.8, "ozone": 61.0}, "uv_index": 5.2}),
        (p + "/geocode", price,
         "Turn a place name into coordinates, country, admin region, timezone, elevation and "
         "population — the lookup every other location-aware call needs first",
         {"name": "Osaka", "count": 3},
         s({"name": {"type": "string", "description": "Place name to resolve"},
            "count": {"type": "integer", "description": "1-20 candidates (default 5)"}}, ["name"]),
         {"query": "Osaka", "count": 1, "results": [
             {"name": "Osaka", "country": "Japan", "country_code": "JP",
              "latitude": 34.69, "longitude": 135.5, "timezone": "Asia/Tokyo",
              "population": 2691185}]}),
        (p + "/earthquakes", price,
         "Which earthquakes have just happened? Recent USGS events worldwide or within a "
         "radius of a named place, with magnitude, depth, tsunami flag and felt reports",
         {"min_magnitude": 5.0, "days": 7, "location": "Tokyo", "radius_km": 800},
         s({"min_magnitude": {"type": "number", "description": "Lower magnitude bound (default 4.5)"},
            "days": {"type": "integer", "description": "1-30 days back (default 1)"},
            "limit": {"type": "integer", "description": "1-100 events (default 20)"},
            "location": {"type": "string", "description": "Centre the search on a place name"},
            "radius_km": {"type": "number", "description": "Radius around location (default 500)"}}, []),
         {"count": 2, "days": 7, "centre": "Tokyo, Japan", "earthquakes": [
             {"magnitude": 6.1, "place": "off the east coast of Honshu, Japan",
              "time": "2026-07-27T11:02:14Z", "depth_km": 42.0, "tsunami": False}]}),
        (p + "/holidays", price,
         "Which days are public holidays in this country? Full year of national and regional "
         "holidays with local names and a past/upcoming flag — date arithmetic an agent "
         "cannot infer from a calendar alone",
         {"country": "JP", "year": 2026},
         s({"country": {"type": "string", "description": "ISO 2-letter country code, e.g. JP"},
            "year": {"type": "integer", "description": "Calendar year (defaults to the current one)"}},
           ["country"]),
         {"country": "JP", "year": 2026, "count": 16, "holidays": [
             {"date": "2026-01-01", "name": "New Year's Day", "local_name": "元日",
              "nationwide": True, "past": True}]}),
        (p + "/indicators", price,
         "What are this country's headline economics? World Bank time series for GDP, GDP per "
         "capita, population, inflation, unemployment, life expectancy, CO2 per capita or "
         "internet penetration, by plain-English alias or raw indicator code",
         {"country": "JP", "indicator": "gdp", "years": 5},
         s({"country": {"type": "string", "description": "ISO 2- or 3-letter country code"},
            "indicator": {"type": "string", "description":
                          "gdp | gdp_per_capita | population | inflation | unemployment | "
                          "life_expectancy | co2_per_capita | internet_users, or a World Bank code"},
            "years": {"type": "integer", "description": "1-60 most recent years (default 5)"}},
           ["country"]),
         {"country": "Japan", "country_code": "JPN", "indicator": "GDP (current US$)",
          "latest": {"year": "2025", "value": 4435162999900.0},
          "series": [{"year": "2025", "value": 4435162999900.0}]}),
        (p + "/elevation", price,
         "How high above sea level is this point? Ground elevation in metres for a place name "
         "or a coordinate pair",
         {"location": "Tokyo"}, s(place, []),
         {"location": "Tokyo, Japan", "latitude": 35.68, "longitude": 139.69,
          "elevation_m": 38.0}),
    ]

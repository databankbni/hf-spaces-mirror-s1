"""
FII/DII flow and Nifty PCR fetcher with JSON cache fallback.
Uses NSE public APIs; falls back to yesterday's cached values on failure.
"""
import json
import os
import time
import datetime
import requests

CACHE_FILE = os.path.join(os.path.dirname(__file__), "fii_pcr_cache.json")

# Browser-like headers required by NSE archives
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.nseindia.com/",
}

_NSE_FII_URL = (
    "https://archives.nseindia.com/content/fo/fii_stats_{date}.csv"
)
_NSE_OPTION_CHAIN_URL = (
    "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
)


def _load_cache() -> dict:
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(data: dict) -> None:
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def _cache_is_fresh(cache: dict) -> bool:
    ts = cache.get("ts", "")
    today = datetime.date.today().isoformat()
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    return ts in (today, yesterday)


def _classify_regime(fii_net: float, dii_net: float) -> str:
    if fii_net >= 3000:
        return "FII_STRONG_BUY"
    elif fii_net >= 1000:
        return "FII_BUY"
    elif fii_net <= -3000:
        return "RISK_OFF"
    elif fii_net <= -2000 and dii_net >= 1500:
        return "FII_SELLING_DII_ABSORBING"
    else:
        return "NEUTRAL"


def get_fii_dii_flow() -> dict:
    """
    Fetch FII/DII net flow from NSE archives CSV.
    Returns dict: {fii_net, dii_net, regime, ts}.
    Falls back to cached value (up to 1 day old) on any network error.
    Units: crore INR (as published by NSE).
    """
    cache = _load_cache()

    # Try today and yesterday in case today's file isn't published yet
    for offset in (0, 1, 2):
        date_obj = datetime.date.today() - datetime.timedelta(days=offset)
        date_str = date_obj.strftime("%d%m%Y")
        url = _NSE_FII_URL.format(date=date_str)
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=8)
            if resp.status_code != 200:
                continue
            # NSE CSV columns: Type, Buy, Sell, Net (in crore)
            lines = [l.strip() for l in resp.text.splitlines() if l.strip()]
            fii_net = dii_net = None
            for line in lines:
                parts = [p.strip().strip('"') for p in line.split(",")]
                if len(parts) < 4:
                    continue
                label = parts[0].upper()
                try:
                    net = float(parts[3].replace(",", ""))
                except (ValueError, IndexError):
                    continue
                if "FII" in label or "FOREIGN" in label:
                    fii_net = net
                elif "DII" in label or "DOMESTIC" in label:
                    dii_net = net
            if fii_net is None:
                continue
            dii_net = dii_net or 0.0
            regime = _classify_regime(fii_net, dii_net)
            result = {
                "fii_net": round(fii_net, 1),
                "dii_net": round(dii_net, 1),
                "regime":  regime,
                "ts":      date_obj.isoformat(),
            }
            cache.update(result)
            _save_cache(cache)
            return result
        except Exception:
            continue

    # Fallback: use cache if fresh enough
    if _cache_is_fresh(cache) and "fii_net" in cache:
        return {k: cache[k] for k in ("fii_net", "dii_net", "regime", "ts")}

    # Last resort: neutral defaults
    return {"fii_net": 0.0, "dii_net": 0.0, "regime": "NEUTRAL",
            "ts": datetime.date.today().isoformat()}


def get_nifty_pcr() -> float | None:
    """
    Fetch Nifty Put-Call Ratio from NSE option chain API.
    Returns total put OI / total call OI, or None on failure.
    Falls back to cached value (up to 1 day old).
    """
    cache = _load_cache()

    try:
        # NSE option chain requires a cookie first
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=_HEADERS, timeout=8)
        time.sleep(0.3)
        resp = session.get(_NSE_OPTION_CHAIN_URL, headers=_HEADERS, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            records = data.get("records", {}).get("data", [])
            total_put_oi = sum(
                r.get("PE", {}).get("openInterest", 0) for r in records if r.get("PE")
            )
            total_call_oi = sum(
                r.get("CE", {}).get("openInterest", 0) for r in records if r.get("CE")
            )
            if total_call_oi > 0:
                pcr = round(total_put_oi / total_call_oi, 2)
                cache["pcr"] = pcr
                cache["pcr_ts"] = datetime.date.today().isoformat()
                _save_cache(cache)
                return pcr
    except Exception:
        pass

    # Fallback
    pcr_ts = cache.get("pcr_ts", "")
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    if pcr_ts >= yesterday and "pcr" in cache:
        return float(cache["pcr"])

    return None


if __name__ == "__main__":
    print("FII/DII flow:", get_fii_dii_flow())
    print("Nifty PCR:", get_nifty_pcr())

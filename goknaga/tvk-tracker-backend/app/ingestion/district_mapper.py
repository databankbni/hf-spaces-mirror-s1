"""Tamil Nadu locality -> district mapper.

Maps the free-text `location` field on each incident to one of TN's
38 administrative districts. Used by the ingestion pipeline so every
new incident gets tagged with its district, and by the backfill script
for existing rows.

Two-stage resolution:
  1. EXACT/SUBSTRING match against the locality dictionary below
     (covers all 38 districts as their own names + spelling variants +
     Chennai's main neighborhoods + major towns mapped to their districts)
  2. AI fallback via Claude — only invoked when the dictionary returns
     None and the location string is non-trivial. Cheap (~$0.0003 per
     unknown locality, cached so we never ask twice for the same string).

The dictionary is intentionally hand-curated rather than auto-scraped
from Wikipedia because it covers the high-frequency locality names that
actually appear in Tamil press incidents. Coverage can grow over time
as unknown locations get logged.
"""
from __future__ import annotations
import logging
import re
import json

logger = logging.getLogger(__name__)


# All 38 districts as their canonical English names. Used for output
# normalization so spelling variants ("Trichy" / "Tiruchirappalli") collapse
# to one bucket on the dashboard.
TN_DISTRICTS: list[str] = [
    "Ariyalur", "Chengalpattu", "Chennai", "Coimbatore", "Cuddalore",
    "Dharmapuri", "Dindigul", "Erode", "Kallakurichi", "Kanchipuram",
    "Kanyakumari", "Karur", "Krishnagiri", "Madurai", "Mayiladuthurai",
    "Nagapattinam", "Namakkal", "Nilgiris", "Perambalur", "Pudukkottai",
    "Ramanathapuram", "Ranipet", "Salem", "Sivaganga", "Tenkasi",
    "Thanjavur", "Theni", "Thoothukudi", "Tiruchirappalli", "Tirunelveli",
    "Tirupattur", "Tiruppur", "Tiruvallur", "Tiruvannamalai", "Tiruvarur",
    "Vellore", "Viluppuram", "Virudhunagar",
]

DISTRICT_SET = {d.lower() for d in TN_DISTRICTS}


# Locality -> canonical district name.  All lookups are case-insensitive
# substring matches, so partial city names match too (e.g. "in Pollachi
# town" -> matches "pollachi" -> Coimbatore).
#
# Format: every key is the LOWERCASE locality keyword that might appear
# in a `location` string. Values are the official TN district name.
LOCALITY_TO_DISTRICT: dict[str, str] = {
    # ---- District names + spelling variants (most common case) ----
    "chennai":            "Chennai",
    "madras":             "Chennai",
    "coimbatore":         "Coimbatore",
    "kovai":              "Coimbatore",
    "madurai":            "Madurai",
    "alagar kovil":       "Madurai",
    "alagarkovil":        "Madurai",
    "azhagar kovil":      "Madurai",
    "trichy":             "Tiruchirappalli",
    "tiruchi":            "Tiruchirappalli",
    "tiruchirappalli":    "Tiruchirappalli",
    "tiruchirapalli":     "Tiruchirappalli",
    "tirunelveli":        "Tirunelveli",
    "thirunelveli":       "Tirunelveli",   # common 'th' transliteration
    "nellai":             "Tirunelveli",
    "salem":              "Salem",
    "erode":              "Erode",
    "vellore":            "Vellore",
    "thanjavur":          "Thanjavur",
    "tanjore":            "Thanjavur",
    "tanjavur":           "Thanjavur",
    "dindigul":           "Dindigul",
    "tiruppur":           "Tiruppur",
    "tirupur":            "Tiruppur",
    "thiruppur":          "Tiruppur",
    "thirupur":           "Tiruppur",
    "tuticorin":          "Thoothukudi",
    "thoothukudi":        "Thoothukudi",
    "thoothukkudi":       "Thoothukudi",
    "vilathikulam":       "Thoothukudi",
    "sathankulam":        "Thoothukudi",
    "kanyakumari":        "Kanyakumari",
    "kanniyakumari":      "Kanyakumari",
    "cape comorin":       "Kanyakumari",
    "nagercoil":          "Kanyakumari",
    "krishnagiri":        "Krishnagiri",
    "hosur":              "Krishnagiri",
    "dharmapuri":         "Dharmapuri",
    "namakkal":           "Namakkal",
    "tiruvallur":         "Tiruvallur",
    "thiruvallur":        "Tiruvallur",
    "tiruvalur":          "Tiruvallur",   # common single-l typo
    "tiruvarur":          "Tiruvarur",
    "thiruvarur":         "Tiruvarur",
    "nagapattinam":       "Nagapattinam",
    "mayiladuthurai":     "Mayiladuthurai",
    "perambalur":         "Perambalur",
    "ariyalur":           "Ariyalur",
    "cuddalore":          "Cuddalore",
    "viluppuram":         "Viluppuram",
    "villupuram":         "Viluppuram",
    "vizhupuram":         "Viluppuram",
    "kallakurichi":       "Kallakurichi",
    "tiruvannamalai":     "Tiruvannamalai",
    "thiruvannamalai":    "Tiruvannamalai",
    "tirupathur":         "Tirupattur",
    "tirupattur":         "Tirupattur",
    "ranipet":            "Ranipet",
    "kanchipuram":        "Kanchipuram",
    "kancheepuram":       "Kanchipuram",
    "chengalpattu":       "Chengalpattu",
    "chengalpet":         "Chengalpattu",
    "karur":              "Karur",
    "pudukkottai":        "Pudukkottai",
    "pudukottai":         "Pudukkottai",
    "sivaganga":          "Sivaganga",
    "sivagangai":         "Sivaganga",
    "ramanathapuram":     "Ramanathapuram",
    "ramnad":             "Ramanathapuram",
    "virudhunagar":       "Virudhunagar",
    "theni":              "Theni",
    "tenkasi":            "Tenkasi",
    "thenkasi":           "Tenkasi",
    "nilgiris":           "Nilgiris",
    "nilgiri":            "Nilgiris",      # singular form ("Nilgiri district")
    "ooty":               "Nilgiris",
    "udhagamandalam":     "Nilgiris",
    "coonoor":            "Nilgiris",
    "kotagiri":           "Nilgiris",
    # ---- Chennai neighborhoods (high incident frequency) ----
    "adyar":              "Chennai",
    "anna nagar":         "Chennai",
    "annanagar":          "Chennai",
    "t.nagar":            "Chennai",
    "t nagar":            "Chennai",
    "thiyagaraya nagar":  "Chennai",
    "mylapore":           "Chennai",
    "velachery":          "Chennai",
    "thiruvanmiyur":      "Chennai",
    "neelankarai":        "Chennai",
    "besant nagar":       "Chennai",
    "mandaveli":          "Chennai",
    "mambalam":           "Chennai",
    "royapettah":         "Chennai",
    "triplicane":         "Chennai",
    "chetpet":            "Chennai",
    "egmore":             "Chennai",
    "nungambakkam":       "Chennai",
    "kilpauk":            "Chennai",
    "aminjikarai":        "Chennai",
    "vadapalani":         "Chennai",
    "chromepet":          "Chennai",
    "tambaram":           "Chennai",
    "pallavaram":         "Chennai",
    "guindy":             "Chennai",
    "saidapet":           "Chennai",
    "alandur":            "Chennai",
    "porur":              "Chennai",
    "ambattur":           "Chennai",
    "kolathur":           "Chennai",
    "madhavaram":         "Chennai",
    "perambur":           "Chennai",
    "sembium":            "Chennai",
    "manali":             "Chennai",
    "tondiarpet":         "Chennai",
    "sowcarpet":          "Chennai",
    "royapuram":          "Chennai",
    "tiruvottiyur":       "Chennai",
    "thiruvottriyur":     "Chennai",
    "kovilambakkam":      "Chennai",
    "sholinganallur":     "Chennai",
    "thoraipakkam":       "Chennai",
    "perungudi":          "Chennai",
    "kotturpuram":        "Chennai",
    "teynampet":          "Chennai",
    "park town":          "Chennai",
    "mount road":         "Chennai",
    "anna salai":         "Chennai",
    "marina":             "Chennai",
    "marina beach":       "Chennai",
    # ---- Major non-district towns mapped to their district ----
    "pollachi":           "Coimbatore",
    "mettupalayam":       "Coimbatore",
    "kavundampalayam":    "Coimbatore",
    "valparai":           "Coimbatore",
    "sulur":              "Coimbatore",
    "kumbakonam":         "Thanjavur",
    "papanasam":          "Thanjavur",
    "thiruvaiyaru":       "Thanjavur",
    "rameshwaram":        "Ramanathapuram",
    "rameswaram":         "Ramanathapuram",
    "paramakudi":         "Ramanathapuram",
    "karaikudi":          "Sivaganga",
    "devakottai":         "Sivaganga",
    "sivakasi":           "Virudhunagar",
    "rajapalayam":        "Virudhunagar",
    "srivilliputhur":     "Virudhunagar",
    "aruppukkottai":      "Virudhunagar",
    "kovilpatti":         "Thoothukudi",
    "tiruchendur":        "Thoothukudi",
    "thiruchendur":       "Thoothukudi",
    "ettayapuram":        "Thoothukudi",
    "vriddhachalam":      "Cuddalore",
    "chidambaram":        "Cuddalore",
    "neyveli":            "Cuddalore",
    "panruti":            "Cuddalore",
    "tindivanam":         "Viluppuram",
    "gingee":             "Viluppuram",
    "ulundurpet":         "Kallakurichi",
    "sankarapuram":       "Kallakurichi",
    "polur":              "Tiruvannamalai",
    "arani":              "Tiruvannamalai",
    "cheyyar":            "Tiruvannamalai",
    "vandavasi":          "Tiruvannamalai",
    "kallakkurichi":      "Kallakurichi",
    "arakkonam":          "Ranipet",
    "walajapet":          "Ranipet",
    "ambur":              "Tirupattur",
    "vaniyambadi":        "Tirupattur",
    "natrampalli":        "Tirupattur",
    "sriperumbudur":      "Kanchipuram",
    "kanchi":             "Kanchipuram",
    "tirukalukundram":    "Chengalpattu",
    "thirukazhukundram":  "Chengalpattu",
    "mahabalipuram":      "Chengalpattu",
    "kelambakkam":        "Chengalpattu",
    "tiruporur":          "Chengalpattu",
    "avadi":              "Tiruvallur",
    "tiruttani":          "Tiruvallur",
    "ponneri":            "Tiruvallur",
    "poonamallee":        "Tiruvallur",
    "redhills":           "Tiruvallur",
    "gummidipoondi":      "Tiruvallur",
    "thirumullaivoyal":   "Tiruvallur",
    "uthukottai":         "Tiruvallur",
    "tirukoyilur":        "Kallakurichi",   # historical reassignment
    "panagudi":           "Tirunelveli",
    "kallidaikurichi":    "Tirunelveli",
    "ambasamudram":       "Tirunelveli",
    "tenkasi-town":       "Tenkasi",
    "shenkottai":         "Tenkasi",
    "alangulam":          "Tenkasi",
    "sankarankoil":       "Tenkasi",
    "kovilpatti-town":    "Thoothukudi",
    "palani":             "Dindigul",
    "kodaikanal":         "Dindigul",
    "oddanchatram":       "Dindigul",
    "vedasandur":         "Dindigul",
    "natham":             "Dindigul",
    "uttamapalayam":      "Theni",
    "bodi":               "Theni",
    "bodinayakanur":      "Theni",
    "cumbum":             "Theni",
    "perundurai":         "Erode",
    "gobichettipalayam":  "Erode",
    "bhavani":            "Erode",
    "sathyamangalam":     "Erode",
    "anthiyur":           "Erode",
    "kangeyam":           "Tiruppur",
    "dharapuram":         "Tiruppur",
    "udumalpet":          "Tiruppur",
    "avinashi":           "Tiruppur",
    "palladam":           "Tiruppur",
    "rasipuram":          "Namakkal",
    "tiruchengode":       "Namakkal",
    "thiruchengode":      "Namakkal",
    "sankari":            "Salem",
    "mettur":             "Salem",
    "yercaud":            "Salem",
    "attur":              "Salem",
    "edappadi":           "Salem",
    "harur":              "Dharmapuri",
    "pennagaram":         "Dharmapuri",
    "palacode":           "Dharmapuri",
    "denkanikottai":      "Krishnagiri",
    "uthangarai":         "Krishnagiri",
    "bargur":             "Krishnagiri",
    "veppanahalli":       "Krishnagiri",
    "thiruverumbur":      "Tiruchirappalli",
    "tiruverumbur":       "Tiruchirappalli",
    "musiri":             "Tiruchirappalli",
    "lalgudi":            "Tiruchirappalli",
    "manapparai":         "Tiruchirappalli",
    "srirangam":          "Tiruchirappalli",
    "perambalur-town":    "Perambalur",
    "udayarpalayam":      "Ariyalur",
    "jayankondam":        "Ariyalur",
    "mannargudi":         "Tiruvarur",
    "nannilam":           "Tiruvarur",
    "thiruthuraipoondi":  "Tiruvarur",
    "kuthalam":           "Mayiladuthurai",
    "sirkali":            "Mayiladuthurai",
    "tharangambadi":      "Mayiladuthurai",
    "vedaranyam":         "Nagapattinam",
    "kilvelur":           "Nagapattinam",
    "sembanarkoil":       "Nagapattinam",
    "thirukkadaiyur":     "Mayiladuthurai",
    "sholavandan":        "Madurai",          # named in NIE article
    "melur":              "Madurai",
    "usilampatti":        "Madurai",
    "vadipatti":          "Madurai",
    "thirumangalam":      "Madurai",
    "thirupuvanam":       "Madurai",
    "alanganallur":       "Madurai",
    "andipatti":          "Theni",
    "villathikulam":      "Thoothukudi",
    # ---- Added after first-pass backfill discovered gaps ----
    "pallipalayam":       "Namakkal",
    "kumarapalayam":      "Namakkal",
    "komarapalayam":      "Namakkal",      # spelling variant
    "ilayankudi":         "Sivaganga",
    "ilaiyankudi":        "Sivaganga",
    "kuppam":             "Krishnagiri",   # Tamil-speaking border zone, closest TN district
    # ---- Added after 2026-07 coverage audit (real localities the mapper missed) ----
    "kummidipundi":       "Tiruvallur",    # Gummidipoondi spelling variant
    "gummidipundi":       "Tiruvallur",
    "parandur":           "Kanchipuram",   # proposed airport site
    "thiruttani":         "Tiruvallur",
    "srivaikuntam":       "Thoothukudi",
    "srivaikundam":       "Thoothukudi",
    "thiruparankundram":  "Madurai",
    "thiruparankundram":  "Madurai",
    "ambasamudram":       "Tirunelveli",
    "ambazamuthur":       "Tirunelveli",   # phonetic variant
    "jayamkondam":        "Ariyalur",
    "jayankondam":        "Ariyalur",
    "tharapuram":         "Tiruppur",      # Dharapuram variant
    "oosoor":             "Krishnagiri",   # Hosur variant
    "shozhinganallur":    "Chengalpattu",
    "sholinganallur":     "Chengalpattu",
    "pallavaram":         "Chengalpattu",
    "tambaram":           "Chengalpattu",
    "vridhachalam":       "Cuddalore",
    "vriddhachalam":      "Cuddalore",
    "kadayanallur":       "Tenkasi",
    "sankarankovil":      "Tenkasi",
    "manamadurai":        "Sivaganga",
}


def _normalize(s: str) -> str:
    """Lowercase + collapse whitespace + strip punctuation for matching."""
    return re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower()).strip()


def map_location_to_district(location: str | None) -> str | None:
    """Resolve a free-text location to one of TN's 38 districts.

    Returns the canonical district name (e.g. "Chennai") or None if no
    match.  Callers may then fall back to AI resolution for unknowns.
    """
    if not location:
        return None
    norm = _normalize(location)
    if not norm:
        return None

    # "tamil nadu" / "tamilnadu" / "tn" alone -> state-wide, no district
    if norm in ("tamil nadu", "tamilnadu", "tn", "tn state", "tn statewide", "tamil nadu state"):
        return None

    # Direct district name match (most common)
    for district in TN_DISTRICTS:
        d_lower = district.lower()
        if d_lower == norm or f" {d_lower} " in f" {norm} ":
            return district

    # Locality dictionary substring match — longest keyword wins to avoid
    # "anna nagar" matching just "anna".
    matches: list[tuple[int, str]] = []
    for key, dist in LOCALITY_TO_DISTRICT.items():
        if key in norm:
            matches.append((len(key), dist))
    if matches:
        matches.sort(reverse=True)
        return matches[0][1]

    return None


# ---- AI fallback for unknowns -------------------------------------------

_DISTRICT_LIST_PROMPT = ", ".join(TN_DISTRICTS)


def map_location_via_ai(location: str, *, client=None, model: str | None = None) -> str | None:
    """Last-resort: ask Claude to resolve an unknown TN locality to its
    district.  Only call when the dictionary returns None; not free.
    """
    if not location:
        return None
    try:
        if client is None:
            from app.ingestion.ai_processor import _get_client_and_model
            client, model = _get_client_and_model()
        if client is None:
            return None
        prompt = (
            f"Which Tamil Nadu district contains the locality '{location}'?\n"
            f"Choose EXACTLY ONE from this list (or reply 'NONE' if not in TN or unknown):\n"
            f"{_DISTRICT_LIST_PROMPT}\n\n"
            f"Reply with ONLY the district name, nothing else. Examples:\n"
            f"  Input: 'Pollachi' -> Output: Coimbatore\n"
            f"  Input: 'XYZ village' -> Output: NONE"
        )
        resp = client.chat.completions.create(
            model=model,
            max_tokens=20,
            messages=[{"role": "user", "content": prompt}],
        )
        answer = (resp.choices[0].message.content or "").strip().split("\n")[0].strip()
        if answer.upper() == "NONE":
            return None
        for d in TN_DISTRICTS:
            if d.lower() == answer.lower():
                return d
        return None
    except Exception as e:
        logger.debug("AI district resolution failed for %r: %s", location, e)
        return None


def resolve_district(location: str | None, *, use_ai_fallback: bool = True) -> str | None:
    """Public API: dict lookup first, AI fallback if requested.  Returns
    canonical district name or None for state-wide / unknown."""
    if not location:
        return None
    direct = map_location_to_district(location)
    if direct:
        return direct
    if use_ai_fallback:
        return map_location_via_ai(location)
    return None

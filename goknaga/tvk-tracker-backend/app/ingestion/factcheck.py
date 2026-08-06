"""
Google Fact Check Tools API integration.

Free API that indexes ClaimReview-tagged fact-checks from:
  AltNews, BOOM Live, Fact Crescendo, NewsMobile, The Quint Webqoof,
  Politifact, Snopes, AFP Fact Check, etc.

Docs: https://developers.google.com/fact-check/tools/api
Endpoint: GET https://factchecktools.googleapis.com/v1alpha1/claims:search

Set GOOGLE_FACT_CHECK_API_KEY in the env. Without it, this module is a
no-op (lookup returns []) so the rest of the pipeline still works.
"""
import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

API_URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"


def lookup_factchecks(claim_text: str, people: list[str] | None = None) -> list[dict]:
    """Return a list of fact-checks matching `claim_text` or any of `people`.

    Each result has keys: publisher, url, claim, rating, date.
    Empty list if API key missing or no matches.
    """
    api_key = settings.google_fact_check_api_key
    if not api_key:
        return []

    queries: list[str] = []
    # Try the full claim text first (Google trims to first 100 chars for relevance)
    queries.append(claim_text[:120])
    # Then individual people-of-interest as fallback searches
    for p in (people or [])[:2]:
        if p and len(p) > 3:
            queries.append(p)

    seen_urls: set[str] = set()
    results: list[dict] = []

    for q in queries:
        try:
            r = httpx.get(
                API_URL,
                params={
                    "key": api_key,
                    "query": q,
                    "languageCode": "en",  # also try 'ta' separately below
                    "maxAgeDays": 30,       # restrict to recent fact-checks
                    "pageSize": 5,
                },
                timeout=10.0,
            )
            if r.status_code != 200:
                logger.debug("FactCheck %s -> %d %s", q[:40], r.status_code, r.text[:120])
                continue
            data = r.json()
            for c in data.get("claims", []) or []:
                claim_text_str = (c.get("text") or "").strip()
                for review in (c.get("claimReview") or [])[:1]:
                    url = review.get("url")
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    results.append({
                        "publisher": (review.get("publisher") or {}).get("name") or "?",
                        "publisher_site": (review.get("publisher") or {}).get("site") or "",
                        "url": url,
                        "claim": claim_text_str[:300],
                        "rating": review.get("textualRating") or "",
                        "review_date": review.get("reviewDate") or "",
                        "language": review.get("languageCode") or "en",
                    })
        except httpx.RequestError as e:
            logger.debug("FactCheck request error: %s", e)

    # Also try Tamil-language search for the same query (Fact Crescendo Tamil etc.)
    if queries:
        try:
            r = httpx.get(
                API_URL,
                params={
                    "key": api_key,
                    "query": queries[0],
                    "languageCode": "ta",
                    "maxAgeDays": 30,
                    "pageSize": 3,
                },
                timeout=10.0,
            )
            if r.status_code == 200:
                for c in r.json().get("claims", []) or []:
                    for review in (c.get("claimReview") or [])[:1]:
                        url = review.get("url")
                        if not url or url in seen_urls:
                            continue
                        seen_urls.add(url)
                        results.append({
                            "publisher": (review.get("publisher") or {}).get("name") or "?",
                            "publisher_site": (review.get("publisher") or {}).get("site") or "",
                            "url": url,
                            "claim": (c.get("text") or "")[:300],
                            "rating": review.get("textualRating") or "",
                            "review_date": review.get("reviewDate") or "",
                            "language": "ta",
                        })
        except httpx.RequestError as e:
            logger.debug("FactCheck Tamil request error: %s", e)

    return results[:8]

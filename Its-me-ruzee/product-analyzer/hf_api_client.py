"""
HF Inference API client with rate limiting for free tier.

Uses httpx directly with DoH DNS fallback for reliable API calls.
Endpoint: router.huggingface.co (api-inference.huggingface.co deprecated)

Free tier constraints:
  - ~1000 requests/day
  - Rate limited (429s if too fast)
  - Cold starts: 20-60s for first request per model

Strategy:
  - Token bucket rate limiter: 10 requests/min max
  - 6-second minimum between requests
  - Exponential backoff on 429
  - Daily usage counter
"""

import os
import time
import logging
import threading
import socket
from io import BytesIO
from typing import Optional

from PIL import Image

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# DNS resolution fix — DoH fallback
# ─────────────────────────────────────────────────────────────
_DNS_CACHE: dict[str, str] = {}
_original_getaddrinfo = socket.getaddrinfo


def _resolve_via_doh(hostname: str) -> str:
    """Resolve hostname via DNS-over-HTTPS (Google) when system DNS fails."""
    import httpx as _httpx
    if hostname in _DNS_CACHE:
        return _DNS_CACHE[hostname]
    try:
        resp = _httpx.get(
            f"https://dns.google/resolve?name={hostname}&type=A",
            timeout=5,
        )
        data = resp.json()
        answers = data.get("Answer", [])
        if not answers:
            raise ValueError(f"No DNS records for {hostname}")
        ip = answers[0]["data"]
        _DNS_CACHE[hostname] = ip
        logger.info(f"Resolved {hostname} via DoH: {ip}")
        return ip
    except Exception as e:
        logger.error(f"DoH resolution failed for {hostname}: {e}")
        raise


def _patched_getaddrinfo(host, port, *args, **kwargs):
    """Patched getaddrinfo that falls back to DoH on failure."""
    try:
        return _original_getaddrinfo(host, port, *args, **kwargs)
    except socket.gaierror:
        if isinstance(port, int):
            ip = _resolve_via_doh(host)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, port))]
        raise


socket.getaddrinfo = _patched_getaddrinfo


# ─────────────────────────────────────────────────────────────
# Rate Limiter — Token Bucket
# ─────────────────────────────────────────────────────────────
class RateLimiter:
    """Thread-safe token bucket rate limiter."""

    def __init__(
        self,
        min_interval: float = 6.0,
        max_per_minute: int = 10,
        max_per_day: int = 950,
    ):
        self.min_interval = min_interval
        self.max_per_minute = max_per_minute
        self.max_per_day = max_per_day

        self._last_request = 0.0
        self._minute_timestamps: list[float] = []
        self._daily_count = 0
        self._daily_reset = self._today()
        self._lock = threading.Lock()

    @staticmethod
    def _today() -> str:
        return time.strftime("%Y-%m-%d", time.localtime())

    def wait_if_needed(self):
        """Block until a request can be made."""
        with self._lock:
            today = self._today()
            if today != self._daily_reset:
                self._daily_count = 0
                self._daily_reset = today
                logger.info("Daily API counter reset")

            if self._daily_count >= self.max_per_day:
                raise RuntimeError(f"Daily API limit reached ({self.max_per_day}).")

            now = time.time()
            cutoff = now - 60
            self._minute_timestamps = [
                ts for ts in self._minute_timestamps if ts > cutoff
            ]

            if len(self._minute_timestamps) >= self.max_per_minute:
                wait_until = self._minute_timestamps[0] + 60
                sleep_time = wait_until - now
                if sleep_time > 0:
                    logger.info(f"Rate limit: sleeping {sleep_time:.1f}s")
                    time.sleep(sleep_time)
                    now = time.time()

            elapsed = now - self._last_request
            if elapsed < self.min_interval:
                sleep_time = self.min_interval - elapsed
                logger.debug(f"Min interval: sleeping {sleep_time:.1f}s")
                time.sleep(sleep_time)

            now = time.time()
            self._last_request = now
            self._minute_timestamps.append(now)
            self._daily_count += 1

    def backoff_sleep(self, attempt: int, retry_after: Optional[float] = None):
        if retry_after and retry_after > 0:
            sleep_time = retry_after
        else:
            sleep_time = min(30.0, 2 ** attempt)
        logger.info(f"Backoff: sleeping {sleep_time:.1f}s (attempt {attempt})")
        time.sleep(sleep_time)

    def get_status(self) -> dict:
        with self._lock:
            now = time.time()
            cutoff = now - 60
            recent = [ts for ts in self._minute_timestamps if ts > cutoff]
            return {
                "daily_count": self._daily_count,
                "daily_limit": self.max_per_day,
                "daily_remaining": self.max_per_day - self._daily_count,
                "per_minute_count": len(recent),
                "per_minute_limit": self.max_per_minute,
                "min_interval": self.min_interval,
            }


_rate_limiter = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    return _rate_limiter


# ─────────────────────────────────────────────────────────────
# HF Inference API Client (httpx + DoH)
# ─────────────────────────────────────────────────────────────
MAX_RETRIES = 4
API_BASE = "https://router.huggingface.co/hf-inference"

# Models (verified supported on router.huggingface.co)
NSFW_TEXT_MODEL = "unitary/toxic-bert"           # toxicity: toxic, obscene, insult, identity_hate, threat
NSFW_IMAGE_MODEL = "Falconsai/nsfw_image_detection"  # nsfw vs safe


def _get_token() -> str:
    """Get HF token from environment."""
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if not token:
        try:
            from huggingface_hub import HfFolder
            token = HfFolder.get_token()
        except Exception:
            pass
    if not token:
        raise RuntimeError("HF_TOKEN not set")
    return token


def _api_request(model: str, payload: dict, timeout: int = 120) -> dict:
    """
    Make a request to HF Inference API with rate limiting and retries.
    Uses router.huggingface.co with DoH DNS fallback.
    """
    import httpx

    token = _get_token()
    url = f"{API_BASE}/models/{model}"
    headers = {"Authorization": f"Bearer {token}"}

    last_error = None
    for attempt in range(MAX_RETRIES):
        _rate_limiter.wait_if_needed()

        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(url, json=payload, headers=headers)

            if response.status_code == 200:
                return response.json()

            if response.status_code == 503:
                try:
                    body = response.json()
                    wait_time = body.get("estimated_time", 30)
                except Exception:
                    wait_time = 30
                logger.info(f"Model {model} loading, waiting {wait_time:.0f}s")
                _rate_limiter.backoff_sleep(attempt, retry_after=min(wait_time, 90))
                continue

            if response.status_code == 429:
                retry_after = None
                if "Retry-After" in response.headers:
                    try:
                        retry_after = float(response.headers["Retry-After"])
                    except ValueError:
                        pass
                logger.warning(f"Rate limited on {model} (attempt {attempt + 1})")
                _rate_limiter.backoff_sleep(attempt, retry_after=retry_after)
                continue

            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
            logger.error(f"API error: {last_error}")
            _rate_limiter.backoff_sleep(attempt)

        except httpx.TimeoutException:
            last_error = f"Timeout after {timeout}s"
            logger.error(f"Request timeout: {model}")
            _rate_limiter.backoff_sleep(attempt)

        except Exception as e:
            last_error = str(e)
            logger.error(f"Request error: {last_error}")
            _rate_limiter.backoff_sleep(attempt)

    raise RuntimeError(f"HF API failed after {MAX_RETRIES} retries: {last_error}")


def _fetch_image_from_url(url: str, timeout: int = 20) -> Optional[bytes]:
    """Download image bytes from URL."""
    import httpx
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ProductAnalyzer/1.0)"},
            )
            resp.raise_for_status()
            return resp.content
    except Exception as e:
        logger.error(f"Failed to fetch image {url}: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# Public API Functions
# ─────────────────────────────────────────────────────────────
NSFW_TEXT_THRESHOLD = 0.85
NSFW_IMAGE_THRESHOLD = 0.80


def classify_text_nsfw(text: str) -> dict:
    """
    Layer 2: Classify text toxicity via unitary/toxic-bert.

    toxic-bert returns: [{"label": "toxic", "score": 0.95}, {"label": "obscene", ...}, ...]
    We flag if ANY toxic category score exceeds threshold.
    """
    if not text or not text.strip():
        return {"flagged": False, "label": "SFW", "score": 0.0, "reason": "Empty text", "error": None}

    try:
        result = _api_request(NSFW_TEXT_MODEL, {"inputs": text[:2048]}, timeout=60)

        # toxic-bert returns: [[{"label": "toxic", "score": 0.95}, ...]]
        # or: [{"label": "toxic", "score": 0.95}, ...]
        if isinstance(result, list) and len(result) > 0:
            # Handle nested list (some models wrap in extra list)
            scores = result[0] if isinstance(result[0], list) else result

            # Find all toxic categories
            toxic_categories = ["toxic", "obscene", "insult", "identity_hate", "threat"]
            max_toxic_score = 0.0
            max_toxic_label = "SFW"
            flagged = False

            for entry in scores:
                label = entry.get("label", "").lower()
                score = entry.get("score", 0.0)
                if label in toxic_categories and score > max_toxic_score:
                    max_toxic_score = score
                    max_toxic_label = label

            flagged = max_toxic_score >= NSFW_TEXT_THRESHOLD

            return {
                "flagged": flagged,
                "label": max_toxic_label.upper(),
                "score": round(max_toxic_score, 4),
                "reason": f"Text classified as {max_toxic_label} with {max_toxic_score:.0%} confidence" if flagged else "Text passed toxicity check",
                "error": None,
            }

        return {"flagged": False, "label": "SFW", "score": 0.0, "reason": "Unexpected response", "error": str(result)[:200]}

    except Exception as e:
        logger.error(f"Text classification failed: {e}")
        return {"flagged": False, "label": "ERROR", "score": 0.0, "reason": "Text classifier unavailable", "error": str(e)}


def classify_image_nsfw(image_bytes: bytes) -> dict:
    """Layer 4: Classify image as NSFW."""
    import base64
    try:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        result = _api_request(
            NSFW_IMAGE_MODEL,
            {"inputs": f"data:image/jpeg;base64,{b64}"},
            timeout=90,
        )

        if isinstance(result, list) and len(result) > 0:
            nsfw_entry = next(
                (r for r in result if r.get("label", "").lower() == "nsfw"),
                result[0],
            )
            score = nsfw_entry.get("score", 0.0)
            flagged = score >= NSFW_IMAGE_THRESHOLD

            return {
                "flagged": flagged,
                "score": round(score, 4),
                "reason": f"Image classified as NSFW ({score:.0%} confidence)" if flagged else "Image passed NSFW check",
                "error": None,
            }

        return {"flagged": False, "score": 0.0, "reason": "Unexpected response", "error": str(result)[:200]}

    except Exception as e:
        logger.error(f"Image classification failed: {e}")
        return {"flagged": False, "score": 0.0, "reason": "Image classifier unavailable", "error": str(e)}


def classify_images_from_urls(image_urls: list) -> dict:
    """Layer 4: Check all product images for NSFW content."""
    flagged_images = []

    for url in image_urls:
        image_bytes = _fetch_image_from_url(url)
        if image_bytes is None:
            continue

        result = classify_image_nsfw(image_bytes)
        if result["flagged"]:
            flagged_images.append({
                "url": url,
                "score": result["score"],
                "reason": result["reason"],
            })
            return {
                "flagged": True,
                "flagged_images": flagged_images,
                "reason": f"{len(flagged_images)} image(s) flagged as NSFW",
            }

    return {"flagged": False, "flagged_images": [], "reason": "All images passed"}

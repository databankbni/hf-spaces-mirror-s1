"""
Product Analyzer — Multi-layer content moderation pipeline.

Layer 1: Keyword matching         (LOCAL, instant, no API calls)
Layer 2: NSFW text classifier     (HF Inference API — michellejieli/NSFW_text_classifier)
Layer 3: OCR → keyword check      (HF Inference API — Salesforce/blip-image-captioning-large)
Layer 4: NSFW image classifier    (HF Inference API — Falconsai/nsfw_image_detection)

Layer 1 runs locally for instant feedback.
Layers 2-4 use HF Inference API (free tier) — queued with rate limiting.
"""

import re
import json
import unicodedata
import logging
from pathlib import Path

from hf_api_client import (
    classify_text_nsfw,
    classify_images_from_urls,
    get_rate_limiter,
)

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "config" / "prohibited.json"


# ── Config helpers ────────────────────────────────────────────────────────────
def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def flatten_terms(data) -> list:
    if isinstance(data, list):
        return data
    terms = []
    if isinstance(data, dict):
        for val in data.values():
            if isinstance(val, list):
                terms.extend(val)
            elif isinstance(val, dict):
                terms.extend(flatten_terms(val))
    return terms


def normalize(text: str, leet_map: dict) -> str:
    text = text.lower().strip()
    text = unicodedata.normalize("NFKD", text)
    for symbol, letter in leet_map.items():
        text = text.replace(symbol, letter)
    text = re.sub(r"(?<=[a-z0-9])([\.\-\_]+)(?=[a-z0-9])", "", text)
    text = re.sub(r"[^a-z0-9\s஀-௿඀-෿]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ── Layer 1: keyword matching (LOCAL, instant) ───────────────────────────────
def layer1_check(text: str, config: dict) -> dict:
    leet_map = config.get("leet_map", {})
    normalized = normalize(text, leet_map)
    matched_terms = []
    matched_categories = []
    skip_keys = {"leet_map", "spacing_patterns"}

    for category, data in config.items():
        if category in skip_keys:
            continue
        for term in flatten_terms(data):
            term_lower = term.lower().strip()
            if not term_lower:
                continue
            if any(ord(c) > 127 for c in term_lower):
                if term_lower in text.lower():
                    matched_terms.append(term)
                    if category not in matched_categories:
                        matched_categories.append(category)
            else:
                pattern = r"\b" + re.escape(term_lower) + r"\b"
                if re.search(pattern, normalized):
                    matched_terms.append(term)
                    if category not in matched_categories:
                        matched_categories.append(category)

    return {
        "flagged": len(matched_terms) > 0,
        "matched_terms": list(set(matched_terms)),
        "matched_categories": list(set(matched_categories)),
    }


# ── Layer 2: NSFW text classifier (HF Inference API) ────────────────────────
def layer2_text_check(text: str) -> dict:
    """
    Classify product text via HF Inference API.
    Handles semantic adult content that keyword matching misses.
    """
    if not text or not text.strip():
        return {"flagged": False, "label": "SFW", "score": 0.0, "reason": "Empty text"}

    result = classify_text_nsfw(text)
    return {
        "flagged": result["flagged"],
        "label": result.get("label", "SFW"),
        "score": result.get("score", 0.0),
        "reason": result.get("reason", ""),
        "error": result.get("error"),
    }


# ── Layer 3: NSFW image classifier (HF Inference API) ───────────────────────
def layer3_image_check(image_urls: list) -> dict:
    """
    Check product images for NSFW content via HF Inference API.
    """
    if not image_urls:
        return {"flagged": False, "flagged_images": [], "reason": "No images to check"}

    return classify_images_from_urls(image_urls)


# ── Main entry point ──────────────────────────────────────────────────────────
def analyze_product(product: dict) -> dict:
    """
    Run the full analysis pipeline on a product.

    Layer 1 (keyword) runs locally for instant feedback.
    Layers 2-4 are designed to be called from the queue manager
    after Layer 1 passes.
    """
    config = load_config()

    name = str(product.get("name", ""))
    description = str(product.get("description", ""))
    category = str(product.get("category", ""))
    google_cat = str(product.get("google_product_category", ""))
    slug = str(product.get("slug", ""))
    image_urls = product.get("image_urls", [])

    text_blob = " ".join([name, description, category, google_cat, slug])

    # ── Layer 1: keyword check (LOCAL, instant) ─────────────────────────────
    l1 = layer1_check(text_blob, config)
    if l1["flagged"]:
        return {
            "flagged": True,
            "flag_type": "prohibited_terms",
            "severity": "high",
            "reason": f"Prohibited terms detected: {', '.join(l1['matched_terms'])}",
            "meta": {
                "terms": l1["matched_terms"],
                "categories": l1["matched_categories"],
                "layer_triggered": "layer1_text",
                "confidence": "high",
            },
        }

    # Layers 2-4 are called separately by queue_manager after Layer 1 passes.
    # This function returns "passed" to signal the queue manager to continue.
    return {
        "flagged": False,
        "flag_type": None,
        "severity": None,
        "reason": "Layer 1 passed — queued for API analysis",
        "meta": {
            "terms": [],
            "categories": [],
            "layer_triggered": None,
            "confidence": "high",
            "queued_for_api": True,
        },
    }


def run_api_layers(product: dict) -> dict:
    """
    Run Layers 2-4 (API-based) on a product that passed Layer 1.
    Called by queue_manager after Layer 1 passes.

    Returns the final analysis result.
    """
    config = load_config()

    name = str(product.get("name", ""))
    description = str(product.get("description", ""))
    category = str(product.get("category", ""))
    google_cat = str(product.get("google_product_category", ""))
    slug = str(product.get("slug", ""))
    image_urls = product.get("image_urls", [])

    text_blob = " ".join([name, description, category, google_cat, slug])

    # ── Layer 2: NSFW text classifier (API) ─────────────────────────────────
    l2 = layer2_text_check(text_blob)
    if l2["flagged"]:
        return {
            "flagged": True,
            "flag_type": "nsfw_text",
            "severity": "high",
            "reason": l2["reason"],
            "meta": {
                "terms": [],
                "categories": [],
                "layer_triggered": "layer2_text_classifier",
                "confidence": "high",
                "score": l2["score"],
            },
        }

    # ── Layer 3: NSFW image classifier (API) ───────────────────────────────
    if image_urls:
        l3 = layer3_image_check(image_urls)
        if l3["flagged"]:
            return {
                "flagged": True,
                "flag_type": "nsfw_image",
                "severity": "high",
                "reason": l3["reason"],
                "meta": {
                    "terms": [],
                    "categories": [],
                    "layer_triggered": "layer3_image_classifier",
                    "confidence": "high",
                    "flagged_images": l3["flagged_images"],
                },
            }

    # ── All clear ───────────────────────────────────────────────────────────
    return {
        "flagged": False,
        "flag_type": None,
        "severity": None,
        "reason": "Passed all checks",
        "meta": {
            "terms": [],
            "categories": [],
            "layer_triggered": None,
            "confidence": "high",
        },
    }

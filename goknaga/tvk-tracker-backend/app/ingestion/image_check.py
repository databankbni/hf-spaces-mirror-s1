"""
AI-generated image detection pipeline.

Multi-layer approach (no single layer is trusted alone):

  Layer 1 — Open-source AI-detection via HuggingFace Inference API.
            Model: Organika/sdxl-detector (free, public).
            Output: ai_suspicion 0.0-1.0.

  Layer 2 — (deferred) Reverse image search to find earliest source.
            Requires TinEye or Google Vision API key.

  Layer 3 — Human admin review. NOTHING is published as "FAKE" without
            an admin verifying. AI verdicts are advisory only.

Set HUGGINGFACE_API_KEY in env to enable Layer 1.
Without it, images are saved but flagged 'not_checked'.
"""
import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

# Public model — sdxl-detector classifies "artificial" vs "human" generated
HF_MODEL = "Organika/sdxl-detector"
HF_INFERENCE_URL = f"https://api-inference.huggingface.co/models/{HF_MODEL}"


def _detect_ai_generated(image_url: str) -> dict:
    """Run HuggingFace inference. Returns {ai_suspicion, raw_scores, error?}."""
    if not settings.huggingface_api_key:
        return {"ai_suspicion": None, "status": "no_api_key"}

    try:
        # Fetch image bytes (HF inference accepts URL OR binary)
        img_resp = httpx.get(image_url, timeout=15, follow_redirects=True)
        if img_resp.status_code != 200:
            return {"ai_suspicion": None, "status": "image_fetch_failed", "code": img_resp.status_code}

        # Send to HF
        r = httpx.post(
            HF_INFERENCE_URL,
            headers={
                "Authorization": f"Bearer {settings.huggingface_api_key}",
                "Content-Type": "application/octet-stream",
            },
            content=img_resp.content,
            timeout=30,
        )
        if r.status_code == 503:
            # Model warming up — pretty common with free HF inference
            return {"ai_suspicion": None, "status": "model_loading"}
        if r.status_code != 200:
            return {"ai_suspicion": None, "status": "hf_error", "code": r.status_code, "body": r.text[:200]}

        scores = r.json()
        if not isinstance(scores, list):
            return {"ai_suspicion": None, "status": "unexpected_response", "raw": str(scores)[:200]}

        # sdxl-detector returns [{label: "artificial", score: x}, {label: "human", score: y}]
        ai_score = next((s["score"] for s in scores if s.get("label", "").lower() in ("artificial", "ai", "fake")), None)
        return {
            "ai_suspicion": ai_score,
            "status": "checked",
            "raw_scores": scores,
        }

    except httpx.RequestError as e:
        return {"ai_suspicion": None, "status": "request_error", "error": str(e)[:200]}


def enqueue_images(db, incident_id: str, image_urls: list[str]) -> None:
    """Check each image and persist verdicts on the incident.

    Skips images > 5. Always best-effort — never blocks the article pipeline.
    """
    if not image_urls:
        return

    verdicts = []
    for url in image_urls[:5]:
        detection = _detect_ai_generated(url)
        suspicion = detection.get("ai_suspicion")
        verdicts.append({
            "url": url,
            "ai_suspicion": suspicion,
            "status": detection.get("status"),
            "needs_review": (suspicion or 0) >= 0.6,
            "verdict": "pending",  # only admin can set 'verified_fake' or 'verified_real'
        })

    # Persist verdicts (jsonb column on incidents)
    try:
        db.table("incidents").update({"image_verdicts": verdicts}).eq("id", incident_id).execute()
        flagged = sum(1 for v in verdicts if v.get("needs_review"))
        if flagged:
            logger.warning(
                "Incident %s has %d image(s) flagged for review (AI-generation suspected)",
                incident_id, flagged,
            )
    except Exception as e:
        logger.warning("Persist image verdicts failed: %s", e)

from __future__ import annotations

import logging
import os
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.config import require_api_key
from .anti_manipulation import AntiManipulationEngine
from .reputation_scorer import ReputationScorer

if TYPE_CHECKING:
    from .sentiment_analyzer import SentimentAnalyzer

logger = logging.getLogger(__name__)


class ReviewSentimentRequest(BaseModel):
    review_text: str = Field(..., min_length=5, max_length=4000)
    recent_submissions: list[str] | None = None
    ip_hash: str | None = None


class SentimentInferenceService:
    def __init__(self):
        self._lock = Lock()
        self._ready = False
        self._analyzer: "SentimentAnalyzer | None" = None
        self._anti_engine = AntiManipulationEngine()
        # alpha=0 keeps single-comment score aligned with analyzer output while
        # still using the standalone reputation scoring module.
        self._reputation_scorer = ReputationScorer(
            bayesian_alpha=0,
            min_calibrated_confidence=0.0,
        )

    def _model_dir(self) -> Path:
        project_root = Path(__file__).resolve().parents[2]
        candidates = [
            project_root / "app" / "model_output_v3",
            project_root / "model_output_v3" / "model_output_v3",
            project_root / "model_output_v3",
        ]

        for candidate in candidates:
            if (candidate / "best.pt").exists():
                return candidate

        # Return the primary expected path to keep downstream error messages clear.
        return candidates[0]

    def _download_from_hf(self, model_dir: Path) -> None:
        """Pull the fine-tuned checkpoint from Hugging Face Hub on first use.

        The checkpoint (~254MB) is too large to commit to git, so it's hosted
        on HF Hub and fetched here instead of at deploy time — this repo has
        no Docker build step to hook a download into on a plain Render web
        service, so this runs lazily the first time the endpoint is hit.
        """
        repo_id = os.getenv("HF_MODEL_REPO")
        if not repo_id:
            return

        from huggingface_hub import snapshot_download

        logger.info("Downloading sentiment model from Hugging Face Hub: %s", repo_id)
        snapshot_download(repo_id=repo_id, local_dir=str(model_dir))
        logger.info("Sentiment model download complete: %s", model_dir)

    def _load(self):
        from .sentiment_analyzer import SentimentAnalyzer

        model_dir = self._model_dir()
        weight_path = model_dir / "best.pt"

        if not weight_path.exists():
            self._download_from_hf(model_dir)

        if not weight_path.exists():
            raise RuntimeError(f"Model files missing at {weight_path}")

        # Use the same analyzer implementation as standalone workflow to keep
        # API and script predictions fully aligned.
        self._analyzer = SentimentAnalyzer(model_dir=str(model_dir), device="cpu")
        self._ready = True

    def ensure_ready(self):
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            self._load()

    def analyze(
        self,
        review_text: str,
        recent_submissions: list[str] | None = None,
        ip_hash: str | None = None,
    ) -> Dict[str, object]:
        self.ensure_ready()
        assert self._analyzer is not None

        prediction = self._analyzer.predict(review_text)
        raw_overall_score = float(prediction["overall_rating"])
        raw_aspect_scores = {
            key: float(value)
            for key, value in prediction.get("aspect_scores", {}).items()
        }
        base_signal = float(prediction.get("sentiment_signal", 0.0))
        confidence = float(prediction.get("confidence", 0.0))

        anti_result = self._anti_engine.check_submission(
            text=review_text,
            ip_hash=ip_hash or "",
            recent_submissions=recent_submissions or [],
            sentiment_confidence=confidence,
        )

        weight_factor = float(anti_result.get("weight_factor", 1.0))

        reputation_projection = self._reputation_scorer.compute_reputation_score(
            sentiments=[{"signal": base_signal, "confidence": confidence}],
            scale="5star",
        )

        # API primary scores must stay identical to standalone model output.
        overall_score = raw_overall_score

        return {
            "overall_score": round(overall_score, 3),
            "aspect_scores": {k: round(v, 3) for k, v in raw_aspect_scores.items()},
            "rating_min": 1.0,
            "rating_max": 5.0,
            "label": prediction.get("label"),
            "confidence": round(confidence, 3),
            "sentiment_signal": round(base_signal, 3),
            "raw_sentiment": {
                "overall_score": round(raw_overall_score, 3),
                "aspect_scores": {k: round(v, 3) for k, v in raw_aspect_scores.items()},
                "sentiment_signal": round(base_signal, 3),
            },
            "anti_manipulation": {
                "is_suspicious": bool(anti_result.get("is_suspicious", False)),
                "flags": anti_result.get("flags", []),
                "weight_factor": round(weight_factor, 3),
                "recommendation": anti_result.get("recommendation", "approve"),
                "details": anti_result.get("details", {}),
            },
            "reputation_projection": {
                "score": round(float(reputation_projection.get("score", overall_score)), 3),
                "ci_lower": round(float(reputation_projection.get("ci_lower", 1.0)), 3),
                "ci_upper": round(float(reputation_projection.get("ci_upper", 5.0)), 3),
                "sample_size": int(reputation_projection.get("sample_size", 0)),
                "sentiment_signal": round(float(reputation_projection.get("sentiment_signal", base_signal)), 3),
                "scale": reputation_projection.get("scale", "5star"),
            },
            "model": "model_output_v3",
        }


_service = SentimentInferenceService()
router = APIRouter(dependencies=[Depends(require_api_key)])


@router.post("/analyze-review-sentiment")
def analyze_review_sentiment(payload: ReviewSentimentRequest):
    text = payload.review_text.strip()
    if len(text) < 5:
        raise HTTPException(status_code=400, detail="review_text is too short")

    try:
        return _service.analyze(
            text,
            recent_submissions=payload.recent_submissions,
            ip_hash=payload.ip_hash,
        )
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Sentiment analysis failed: {error}")

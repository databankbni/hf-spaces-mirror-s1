"""PIRD REST API (Hugging Face Spaces, docker SDK).

Serves the trained PIRD checkpoint (./pird_deploy) as a JSON API for external
front-ends. CORS is open so the Next.js site (Vercel) can call it from the browser.
"""
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from pird.detectors.pird import PIRDDetector

MIN_WORDS = 20
MAX_CHARS = 20000

detector = PIRDDetector(os.environ.get("PIRD_CKPT", "pird_deploy"))

app = FastAPI(
    title="PIRD API",
    description="Paraphrase-robust, calibrated AI-generated-text detection.",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class PredictRequest(BaseModel):
    text: str


@app.get("/")
def root():
    return {
        "service": "PIRD — Paraphrase-Robust AI-Text Detector",
        "status": "ok",
        "usage": "POST /predict with JSON body {\"text\": \"...\"} (>= 20 words)",
        "disclaimer": ("Research demo. Predictions are probabilistic and not infallible; "
                       "do not use as sole evidence of misconduct."),
    }


@app.post("/predict")
def predict(req: PredictRequest):
    text = (req.text or "").strip()
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
    n_words = len(text.split())
    if n_words < MIN_WORDS:
        raise HTTPException(
            status_code=422,
            detail=f"Please provide at least {MIN_WORDS} words for a reliable estimate "
                   f"(got {n_words}).",
        )
    p = float(detector.predict_proba([text])[0])
    return {
        "p_ai": round(p, 4),
        "label": "ai" if p >= 0.5 else "human",
        "words": n_words,
        "calibrated": True,
    }

from fastapi import FastAPI
from .utils import label_cols
from datetime import datetime
from pydantic import BaseModel
from typing import Dict, List
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from huggingface_hub import hf_hub_download
import json
import torch
STARTUP_TIME = datetime.now()
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

model_name = "lakresi/toxic-comment-moderator"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForSequenceClassification.from_pretrained(model_name)

file_path = hf_hub_download(
    repo_id=model_name,
    filename="thresholds.json"
)
with open(file_path) as f:
  thresholds = json.load(f)

model.eval()

def predict(text: str):
    inputs = tokenizer(
        text,
        return_tensors="pt",
        truncation=True,
        padding="max_length",
        max_length=512
    )

    with torch.no_grad():
        logits = model(**inputs).logits

    probs = torch.sigmoid(logits).squeeze().tolist()

    return{
        label: {
            "probability":round(prob, 4),
            "flagged": prob>=thresholds[label]
        } for label, prob in zip(label_cols, probs)
    }

class Text(BaseModel):
    text:str

class ClassificationResponse(BaseModel):
    is_toxic: bool
    confidence: float
    categories: Dict[str, float]
    flagged_categories: List[str]
    processing_time_ms: float

app = FastAPI()

@app.get("/")
def api_info():
    return {
  "name": "Toxic Comment Moderation API",
  "version": "1.0.0",
  "description": "Multi-label toxic comment classifier fine-tuned on the Jigsaw dataset. Detects six categories of toxic content in text.",
  "model": {
    "base": "distilbert-base-uncased",
    "trained_on": "Jigsaw Toxic Comment Classification Dataset",
    "categories": [
      "toxic",
      "severe_toxic",
      "obscene",
      "threat",
      "insult",
      "identity_hate"
    ],
    "performance": {
      "f1_macro": 0.687,
      "roc_auc": 0.987
    }
  },
  "endpoints": {
    "classify": "POST /classify",
    "health": "GET /health",
    "docs": "GET /docs"
  },
  "huggingface_model": "lakresi/toxic-comment-moderator"
}

@app.post("/classify/", response_model=ClassificationResponse)
async def classifier(text: Text):
    inference_start_time = datetime.now()
    out = predict(text.text)
    toxic = any(v["flagged"] for v in out.values())
    probabilities = {}
    flagged = []
    for k, v in out.items():
        probabilities[k] = v["probability"]
        if v["flagged"]:
             flagged.append(k)
    confidence = max(probabilities.values())
    processing_time_ms = (datetime.now() - inference_start_time).total_seconds() * 1000

    return {
        "is_toxic":toxic,
        "confidence":confidence,
        "categories":probabilities,
        "flagged_categories":flagged,
        "processing_time_ms":processing_time_ms
    }



@app.get("/health")
def app_health():
    UPTIME = (datetime.now() - STARTUP_TIME).total_seconds()
    return {
  "status": "healthy",
  "model_loaded": True,
  "device": DEVICE,
  "uptime_seconds": UPTIME,
  "version": "1.0.0"
}

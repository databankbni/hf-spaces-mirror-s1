"""Inference wrapper for the five-head DistilBERT regression model."""

import json
import logging
from pathlib import Path
from typing import Dict, List

import torch
from torch import nn
from transformers import DistilBertModel, DistilBertTokenizerFast


logger = logging.getLogger(__name__)

RATING_MIN = 1.0
RATING_MAX = 5.0
DEFAULT_BASE_MODEL = "distilbert-base-uncased"
DEFAULT_MAX_LEN = 384
DEFAULT_DROPOUT = 0.25
OUTPUT_NAMES = [
    "overall_rating",
    "work_life_balance",
    "company_culture",
    "career_opportunities",
    "salary_benefits",
]


def build_review_input(text: str) -> str:
    return f"[REVIEW] {str(text).strip()}"


class DistilBertMultiHeadRegressor(nn.Module):
    def __init__(self, base_model: str, dropout: float = DEFAULT_DROPOUT):
        super().__init__()
        self.encoder = DistilBertModel.from_pretrained(base_model)
        hidden_size = self.encoder.config.hidden_size
        self.dropout = nn.Dropout(dropout)
        self.heads = nn.ModuleDict({name: nn.Linear(hidden_size, 1) for name in OUTPUT_NAMES})

    @staticmethod
    def scale_output(logit: torch.Tensor) -> torch.Tensor:
        return torch.sigmoid(logit) * (RATING_MAX - RATING_MIN) + RATING_MIN

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> Dict[str, torch.Tensor]:
        encoded = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
        pooled = self.dropout(encoded.last_hidden_state[:, 0])
        return {name: self.scale_output(head(pooled).squeeze(-1)) for name, head in self.heads.items()}


class SentimentAnalyzer:
    """Loads the trained regression model and returns five continuous ratings."""

    def __init__(
        self,
        model_dir: str = "model_output_v3",
        base_model: str = DEFAULT_BASE_MODEL,
        device: str | None = None,
        max_len: int = DEFAULT_MAX_LEN,
    ):
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"

        self.model_dir = model_dir
        self.device = torch.device(device)
        self.max_len = max_len

        config_path = Path(model_dir) / "config.json"
        weights_path = Path(model_dir) / "best.pt"
        if not weights_path.exists():
            raise FileNotFoundError(f"Missing trained weights at {weights_path}")

        config = {}
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as handle:
                config = json.load(handle)

        self.base_model = config.get("base_model", base_model)
        self.max_len = int(config.get("max_len", max_len))
        self.dropout = float(config.get("dropout", DEFAULT_DROPOUT))

        try:
            self.tokenizer = DistilBertTokenizerFast.from_pretrained(model_dir)
        except Exception:
            self.tokenizer = DistilBertTokenizerFast.from_pretrained(self.base_model)

        self.model = DistilBertMultiHeadRegressor(base_model=self.base_model, dropout=self.dropout)
        state_dict = torch.load(weights_path, map_location=self.device)
        self.model.load_state_dict(state_dict)
        self.model.to(self.device)
        self.model.eval()

    @staticmethod
    def _clip_rating(value: float) -> float:
        return float(max(RATING_MIN, min(RATING_MAX, value)))

    def _predict_batch(self, texts: List[str]) -> List[Dict[str, object]]:
        if not texts:
            return []

        encoded = self.tokenizer(
            [build_review_input(text) for text in texts],
            return_tensors="pt",
            truncation=True,
            padding=True,
            max_length=self.max_len,
        )
        encoded = {key: value.to(self.device) for key, value in encoded.items()}

        with torch.no_grad():
            outputs = self.model(**encoded)

        results = []
        for index, original_text in enumerate(texts):
            aspect_ratings = {
                name: self._clip_rating(outputs[name][index].item())
                for name in OUTPUT_NAMES
                if name != "overall_rating"
            }
            overall_rating = self._clip_rating(outputs["overall_rating"][index].item())
            sentiment_signal = max(-1.0, min(1.0, (overall_rating - 3.0) / 2.0))
            confidence = float(max(0.0, min(1.0, 1.0 - abs(overall_rating - 3.0) / 2.0)))
            label = "POSITIVE" if overall_rating >= 3.5 else "NEGATIVE" if overall_rating <= 2.5 else "NEUTRAL"

            result = {
                "text": original_text,
                "overall_rating": overall_rating,
                "work_life_balance": aspect_ratings["work_life_balance"],
                "company_culture": aspect_ratings["company_culture"],
                "career_opportunities": aspect_ratings["career_opportunities"],
                "salary_benefits": aspect_ratings["salary_benefits"],
                "aspect_ratings": aspect_ratings,
                "aspect_scores": aspect_ratings,
                "aspect_sentiments": {
                    name: max(-1.0, min(1.0, (score - 3.0) / 2.0))
                    for name, score in aspect_ratings.items()
                },
                "sentiment_signal": sentiment_signal,
                "confidence": confidence,
                "label": label,
            }
            results.append(result)

        return results

    def predict(self, text: str) -> Dict[str, object]:
        return self._predict_batch([text])[0]

    def batch_predict(self, texts: List[str]) -> List[Dict[str, object]]:
        return self._predict_batch(texts)

    def get_model_info(self) -> Dict[str, object]:
        return {
            "model_dir": self.model_dir,
            "base_model": self.base_model,
            "device": str(self.device),
            "max_len": self.max_len,
            "output_names": OUTPUT_NAMES,
            "num_parameters": sum(parameter.numel() for parameter in self.model.parameters()),
        }


def demo_sentiment_analysis() -> None:
    analyzer = SentimentAnalyzer(device="cpu")
    sample_comments = [
        "Amazing culture, love the team!",
        "Pay is low compared to competitors.",
        "Decent place to work overall.",
    ]

    results = analyzer.batch_predict(sample_comments)
    for index, result in enumerate(results, start=1):
        print(f"[{index}] {result['text']}")
        print(
            f"  overall={result['overall_rating']:.2f} | wlb={result['work_life_balance']:.2f} | "
            f"culture={result['company_culture']:.2f} | career={result['career_opportunities']:.2f} | "
            f"salary={result['salary_benefits']:.2f}"
        )


if __name__ == "__main__":
    demo_sentiment_analysis()
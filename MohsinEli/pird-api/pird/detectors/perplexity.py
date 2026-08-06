"""Perplexity baseline detector. Low perplexity under a proxy LM => more likely AI.

This is the simplest zero-shot baseline and the one whose paraphrase-fragility / non-native-bias
coupling we demonstrated in Phase 0. Score = -perplexity (higher = more AI)."""
from __future__ import annotations
import math
import numpy as np
from .base import Detector


class PerplexityDetector(Detector):
    name = "perplexity"

    def __init__(self, model_name: str = "gpt2", device: str | None = None, max_tokens: int = 512):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.max_tokens = max_tokens
        self.tok = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForCausalLM.from_pretrained(model_name).to(self.device).eval()

    def perplexity(self, text: str) -> float:
        if not text or not text.strip():
            return float("nan")
        ids = self.tok(text, return_tensors="pt", truncation=True,
                       max_length=self.max_tokens).input_ids.to(self.device)
        if ids.size(1) < 2:
            return float("nan")
        with self.torch.no_grad():
            loss = self.model(ids, labels=ids).loss
        ppl = math.exp(loss.item())
        return ppl if math.isfinite(ppl) else float("nan")

    def score(self, texts: list[str]) -> np.ndarray:
        # higher score = more AI => negative perplexity
        return np.array([-self.perplexity(t) for t in texts], dtype=float)

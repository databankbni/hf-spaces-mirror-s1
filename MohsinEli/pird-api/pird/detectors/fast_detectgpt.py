"""Fast-DetectGPT (Bao et al., 2023) — conditional probability curvature.

Analytic single-model form (sampling model = scoring model): using the model's full next-token
distribution we compute, per position, the observed log-prob vs its conditional mean and variance.
The standardized statistic d = (logp_obs - mu) / sigma is HIGH for machine text. We return d directly
(higher = more AI). Default proxy is gpt2 (Colab-cheap); use EleutherAI/gpt-neo-1.3B for a stronger
signal. arXiv:2310.05130
"""
from __future__ import annotations
import numpy as np
from .base import Detector


class FastDetectGPTDetector(Detector):
    name = "fast-detectgpt"

    def __init__(self, model_name: str = "gpt2", device: str | None = None, max_tokens: int = 512):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.max_tokens = max_tokens
        self.tok = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForCausalLM.from_pretrained(model_name).to(self.device).eval()

    def _curvature(self, text: str) -> float:
        torch = self.torch
        if not text or not text.strip():
            return float("nan")
        ids = self.tok(text, return_tensors="pt", truncation=True,
                       max_length=self.max_tokens).input_ids.to(self.device)
        if ids.size(1) < 3:
            return float("nan")
        with torch.no_grad():
            logits = self.model(ids).logits[:, :-1, :]          # predict tokens 1..L-1
            lp = torch.log_softmax(logits, dim=-1)              # [1, L-1, V]
            p = lp.exp()
            tgt = ids[:, 1:]                                    # [1, L-1]
            logp_tok = lp.gather(-1, tgt.unsqueeze(-1)).squeeze(-1)  # observed log-probs
            mu = (p * lp).sum(-1)                               # conditional mean (= -entropy)
            var = (p * lp.pow(2)).sum(-1) - mu.pow(2)           # conditional variance
            num = (logp_tok - mu).sum()
            den = var.sum().clamp_min(1e-8).sqrt()
            d = (num / den).item()
        return float(d)

    def score(self, texts: list[str]) -> np.ndarray:
        return np.array([self._curvature(t) for t in texts], dtype=float)

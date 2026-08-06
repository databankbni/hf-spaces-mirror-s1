"""Binoculars (Hans et al., ICML 2024) — log-perplexity / cross-perplexity.

Two models that SHARE a tokenizer/vocab: an "observer" and a "performer". The score
    B = logPPL_observer(text) / X-PPL(performer, observer)
is LOW for machine text. We return -B (higher = more AI).

Colab-friendly default pair: observer=gpt2, performer=distilgpt2 (same GPT-2 vocab). For the paper's
full strength use a base/instruct pair from one family (e.g. tiiuae/falcon-7b + falcon-7b-instruct)
if you have the GPU memory. arXiv:2401.12070
"""
from __future__ import annotations
import numpy as np
from .base import Detector


class BinocularsDetector(Detector):
    name = "binoculars"

    def __init__(self, observer: str = "gpt2", performer: str = "distilgpt2",
                 device: str | None = None, max_tokens: int = 512):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.max_tokens = max_tokens
        self.tok = AutoTokenizer.from_pretrained(observer)
        self.m_obs = AutoModelForCausalLM.from_pretrained(observer).to(self.device).eval()
        self.m_perf = AutoModelForCausalLM.from_pretrained(performer).to(self.device).eval()

    def _bino(self, text: str) -> float:
        torch = self.torch
        if not text or not text.strip():
            return float("nan")
        ids = self.tok(text, return_tensors="pt", truncation=True,
                       max_length=self.max_tokens).input_ids.to(self.device)
        if ids.size(1) < 3:
            return float("nan")
        with torch.no_grad():
            obs = self.m_obs(ids).logits[:, :-1, :]
            perf = self.m_perf(ids).logits[:, :-1, :]
            logp_obs = torch.log_softmax(obs, dim=-1)
            tgt = ids[:, 1:]
            log_ppl = -logp_obs.gather(-1, tgt.unsqueeze(-1)).squeeze(-1).mean()   # avg NLL (nats)
            p_perf = torch.softmax(perf, dim=-1)
            x_ppl = -(p_perf * logp_obs).sum(-1).mean()                            # cross-entropy
            b = (log_ppl / x_ppl.clamp_min(1e-8)).item()
        return float(b)

    def score(self, texts: list[str]) -> np.ndarray:
        # low Binoculars score = machine => negate so higher = more AI
        return np.array([-self._bino(t) for t in texts], dtype=float)

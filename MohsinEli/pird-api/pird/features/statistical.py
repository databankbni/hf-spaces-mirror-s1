"""Stream A — statistical / model-based features from a proxy LM.

A compact vector of the signals that zero-shot detectors rely on (perplexity, log-prob mean/variance
= burstiness, token entropy, GLTR-style rank fractions, Fast-DetectGPT curvature). PIRD includes them
so it can *use* this signal where reliable while the encoder + stylometric streams compensate where it
is fragile (paraphrase) or biased (non-native). Needs torch + a causal LM (default gpt2)."""
from __future__ import annotations
import math
import numpy as np

FEATURE_NAMES = [
    "mean_logp", "std_logp", "log_perplexity", "mean_entropy", "std_entropy",
    "top1_frac", "top10_frac", "fast_detectgpt_d",
]
N_FEATURES = len(FEATURE_NAMES)


class StatisticalFeatures:
    def __init__(self, model_name: str = "gpt2", device: str | None = None, max_tokens: int = 512):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.max_tokens = max_tokens
        self.tok = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForCausalLM.from_pretrained(model_name).to(self.device).eval()

    def features(self, text: str) -> np.ndarray:
        torch = self.torch
        if not text or not text.strip():
            return np.zeros(N_FEATURES, dtype=float)
        ids = self.tok(text, return_tensors="pt", truncation=True,
                       max_length=self.max_tokens).input_ids.to(self.device)
        if ids.size(1) < 3:
            return np.zeros(N_FEATURES, dtype=float)
        with torch.no_grad():
            logits = self.model(ids).logits[:, :-1, :]            # predict tokens 1..L-1
            lp = torch.log_softmax(logits, dim=-1)
            p = lp.exp()
            tgt = ids[:, 1:]
            true_logit = logits.gather(-1, tgt.unsqueeze(-1))     # [1, L-1, 1]
            logp_tok = lp.gather(-1, tgt.unsqueeze(-1)).squeeze(-1).squeeze(0)   # [L-1]
            ranks = (logits > true_logit).sum(-1).squeeze(0)      # # tokens ranked above the true one
            ent = -(p * lp).sum(-1).squeeze(0)                    # per-position entropy
            mu = (p * lp).sum(-1)
            var = (p * lp.pow(2)).sum(-1) - mu.pow(2)
            d = ((logp_tok.sum() - mu.sum()) / var.sum().clamp_min(1e-8).sqrt()).item()

            mean_logp = logp_tok.mean().item()
            feats = [
                mean_logp,
                logp_tok.std().item(),
                min(-mean_logp, 20.0),                            # log-perplexity, clipped
                ent.mean().item(),
                ent.std().item(),
                (ranks == 0).float().mean().item(),              # top-1 fraction
                (ranks < 10).float().mean().item(),              # top-10 fraction
                d,
            ]
        return np.array([f if math.isfinite(f) else 0.0 for f in feats], dtype=float)

    def matrix(self, texts: list[str]) -> np.ndarray:
        return np.vstack([self.features(t) for t in texts]) if texts \
            else np.zeros((0, N_FEATURES))

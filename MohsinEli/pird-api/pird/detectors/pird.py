"""PIRDDetector — wraps a trained PIRD checkpoint (encoder [+ fused A/C features], calibrated)."""
from __future__ import annotations
import json
import os
import numpy as np
from .base import Detector


class PIRDDetector(Detector):
    name = "pird"

    def __init__(self, ckpt_dir: str, device: str | None = None,
                 max_len: int | None = None, batch_size: int = 16):
        import torch
        from transformers import AutoTokenizer
        from ..model import PIRDModel
        self.torch = torch
        with open(os.path.join(ckpt_dir, "config.json")) as f:
            cfg = json.load(f)
        self.cfg = cfg
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.max_len = max_len or cfg.get("max_len", 256)
        self.batch_size = batch_size
        self.n_extra = cfg.get("n_extra", 0)
        self.temperature = cfg.get("temperature", 1.0) or 1.0
        self.tok = AutoTokenizer.from_pretrained(cfg["encoder"])
        self.model = PIRDModel(cfg["encoder"], n_extra=self.n_extra).to(self.device)
        sd = torch.load(os.path.join(ckpt_dir, "pird.pt"), map_location=self.device)
        self.model.load_state_dict(sd)
        self.model.eval()
        if self.n_extra:
            from ..features import CombinedFeatures, standardize
            self._standardize = standardize
            self.extractor = CombinedFeatures(cfg.get("stat_model", "gpt2"), device=self.device)
            self.mean = np.array(cfg["feat_mean"]); self.std = np.array(cfg["feat_std"])

    def score(self, texts: list[str]) -> np.ndarray:
        torch = self.torch
        if not texts:
            return np.zeros(0)
        extra_all = None
        if self.n_extra:
            extra_all = self._standardize(self.extractor.matrix(texts), self.mean, self.std)
        out = []
        for i in range(0, len(texts), self.batch_size):
            chunk = texts[i:i + self.batch_size]
            e = self.tok(chunk, return_tensors="pt", truncation=True,
                         max_length=self.max_len, padding=True)
            extra = (torch.tensor(extra_all[i:i + self.batch_size], dtype=torch.float).to(self.device)
                     if self.n_extra else None)
            with torch.no_grad():
                logits = self.model(e["input_ids"].to(self.device),
                                    e["attention_mask"].to(self.device), extra)
            out.append(np.atleast_1d(logits.detach().float().cpu().numpy()))
        return np.concatenate(out)

    def predict_proba(self, texts: list[str]) -> np.ndarray:
        # temperature-calibrated P(AI)
        return 1.0 / (1.0 + np.exp(-self.score(texts) / self.temperature))

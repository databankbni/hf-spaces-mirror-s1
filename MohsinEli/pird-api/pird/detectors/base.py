"""Detector interface. Every baseline and PIRD itself implements this."""
from __future__ import annotations
from abc import ABC, abstractmethod
import numpy as np


class Detector(ABC):
    name: str = "detector"

    @abstractmethod
    def score(self, texts: list[str]) -> np.ndarray:
        """Return an AI-ness score per text. HIGHER = more likely AI-generated.
        Scores need not be probabilities; calibration is handled separately."""
        ...

    def predict_proba(self, texts: list[str]) -> np.ndarray:
        """Optional calibrated P(AI) in [0,1]. Default: logistic squash of standardized scores
        (rough; replace with a fitted calibrator for the real 0-100% claim)."""
        s = np.asarray(self.score(texts), dtype=float)
        if s.size == 0:
            return s
        z = (s - np.nanmean(s)) / (np.nanstd(s) + 1e-8)
        return 1.0 / (1.0 + np.exp(-z))

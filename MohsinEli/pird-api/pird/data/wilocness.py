"""WI+LOCNESS (BEA-2019) loader — canonical package version.

Downloads the original Cambridge release and parses its per-CEFR JSON (HF mirrors are loading-script
datasets that modern `datasets`/datasets-server refuse to run). Filename leading letter = band:
A/B/C = non-native learners (W&I), N = native (LOCNESS). We use the original (uncorrected) text.
"""
from __future__ import annotations
import io
import json
import os
import random
import tarfile
import tempfile
from typing import Optional

_URL = "https://www.cl.cam.ac.uk/research/nl/bea2019st/data/wi+locness_v2.1.bea19.tar.gz"
_CACHE = os.path.join(tempfile.gettempdir(), "wi_locness_v2.1.bea19.tar.gz")


def _download() -> str:
    if os.path.exists(_CACHE) and os.path.getsize(_CACHE) > 0:
        return _CACHE
    import requests
    r = requests.get(_URL, timeout=180, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    with open(_CACHE, "wb") as f:
        f.write(r.content)
    return _CACHE


def _iter_essays():
    """Yield (band_letter, text) for every essay in the tarball's JSON files."""
    with tarfile.open(_download(), "r:gz") as tar:
        seen = 0
        for m in tar.getmembers():
            name = m.name.replace("\\", "/")
            if not (m.isfile() and "/json/" in name and name.endswith(".json")):
                continue
            band = os.path.basename(name)[:1].upper()
            if band not in {"A", "B", "C", "N"}:
                continue
            seen += 1
            fobj = tar.extractfile(m)
            if fobj is None:
                continue
            for line in io.TextIOWrapper(fobj, encoding="utf-8"):
                line = line.strip()
                if not line:
                    continue
                try:
                    text = json.loads(line).get("text")
                except json.JSONDecodeError:
                    continue
                if isinstance(text, str) and text.strip():
                    yield band, text.strip()
        if seen == 0:
            raise RuntimeError("No '*/json/*.json' files in WI+LOCNESS tarball; layout changed?")


def load_nonnative(n: int = 150, min_words: int = 30, levels: Optional[set] = None, seed: int = 42):
    bands = {b.upper() for b in (levels or {"A", "B", "C"})} & {"A", "B", "C"}
    out = [t for band, t in _iter_essays() if band in bands and len(t.split()) >= min_words]
    random.Random(seed).shuffle(out)
    return out[:n]


def load_native(n: int = 100, min_words: int = 30, seed: int = 42):
    out = [t for band, t in _iter_essays() if band == "N" and len(t.split()) >= min_words]
    random.Random(seed).shuffle(out)
    return out[:n]


def load_by_band(n_per_band: int = 100, min_words: int = 30, seed: int = 42):
    bands = {"A": [], "B": [], "C": []}
    for band, text in _iter_essays():
        if band in bands and len(text.split()) >= min_words:
            bands[band].append(text)
    for b in bands:
        random.Random(seed).shuffle(bands[b])
        bands[b] = bands[b][:n_per_band]
    return bands

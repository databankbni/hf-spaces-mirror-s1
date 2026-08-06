"""HC3 loader (human vs ChatGPT). Loaded via the HF datasets-server parquet API because the HF
repo ships a loading script that modern `datasets` (>=3) refuses to run."""
from __future__ import annotations
import io
import random
import requests


def _hf_parquet_frames(dataset: str, config: str | None = None, split: str | None = None):
    import pandas as pd
    api = f"https://datasets-server.huggingface.co/parquet?dataset={dataset}"
    meta = requests.get(api, timeout=60).json()
    files = meta.get("parquet_files", [])
    if not files:
        raise RuntimeError(f"No parquet files for {dataset}: {meta}")
    sel = [f for f in files
           if (config is None or f["config"] == config)
           and (split is None or f["split"] == split)]
    if not sel:
        raise RuntimeError(f"No parquet for {dataset} config={config} split={split}; "
                           f"configs={sorted({f['config'] for f in files})}")
    frames = [pd.read_parquet(io.BytesIO(requests.get(f["url"], timeout=180).content)) for f in sel]
    return pd.concat(frames, ignore_index=True)


def _collect(n_needed: int, min_words: int, seed: int):
    """Collect (and deterministically shuffle) at least n_needed human and AI texts."""
    df = _hf_parquet_frames("Hello-SimpleAI/HC3", config="all", split="train")
    human, ai = [], []
    for _, row in df.iterrows():
        ha = row.get("human_answers"); ca = row.get("chatgpt_answers")
        for h in (ha if ha is not None else []):
            if isinstance(h, str) and len(h.split()) >= min_words:
                human.append(h.strip())
        for a in (ca if ca is not None else []):
            if isinstance(a, str) and len(a.split()) >= min_words:
                ai.append(a.strip())
        if len(human) >= n_needed and len(ai) >= n_needed:
            break
    random.Random(seed).shuffle(human)
    random.Random(seed + 1).shuffle(ai)
    return human, ai


def load_hc3(n_per_class: int = 500, min_words: int = 30, seed: int = 42):
    """Return (human_texts, ai_texts), each truncated to n_per_class."""
    human, ai = _collect(n_per_class, min_words, seed)
    return human[:n_per_class], ai[:n_per_class]


def load_hc3_split(n_train: int = 1500, n_test: int = 300, min_words: int = 30, seed: int = 42):
    """Disjoint train/test split: returns (train_human, train_ai), (test_human, test_ai)."""
    need = n_train + n_test
    human, ai = _collect(need, min_words, seed)
    tr = (human[:n_train], ai[:n_train])
    te = (human[n_train:need], ai[n_train:need])
    return tr, te

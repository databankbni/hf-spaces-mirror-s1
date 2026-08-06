"""RAID loader (liamdugan/raid) — multi-domain, multi-generator AI-text data.

RAID is sorted by (domain, model, attack). Schema: text=`generation`, label=`model`
('human' = human, else = AI), `domain`, `attack` ('none' = clean).

IMPORTANT: HF only PARTIALLY converts RAID to parquet (it's huge), and because RAID is
domain-sorted the partial parquet contains only the *early* domains. So we never hardcode which
domains exist — `load_raid_records` returns domain-tagged records for whatever is present, and the
caller splits train/OOD from the domains actually observed. Shards are cached + column-pruned.
"""
from __future__ import annotations
import os
import random
import tempfile
from collections import Counter, defaultdict
import requests

_PARQUET_API = "https://datasets-server.huggingface.co/parquet?dataset=liamdugan/raid"
_CACHE_DIR = os.path.join(tempfile.gettempdir(), "raid_parquet")
_NEEDED = ["generation", "model", "domain", "attack"]


def _shard_files(split: str):
    meta = requests.get(_PARQUET_API, timeout=60).json()
    files = [f for f in meta.get("parquet_files", [])
             if f.get("split") == split and f.get("config") == "raid"]
    if not files:
        raise RuntimeError(f"No RAID parquet shards for split={split}; api keys={list(meta)}")
    files.sort(key=lambda f: f["url"])
    print(f"[raid] split='{split}': {len(files)} shard(s), partial-conversion="
          f"{requests.get(_PARQUET_API, timeout=60).json().get('partial')}")
    return files


def _download_shard(f) -> str:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    path = os.path.join(_CACHE_DIR, f["split"] + "_" + f["filename"])
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return path
    print(f"[raid] downloading {f['filename']} ({f.get('size',0)/1e6:.0f} MB)...")
    b = requests.get(f["url"], timeout=900).content
    with open(path, "wb") as fh:
        fh.write(b)
    return path


def _read_shard(path):
    import pandas as pd
    try:
        import pyarrow.parquet as pq
        names = pq.read_schema(path).names
        cols = [c for c in _NEEDED if c in names]
        if len(cols) == len(_NEEDED):
            return pd.read_parquet(path, columns=cols)
    except Exception:
        pass
    return pd.read_parquet(path)


def load_raid_records(n_per_domain_class=300, split="train", attack="none",
                      min_words=30, max_words=600, max_shards=10, seed=42, verbose=True):
    """Return a list of {text, label(0=human,1=ai), domain, model} tagged records, balanced up to
    `n_per_domain_class` per (domain, label) across whatever domains the partial parquet contains."""
    counts = defaultdict(int)
    records = []
    raw_domains, raw_attacks = set(), set()
    for si, f in enumerate(_shard_files(split)[:max_shards]):
        df = _read_shard(_download_shard(f))
        for col in _NEEDED:
            if col not in df.columns:
                raise RuntimeError(f"RAID shard missing '{col}'; columns={list(df.columns)}")
        dom = df["domain"].astype(str).str.strip().str.lower()
        atk = df["attack"].astype(str).str.strip().str.lower()
        mdl = df["model"].astype(str).str.strip().str.lower()
        raw_domains.update(dom.unique().tolist()); raw_attacks.update(atk.unique().tolist())
        if si == 0 and verbose:
            print(f"[raid] shard0 shape={df.shape} domains={sorted(set(dom))[:12]} "
                  f"attacks={sorted(set(atk))[:6]}")
        mask = df["generation"].notna()
        if attack is not None:
            mask &= (atk == str(attack).lower())
        wc = df["generation"].str.split().str.len()
        mask &= (wc >= min_words) & (wc <= max_words)
        idx = df.index[mask].tolist()
        random.Random(seed + si).shuffle(idx)
        gen = df["generation"]
        for i in idx:
            d = dom[i]; label = 0 if mdl[i] == "human" else 1
            if counts[(d, label)] >= n_per_domain_class:
                continue
            counts[(d, label)] += 1
            records.append({"text": gen[i].strip(), "label": label, "domain": d, "model": mdl[i]})
        if verbose:
            print(f"[raid] after {f['filename']}: domains={sorted({k[0] for k in counts})}")
    if not records:
        raise RuntimeError(f"RAID collected 0 records. pre-filter domains={sorted(raw_domains)} "
                           f"attacks={sorted(raw_attacks)} attack-requested='{attack}'.")
    if verbose:
        print(f"[raid] records/domain: {dict(Counter(r['domain'] for r in records))}")
        print(f"[raid] label balance: {dict(Counter(r['label'] for r in records))}")
    return records


def load_raid(n_per_class=1500, split="train", domains=None, holdout_domains=None,
              attack="none", min_words=30, max_words=600, max_shards=10, seed=42, verbose=True):
    """(human, ai) convenience wrapper over load_raid_records, with optional domain include/holdout."""
    recs = load_raid_records(n_per_domain_class=max(50, n_per_class // 3), split=split, attack=attack,
                             min_words=min_words, max_words=max_words, max_shards=max_shards,
                             seed=seed, verbose=verbose)
    if domains:
        ds = {d.lower() for d in domains}; recs = [r for r in recs if r["domain"] in ds]
    if holdout_domains:
        hs = {d.lower() for d in holdout_domains}; recs = [r for r in recs if r["domain"] not in hs]
    human = [r["text"] for r in recs if r["label"] == 0]
    ai = [r["text"] for r in recs if r["label"] == 1]
    random.Random(seed + 2).shuffle(human); random.Random(seed + 3).shuffle(ai)
    return human[:n_per_class], ai[:n_per_class]

"""Keep temp, HF cache, and scratch I/O on the configured DATA_DIR volume.

Windows returns ``[Errno 22] Invalid argument`` when the system temp drive (often
C:) is nearly full while FAISS / upload / embedding caches still write there.
"""

from __future__ import annotations

import os
from pathlib import Path

from backend.config import settings


def ensure_data_drive_runtime_dirs() -> Path:
    """Point TMP/TEMP and HF caches at ``DATA_DIR`` (safe on D: etc.)."""
    root = settings.data_dir_path
    tmp = root / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    os.environ["TMP"] = str(tmp)
    os.environ["TEMP"] = str(tmp)

    # Reduce CUDA allocator fragmentation on small GPUs (the exact remedy the torch
    # OOM error suggests). Lets the caching allocator grow segments instead of
    # failing on a large contiguous request — meaningful headroom on a 4 GB card.
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

    hf = root / "hf_cache"
    hf.mkdir(parents=True, exist_ok=True)
    # HF_HOME is the single source of truth for the model cache (weights live under
    # HF_HOME/hub). Do NOT set SENTENCE_TRANSFORMERS_HOME: for trust_remote_code
    # models (jina-embeddings-v3) it diverts the dynamic-module resolution to a
    # separate root and, under HF_HUB_OFFLINE, breaks tokenizer registration
    # ("Unrecognized configuration class XLMRobertaFlashConfig to build an
    # AutoTokenizer"). It is legacy anyway —
    # modern sentence-transformers resolves models via HF_HOME/hub.
    os.environ.setdefault("HF_HOME", str(hf))
    os.environ.setdefault("TORCH_HOME", str(hf / "torch"))

    # Force fully-offline model loading when configured. Must be set before any
    # transformers / sentence-transformers import triggers a load. For
    # trust_remote_code models (jina-embeddings-v3, jina-reranker-v3), a cached
    # load still issues an online HEAD check for the remote module file
    # (custom_st.py) that local_files_only does NOT suppress — on a slow/blocked/
    # air-gapped host that hangs (10s timeout × retries) or fails. HF_HUB_OFFLINE
    # makes every hub call (including transitive remote-code fetches) cache-only.
    if getattr(settings, "hf_offline", False):
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    return tmp

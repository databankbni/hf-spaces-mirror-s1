"""Shared lazy singleton for SAM 2.1 Tiny (model + processor).

Both card detection (prompt-based) and hand segmentation use the same
HuggingFace weights, so loading them once per process halves cold-start
cost and keeps only one copy of the encoder in memory.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Tuple

# Bump the default HF Hub HEAD/download timeout (10s) before transformers
# reads the env var. On flaky networks the 10s HEAD check fires a retry storm
# even when the weights are already cached locally.
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")

logger = logging.getLogger(__name__)

SAM2_MODEL_ID = "facebook/sam2.1-hiera-small"

# SAM resizes internally to 1024 — feeding >1024 wastes CPU on image encoding.
INFERENCE_MAX_SIDE = 1024

_model = None
_processor = None


def get_sam2() -> Tuple[object, object]:
    """Return (model, processor) singletons, loading on first call.

    Tries the local HF cache first (``local_files_only=True``). This avoids
    the HEAD-request retry storm that happens when huggingface.co is slow or
    unreachable but the weights are already on disk. On a true cache miss we
    fall through to a normal online load.
    """
    global _model, _processor
    if _model is None or _processor is None:
        from transformers import Sam2Model, Sam2Processor
        t0 = time.time()
        logger.info("loading SAM 2.1 (%s)", SAM2_MODEL_ID)
        try:
            _processor = Sam2Processor.from_pretrained(SAM2_MODEL_ID, local_files_only=True)
            _model = Sam2Model.from_pretrained(SAM2_MODEL_ID, local_files_only=True).to("cpu").eval()
            logger.info("SAM 2.1 loaded (offline cache) in %.1fs", time.time() - t0)
        except (OSError, ValueError):
            # Cache miss — fall back to online download.
            _processor = Sam2Processor.from_pretrained(SAM2_MODEL_ID)
            _model = Sam2Model.from_pretrained(SAM2_MODEL_ID).to("cpu").eval()
            logger.info("SAM 2.1 loaded (online) in %.1fs", time.time() - t0)
    return _model, _processor

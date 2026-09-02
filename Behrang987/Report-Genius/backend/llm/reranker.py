"""jina-reranker-v3 cross-encoder: lazy load, RAM guard, and listwise re-scoring.

Extracted from the paragraph retriever so the reranker *model* lives in the
``llm`` provider layer (alongside the embedder and OpenAI client) while the
``rag`` retriever keeps only the multi-signal, observation-based reranking. The
model is loaded lazily and degrades gracefully: when transformers/torch/weights
are unavailable, or under the free-RAM guard, callers fall back to multi-signal
ordering. Device defaults to CPU so the reranker never contends with the
resident embedder on a small GPU.
"""

from __future__ import annotations

import logging

from backend.config import settings
from backend.rag.types import SearchHit

logger = logging.getLogger(__name__)

# Lazy reranker singleton. None = not loaded yet; False = load failed (don't
# retry every call); otherwise the loaded jina-reranker-v3 wrapper.
_CROSS_ENCODER: object | bool | None = None


class _JinaReranker:
    """jina-reranker-v3 listwise reranker.

    ``model.rerank(query, documents)`` tokenises, batches, scores, and sorts the
    whole candidate set in one cross-document forward pass, returning dicts of
    ``{document, relevance_score, index, embedding}`` sorted best-first, where
    ``index`` is the position in the input ``documents`` list. We map the scores
    back onto the original input order so ``cross_encoder_rerank`` keeps its
    contract (stamp ``rerank_score`` per hit, then re-sort).

    jina's ``relevance_score`` is a raw cosine similarity in [-1, 1], so we remap
    it to [0, 1] via ``(1 + s) / 2`` — the same transform the model uses
    internally for block weighting. This is monotonic (ranking is unchanged) and
    preserves the non-negative ``rerank_score`` contract the downstream source
    selection relies on (e.g. the ``max_rerank > 0`` "was this group reranked?"
    gate, which a raw negative cosine would otherwise mis-trip into the
    raw-similarity fallback).
    """

    def __init__(self, model, on_cuda: bool):
        self._model = model
        self._on_cuda = on_cuda

    def score(self, query: str, docs: list[str]) -> list[float]:
        import torch

        from backend.llm.embeddings import gpu_inference_guard

        # The whole scoring pass runs under the shared GPU lock so concurrent
        # section workers (and a concurrent reingest) never issue simultaneous
        # CUDA forward passes — the documented cause of the 4 GB hard-abort crash.
        scores = [0.0] * len(docs)
        with gpu_inference_guard(self._on_cuda):
            try:
                results = self._model.rerank(query, docs)
                for r in results:
                    idx = int(r["index"])
                    if 0 <= idx < len(scores):
                        cosine = float(r["relevance_score"])
                        scores[idx] = min(1.0, max(0.0, (1.0 + cosine) / 2.0))
            finally:
                if self._on_cuda:
                    # Release activations promptly so 26-54 sequential rerank
                    # passes don't fragment the tiny VRAM pool into an OOM.
                    torch.cuda.empty_cache()
        return scores


def _available_ram_gb() -> float:
    """Best-effort free host RAM in GiB.

    Returns ``inf`` when it cannot be measured so an unmeasurable platform never
    blocks the reranker. Tries psutil, then Linux ``/proc/meminfo`` (HF Spaces),
    then the Windows ``GlobalMemoryStatusEx`` API — no hard dependency.
    """
    try:
        import psutil  # type: ignore

        return float(psutil.virtual_memory().available) / (1024**3)
    except Exception:  # noqa: BLE001 - psutil is optional
        pass
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / (1024**2)  # kB -> GiB
    except Exception:  # noqa: BLE001 - not Linux / unreadable
        pass
    try:
        import ctypes

        class _MemStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        ms = _MemStatus()
        ms.dwLength = ctypes.sizeof(_MemStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):  # type: ignore[attr-defined]
            # Use the tighter of physical RAM and page-file headroom so a small
            # Windows paging file (os error 1455) skips the reranker pre-emptively.
            avail_phys = float(ms.ullAvailPhys) / (1024**3)
            avail_page = float(ms.ullAvailPageFile) / (1024**3)
            return min(avail_phys, avail_page)
    except Exception:  # noqa: BLE001 - not Windows / API unavailable
        pass
    return float("inf")


def _get_cross_encoder():
    """Load jina-reranker-v3 once; cache failure so we never retry on a hot path.

    Returns a :class:`_JinaReranker`, or ``None`` when transformers / torch / the
    weights are unavailable — callers then degrade to the multi-signal reranker.
    """
    global _CROSS_ENCODER
    if _CROSS_ENCODER is not None:
        return _CROSS_ENCODER or None

    model_name = settings.reference_cross_encoder_model
    try:
        import torch
        from transformers import AutoModel

        # Device selection: 'auto' uses CUDA when present, but on a small GPU the
        # reranker cannot co-reside with the resident embedder, so 'cpu' keeps the
        # reranker off the card entirely (embedder stays on GPU).
        device_pref = (
            (settings.reference_cross_encoder_device or "auto").strip().lower()
        )
        cuda_available = torch.cuda.is_available()
        if device_pref == "cpu":
            device = "cpu"
        else:
            device = "cuda" if cuda_available else "cpu"
        cuda = device == "cuda"

        # Memory guard: the weight load can hard-abort the process (OpenBLAS /
        # safetensors OOM) on a RAM-tight host rather than raise. The .to(device)
        # path materialises the full model in host RAM before moving it to the
        # device, so keep a free-RAM floor below which we skip and degrade to the
        # multi-signal reranker.
        min_free = float(settings.reference_cross_encoder_min_free_gb or 0.0)
        if min_free > 0.0:
            free_gb = _available_ram_gb()
            if free_gb < min_free:
                logger.warning(
                    "Skipping jina-reranker-v3: %.1f GB free RAM < %.1f GB required "
                    "(%s path); using multi-signal rerank. Free memory or lower "
                    "reference_cross_encoder_min_free_gb to override.",
                    free_gb,
                    min_free,
                    device,
                )
                _CROSS_ENCODER = False
                return None

        dtype_name = (settings.reference_cross_encoder_dtype or "auto").strip().lower()
        if dtype_name == "auto":
            torch_dtype = torch.float16 if cuda else torch.bfloat16
        else:
            torch_dtype = getattr(torch, dtype_name, torch.bfloat16)

        # Prefer the local cache: HF Hub otherwise performs a network revision
        # check on every load that can stall the hot path for minutes. Fall back
        # to a one-time networked download only when the weights aren't cached.
        # trust_remote_code is required: jina-reranker-v3 ships a custom
        # architecture and the .rerank() method via remote modeling code.
        def _load(local_only: bool):
            return AutoModel.from_pretrained(
                model_name,
                dtype=torch_dtype,
                trust_remote_code=True,
                low_cpu_mem_usage=True,
                local_files_only=local_only,
            )

        if cuda:
            torch.cuda.empty_cache()
        try:
            model = _load(local_only=True)
        except Exception:  # noqa: BLE001 - not cached yet; allow a single download
            model = _load(local_only=False)
        model = model.to(device).eval()
        _CROSS_ENCODER = _JinaReranker(model, on_cuda=cuda)
        logger.info(
            "Loaded jina-reranker-v3 %s (%s, %s)", model_name, torch_dtype, device
        )
    except Exception as exc:  # noqa: BLE001 - degrade gracefully on any failure
        logger.warning(
            "Reranker %s unavailable (%s); using multi-signal rerank only.",
            model_name,
            exc,
        )
        _CROSS_ENCODER = False
    return _CROSS_ENCODER or None


def warmup_cross_encoder() -> bool:
    """Eagerly load jina-reranker-v3 at startup (best moment for host RAM).

    No-op unless the reranker is enabled and warmup is configured. Never raises:
    a failed load is already cached as a graceful degrade by ``_get_cross_encoder``.
    Returns True when a reranker instance is live afterwards.
    """
    if not settings.reference_cross_encoder_enabled:
        return False
    if not settings.reference_cross_encoder_warmup:
        return False
    return _get_cross_encoder() is not None


def cross_encoder_rerank(
    query: str,
    hits: list[SearchHit],
    *,
    top_n: int | None = None,
) -> list[SearchHit]:
    """Final-stage jina-reranker-v3 re-scoring of the hybrid-retrieval shortlist.

    Scores the first ``top_n`` candidates jointly against the query, writes the
    0..1 relevance back onto ``rerank_score`` (so source selection honours the
    cross-encoder), and bubbles the best to the front. The remaining candidates
    keep their order. No-ops (returns the input) when the model is unavailable.
    """
    if len(hits) < 2:
        return hits
    reranker = _get_cross_encoder()
    if reranker is None:
        return hits

    n = max(2, top_n or settings.reference_cross_encoder_top_n)
    shortlist = hits[:n]
    tail = hits[n:]
    cap = settings.reference_cross_encoder_doc_chars
    docs = [(h.text or "")[:cap] for h in shortlist]
    try:
        scores = reranker.score(query, docs)
    except Exception as exc:  # noqa: BLE001 - never let reranking break generation
        logger.warning(
            "Cross-encoder scoring failed (%s); keeping multi-signal order.", exc
        )
        return hits

    for hit, score in zip(shortlist, scores, strict=False):
        hit.rerank_score = float(score)
    shortlist = sorted(shortlist, key=lambda h: h.rerank_score, reverse=True)
    return shortlist + tail

"""Embedding abstraction for the v2 backend.

Default backend is a free, local sentence-transformers model
(``jinaai/jina-embeddings-v3``, 1024-dim). Setting ``embedding_provider='openai'``
switches to OpenAI embeddings. The active embedder exposes ``embed_dim`` so the
FAISS store can size its index. Load failures raise — there is no silent fake
fallback in production.
"""

from __future__ import annotations

import logging
import threading
from contextlib import nullcontext

from backend.config import settings

logger = logging.getLogger(__name__)

# Process-wide serialization of GPU model inference. The report pipeline fans a
# report out across many concurrent section workers (``asyncio.to_thread``), and a
# reingest can run at the same time — each issuing forward passes on the *shared*
# CUDA models (jina-embeddings-v3 embedder + jina-reranker-v3). On a small card (e.g. 4 GB RTX
# 2050) those simultaneous passes spike VRAM past the ceiling and the driver hard-
# aborts the whole process (uncatchable in Python), and concurrent forward passes
# on one model also race on CUDA state. Serializing every GPU inference behind one
# lock bounds VRAM to a single op and removes the race. The expensive part of the
# pipeline (concurrent OpenAI calls) is unaffected; GPU ops are milliseconds. On
# CPU there is no VRAM ceiling, so the guard is a no-op and parallelism is kept.
GPU_INFERENCE_LOCK = threading.Lock()


def gpu_inference_guard(on_cuda: bool):
    """Return the global GPU lock as a context manager (no-op when not on CUDA)."""
    return GPU_INFERENCE_LOCK if on_cuda else nullcontext()


class Embedder:
    """Minimal embedding interface used by the RAG store."""

    embed_dim: int

    def embed_documents(
        self, texts: list[str]
    ) -> list[list[float]]:  # pragma: no cover - interface
        raise NotImplementedError

    def embed_query(self, text: str) -> list[float]:  # pragma: no cover - interface
        raise NotImplementedError


class LocalEmbedder(Embedder):
    """sentence-transformers backend (default: jina-embeddings-v3)."""

    def __init__(
        self,
        model_name: str,
        *,
        dtype: str = "auto",
        trust_remote_code: bool = False,
        device: str = "auto",
        batch_size: int = 8,
        max_seq_length: int = 1024,
    ) -> None:
        from sentence_transformers import SentenceTransformer

        # jina-embeddings-v3 exposes asymmetric task LoRA adapters through the
        # encode `task` kwarg (retrieval.passage for documents, retrieval.query for
        # queries). Symmetric models (MiniLM, etc.) reject that kwarg, so it is only
        # passed for jina models.
        self._model_name = model_name
        self._is_jina = "jina" in model_name.lower()

        # Encode batch ceiling. Auto-tuned down (sticky) on CUDA OOM; see _encode.
        self._init_batch_size = max(1, int(batch_size))
        self._batch_size = self._init_batch_size

        model_kwargs: dict = {}
        torch_dtype = self._resolve_dtype(dtype)
        if torch_dtype is not None:
            model_kwargs[self._dtype_kwarg()] = torch_dtype

        # device: "auto" → let sentence-transformers pick (CUDA if available); an
        # explicit "cpu"/"cuda" forces it. Force "cpu" on GPUs too small for the
        # model (see local_embedding_device).
        st_device = None if (device or "auto").strip().lower() == "auto" else device

        # Offline loading is controlled ONLY by HF_HUB_OFFLINE (set via hf_offline in
        # runtime_paths), never by per-call local_files_only: passing
        # local_files_only=True to SentenceTransformer breaks jina-embeddings-v3's
        # tokenizer resolution ("Unrecognized configuration class XLMRobertaFlashConfig
        # to build an AutoTokenizer"), whereas the HF_HUB_OFFLINE env var loads the
        # cached remote code + tokenizer cleanly. See hf_offline in backend/config.py.
        self._model = SentenceTransformer(
            model_name,
            device=st_device,
            trust_remote_code=trust_remote_code,
            model_kwargs=model_kwargs or None,
        )
        # Cap the token window. jina-v3's native 8192 makes attention (O(L^2))
        # allocate multiple GB for a batch of long chunks — the actual cause of the
        # reingest OOM/crash on a 4 GB GPU and of CPU allocator failures. RAG chunks
        # are ~500 tokens, so 1024 truncates almost nothing while bounding memory.
        # Always clamp to the loaded weights' max_position_embeddings: a config of
        # 8192 does not extend the position table (512 on some paths), and encode()
        # then crashes with "tensor a (1510) must match tensor b (512)" on long chunks.
        effective_max = self._clamp_max_seq_length(int(max_seq_length))
        if effective_max > 0:
            try:
                self._model.max_seq_length = effective_max
            except Exception:  # noqa: BLE001 - not all models expose the setter
                pass
        self._max_seq_length = int(getattr(self._model, "max_seq_length", effective_max) or effective_max)

        self.embed_dim = int(self._model.get_sentence_embedding_dimension())
        try:
            self._on_cuda = getattr(self._model.device, "type", "") == "cuda"
        except Exception:  # noqa: BLE001 - device introspection is best-effort
            self._on_cuda = False
        logger.info(
            "LocalEmbedder loaded %s (dim=%d, dtype=%s, cuda=%s, batch=%d, max_seq=%s, jina_tasks=%s)",
            model_name,
            self.embed_dim,
            torch_dtype or "default",
            self._on_cuda,
            self._batch_size,
            self._max_seq_length,
            self._is_jina,
        )

    @staticmethod
    def _position_embedding_cap(model) -> int | None:
        """Smallest max_position_embeddings exposed by the loaded ST stack."""
        caps: list[int] = []
        try:
            for module in model:
                for attr in ("auto_model", "0", "model"):
                    inner = getattr(module, attr, None)
                    if inner is None:
                        continue
                    cfg = getattr(inner, "config", None)
                    mpe = getattr(cfg, "max_position_embeddings", None)
                    if mpe is not None:
                        caps.append(int(mpe))
        except Exception:  # noqa: BLE001 - introspection is best-effort
            pass
        try:
            tok_max = getattr(getattr(model, "tokenizer", None), "model_max_length", None)
            if tok_max is not None and int(tok_max) > 0:
                caps.append(int(tok_max))
        except Exception:  # noqa: BLE001
            pass
        return min(caps) if caps else None

    def _clamp_max_seq_length(self, requested: int) -> int:
        """Return ``min(requested, hard weight cap)`` so encode() always truncates."""
        if requested <= 0:
            return requested
        hard = self._position_embedding_cap(self._model)
        if hard is None or hard >= requested:
            return requested
        logger.warning(
            "Clamping local embedder max_seq_length %d → %d (model position table limit).",
            requested,
            hard,
        )
        return hard

    @staticmethod
    def _dtype_kwarg() -> str:
        """Name of the ``from_pretrained`` dtype kwarg for the installed transformers.

        transformers >=4.56 (and 5.x) take ``dtype``; older releases take the now-
        deprecated ``torch_dtype``. Matches the reranker loader, which already uses
        ``dtype=`` on this environment's transformers 5.x.
        """
        try:
            import transformers

            parts = transformers.__version__.split(".")
            major, minor = int(parts[0]), int(parts[1])
        except Exception:  # noqa: BLE001 - version parsing is best-effort
            return "dtype"
        if major > 4 or (major == 4 and minor >= 56):
            return "dtype"
        return "torch_dtype"

    @staticmethod
    def _resolve_dtype(dtype: str):
        """Map a dtype setting to a torch dtype (``None`` → library default)."""
        name = (dtype or "auto").strip().lower()
        try:
            import torch
        except Exception:  # noqa: BLE001 - torch ships with sentence-transformers
            return None
        if name in ("", "default"):
            return None
        if name == "auto":
            return torch.float16 if torch.cuda.is_available() else torch.bfloat16
        return getattr(torch, name, None)

    @staticmethod
    def _is_oom(exc: BaseException) -> bool:
        """True for a GPU *or* CPU out-of-memory / allocator fault."""
        try:
            import torch

            if isinstance(exc, torch.cuda.OutOfMemoryError):
                return True
        except Exception:  # noqa: BLE001 - torch always present here, be defensive
            pass
        msg = str(exc).lower()
        return (
            "out of memory" in msg  # CUDA OOM
            or "not enough memory" in msg  # torch DefaultCPUAllocator
            or "alloc_cpu" in msg  # torch CPU enforce fail
            or "defaultcpuallocator" in msg
            or "bad_alloc" in msg  # std::bad_alloc
        )

    def _empty_cuda_cache(self) -> None:
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001 - best-effort VRAM reclaim
            pass

    def _downgrade_to_cpu(self) -> None:
        """Permanently move the model to CPU (GPU can't fit even batch_size=1)."""
        try:
            self._model.to("cpu")
        except Exception:  # noqa: BLE001
            pass
        self._on_cuda = False
        self._batch_size = self._init_batch_size  # no VRAM ceiling on CPU
        self._empty_cuda_cache()

    def _encode(self, texts: list[str], task: str) -> list[list[float]]:
        kwargs: dict = {"normalize_embeddings": True, "convert_to_numpy": True}
        if self._is_jina:
            kwargs["task"] = task
        payload = list(texts)
        # Even with the max_seq_length cap, a large batch can exceed a small VRAM (or
        # CPU RAM) budget. Recover in-process instead of failing the whole document:
        # reclaim VRAM and halve the batch (sticky) down to 1. If batch_size 1 still
        # OOMs on GPU, the card is too small/contended — move to CPU permanently and
        # retry; if it OOMs on CPU too, the host is genuinely out of RAM → re-raise.
        while True:
            try:
                with gpu_inference_guard(self._on_cuda):
                    vecs = self._model.encode(
                        payload, batch_size=self._batch_size, **kwargs
                    )
                return [v.tolist() for v in vecs]
            except Exception as exc:  # noqa: BLE001 - narrow to memory faults below
                # On CUDA also treat opaque OSErrors as OOM: under VRAM pressure
                # Windows surfaces a wedged CUDA context as "[Errno 22] Invalid
                # argument". This block only runs model compute, so an OSError here is
                # a device fault, not disk.
                recoverable = self._is_oom(exc) or (
                    self._on_cuda and isinstance(exc, OSError)
                )
                if not recoverable:
                    raise
                if self._on_cuda:
                    self._empty_cuda_cache()
                if self._batch_size > 1:
                    smaller = max(1, self._batch_size // 2)
                    logger.warning(
                        "OOM embedding %d text(s) on %s at batch_size=%d; retrying at %d.",
                        len(payload),
                        "cuda" if self._on_cuda else "cpu",
                        self._batch_size,
                        smaller,
                    )
                    self._batch_size = smaller
                    continue
                if self._on_cuda:
                    logger.warning(
                        "CUDA OOM at batch_size=1; moving embedder to CPU permanently."
                    )
                    self._downgrade_to_cpu()
                    continue
                raise

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out = self._encode(list(texts), "retrieval.passage")
        try:
            from backend.cost import record_embedding_cost

            # Local embedder is free; still record volume for provider comparisons.
            # Approximate tokens as chars/4 when tiktoken is unavailable.
            chars = sum(len(t or "") for t in texts)
            approx_tokens = max(0, chars // 4)
            record_embedding_cost(
                model=self._model_name,
                prompt_tokens=approx_tokens,
                label="embed_local",
                provider="local",
                texts_count=len(texts),
            )
        except Exception:  # noqa: BLE001
            pass
        return out

    def embed_query(self, text: str) -> list[float]:
        return self._encode([text], "retrieval.query")[0]


class OpenAIEmbedder(Embedder):
    """OpenAI embeddings backend."""

    _DIMS = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
    }

    def __init__(self, model_name: str, api_key: str) -> None:
        from openai import OpenAI

        self._client = OpenAI(
            api_key=api_key,
            timeout=float(settings.openai_request_timeout_seconds),
        )
        self._model = model_name
        self.embed_dim = self._DIMS.get(model_name, 1536)
        logger.info("OpenAIEmbedder using %s (dim=%d)", model_name, self.embed_dim)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        from backend.llm.openai_client import pipeline_timeout

        # OpenAI caps batch size; keep requests modest for timeouts/rate limits.
        batch = 64
        out: list[list[float]] = []
        for i in range(0, len(texts), batch):
            block = list(texts[i : i + batch])
            resp = self._client.embeddings.create(
                model=self._model,
                input=block,
                timeout=pipeline_timeout(),
            )
            # API may return out of order — sort by index.
            ordered = sorted(resp.data, key=lambda d: d.index)
            out.extend(d.embedding for d in ordered)
            try:
                from backend.cost import record_embedding_cost

                usage = getattr(resp, "usage", None)
                pt = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
                if pt <= 0 and usage is not None:
                    pt = int(getattr(usage, "total_tokens", 0) or 0)
                if pt <= 0:
                    # Fallback estimate when usage is missing.
                    pt = max(0, sum(len(t or "") for t in block) // 4)
                record_embedding_cost(
                    model=self._model,
                    prompt_tokens=pt,
                    label="embed_openai",
                    provider="openai",
                    texts_count=len(block),
                )
            except Exception:  # noqa: BLE001
                pass
        return out

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


_instance: Embedder | None = None


def get_embedder() -> Embedder:
    """Return the cached embedder singleton selected by configuration.

    Raises on load failure (missing weights, wrong device, CUDA/CPU mismatch, etc.).
    """
    global _instance
    if _instance is not None:
        return _instance

    provider = (settings.embedding_provider or "openai").lower()
    if provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError(
                "embedding_provider='openai' (or USE_OPENAI_EMBEDDINGS=true) requires "
                "OPENAI_API_KEY. Set the key, or switch back to EMBEDDING_PROVIDER=local."
            )
        _instance = OpenAIEmbedder(
            settings.openai_embedding_model, settings.openai_api_key
        )
    else:
        _instance = LocalEmbedder(
            settings.local_embedding_model,
            dtype=settings.local_embedding_dtype,
            trust_remote_code=settings.local_embedding_trust_remote_code,
            device=settings.local_embedding_device,
            batch_size=settings.local_embedding_batch_size,
            max_seq_length=settings.local_embedding_max_seq_length,
        )
    return _instance


def reset_embedder() -> None:
    """Reset the cached embedder (tests / config reloads)."""
    global _instance
    _instance = None

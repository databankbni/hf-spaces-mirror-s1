"""Configuration for the template-agnostic v2 backend.

All values are overridable via environment variables (prefix-free) or a ``.env``
file at the repository root. See the package README for the deployment model.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/config.py -> repo root is one level up from this package.
REPO_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """Central v2 settings object."""

    model_config = SettingsConfigDict(
        # Resolve from repo root, not process cwd — uvicorn launched from the wrong
        # directory (e.g. a path typo) must still pick up DATA_DIR / HF_HOME.
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # ── LLM (OpenAI / Gemini) ─────────────────────────────────────────────────
    openai_api_key: str = Field(default="", description="OpenAI API key")
    gemini_api_key: str = Field(
        default="",
        description="Google Gemini API key (GEMINI_API_KEY or GOOGLE_API_KEY).",
        validation_alias=AliasChoices(
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "gemini_api_key",
        ),
    )
    mapping_model: str = Field(
        default="gpt-5.6-luna",
        description=(
            "Model used to map surveyor notes onto retrieved baseline paragraphs. "
            "Prose writer for Assist/Expert mapping. Audit/repair/discovery stay on "
            "gpt-5-nano (JSON discipline matters more than prose there)."
        ),
    )
    discovery_model: str = Field(
        default="gpt-5-nano",
        description="Model used for master-template schema discovery (JSON mode).",
    )
    grounding_model: str = Field(
        default="gpt-5-nano",
        description="Model used for the PII / grounding audit pass.",
    )
    repair_model: str = Field(
        default="gpt-5-nano",
        description=(
            "Model used for the surgical repair pass. Kept on the cheap "
            "JSON-disciplined model even when mapping_model is upgraded."
        ),
    )
    grounding_temperature: float = Field(
        default=0.2,
        ge=0.0,
        le=2.0,
        description=(
            "LLM temperature for the grounding auditor. Only sent when "
            "grounding_reasoning_effort is none/empty."
        ),
    )
    grounding_reasoning_effort: str = Field(
        default="none",
        description=(
            "OpenAI gpt-5 / o-series reasoning_effort for the auditor "
            "(none|minimal|low|medium|high). Default none pairs with "
            "grounding_temperature."
        ),
    )
    repair_temperature: float = Field(
        default=0.2,
        ge=0.0,
        le=2.0,
        description=(
            "LLM temperature for the repair pass. Only sent when "
            "repair_reasoning_effort is none/empty."
        ),
    )
    repair_reasoning_effort: str = Field(
        default="none",
        description=(
            "OpenAI gpt-5 / o-series reasoning_effort for repair "
            "(none|minimal|low|medium|high). Default none pairs with "
            "repair_temperature."
        ),
    )
    openai_request_timeout_seconds: float = Field(
        default=60.0,
        ge=5.0,
        le=600.0,
        description="Hard timeout for OpenAI chat and embedding HTTP calls (seconds).",
    )
    openai_pipeline_timeout_seconds: float = Field(
        default=20.0,
        ge=5.0,
        le=120.0,
        description=(
            "Strict per-call timeout (seconds) for chat/embeddings inside the "
            "report generation pipeline."
        ),
    )
    max_concurrent_llm_calls: int = Field(
        default=10,
        ge=1,
        le=100,
        description=(
            "Maximum concurrent in-flight OpenAI chat completion HTTP requests "
            "across parallel section workers."
        ),
    )
    section_concurrency: int = Field(
        default=4,
        ge=1,
        le=54,
        description=(
            "Max sections processed in parallel during report generation. Default "
            "4 keeps jina embedder + reranker + OpenAI within a 4 GB GPU and small "
            "Windows paging file; 54 fans out every section at once and can hard-"
            "abort the process (browser shows 'Failed to fetch')."
        ),
    )
    openai_rate_limit_max_retries: int = Field(
        default=5,
        ge=0,
        le=20,
        description="Retry attempts after OpenAI HTTP 429 rate-limit responses.",
    )
    openai_rate_limit_backoff_base_seconds: float = Field(
        default=1.0,
        ge=0.1,
        le=60.0,
        description="Initial exponential backoff base (seconds) for 429 retries.",
    )
    openai_rate_limit_backoff_max_seconds: float = Field(
        default=60.0,
        ge=1.0,
        le=300.0,
        description="Maximum backoff delay (seconds) between 429 retries.",
    )

    # ── Embeddings (local jina-embeddings-v3 default; OpenAI optional) ────────
    embedding_provider: str = Field(
        default="openai",
        description=(
            "Embedding backend: 'openai' (default) or 'local' (sentence-transformers / jina). "
            "Also settable via USE_OPENAI_EMBEDDINGS=true|false."
        ),
        validation_alias=AliasChoices(
            "EMBEDDING_PROVIDER",
            "embedding_provider",
        ),
    )
    use_openai_embeddings: bool | None = Field(
        default=None,
        description=(
            "LEGACY override — prefer EMBEDDING_PROVIDER alone. "
            "true → embedding_provider=openai, false → embedding_provider=local. "
            "When unset, EMBEDDING_PROVIDER wins. Requires OPENAI_API_KEY when true. "
            "Re-ingest after switching — local jina (1024-d) and OpenAI "
            "text-embedding-3-* (1536/3072-d) indexes are not interchangeable."
        ),
        validation_alias=AliasChoices(
            "USE_OPENAI_EMBEDDINGS",
            "use_openai_embeddings",
        ),
    )
    local_embedding_model: str = Field(
        default="jinaai/jina-embeddings-v3",
        description=(
            "sentence-transformers model used when embedding_provider='local'. "
            "jina-embeddings-v3 is a 1024-dim, 8192-token model with a custom "
            "architecture loaded via trust_remote_code; it uses asymmetric task "
            "adapters (retrieval.passage for documents, retrieval.query for queries)."
        ),
    )
    local_embedding_dtype: str = Field(
        default="bfloat16",
        description=(
            "Weight dtype for the local embedder: 'auto' (float16 on GPU, bfloat16 "
            "on CPU), or an explicit 'float32' / 'float16' / 'bfloat16'. bfloat16 "
            "halves resident memory for the 0.57B jina model to ~1.14 GB."
        ),
    )
    local_embedding_trust_remote_code: bool = Field(
        default=True,
        description=(
            "Allow the local embedder to execute the model's remote modeling code. "
            "Required by jina-embeddings-v3 (custom architecture). Set False to pin "
            "to models that ship no remote code (e.g. all-MiniLM-L6-v2)."
        ),
    )
    local_embedding_device: str = Field(
        default="cpu",
        description=(
            "Device for the backend local embedder: 'auto' (CUDA if available, else "
            "CPU), 'cuda', or 'cpu'. Force 'cpu' on small GPUs (<6 GB) where jina-v3 "
            "(0.57B) plus a reranker will not fit — the embedder auto-falls back to "
            "CPU on unrecoverable CUDA OOM regardless, but 'cpu' avoids the churn."
        ),
    )
    local_embedding_batch_size: int = Field(
        default=8,
        description=(
            "Max texts per embedder forward pass. Small default keeps jina-v3 within "
            "a 4 GB VRAM budget during reingest. On CUDA OOM the embedder halves this "
            "(sticky, per-process) down to 1, then falls back to CPU — so this is a "
            "starting ceiling, not a hard limit. Raise it on larger GPUs for speed."
        ),
    )
    local_embedding_max_seq_length: int = Field(
        default=8192,
        description=(
            "Token truncation length for the local embedder. jina-v3's native window "
            "is 8192; keeping it means REFERENCE chunks (reference_paragraph_max_chars "
            "= 8000 chars ~= 2000 tokens) embed in full with no truncation. Attention "
            "is O(L^2) under native (non-flash) attention, so on low-VRAM GPUs pair "
            "this with a small local_embedding_batch_size; the embedder also auto-"
            "halves the batch and falls back to CPU on OOM. Lower it to force "
            "truncation, or set 0 for the model default."
        ),
    )
    hf_offline: bool = Field(
        default=False,
        description=(
            "Run HuggingFace fully offline: load embedder + reranker weights and "
            "trust_remote_code modules from the local HF cache only, with zero "
            "network calls. Exported as HF_HUB_OFFLINE=1 + TRANSFORMERS_OFFLINE=1 "
            "at startup (before any model import). Required in production and on "
            "slow/blocked networks: for trust_remote_code models (jina-v3, "
            "jina-reranker-v3) even a fully-cached load otherwise issues an online "
            "HEAD check for custom_st.py that hangs or fails. Weights must be "
            "pre-provisioned (baked into the image or a mounted cache). Leave False "
            "for the first download on a fresh host, then set True."
        ),
    )
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        description=(
            "OpenAI embedding model when embedding_provider='openai' "
            "(text-embedding-3-small / text-embedding-3-large / text-embedding-ada-002). "
            "Also accepts EMBEDDING_MODEL as an alias."
        ),
        validation_alias=AliasChoices(
            "OPENAI_EMBEDDING_MODEL",
            "EMBEDDING_MODEL",
            "openai_embedding_model",
        ),
    )

    # ── PII scrubbing ────────────────────────────────────────────────────────
    pii_scrubbing_enabled: bool = Field(
        default=False,
        description=(
            "Master switch for the ENTIRE PII layer — regex + spaCy redaction and "
            "every assert_no_pii hard gate. False (default) disables the layer "
            "end-to-end (nothing redacted, dropped, or blocked). "
            "Set PII_SCRUBBING_ENABLED=true to enable scrubbing at ingest, "
            "sanitise generation context, and reject residual PII in DOCX / "
            "master-template gates."
        ),
        validation_alias=AliasChoices(
            "PII_SCRUBBING_ENABLED",
            "PII_SCRUB_ENABLED",
            "ENABLE_PII_SCRUBBING",
            "pii_scrubbing_enabled",
        ),
    )
    spacy_model: str = Field(
        default="en_core_web_sm",
        description=(
            "spaCy NER model for PII scrubbing. en_core_web_sm is bundled via "
            "requirements.txt; set en_core_web_md or en_core_web_trf in .env for "
            "higher accuracy when installed."
        ),
    )
    pii_use_spacy: bool = Field(
        default=False,
        description=(
            "Enable the spaCy NER pass on top of the always-on regex pass. "
            "Off by default (regex-only); needs the spaCy model installed when true."
        ),
    )
    pii_scrub_audit_dump: bool = Field(
        default=True,
        description=(
            "Write verbose PII scrub audit artifacts at REFERENCE ingest under "
            "<data_dir>/pii_scrub_audit/<tenant>/<document>/: redacted_content.txt "
            "(the whole document after redaction, section by section) and "
            "redactions.json (every redacted value with its location — section, "
            "paragraph, chunk, char offset, context — plus whitelisted survey terms "
            "and dropped chunks). Also writes a static whitelist_catalog.json. "
            "pii_mapping.json is always written for scrubbed content regardless of "
            "this flag. Disable verbose dump via PII_SCRUB_AUDIT_DUMP=false."
        ),
    )
    pii_scrub_audit_max_surface_chars: int = Field(
        default=200,
        ge=0,
        le=2000,
        description=(
            "Max characters of each redacted/whitelisted surface string and context "
            "snippet in redactions.json (0 = full text)."
        ),
    )

    # ── Operator bundle (Master Standard report and paragraphs/) ─────────────
    master_template_dir: str = Field(
        default="Master Standard report and paragraphs",
        description="Folder holding the report template PDF and standard-paragraphs Word file.",
    )
    report_template_filename: str = Field(
        default="SAMPLE LEVEL 3 REPORT NCS.pdf",
        description=(
            "Report template (PDF): defines section structure, order and ratings. "
            "Schema discovery reads this file."
        ),
    )
    standard_paragraphs_filename: str = Field(
        default="HB-BS STANDARD PARAS v6 Sept 2015.doc",
        description=(
            "Standard paragraphs (Word): firm-approved boilerplate wording per section. "
            "Ingested into the MASTER RAG tier."
        ),
    )
    # Backward-compatible alias for the standard-paragraphs file.
    master_template_filename: str = Field(
        default="HB-BS STANDARD PARAS v6 Sept 2015.doc",
        description="Deprecated alias for standard_paragraphs_filename.",
    )
    master_template_prebuilt_schema: str = Field(
        default="",
        description="Optional path to a prebuilt schema.json; skips discovery when set and present.",
    )
    master_template_prebuilt_faiss: str = Field(
        default="",
        description="Optional path to a prebuilt MASTER FAISS dir; skips embedding when set and present.",
    )
    master_template_upload_enabled: bool = Field(
        default=False,
        description="Enable the gated admin override routes for replacing the master at runtime.",
    )

    # ── Reference PDF text extraction (upload / re-ingest) ───────────────────
    pdf_extractor: str = Field(
        default="textract",
        description=(
            "How uploaded/re-ingested reference PDFs are turned into text before "
            "segmentation. One of: textract | llamaparse | pypdf. "
            "textract needs AWS credentials + AWS_S3_BUCKET; llamaparse needs "
            "LLAMA_CLOUD_API_KEY; pypdf is local-only (PyMuPDF fallback)."
        ),
        validation_alias=AliasChoices(
            "PDF_EXTRACTOR",
            "REFERENCE_PDF_EXTRACTOR",
            "pdf_extractor",
        ),
    )
    llama_cloud_api_key: str = Field(
        default="",
        description="LlamaCloud API key for PDF_EXTRACTOR=llamaparse.",
        validation_alias=AliasChoices(
            "LLAMA_CLOUD_API_KEY",
            "LLAMA_PARSE_API_KEY",
            "llama_cloud_api_key",
        ),
    )
    llama_parse_tier: str = Field(
        default="agentic",
        description="LlamaParse tier: agentic | agentic_plus | cost_effective | fast.",
        validation_alias=AliasChoices("LLAMA_PARSE_TIER", "llama_parse_tier"),
    )
    llama_parse_version: str = Field(
        default="latest",
        description="LlamaParse API parse version string.",
        validation_alias=AliasChoices("LLAMA_PARSE_VERSION", "llama_parse_version"),
    )
    aws_region: str = Field(
        default="",
        description="AWS region for Textract/S3 (or AWS_DEFAULT_REGION).",
        validation_alias=AliasChoices(
            "AWS_REGION",
            "AWS_DEFAULT_REGION",
            "aws_region",
        ),
    )
    aws_s3_bucket: str = Field(
        default="",
        description="S3 bucket for Textract async PDF input (local PDF uploads).",
        validation_alias=AliasChoices(
            "AWS_S3_BUCKET",
            "TEXTRACT_S3_BUCKET",
            "aws_s3_bucket",
        ),
    )
    textract_s3_prefix: str = Field(
        default="textract-input/",
        description="S3 key prefix for temporary Textract PDF uploads.",
        validation_alias=AliasChoices("TEXTRACT_S3_PREFIX", "textract_s3_prefix"),
    )
    aws_profile: str = Field(
        default="",
        description="Optional named AWS profile for Textract/S3.",
        validation_alias=AliasChoices("AWS_PROFILE", "aws_profile"),
    )

    # ── Reference ingest segmentation (LLM-assisted, regex fallback) ──────────
    ingest_llm_segmentation_enabled: bool = Field(
        default=False,
        description=(
            "Segment uploaded past reports with an LLM at upload time "
            "(leaf ids for D–I/J, parent-level bodies for A/B/C/K/L/M/N). "
            "Default false = regex heading chunker only (no LLM cost). "
            "Set true / USE_LLM_SEGMENTATION=true to try the LLM first; "
            "still falls back to regex if there is no API key or the call fails."
        ),
        validation_alias=AliasChoices(
            "INGEST_LLM_SEGMENTATION_ENABLED",
            "USE_LLM_SEGMENTATION",
            "ingest_llm_segmentation_enabled",
        ),
    )
    ingest_embed_enabled: bool = Field(
        default=True,
        description=(
            "When true (default), ingest embeds prepared chunks into FAISS. "
            "When false / USE_INGEST_EMBEDDING=false, only extract → segment → "
            "scrub → persist chunk text (extracted_chunks / chunks_only.json) — "
            "no embedding API cost and nothing searchable until you re-ingest "
            "with embedding on."
        ),
        validation_alias=AliasChoices(
            "INGEST_EMBED_ENABLED",
            "USE_INGEST_EMBEDDING",
            "ingest_embed_enabled",
        ),
    )
    ingest_segmentation_model: str = Field(
        default="gpt-5-nano",
        description=(
            "Model for ingest segmentation (JSON marker output). Keep on "
            "gpt-5-nano unless explicitly overridden; pair with "
            "reasoning_effort=minimal so hidden reasoning does not exhaust the "
            "completion budget and return empty content."
        ),
    )
    ingest_segmentation_window_lines: int = Field(
        default=300,
        ge=50,
        le=2000,
        description="Lines of extracted text per segmentation LLM window.",
    )
    ingest_segmentation_window_overlap: int = Field(
        default=30,
        ge=0,
        le=200,
        description="Overlap lines between consecutive segmentation windows.",
    )
    ingest_segmentation_timeout_seconds: float = Field(
        default=120.0,
        ge=20.0,
        le=600.0,
        description=(
            "Per-window timeout for ingest LLM segmentation. Defaults higher than "
            "OPENAI_PIPELINE_TIMEOUT_SECONDS (generation uses ~20s); large PDF "
            "windows on gpt-5-* often need 60–120s."
        ),
        validation_alias=AliasChoices(
            "INGEST_SEGMENTATION_TIMEOUT_SECONDS",
            "ingest_segmentation_timeout_seconds",
        ),
    )
    ingest_segmentation_max_tokens: int = Field(
        default=8000,
        ge=512,
        le=32000,
        description=(
            "max_completion_tokens for ingest segmentation JSON. gpt-5 models count "
            "reasoning against this budget — too low yields empty content and regex "
            "fallback."
        ),
        validation_alias=AliasChoices(
            "INGEST_SEGMENTATION_MAX_TOKENS",
            "ingest_segmentation_max_tokens",
        ),
    )

    # ── Optional reference uploads (past completed reports, style only) ────────
    reference_auto_ingest_enabled: bool = Field(
        default=False,
        description=(
            "When true, scan reference_auto_ingest_dir for extra past reports. "
            "The report-template PDF and standard-paragraphs Word file are never "
            "ingested as references."
        ),
    )
    reference_auto_ingest_dir: str = Field(
        default="",
        description="Folder to scan for reference docs; empty means use master_template_dir.",
    )
    reference_auto_ingest_globs: str = Field(
        default="*.pdf,*.docx,*.doc",
        description="Comma-separated globs scanned for reference docs (master filename excluded).",
    )
    # ── RAG / retrieval ──────────────────────────────────────────────────────
    data_dir: str = Field(
        default_factory=lambda: str(Path.home() / ".rics_v2"),
        description="Root directory for per-tenant schema + FAISS artifacts.",
    )
    default_tenant_id: str = Field(
        default="default",
        description="Tenant that receives the operator master at startup.",
    )
    retrieval_top_k: int = Field(default=15, ge=1, le=50)
    reference_baseline_top_k: int = Field(
        default=4,
        ge=1,
        le=50,
        description="Top REFERENCE-tier blocks retrieved as stylistic baseline scaffolding.",
    )
    add_to_memory_top_k: int = Field(
        default=20,
        ge=1,
        le=50,
        description=(
            "Top-K Add-to-Memory paragraphs (REFERENCE document_type=add_to_memory) "
            "ranked by note similarity for past-report prompt injection."
        ),
    )
    add_to_memory_min_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum retrieval score for an Add-to-Memory hit to enter the "
            "past-report mapping prompt. 0 keeps all ranked top-K hits."
        ),
    )
    retrieval_section_boost: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="FAISS score boost when chunk section_id matches the alias-resolved id.",
    )
    retrieval_lexical_boost: float = Field(
        default=0.04,
        ge=0.0,
        le=0.5,
        description="Per shared content-token boost when reranking paragraphs against notes.",
    )
    hybrid_retrieval_enabled: bool = Field(
        default=True,
        description=(
            "Fuse a sparse BM25 arm with the dense FAISS arm at retrieval time "
            "(Reciprocal Rank Fusion). When True, lexically-strong chunks that "
            "embed poorly still enter the candidate pool before reranking. "
            "Disable to fall back to dense-only retrieval."
        ),
    )
    hybrid_rrf_k: int = Field(
        default=60,
        ge=1,
        le=1000,
        description=(
            "Reciprocal Rank Fusion damping constant. A rank-r (0-based) hit "
            "contributes 1/(k+r+1); the standard value is 60."
        ),
    )
    hybrid_bm25_k1: float = Field(
        default=1.5,
        ge=0.0,
        le=5.0,
        description="BM25 term-frequency saturation (k1). Typical range 1.2-2.0.",
    )
    hybrid_bm25_b: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="BM25 document-length normalisation (b). 0=no normalisation.",
    )
    reference_subchunk_indexing_enabled: bool = Field(
        default=False,
        description=(
            "Small-to-big dense retrieval for the REFERENCE tier via general "
            "search(). When True, the dense arm scores per-parent the BEST "
            "overlapping sub-window instead of the head-truncated full chunk "
            "(mitigates short-context head-bias on long past-report chunks). "
            "Subchunk hits collapse to their parent before RRF with the "
            "unchanged parent-level BM25 arm. The view is built lazily in-memory "
            "and rebuilt on meta change / process restart — which can burn "
            "many embedding calls. Default False: dense-on-full-chunk only. "
            "Section-scoped hybrid (past-report + ATM dual-path) never uses "
            "this path. See backend/tests/golden/retrieval_benchmark.py."
        ),
    )
    reference_subchunk_words: int = Field(
        default=120,
        ge=16,
        le=512,
        description=(
            "Sub-window length in whitespace tokens for reference subchunk "
            "indexing. ~120 words (~160 MiniLM tokens) sits inside the model's "
            "256-token window so each window embeds without head-truncation."
        ),
    )
    reference_subchunk_overlap: int = Field(
        default=30,
        ge=0,
        le=256,
        description=(
            "Sub-window overlap in whitespace tokens. Overlap keeps a finding that "
            "straddles a window boundary intact in at least one window."
        ),
    )
    reference_subchunk_embed_batch: int = Field(
        default=512,
        ge=16,
        le=4096,
        description=(
            "Sub-windows embedded per embed_documents() call when building the "
            "subchunk view. Bounds the transient list-of-lists allocation: a large "
            "reference tier yields tens of thousands of windows, and embedding them "
            "all at once spikes host RAM (each MiniLM vector round-trips through a "
            "Python list before re-packing to float32). Batching writes straight "
            "into a preallocated matrix so peak memory stays flat regardless of "
            "corpus size."
        ),
    )
    dedupe_chunks_on_ingest: bool = Field(
        default=True,
        description=(
            "Drop duplicate chunks at ingest BEFORE scrubbing/embedding so they are "
            "never processed or stored. A chunk is a duplicate when another chunk "
            "with the same (section_id, normalised text) was already seen in this "
            "batch or already exists in the tier. Prevents the index bloat that "
            "follows repeated uploads / re-ingests (the OOM root cause) and keeps "
            "BM25 document frequencies + the subchunk view honest."
        ),
    )
    prompt_literature_few_shot_enabled: bool = Field(
        default=True,
        description=(
            "Inject curated few-shot user/assistant turns from the operator "
            "literature corpus (My literature April 2026) before the live task."
        ),
    )
    prompt_chain_of_thought_enabled: bool = Field(
        default=False,
        description=(
            "Append internal chain-of-thought protocols to system prompts. "
            "Off by default. When enabled, models reason through steps "
            "internally; output contracts unchanged. "
            "Set PROMPT_CHAIN_OF_THOUGHT_ENABLED=true to turn on."
        ),
    )
    prompt_dynamic_literature_enabled: bool = Field(
        default=True,
        description=(
            "Retrieve task-relevant exemplars LIVE from the operator literature "
            "corpus (segmented + hybrid-indexed at runtime) and inject them as "
            "fenced phrasing references plus any mined draft->edited few-shot "
            "pairs. Keyed on the live section + notes. Augments the curated "
            "static few-shot; the foreign-fact reducers remain the safety net."
        ),
    )
    literature_corpus_filename: str = Field(
        default="My literature April 2026.docx",
        description=(
            "Operator literature corpus file used for dynamic exemplar retrieval. "
            "Absolute path, or resolved relative to the project root."
        ),
    )
    literature_exemplar_top_k: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Max literature reference exhibits injected per LLM call.",
    )
    literature_exemplar_pairs_max: int = Field(
        default=1,
        ge=0,
        le=4,
        description="Max mined draft->edited few-shot pairs injected per LLM call.",
    )
    literature_exemplar_min_score: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum dense cosine for a literature passage to be injected. Floors "
            "out topically-irrelevant exhibits so we never pad prompts with noise."
        ),
    )
    literature_redact_specifics: bool = Field(
        default=True,
        description=(
            "Redact hard specifics (money, dates, measurements, percentages, URLs, "
            "phone numbers) from literature exhibits before injection so the "
            "phrasing survives but other-property facts cannot bleed in."
        ),
    )
    reference_cross_encoder_enabled: bool = Field(
        default=False,
        description=(
            "Apply the jina-reranker-v3 listwise reranker as the final re-scoring "
            "stage on the reference-mapping shortlist. Prefer USE_RERANKER=true|false. "
            "Off by default (no local Jina). REFERENCE_CROSS_ENCODER_ENABLED is a "
            "legacy alias for the same flag. Degrades gracefully if the model / deps "
            "/ weights are unavailable."
        ),
        validation_alias=AliasChoices(
            "USE_RERANKER",
            "REFERENCE_CROSS_ENCODER_ENABLED",
            "reference_cross_encoder_enabled",
        ),
    )
    reference_cross_encoder_model: str = Field(
        default="jinaai/jina-reranker-v3",
        description=(
            "HuggingFace model id of the reranker. jina-reranker-v3 is a listwise "
            "reranker loaded with trust_remote_code (custom architecture)."
        ),
    )
    reference_cross_encoder_top_n: int = Field(
        default=8,
        ge=2,
        le=50,
        description=(
            "How many top multi-signal candidates to re-score with the "
            "cross-encoder. Kept small to bound CPU latency. Alias: RERANK_TOP_N."
        ),
        validation_alias=AliasChoices(
            "REFERENCE_CROSS_ENCODER_TOP_N",
            "RERANK_TOP_N",
            "reference_cross_encoder_top_n",
        ),
    )
    reference_cross_encoder_doc_chars: int = Field(
        default=1600,
        ge=200,
        le=8000,
        description="Per-candidate character cap fed to the cross-encoder.",
    )
    reference_cross_encoder_dtype: str = Field(
        default="auto",
        description=(
            "Weight dtype for the reranker: 'auto' (float16 on GPU, bfloat16 on CPU "
            "to halve RAM), or an explicit 'float32' / 'float16' / 'bfloat16'. Half "
            "precision keeps the 0.6B model well under ~1.2GB."
        ),
    )
    reference_cross_encoder_device: str = Field(
        default="auto",
        description=(
            "Device for the jina-reranker-v3 reranker: 'auto' (CUDA when available, "
            "else CPU), 'cpu' (force CPU), or 'cuda'. On a small GPU (e.g. 4 GB) the "
            "reranker cannot co-reside with the resident jina embedder — the weight "
            "load / forward pass can hard-abort the process (native CUDA/driver "
            "abort Python cannot catch). Set 'cpu' to keep the embedder on GPU while "
            "the reranker runs in host RAM (bounded latency: top_n candidates only)."
        ),
    )
    reference_cross_encoder_warmup: bool = Field(
        default=False,
        description=(
            "Load the reranker once at server startup instead of lazily on the "
            "first reference mapping. Disabled by default: on Windows hosts with a "
            "small paging file the eager weight load can hard-abort (os error 1455) "
            "before Python can catch it. Set true on servers with ample RAM to "
            "avoid a lazy-load spike mid-generation. Guarded by the free-RAM check "
            "and wrapped non-fatally when enabled."
        ),
    )
    reference_cross_encoder_min_free_gb: float = Field(
        default=1.5,
        ge=0.0,
        le=64.0,
        description=(
            "Minimum free host RAM (GiB) required to load the reranker. The load "
            "path materialises the full fp16 model in host RAM (~1.2 GB) before "
            "moving it to the device, and on a memory-tight host attempting it can "
            "hard-abort the process (OpenBLAS/safetensors OOM) instead of raising. "
            "Below this floor the reranker is skipped and retrieval degrades to "
            "multi-signal. Set 0 to disable the check."
        ),
    )
    retrieval_debug_dump: bool = Field(
        default=False,
        description=(
            "Write the hybrid-retrieval candidates (dense embedder + BM25, RRF-fused) "
            "to a human-readable file BEFORE jina-reranker-v3 reorders them, so you "
            "can audit whether the right chunks are retrieved. Off by default; enable "
            "via RETRIEVAL_DEBUG_DUMP=true. Files land in <data_dir>/retrieval_debug/ "
            "as retrieval_<date>.log (one appended block per section retrieval). "
            "Each block includes tiktoken counts (cl100k_base proxy) for the query, "
            "full chunk, embedder truncation risk, and reranker char-capped feed."
        ),
    )
    retrieval_debug_max_text_chars: int = Field(
        default=1500,
        ge=0,
        le=20000,
        description=(
            "Max characters of each candidate chunk written to the retrieval-debug "
            "dump (0 = full chunk). Keeps the audit file readable when chunks are "
            "large (~8000-char reference chunks)."
        ),
    )
    note_routing_mode: str = Field(
        default="keyword",
        description="Note routing: 'keyword' (deterministic regex) or 'rag' (embedding anchors).",
    )
    note_rag_match_min_score: float = Field(
        default=0.72,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum cosine similarity for a surveyor note to be mapped onto a "
            "canonical section anchor. Below this, the note is surfaced as UNASSIGNED."
        ),
    )
    note_rag_ambiguity_margin: float = Field(
        default=0.05,
        ge=0.0,
        le=0.5,
        description=(
            "Minimum cosine gap between the top two section-anchor matches. When "
            "the margin is narrower, the note is treated as ambiguous and UNASSIGNED."
        ),
    )
    note_baseline_lexical_min_overlap: float = Field(
        default=0.12,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum token-overlap ratio between a note and the section baseline "
            "to allow in-place mapping without a strong per-note RAG hit."
        ),
    )
    paragraph_min_chars: int = Field(default=80, ge=1, le=2000)
    paragraph_max_chars: int = Field(default=1200, ge=100, le=4000)
    chunk_overlap: int = Field(default=120, ge=0, le=1000)
    reference_paragraph_max_chars: int = Field(
        default=8000,
        ge=500,
        le=20000,
        description=(
            "Legacy: unused for REFERENCE section storage. Sections are always "
            "one whole chunk with no character-limit splits."
        ),
    )
    reference_chunk_overlap: int = Field(
        default=1500,
        ge=0,
        le=5000,
        description="Legacy: unused while REFERENCE sections stay one-chunk.",
    )
    reference_one_chunk_per_section: bool = Field(
        default=True,
        description=(
            "Legacy env flag ignored at runtime — REFERENCE sections are always "
            "one chunk each (no paragraph / max-char splitting)."
        ),
    )
    reference_include_section_headings: bool = Field(
        default=True,
        description=(
            "When true, prepend the matched subsection heading (e.g. 'D1 Chimney stacks') "
            "to each leaf chunk body."
        ),
    )
    reference_include_parent_intro: bool = Field(
        default=False,
        description=(
            "Legacy env flag ignored at runtime — leaf baselines never prepend "
            "parent-group intros. Parent intros remain separate stored chunks."
        ),
    )
    metadata_first_retrieval_enabled: bool = Field(
        default=True,
        description=(
            "Retrieve the mapping baseline by EXACT subsection metadata from the "
            "user's own uploaded reports first (section-complete fetch), and only "
            "fall back to semantic similarity search when the subsection is absent "
            "from the index. With section-accurate ingest storage this removes the "
            "similarity guess that caused wrong-section baselines."
        ),
    )
    reference_section_complete_enabled: bool = Field(
        default=True,
        description=(
            "Assemble the WHOLE past-report section as the mapping baseline (every "
            "chunk for the chosen source+section, in document order) rather than only "
            "the top-K semantically nearest chunks. Also lets a section that exists in "
            "the index but was missed by similarity search fall back to a metadata "
            "fetch before degrading to NOTES_ONLY. Disable to restore top-K-only."
        ),
    )
    reference_section_complete_max_chars: int = Field(
        default=12000,
        ge=1000,
        le=40000,
        description=(
            "Safety cap on an assembled section-complete baseline. Chunks are added "
            "in document order until this budget is reached, bounding the mapping "
            "prompt while still covering long (30–50 line) past-report sections."
        ),
    )

    style_injection_enabled: bool = Field(
        default=True,
        description=(
            "Inject the mined per-tenant writing-voice profile into the mapping "
            "system prompt (tone/phrases only). Verbatim same-subsection "
            "paragraphs are NOT injected here — they already appear once as "
            "PAST-REPORT scaffolds in the user message."
        ),
    )

    # ── Generation behaviour ─────────────────────────────────────────────────
    default_survey_level: int = Field(
        default=3,
        ge=1,
        le=3,
        description="Default RICS survey tier (Level 3 → full in-place narrative edit).",
    )
    composition_mode: str = Field(
        default="in_place_edit",
        description="Report composition strategy: style-informed in-place edit on REFERENCE baseline.",
    )
    max_tokens_mapping: int = Field(default=4096, ge=256, le=16000)
    max_tokens_grounding: int = Field(default=1024, ge=256, le=8000)
    max_tokens_repair: int = Field(
        default=900,
        ge=256,
        le=4096,
        description=(
            "Output cap for the surgical repair pass. Repair edits a single "
            "paragraph (subtract-only), so a tight cap speeds completion and "
            "avoids the timeouts seen when it shared the 4096 mapping budget."
        ),
    )
    validation_call_timeout_seconds: float = Field(
        default=60.0,
        ge=5.0,
        le=600.0,
        description=(
            "Per-call timeout for the auditor and repair LLM passes. These are "
            "the quality gate and are given more headroom than the strict "
            "generation-pipeline timeout to avoid wasted circuit-breaker iterations."
        ),
    )
    max_tokens_discovery: int = Field(default=4000, ge=512, le=16000)
    notes_expansion_enabled: bool = Field(
        default=False,
        description="Run the optional notes-expander pass before mapping.",
    )
    use_llm_paragraph_mapping: bool = Field(
        default=True,
        description=(
            "Style-informed in-place edit on the REFERENCE baseline using the "
            "mapping editor prompt. When false, deterministic weave only."
        ),
    )
    mapping_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description=(
            "LLM temperature for past-report (REFERENCE) subsection mapping. "
            "0 is most deterministic; raise slightly (e.g. 0.5) for freer prose."
        ),
    )
    grounding_enabled: bool = Field(
        default=True,
        description="Run the grounding/PII audit on each mapped section before assembly.",
    )
    grounding_alert_threshold: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description=(
            "Fraction of sections needing review above which the preview flags "
            "manual_review_required."
        ),
    )

    # ── Post-generation evaluation (advisory QA; does not block DOCX) ─────────
    evaluation_enabled: bool = Field(
        default=False,
        description=(
            "Master switch for post-generation evaluation. When false, skip all "
            "evaluation LLM calls and omit evaluation from the report preview."
        ),
    )
    evaluation_llm_coverage: bool = Field(
        default=True,
        description=(
            "Approach 2: per-section LLM coverage judge (notes vs generated prose). "
            "When true, every active leaf with observations gets one JSON judge call."
        ),
    )
    evaluation_llm_faithfulness: bool = Field(
        default=False,
        description=(
            "Approach 3: per-section LLM faithfulness/leakage judge (notes + generated "
            "+ past-report baseline). Off by default (extra cost)."
        ),
    )
    evaluation_provider: str = Field(
        default="auto",
        description=(
            "Structured-output provider for evaluation judges: "
            "auto | openai | gemini. auto picks gemini when EVALUATION_MODEL "
            "starts with 'gemini', otherwise openai."
        ),
    )
    evaluation_model: str = Field(
        default="",
        description=(
            "Model for evaluation judges. Empty string uses grounding_model "
            "(OpenAI path) or gemini-3.1-flash-lite when provider=gemini. "
            "Only Gemini judge we use: gemini-3.1-flash-lite."
        ),
    )
    evaluation_temperature: float = Field(
        default=0.2,
        ge=0.0,
        le=2.0,
        description=(
            "LLM temperature for evaluation judges. Only sent when "
            "evaluation_reasoning_effort is none/empty."
        ),
    )
    evaluation_reasoning_effort: str = Field(
        default="none",
        description=(
            "Judge reasoning depth from EVALUATION_REASONING_EFFORT. "
            "OpenAI gpt-5 / o-series: reasoning_effort "
            "(none|minimal|low|medium|high). Default none pairs with "
            "evaluation_temperature. "
            "Gemini: mapped onto thinking_budget where the model supports it."
        ),
    )
    evaluation_max_tokens: int = Field(
        default=4000,
        ge=256,
        le=32000,
        description=(
            "Max completion / output tokens for evaluation judges. "
            "Ignored for OpenAI gpt-5 / o-series (length cap omitted). "
            "Applied as max_output_tokens for Gemini."
        ),
    )
    evaluation_call_timeout_seconds: float = Field(
        default=60.0,
        ge=5.0,
        le=600.0,
        description="Per-call timeout (seconds) for one evaluation LLM call.",
    )
    evaluation_concurrency: int = Field(
        default=4,
        ge=1,
        le=32,
        description=(
            "Max concurrent evaluation LLM calls (separate from mapping concurrency)."
        ),
    )
    evaluation_coverage_pass_threshold: float = Field(
        default=0.95,
        ge=0.0,
        le=1.0,
        description=(
            "Report rollup PASS when coverage_rate >= this value (advisory only)."
        ),
    )
    evaluation_coverage_warn_threshold: float = Field(
        default=0.80,
        ge=0.0,
        le=1.0,
        description=(
            "Report rollup WARN when coverage_rate >= this value but below PASS; "
            "else FAIL (advisory only)."
        ),
    )

    ai_transparency_footer_enabled: bool = Field(
        default=False,
        description="Append an AI transparency footer to generated DOCX when enabled.",
    )
    template_docx_path: str = Field(
        default="",
        description="Optional branded DOCX template path for report export.",
    )

    # ── Report post-processing (final cleanup pass) ───────────────────────────
    postprocess_enabled: bool = Field(
        default=True,
        description="Master switch for the final report post-processing/normalisation pass.",
    )
    dedup_similarity_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Character-trigram Jaccard threshold for near-duplicate paragraph removal (lower = more aggressive).",
    )
    extra_header_patterns: list[str] = Field(
        default_factory=list,
        description="Firm-specific header/artifact regex strings to strip during post-processing (keeps the pipeline firm-agnostic).",
    )
    postprocess_placeholder_pattern: str = Field(
        default=r"\[{1,2}REDACTED_[A-Z]+(?:_\d+)?\]{1,2}",
        description="Regex matching redaction tokens for post-processing grammar repair.",
    )
    postprocess_debug: bool = Field(
        default=False,
        description="When true, the post-processor prints a before/after preview to stdout.",
    )

    # ── Property-type retrieval guard ─────────────────────────────────────────
    property_guard_enabled: bool = Field(
        default=False,
        description=(
            "Legacy flag — property-type chunk dropping is retired. Retrieval "
            "always keeps past-report baselines; foreign terminology is handled "
            "by anti-bleed + auditor. Kept so existing env files do not break."
        ),
    )
    property_blocklist_extra_terms: list[str] = Field(
        default_factory=list,
        description="Additional firm-specific terms that mark a retrieved paragraph as property-incompatible.",
    )

    # ── Upload limits (batch + ZIP + notes extract) ───────────────────────────
    max_single_upload_bytes: int = Field(
        default=50 * 1024 * 1024,
        ge=1024 * 1024,
        le=200 * 1024 * 1024,
        description="Max bytes per uploaded reference file (single or inside ZIP).",
    )
    max_zip_members: int = Field(
        default=40,
        ge=1,
        le=200,
        description="Max non-directory entries allowed inside an uploaded ZIP.",
    )
    max_zip_uncompressed_bytes: int = Field(
        default=200 * 1024 * 1024,
        ge=1024 * 1024,
        le=1024 * 1024 * 1024,
        description="Max total uncompressed size of all files in a ZIP.",
    )
    max_notes_extract_bytes: int = Field(
        default=10 * 1024 * 1024,
        ge=64 * 1024,
        le=50 * 1024 * 1024,
        description="Max bytes for /extract-notes uploads.",
    )

    # ── Section photos & vision ────────────────────────────────────────────────
    max_section_photo_bytes: int = Field(
        default=8 * 1024 * 1024,
        ge=256 * 1024,
        le=50 * 1024 * 1024,
        description="Max bytes per uploaded section photo.",
    )
    max_section_photos_per_section: int = Field(
        default=5,
        ge=0,
        le=50,
        description="Max photos stored per report section.",
    )
    max_section_photos_for_ai: int = Field(
        default=2,
        ge=0,
        le=10,
        description="Max photos per section the user may select for AI vision analysis.",
    )
    section_photo_vision_enabled: bool = Field(
        default=True,
        description="When true and OpenAI is configured, analyze selected section photos at generation.",
    )
    vision_model: str = Field(
        default="gpt-4o",
        description="OpenAI vision-capable model for section photo analysis.",
    )
    vision_max_tokens: int = Field(
        default=1200,
        ge=256,
        le=4096,
        description="Token budget for a section photo vision analysis call.",
    )
    vision_timeout_seconds: float = Field(
        default=90.0,
        ge=10.0,
        le=300.0,
        description="Hard timeout per vision API call (seconds).",
    )
    vision_max_observations: int = Field(
        default=12,
        ge=4,
        le=40,
        description="Max observation lines merged from vision per section.",
    )

    # ── Observability (local-only telemetry) ─────────────────────────────────
    # All observability is local: telemetry is written under the DATA_DIR and, when
    # tracing is enabled, exported to a localhost OTLP/Phoenix collector. No prompt
    # or completion text is recorded and nothing leaves the machine.
    observability_enabled: bool = Field(
        default=True,
        description=(
            "Master switch for local runtime telemetry: per-LLM-call latency / token "
            "/ cost records and per-report quality metrics, written as JSONL under "
            "the metrics dir. Passive (no text captured); safe to leave on. Disable "
            "to make every recorder a no-op."
        ),
    )
    observability_metrics_dir: str = Field(
        default="",
        description=(
            "Directory for local metrics JSONL (llm_calls.jsonl, reports.jsonl). "
            "Empty resolves to '<data_dir>/metrics'. Absolute or repo-relative."
        ),
    )
    observability_console_log_calls: bool = Field(
        default=False,
        description=(
            "Also emit one INFO log line per LLM call (label/model/latency/tokens/"
            "cost). Off by default to keep generation logs readable; the JSONL sink "
            "always records regardless."
        ),
    )
    observability_tracing_enabled: bool = Field(
        default=False,
        description=(
            "Emit OpenTelemetry spans (parent per report; children for retrieval, "
            "rerank, each section map, each validation iteration) to a local OTLP "
            "collector such as Arize Phoenix. Off by default and fully no-op when "
            "the OTel packages or the endpoint are unavailable, so CI/offline runs "
            "are never affected."
        ),
    )
    observability_otlp_endpoint: str = Field(
        default="http://127.0.0.1:6006/v1/traces",
        description=(
            "OTLP/HTTP traces endpoint for the local collector (Arize Phoenix "
            "default). Used only when observability_tracing_enabled is true."
        ),
    )
    observability_service_name: str = Field(
        default="rics-rag-backend",
        description="OpenTelemetry service.name resource attribute for emitted spans.",
    )
    model_pricing: dict[str, list[float]] = Field(
        default_factory=lambda: {
            # USD per 1,000,000 tokens, as [input, output]. Embeddings have no
            # output cost (output element is 0.0). Approximate list-price values —
            # override via the MODEL_PRICING env var (JSON) for exact accounting.
            # Matched by exact id first, then by longest key prefix.
            "gpt-5-nano": [0.05, 0.40],
            "gpt-5.4-nano": [0.20, 1.25],
            # Confirmed OpenAI list price after 80% reduction (input, output).
            "gpt-5.6-luna": [0.20, 1.20],
            "gpt-4o-mini": [0.15, 0.60],
            "gpt-4o": [2.50, 10.00],
            "gpt-4.1-mini": [0.40, 1.60],
            "gpt-4.1": [2.00, 8.00],
            "gemini-2.5-flash-lite-preview-09-2025": [0.10, 0.40],
            "gemini-3.1-flash-lite": [0.25, 1.50],
            "text-embedding-3-small": [0.02, 0.0],
            "text-embedding-3-large": [0.13, 0.0],
            "text-embedding-ada-002": [0.10, 0.0],
        },
        description=(
            "Token pricing table (USD per 1M tokens, [input, output]) used to "
            "estimate per-call and per-report cost. Override via env for exact "
            "rates; unknown models cost 0.0 (recorded but not priced)."
        ),
    )
    # ── Per-tenant cost ledger (DATA_DIR/tenants/<id>/costs/) ─────────────────
    cost_tracking_enabled: bool = Field(
        default=True,
        description=(
            "Master switch for the per-tenant cost ledger (LlamaParse pages, "
            "OpenAI embeddings, LLM tokens). Writes under "
            "tenants/<id>/costs/. Safe to leave on; disable to no-op every "
            "recorder."
        ),
    )
    llamaparse_credits_per_page: dict[str, float] = Field(
        default_factory=lambda: {
            # Published LlamaParse credits / page by tier (confirm against plan).
            "fast": 1.0,
            "cost_effective": 3.0,
            "agentic": 10.0,
            "agentic_plus": 45.0,
        },
        description=(
            "LlamaParse credits charged per page for each parse tier. Used as "
            "pages × credits_per_page[tier] × llamaparse_usd_per_credit."
        ),
    )
    llamaparse_usd_per_credit: float = Field(
        default=0.001,
        ge=0.0,
        description=(
            "USD per LlamaParse credit (default 0.001 ≈ 1000 credits per $1). "
            "Override to match your plan; the only knob needed to reprice all "
            "parse events."
        ),
    )
    llamaparse_legacy_assumed_tier: str = Field(
        default="agentic",
        description=(
            "Tier assumed when the legacy llama_parse engine serves a job "
            "without forwarding LLAMA_PARSE_TIER. Events are marked "
            "priced_assumed=true."
        ),
    )

    # ── Context construction (flag-gated; eval before enabling) ───────────────
    context_reorder_enabled: bool = Field(
        default=False,
        description=(
            "Lost-in-the-middle mitigation for the MULTI-SOURCE reference merge: "
            "reorder merged sentences edges-in (highest note-relevance at the head "
            "and tail, lowest in the middle) so salient context is not buried where "
            "long-context models attend least. Scoped to combine_reference_blocks "
            "extras only — a single coherent section keeps its document order. Off "
            "until the golden grounding/coverage + retrieval benchmark confirm no "
            "regression."
        ),
    )
    context_compression_enabled: bool = Field(
        default=False,
        description=(
            "Relevance-aware extractive compression when an assembled "
            "section-complete baseline exceeds reference_section_complete_max_chars: "
            "keep the sentences with the highest note overlap within budget instead "
            "of a positional tail-cut. Deterministic/extractive (no LLM, no new "
            "invention surface). Off until eval-confirmed."
        ),
    )

    # ── Text normalization (flag-gated; eval before enabling) ─────────────────
    text_normalize_enabled: bool = Field(
        default=False,
        description=(
            "Apply unified text normalization (NFKC, smart-quote/dash folding, PDF "
            "de-hyphenation, whitespace collapse) at reference ingest and on the "
            "retrieval query. Preserves RICS section codes and never alters PII "
            "scrubbing. Off until the retrieval benchmark confirms no regression."
        ),
    )

    # ── Auth ─────────────────────────────────────────────────────────────────
    jwt_secret: str = Field(
        default="change-me-in-production",
        description="HMAC secret for signing tenant JWTs.",
    )
    jwt_algorithm: str = Field(default="HS256")
    jwt_expiry_minutes: int = Field(default=60 * 24, ge=5, le=60 * 24 * 30)
    admin_token: str = Field(
        default="",
        description="Static admin token required (in addition to JWT) for /admin routes.",
    )
    internal_service_token: str = Field(
        default="",
        description=(
            "Shared secret for Node BFF → Python internal routes "
            "(/internal/v1/...). When empty, internal routes also accept tenant JWT "
            "(local/dev). Set in production and pass as X-Service-Token."
        ),
    )
    standard_paragraphs_top_k: int = Field(
        default=20,
        ge=1,
        le=50,
        description=(
            "Deprecated alias for per-issue Top-K when "
            "STANDARD_PARAGRAPHS_PER_ISSUE_TOP_K is unset in older envs."
        ),
    )
    standard_paragraphs_per_issue_top_k: int = Field(
        default=3,
        ge=1,
        le=20,
        description=(
            "Top-K standard paragraphs retrieved per decomposed note issue "
            "(section-scoped hybrid)."
        ),
    )
    standard_paragraphs_merged_top_k: int = Field(
        default=20,
        ge=1,
        le=50,
        description=(
            "Cap on merged/deduped SP candidates stored on the retrieval "
            "manifest after per-finding retrieval."
        ),
    )
    standard_paragraphs_min_match_score: float = Field(
        default=0.22,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum dense cosine score for a retrieved SP to count as a "
            "strong match for a finding. Below this → "
            "'No strong approved match' in the generation prompt."
        ),
    )
    standard_paragraphs_decompose_notes: bool = Field(
        default=False,
        description=(
            "When true, lightly LLM-decompose multi-issue note blobs and "
            "retrieve SPs per finding. Keep false until standalone decompose "
            "tests look good; generation then uses single-query retrieve."
        ),
    )
    standard_paragraphs_temperature: float = Field(
        default=0.2,
        ge=0.0,
        le=2.0,
        description=(
            "LLM temperature for standard-paragraph subsection generation. "
            "Keep low (e.g. 0.2) for factual, notes-first RICS prose. "
            "Only sent when standard_paragraphs_reasoning_effort is none/empty."
        ),
    )
    standard_paragraphs_reasoning_effort: str = Field(
        default="none",
        description=(
            "OpenAI gpt-5 / o-series reasoning_effort for SP generation "
            "(none|minimal|low|medium|high). When not none, temperature is "
            "omitted from the API call."
        ),
    )
    standard_paragraphs_style_samples_enabled: bool = Field(
        default=False,
        description=(
            "When true, inject past uploaded REFERENCE subsection samples into "
            "the SP generation prompt as style/length exemplars only. "
            "Findings + approved SPs remain authoritative for facts."
        ),
    )
    standard_paragraphs_style_samples_max: int = Field(
        default=2,
        ge=1,
        le=5,
        description=(
            "Max past-report subsection samples to inject when "
            "standard_paragraphs_style_samples_enabled is true."
        ),
    )
    standard_paragraphs_max_upload_bytes: int = Field(
        default=50 * 1024 * 1024,
        ge=1024,
        description="Max upload size for standard-paragraph ingest (Word or PDF).",
    )

    # ── Content-based topic mode (parallel to RICS L3 structure mode) ──────────
    content_mode_enabled: bool = Field(
        default=True,
        description=(
            "Master switch for the content-based topic report mode. When true, "
            "clients may request structure_mode='content' to classify notes, past "
            "reports and standard paragraphs by a fixed property topic taxonomy "
            "(Location & Facilities, Outside, Inside, Services, Grounds, Rooms "
            "Described, Other) instead of by RICS Level 3 structure."
        ),
        validation_alias=AliasChoices(
            "CONTENT_MODE_ENABLED", "content_mode_enabled"
        ),
    )
    content_classifier_llm_enabled: bool = Field(
        default=True,
        description=(
            "When true, the LLM is the PRIMARY content classifier: text with no exact "
            "RICS leaf code is placed by meaning by the model, and the embedding-anchor "
            "match is only the fallback for what the LLM did not resolve. Turn off to "
            "run embedding-anchor classification alone (no token cost, lower accuracy)."
        ),
        validation_alias=AliasChoices(
            "CONTENT_CLASSIFIER_LLM_ENABLED", "content_classifier_llm_enabled"
        ),
    )
    content_classification_model: str = Field(
        default="gpt-5-nano",
        description=(
            "Model for the LLM topic-classification pass (JSON output). "
            "Kept on the cheap JSON-disciplined model."
        ),
        validation_alias=AliasChoices(
            "CONTENT_CLASSIFICATION_MODEL", "content_classification_model"
        ),
    )
    content_classification_timeout_seconds: float = Field(
        default=60.0,
        ge=5.0,
        le=600.0,
        description="Per-call timeout (seconds) for the LLM topic classifier.",
    )
    content_classification_max_tokens: int = Field(
        default=4000,
        ge=256,
        le=32000,
        description=(
            "max_completion_tokens for the LLM topic classifier. Ignored by the client "
            "when content_classification_reasoning_effort is none/minimal, because a "
            "hard cap shared with hidden reasoning can return empty content."
        ),
    )
    content_classification_reasoning_effort: str = Field(
        default="minimal",
        description=(
            "OpenAI gpt-5 / o-series reasoning_effort for topic classification "
            "(none|minimal|low|medium|high). Default minimal matches ingest "
            "segmentation: enough for a fixed-taxonomy choice, and it drops the "
            "output cap so the JSON always fits. Raise to low/medium if snippets "
            "are being placed in the wrong topic."
        ),
        validation_alias=AliasChoices(
            "CONTENT_CLASSIFICATION_REASONING_EFFORT",
            "content_classification_reasoning_effort",
        ),
    )
    content_classification_window_size: int = Field(
        default=40,
        ge=1,
        le=200,
        description=(
            "Snippets per LLM classification call. Ingest can hand the classifier "
            "hundreds of chunks at once; they are windowed so no single call exceeds "
            "the context budget. Lower it if long chunks cause truncated JSON."
        ),
        validation_alias=AliasChoices(
            "CONTENT_CLASSIFICATION_WINDOW_SIZE", "content_classification_window_size"
        ),
    )
    content_classification_max_chars: int = Field(
        default=1200,
        ge=200,
        le=8000,
        description=(
            "Per-snippet character cap sent to the LLM classifier. Enough of a chunk "
            "to judge its topic without paying for the whole paragraph."
        ),
        validation_alias=AliasChoices(
            "CONTENT_CLASSIFICATION_MAX_CHARS", "content_classification_max_chars"
        ),
    )
    content_topic_min_score: float = Field(
        default=0.30,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum dense cosine score between a text and a topic/sub-topic anchor "
            "for a confident content classification in the FALLBACK embedding pass "
            "(LLM unavailable, disabled, or silent on that snippet). Below this the "
            "text falls to the 'Other / General Observations' catch-all and is "
            "flagged needs_review."
        ),
    )
    content_room_detection_enabled: bool = Field(
        default=True,
        description=(
            "Detect room-by-room descriptions and route them to the 'Rooms Described' "
            "topic (dynamic room sub-topics) instead of an element topic."
        ),
    )
    topic_retrieval_boost: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description=(
            "FAISS score boost when a chunk's topic_id matches the requested topic in "
            "content-mode retrieval (analogue of retrieval_section_boost). Currently "
            "unused: topic-scoped retrieval filters on topic_id rather than boosting."
        ),
    )
    tag_retrieval_boost: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        description=(
            "Proportional ranking preference for chunks sharing a cross-cutting theme "
            "tag (damp, movement, ...) with the request: 0.15 means +15%. Applied to "
            "whichever key sorts (dense or hybrid fusion), within an already "
            "topic-scoped result set, so it reorders rather than widens. 0 disables."
        ),
    )
    content_min_chunk_chars: int = Field(
        default=80,
        ge=0,
        description=(
            "Minimum chunk length to be usable as a style exemplar in content mode. "
            "Filters out form-field rows ('Conservatory: not applicable') that are "
            "worthless as prose baselines. 0 disables the filter."
        ),
    )

    # ── Note intake: semantic filing of raw site notes (stage A) ──────────────
    note_intake_enabled: bool = Field(
        default=True,
        description=(
            "Use the LLM to extract and classify a raw note blob under the 41 "
            "schema codes. Each chip gets preserved raw source wording (or "
            "'No specific information provided.'). Off leaves notes unfiled "
            "(returned as unassigned) rather than calling out."
        ),
    )
    note_intake_model: str = Field(
        default="gpt-5.6-luna",
        description=(
            "Model for Stage A extraction/classification. Empty uses "
            "GROUNDING_MODEL. Long context (full SCHEMA + source) with structured "
            "JSON out covering every destination."
        ),
    )
    note_intake_timeout_seconds: float = Field(
        default=300.0,
        gt=0,
        description=(
            "Per-call timeout for Stage A. Higher than most stages because one call "
            "classifies atomic observations into every SCHEMA destination."
        ),
    )
    note_intake_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description=(
            "LLM temperature for Stage A extraction/classification. Keep at 0 for "
            "stable filing; raise only if you need freer classification. Only sent "
            "to the API when note_intake_reasoning_effort is none/empty (gpt-5.6 / "
            "luna omit temperature when reasoning is on)."
        ),
    )
    note_intake_reasoning_effort: str = Field(
        default="low",
        description=(
            "Reasoning effort for Stage A on models that support it "
            "(none|minimal|low|medium|high). When not none, temperature is omitted "
            "from the API call. Set to none to apply NOTE_INTAKE_TEMPERATURE."
        ),
    )
    # Legacy knobs (unused by semantic Stage A; kept so existing .env keys load).
    note_intake_max_tokens: int = Field(
        default=32000,
        ge=256,
        description=(
            "Unused by Stage A (no output token cap is sent). Kept so existing "
            ".env keys still load."
        ),
    )
    note_intake_max_lines: int = Field(
        default=120,
        ge=10,
        le=1000,
        description="Unused by semantic Stage A; kept for .env compatibility.",
    )
    note_intake_carve_enabled: bool = Field(
        default=True,
        description="Unused by semantic Stage A; kept for .env compatibility.",
    )
    note_intake_carve_trigger_chars: int = Field(
        default=240,
        ge=80,
        le=4000,
        description="Unused by semantic Stage A; kept for .env compatibility.",
    )
    note_intake_span_min_chars: int = Field(
        default=12,
        ge=4,
        le=200,
        description="Unused by semantic Stage A; kept for .env compatibility.",
    )
    note_intake_max_secondary: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Unused by semantic Stage A; kept for .env compatibility.",
    )
    note_intake_min_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Unused by semantic Stage A; kept for .env compatibility.",
    )

    # ── Note quality: grade each sub-topic against the practice rubric (stage B)
    note_quality_enabled: bool = Field(
        default=True,
        description=(
            "Grade each content-mode sub-topic Green/Yellow/Red against the practice's "
            "note-quality rubric (backend/note_quality/rubric.py) and colour its chip. "
            "Off leaves the chips on plain has-notes/empty colouring."
        ),
    )
    note_quality_model: str = Field(
        default="",
        description=(
            "Model for the note-quality judge. Empty uses GROUNDING_MODEL. This is a "
            "judgement task against normative prose — a nano-class model tends to mark "
            "everything Green, so do not point it at the classifier model by default."
        ),
    )
    note_quality_timeout_seconds: float = Field(
        default=60.0,
        gt=0,
        description="Per-call timeout for one report group of the note-quality judge.",
    )
    note_quality_max_tokens: int = Field(
        default=4000,
        ge=256,
        description=(
            "Output cap for one note-quality judge call. Each graded sub-topic returns "
            "a grade plus short present/missing lists."
        ),
    )
    note_quality_reasoning_effort: str = Field(
        default="low",
        description=(
            "Reasoning effort for the note-quality judge (minimal|low|medium|high). "
            "The rubric asks for a 'meaningful inspection assessment' judgement, so "
            "minimal tends to over-award Green."
        ),
    )
    note_quality_max_chars: int = Field(
        default=2000,
        ge=200,
        description=(
            "Per-sub-topic character cap on the notes sent to the judge. Enough to "
            "judge completeness without paying for a whole dictated section."
        ),
    )
    note_quality_concurrency: int = Field(
        default=4,
        ge=1,
        le=32,
        description=(
            "Concurrent note-quality judge calls. The surveyor is waiting, so this is "
            "higher than a background job would use."
        ),
    )

    @model_validator(mode="after")
    def _resolve_embedding_provider(self) -> Settings:
        """Apply USE_OPENAI_EMBEDDINGS over EMBEDDING_PROVIDER when set."""
        if self.use_openai_embeddings is True:
            object.__setattr__(self, "embedding_provider", "openai")
        elif self.use_openai_embeddings is False:
            object.__setattr__(self, "embedding_provider", "local")
        provider = (self.embedding_provider or "openai").strip().lower()
        if provider not in ("local", "openai"):
            raise ValueError(
                f"embedding_provider must be 'local' or 'openai', got {provider!r}"
            )
        object.__setattr__(self, "embedding_provider", provider)
        return self

    # ── Helpers ──────────────────────────────────────────────────────────────
    def resolve_path(self, value: str | Path) -> Path:
        """Resolve a possibly repo-relative path to an absolute path."""
        p = Path(value)
        return p if p.is_absolute() else (REPO_ROOT / p)

    @property
    def report_template_path(self) -> Path:
        """Absolute path to the report template (PDF) — schema authority."""
        return (
            self.resolve_path(self.master_template_dir) / self.report_template_filename
        )

    @property
    def standard_paragraphs_path(self) -> Path:
        """Absolute path to the standard-paragraphs Word file — MASTER RAG authority."""
        name = self.standard_paragraphs_filename or self.master_template_filename
        return self.resolve_path(self.master_template_dir) / name

    @property
    def master_template_path(self) -> Path:
        """Backward-compatible alias for :attr:`standard_paragraphs_path`."""
        return self.standard_paragraphs_path

    @property
    def reference_dir_path(self) -> Path:
        """Absolute path to the folder scanned for reference auto-ingest."""
        target = self.reference_auto_ingest_dir or self.master_template_dir
        return self.resolve_path(target)

    @property
    def data_dir_path(self) -> Path:
        return self.resolve_path(self.data_dir)

    @property
    def rag_top_k(self) -> int:
        """Spec alias for :attr:`retrieval_top_k`."""
        return self.retrieval_top_k

    @property
    def confidence_threshold(self) -> float:
        """Alias for per-note REFERENCE match gate (CURSOR_REFACTOR parity)."""
        return self.note_rag_match_min_score

    @property
    def branded_template_path(self) -> Path | None:
        if not self.template_docx_path.strip():
            return None
        p = self.resolve_path(self.template_docx_path)
        return p if p.is_file() else None


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()


settings = get_settings()

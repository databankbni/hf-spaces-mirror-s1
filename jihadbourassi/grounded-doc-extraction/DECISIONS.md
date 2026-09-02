# Architectural decisions

Format: Decision / Evidence / Alternatives / Reason / Consequences.
Entries are appended, never rewritten silently.

---

## D-001 — Phase 0 is a deployment smoke test, before any extraction logic

Decision:
: Ship a Space that only proves the runtime can host the dependency stack.

Evidence:
: None yet at the time of the decision — that is the point. The unknowns
  (ZeroGPU behaviour, OCR install, cold start, anonymous quota) all sit in the
  runtime, not in the ML.

Alternatives:
: Build the pipeline first and deploy at the end (the classic failure mode:
  discover on day 20 that the chosen OCR engine cannot be installed on the target).

Reason:
: The recruitment criterion is "a link that actually works". Runtime risk is the
  project's dominant risk, so it is retired first.

Consequences:
: One extra deploy cycle up front. Phase 5 reuses this Space rather than creating
  a second one.

---

## D-002 — OCR engine candidate: `rapidocr-onnxruntime` (PP-OCRv4 via ONNX Runtime)

Decision:
: Use `rapidocr-onnxruntime==1.4.4` as the Phase 0 OCR candidate, with PaddleOCR
  kept as a fallback candidate only if quality proves insufficient in Phase 3.

Evidence:
: Verified locally (1 vCPU container): install from PyPI succeeds on Python 3.12;
  detection/recognition/angle ONNX models (16.2 MB total) are shipped *inside the
  wheel*, so there is no runtime model download; engine init 0.53 s; first page
  7.6 s; warm page 4.4 s at 200 dpi (1654x2339); all four planted fields
  (`BH-2024-017`, `412345.6`, `287654.3`, `25.40`) recovered at mean confidence
  0.973, each with a bounding box.

Alternatives:
: PaddleOCR (the engine used in the earlier private project) — heavier install,
  `paddlepaddle` wheel, and it downloads weights at first use from an external
  host, which is an extra runtime failure mode on a Space. Tesseract — needs apt
  packages and is weaker on this kind of scan. docTR — heavier, torch-based.

Reason:
: Same underlying PP-OCR models as the previous approach, none of the deployment
  fragility. No external model host in the request path.

Consequences:
: OCR runs on CPU. At ~4 s/page a 20-page report is ~80 s, which is what makes the
  page prefilter in Phase 3 a requirement rather than an optimisation.

Update (2026-08-16, measured on the Space):
: Remote OCR is roughly 3x slower than local — ~18–20 s first page, ~12–13 s warm.
  The cause of the gap was measured but not isolated; CPU allocation, thread
  limits, contention and I/O are all plausible and untested. In the synthetic
  smoke test this makes one warm OCR page (~12–13 s) materially more expensive
  than one short synthetic generation (~2.2 s, ~120-token prompt) — a narrow
  comparison, not a statement about the real system, since real document contexts
  and real RAG / Direct-LLM prompt sizes are still unmeasured. The engine choice
  stands (nothing here is engine-specific). Working hypothesis for Phase 3, to be
  re-tested against real documents: OCR cost may dominate the latency budget, so
  raster DPI, downscaling, prefiltering and caching deserve treatment as
  first-class latency work. See K-006.

---

## D-003 — PDF rasterisation via `pypdfium2`

Decision:
: `pypdfium2==5.6.0`, render at 200 dpi by default.

Evidence:
: 0.18 s for an A4 page to 1654x2339 px locally. Pure-wheel install, no system
  dependencies, permissive licensing (PDFium: BSD-3-Clause / Apache-2.0).

Alternatives:
: `pdf2image` (needs poppler installed via apt), PyMuPDF (AGPL — a redistribution
  constraint we do not want in a public demo).

Reason:
: No apt dependency, no licence friction, fast.

Consequences:
: DPI becomes a tunable that trades OCR accuracy against latency; to be measured
  in Phase 3.

---

## D-004 — Phase 0 candidate LLM: `Qwen/Qwen3-4B-Instruct-2507`

Decision:
: Use it as the Phase 0 *feasibility* candidate only. The binding choice is made
  in Phase 7, after real OCR token counts are measured.

Evidence:
: Apache-2.0; ~8 GB in bf16, well inside the 48 GB of a default ZeroGPU slice;
  262k native context, which keeps the Direct-LLM baseline (Phase 10) an open
  question rather than a foregone conclusion; non-thinking variant, so no
  reasoning-block parsing.

Alternatives:
: Deferred to Phase 7 on purpose — choosing a model before measuring the context
  requirement is the mistake the spec explicitly forbids.

Reason:
: Phase 0 needs *a* representative model to prove the runtime, not the best model.

Consequences:
: If Phase 7 selects a different model, only `LLM_MODEL_ID` changes; the smoke
  test itself is model-agnostic via the `GDE_LLM_MODEL_ID` environment variable.

---

## D-005 — LLM placement on CUDA happens at module startup, not at request time

**Superseded implementation, 2026-08-16.** The original entry stated the correct
principle ("load in the parent process") but the code implemented lazy loading
from a Gradio request handler and used "is the `spaces` package importable?" as
the test for "are we on ZeroGPU?". Recorded here rather than rewritten, because
the gap between a stated decision and its implementation is the interesting part.

Decision:
: `load_llm()` runs at module import, gated on the `SPACES_ZERO_GPU` environment
  variable. The `@spaces.GPU`-decorated `_generate()` only runs the forward pass.
  On ZeroGPU, `check_llm()` never loads — if the model is absent it reports the
  startup failure.

Evidence:
: Deployment on the Space failed with
  `RuntimeError: Low-level CUDA init (torch._C._cuda_init) reached` at
  `model.to("cuda")` inside `load_llm()`, called from a request. HF ZeroGPU
  documentation: model placement on `cuda` must happen at root/module level,
  where the CUDA emulation layer intercepts it; outside that window the call
  reaches real CUDA in a process that has no GPU attached.

Alternatives:
: Move the load inside `@spaces.GPU` (works, but reloads ~8 GB per call and
  burns the visitor's GPU quota on loading rather than inference).

Reason:
: It is the documented pattern, and it keeps per-request GPU seconds equal to
  generation time — which is what the anonymous-visitor quota is spent on.

Consequences:
: Space startup now includes the model download, so cold start moves from the
  first LLM click to Space boot. `GDE_DISABLE_STARTUP_LLM=1` disables the startup
  load as a Space variable if it ever threatens the startup timeout.

Verified (2026-08-16, on the Space):
: `llm_ready_from_startup=True`, `llm_startup_error=None`. Startup load ~7.6–8.0 s
  for ~8.04 GB of packed tensors — well inside the startup budget. The emulated
  placement survives into the forked `@spaces.GPU` worker: inference reports
  `ran_on=cuda:0`, ~2.0–2.3 s per generation, ~25–29 tokens/s, ~8.14 GB peak VRAM.
  Confirmed working for an unauthenticated visitor (4.095 s total). The pattern is
  correct; a transient allocation failure observed later is recorded in K-009,
  with its relationship to this pattern unconfirmed.

---

## D-007 — Environment detection must not be inferred from package availability

Decision:
: `ON_ZEROGPU = _env_flag("SPACES_ZERO_GPU")`. `GPU_DECORATOR_AVAILABLE` is
  demoted to a reported fact, never a control-flow signal.

Evidence:
: The `spaces` package is in `requirements.txt` and installs anywhere, including
  a laptop with no GPU. Using its importability as a proxy for the runtime is
  what produced the D-005 failure.

Alternatives:
: `torch.cuda.is_available()` alone — false on a ZeroGPU main process, so it
  would silently keep the model on CPU and never use the GPU at all.

Reason:
: Capability of a library and identity of an environment are different questions.

Consequences:
: Three explicit paths, all tested: ZeroGPU (startup load, emulated placement),
  real local GPU (lazy load, real placement), CPU (lazy load, no placement).


---

## D-006 — `torch` is deliberately not pinned in `requirements.txt`

Decision:
: Let the ZeroGPU base image provide torch.

Evidence:
: HF documents supported torch versions 2.8.0 → latest for ZeroGPU; PyPI's current
  latest (2.13.0) is outside the explicitly listed set. A pin also risks a
  multi-gigabyte reinstall of a CUDA build at every rebuild.

Alternatives:
: Pin an exact version (reproducible but fragile against the image's CUDA build).

Reason:
: The image's torch is CUDA-matched by construction; ours would not be.

Consequences:
: Local and Space torch versions may differ. The runtime report prints the actual
  version so the difference is always visible rather than assumed.

---

## D-008 — Phase 0 accepted: the deployment target is confirmed, Phase 1 may begin

Decision:
: Hugging Face Space + Gradio + ZeroGPU is confirmed as the deployment
  architecture for this project. Phase 0 is closed and Phase 1 (BGS/SOBI data
  audit) is unblocked.

Evidence (measured on the Space, 2026-08-16):
: - Space builds and starts; public URL reachable from an Incognito window with
    no authentication.
  - `runtime_report`: Python 3.12.12, ZeroGPU detected, `llm_ready_from_startup=True`,
    `llm_startup_error=None`.
  - `pdf_rasterization`: PASS.
  - `ocr_cpu`: PASS, 4/4 planted fields, mean confidence 0.973, ~18–20 s first
    page / ~12–13 s warm.
  - `embeddings`: PASS, `bge-small-en-v1.5`, dim 384.
  - `llm_structured_extraction`: PASS repeatedly — model prepared at startup on
    `cuda:0` (~7.6–8.0 s, ~8.04 GB packed), generation ~2.0–2.3 s, ~25–29 tok/s,
    ~8.14 GB peak VRAM, valid JSON, 4/4 synthetic fields.
  - Unauthenticated visitor: full LLM inference in 4.095 s total (2.219 s
    generation, 26.1 tok/s, `ran_on=cuda:0`, JSON parse OK, all fields correct).

What this decision does NOT claim:
: - **Extraction quality is not validated.** The document is synthetic and the
    values were planted by the same code that checks them. No accuracy,
    grounding or hallucination claim follows from any Phase 0 number. See K-010.
  - **`Run all` is not validated end-to-end.** One invocation failed with a
    transient ZeroGPU allocation error (K-009). Individual checks pass.
  - **Sleep → wake latency is unmeasured.**

Alternatives:
: Docker Space on paid GPU hardware (predictable allocation, ongoing cost);
  CPU-only Space (no LLM methods, which would delete the comparative experiment
  that is the point of the project).

Reason:
: Every question Phase 0 existed to answer has an answer backed by a measurement,
  including the one that mattered most — a stranger with no account can trigger
  real GPU inference on this link.

Consequences:
: - Latency behaviour is known only for the synthetic smoke test, where one warm
    OCR page costs materially more than one short generation. Whether OCR
    dominates the real pipeline is unmeasured; Phase 3 owns that question, and
    Phase 7 may revise it once real prompt sizes exist.
  - GPU allocation must be treated as fallible from Phase 5 onward: allocation
    failure surfaces as a clear status, and the Expert pipeline (no GPU) is the
    natural degraded mode.
  - The Phase 0 Space is reused and grown into the product rather than replaced,
    so this runtime configuration is now load-bearing and changes to it need a
    reason and a re-measurement.

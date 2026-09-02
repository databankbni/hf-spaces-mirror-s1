# Known issues and open questions

Each entry: what, why it matters, how it will be resolved.
Resolved entries are kept, marked, and dated — the history is part of the record.

## K-001 — LLM and embedding success paths unverified — RESOLVED 2026-08-16
Both were written blind: the development sandbox has no access to
`huggingface.co`. Both now PASS on the Space. Embeddings: `bge-small-en-v1.5`,
dim 384. LLM: `Qwen3-4B-Instruct-2507` loads at startup on `cuda:0` and returns
valid JSON. Nothing further to do.

## K-002 — `transformers==5.15.0` major-version API drift — RESOLVED 2026-08-16
The `from_pretrained(dtype=...)` / `torch_dtype=...` fallback in `load_llm()`
was never exercised in anger. The Space loads the model without error, so the
pinned version's API matches the primary call path. The fallback stays as cheap
insurance.

## K-003 — `sdk_version: 6.24.0` whitelisting — RESOLVED 2026-08-16
The Space builds and starts on the pinned Gradio version. No change needed.

## K-004 — Anonymous visitors get a small ZeroGPU quota — MEASURED, still live
Documented tiers: unauthenticated ~2 min/day of GPU per IP, free account ~5 min,
PRO ~40 min. Measured on the Space: an unauthenticated Incognito visitor
completed a full LLM check in 4.095 s total, of which ~2.2 s was generation.
So a reviewer who never logs in has room for a useful number of extractions
rather than one or two — the design constraint has been met, not removed.
**Caveat:** ZeroGPU may bill the *allocated* slice rather than the elapsed
generation, so the effective count could be lower than 120 s ÷ 2.2 s suggests.
**Consequence:** keep OCR on CPU, keep `@spaces.GPU` around generation only, and
keep `duration=` tight. Revisit in Phase 7 when real (not synthetic) prompt sizes
are known.

## K-005 — ZeroGPU hosting requires an account in good standing — RESOLVED 2026-08-16
The Space is hosted on ZeroGPU and publicly reachable without authentication.
The eligibility constraint (verified email, account older than 30 days, or PRO)
did not block this project.

## K-006 — OCR cost looks likely to dominate the latency budget — SLOWER REMOTELY
Local (1 vCPU): 7.6 s first page, 4.4 s warm. **On the Space: ~18–20 s first
page, ~12–13 s warm** — roughly 3x the local cost. The cause of that gap is
*not* established: CPU allocation, thread limits, contention and I/O are all
plausible and none was isolated.

Scope of what this shows: in the synthetic smoke test, one warm OCR page
(~12–13 s) costs materially more than one short synthetic LLM generation
(~2.2 s, ~120-token prompt). It does **not** show that OCR dominates the real
system. Real BGS scans, real linearised OCR contexts, and real Naive RAG /
Adaptive RAG / Direct-LLM prompt sizes are unmeasured; a long-context prompt
could shift the balance materially. Treat the following as a working hypothesis
for Phase 3, to be re-tested once real documents exist:
- the page prefilter is likely to be necessary rather than merely nice to have;
- its fallback branch (heuristic finds nothing → broaden to full OCR) is the
  expensive path and must be measured, not assumed;
- raster DPI, image downscaling and per-page parallelism are worth treating as
  real tuning levers;
- a 20-page report at ~12 s/page would be ~4 minutes of OCR, which no live demo
  can absorb — so prefiltering, caching and honest progress reporting are the
  obvious levers to test.
Isolating the local/remote gap is worth a short experiment in Phase 3 rather than
a guess now.

## K-007 — ZeroGPU request-time CUDA placement — RESOLVED 2026-08-16
First deployment failed with `RuntimeError: Low-level CUDA init
(torch._C._cuda_init) reached` at `model.to("cuda")` in `load_llm()`, called from
a Gradio request. Cause: `spaces` being importable was used as the test for "are
we on ZeroGPU", so placement happened outside the startup window where ZeroGPU's
emulation layer intercepts it. Fixed by gating on `SPACES_ZERO_GPU` and loading
at module import. **Verified on the Space:** `llm_ready_from_startup=True`,
`llm_startup_error=None`, model prepared on `cuda:0` in ~7.6–8.0 s, and the
emulated placement survives into the forked `@spaces.GPU` worker — inference runs
on `cuda:0` at ~25–29 tokens/s with ~8.14 GB peak VRAM.

## K-008 — Startup model load competes with the Space startup timeout — LOW RISK
Measured startup load: ~7.6–8.0 s for ~8.04 GB of packed tensors, comfortably
inside the startup budget. The risk is downgraded but not eliminated: a larger
model chosen in Phase 7 would push this back up. Escape hatch retained — set the
Space variable `GDE_DISABLE_STARTUP_LLM=1` (Settings → Variables) to boot without
the LLM; the other four checks keep working and `check_llm()` reports why the
model is unavailable.

## K-009 — Transient ZeroGPU allocation failure — OPEN, root cause unconfirmed
Observations, in the order they occurred:
- several GPU calls succeeded, including one from an unauthenticated visitor;
- one **Run all** invocation then failed inside `spaces/zero/wrappers.py` at
  `worker_init` with `RuntimeError: No CUDA GPUs are available`;
- a subsequent standalone LLM call also failed;
- no application code was changed between the successful and failed calls;
- restarting the Space restored normal standalone inference immediately.

Classification: a **probable transient ZeroGPU infrastructure/runtime issue**.
The failure surfaced in ZeroGPU's own worker initialisation rather than in our
code, and the same code path had already succeeded repeatedly, which is what
makes an infrastructure explanation the leading one. The exact root cause is
**unconfirmed**: an application-side or usage-pattern contribution (for example
how `Run all` issues several GPU calls in quick succession) has not been ruled
out, and one occurrence is not enough to characterise the fault.

Candidate explanations, none confirmed: quota exhaustion presenting as an
allocation error; contention in the shared ZeroGPU pool; a worker whose state did
not survive several allocations in quick succession; an interaction specific to
sequential calls within one invocation.

Consequences:
- **`Run all` is NOT validated end-to-end.** Every individual check passes; the
  combined sequence has one observed failure and no observed success, so it is
  unvalidated rather than known-good or known-broken.
- **Design implication for Phase 5+:** a live demo must not assume GPU allocation
  succeeds. A failed allocation should surface as a clear, honest status
  (`extraction_error`) rather than a stack trace, and the Expert pipeline — which
  needs no GPU at all — is the natural degraded mode.
- **Reviewer-facing implication:** if the hiring manager hits this, the Space
  needs a restart. Worth knowing before the link is sent, not after.
- **To resolve:** re-run `Run all` several times and record outcomes. If failures
  recur only in the multi-call sequence, that points back at our usage pattern
  rather than the platform, and the classification above must be revised.

## K-010 — Extraction quality is NOT validated by Phase 0 — by design
The smoke test proves the runtime *functions*. It says nothing about whether the
system extracts correctly. The LLM check scored 4/4 fields and OCR recovered 4/4
planted values, and neither number is evidence of anything beyond plumbing:
- the page is **synthetic**, clean, high-contrast, digitally rendered — the
  opposite of a scanned BGS borehole log;
- the field values were **planted by the same code that checks them**;
- the prompt contains a short, unambiguous, hand-written OCR snippet, not a real
  linearised multi-page document;
- there is no ground truth, no competing candidates, no neighbouring boreholes,
  no ambiguity, and therefore no possible measurement of grounding or accuracy.

Real extraction quality is measured in Phase 12, against the manually verified
truth set built in Phase 11. Until then, no accuracy claim of any kind should be
made from Phase 0 numbers, in the README, in the app, or in an interview.

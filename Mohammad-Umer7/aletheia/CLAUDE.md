# ALETHEIA — Project State

**What this is:** An AI research assistant that can change its mind. Built on self-hosted
open-source Cognee for the "The Hangover Part AI" hackathon (Best Use of Open Source track).
Full spec: `ALETHEIA_BUILD_SPEC.md` — read it before changing anything.

## Current phase

**Phase 0 — Preflight: COMPLETE** (gate: cognee 1.2.2 imports, Groq provider active)
**Phase 1 — Memory core: COMPLETE** (gate: smoke.py clean end-to-end — remember/recall/
improve-with-session-bridge/forget all verified against live Groq + fastembed)
**Phase 2 — Source engine + seed: COMPLETE** (gate: 4 trusted sources seeded with
ledger-exact node attribution; debug_graph.html rich; ask() cites correctly)
**Phase 3 — Flip test: COMPLETE** (gate: pytest green twice consecutively on
groq/openai/gpt-oss-120b — 2:46 and 3:29 per run)
**Phase 4 — Backend API: COMPLETE** (gate: every endpoint exercised via httpx with real
data — reads, ask, background ingest/seed, retract, 404/409 guards)
**Phase 5 — Frontend: COMPLETE** (gate: full demo click-through verified in ONE browser
session via Playwright — seed -> ask (cites helios+meridian, parrots 40%) -> retraction
arrives -> retract helios (13 real node deaths animated red, ledger types in) -> retract
meridian -> ask again (cites northfield+retraction only). Visual QA pass done: fixed
meta-row wrapping, 4-cards-above-fold, structural node prominence, ledger overlap jank.)
**Phase 6 — Polish + submission pack: COMPLETE** (gate: fresh `git clone` -> venv ->
pip install per README -> cognee 1.2.2 imports -> uvicorn boots at 0 sources -> ingest
13 nodes in 13s -> cited answer -> retraction removes all 13 -> changelog entry. Frontend
`npm ci && npm run build` produces dist/ clean. README has the 60s demo script, mermaid
architecture, Cognee Usage Map, MIT license, fictional-data note, disclosure line.)

**FINAL SPRINT (2026-07-05) — wow-factor upgrades U1–U4: COMPLETE**
- **U1 Conflict detection (THE wow factor):** after every live ingest (NOT during
  seeding — the seed is the baseline worldview), one temperature-0 direct Groq call
  (`backend/llm_direct.py`, model llama-3.3-70b-versatile — separate per-model quota
  from cognee's pipeline) compares the new source's raw_text against every trusted
  source; conflicts stored on the registry entry and surfaced as amber conflict
  cards whose Retract button pre-fills the LLM-detected reason. Registry now stores
  `raw_text` + `conflicts` (raw_text backfilled from seed content at API startup).
  Detection is non-fatal by construction (parse-retry once, then no conflicts).
  Kill switch: `ALETHEIA_CONFLICT_CHECK=0`. NOTE: the detector WOULD flag
  northfield-vs-helios too (the meta-analysis disputes the claim) — another reason
  seeding skips the check.
- **U2 Stateless compare:** `/api/ask` also returns `stateless_answer` (direct Groq,
  no memory), computed concurrently via asyncio.gather; per-answer segmented toggle.
- **U3 Weighty retraction:** all retract paths route through a confirm modal;
  `retract_source` measures `links_removed` from the pre-forget edge snapshot; a
  live ticker counts up beside the ledger during the 1.6s fade and the ledger entry
  types in when it lands.
- **U4 Receipts:** citation chips are clickable -> pulse that source's node_ids in
  the source's hue (`pulseNodes(ids, color)`; green remains the answer-pulse default).
- Demo-flow change: seed = sources 1,2,4 only (`seed_demo` default
  include_retraction=False; scripts/seed.py flag flipped to `--with-retraction`);
  the retraction is ingested LIVE via "A retraction notice arrives…" so the
  conflict card appears on camera.
- Flip test extended: asserts conflicts non-empty, disputed_source_id==helios_study,
  links_removed>0, retraction via the same code path as the UI button. Green 2x
  consecutively post-upgrades (3:10, 2:46). Full Playwright click-through of the
  final demo path passed (conflict card -> modal -> ticker -> corrected answer).

Run the backend: `$env:PYTHONUTF8="1"; .venv\Scripts\python.exe -m uvicorn backend.api:app --port 8000 --timeout-keep-alive 75`
(keep-alive bump matters: cognee's in-process fastembed compute stalls the event loop;
with the default 5s keep-alive, idle sockets close mid-reuse -> WinError 10053 races.
The frontend's poll loop tolerates transient drops either way.)

## Key decisions

1. **One Cognee dataset per source** (`src_<slug>`). Makes `forget(dataset=...)` surgical and
   the retraction demo reliable. Local `data/registry.json` is the source of truth for
   trust state; `ask()` scopes `recall()` to trusted datasets only.
2. **Groq LLM + fastembed local embeddings.** Groq has no embeddings API; leaving embeddings
   unconfigured makes Cognee silently fall back to OpenAI and crash. Both env blocks are mandatory.
3. **Node attribution via snapshot diff** (graph node IDs after − before ingesting a source).
   Entity dedup means shared entities may attach to the earliest source that mentioned them —
   accepted limitation.
4. **Relocate cognee storage into `<repo>/data/`** via `cognee.config.system_root_directory()`
   + `data_root_directory()` at wrapper init — default lands inside site-packages (wiped on
   reinstall, survives nothing). Project-local storage also makes `reset.py` trivial.
5. **Frontend never talks to Cognee** — only to our FastAPI backend.
6. All memory operations are real Cognee calls. Nothing mocked, nothing hardcoded.

## Environment

- Windows 11, Python 3.11.9, venv at `.venv/`
- Run backend python via `.venv\Scripts\python.exe` (no activation needed)
- Storage: embedded (SQLite relational + LanceDB vectors + **ladybug** graph store)
- First run downloads the fastembed model (~100MB) — expected, be patient
- Groq free tier rate-limits hard: retry with exponential backoff on 429s, ingest sources
  strictly one at a time

## Installed-cognee quirks (v1.2.2, verified 2026-07-02)

- **`LLM_PROVIDER="groq"` is REJECTED** (`ValueError: 'groq' is not a valid LLMProvider`).
  The enum only has openai/ollama/anthropic/custom/gemini/mistral/azure/bedrock/llama_cpp.
  Groq runs via `LLM_PROVIDER="custom"` (GenericAPIAdapter -> LiteLLM) with the `groq/`
  model prefix + explicit `LLM_ENDPOINT="https://api.groq.com/openai/v1"`. Adapter's
  instructor mode defaults to `json_mode`; cognee also runs a connection test
  (`test_llm_connection`) before the first pipeline of a process.
- **Graph DB provider is `ladybug`** (cognee's embedded engine), not Kuzu as older docs say.
  Embedded, file-based, no Docker. `graph_database_subprocess_enabled=True` by default.
- **`recall()` returns a list of typed entry objects**, NOT plain strings. Verified shape
  (smoke run): `ResponseGraphEntry(kind='graph_completion', text='...', dataset_id=UUID,
  dataset_name='smoke_patient_zero', raw={'value': ...}, source='graph')`. `.text` holds the
  answer; **`.dataset_name` is real per-entry provenance** — with one-dataset-per-source this
  identifies the contributing source exactly. Use it for citations (better than text heuristic).
- **`recall()` on a deleted/nonexistent dataset raises `DatasetNotFoundError` (404)** instead
  of returning an empty list — `ask()` must catch it (e.g. when all sources are retracted).
- **Session bridging verified:** `improve(ds, session_ids=["s1"])` consolidates session
  memories into the permanent graph — facts become recallable without the session_id.
- **`ENABLE_BACKEND_ACCESS_CONTROL=false` is REQUIRED for our architecture** (set in `.env`).
  With it on (default), datasets get isolated per-dataset DB contexts and
  `visualize_graph(dataset=None)` errors. Off = one global graph; bare `get_graph_data()`
  sees everything; auth posture logs "authentication=disabled".
- **cognee keeps a relational graph ledger** (`nodes`/`edges` tables,
  `cognee.modules.graph.models.Node`) mapping every graph node to its `dataset_id` — EXACT
  per-source attribution, including shared entities attributed to ALL datasets that mention
  them (snapshot diff undercounts those; e.g. meridian: ledger=10 vs diff=4). Query it with
  `NodeRow.dataset_id == uuid.UUID(dataset_id_str)` — passing a str breaks sqlite UUID binding.
- **Multi-dataset `recall()` returns ONE `graph_completion` entry with `dataset_name=None`**
  — per-entry provenance only exists for single-dataset recalls. Citations therefore come
  from the label-match heuristic (source's ledger labels appearing in the answer text).
- **`visualize_graph()` returns the HTML string** (it also writes the file). Don't print it.
- **Windows: ALWAYS run python with `PYTHONUTF8=1`** — cognee's HTML writer and any print
  of non-cp1252 chars (data contains em dashes etc.) crash otherwise. Keep our own script
  output ASCII-safe regardless.
- Retraction counts: `nodes_removed` = real graph diff (what actually died); shared entities
  survive if another trusted source still references them — honest and demo-friendly.
- **LLM model is `groq/openai/gpt-oss-120b`** (switched 2026-07-02): we exhausted
  llama-3.3-70b's 100k tokens/DAY free budget during Phase 3. gpt-oss-120b has its own
  separate 200k TPD bucket but only 8k tokens/MINUTE — cognee's tenacity retries ride the
  TPM waves fine (a full flip run still completes in ~3 min). Groq quotas are PER MODEL;
  if a bucket drains, switching models in .env is the unblock. One quirk: gpt-oss writes
  "40 %" (with a space), so test_flip's verbatim '"40%" not in answer2' assertion holds
  even when answer2 mentions the figure in retracted/unsupported framing.
- **`remember()` defaults `self_improvement=True`** — spec wants it passed as `False` explicitly.
  Signature: `remember(data, dataset_name="main_dataset", *, session_id=None, ...,
  self_improvement=True, run_in_background=False)`.
- **`forget()` signature confirmed:** keyword-only `forget(dataset="...")`,
  `forget(everything=True)`, also `data_id`/`dataset_id`/`memory_only`. Returns a dict
  (inspect for deletion stats — may give us removed counts for free).
- **`improve()` signature confirmed:** `improve(dataset="...", session_ids=[...])` as spec'd.
  Bonus flags exist: `build_global_context_index`, `build_truth_subspace`.
- **`visualize_graph(path, dataset='main_dataset')` is per-dataset by default** — pass
  `dataset=None` (or call per dataset) to try to get the whole graph; verify at Phase 2.
- **`recall(include_references=True)` exists** — may provide real citation provenance,
  better than the spec's text-match heuristic. Evaluate in Phase 2; keep heuristic as fallback.
- **Multi-user access control + auth ON by default** ("auth posture: authentication=required,
  multi_tenant=enabled"). Python API auto-authenticates a default local user. If we hit
  user/permission errors, set `ENABLE_BACKEND_ACCESS_CONTROL=false` in `.env`.
- **Session memory on by default** (`CACHING=false` disables) — relevant to stretch goal.
- `EMBEDDING_MAX_TOKENS=256` from `.env` didn't surface in the embedding config
  (`embedding_max_completion_tokens` stayed 8191) — env var name may differ; harmless for
  MiniLM (model truncates internally). Revisit only if embedding errors appear.
- Legacy v1 API (`add`/`cognify`/`search`/`prune`) still present — do NOT use; spec is v2-only.

## Phase log

- Phase 0: done 2026-07-02 — venv, pinned deps, cognee 1.2.2, Groq provider + fastembed
  confirmed via `get_llm_config()`; API surface verified against spec §3.

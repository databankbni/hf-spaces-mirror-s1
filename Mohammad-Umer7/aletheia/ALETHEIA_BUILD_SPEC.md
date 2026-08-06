# ALETHEIA — End-to-End Build Spec for Claude Code

You are the lead engineer building **Aletheia** ("the un-forgetting"), a hackathon project that must win the **Best Use of Open Source** track of the Cognee "The Hangover Part AI" hackathon (WeMakeDevs, deadline July 5, 2026). Judging criteria: Potential Impact, Creativity & Innovation, Technical Excellence, **Best Use of Cognee**, User Experience, Presentation Quality. The winning edge: this app makes Cognee's `forget()` and `improve()` the *product itself*, not afterthoughts, and shows the AI's brain changing **live on screen** as an animated knowledge-graph constellation.

**One-line pitch:** An AI research assistant that can change its mind — feed it sources, ask questions, then feed it a retraction and *watch* the discredited knowledge fade out of its brain while its answers correct themselves.

---

## 1. Hard rules (never violate)

1. **Open-source, self-hosted Cognee only.** `pip install cognee`, running locally. NEVER use Cognee Cloud, `cognee.serve()`, or any hosted endpoint. Self-hosting is our prize-track requirement and our privacy story.
2. **All memory is real.** Every answer must come from `cognee.recall()`. Never mock, hardcode, or fake memory operations, answers, or graph data — judges will read the code.
3. **Work phase by phase.** After each phase, run its acceptance gate, show me the output, `git commit -m "phase-N: <summary>"`, and only then continue. If a gate fails, fix it before moving on.
4. **Never invent Cognee APIs.** If a signature is unclear or errors, inspect the installed package (`help(cognee.remember)`, read the source in site-packages) and adapt. Do not guess parameter names.
5. Keep dependencies minimal and pinned. Backend: `pip install "cognee[groq,fastembed]" fastapi uvicorn python-dotenv pytest httpx`. Frontend: Vite + React + `react-force-graph-2d` + `framer-motion` + `lucide-react`, styled with hand-written CSS design tokens — **no Bootstrap, MUI, AntD, shadcn, Tailwind templates, or any pre-built component kit.**
6. Maintain `CLAUDE.md` at repo root: current phase, key decisions, known quirks of the installed cognee version. Update it every phase.
7. Long operations (ingestion takes 20–90s per source because Cognee calls an LLM) must never freeze the UI — run them as background tasks with status polling.
8. All seed data is **fictional** (no real brands, companies, journals, or people). Note this in the README.
9. The frontend never talks to Cognee directly — only to our FastAPI backend.
10. Do not add unrequested features until Phase 6 is complete and polished.

---

## 2. What we are building

A single-page web app with three panels around a living knowledge-graph:

- **Center — The Constellation.** A force-directed graph (canvas) of Aletheia's entire memory. Every node is a piece of knowledge; nodes are hue-coded by which *source* they came from. Hovering a node shows a tooltip (Name / Type / Description) like Cognee's own visualizer.
- **Left — Sources & the Mind-Change Log.** A list of ingested sources, each with a trust badge (`trusted` / `retracted`) and a **Retract source** button. Below it, an append-only ledger of every belief change ("Jul 3 21:04 — Retracted *Helios study* — 41 memories removed — answers re-derived").
- **Right — Ask Aletheia.** A chat thread. Answers cite which sources contributed. When an answer arrives, the contributing nodes **pulse green** in the constellation.

**The money shot (build everything in service of this):** user asks a question → answer cites Source A → user ingests a retraction and clicks **Retract** on Source A → Source A's nodes glow red, shrink, and fade out over ~1.6s → the constellation physically rearranges as the force simulation re-heats → the Mind-Change Log gains an entry → user asks the same question → the corrected answer cites different sources. The AI visibly changed its mind.

---

## 3. Cognee crash course (v1.x, verify against installed version)

```python
import cognee

# Ingest → builds graph + vectors (LLM-heavy, slow). Text, file paths, and URLs all work.
await cognee.remember(text_or_path, dataset_name="...", self_improvement=False)
# Session (short-term) memory variant:
await cognee.remember(text, dataset_name="...", session_id="...", self_improvement=False)

# Query. Scope to specific datasets. Returns a list of result strings.
results = await cognee.recall("question?", datasets=["ds1", "ds2"])

# Enrich existing memory; optionally bridge session memory into the permanent graph.
await cognee.improve(dataset="...", session_ids=["..."])   # session_ids optional

# Surgical deletion. Verify exact kwarg (dataset vs dataset_name) via help(cognee.forget).
await cognee.forget(dataset="...")
await cognee.forget(everything=True)   # test-only full reset

# Built-in debug visualization → interactive HTML file:
from cognee import visualize_graph
await visualize_graph("debug_graph.html")

# Raw graph data for our own frontend:
from cognee.infrastructure.databases.graph import get_graph_engine
engine = await get_graph_engine()
nodes, edges = await engine.get_graph_data()
# NOTE: inspect the actual shape at runtime (nodes may be (id, props) tuples;
# edges may be (source, target, label, props)). Write one normalizer and reuse it.
```

**Environment — we use GROQ for the LLM (fast + free tier) and fastembed for local, free embeddings.** Critical: Cognee always needs TWO models — an LLM for extraction and a *mandatory* embedding model for vectors. Groq provides no embeddings API, and if embeddings are left unconfigured Cognee silently falls back to OpenAI and crashes without an OpenAI key. So `.env` at repo root must contain exactly:

```env
LLM_PROVIDER="groq"
LLM_MODEL="groq/llama-3.3-70b-versatile"
LLM_API_KEY="gsk_your_groq_key_here"

EMBEDDING_PROVIDER="fastembed"
EMBEDDING_MODEL="sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS="384"
EMBEDDING_MAX_TOKENS="256"
```

Groq notes: no `LLM_ENDPOINT` needed — LiteLLM resolves it from the `groq/` model prefix. If the installed version rejects `LLM_PROVIDER="groq"`, read the package's `.env.template` and `cognee/infrastructure/llm/config.py` for the accepted value and adapt (rule 4). Groq's free tier rate-limits aggressively and Cognee makes many sequential LLM calls during ingestion — wrap our cognee calls with retry + exponential backoff on 429s, ingest sources strictly one at a time, and if extraction returns malformed structured output, consult `LLM_INSTRUCTOR_MODE` in Cognee's LLM Providers docs. First run downloads the fastembed model (~100MB) — expected, be patient. Storage defaults (SQLite + LanceDB + Kuzu) run embedded — no Docker, no external DBs.

---

## 4. Core architecture decision: one dataset per source

This is the trick that makes forgetting surgical and the demo reliable:

- Every source gets its **own Cognee dataset**: `src_<slug>` (e.g. `src_helios_study`).
- A local **registry** (`data/registry.json`) tracks: `{id, title, kind (study|news|retraction|meta-analysis), dataset, trust: "trusted"|"retracted", node_ids: [], color_index, added_at, retracted_at, reason}`.
- **Node attribution via snapshot diff:** before ingesting source S, capture the set of node IDs from `get_graph_data()`; after ingesting, capture again; `S.node_ids = after − before`. (Entity dedup means shared entities may attach to earlier sources — acceptable; note it in CLAUDE.md.)
- **Ask** = `recall(question, datasets=[every dataset whose trust == "trusted"])`. Retracted knowledge is structurally unreachable, not just deleted — mention this in the README, judges will like it.
- **Retract(S)** = `forget(dataset=S.dataset)` → `improve()` over each remaining trusted dataset (re-enrichment pass) → re-fetch graph, compute which node IDs actually disappeared → append a Mind-Change Log entry (`data/changelog.jsonl`) with counts → return `removed_node_ids` so the frontend can animate their death.
- **Answer attribution (honest heuristic):** after recall, for each trusted source, check whether any of its node labels/entity names appear in the answer text (case-insensitive). Matching sources = "cited"; return their `node_ids` as `highlight_node_ids` for the green pulse.

---

## 5. Repo layout

```
aletheia/
  .env                      # LLM_API_KEY (never commit)
  .gitignore                # venv, .env, data/, __pycache__, node_modules, .artifacts
  CLAUDE.md
  README.md
  backend/
    memory.py               # thin async wrapper around cognee (§3 calls only)
    sources.py              # registry, ingest_source, retract_source, ask, graph_snapshot
    changelog.py            # append/read data/changelog.jsonl
    api.py                  # FastAPI app
  scripts/
    smoke.py                # Phase 1 gate
    seed.py                 # loads the 4 fictional sources (§9)
    reset.py                # forget(everything=True) + clear data/
  tests/
    test_flip.py            # Phase 3 gate — THE most important file in the repo
  frontend/                 # Vite + React app
  data/                     # registry.json, changelog.jsonl (gitignored, created at runtime)
```

---

## 6. Phases and acceptance gates

**Phase 0 — Preflight.** Create venv if missing, install pinned deps (`pip install "cognee[groq,fastembed]" ...`), verify `.env` contains the full §3 block (Groq LLM vars **and** fastembed embedding vars — if the Groq key is missing, STOP and ask me for it; never fabricate). Print `get_llm_config().to_dict()` to confirm Groq is active. `git init`, first commit, write initial `CLAUDE.md`.
*Gate:* `python -c "import cognee; print(cognee.__version__)"` succeeds.

**Phase 1 — Memory core.** Implement `backend/memory.py` and `scripts/smoke.py`: reset → remember one permanent fact + one session fact (`session_id="s1"`) about a patient-zero topic → recall both → `improve(dataset, session_ids=["s1"])` → recall again → forget the dataset → recall returns nothing relevant. Print every result.
*Gate:* smoke script runs clean end-to-end; paste its output to me.

**Phase 2 — Source engine + seed.** Implement `sources.py` (registry, snapshot-diff ingestion, retract, ask with trust scoping, attribution heuristic) and `scripts/seed.py` loading the four sources from §9 sequentially with progress prints. Also write the built-in `visualize_graph("debug_graph.html")` at the end of seeding.
*Gate:* seed completes; registry.json shows 4 trusted sources each with non-empty `node_ids`; debug_graph.html opens and shows a rich graph.

**Phase 3 — The flip test (do not proceed until this is green twice in a row).** `tests/test_flip.py`, using pytest + asyncio, full programmatic run: reset → seed → `ask(DEMO_QUESTION)` and record answer₁ + cited sources → assert the Helios study is among the cited/scoped sources → `retract("helios_study", reason="Journal retraction: fabricated data")` → assert changelog has 1 entry with `nodes_removed > 0` → `ask(DEMO_QUESTION)` again → assert (a) `src_helios_study` is no longer in the scoped datasets, (b) answer₂ differs from answer₁, (c) "40%" no longer appears in answer₂. LLM output varies — assert on structure (scoping, citations, changelog) more than exact wording.
*Gate:* `pytest tests/test_flip.py` passes twice consecutively.

**Phase 4 — Backend API.** FastAPI in `api.py` with CORS for the Vite dev origin:
- `POST /api/sources` `{title, kind, text?, url?}` → starts background ingestion → `{source_id, status:"ingesting"}`
- `GET /api/sources` → registry with trust states + ingestion status
- `POST /api/ask` `{question}` → `{answer, cited_sources:[...], highlight_node_ids:[...]}`
- `POST /api/sources/{id}/retract` `{reason}` → `{removed_node_ids:[...], nodes_removed, changelog_entry}`
- `GET /api/graph` → `{nodes:[{id, label, type, source_id|null, trust}], links:[{source, target, label}]}` (normalized shapes, structural nodes get `source_id: null`)
- `GET /api/changelog` → entries, newest first
- `POST /api/demo/seed` → runs the seed in the background (for the "Load demo scenario" button)
*Gate:* every endpoint exercised via curl/httpx with real data; paste responses.

**Phase 5 — Frontend.** Build per §7–§8.
*Gate:* full click-through works in the browser: Load demo → constellation appears → Ask → green pulse + cited answer → Retract Helios → red fade-out + layout rearrange + ledger entry → Ask again → corrected answer. Then run a visual QA pass: screenshot the app, critique it against §7 ("would a design-savvy judge believe a funded startup shipped this?"), fix the three weakest details, and screenshot again. Fix any jank before proceeding.

**Phase 6 — Polish + submission pack.** Loading/empty/error states with directive copy ("Ingesting — Aletheia is reading this source, ~60s"), a 60-second demo script in `README.md`, architecture diagram (mermaid), the **Cognee Usage Map** table (operation → file/function → why it matters), setup instructions verified from a fresh clone, MIT license, fictional-data note, and this exact disclosure line: *"Built with AI assistance (Claude Code); all architecture and code reviewed by the team."*
*Gate:* I can follow README from scratch and reach the money shot.

**Stretch (only after Phase 6 is flawless) — Session consolidation.** Log each Q&A into session memory (`remember(..., dataset_name="aletheia_notebook", session_id=<research session>)`); add an "End session & consolidate" button calling `improve(dataset="aletheia_notebook", session_ids=[sid])` so the session's findings visibly join the permanent constellation (new nodes fade in). This demonstrates Cognee's session-bridging — a big Best-Use-of-Cognee bonus — but the core demo must never depend on it.

---

## 7. Frontend design directives

**Non-negotiable: this must look like a 2026 flagship product from a well-funded startup — never like a hackathon dashboard or a template.** Act as the design lead of a studio known for interfaces that couldn't be mistaken for anyone else's. Before writing any frontend code, produce a 10-line design plan (palette tokens, type roles, layout, and the single signature element — which is the retraction moment). Self-critique it: if any part reads like the generic output you'd produce for any app, revise that part and say why. Only then build, exactly to the plan.

**Identity.** Wordmark: `ALETHEIA` with tagline *the un-forgetting* (Greek: a- "not" + lethe "forgetting"). Display face: **Instrument Serif** (italic for the tagline); UI/body: **Inter**; data/log: **IBM Plex Mono**. Load via Google Fonts.

**Palette (CSS variables, exact values):** background `#0E0A1F` with a soft radial vignette to `#1B1140` behind the graph; text `#EDEAF7`; muted `#8B84A8`; panel surface `rgba(20,14,46,0.72)` with 1px `#2A2150` borders. Source hues (assigned by `color_index`, cycling): `#7C6CFF`, `#C86CFF`, `#5FD4E8`, `#FFB454`. Structural nodes (chunks/summaries): dim `#4A4468`. Retraction red: `#FF4D5E`. Answer pulse green: `#6CFFA8`. Spend all boldness on the constellation and the retraction moment; keep panels quiet and disciplined.

**Layout:**

```
┌──────────────────────────────────────────────────────────────────┐
│ ✦ ALETHEIA · the un-forgetting          412 memories · 977 links │
├──────────────┬────────────────────────────────┬──────────────────┤
│ SOURCES      │                                │ ASK ALETHEIA     │
│ ● Helios st… │        THE CONSTELLATION       │ chat thread;     │
│   [Retract]  │   react-force-graph-2d canvas  │ each answer      │
│ ● Meridian…  │   hover → tooltip (name/type/  │ lists “Based on: │
│ ● Retraction │            description)        │ <source chips>”  │
│ ● Northfield │                                │                  │
│──────────────│                                │──────────────────│
│ MIND-CHANGE  │                                │ [input…]  [Ask]  │
│ LOG (ledger, │                                │                  │
│ mono, newest │                                │                  │
│ first)       │                                │                  │
└──────────────┴────────────────────────────────┴──────────────────┘
```

Buttons say exactly what they do: **Load demo scenario**, **Add source**, **Retract source**, **Ask**. Toasts mirror the verb: "Source retracted — 41 memories removed."

**Empty state (center, before any data):** a faint constellation outline + "Aletheia hasn't read anything yet. Load the demo scenario or add a source." — an invitation to act, not a shrug.

**Modern polish checklist (all required):**
- Panels are glass: `backdrop-filter: blur(14px)`, translucent surfaces over the constellation, 1px `#2A2150` borders, soft layered shadows for depth; subtle film-grain/noise overlay on the background and a radial glow behind the graph.
- Micro-interactions everywhere via `framer-motion`: buttons compress to 0.98 on press; source cards and chips glow on hover; panel content staggers in (150–250ms, ease-out); the ledger entry types in.
- Loading is designed, not default: shimmer skeletons for sources/graph, an animated three-dot "Aletheia is thinking…" indicator in chat, and an ingestion progress card ("Reading this source, ~60s").
- Icons from `lucide-react` only — never emojis in UI chrome.
- Custom thin rounded scrollbars, a 2px violet focus ring on every focusable element, custom text-selection color, `tabular-nums` on all counters.
- Typography with intent: large Instrument Serif wordmark; 11px uppercase letter-spaced muted labels; IBM Plex Mono for IDs, counts, and the ledger.
- Toasts: glass cards bottom-right, icon + verb-first copy ("Source retracted — 41 memories removed").
- The canvas stays at 60fps; the graph is always the dominant element at every window size (responsive down to 1280px).

**Banned outdated looks (instant fail):** default browser buttons/inputs; Bootstrap/MUI/AntD or any component-kit aesthetic; white or flat gray backgrounds; harsh 1px black borders; default blue hyperlinks; Arial/Times/system-default fonts; emoji icons; cramped spacing; the generic purple-gradient-on-white "AI SaaS" template look.

---

## 8. Animation spec (this is the demo — get it right)

Use `react-force-graph-2d` with a custom `nodeCanvasObject` (circle + soft glow; radius by degree, clamp 3–9px). Keep client-side node state keyed by id: `{status: "alive"|"entering"|"dying", pulseUntil}`.

1. **Entering** (after ingest/seed): new nodes start at radius 0 / opacity 0, ease to full over 600ms, staggered ~8ms apart.
2. **Answer pulse:** on `/ask` response, nodes in `highlight_node_ids` get a green outer-glow pulse (sine opacity) for 3s.
3. **Retraction (the money shot):** on retract response, do NOT refetch immediately. Mark `removed_node_ids` as `dying`: red glow, radius and opacity ease to 0 over 1.6s; then remove them from the data array and call the force engine's reheat (`d3ReheatSimulation()`) so the constellation visibly re-settles. Then refetch `/api/graph` to reconcile.
4. **Ledger entry** types in with a brief highlight at the same moment the nodes finish dying.
5. Respect `prefers-reduced-motion`: swap animations for instant transitions.

Tooltips on hover: dark card with `Name`, `Type`, `ID`, `Description` in mono — deliberately echoing Cognee's own visualizer aesthetic.

---

## 9. Seed scenario (exact fictional content — use verbatim)

`DEMO_QUESTION = "Does Mnemosyne-7 improve memory? What actually works?"`

1. **id `helios_study`, kind `study`, title "Helios Longevity Institute trial (2025)":**
   "Helios Longevity Institute, 2025 — In a 12-week internal trial of 240 adults, daily Mnemosyne-7 supplementation improved verbal recall scores by 40% versus placebo. Lead researcher Dr. R. Calder called it 'the largest effect ever recorded for an over-the-counter memory supplement.' The Institute notes that Mnemosyne-7 is available for purchase directly from its online store."
2. **id `meridian_post`, kind `news`, title "Meridian Post: 'The end of forgetting?' (2025)":**
   "Meridian Post, 2025 — A new study from the Helios Longevity Institute claims the supplement Mnemosyne-7 boosts memory by 40%. 'This could change aging itself,' said lead researcher Dr. R. Calder. Sales of Mnemosyne-7 have surged since the announcement, and retailers report waiting lists."
3. **id `jch_retraction`, kind `retraction`, title "Journal of Cognitive Health — Retraction notice (2026)":**
   "Journal of Cognitive Health, 2026 — RETRACTION: The Helios Longevity Institute trial of Mnemosyne-7 has been retracted after independent auditors found fabricated placebo-group data and an undisclosed financial conflict of interest: the Institute manufactures and sells Mnemosyne-7. The reported 40% memory-improvement claim should be considered unsupported by evidence."
4. **id `northfield_meta`, kind `meta-analysis`, title "Northfield University meta-analysis (2024)":**
   "Northfield University, 2024 — A meta-analysis of 61 randomized controlled trials finds that consistent aerobic exercise (three or more sessions per week) and regular 7–9 hour sleep show the strongest and most replicated effects on memory consolidation in healthy adults. Evidence for over-the-counter memory supplements remains weak and inconsistent."

Demo flow: seed 1, 2, 4 → ask (answer parrots the 40% claim, cites Helios/Meridian) → ingest 3 → retract `helios_study` (reason: the retraction) → optionally also retract `meridian_post` (it only repeats the claim) → ask again (answer now: claim retracted/unsupported; exercise and sleep are what actually work, citing Northfield).

---

## 10. Do NOT

- Do not use Cognee Cloud, `serve()`, or hosted keys.
- Do not mock/hardcode any answer, node, or changelog entry.
- Do not skip or weaken `test_flip.py` to make it pass.
- Do not put personal data or real brand/journal/person names in seed content.
- Do not build extra features (auth, multi-user, uploads UI) before Phase 6 is done.
- Do not change the cognee version mid-build; if an API mismatch appears, adapt our wrapper.

## 11. Working agreement

Start now with Phase 0. At each gate: show me the command output, commit, then continue automatically to the next phase. Only stop and ask me when (a) `.env`/API key is missing, (b) a gate fails twice after your best fixes, or (c) an installed-cognee API differs materially from §3 — in that case show me what `help()` says and your proposed adaptation.

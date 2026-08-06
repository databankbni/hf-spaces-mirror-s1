# BhagwadGitaReadingAgent — Plan

> **Status:** Draft for review. No application code written yet — this document only.
> **Author / owner:** kanika23oct
> **Repo:** local `D:\Huggingface_ai_learning\BhagwadGitaReadingAgent\` → HF Space `kanika23oct/BhagwadGitaReadingAgent`
> **Date:** 2026-05-13

---

## 1. Goal

A standalone agent that **reads the Bhagavad Gita to a user** — Sanskrit shloka
followed by English translation — for a configurable wall-clock window
(min 10 minutes, default 10, max set per user). The agent:

1. Plays text + audio for each verse.
2. Saves the user's position when the window ends or the user stops.
3. On the user's next visit, **resumes from the exact next verse**.
4. Optionally sends **email reminders** to subscribed users.

Runs locally first; deploys to **Hugging Face Spaces** as the hosted target.
This repo is a **separate top-level project** — independent of
`kanikatestmodel/`.

---

## 2. Decisions captured

| Concern | Choice | Why |
|---|---|---|
| Reading modality | **Text + synced audio** (verse-level sync) | User selection. Word-level sync explicitly out of scope for v1. |
| Languages displayed/spoken | **Sanskrit verse + English translation**, both rendered and both spoken | User selection. |
| Source dataset | **`OEvortex/Bhagavad_Gita`** on Hugging Face | 700 rows, MIT license, schema has all needed columns (see §3). |
| User identity | **Email address** (no password / no OAuth) | User selection. Soft identifier — keys bookmarks + reminders. |
| Reminder transport | **SMTP email** (stdlib `smtplib`, Gmail App Password locally; SMTP secrets on the Space) | User selection. No third-party API key needed for v1. |
| Reminder scheduler | **In-process APScheduler** (v1, local-only) | User chose "defer to v1 = local only". On free HF Space tier, scheduler stops when Space sleeps — documented as v2 limitation. |
| Session length unit | **Wall-clock minutes of audio playback** | User selection. Loop checks audio duration before queueing the next verse. |
| Agent framework | **`smolagents` for the chat layer + plain Python for the reading loop** | smolagents matches existing `kanikatestmodel/phase-5-agents/` patterns and the `kanikatestmodel/spaces/smoltestagent/` deploy template. The reading loop stays deterministic — LLMs are unreliable for wall-clock timing. AutoGen / LangGraph evaluated and rejected (multi-agent overkill for a single-user reader). |
| LLM (chat layer) | **`meta-llama/Llama-3.1-8B-Instruct`** via HF Inference Providers, `temperature=0.0` | The chat panel is the *only* place an LLM is used (grounded Q&A after listening). 8B is ~10x cheaper than 70B and plenty for explaining the English translation of retrieved verses. Same code pattern as `smoltestagent` — only the `model_id` string differs. **Indic-tuned models (e.g. `sarvamai/sarvam-1`, `ai4bharat/Airavata`) are a v2 option** if word-by-word *Sanskrit* explanation is added. |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` | Already used in `kanikatestmodel/phase-3-rag/ingestion/embedder.py`. 384-dim, CPU-friendly. |
| Vector store | Chroma persistent client | Already used in the project. |
| Verse store | **SQLite** (`data/gita.sqlite`) | Verses are atomic — no chunking needed. SQLite gives indexed `(chapter, verse)` lookup + cheap migrations. |
| TTS engine (v1) | `gTTS` — `lang='hi'` for Sanskrit, `lang='en'` for English | Free, no API key. Hindi voice approximates Sanskrit pronunciation acceptably. v2 upgrade path = AI4Bharat IndicTTS. |
| HF Space layout | Flat (no package prefixes) — same as `kanikatestmodel/spaces/smoltestagent/` | Matches existing project convention. |
| Pre-baked artifacts | **Bake SQLite + audio cache into the Space upload** | Opposite of `smoltestagent` (which builds Chroma at cold-start). Audio synthesis takes minutes; baking eliminates cold-start cost. |

---

## 3. Source dataset — `OEvortex/Bhagavad_Gita`

Verified via `https://datasets-server.huggingface.co/rows?dataset=OEvortex%2FBhagavad_Gita&...`:

- **Rows:** 700 (one per verse, full Gita)
- **License:** MIT
- **Columns** (note one typo in the source schema):

| Column | Type | Use |
|---|---|---|
| `S.No.` | int64 | ignore |
| `Title` | string | optional chapter title display |
| `Chapter` | string (e.g. `"Chapter 1"`) | parse → int |
| `Verse` | string (e.g. `"Verse 1.1"`) | parse → int |
| `Sanskrit Anuvad` | string | **shloka source** |
| `Hindi Anuvad` | string | optional, store but don't display in v1 |
| `Enlgish Translation` | string *(sic — typo)* | **English translation source** |

**Datasets evaluated and rejected:**
- `AmanKumar007/bhagavad-gita-shloka-dataset` — instruction-tuning format (`input_text` / `output_text`), would need parsing.
- `SatyaSanatan/shrimad-bhagavad-gita-dataset-alpaca` — Alpaca QA format, no clean per-verse rows.
- `knowrohit07/gita_dataset` — 27.4k commentary-heavy QA pairs, wrong granularity.

**Normalized internal schema** (after ingestion):
```
verse_id     TEXT PRIMARY KEY  -- e.g. "BG2.47"
chapter      INTEGER
verse        INTEGER
title        TEXT              -- chapter title
sanskrit     TEXT
english      TEXT
hindi        TEXT              -- stored, unused in v1 UI
sa_seconds   REAL              -- audio duration (filled by build_audio.py)
en_seconds   REAL
```

---

## 4. Folder layout

```
BhagwadGitaReadingAgent/
├── PLAN.md                        # this document
├── README.md                      # HF Space frontmatter + short description
├── app.py                         # Gradio entrypoint (placeholder until §5 lands)
├── requirements.txt
├── _deploy.py                     # huggingface_hub upload helper (mirrors smoltestagent/_deploy.py)
├── data/
│   ├── gita.sqlite                # built artifact, gitignored locally, baked into Space
│   ├── .chroma/                   # Chroma persistent dir, baked into Space
│   └── audio_cache/
│       ├── sanskrit/{verse_id}.mp3
│       └── english/{verse_id}.mp3
├── ingestion/
│   ├── fetch_dataset.py           # OEvortex/Bhagavad_Gita → normalized rows
│   ├── build_corpus.py            # rows → SQLite + Chroma index
│   └── build_audio.py             # rows → per-verse mp3 (gTTS) + duration probe (mutagen)
├── reader/
│   ├── verse_store.py             # SQLite read API: get_verse, next_verse_after, first_verse
│   ├── session.py                 # ReadingSession: wall-clock budget + verse iterator
│   └── audio.py                   # audio path resolution + duration helpers
├── users/
│   ├── profile_store.py           # SQLite users table (email, max_minutes, reminder_opt_in, reminder_time)
│   └── bookmarks.py               # save_position / load_position keyed by email
├── reminders/
│   ├── mailer.py                  # smtplib-based send_reminder()
│   └── scheduler.py               # APScheduler BackgroundScheduler wrapper
├── agent/
│   ├── build_agent.py             # InferenceClientModel + ToolCallingAgent factory
│   └── tools/
│       ├── verse_lookup.py        # smolagents Tool: get_verse(chapter, verse)
│       ├── verse_search.py        # smolagents Tool: semantic search over Chroma
│       └── jump_to.py             # smolagents Tool: set reader position
└── tests/
    ├── test_session_budget.py     # asserts wall-clock budget logic
    ├── test_verse_store.py
    ├── test_bookmark_round_trip.py
    └── test_mailer_dry_run.py     # message format check, no actual send
```

---

## 5. Phases (each independently verifiable)

### Phase A — Data ingestion (no UI, no LLM)
1. **A1** `ingestion/fetch_dataset.py` — `datasets.load_dataset("OEvortex/Bhagavad_Gita", split="train")`. Parse `Chapter` / `Verse` strings into ints, build `verse_id = f"BG{chapter}.{verse}"`, normalize column names (handle the `Enlgish Translation` typo).
2. **A2** `ingestion/build_corpus.py` — write rows to `data/gita.sqlite`. Embed `english` text with the existing MiniLM Embedder pattern (clone from `kanikatestmodel/phase-3-rag/ingestion/embedder.py`) → Chroma collection `gita_verses` at `data/.chroma/`.
3. **A3** `ingestion/build_audio.py` — for each row, generate `audio_cache/sanskrit/{verse_id}.mp3` (gTTS `lang='hi'`) and `audio_cache/english/{verse_id}.mp3` (gTTS `lang='en'`). Probe duration with `mutagen.mp3.MP3(path).info.length`, write back to SQLite. **Idempotent** — skip files already on disk (mirror the `ensure_index()` pattern from `kanikatestmodel/spaces/smoltestagent/build_index.py`).

*Order: A1 → A2 → A3 strictly sequential.*

**Verification:**
- `sqlite3 data/gita.sqlite "SELECT COUNT(*) FROM verses"` → 700.
- `ls data/audio_cache/sanskrit | wc -l` → 700.
- Random sample: `mutagen` reports nonzero duration.

---

### Phase B — Reading engine (deterministic, no LLM)
4. **B1** `reader/verse_store.py` — `get_verse(verse_id)`, `next_verse_after(verse_id) → verse_id|None`, `first_verse() → "BG1.1"`. Pure read API over SQLite.
5. **B2** `reader/session.py` — `ReadingSession(start_verse_id, budget_seconds)` with `iter_verses() -> Iterator[VersePlayback]`. Each yielded `VersePlayback` has `verse_id`, `sanskrit_text`, `english_text`, `sanskrit_audio_path`, `english_audio_path`, `total_seconds`. The loop checks `remaining_budget >= total_seconds` **before** yielding; otherwise stops and exposes the next-unread verse as the new bookmark.

*This is the timing guarantee — no LLM in the loop.*

**Verification:** `tests/test_session_budget.py` — synthetic durations, assert session stops at the correct verse for a known budget.

---

### Phase C — User store + reminders (local v1)
6. **C1** `users/profile_store.py` — SQLite table `users(email PK, max_minutes int default 10, reminder_opt_in bool, reminder_time_local TEXT, created_at, updated_at)`.
7. **C2** `users/bookmarks.py` — table `bookmarks(email FK, last_verse_id, updated_at)`. `save_position(email, verse_id)` / `load_position(email) -> verse_id` (returns `"BG1.1"` for new users).
8. **C3** `reminders/mailer.py` — stdlib `smtplib` + `email.message.EmailMessage`. SMTP config from env: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`. Same env-first / file-fallback pattern as `_read_token()` in `kanikatestmodel/spaces/smoltestagent/app.py`.
9. **C4** `reminders/scheduler.py` — `APScheduler.BackgroundScheduler` wrapper. On startup, scan `users` for `reminder_opt_in=True`, schedule one daily job per user at `reminder_time_local`. Public API: `subscribe(email, time)`, `unsubscribe(email)`, `reschedule(email)`.

**Documented limitation:** on free HF Space tier, the scheduler stops when the Space sleeps. v2 plan = external GitHub Actions cron pinging a webhook.

**Verification:** `pytest tests/test_bookmark_round_trip.py tests/test_mailer_dry_run.py`. Manual: subscribe self, schedule a reminder for `now + 1 min`, observe email arrives.

---

### Phase D — Gradio UI (deterministic reader, no LLM yet)
10. **D1** `app.py` — single-page Gradio app:
    - **Header:** email input (required), "Resume reading" button, settings modal (max_minutes slider 10–60, reminder opt-in toggle + `gr.Textbox` HH:MM time).
    - **Reader panel:** `gr.Markdown` showing current verse (Sanskrit on top, English below, ref like `BG 2.47`). Two `gr.Audio` players: Sanskrit autoplay → English autoplay, then advance. `gr.State` holds the iterator + `remaining_seconds`. **Stop** button → `bookmarks.save_position()` immediately.
    - **Status strip:** `"Reading from BG2.47 — 7m32s remaining of 10m"`.
11. **D2** Cold-start sequence (mirrors `kanikatestmodel/spaces/smoltestagent/app.py`):
    `ensure_corpus()` → `ensure_audio()` → open SQLite → start APScheduler → launch Gradio.

**Verification:** open `http://localhost:7860`, enter email, click Resume, watch text + audio advance for 10 min, click Stop, refresh, confirm Resume picks up the next verse.

---

### Phase E — Smolagents chat layer (LLM-driven explanations)
12. **E1** `agent/tools/verse_lookup.py` — `Tool` subclass with `forward(chapter: int, verse: int) -> str` returning Sanskrit + English of the requested verse. Same shape as `kanikatestmodel/phase-5-agents/tools/calculator.py`.
13. **E2** `agent/tools/verse_search.py` — `Tool` taking a natural-language query, runs `Retriever().query(...)` over the `gita_verses` Chroma collection, returns top-3 verse refs + English text. Mirrors `kanikatestmodel/phase-5-agents/tools/rag_search.py`.
14. **E3** `agent/tools/jump_to.py` — `Tool` that updates the current `gr.State` reader position so the user can say "jump to chapter 4 verse 7".
15. **E4** `agent/build_agent.py` — `InferenceClientModel(model_id="meta-llama/Llama-3.3-70B-Instruct", provider="together", token=_read_token(), temperature=0.0)` + `ToolCallingAgent(tools=[VerseLookup, VerseSearch, JumpTo], max_steps=4)`. Identical scaffolding to `kanikatestmodel/spaces/smoltestagent/app.py::build_agent()`.
16. **E5** Add an "Ask the Sage" `gr.Chatbot` panel below the reader. Wrap user input with a grounding preamble: *"Answer using only the Bhagavad Gita verses returned by `verse_search`. Cite verse refs in `[BGx.y]` form."* Reuse the `REFUSAL_PHRASE` pattern from `kanikatestmodel/phase-3-rag/rag/pipeline.py`.

*Phase E depends only on Phase A — can be built in parallel with B/C/D.*

---

### Phase F — Hugging Face Space deployment
17. **F1** `requirements.txt`:
    ```
    gradio>=5.0,<6
    smolagents==1.24.0
    sentence-transformers==5.4.1
    chromadb==1.5.9
    huggingface_hub>=0.36,<1.0
    apscheduler>=3.10,<4
    gtts>=2.5
    mutagen>=1.47
    datasets>=2.18
    audioop-lts; python_version >= "3.13"
    ```
18. **F2** `README.md` with HF Space frontmatter (`sdk: gradio`, `sdk_version: 5.0.0`, `app_file: app.py`).
19. **F3** Bake `data/gita.sqlite` + `data/.chroma/` + `data/audio_cache/` **into** the upload (do NOT add them to `IGNORE_PATTERNS` — opposite of `kanikatestmodel/spaces/smoltestagent/_deploy.py`). Reason: audio synthesis takes minutes, eliminating cold-start cost is worth the upload size (~50–100 MB).
20. **F4** `_deploy.py` — clone of `kanikatestmodel/spaces/smoltestagent/_deploy.py`. Change `REPO_ID = "kanika23oct/BhagwadGitaReadingAgent"`. Add Space secrets: `HF_TOKEN`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` via `api.add_space_secret()`.

---

## 6. Reuse map (existing files in this workspace)

| Need | Reuse from |
|---|---|
| `Tool` subclass template | [kanikatestmodel/phase-5-agents/tools/calculator.py](kanikatestmodel/phase-5-agents/tools/calculator.py) |
| Dependency-injected RAG tool | [kanikatestmodel/phase-5-agents/tools/rag_search.py](kanikatestmodel/phase-5-agents/tools/rag_search.py) |
| Agent factory + REPL skeleton | [kanikatestmodel/phase-5-agents/SmolAgentChat.py](kanikatestmodel/phase-5-agents/SmolAgentChat.py) |
| Gradio cold-start pattern + `_read_token()` | [kanikatestmodel/spaces/smoltestagent/app.py](kanikatestmodel/spaces/smoltestagent/app.py) |
| `ensure_index()` idempotency pattern | [kanikatestmodel/spaces/smoltestagent/build_index.py](kanikatestmodel/spaces/smoltestagent/build_index.py) |
| `_deploy.py` (HfApi upload + add_space_secret) | [kanikatestmodel/spaces/smoltestagent/_deploy.py](kanikatestmodel/spaces/smoltestagent/_deploy.py) |
| MiniLM embedder | [kanikatestmodel/phase-3-rag/ingestion/embedder.py](kanikatestmodel/phase-3-rag/ingestion/embedder.py) |
| Chroma retriever | [kanikatestmodel/phase-3-rag/retrieval/retriever.py](kanikatestmodel/phase-3-rag/retrieval/retriever.py) |
| Grounded prompt + REFUSAL phrase | [kanikatestmodel/phase-3-rag/rag/pipeline.py](kanikatestmodel/phase-3-rag/rag/pipeline.py) |
| Pinned versions | [kanikatestmodel/spaces/smoltestagent/requirements.txt](kanikatestmodel/spaces/smoltestagent/requirements.txt) |

---

## 7. Out of scope for v1

- Multi-language UI (English UI only).
- Word-level audio↔text sync.
- Multi-agent orchestration (autogen-style reader↔explainer↔scheduler).
- Reminders that survive HF Space sleep — documented as v2 (external cron).
- Authentication / passwords — email is a soft identifier.
- Mobile app, browser push, calendar integration.
- Translations beyond what the dataset already supplies.

---

## 8. Open items for review

1. **Email sender account** — Gmail with App Password is the recommendation. Need a Gmail account dedicated to this app (or a SendGrid/Resend free-tier account if Gmail is undesirable).
2. **Sanskrit TTS quality** — gTTS `lang='hi'` is acceptable but not authentic. If pronunciation feels wrong on first listen, fall back to "show Sanskrit text only, audio in English only" for v1.
3. **Reminder content** — what should the email actually say? Default proposal: *"Continue your Bhagavad Gita reading. You left off at BG{chapter}.{verse}. Click here to resume: {space_url}?email={email}"*. Confirm wording.
4. **HF Space hardware tier** — free CPU is enough for the deterministic reader, but the smolagents chat panel calls HF Inference Providers (Together) which uses your token's quota. Is that acceptable, or should the chat panel be opt-in?

---

## 9. Out-of-mode notes (for the implementing session)

This document was authored in chat planning mode. To start implementing:

- Switch to a build/agent mode with file-edit + terminal tools.
- First commit should be Phase A1 + A2 + A3 (data ingestion only) — verify
  `sqlite3 data/gita.sqlite "SELECT COUNT(*)"` returns 700 before moving on.
- Do not add any code to this PLAN.md — keep it as a living spec.

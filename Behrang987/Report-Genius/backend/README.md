# RICS Template-Agnostic Backend (v2)

A redesigned backend that treats report **structure as data** discovered from an
operator-provided **report template**, with **standard paragraphs** supplying
approved wording. Surveyors upload **notes only**.

See [docs/DEVIATIONS.md](docs/DEVIATIONS.md) for intentional differences from the original v2 spec.

| Spec default | This deployment |
|--------------|-----------------|
| Anthropic Claude | **OpenAI** (`backend/llm/openai_client.py`) |
| Tenant `POST /api/upload/template` | **Operator PDF + Word bundle** at startup |
| Single schema source | PDF = structure; Word = MASTER RAG wording |

## Operator bundle

All operator-provided material lives in `Master Standard report and paragraphs/`:

```
Master Standard report and paragraphs/
  SAMPLE LEVEL 3 REPORT NCS.pdf           -> REPORT TEMPLATE (schema: section order, titles, ratings)
  HB-BS STANDARD PARAS v6 Sept 2015.doc  -> STANDARD PARAGRAPHS (MASTER RAG: approved wording)
```

| File | Role | Ingest treatment |
|------|------|------------------|
| **PDF report template** | Defines report structure | Schema discovery only (`schema.json`) |
| **Word standard paragraphs** | Optional firm boilerplate | MASTER FAISS via tenant upload or gated `/admin/template` |
| **Field notes** | Surveyor input per job | Not scrubbed; parsed verbatim |
| **Reference uploads** | Each tenant's past completed reports via `POST /api/upload/reference` | REFERENCE FAISS (scrubbed) — **the generation source at every level** |

## PII two-tier policy

| Stage | Document / context | Scrubbing | Guard |
|-------|-------------------|-----------|-------|
| Field notes | Surveyor input | **None** — parsed verbatim | Output/DOCX gate redacts generated text only |
| Standard paragraphs (Word) | TIER_MASTER | None at ingest | `assert_no_pii()` rejects address/postcode |
| Reference uploads | TIER_REFERENCE | `scrub_reference_for_ingest()` at ingest | Unscrubbed chunks dropped |
| Mapped paragraph output | Generated text | Per-paragraph + batch `assert_no_pii()` | Full `scrub()` on output if residual PII |

**Report mapping is sourced from the tenant's own past reports (REFERENCE tier) at
every interference level** (`minimum`/`medium`/`maximum` all use
`search_for_reference_mapping`). Shared operator Word boilerplate is not seeded at
boot; tenants upload their own standard paragraphs. `search_for_generation`
(MASTER-only) remains for that per-tenant catalogue.

## Pipeline

```
report template (PDF)  -> schema.json (canonical RICS L3 sections, order, ratings)
past reports (per tenant) -> REFERENCE RAG (scrubbed) — baseline wording per section
notes                  -> schema-driven parse (verbatim) -> section retrieve (REFERENCE)
                       -> lexical rerank -> LLM weave notes onto baseline paragraph
                       -> schema-ordered DOCX (empty sections omitted)
```

## Configuration

Copy [`.env.example`](.env.example) to the repo root `.env`. Key settings:

| Setting | Default | Purpose |
|---------|---------|---------|
| `paragraph_min_chars` | `80` | Minimum RAG chunk size |
| `paragraph_max_chars` | `1200` | Maximum RAG chunk size |
| `retrieval_top_k` / `rag_top_k` | `5` | Paragraphs retrieved per section |
| `max_tokens_mapping` | `2048` | Mapping LLM token limit |
| `max_tokens_grounding` | `1024` | Grounding LLM token limit |
| `max_tokens_discovery` | `4000` | Discovery enrichment token limit |
| `use_llm_paragraph_mapping` | `false` | When false, report text is the **full RAG paragraph verbatim** with notes in blanks or appended |
| `template_docx_path` | *(empty)* | Optional branded DOCX export template |
| `ai_transparency_footer_enabled` | `false` | Global DOCX footer default |

**Re-ingest required** after changing `paragraph_min_chars` / `paragraph_max_chars` (restart or `POST /admin/template/reingest`).

## API

| Route | Purpose |
|-------|---------|
| `GET /api/schema` | Sections discovered from the **report template** |
| `PATCH /api/schema` | Operator corrections (e.g. `section_alias_map` overrides) |
| `POST /api/report/preview` | JSON preview with `manual_review_required` |
| `POST /api/report/generate` | DOCX download (`survey_report_draft.docx`) |
| `POST /api/upload/reference` | Upload a past report (scrubbed, REFERENCE tier) |
| `POST /auth/register`, `POST /auth/login` | JWT tenant auth |
| `GET /health` | `master_loaded` (schema present), `reference_ready`, FAISS counts |
| `POST /admin/template/reingest` | Re-ingest operator bundle (gated) |

Generation returns **400** when the schema is missing or the tenant has no REFERENCE
content for the requested sections.

## Operator checklist

1. Keep the PDF report template in the operator folder (schema is canonical RICS L3).
2. On boot, confirm `GET /health` shows `master_loaded: true` (schema installed).
3. Each tenant uploads its **own past reports** (`POST /api/upload/reference`) — these
   are the generation baseline at every level — then **notes only** per job.
4. To update structure: replace the template and restart (or admin reingest).

## Running

```bash
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload
```

Open **http://localhost:8000** for the legacy survey UI (`frontend/index.html`) or **`/v2.html`** for the simplified demo.

Docker: `docker compose -f docker-compose.v2.yml up --build`.

## Tests

```bash
python -m pytest backend/tests -q -o addopts=""
```

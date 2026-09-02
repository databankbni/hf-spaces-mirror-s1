# Intentional Deviations from the Original v2 Spec

This deployment closes the v2 spec gap while preserving the following locked decisions.

## Onboarding

- **Spec:** `POST /api/upload/template` for tenant master upload + schema discovery.
- **This deployment:** Operator PDF + Word bundle ingested at startup (`backend/startup.py`) plus optional gated `/admin/template` override. No tenant template upload route.

## LLM provider

- **Spec:** Anthropic Claude (`anthropic_api_key`, `claude-sonnet-4-20250514`).
- **This deployment:** OpenAI via `backend/llm/openai_client.py` (`openai_api_key`, `gpt-5-nano` / `gpt-5.4-nano` defaults).

## Embeddings

- **Spec:** OpenAI `text-embedding-3-small` only.
- **This deployment:** Configurable `embedding_provider` with OpenAI embeddings default (`text-embedding-3-small`). Local `jinaai/jina-embeddings-v3` remains available when `EMBEDDING_PROVIDER=local`.

## Surveyor notes (Security #1)

- **Spec:** Scrub `raw_notes` before any LLM call; middleware may return 400 on PII in requests.
- **This deployment:** Notes are parsed **verbatim**. Request middleware logs EMAIL/POSTCODE but does not block. PII scrubbing applies to REFERENCE RAG ingest and generated DOCX output.

## Generation RAG

- **Spec:** Allows REFERENCE tier as style fallback during mapping.
- **This deployment:** Mapping is sourced from each tenant's **own past reports
  (REFERENCE tier)** at every interference level via `search_for_reference_mapping()`.
  Shared operator Word boilerplate is **not seeded at boot**; tenants upload their
  own standard paragraphs. `search_for_generation()` (MASTER-only) remains for that
  per-tenant catalogue. Per-tenant isolation: a tenant only ever retrieves its own
  scrubbed reports.

## Legacy `app/`

The original `app/` package has been **removed**. `backend/` is the only stack.

## Additional extensions (beyond spec)

| Feature | Route / setting |
|---------|-----------------|
| JWT auth | `/auth/register`, `/auth/login` |
| Health | `GET /health` with `reference_ready` + FAISS counts |
| Admin reingest | `POST /admin/template/reingest` |

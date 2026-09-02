# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Gradio-based MCP (Model Context Protocol) server that exposes Opentrons protocol tools
(`chat`, `get_relevant_api_docs`, `simulate_protocol`) for AI agents.

Docs come from the [Opentrons Knowledge](https://github.com/Opentrons/knowledge) corpus and are
committed under `storage/` so Hugging Face Spaces can run from git alone.

## Updating docs (only process)

Pin a knowledge release version, sync it, commit `storage/`:

```bash
# version is the corpus id; release tag is knowledge-v<version>
make sync-knowledge KNOWLEDGE_VERSION=9.0.0-k1
# then commit storage/docs and storage/api_docs
```

What sync does:

1. Downloads `opentrons-knowledge-<version>.tar.zst` into `.cache/opentrons-knowledge/downloads/`
2. Unpacks the corpus under `.cache/opentrons-knowledge/corpora/<version>/`
3. Materializes runtime files into `storage/` (AI guides + MkDocs API docs + struct catalog)
4. By default, rewrites each `api_docs_struct.md` `<about>` with Claude Sonnet 5 against the
   freshly materialized pages (`ANTHROPIC_API_KEY` required). Offline fallback:
   `make sync-knowledge CLAUDE_ABOUTS=0`

Runtime only reads `storage/`. There is no download path at app startup.

Also bump `knowledge_version` in `api/settings.py` (or `KNOWLEDGE_VERSION` env) to match
`storage/api_docs/.knowledge-version`.

Layout:

```text
storage/
  docs/*.md                      # AI guides (system context)
  api_docs/
    .knowledge-version           # e.g. 9.0.0-k1
    .api-level                   # e.g. 2.28
    api_docs_struct.md           # generated catalog for get_relevant_api_docs
    docs/v2/**/*.md              # MkDocs Python API docs
.cache/opentrons-knowledge/      # sync download/unpack only (gitignored)
```

`api_docs_struct.md` `<about>` text is Claude-written during sync (model:
`knowledge_about_model`, default `claude-sonnet-5`) from the freshly materialized pages.
If Claude is disabled or a page fails, a local extract fallback is used for that page.
Abouts are never retained as a separate hand-edited catalog.

Each sync wipes `storage/docs` and `storage/api_docs` first, so only the pinned corpus
contents remain (no Protocol Designer leftovers, Sphinx scripts, or curated about files).

## Architecture

- **[app.py](app.py)**: Gradio MCP entrypoint
- **[api/domain/anthropic_predict.py](api/domain/anthropic_predict.py)**: Chat + tool loop; loads `storage/`
- **[api/knowledge/](api/knowledge/)**: `sync_knowledge` (CLI) and `load_knowledge_runtime` (app)

## Development Environment

```bash
uv venv
uv pip install -r requirements.txt
# set ANTHROPIC_API_KEY in .env
make sync-knowledge   # when bumping the knowledge pin
make local-run
```

## Testing

```bash
uv run pytest
```

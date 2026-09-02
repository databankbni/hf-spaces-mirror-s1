# reference/ — shared eval reference data

Cross-cutting data that more than one experiment depends on, kept in one place so the experiments can't drift. (Distinct from `discovery-and-conformance/`, which is the reference *area* for host-app/capability facts — this folder is for **eval infrastructure**: the models and providers we run experiments against.)

## `models.json` — the model/provider registry

The single source of truth for the models we commonly test. Every experiment that calls models should consume this list rather than keep its own copy.

Each entry is minimal — just identity, not per-run knobs:

| field | meaning |
| --- | --- |
| `label` | stable short name used in results/datasets (e.g. `claude-fable-5`). Unique. |
| `provider` | how it's reached: `huggingface` (the HF Inference Providers router, `https://router.huggingface.co/v1`, one `HF_TOKEN` — **the default route for open-weight models**), `anthropic` / `openai` / `google` (the vendor's native first-party SDK via `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY`), `moonshot` (Moonshot's native first-party API — OpenAI-compatible chat completions at `https://api.moonshot.ai/v1`, key `MOONSHOT_API_KEY`; the vendor's own route to the Kimi models, kept alongside the router route where both exist — `kimi-k3` and `kimi-k3-hf` are the same model reached two ways), or `lan` (a local OpenAI-compatible server — Ollama/llama.cpp/vLLM — via `LAN_BASE_URL`/`LAN_API_KEY`). |
| `model` | the provider's model id: an HF Hub id (`zai-org/GLM-5.2`), a native vendor id (`claude-fable-5`), or a local model id (`llama3.2:3b`). |

Run-specific concerns (temperature, HF provider pinning via the `<hub-id>:<provider>` suffix, `tool_choice`, retries) belong in the **consuming** experiment, keyed by `label` — not here. Keep this file identity-only.

### Adding a model

Add one line with a unique `label`, the right `provider`, and the `model` id. Every consumer picks it up on its next run (a vendored copy may need re-syncing — see below).

## `inference-provider-capabilities.{md,jsonl}` — provider capability snapshot

Which Hugging Face Inference Providers expose **tool calling** and **structured output** (plus pricing/context) per `(model, provider)`, so experiments can pick a route that actually supports the feature they need. `models.json` is identity-only; this captures the orthogonal *capability* facts. Sourced from HF's Inference Providers catalog (<https://router.huggingface.co/v1/models>). It is a dated **snapshot** — see the `.md` for how to refresh, and re-pull if it's more than ~7 days old.

### Consumers

- **`mcp/explicit-state-handles/harness/`** (TypeScript) — loads this file directly (`src/index.ts` → `loadModels()` reads `../../../../reference/models.json`); falls back to its built-in `DEFAULT_MODELS` if absent. Speaks OpenAI-compatible chat only, so it runs `huggingface`, `openrouter`, and `lan` entries and skips native-SDK entries with a warning.
- **`mcp/tool-schemas/companion-space/`** (Python, deploys as its own Hugging Face Space) — because the Space deploys from its own subfolder, it can't read a repo-root file at runtime, so it keeps a **vendored copy** `companion-space/models.json` that its `selftest.py` asserts is **byte-for-byte equal** to this file (the same drift-check discipline as `mcp/tool-schemas/schemas.json`). Its proxy serves the `huggingface` entries through the HF router; `direct_providers.py` (local-only) runs the `anthropic`/`openai`/`google`/`moonshot` entries through each vendor's native SDK or first-party endpoint. After editing this file, re-copy it over `companion-space/models.json` or that drift check fails.

This mirrors the project's single-source-of-truth pattern: edit the canonical file here; vendored copies are byte-equal mirrors guarded by a drift check, never hand-edited.

## `provider-endpoint-notes.md` — operational endpoint learnings

Dated, provenance-linked record of vendor-endpoint *behavior* discovered while running experiments here: schema-validation gates (Moonshot's flavored-schema `items: false` rejection, Anthropic's top-level combinator gate), tool_choice/thinking policies (Kimi K3's required-only forcing, the GPT-5.6 reasoning gate), per-model quirks, and gateway footguns (the `probe_hf.py` scoped-run clobber). Read it before wiring a new arm against any of these endpoints; add to it (with a date + provenance pointer) whenever an experiment surfaces a new endpoint fact. This file exists so learnings live in the repo rather than in any one machine's or agent's local memory.

## Historical registries


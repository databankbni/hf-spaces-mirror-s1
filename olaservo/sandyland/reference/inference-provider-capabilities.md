# Inference-provider capabilities — tools & structured output

A snapshot of which Hugging Face Inference Providers expose **tool calling** and **structured output** (server-side JSON-schema / `response_format` enforcement) for each model, with pricing and context length. Complements `models.json` (identity only) by recording per-`(model, provider)` *capabilities* — the thing that actually decides whether a given route can run an agentic or JSON-constrained experiment.

**Source:** Hugging Face — Inference Providers catalog, <https://huggingface.co/inference/models> (author: Hugging Face). Data pulled from the catalog's backing endpoint <https://router.huggingface.co/v1/models>.
**Snapshot retrieved:** 2026-07-27. **Rows:** 285 live `(model, provider)` pairs across 129 models and 13 providers.

> ⚠️ **Snapshot, not live.** These booleans and prices change as providers come and go. If this snapshot is more than **7 days old**, re-pull before relying on it — see "Refreshing" below. The `retrieved` field on every JSONL record carries the snapshot date so staleness is self-evident.

## Data — `inference-provider-capabilities.jsonl`

Newline-delimited JSON, one record per live `(model, provider)` pair, with full provenance on each record (HF-ready per the repo's dataset convention).

| field | meaning |
| --- | --- |
| `model` | HF model id, e.g. `zai-org/GLM-5.2` |
| `owned_by` | model owner/org |
| `provider` | inference provider serving it, e.g. `deepinfra` |
| `context_length` | context window in tokens (`null` if the provider didn't report one) |
| `input_price_per_mtok` / `output_price_per_mtok` | USD per 1M tokens (`null` if unpriced) |
| `supports_tools` | provider supports function/tool calling |
| `supports_structured_output` | provider enforces structured output (JSON schema / `response_format`) |
| `is_model_author` | provider is the model's first-party host |
| `retrieved` | snapshot date (source of truth for staleness) |
| `source` / `endpoint` | provenance URLs |

Only `status: "live"` rows are kept — one record per live `(model, provider)` pair. Live-but-capability-less rows are kept as-is (`featherless-ai` reports no tools and no structured output on every model it serves, and that "serves it, can't do tools" fact is exactly what a route-picking consumer needs to see).

## What the snapshot shows

**Both tools + structured output:** 83 provider rows across **54 models**. **Tools-only** (function calling but no enforced structured output): 93 rows.

### Provider capability profile

| Provider | live rows | tools | tools **+** structured output |
| --- | ---: | ---: | ---: |
| deepinfra | 50 | 46 | **31** |
| novita | 59 | 44 | 14 |
| together | 22 | 17 | 13 |
| nscale | 17 | 10 | 8 |
| scaleway | 9 | 9 | 7 |
| ovhcloud | 7 | 6 | 6 |
| publicai | 9 | 5 | 4 |
| zai-org | 17 | 14 | **0** |
| fireworks-ai | 12 | 12 | **0** |
| cohere | 12 | 6 | **0** |
| groq | 4 | 4 | **0** |
| cerebras | 3 | 3 | **0** |
| featherless-ai | 64 | 0 | 0 |

**Reading it:** `deepinfra` is the widest-coverage route that supports both, and the cheapest on most models; `together`, `scaleway`, `nscale`, `ovhcloud` also support both broadly. `fireworks-ai`, `zai-org`, `groq`, `cerebras`, and `cohere` are effectively **tools-only** — they never expose structured output in this snapshot. So whether a model "supports both" often depends on *which provider you route to*, not the model itself.

### Notable capability gaps

- **`moonshotai/Kimi-K3`** is **new in this snapshot** (absent on 2026-07-18, when the only route to K3 was Moonshot's own API): one provider, `together`, with both tools and structured output — 1M context, $3 / $15 per 1M tokens, the priciest open route in the catalog.
- **`zai-org/GLM-4.7`** (and `GLM-4.7-Flash`) is tools-only on **every** provider that serves it — no structured-output route exists. (`deepseek-ai/DeepSeek-V4-Flash`, tools-only-everywhere in the 2026-07-05 snapshot, has since gained structured output on `deepinfra` — capability drift in action.)
- The older **MiniMax M-series** (M1-80k/M2/M2.1) is tools-only (`novita`); `MiniMax-M3` gains structured output on `together`. **Kimi K2.x** structured-output routes vary by version: `K2.6` on `deepinfra`/`together` (it gained `deepinfra` since 2026-07-18), `K2.7-Code` on `deepinfra`/`novita`/`together`, `K2-Instruct` tools-only.
- **`thinkingmachines/Inkling`** moved hosts between snapshots: on 2026-07-18 `together` served it with tools + structured output; on 2026-07-27 `together` reports **neither**, and a new `deepinfra` route carries tools (no structured output). Capability drift on a model this repo actively measures — see the caveat below.
- **`XiaomiMiMo/MiMo-V2.5-Pro`** flipped from no-tools to **tools + structured output** on `deepinfra`, and `Qwen/Qwen3.6-35B-A3B` **lost** its `deepinfra` route entirely (only `scaleway` still serves it with tools).
- Same model, different capability by provider remains common — whether a model "supports both" often depends on which provider you route to, not the model itself.

> ⚠️ **Capability drift is real and fast.** Between the 2026-07-18 and 2026-07-27 pulls, 10 `(model, provider)` pairs appeared, 7 disappeared, and 24 flipped a capability boolean — on a catalog of ~285 rows. (Two of those additions, `MiniMax-M2.5`/`M2.7` on `deepinfra`, showed up *between two pulls minutes apart* on 2026-07-27.) Any experiment that pinned a serving host from an older snapshot should re-verify the pin still exists before trusting a re-run.

### Cheapest "both" routes (illustrative)

| Model | Cheapest both-capable provider | Context | $ In / Out (1M) |
| --- | --- | ---: | --- |
| Qwen/Qwen3-4B-Instruct-2507 | nscale | 262K | 0.01 / 0.03 |
| Qwen/Qwen3-4B-Thinking-2507 | nscale | 262K | 0.01 / 0.03 |
| openai/gpt-oss-20b | deepinfra | 131K | 0.03 / 0.14 |
| openai/gpt-oss-120b | deepinfra | 131K | 0.037 / 0.17 |
| google/gemma-3-12b-it | deepinfra | 131K | 0.05 / 0.15 |

## Refreshing

Re-pull whenever the snapshot is older than ~7 days (or a provider/model you care about changed). The generator is checked in next to the data — [`refresh-capabilities.py`](refresh-capabilities.py) (no API key needed; the catalog endpoint is public):

```bash
cd reference
python refresh-capabilities.py --diff --summary     # pull, rewrite the JSONL, report drift + the .md numbers
python refresh-capabilities.py --dry-run --diff     # look before you leap: report only, write nothing
```

It keeps only `status: "live"` rows, flattens each `providers[]` entry to one record, stamps `retrieved` with the pull date, rounds prices, and writes the file in its frozen field order sorted by model then provider — so a re-pull produces a clean diff. `--diff` lists every `(model, provider)` pair added, removed, or capability-flipped since the committed snapshot; `--summary` recomputes the hand-maintained numbers above (row/model counts, the provider table, the cheapest-routes table) to paste in. **The `.md` prose is not auto-generated** — update the snapshot date, the counts, the provider table, the notable-gaps bullets, and the cheapest-routes table by hand from that output.

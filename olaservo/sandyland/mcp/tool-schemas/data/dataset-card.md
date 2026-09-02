# Dataset card — tool input schema fidelity

This dataset measures whether models honor JSON Schema 2020-12 keywords when **calling** a tool. Each of six demo tools' verbatim `inputSchema` (single source of truth: [`../schemas.json`](../schemas.json)) is sent as a forced tool call's parameters, and every returned set of arguments gets a verdict. This is the production MCP path: SEP-2106 makes this vocabulary legal in `inputSchema`, and the model is the party that must conform when it emits a tool call.

**5,160 rows: 24 models (25 model-arms), 3 API arms, 6 tools, 20 trials per cell**, generated 2026-07-05 with scoped additions through 2026-07-27 (see Provenance). **The findings are written up in [`../README.md`](../README.md)** — this card documents how the data was produced, what each file contains, and how to read the numbers.

## The six tools

| tool | keyword demonstrated |
| --- | --- |
| `lookup-record` | top-level `oneOf` |
| `create-payment` | nested `oneOf` with `const` discriminators ("const union") |
| `create-shipment` | `$ref` / `$defs` |
| `register-address` | `if` / `then` (with a `pattern`-constrained ZIP) |
| `plot-point` | 2020-12 tuple (`prefixItems` + `items: false`) |
| `get-enum-selections` | enum varieties: plain `enum`, `oneOf`/`anyOf` of `const`+`title` (SEP-1330), `enumNames` |

## Design — three arms

| arm (`transport`) | models | route |
| --- | --- | --- |
| `huggingface` | 11 open-weight models | HF Inference Providers router (`router.huggingface.co/v1`, OpenAI-compatible), each model pinned to one verified serving provider |
| `direct` | 14 natively-served models: Anthropic ×4, OpenAI ×6 (`strict` on/off), Google ×3, Moonshot ×1 | each vendor's own SDK and native tool-schema field |
| `direct-responses` | the same 6 OpenAI models (`strict` on/off) | OpenAI's `/v1/responses` endpoint — the vendor's recommended API surface |

Row count: 1,320 (HF) + 2,400 (direct) + 1,440 (direct-responses) = 5,160.

- **Pinning.** Each open model is pinned to one serving provider via the router's `<hub-id>:<provider>` model-id suffix, and the router's echoed model id is stored per row as `served_by` (`pin_drift = 0` across the dataset). 9 of the 11 opens are pinned to deepinfra; `inkling` and `kimi-k3-hf` to together, their only live provider. The measured unit for an open model is therefore **`(model × serving host)`**, not the model alone.
- **Roster.** The newest tool-capable model per open family (per the HF catalog snapshot in `reference/inference-provider-capabilities.jsonl`), plus three tiers per closed vendor — OpenAI at two generations, Anthropic plus its prior-generation flagship. Two models failed the feasibility gate and are excluded (`mimo-v2.5-pro`, `olmo-3-7b`). `kimi-k3` is the one model measured on **two** arms: Moonshot's own API (`kimi-k3`) and the HF router via together (`kimi-k3-hf`).
- **Operating points.** Sampling is each vendor's/host's default; no request sets `temperature`, `top_p`, or a seed (Anthropic's required `max_tokens` is 1024). Two recorded-per-row exceptions: the GPT-5.6 chat.completions cells run at `reasoning_effort="none"` because that endpoint refuses function tools at any other effort, and the `kimi-k3` cells run with `tool_choice="required"` because Moonshot refuses a specified tool_choice under its always-on thinking.
- **Prompts.** One fixed sentence per tool, with values that already conform to the schema (`lookup-record`'s adds one structural nudge). Rates are therefore **upper bounds under favorable phrasing** — see the uncoached control below.

## Verdicts

Each trial gets one of five verdicts (re-derivable offline from the stored `arguments` via `reclassify.py`; the logic is the Python port of the playground's checks):

- **`honored`** — the arguments validate against the verbatim schema (a real 2020-12 validator) and the demonstrated keyword is respected: exactly one `oneOf` branch, the right `const` discriminator, a 2-element tuple. It measures structure, not content accuracy. (Two tools hand the model an already-conforming value — the ZIP, the card number — so those cells partly measure placement rather than derivation; see the copy-vs-derive probe.)
- **`rejected`** — the provider's API refused the schema at request time. A host property, deterministic (it repeats 20/20).
- **`invalid`** — the provider served the schema but the model's arguments fail validation. A model-skill failure.
- **`dropped`** — valid arguments that flatten the keyword. Near-zero **by design** (4 of 5,160 rows): five of the six schemas pin their keyword so flattening lands in `invalid` instead.
- **`error`** — transport noise (rate limits, no-tool-call responses); 13 rows, excluded from every denominator.

## Metrics — how to read the numbers

- **`honored_of_served`** (the headline metric) = honored / (honored + dropped + invalid + rejected). `summary.csv` carries it per cell with a served-based Wilson 95% CI (`hos_ci_lo`/`hos_ci_hi`).
- It pools two different phenomena, so `summary.csv` also reports the split: **`accepted_pct`** = accepted / served (did the API even *accept* the schema — a deterministic host property) and **`honored_given_accepted`** = honored / accepted (given acceptance, did the model fill it out correctly). The two factor exactly: `honored_of_served = accepted_pct × honored_given_accepted`.
- Don't rank models by the pooled number. Two cells can both read 0 for opposite reasons: claude-haiku-4.5 × create-payment failed in the model (accepted 1.00, skill 0.00), while gpt-5.4 × create-payment (strict) never got past the API (accepted 0.00). There is deliberately no single scalar ranking a model's keyword ability.
- **Legacy column caveat:** the original `honored_rate` (and its CI) divides by all trials, errors included — kept unchanged for continuity; prefer `honored_of_served`.
- **Underpowered cells:** four cells rest on fewer than 20 served trials (the dataset's 13 `error` rows all fall in them), flagged by `summary.csv`'s `underpowered` column: gpt-oss-120b × enums (14 served), qwen3.5-397b × top-level `oneOf` (16), gemini-3.1-pro × `$ref` (18), kimi-k3-hf × const union (19).

## Files

**The main grid:**

- `runs.jsonl` — one row per (tool × model × arm × trial) with full provenance: timestamp, git SHA, requested provider/model, served-by echo, prompt, arguments, trimmed raw payload, latency, verdict + note. Columns added later (absent/`null` on older rows): `reasoning_effort`, `reasoning_tokens` (`direct-responses` rows), `tool_choice` (Moonshot rows).
- `summary.csv` — per-cell verdict distribution plus every metric above. Regenerated offline from `runs.jsonl` by `recompute_summary.py`.
- `run-meta.json` — run configuration: trials, transports, models, `hf_pins`.
- `cycle.csv` — the spec→render→behaviour join with the evalstate render atlas (below); `transport_diff.csv` — cohort-level arm comparison per tool.
- `evalstate-render.json` — vendored extract of Shaun Smith's [evalstate/tool-research](https://huggingface.co/spaces/evalstate/tool-research) render atlas (provenance block inside).

**Probe appendices** — each a targeted follow-up; the `.meta.json` files embed the exact variant schemas used:

- `cross_host.csv` — the same schemas on each open model's other tool-capable providers. Takeaway: "perfect" belongs to the `(model × host)` pair — some main-grid failures follow the model everywhere, others flip to 100% on a different host.
- `grammar_probe.csv` — prompted to *break* each schema, the models comply, so no host is quietly forcing conformance with a constrained decoder.
- `uncoached.csv` — every task re-phrased naturally, without the helpful hints. 115 of 128 comparable cells didn't change; coaching only props up weak models on the hardest keywords.
- `moonshot_family_probe.csv` — a same-model control showing Moonshot's API, not the Kimi models, is what rejects `prefixItems`.
- `title_const_probe.csv` — why Gemini fails the titled selects: Google's transport hides `oneOf`/`anyOf` branch `const`s from every Gemini generation, so even the passing model is reconstructing the wire values rather than reading them. (Tool-author note: plain `enum` + `enumNames` survives this path.)
- `strict_probe.csv` — what OpenAI `strict: true` actually forbids once its envelope boilerplate is satisfied: `oneOf` and `if`/`then`. Everything else is expressible, and every tool has a strict-compatible rework the models honor.
- `anthropic_strict_probe.csv` — the same decomposition for Anthropic's strict tool use: a smaller accepted subset than OpenAI's, no endpoint escape from the top-level-combinator gate, and a strict rework that fixes Haiku 4.5's one model-skill failure.
- `gpt56_reasoning_probe.csv` — the chat.completions "no function tools with reasoning" gate captured verbatim (it predates GPT-5.6), plus the discovery that `/v1/responses` honors all six schemas — later promoted to the `direct-responses` arm.
- `prompt_v2.csv` + `prompt_v2_crosshost.csv` — do models *derive* conforming values, or copy given ones? The effect proved too fragile (format-, phrasing-, and host-dependent) to be a finding, so it survives only as a caveat on the ZIP/card cells.
- `small_qwen_baseline.csv` — a scouting probe of small hosted Qwen models for a possible local-hosting follow-up; not part of the grid.

**A note on the strict "repairs":** they measure each vendor's accepted subset; they are not guidance. MCP's position (SEP-2106) is that tools publish standard JSON Schema 2020-12 and clients validate against it directly — per-provider schema rewriting reintroduces the translation layers the standard exists to remove. The gap is the provider API's to close.

## Provenance

- The grid was generated 2026-07-05/06 (HF arm + native arm). Later additions were **scoped merges** — each ran only its new cells and left prior rows byte-untouched (verified against pre-merge backups): the GPT-5.6 trio 2026-07-14, `claude-opus-4.8` 2026-07-16, the `direct-responses` arm + `inkling` 2026-07-18, `kimi-k3` 2026-07-19, `kimi-k3-hf` 2026-07-27.
- The paired output-role study (can a model *author* an object conforming to these schemas?) was split out on 2026-07-06 and later retired; its rows are not in this dataset.
- An earlier exploratory v1 run used a different gateway and roster and is not comparable; it lives in git history only.
- Everything downstream of the raw rows is re-derivable offline: `reclassify.py` re-derives every verdict from the stored `arguments`; `recompute_summary.py` rebuilds `summary.csv` from `runs.jsonl`. Neither calls a model.

## License / citation

License: data (this card, the CSVs, `runs.jsonl`) **CC-BY-4.0** (Creative Commons Attribution 4.0) — reuse freely with attribution; code (the harness, probes, demo servers, playground) **MIT** (see the repo-root `LICENSE`). Cite this repo ([olaservo/research-hub-public](https://github.com/olaservo/research-hub-public), `mcp/tool-schemas`) and, for the render-layer join, Shaun Smith's [evalstate/tool-research](https://huggingface.co/spaces/evalstate/tool-research). Tool schemas per MCP SEP-2106 (JSON Schema 2020-12 in tool inputs) and SEP-1330 (enum varieties).

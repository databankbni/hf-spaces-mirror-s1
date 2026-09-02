# Measuring tool input schema fidelity

[SEP-2106](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2106-json-schema-2020-12.md), released as part of the 2026-07-28 MCP spec, allows the full JSON Schema 2020-12 schema dialect at the root of an MCP tool's `inputSchema`. To see whether the full vocabulary survives contact with real inference stacks, I handed six demo tools' verbatim schemas to 24 models across their serving providers.

*Last updated 2026-08-06.*

## The result at a glance

Each (model × keyword) cell pools 20 trials. 125 of the 144 cells were **honored on every served trial** — the returned arguments validate against the verbatim schema and respect the demonstrated keyword. Percentages throughout are **honored-of-served**: honored trials out of trials actually served, with transport errors (rate-limit noise) excluded from the denominator.

The 19 exceptions, and which finding each belongs to:

| Model | Keyword | What happened | Finding |
| --- | --- | --- | --- |
| `claude-fable-5` | top-level oneOf | ⊘ rejected — the API refused the schema at request time | [Schema refusals](#schema-refusals) |
| `claude-sonnet-5` | top-level oneOf | ⊘ rejected at request time | [Schema refusals](#schema-refusals) |
| `claude-haiku-4.5` | top-level oneOf | ⊘ rejected at request time | [Schema refusals](#schema-refusals) |
| `claude-opus-4.8` | top-level oneOf | ⊘ rejected at request time | [Schema refusals](#schema-refusals) |
| `claude-haiku-4.5` | const union | ✗ invalid args on every served trial | [Sometimes it is just up to the model](#sometimes-it-is-just-up-to-the-model) |
| `gemini-3.1-pro` | enums | ✗ echoes the display title instead of the const on oneOf/anyOf fields | [Reconstructing the schema vs reading it](#reconstructing-the-schema-vs-reading-it) |
| `gemini-3.1-flash-lite` | enums | ✗ echoes the display title instead of the const on oneOf/anyOf fields | [Reconstructing the schema vs reading it](#reconstructing-the-schema-vs-reading-it) |
| `kimi-k2.7-code` | const union | 95% honored of served | [Sometimes it is just up to the model](#sometimes-it-is-just-up-to-the-model) |
| `kimi-k2.7-code` | $ref | 85% honored of served | [Sometimes it is just up to the model](#sometimes-it-is-just-up-to-the-model) |
| `kimi-k2.7-code` | prefixItems | 80% honored of served | [Sometimes it is just up to the model](#sometimes-it-is-just-up-to-the-model) |
| `qwen3.6-35b` | enums | 90% honored of served | [Sometimes it is just up to the model](#sometimes-it-is-just-up-to-the-model) |
| `qwen3.6-35b` | top-level oneOf | ✗ invalid args on every served trial | [Sometimes it is just up to the model](#sometimes-it-is-just-up-to-the-model) |
| `qwen3.5-397b` | enums | 95% honored of served | [Sometimes it is just up to the model](#sometimes-it-is-just-up-to-the-model) |
| `qwen3.5-397b` | top-level oneOf | ✗ invalid args on every served trial | [Sometimes it is just up to the model](#sometimes-it-is-just-up-to-the-model) |
| `minimax-m3` | prefixItems | ✗ on deepinfra only — fireworks-ai, novita, and together all serve it at 100% | [Serving host variance](#serving-host-variance) |
| `gemma-4-31b` | enums | 95% honored of served | [Sometimes it is just up to the model](#sometimes-it-is-just-up-to-the-model) |
| `gemma-4-31b` | top-level oneOf | 65% honored of served (0% without the coached prompt) | [Sometimes it is just up to the model](#sometimes-it-is-just-up-to-the-model) |
| `gpt-oss-120b` | enums | ✗ host-conditional — novita and scaleway reproduce it, fireworks-ai and together don't | [Serving host variance](#serving-host-variance) |
| `gpt-oss-120b` | $ref | 65% honored of served (30% uncoached) | [Sometimes it is just up to the model](#sometimes-it-is-just-up-to-the-model) |

## What the exceptions represent

### Schema refusals

In some cases the schema was refused by the provider API at request time. Anthropic's API and OpenAI's older chat-completions endpoint both refuse a top-level `oneOf`; Moonshot's API refuses the 2020-12 tuple form (`prefixItems` + `items: false`) with a validator error. This also varies by the serving host. In the case of `kimi-k3` the same model and the same schema was honored on every trial via Together but refused outright by Moonshot's own endpoint. Evidence: [main grid](#how-models-handled-each-keyword--the-main-grid) · [chat-completions vs responses](#openai-chat-completions-vs-responses-endpoints) · [cross-provider table](#the-same-model-on-different-providers).

### Serving host variance

The measured unit for open models is `(model × serving host)`.  Some failures can be attributed to the host rather than the model. `minimax-m3`'s `prefixItems` fails only on deepinfra — fireworks-ai, novita, and together all serve it at 100% — and `gpt-oss-120b`'s enums failure reproduces on novita and scaleway but not on fireworks-ai or together. A break-the-schema control confirmed the perfect scores aren't a constrained decoder forcing conformance. Evidence: [cross-provider table](#the-same-model-on-different-providers) · [forced-conformance check](#are-the-highest-fidelity-providers-forcing-conformance).

### Reconstructing the schema vs reading it

Both Gemini 3.1 models use plain `enum` fields perfectly but return the display *title* instead of the `const` on `oneOf`/`anyOf` option fields. A follow-up probe shows branch consts don't survive Google's function-declaration path at all: every Gemini generation quotes the titles, and even 3.5 Flash is reconstructing the wire values from `default` + option order rather than reading them — it just reconstructs well enough to score a pass. Evidence: [the title-vs-const decomposition](#the-gemini-title-vs-const-decomposition).

### Sometimes it is just up to the model

The remaining exceptions are genuine model skill, concentrated where a weaker model meets a hard keyword. Both Qwens emit invalid arguments for a top-level `oneOf` on every host tried (the failure follows the model); `claude-haiku-4.5` fails the `const` union its larger siblings pass; `kimi-k2.7-code` is mixed on three keywords; and `gemma-4-31b` manages the top-level `oneOf` only 65% of the time — and only with a helpful prompt. Evidence: [main grid](#how-models-handled-each-keyword--the-main-grid) · [cross-provider table](#the-same-model-on-different-providers).

### Coaching only matters at the edges

The default prompts hand the model already-conforming values, so an uncoached control re-ran 22 of the 24 models with natural phrasing. 115 of 128 comparable cells were identical and 15 models didn't change at all.  This seems to indicate that the perfect scores come from reading the schema, and not the prompt. But where a weak model meets a hard keyword, coaching props it up: `gemma-4-31b` drops from 65% to 0% on the top-level `oneOf`, `gpt-oss-120b` from 65% to 30% on `$ref`. Read the headline rates as upper bounds under favorable phrasing. Evidence: [the coaching control](#does-coaching-the-prompt-inflate-the-numbers).

## The evidence

### How to read these numbers (methodology & caveats)

The results come from handing each tool's verbatim `inputSchema` to a selection of models and providers over two buckets: open-weight models via Hugging Face's Inference Providers router (each pinned to one verified serving provider) and closed models via each vendor's own SDK.

- A cell counts as 'honored' if the returned arguments both validate against the verbatim schema and respect the demonstrated keyword (such as populating exactly one `oneOf` branch, handling a 2-element tuple, using the right `const` discriminator). Percentages are **honored-of-served**: honored trials out of the trials actually served (transport `error` rows, like rate-limit noise, are excluded from the denominator).
- A single honored-of-served number pools two different things: whether the provider's API even *accepted* the schema (a deterministic host gate) and, given acceptance, whether the model filled it out correctly (model skill).  So don't rank models by the pooled number: an Anthropic/OpenAI-chat 0.83 represents a deterministic API reject of one keyword, while a lower score elsewhere may be a genuine model failure.
- Each open-model verdict is specific to a (model × serving host) at a point in time and not 100% exhaustive of all possible hosts and configurations. These results are not meant to be a comprehensive decision guide on which providers to use. They are meant to be illustrative of how schema support varies, and what constraints you may need to consider as an MCP server, framework, or SDK author.
- Read the rates as upper bounds under favorable phrasing. The default prompts state each task in a single fixed sentence whose values already conform to the schema, and one of them (`lookup-record`'s "Use whichever single identifier the tool expects") explicitly nudges the expected structure.  See the coaching control below for a comparison with more natural phrasings.

### How models handled each keyword — the main grid

This results table reports one serving arm per model.  For closed vendors, this was the vendor's own API.  For open models, this represents a single pinned host.

- Native inference APIs were used for closed model examples, and/or models that were not available on Hugging Face Inference Providers (Claude, GPT, Gemini). The OpenAI rows in this table are the `/v1/responses` arm.  (OpenAI recommends this endpoint for function tools.)
- A sample of open model host providers through Hugging Face Inference were used for all other models. (The results in the table below are from Deepinfra for all open models, except for Inkling and Kimi 3, which were each available from only one host — Together.)

These results also reflect setting the API parameters to allow for these schema keywords, such as by setting strict mode to 'false' where applicable.

| Model                   | enums | top-level oneOf | const union | $ref | if / then | prefixItems |
| ----------------------- | ----- | --------------- | ----------- | ---- | --------- | ----------- |
| `claude-fable-5`        | ✓     | ⊘               | ✓           | ✓    | ✓         | ✓           |
| `claude-sonnet-5`       | ✓     | ⊘               | ✓           | ✓    | ✓         | ✓           |
| `claude-haiku-4.5`      | ✓     | ⊘               | ✗           | ✓    | ✓         | ✓           |
| `claude-opus-4.8`       | ✓     | ⊘               | ✓           | ✓    | ✓         | ✓           |
| `gpt-5.5`               | ✓     | ✓               | ✓           | ✓    | ✓         | ✓           |
| `gpt-5.4`               | ✓     | ✓               | ✓           | ✓    | ✓         | ✓           |
| `gpt-5.4-mini`          | ✓     | ✓               | ✓           | ✓    | ✓         | ✓           |
| `gpt-5.6-sol`           | ✓     | ✓               | ✓           | ✓    | ✓         | ✓           |
| `gpt-5.6-terra`         | ✓     | ✓               | ✓           | ✓    | ✓         | ✓           |
| `gpt-5.6-luna`          | ✓     | ✓               | ✓           | ✓    | ✓         | ✓           |
| `gemini-3.5-flash`      | ✓     | ✓               | ✓           | ✓    | ✓         | ✓           |
| `gemini-3.1-pro`        | ✗     | ✓               | ✓           | ✓    | ✓         | ✓           |
| `gemini-3.1-flash-lite` | ✗     | ✓               | ✓           | ✓    | ✓         | ✓           |
| `glm-5.2`               | ✓     | ✓               | ✓           | ✓    | ✓         | ✓           |
| `deepseek-v4-flash`     | ✓     | ✓               | ✓           | ✓    | ✓         | ✓           |
| `kimi-k2.6`             | ✓     | ✓               | ✓           | ✓    | ✓         | ✓           |
| `kimi-k2.7-code`        | ✓     | ✓               | 95%         | 85%  | ✓         | 80%         |
| `kimi-k3`               | ✓     | ✓               | ✓           | ✓    | ✓         | ✓           |
| `qwen3.6-35b`           | 90%   | ✗               | ✓           | ✓    | ✓         | ✓           |
| `qwen3.5-397b`          | 95%   | ✗               | ✓           | ✓    | ✓         | ✓           |
| `minimax-m3`            | ✓     | ✓               | ✓           | ✓    | ✓         | ✗           |
| `gemma-4-31b`           | 95%   | 65%             | ✓           | ✓    | ✓         | ✓           |
| `gpt-oss-120b`          | ✗     | ✓               | ✓           | 65%  | ✓         | ✓           |
| `inkling`               | ✓     | ✓               | ✓           | ✓    | ✓         | ✓           |

Key: **✓** honored on every served trial · **n%** honored on only that share of trials (mixed results, honored-of-served) · **✗** produces invalid args (fails 2020-12 validation) on every served trial · **⊘** rejected (the provider refused the schema at request time).

Two of the ✗ cells are attributable to the pinned serving host rather than the model: `minimax-m3`'s `prefixItems` fails only on deepinfra (fireworks-ai, novita, and together all serve it at 100%), and `gpt-oss-120b`'s enums failure is host-conditional (novita and scaleway reproduce it; fireworks-ai and together don't). The measured unit for open models is `(model × serving host)` — see the cross-host appendix in the [dataset card](https://github.com/olaservo/research-hub-public/blob/main/mcp/tool-schemas/data/dataset-card.md).

### OpenAI Chat Completions vs Responses endpoints

I also tested the same OpenAI models on the older `/v1/chat/completions` endpoint. On the chat-completions endpoint, the top-level `oneOf` was refused on every tier and both generations of model. The GPT-5.6 rows here were measured with `reasoning_effort="none"` because chat-completions refuses function tools at any other effort.

| Model | enums | top-level oneOf | const union | $ref | if / then | prefixItems |
| --- | --- | --- | --- | --- | --- | --- |
| `gpt-5.5` | ✓ | ⊘ | ✓ | ✓ | ✓ | ✓ |
| `gpt-5.4` | ✓ | ⊘ | ✓ | ✓ | ✓ | ✓ |
| `gpt-5.4-mini` | ✓ | ⊘ | ✓ | ✓ | ✓ | ✓ |
| `gpt-5.6-sol` | ✓ | ⊘ | ✓ | ✓ | ✓ | ✓ |
| `gpt-5.6-terra` | ✓ | ⊘ | ✓ | ✓ | ✓ | ✓ |
| `gpt-5.6-luna` | ✓ | ⊘ | ✓ | ✓ | ✓ | ✓ |

### The same model on different providers

As a side experiment, I re-ran the identical schemas on other tool-capable Hugging Face providers, then added Moonshot's own API in order to cover multiple Kimi model versions side by side on the same providers.

The `kimi-k3` row is the sharpest case in this table: the same model and the same six schemas on two delivery paths, and one keyword flips. Moonshot's API refuses the 2020-12 tuple (`prefixItems` + `items: false`) at request time, before the model ever sees it; Together serves the identical schema and K3 honors it on every trial. The ⊘ is the endpoint's, not the model's.

<table><thead><tr><th>Model</th><th>Keyword</th><th>deepinfra</th><th>fireworks-ai</th><th>novita</th><th>scaleway</th><th>together</th><th>zai-org</th><th>moonshot</th></tr></thead><tbody><tr><td rowspan="6"><code>deepseek-v4-flash</code></td><td>enums</td><td>100%</td><td>100%</td><td>100%</td><td>–</td><td>–</td><td>–</td><td>–</td></tr><tr><td>top-level oneOf</td><td>100%</td><td>100%</td><td>95%</td><td>–</td><td>–</td><td>–</td><td>–</td></tr><tr><td>const union</td><td>100%</td><td>0%</td><td>100%</td><td>–</td><td>–</td><td>–</td><td>–</td></tr><tr><td>$ref</td><td>100%</td><td>0%</td><td>100%</td><td>–</td><td>–</td><td>–</td><td>–</td></tr><tr><td>if / then</td><td>100%</td><td>100%</td><td>100%</td><td>–</td><td>–</td><td>–</td><td>–</td></tr><tr><td>prefixItems</td><td>100%</td><td>100%</td><td>100%</td><td>–</td><td>–</td><td>–</td><td>–</td></tr><tr><td rowspan="6"><code>kimi-k2.6</code></td><td>enums</td><td>100%</td><td>100%</td><td>100%</td><td>–</td><td>100%</td><td>–</td><td>100%</td></tr><tr><td>top-level oneOf</td><td>100%</td><td>⊘ 0%</td><td>100%</td><td>–</td><td>100%</td><td>–</td><td>100%</td></tr><tr><td>const union</td><td>100%</td><td>100%</td><td>100%</td><td>–</td><td>100%</td><td>–</td><td>100%</td></tr><tr><td>$ref</td><td>100%</td><td>100%</td><td>100%</td><td>–</td><td>100%</td><td>–</td><td>100%</td></tr><tr><td>if / then</td><td>100%</td><td>100%</td><td>100%</td><td>–</td><td>100%</td><td>–</td><td>100%</td></tr><tr><td>prefixItems</td><td>100%</td><td>100%</td><td>100%</td><td>–</td><td>100%</td><td>–</td><td>⊘ 0%</td></tr><tr><td rowspan="6"><code>kimi-k3</code></td><td>enums</td><td>–</td><td>–</td><td>–</td><td>–</td><td>100%</td><td>–</td><td>100%</td></tr><tr><td>top-level oneOf</td><td>–</td><td>–</td><td>–</td><td>–</td><td>100%</td><td>–</td><td>100%</td></tr><tr><td>const union</td><td>–</td><td>–</td><td>–</td><td>–</td><td>100%</td><td>–</td><td>100%</td></tr><tr><td>$ref</td><td>–</td><td>–</td><td>–</td><td>–</td><td>100%</td><td>–</td><td>100%</td></tr><tr><td>if / then</td><td>–</td><td>–</td><td>–</td><td>–</td><td>100%</td><td>–</td><td>100%</td></tr><tr><td>prefixItems</td><td>–</td><td>–</td><td>–</td><td>–</td><td>100%</td><td>–</td><td>⊘ 0%</td></tr><tr><td rowspan="6"><code>glm-5.2</code></td><td>enums</td><td>100%</td><td>100%</td><td>n/s</td><td>100%</td><td>80%</td><td>100%</td><td>–</td></tr><tr><td>top-level oneOf</td><td>100%</td><td>100%</td><td>n/s</td><td>100%</td><td>0%</td><td>100%</td><td>–</td></tr><tr><td>const union</td><td>100%</td><td>100%</td><td>n/s</td><td>100%</td><td>100%</td><td>100%</td><td>–</td></tr><tr><td>$ref</td><td>100%</td><td>⊘ 0%</td><td>n/s</td><td>0%</td><td>100%</td><td>0%</td><td>–</td></tr><tr><td>if / then</td><td>100%</td><td>100%</td><td>n/s</td><td>100%</td><td>100%</td><td>100%</td><td>–</td></tr><tr><td>prefixItems</td><td>100%</td><td>100%</td><td>n/s</td><td>100%</td><td>100%</td><td>100%</td><td>–</td></tr><tr><td rowspan="6"><code>qwen3.6-35b</code></td><td>enums</td><td>90%</td><td>–</td><td>–</td><td>75%</td><td>–</td><td>–</td><td>–</td></tr><tr><td>top-level oneOf</td><td>0%</td><td>–</td><td>–</td><td>0%</td><td>–</td><td>–</td><td>–</td></tr><tr><td>const union</td><td>100%</td><td>–</td><td>–</td><td>100%</td><td>–</td><td>–</td><td>–</td></tr><tr><td>$ref</td><td>100%</td><td>–</td><td>–</td><td>100%</td><td>–</td><td>–</td><td>–</td></tr><tr><td>if / then</td><td>95%</td><td>–</td><td>–</td><td>100%</td><td>–</td><td>–</td><td>–</td></tr><tr><td>prefixItems</td><td>100%</td><td>–</td><td>–</td><td>100%</td><td>–</td><td>–</td><td>–</td></tr><tr><td rowspan="6"><code>qwen3.5-397b</code></td><td>enums</td><td>100%</td><td>–</td><td>⊘ 0%</td><td>95%</td><td>–</td><td>–</td><td>–</td></tr><tr><td>top-level oneOf</td><td>0%</td><td>–</td><td>⊘ 0%</td><td>0%</td><td>–</td><td>–</td><td>–</td></tr><tr><td>const union</td><td>100%</td><td>–</td><td>⊘ 0%</td><td>100%</td><td>–</td><td>–</td><td>–</td></tr><tr><td>$ref</td><td>100%</td><td>–</td><td>⊘ 0%</td><td>100%</td><td>–</td><td>–</td><td>–</td></tr><tr><td>if / then</td><td>100%</td><td>–</td><td>⊘ 0%</td><td>100%</td><td>–</td><td>–</td><td>–</td></tr><tr><td>prefixItems</td><td>100%</td><td>–</td><td>⊘ 0%</td><td>100%</td><td>–</td><td>–</td><td>–</td></tr><tr><td rowspan="6"><code>minimax-m3</code></td><td>enums</td><td>100%</td><td>100%</td><td>100%</td><td>–</td><td>55%</td><td>–</td><td>–</td></tr><tr><td>top-level oneOf</td><td>100%</td><td>100%</td><td>100%</td><td>–</td><td>0%</td><td>–</td><td>–</td></tr><tr><td>const union</td><td>100%</td><td>100%</td><td>0%</td><td>–</td><td>100%</td><td>–</td><td>–</td></tr><tr><td>$ref</td><td>100%</td><td>100%</td><td>100%</td><td>–</td><td>100%</td><td>–</td><td>–</td></tr><tr><td>if / then</td><td>100%</td><td>100%</td><td>100%</td><td>–</td><td>100%</td><td>–</td><td>–</td></tr><tr><td>prefixItems</td><td>0%</td><td>100%</td><td>100%</td><td>–</td><td>100%</td><td>–</td><td>–</td></tr><tr><td rowspan="6"><code>gpt-oss-120b</code></td><td>enums</td><td>0%</td><td>100%</td><td>0%</td><td>0%</td><td>100%</td><td>–</td><td>–</td></tr><tr><td>top-level oneOf</td><td>100%</td><td>⊘ 0%</td><td>100%</td><td>100%</td><td>100%</td><td>–</td><td>–</td></tr><tr><td>const union</td><td>100%</td><td>100%</td><td>100%</td><td>100%</td><td>100%</td><td>–</td><td>–</td></tr><tr><td>$ref</td><td>100%</td><td>100%</td><td>40%</td><td>60%</td><td>95%</td><td>–</td><td>–</td></tr><tr><td>if / then</td><td>100%</td><td>100%</td><td>100%</td><td>100%</td><td>25%</td><td>–</td><td>–</td></tr><tr><td>prefixItems</td><td>100%</td><td>100%</td><td>100%</td><td>100%</td><td>100%</td><td>–</td><td>–</td></tr></tbody></table>

Honored-of-served %, 20 trials/cell. **–** means that the provider doesn't offer this model; **n/s** offered but did not reliably serve a forced tool call, so the pairing was excluded; **⊘** means that the provider's API refused the schema at request time.

### The Gemini title-vs-const decomposition

The example "enums" tool bundles six keywords (`enum` / `oneOf` / `anyOf` / `const` / `title` / `enumNames`). Both Gemini 3.1 models used the three plain-`enum` fields perfectly, but a follow-up probe (the title-vs-const decomposition in the [dataset card](https://github.com/olaservo/research-hub-public/blob/main/mcp/tool-schemas/data/dataset-card.md)'s appendix) found that `oneOf`/`anyOf` branch `const`s don't survive Google's function-declaration path: asked to echo the allowed values, all three Gemini generations quote the display titles and never the consts, and renaming the consts shows even 3.5 Flash is reconstructing the wire values (from `default` + option order) rather than reading them from the schema. 3.5 Flash reconstructs well enough to score ✓; the 3.1 models echo the title instead.

### Are the highest-fidelity providers forcing conformance?

I also tested whether Deepinfra's perfect score was a result of a constrained decoder forcing conformance rather than the model following the schema, by telling the model to break the schema and seeing if it would. Deepinfra lets models emit invalid output, so my conclusion is that the results do not reflect forced conformance by the model serving host. I ran the same check on Together, which was the only provider available for `inkling` at the time. 

### Does coaching the prompt inflate the numbers?

The prompts used in the results above hand the model already-conforming values, and one (`lookup-record`) also nudges the expected structure, so there was a chance that the results are measuring prompt-following rather than schema-reading. An 'uncoached' control re-phrasing each task naturally was run across 22 of the 24 models in the table (`claude-opus-4.8` and `inkling` have no uncoached rows).

**115 of 128** comparable cells were identical between 'coached' vs 'uncoached', and **15 of the 22 models** didn't change results (four more changed by only one or two trials in one cell). In these cases, the perfect scores appear to be a result of the model reading the schema, not the prompt coaching the model.

The 13 cells that did change are below. Coaching appears to matter mainly where a weaker model meets a hard keyword (for example: `gemma-4-31b` couldn't handle a top-level `oneOf` without the hint, and `gpt-oss-120b` leaned on the coaching for `$ref`):

| Model | Keyword | Coached | Uncoached | Δ |
| --- | --- | --- | --- | --- |
| `gemma-4-31b` | top-level oneOf | 65% | 0% | \-65 |
| `gpt-oss-120b` | $ref | 65% | 30% | \-35 |
| `qwen3.6-35b` | enums | 90% | 80% | \-10 |
| `glm-5.2` | top-level oneOf | 100% | 90% | \-10 |
| `gpt-oss-120b` | const union | 100% | 95% | \-5 |
| `gemma-4-31b` | enums | 95% | 90% | \-5 |
| `kimi-k2.7-code` | enums | 100% | 95% | \-5 |
| `kimi-k2.7-code` | top-level oneOf | 100% | 95% | \-5 |
| `kimi-k2.7-code` | const union | 95% | 100% | +5 |
| `gemini-3.1-pro` | enums | 0% | 5% | +5 |
| `qwen3.5-397b` | enums | 95% | 100% | +5 |
| `kimi-k2.7-code` | $ref | 85% | 95% | +10 |
| `kimi-k2.7-code` | prefixItems | 80% | 100% | +20 |

Percent of 'honored' out of 'served', coached vs uncoached (20 trials each). Negative Δ indicates that the model leaned on the coaching. The 115 unchanged cells and the 15 models with no changed cells aren't shown. A few cells (mostly `kimi-k2.7-code`) did slightly *better* uncoached, but each positive Δ is only 1–4 trials out of 20 (the 95% CI on a rate measured with 20 trials spans roughly ±15 points) and the sign flips both ways across that model's own cells. This appears consistent with sampling noise rather than a real "coaching hurts" effect.

## The data

Every cell above is backed by a Hugging Face-ready dataset (`runs.jsonl` + `summary.csv` + `transport_diff.csv` + `cycle.csv`, full provenance per record including the back-end that served each call).

[Dataset card (GitHub)](https://github.com/olaservo/research-hub-public/blob/main/mcp/tool-schemas/data/dataset-card.md) · [summary.csv](https://github.com/olaservo/research-hub-public/blob/main/mcp/tool-schemas/data/summary.csv) (first-class `honored_of_served` with a served-based Wilson CI, plus the `accepted_pct` / `honored_given_accepted` gate-vs-skill split and an `underpowered` flag; the legacy `honored_rate` divides by all trials — see the dataset card for the conventions)

Source, the Markdown write-ups, and the servers live on [GitHub](https://github.com/olaservo/research-hub-public/tree/main/mcp/tool-schemas).

A related independent study, the [Tool Schema Rendering Atlas](https://huggingface.co/spaces/evalstate/tool-research) by Shaun Smith (evalstate), measures an earlier stage of the same pipeline: it renders shared tool definitions through each open-weight model's own chat template and reports which schema keywords survive into the model-visible prompt text, with no hosted API in the loop. The two views can differ on the same model without disagreeing. A template may rewrite a construct rather than keep its keyword (Kimi's TypeScript renderer expresses `$ref` and unions as TypeScript types, so the keyword vanishes from the text while the constraint still reaches the model), and a keyword that renders verbatim can still be refused or fumbled once a serving endpoint sits in front of the model (the ⊘ gates and host-conditional cells in the results). The dataset's `cycle.csv` joins the two views per (model × tool) where the corpora overlap.

## Try it

### Interactive playground — coming soon

An interactive playground is in the works: pick one of the six demo tools, fill its form, and validate against its schema, with a panel showing how each model + provider handled that `inputSchema`. It isn't published yet. Follow [Ola on LinkedIn](https://www.linkedin.com/in/olahungerford/) for updates, more research, and errata.

<!-- Playground published-links section — restore when the playground ships.
### Interactive playground

Pick one of the six demo tools, fill its form, and validate against its schema. A model-results panel then shows, from the static results dataset, how that model + provider handled the `inputSchema`.

[Open playground](https://olaservo-sandyland.static.hf.space/mcp/tool-schemas/playground.html)
-->

### Or point your own MCP client at the live demo servers

The six demo tools are already live: two public, keyless MCP servers serve them over Streamable HTTP, so any MCP client can connect — no key, no signup. Your client brings the model, which makes this a live playground where you can watch *your* model handle the 2020-12 schemas:

- **`https://olaservo-json-schema-2020-12-ts.hf.space/mcp`** — the TypeScript server
- **`https://olaservo-json-schema-2020-12-py.hf.space/mcp`** — the Python sibling

There are deliberately two. Neither the TypeScript nor the Python MCP SDK validates 2020-12 tool inputs faithfully out of the box, and each server has to opt into an explicit 2020-12 validator — two independent SDKs reaching that same conclusion over one shared schema set is itself one of the topic's findings (see each server's README for the specifics).

Either URL works in any of these clients:

**[MCP Inspector](https://github.com/modelcontextprotocol/inspector)** (MCP maintainers) — launch it, choose the *Streamable HTTP* transport, and paste a URL:

```sh
npx @modelcontextprotocol/inspector
```

**Claude Code:**

```sh
claude mcp add --transport http schema-demo https://olaservo-json-schema-2020-12-ts.hf.space/mcp
```

**[goose](https://block.github.io/goose/docs/getting-started/using-extensions)** (Block) — as a one-off session extension:

```sh
goose session --with-streamable-http-extension "https://olaservo-json-schema-2020-12-ts.hf.space/mcp"
```

**[fast-agent](https://fast-agent.ai/mcp/)** (Shaun Smith / evalstate — the author of the render atlas above) — in `fastagent.config.yaml`:

```yaml
mcp:
  servers:
    schema-demo:
      transport: "http"
      url: "https://olaservo-json-schema-2020-12-ts.hf.space/mcp"
```

Then ask for something that exercises a hard keyword — "look up the record named Acme Corp" (top-level `oneOf`: exactly one of `id` / `name`), or "plot the point 3 across, 7 up" (the `prefixItems` tuple). Every call is validated server-side against the verbatim schema; an invalid call gets back an error listing each failing keyword, so you can watch the model self-correct (or not).

By [Ola Hungerford](https://www.olahungerford.com/)

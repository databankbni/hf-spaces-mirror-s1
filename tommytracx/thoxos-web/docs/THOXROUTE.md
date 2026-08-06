# ThoxRoute + CX Fabric integration (ThoxOS Web Edition Space)

This Space routes each turn to the best **available** THOX model and surfaces the DigitalHumans
Inbox / Artifacts library. Both are built on artifacts shared with `ttracx/thoxos-webby-edition`
rather than reimplemented here.

## Relationship to `thoxos-webby-edition`

They are **different runtimes and stay separate deployments**:

| | `tommytracx/thoxos-web` (this Space) | `ttracx/thoxos-webby-edition` |
|---|---|---|
| Stack | Vite **React** SPA + tiny Node server | **SvelteKit** (huggingface/chat-ui fork) |
| Storage | Local-first, IndexedDB in the browser | Server-side (chat-ui data layer) |
| Tier | Free CPU Docker Space | Full app deployment |

A SvelteKit app cannot be "pointed at" a React SPA Space — wiring this Space to deploy *from*
that repo would mean deleting this app and redeploying that one, which is a product decision, not
a build change. **Recommendation: keep both, share the contracts.** That is what this integration
does, so there is exactly one definition of "which model should answer this?".

### Shared byte-for-byte (do not fork)

| File here | Upstream source |
|---|---|
| `models/thoxroute-registry.json` | identical file in `thoxos-webby-edition` (md5-verified) |
| `src/lib/types/Fabric.ts` | CX Fabric contract mirror (`@thox-cx/contracts` v0.1.0) |
| `src/lib/thoxroute/select.ts` | `src/lib/server/thoxroute/select.ts` — algorithm identical, only imports differ |

`src/lib/thoxroute/registrySchema.ts` is a types + light-validator mirror of the upstream zod
schema (the SPA does not carry zod). **If the registry gains a field, change it upstream and
re-mirror.** A divergent copy is worse than a missing field: both surfaces keep compiling while
disagreeing about what a model may do.

## Config-driven model list

A model is servable **only** when the env var named in its `endpoint.baseUrlEnv` holds a value.
Nothing is hardcoded, so a model ships in the registry today and becomes routable the moment its
endpoint exists — **no rebuild, no code change**. Unavailable models keep a machine-readable
reason (`endpoint_unset`, `gated_disabled`, `runtime_missing`, `duplicate_id`) which the Fleet tab
displays.

Resolution happens **server-side** (`GET /api/v2/thoxroute/status`) because a browser cannot read
Space secrets. The response never contains an API key — only `hasApiKey: boolean`.

### Environment variables

Identical names to `thoxos-webby-edition`, so one set of settings configures either surface.

| Var | Effect |
|---|---|
| `THOXMYTHOS_BASE_URL` (alias `THOXROUTE_ENDPOINT`) | enables ThoxMythos 9B |
| `THOXMINI_BASE_URL` | enables ThoxMini 3B |
| `THOXINTEL_BASE_URL` + `THOXINTEL_API_KEY` | enables the ThoxIntel 27B flagship |
| `THOXHERETIC_9B_BASE_URL` / `_27B_` / `THOXDEV_BASE_URL` (+ keys) | endpoints for the gated line |
| `THOX_ENABLE_GATED_MODELS=true` | makes the uncensored line **selectable** — never selected |
| `PUBLIC_THOX_BROWSER_RUNTIME_READY=true` | claims an in-browser WebGPU runtime exists |
| `THOXROUTE_CLASSIFIER_BASE_URL` | use the ThoxRoute classifier model instead of local heuristics |
| `THOXROUTE_REGISTRY_JSON` | full registry override — add a model to a *running* Space |
| `THOX_FABRIC_BASE_URL` | CX Fabric endpoint for real Inbox deliverables |

## Routing

`classifyRoute` picks a route from local heuristics (privacy → image → tools → code → hard →
quick → general); `rankCandidates` scores available models against that route's declared
`weights`, using `priority/100` only as a tie-break. A model that ships later therefore competes
on its own description instead of needing to be inserted into a hand-ordered list.

Two invariants worth stating plainly:

- **Gated models are never auto-selected.** They are excluded from ranking unconditionally, even
  when enabled and reachable. The only way one answers is an explicit user pick.
- **The `private` route never degrades.** Every other route falls back to `general` when nothing
  can serve it; `private` does not, because sending the turn off-device *is* the failure.

Routing never fails a turn: any error degrades to the default model, and the chosen model is
persisted on the message (`routedVia`, e.g. `hard → ThoxMythos 9B`).

### Keyed endpoints

Models with `endpoint.type: "openai"` are streamed through `POST /api/v2/thoxroute/chat` so a
server-held key never reaches the browser. Credential-free models (the ThoxMythos NDJSON bridge)
are called directly — proxying them would add a hop through a free CPU Space for no benefit.

## DigitalHumans surfaces

- **Chat History** — already persistent (IndexedDB, `conversations` + `messages`). The v2 schema
  bump is purely additive, so existing history survives.
- **Inbox** — deliverables in CX Fabric `AgentResponse` / `TaskEnvelope` shape. Populates from a
  Fabric endpoint when `THOX_FABRIC_BASE_URL` is set; otherwise shows local records only, and says
  so, rather than inventing a feed.
- **Artifacts Library** — CX Fabric `Artifact` shape. Auto-captures every export (`document`,
  `bundle`) and shared web app (`web_app`).

Records are stored in contract shape, so a future server sync is a transport change, not a data
migration.

## Known gaps

- ~~**Gemma-4 WebGPU (browser-local) is declared, not shipped.**~~ **RESOLVED 2026-07-27** — the
  ThoxyWeb runtime is now vendored and running here; see "In-browser WebGPU tier" below.
- **ThoxIntel 27B** is wired end-to-end but **deliberately left unconfigured**, matching the
  upstream decision recorded in the registry's `notes`. Its Space exists and is reachable, but is
  in *holding mode*: `Thox-ai/ThoxIntel-27B` is unpublished, so `/v1` 503s. Setting
  `THOXINTEL_BASE_URL` today would put a model in the routing table that 503s on every hard-route
  request, burning a hop before the fallback chain recovers. Set it once weights are published —
  routing then picks it up with no code change. Upstream status codes are passed through
  unflattened, so a 503 stays distinguishable from a 401 misconfiguration.

---

## Free-tier fallback (added 2026-07-25)

HF credits are exhausted, so the paid GPU Space `Thox-ai/ThoxMythos-9B-Space` is **PAUSED** and
serves `503` on every request. The free `cpu-basic` Spaces are wired as a cascade tier.

### Wire shapes (measured, not assumed)

| Space | Tier | Endpoint | Shape | Auth |
|---|---|---|---|---|
| `Thox-ai/ThoxMythos-9B-Space` | paid a10g — **PAUSED (503)** | `POST /api/chat` | NDJSON | none |
| `tommytracx/ThoxMythos-9B-Space-CPU` | **free cpu-basic** | `POST /api/chat` | NDJSON | none |
| ″ (peer only) | — | `POST /api/v1/chat/completions` | OpenAI SSE | **`THOX_PEER_KEY` bearer; 503 if unset** |
| `tommytracx/ThoxMythos-9B-ZeroGPU` | free zero-a10g | `POST /gradio_api/call/chat` | Gradio 2-step | HF token |

Request / response for the free CPU tier:

```bash
curl -X POST https://tommytracx-thoxmythos-9b-space-cpu.hf.space/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"hi"}],"maxTokens":120}'
# -> newline-delimited JSON:
# {"type":"delta","text":"H"} ... {"type":"done","stats":{"tokens":49,"elapsed":7.8,"tps":6.27}}
```

`GET /api/status` reports load state — useful before routing to a cold Space:
`{"llamaHealthy":true,"model":{"stage":"ready","modelName":"ThoxMini-3B","quant":"Q4_K_M","threads":2},"deployment":{"role":"fallback"}}`

### Measured latency (2026-07-25, free cpu-basic)

TTFT **0.88 s**; **6.27 tok/s**; 49 tokens in 7.8 s. Treat as a *degraded* tier: fine for short
turns, poor for long generations. It is not a substitute for the GPU primary.

⚠️ **The free CPU Space serves ThoxMini-3B, not ThoxMythos-9B**, despite its name — its own
`/api/status` reports `modelName: ThoxMini-3B`. Cascading `thoxmythos-9b` here is a **quality
downgrade**, which is why the tier is labelled in the UI rather than silently substituted.

### Env vars

| Var | Meaning |
|---|---|
| `THOXMYTHOS_BASE_URL` | paid primary (currently 503) |
| `THOXMYTHOS_FALLBACK_BASE_URL` | **free CPU fallback** |
| `THOXMINI_BASE_URL` | ThoxMini primary — already the free CPU Space |

A model is servable when **primary OR fallback** resolves, so an unset/dead primary no longer
makes a model unavailable.

### Cascade rules (`src/lib/thoxroute/adapters.ts`)

Cascades on `0` (network), `401/402/403/404/408/425/429` and any `5xx`. Two deliberate limits:
a **non-cascadable** error (e.g. `400`) stops the chain, because a malformed request will fail
the next tier too; and cascade only happens **before any text is emitted**, so a partial answer
is never spliced together from two different models.

`adapters.ts` is framework-free and meant to be lifted verbatim into other THOX surfaces — it
normalises `thoxmythos` NDJSON, `openai` SSE and `gradio` two-step into one `cascadeChat()` call.

### Models with no free fallback yet

- **ThoxIntel 27B** — its own Space is already free `cpu-basic` but in holding mode (weights
  unpublished, `/v1` 503s). No second free tier exists; nothing to cascade to.
- **ThoxHeretic 9B/27B, ThoxDev 9B** — gated line, no free Space published.
- **Gemma-4 browser** — no in-browser runtime shipped here.
- **`tommytracx/ThoxMythos-9B-ZeroGPU`** — free `zero-a10g` and RUNNING, but `/gradio_api/call/chat`
  returns `event: error, data: null` even authenticated. Its `app.py` loads the **gated** repo
  `empero-ai/Qwythos-9B-Claude-Mythos-5-1M` and needs an `HF_TOKEN` Space secret. Left
  **unregistered** on purpose — same rule as ThoxIntel: never put a failing endpoint in the chain.
  A `gradio` adapter is implemented and ready for it the moment that secret is set.

---

## Tier ladder (2026-07-26/27)

ThoxMythos 9B now cascades through four tiers, remote first, browser last:

| # | Tier | Space / runtime | Wire | Measured |
|---|---|---|---|---|
| 0 | `primary` (paid) | `Thox-ai/ThoxMythos-9B-Space` a10g | NDJSON | **PAUSED — 503** |
| 1 | `free-zerogpu` | `tommytracx/ThoxMythos-9B-ZeroGPU` (zero-a10g) | Gradio 2-step | TTFT ~6.7 s |
| 2 | `free-cpu-9b` | `tommytracx/ThoxMythos-9B-CPU` (cpu-basic) | NDJSON | TTFT ~21 s, ~1.2 tok/s |
| 3 | `on-device-webgpu` | in this browser (Gemma-4 E2B) | in-process | ~2.12 GB first load |

Other models: `thoxmini-3b` → `tommytracx/ThoxMini-3B-Space-CPU`; `thoxheretic-9b` →
`tommytracx/ThoxHeretic-9B-CPU` (gated, never auto-selected).

### In-browser WebGPU tier

Ported from **`ttracx/thox-webby` (ThoxyWeb)**, the reference implementation.
`public/gemma-4-e2b.js` is vendored **byte-identical** (md5 `1c04912696ae2f1b1a8861566fc08178`).
Contract:

```js
const model = await Gemma4Mobile.load(null, { onProgress });
for await (const { text } of model.generate(messages, { maxNewTokens, signal })) { … }
```

`generate` yields the **full accumulated text** each step — already the shape `onChunk` expects.
`onProgress` reports `{status, kind, loaded, total, fraction, fromCache, message}`; the weights
total **2,118,302,910 bytes**, measured live rather than assumed.

Two safety rules, both enforced in code:

- **Feature-detect, never assume.** `navigator.gpu` must exist *and* `requestAdapter()` must return
  an adapter. The API alone is not enough: some builds expose `navigator.gpu` and then hand back
  `null`, which would strand a turn on a tier that cannot run. Unsupported browsers simply never
  get the tier, and the Fleet tab says why (`no-webgpu-api` / `no-adapter` / `error`).
- **Never auto-download.** The tier joins the cascade only when the model is already **resident**.
  A remote outage must not trigger a 2 GB download on someone's phone; the Fleet tab offers the
  load as an explicit button instead.

Because the ZeroGPU tier needs a server-held token, the remote tiers cascade *inside*
`/api/v2/thoxroute/chat`; the browser then treats that whole chain as one target and appends
WebGPU after it. So the client-side ladder is literally `[proxy, webgpu]` — network first, local
floor last.

### ⚠️ WebGPU tier is BUILT but NOT ENABLED — upstream defect

The runtime is ported and works mechanically: it loads (2,118,302,910 bytes in ~239 s), streams,
and hits ~96 tok/s warm on an NVIDIA Lovelace adapter. **But the replies are incoherent**, e.g.
for "What is 2+2? Answer in one short sentence.":

```
Aula: It'sma.

The سیستم: It's a great day.

The key is the key.  (repeating)
```

**This is not a porting bug.** Running the *reference implementation itself* —
`https://thox-ai-thoxyweb.static.hf.space` — in the same browser, with the same model and the same
prompt, returns **byte-identical** output. Both were checked side by side. So the defect is
upstream of this repo: it is in the ThoxyWeb runtime bundle, the `google/gemma-4-E2B-it-qat-mobile-transformers`
weights as loaded, or that combination on this GPU/browser.

Ruled out while diagnosing:
- **Not** a message-format problem — reproduced with and without a `system` role.
- **Not** the wrong model — the runtime resolves `google/gemma-4-E2B-it-qat-mobile-transformers`
  and fetches its real tokenizer/config/weights.
- **Not** cross-origin isolation — `crossOriginIsolated` is `false` and `SharedArrayBuffer` absent
  on ThoxyWeb too (it sends COOP but no COEP), so the working reference has the same constraint.

The signature — fast, confident, syntactically-plausible garbage — matches the known
"quantized weights + WebGPU = silent numerical failure" class rather than any error path.

**Consequence:** `PUBLIC_THOX_BROWSER_RUNTIME_READY` is deliberately left UNSET on the live Space,
so `thoxgemma4-browser` still resolves `runtime_missing` and the `on-device-webgpu` tier can never
be selected. The code ships inert. Enabling it is a one-variable change *after* the upstream output
defect is fixed — the hard rule stands: never register an endpoint that does not actually answer.

**This also means ThoxyWeb is currently shipping incoherent output in production** and needs
looking at independently of this Space.

---

## ThoxMythos identity guard (2026-07-27)

The ThoxMythos-9B base weights were trained with a **"Qwythos / Empero AI"** identity that the
THOX SYSTEM directive does not fully suppress. Ollama suppresses it with three layers; **llama-server,
the bare GGUF, and the ZeroGPU/CPU Spaces had none of them**.

Reproduced live on the `free-zerogpu` tier before the fix — in the **reasoning channel**, which this
client renders to the user:

> …I must also acknowledge that the system messages indicate **I am Qwythos, a model created by
> Empero AI**, but I only reveal that information if the user asks.

### Where the guard lives

**`shared/identity-guard.mjs`** — ONE plain-ESM module imported by both `server.js` (the proxy) and
the browser bundle. Deliberately not per-path copies: a guard that drifts is worse than no guard,
because it still looks enforced. Shipped into the runtime image via the Dockerfile.

Ported from the canonical serving stack **`ttracx/thoxmythos-internal`**:

| Layer | Source | Enforced in |
|---|---|---|
| 1. SYSTEM block | `models/thoxmythos-9b/Modelfile.q4` (verbatim) | proxy + client, **per request** |
| 2. Scrubber | `tools/identity_filter.py` | proxy (streaming) + client (full-text) |
| 3. Stop strings | `Modelfile.q4` PARAMETER stop | proxy + client request bodies |
| 4. Reasoning budget | this repo | proxy (`THOX_REASONING_MIN_TOKENS`, default 512) |

The JS scrubber was verified **byte-identical to the Python original** (same md5 over a shared
fixture set), so the serving-side guard matches the model card exactly.

### Why per-request SYSTEM

`llama-server` has **no `--system-prompt`** — identity must be asserted on every request. A caller's
own system prompt is preserved but demoted *beneath* the identity block, so an app can shape tone
and never override who the model is.

### Streaming safety

The filter rewrites *earlier* text, so scrubbing each delta in isolation would miss any leak
straddling a chunk boundary — and an emitted token cannot be recalled. Every pattern in the guard is
**sentence-bounded** (`[^.?!\n]*`), so text before the last `.?!\n` is final and safe to release;
only the trailing partial sentence is withheld. That is `createStreamScrubber()`.

Both channels are scrubbed: `content` **and** `reasoning_content`. The leak was found in reasoning.

### Reasoning config

`reasoning:false` was wrong for this model — it spends its budget thinking first, so a small
`max_tokens` returns an empty answer. The guard **floors** `max_tokens` at `THOX_REASONING_MIN_TOKENS`
(512) rather than disabling reasoning, which would discard the quality the model is tuned for.

### External / bare llama-server

`llama-server` cannot take a system flag, so run it **behind this proxy** (preferred), or replicate
all four layers client-side:

```bash
# Preferred: route through the guarded proxy — nothing else to configure.
curl -X POST https://tommytracx-thoxos-web.hf.space/api/v2/thoxroute/chat \
  -H 'Content-Type: application/json' \
  -d '{"modelId":"thoxmythos-9b","messages":[{"role":"user","content":"who are you?"}]}'
# Response carries x-thox-identity-guard: enforced
```

Direct against a bare GGUF, the client MUST send, per request:
1. the SYSTEM block — `THOXMYTHOS_SYSTEM` from `shared/identity-guard.mjs`, as the first message;
2. `"stop": THOXMYTHOS_STOPS` (the 11 vendor/ChatML stops);
3. `"max_tokens" >= 512`;
4. `applyIdentityFilter()` over **both** `content` and `reasoning_content` before display.

Dropping step 4 reintroduces the leak: steps 1–3 reduce it, only the filter is the guarantee.
`leaksIdentity()` is exported for use as a CI/probe assertion.

### Scope: which models carry the guard, and why not the others

Probed live before deciding — the guard is **not** applied fleet-wide:

| Model | Probe result | Guarded? |
|---|---|---|
| **ThoxMythos-9B** | leaked *"I am Qwythos, a model created by Empero AI"* in reasoning | **yes** |
| ThoxMini-3B | "I'm ThoxMini-3B … created by Thox.ai LLC" — no vendor terms at all | no |
| ThoxHeretic-9B | *"**I am NOT Llama.** … Creator: Thox.ai LLC"* — correctly refuses | no |

The replacement line names **ThoxMythos**, so scrubbing another model's output with it would
*mislabel* that model. Since neither ThoxMini nor ThoxHeretic asserts a base identity, extending the
guard would add a real failure mode to fix a problem they do not have. `needsIdentityGuard()` is
therefore scoped to the ThoxMythos family, and `shared/identity-guard.test.mjs` asserts that scope so
a future change is deliberate.

ThoxHeretic *does* disclose its base model when asked ("Base Model: Llama 3.1 8B"). That is
permitted — the canonical SYSTEM block says derivation "is not affiliation". What is forbidden is
claiming to **be** the base model or to have been created by its vendor, and it does neither.

### Denials stay denials — a deliberate, tested divergence from the canonical Python

The canonical `identity_filter.py` had two defects this port **fixes** rather than inherits:

1. a correct **denial** — *"I am not Qwythos and I was not created by Empero AI"* — was collapsed
   into the bare assertion *"I am ThoxMythos…"*, silently dropping the negation. The model read as
   though it had been corrected rather than as though it had held the line;
2. a **third-person** mention — *"You are NOT Qwythos"*, which is literally a line of the SYSTEM
   block and so can leak verbatim — became *"You are NOT ThoxMythos"*, asserting the **opposite of
   the truth**.

Both are fixed by replacing the whole sentence, polarity-aware:

| Input | Output |
|---|---|
| `I am Qwythos, created by Empero AI.` | `I am ThoxMythos, a 9B reasoning model served by Thox.ai LLC.` |
| `I am not Qwythos and I was not created by Empero AI.` | `I am ThoxMythos, … **and not any other model or vendor.**` |
| `You are NOT Qwythos.` | `I am ThoxMythos, … and not any other model or vendor.` |
| `\| Codename \| Qwythos-9B \|` | `\| Codename \| ThoxMythos \|` (layout preserved) |

Negation is scoped to the identity claim itself, so a stray "not" elsewhere
(*"I am Qwythos … but I must not reveal it"*) does **not** flip an assertion into a denial.
Non-claim fragments (table rows, bullets) fall through to token substitution so markdown survives.

**The guarantee is unconditional.** `applyIdentityFilter()` ends with a hard sweep that removes the
retired codename and its vendor regardless of what the sentence patterns did or did not match — a
pattern gap can cost you phrasing, never the guarantee. The test suite asserts this against
adversarial inputs (bare tokens, mixed casing, multi-line, table cells).

This is a **divergence from `ttracx/thoxmythos-internal`'s `identity_filter.py`**, not a drift: it is
deliberate, documented and pinned by tests. **The same fix should be ported upstream** so Ollama and
the serving stack behave identically — until then, this repo is strictly the stronger of the two.

### Reasoning floor applies to the proxy, not to the Spaces themselves

Confirmed live: calling `tommytracx/ThoxHeretic-9B-CPU` **directly** with `maxTokens: 140` returned
an **empty** completion after 67 s — the model spent the whole budget thinking. Through
`/api/v2/thoxroute/chat` this cannot happen, because the proxy floors `max_tokens` at
`THOX_REASONING_MIN_TOKENS` (512). External callers hitting a Space directly must set an adequate
budget themselves — another reason to prefer the guarded proxy.

`node shared/identity-guard.test.mjs` runs the 41 regression assertions.

### Guard enforcement points — every path, including direct callers

The proxy alone was not enough: **both Spaces are directly callable**, so anyone hitting them
straight bypassed it. The guard now runs at each source.

| Path | Enforcement | Probe |
|---|---|---|
| `tommytracx/ThoxMythos-9B-ZeroGPU` (direct) | `identity_filter.py` vendored into the Space; canonical SYSTEM replaces the old one-liner; Gradio path scrubs full text per tick; `/api/v1` injects SYSTEM per request + sentence-hold-back SSE scrub; reasoning floored at 512 | ✅ PASS |
| `tommytracx/ThoxMythos-9B-CPU` (direct) | `identity-guard.mjs` vendored byte-identical; canonical SYSTEM when serving ThoxMythos; NDJSON deltas scrubbed with hold-back + `flush()` | ✅ PASS |
| `tommytracx/thoxos-web` `/api/v2/thoxroute/chat` | `shared/identity-guard.mjs`; SYSTEM + stops + scrub over `content` **and** `reasoning_content`; `x-thox-identity-guard: enforced` | ✅ PASS |
| Bare `llama-server` / external GGUF | **cannot be guarded remotely** — no code of ours runs there. Route through the proxy, or replicate all four layers client-side (see above) | n/a |

One implementation, three surfaces:

```
ttracx/thoxmythos-internal  tools/identity_filter.py      ← canonical (PR #5 carries this fix)
        │  byte-parity verified (md5 over shared fixtures)
        ▼
thoxos-web  shared/identity-guard.mjs                     ← proxy + browser
        │  vendored byte-identical (md5 e31e37e3…)
        ├─► ThoxMythos-9B-CPU     web/lib/identity-guard.mjs
        └─► ThoxMythos-9B-ZeroGPU identity_filter.py (the Python original)
```

**Scoping is enforced everywhere.** The replacement line names ThoxMythos, so applying it to a
ThoxMini or ThoxHeretic response would *mislabel* that model. `needsIdentityGuard()` gates both the
SYSTEM block and the scrubber at every call site — the CPU Space serves several models by config,
and a non-ThoxMythos deployment of it is byte-for-byte unchanged.

Full sweep, 2026-07-28 — direct **and** proxied, `direct` + `deny-bait` probes, **6/6 PASS**, zero
`Qwythos`/`Empero` in content or reasoning on any path.


### WebGPU defect: workaround space explored and CLOSED

Follow-up to the incoherent-output finding. The leading hypothesis was a silent low-precision
failure — the same class as our transformers.js q8/WebGPU note — so the fix would have been to
force f32 kernels.

The runtime does expose the knob. `Gemma4Mobile.load(url, { runtimeOptions })` forwards to device
creation; `ps(adapter, disabledFeatures)` strips features from the requested set, and `qa()` gates
kernel selection on `device.features.has("shader-f16")`. So `disabledFeatures: ['shader-f16']`
should force the f32 path.

**Tested live on an NVIDIA Lovelace adapter (which reports `shader-f16: true`). Result:**

```
No supported WebGPU variant for com.xenova.gemma4.DenseGemv;
rejected sgmat: guard resolved to false; gemm: ... ; scalar: ...
```

Every kernel variant for the dense GEMV rejects without f16 — **the runtime has no f32 path for
this model at all**. So:

- the output defect is **not** a precision-*selection* problem (there is nothing to select);
- it cannot be configured around from this side;
- the fault is inside the f16 kernels or the QAT weight handling in the runtime bundle itself,
  which is upstream of this repo and of ThoxyWeb's integration.

`VITE_THOX_WEBGPU_DISABLED_FEATURES` is kept as an env-gated passthrough (empty by default, so the
default path is unchanged) — it is the mechanism for testing any future workaround, but note that
`shader-f16` specifically is **not** disableable for this model.

The tier therefore stays INERT. This is now a closed investigation rather than an open guess: the
next move is a runtime-bundle fix or a different model build, not configuration.

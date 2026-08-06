// Minimal production server for ThoxOS Web Edition on an HF Docker Space.
// Serves the built Vite SPA (dist/) and implements POST /api/blob-upload so the
// Vercel Blob "Share as web app" feature works off-Vercel too — @vercel/blob's
// put() runs from any Node host given BLOB_READ_WRITE_TOKEN. The token is read
// from the environment (a Space secret); it is never sent to the browser.
import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';
import { put } from '@vercel/blob';
import {
  needsIdentityGuard,
  withIdentitySystem,
  THOXMYTHOS_STOPS,
  createStreamScrubber,
  leaksIdentity,
} from './shared/identity-guard.mjs';

const PORT = process.env.PORT || 7860;
const DIST = join(process.cwd(), 'dist');
const TOKEN = process.env.BLOB_READ_WRITE_TOKEN || '';

// ─── ThoxRoute serving registry ───
// The registry is config, not code: a model becomes routable the moment the env var named in its
// `endpoint.baseUrlEnv` holds a value — no rebuild, no redeploy of the bundle. This mirrors
// thoxos-webby-edition's src/lib/server/thoxroute/registry.ts and uses the SAME env var names, so
// one set of Space secrets configures either surface identically.
const REGISTRY_PATH = join(process.cwd(), 'models', 'thoxroute-registry.json');
const ENV_ALIASES = { THOXMYTHOS_BASE_URL: ['THOXROUTE_ENDPOINT'] };

function readEnv(key) {
  const direct = (process.env[key] || '').trim();
  if (direct) return direct;
  for (const alias of ENV_ALIASES[key] || []) {
    const v = (process.env[alias] || '').trim();
    if (v) return v;
  }
  return '';
}

let registryCache;
async function loadRegistry() {
  if (registryCache) return registryCache;
  // A full JSON override lets an operator add a model to a RUNNING Space with no code change.
  // A parse failure costs you the override, never the chat surface.
  const override = readEnv('THOXROUTE_REGISTRY_JSON');
  if (override) {
    try {
      registryCache = JSON.parse(override);
      return registryCache;
    } catch (err) {
      console.error('[thoxroute] THOXROUTE_REGISTRY_JSON invalid; using bundled registry:', err.message);
    }
  }
  try {
    registryCache = JSON.parse(await readFile(REGISTRY_PATH, 'utf8'));
  } catch {
    registryCache = { version: '0', routes: [], models: [] };
  }
  return registryCache;
}

/**
 * Resolve every described model to an explicit availability verdict.
 * Secrets never cross this boundary: we return whether an API key is present, never its value.
 */
async function thoxrouteStatus(res) {
  const registry = await loadRegistry();
  const gatedEnabled = readEnv('THOX_ENABLE_GATED_MODELS').toLowerCase() === 'true';
  const browserReady = readEnv('PUBLIC_THOX_BROWSER_RUNTIME_READY').toLowerCase() === 'true';
  const seen = new Set();

  const models = (registry.models || []).map((model) => {
    const baseURL = readEnv(model.endpoint.baseUrlEnv);
    const upstreamModelId =
      model.endpoint.type === 'openai' && model.endpoint.modelEnv
        ? readEnv(model.endpoint.modelEnv) || model.id
        : model.id;

    // Resolve every declared fallback tier, in order, keeping only the configured ones.
    const declared = model.endpoint.fallback
      ? (Array.isArray(model.endpoint.fallback) ? model.endpoint.fallback : [model.endpoint.fallback])
      : [];
    const fallbacks = declared
      .map((fb) => {
        const fbBase = readEnv(fb.baseUrlEnv);
        if (!fbBase) return null;
        return {
          type: fb.type || 'thoxmythos',
          baseURL: fbBase,
          tier: fb.tier,
          displayName: fb.displayName,
          upstreamModelId: fb.modelEnv ? readEnv(fb.modelEnv) || model.id : model.id,
          hasApiKey: !!(fb.apiKeyEnv && readEnv(fb.apiKeyEnv)),
        };
      })
      .filter(Boolean);
    const fallback = fallbacks[0];

    const out = (available, reason) => ({
      model,
      available,
      ...(reason ? { reason } : {}),
      baseURL: available ? baseURL : '',
      upstreamModelId,
      hasApiKey: !!(model.endpoint.apiKeyEnv && readEnv(model.endpoint.apiKeyEnv)),
      ...(fallbacks.length ? { fallbacks } : {}),
    });

    if (seen.has(model.id)) return out(false, 'duplicate_id');
    seen.add(model.id);
    if (model.audience === 'gated' && !gatedEnabled) return out(false, 'gated_disabled');
    if (model.endpoint.type === 'browser' && !browserReady) return out(false, 'runtime_missing');
    // A configured fallback makes the model servable even with NO primary — that is the whole
    // point of the free tier: when the paid endpoint is unset or out of credit, the model is
    // still answerable, just slower and (possibly) smaller.
    if (!baseURL) {
      if (!fallback) return out(false, 'endpoint_unset');
      const degraded = out(true);
      degraded.baseURL = '';
      degraded.primaryUnset = true;
      return degraded;
    }
    return out(true);
  });

  const classifierBase = registry.classifier ? readEnv(registry.classifier.baseUrlEnv) : '';
  // Normalise `requires` to an array. The shared registry omits it for routes with no hard
  // capability requirement, and the selection logic calls `route.requires.every(...)`
  // unconditionally — emitting the raw JSON would throw in the client mid-turn.
  const routes = (registry.routes || []).map((r) => ({
    ...r,
    requires: r.requires ?? [],
    localityBias: r.localityBias ?? {},
  }));
  return json(res, 200, {
    version: registry.version,
    routes,
    models,
    gatedEnabled,
    browserReady,
    // `null` means ThoxRoute uses its local heuristics — the shipped default.
    classifier: classifierBase ? { id: registry.classifier.id, configured: true } : null,
    // CX Fabric ingest for the Inbox surface. Empty until an operator points this Space at a
    // Fabric deployment; the Inbox then shows real deliverables instead of local-only records.
    fabricBaseUrl: readEnv('THOX_FABRIC_BASE_URL'),
  });
}

const MIME = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css',
  '.svg': 'image/svg+xml', '.json': 'application/json', '.png': 'image/png',
  '.jpg': 'image/jpeg', '.webp': 'image/webp', '.ico': 'image/x-icon',
  '.woff2': 'font/woff2', '.map': 'application/json',
};

function sanitize(name) {
  return String(name || 'thoxos-artifact')
    .replace(/[^a-zA-Z0-9._-]/g, '-').replace(/-+/g, '-').slice(0, 80) || 'thoxos-artifact';
}

async function handleBlobUpload(req, res) {
  if (!TOKEN) return json(res, 503, { error: 'Blob uploads not configured' });
  let body = '';
  for await (const chunk of req) body += chunk;
  let data;
  try { data = JSON.parse(body); } catch { return json(res, 400, { error: 'Invalid JSON' }); }
  const { filename, contentType, text, base64 } = data || {};
  if (!filename || (text == null && base64 == null)) {
    return json(res, 400, { error: 'filename and text|base64 required' });
  }
  try {
    const payload = base64 != null ? Buffer.from(base64, 'base64') : String(text);
    const { url } = await put(`artifacts/${sanitize(filename)}`, payload, {
      access: 'public', contentType: contentType || 'application/octet-stream',
      addRandomSuffix: true, token: TOKEN,
    });
    return json(res, 200, { url });
  } catch (err) {
    return json(res, 502, { error: `Upload failed: ${err?.message || err}` });
  }
}

function json(res, code, obj) {
  res.writeHead(code, { 'content-type': 'application/json' });
  res.end(JSON.stringify(obj));
}

// ─── Server-side wire adapters (mirror of src/lib/thoxroute/adapters.ts) ───
// These exist because some free tiers need a credential the browser must never hold. ZeroGPU in
// particular attributes its GPU quota to the TOKEN: an anonymous call gets `event: error` after
// the first turn, while the same call with a Bearer token keeps working. So the token lives here
// and the whole cascade runs server-side for any model whose chain contains a keyed tier.

// A reasoning model spends its budget thinking before it answers, so a small max_tokens comes
// back blank. Floor it instead of turning reasoning off.
const REASONING_MIN_TOKENS = Number(process.env.THOX_REASONING_MIN_TOKENS || 512);

const CASCADABLE = new Set([0, 401, 402, 403, 404, 408, 425, 429]);
const isCascadable = (s) => CASCADABLE.has(s) || s >= 500;

class Unavailable extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

/** Emit one OpenAI-style SSE chunk so the browser can use a single parser for every tier. */
function sseChunk(res, content) {
  res.write(`data: ${JSON.stringify({ choices: [{ index: 0, delta: { content } }] })}\n\n`);
}

async function callNdjson(target, messages, opts, emit) {
  let r;
  try {
    r = await fetch(`${target.baseURL.replace(/\/$/, '')}/api/chat`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        messages,
        temperature: opts.temperature ?? 0.7,
        maxTokens: opts.maxTokens ?? 4096,
        ...(opts.stop ? { stop: opts.stop } : {}),
      }),
    });
  } catch (e) { throw new Unavailable(0, e.message); }
  if (!r.ok) throw new Unavailable(r.status, (await r.text().catch(() => '')).slice(0, 200));
  let buf = '', full = '';
  const dec = new TextDecoder();
  for await (const chunk of r.body) {
    // fetch() yields Uint8Array; .toString() on it returns comma-joined byte NUMBERS, not text.
    buf += dec.decode(chunk, { stream: true });
    const lines = buf.split('\n'); buf = lines.pop() ?? '';
    for (const line of lines) {
      const t = line.trim(); if (!t) continue;
      let o; try { o = JSON.parse(t); } catch { continue; }
      if (o.type === 'delta' && o.text) { full += o.text; emit(o.text); }
      else if (o.type === 'error') throw new Unavailable(502, o.message || 'upstream error');
    }
  }
  return full;
}

async function callOpenAIUpstream(target, messages, opts, emit) {
  let r;
  try {
    r = await fetch(`${target.baseURL.replace(/\/$/, '')}/chat/completions`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', ...(target.apiKey ? { authorization: `Bearer ${target.apiKey}` } : {}) },
      body: JSON.stringify({
        model: target.model, messages, stream: true,
        ...(opts.temperature != null ? { temperature: opts.temperature } : {}),
        ...(opts.maxTokens != null ? { max_tokens: opts.maxTokens } : {}),
        ...(opts.stop ? { stop: opts.stop } : {}),
      }),
    });
  } catch (e) { throw new Unavailable(0, e.message); }
  if (!r.ok) throw new Unavailable(r.status, (await r.text().catch(() => '')).slice(0, 200));
  let buf = '', full = '';
  const dec = new TextDecoder();
  for await (const chunk of r.body) {
    // fetch() yields Uint8Array; .toString() on it returns comma-joined byte NUMBERS, not text.
    buf += dec.decode(chunk, { stream: true });
    const lines = buf.split('\n'); buf = lines.pop() ?? '';
    for (const line of lines) {
      const t = line.trim(); if (!t.startsWith('data:')) continue;
      const d = t.slice(5).trim(); if (d === '[DONE]') continue;
      try {
        const delta = JSON.parse(d)?.choices?.[0]?.delta ?? {};
        // Reasoning is user-visible in this client, so it is scrubbed on the same path as
        // content — the leak was FOUND in reasoning_content, not in the answer.
        const c = delta.content ?? delta.reasoning_content;
        if (c) { full += c; emit(c); }
      } catch { /* keep-alive */ }
    }
  }
  return full;
}

/**
 * Gradio 4/5 two-step queue. `gr.ChatInterface(type="messages")` takes TWO positional args —
 * (message, history) — which `/gradio_api/info` does not advertise because history is a hidden
 * State component; sending one arg fails with "needed: 2, got: 1".
 */
async function callGradioUpstream(target, messages, opts, emit) {
  const base = target.baseURL.replace(/\/$/, '');
  const fn = (target.fn || 'chat').replace(/^\//, '');
  const auth = target.apiKey ? { authorization: `Bearer ${target.apiKey}` } : {};
  const lastUser = [...messages].reverse().find((m) => m.role === 'user');
  const history = messages.filter((m) => m !== lastUser).map((m) => ({ role: m.role, content: m.content }));

  let enq;
  try {
    enq = await fetch(`${base}/gradio_api/call/${fn}`, {
      method: 'POST', headers: { 'content-type': 'application/json', ...auth },
      body: JSON.stringify({ data: [lastUser?.content ?? '', history] }),
    });
  } catch (e) { throw new Unavailable(0, e.message); }
  if (!enq.ok) throw new Unavailable(enq.status, (await enq.text().catch(() => '')).slice(0, 200));
  const eventId = (await enq.json().catch(() => ({}))).event_id;
  if (!eventId) throw new Unavailable(502, 'gradio: no event_id');

  let poll;
  try {
    poll = await fetch(`${base}/gradio_api/call/${fn}/${eventId}`, { headers: auth });
  } catch (e) { throw new Unavailable(0, e.message); }
  if (!poll.ok || !poll.body) throw new Unavailable(poll.status || 0, 'gradio: no result stream');

  let buf = '', event = '', full = '';
  const dec = new TextDecoder();
  for await (const chunk of poll.body) {
    buf += dec.decode(chunk, { stream: true });
    const lines = buf.split('\n'); buf = lines.pop() ?? '';
    for (const line of lines) {
      if (line.startsWith('event:')) { event = line.slice(6).trim(); continue; }
      if (!line.startsWith('data:')) continue;
      const raw = line.slice(5).trim();
      // Quota exhaustion and model errors both arrive as `event: error` — cascadable.
      if (event === 'error') throw new Unavailable(503, `gradio error: ${raw || 'null'}`);
      let payload; try { payload = JSON.parse(raw); } catch { continue; }
      const first = Array.isArray(payload) ? payload[0] : payload;
      if (typeof first === 'string' && first !== full) {
        // Gradio streams the FULL accumulated string; emit only the new suffix.
        const delta = first.startsWith(full) ? first.slice(full.length) : first;
        full = first;
        if (delta) emit(delta);
      }
    }
  }
  if (!full) throw new Unavailable(502, 'gradio: empty result');
  return full;
}

function callTier(target, messages, opts, emit) {
  if (target.type === 'gradio') return callGradioUpstream(target, messages, opts, emit);
  if (target.type === 'thoxmythos') return callNdjson(target, messages, opts, emit);
  return callOpenAIUpstream(target, messages, opts, emit);
}

/**
 * Streaming proxy for registry models whose endpoint needs a server-held credential.
 *
 * This exists so a keyed backend (ThoxIntel and any future `openai`-type entry) can be routed to
 * from a browser SPA WITHOUT the key ever reaching the browser. Models that need no credential
 * (the ThoxMythos NDJSON bridge) are still called directly by the client — proxying those would
 * add a hop and put chat traffic through a free CPU Space for no benefit.
 *
 * Upstream failures are passed through with their status intact rather than being flattened: a
 * 503 from a model still in holding mode must look different from a 401 misconfiguration.
 */
async function thoxrouteChat(req, res) {
  let body = '';
  for await (const chunk of req) body += chunk;
  let payload;
  try { payload = JSON.parse(body); } catch { return json(res, 400, { error: 'Invalid JSON' }); }

  const { modelId, messages, temperature, max_tokens } = payload || {};
  if (!modelId || !Array.isArray(messages)) {
    return json(res, 400, { error: 'modelId and messages[] required' });
  }

  const registry = await loadRegistry();
  const model = (registry.models || []).find((m) => m.id === modelId);
  if (!model) return json(res, 404, { error: `Unknown model: ${modelId}` });

  const gatedEnabled = readEnv('THOX_ENABLE_GATED_MODELS').toLowerCase() === 'true';
  if (model.audience === 'gated' && !gatedEnabled) {
    return json(res, 403, { error: 'Model is gated and not enabled on this deployment' });
  }

  // Build the full tier chain: primary first, then each configured fallback in declared order.
  const targets = [];
  const primaryBase = readEnv(model.endpoint.baseUrlEnv);
  if (primaryBase) {
    targets.push({
      type: model.endpoint.type,
      baseURL: primaryBase,
      apiKey: model.endpoint.apiKeyEnv ? readEnv(model.endpoint.apiKeyEnv) : '',
      model: model.endpoint.modelEnv ? readEnv(model.endpoint.modelEnv) || model.id : model.id,
      tier: 'primary',
    });
  }
  const declared = model.endpoint.fallback
    ? (Array.isArray(model.endpoint.fallback) ? model.endpoint.fallback : [model.endpoint.fallback])
    : [];
  for (const fb of declared) {
    const b = readEnv(fb.baseUrlEnv);
    if (!b) continue;
    targets.push({
      type: fb.type || 'thoxmythos',
      baseURL: b,
      apiKey: fb.apiKeyEnv ? readEnv(fb.apiKeyEnv) : '',
      model: fb.modelEnv ? readEnv(fb.modelEnv) || model.id : model.id,
      tier: fb.tier || 'fallback',
    });
  }
  if (targets.length === 0) {
    return json(res, 503, { error: `No endpoint configured for ${modelId}`, reason: 'endpoint_unset' });
  }

  // ─── Identity guard, layer 1 of 3: SYSTEM block ───
  // llama-server has no --system-prompt, so identity must be asserted PER REQUEST. Any caller
  // system prompt is preserved but demoted beneath the identity block.
  const guarded = needsIdentityGuard(modelId);
  const outboundMessages = guarded ? withIdentitySystem(messages) : messages;

  const opts = {
    temperature: typeof temperature === 'number' ? temperature : undefined,
    // Layer 4: reasoning budget. This model spends its budget THINKING first, so a small
    // max_tokens returns an empty answer. Floor it rather than disabling reasoning, which would
    // throw away the quality the model is tuned for.
    maxTokens: guarded
      ? Math.max(typeof max_tokens === 'number' ? max_tokens : 0, REASONING_MIN_TOKENS)
      : (typeof max_tokens === 'number' ? max_tokens : undefined),
    // Layer 3: vendor stop strings, verbatim from Modelfile.q4.
    stop: guarded ? THOXMYTHOS_STOPS : undefined,
  };

  // Cascade. Headers are sent lazily so a tier that fails BEFORE emitting can still be reported
  // as a JSON error; once bytes are on the wire we can only stop, never switch (splicing two
  // models' prose into one answer is worse than failing).
  let started = false;
  const failures = [];
  for (const t of targets) {
    let emitted = false;
    // Layer 2: the universal guarantee — scrub every byte before it leaves this process.
    const scrub = guarded ? createStreamScrubber() : null;
    try {
      await callTier(t, outboundMessages, opts, (raw) => {
        const delta = scrub ? scrub.push(raw) : raw;
        if (!delta) return;
        if (!started) {
          started = true;
          res.writeHead(200, {
            'content-type': 'text/event-stream',
            'cache-control': 'no-cache',
            connection: 'keep-alive',
            'x-thox-tier': t.tier,
            ...(guarded ? { 'x-thox-identity-guard': 'enforced' } : {}),
          });
        }
        emitted = true;
        sseChunk(res, delta);
      });
      // Release the withheld trailing sentence, scrubbed.
      if (scrub) {
        const tail = scrub.flush();
        if (tail) {
          if (!started) {
            started = true;
            res.writeHead(200, {
              'content-type': 'text/event-stream',
              'cache-control': 'no-cache',
              connection: 'keep-alive',
              'x-thox-tier': t.tier,
              'x-thox-identity-guard': 'enforced',
            });
          }
          emitted = true;
          sseChunk(res, tail);
        }
        // Fail loudly in the log if anything slipped through — the guard is meant to be total.
        if (leaksIdentity(scrub.text())) {
          console.error(`[identity-guard] LEAK SURVIVED on tier ${t.tier} for ${modelId}`);
        }
      }
      if (!started) {
        // Tier returned success but produced nothing — treat as unavailable and keep cascading.
        throw new Unavailable(502, 'empty completion');
      }
      const tail = JSON.stringify({
        choices: [{ index: 0, delta: {}, finish_reason: 'stop' }],
        thox_tier: t.tier,
      });
      res.write(`data: ${tail}\n\n`);
      res.write('data: [DONE]\n\n');
      return res.end();
    } catch (err) {
      const status = err instanceof Unavailable ? err.status : -1;
      failures.push({ tier: t.tier, status, message: err?.message || String(err) });
      console.error(`[thoxroute] tier ${t.tier} failed (${status}): ${err?.message}`);
      if (emitted || status === -1 || !isCascadable(status)) {
        if (started) return res.end();
        return json(res, status > 0 ? status : 502, { error: `Tier ${t.tier} failed`, detail: err?.message, failures });
      }
    }
  }
  if (started) return res.end();
  return json(res, 503, { error: `All ${targets.length} tier(s) unavailable`, failures });
}

async function serveStatic(res, urlPath) {
  // Resolve within dist/, fall back to index.html for SPA routes.
  let rel = normalize(decodeURIComponent(urlPath.split('?')[0])).replace(/^(\.\.[/\\])+/, '');
  if (rel === '/' || rel === '') rel = '/index.html';
  let filePath = join(DIST, rel);
  try {
    const s = await stat(filePath);
    if (s.isDirectory()) filePath = join(filePath, 'index.html');
  } catch {
    filePath = join(DIST, 'index.html'); // SPA fallback
  }
  try {
    const buf = await readFile(filePath);
    res.writeHead(200, { 'content-type': MIME[extname(filePath)] || 'application/octet-stream' });
    res.end(buf);
  } catch {
    res.writeHead(404); res.end('Not found');
  }
}

createServer((req, res) => {
  if (req.method === 'POST' && req.url.startsWith('/api/blob-upload')) return handleBlobUpload(req, res);
  if (req.method === 'POST' && req.url.startsWith('/api/v2/thoxroute/chat')) return thoxrouteChat(req, res);
  if (req.url.startsWith('/api/health')) return json(res, 200, { ok: true, blob: !!TOKEN });
  // Same path as thoxos-webby-edition so tooling/ops runbooks work against either surface.
  if (req.url.startsWith('/api/v2/thoxroute/status')) return thoxrouteStatus(res);
  return serveStatic(res, req.url);
}).listen(PORT, '0.0.0.0', () => console.log(`[thoxos-web] serving on :${PORT} (blob=${!!TOKEN})`));

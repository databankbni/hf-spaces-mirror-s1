'use strict';

// ╔══════════════════════════════════════════════════════════════════════╗
// ║  ENIGMA EDGE GATEWAY                                                  ║
// ║  A multi-provider LLM completion proxy with hedged execution,        ║
// ║  adaptive timeouts, circuit breakers, request coalescing,             ║
// ║  streaming fan-out, and full observability.                           ║
// ║                                                                       ║
// ║  Design principles (learned the hard way):                            ║
// ║  1. Every upstream will fail. The question is when and how.           ║
// ║  2. Latency is a probability, not a number. Hedge against the tail.   ║
// ║  3. A key that's cooling down is information, not a problem.          ║
// ║  4. Never let one slow provider block a fast one.                     ║
// ║  5. If you can't observe it, you can't fix it.                        ║
// ║  6. The client disconnecting is the most common "error" — handle it   ║
// ║     gracefully everywhere, not just at the top level.                 ║
// ║  7. Bounded everything. Memory, timers, connections, maps.            ║
// ║     Unbounded growth is a bug that only manifests under load.         ║
// ║  8. Backoff without jitter causes thundering herds. Always jitter.    ║
// ╚══════════════════════════════════════════════════════════════════════╝

const express = require('express');
const cors = require('cors');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const helmet = require('helmet');
const compression = require('compression');
const rateLimit = require('express-rate-limit');
const morgan = require('morgan');

// ─── Bootstrap: fail fast on missing config ──────────────────────────
const PROXY_PASSWORD = process.env.PROXY_PASSWORD;
if (!PROXY_PASSWORD) {
  console.error('FATAL: PROXY_PASSWORD environment variable is missing.');
  process.exit(1);
}
// Optional, separate admin credential. If unset, admin routes fall back
// to PROXY_PASSWORD (previous single-password behavior is unchanged).
// This lets an operator hand out PROXY_PASSWORD for chat-completions
// access only, while keeping settings/metrics/diagnose/reset-metrics
// behind a distinct secret that isn't shared with proxy users.
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || PROXY_PASSWORD;
if (!process.env.ADMIN_PASSWORD) {
  console.warn('[BOOT] ADMIN_PASSWORD not set — admin panel is protected by PROXY_PASSWORD (same credential as chat access). Set ADMIN_PASSWORD to separate the two.');
}
// Pre-allocate the expected header values for constant-time comparison.
// We store them as Buffers so we never re-encode them per request.
const EXPECTED_AUTH_BUF = Buffer.from(`Bearer ${PROXY_PASSWORD}`);
const EXPECTED_ADMIN_AUTH_BUF = Buffer.from(`Bearer ${ADMIN_PASSWORD}`);

// In-flight request counter for graceful shutdown reporting.
// Declared at top level so it's available to all middleware.
let inflightCount = 0;

// ─── Connection pooling (undici) ──────────────────────────────────────
// Without a persistent connection pool, every completion request
// renegotiates TLS (2 RTT) + TCP handshake (1 RTT). With keep-alive
// pooling, subsequent requests to the same provider reuse the existing
// socket — 0 RTT for the connection. Over 1000 requests, this saves
// ~3000 RTTs, which at 100ms each is 5 minutes of wall time.
try {
  const { Agent, setGlobalDispatcher } = require('undici');
  setGlobalDispatcher(new Agent({
    keepAliveTimeout: 10_000,
    keepAliveMaxTimeout: 30_000,
    connections: 256,
    pipelining: 1
  }));
} catch {
  console.warn('[BOOT] undici not installed — falling back to default agent. `npm i undici` for lower latency.');
}

// ══════════════════════════════════════════════════════════════════════
// SECTION 1 — CONFIGURATION
// ══════════════════════════════════════════════════════════════════════

const CONFIG = {
  port: Number(process.env.PORT) || 7860,
  bootTime: Date.now(),

  // Per-attempt timeout. Overridden by adaptive timeout when enough
  // latency data exists (see Section 5).
  completionTimeoutMs: Number(process.env.COMPLETION_TIMEOUT_MS) || 30_000,
  // Total budget across all providers for a single client request.
  // If the waterfall hasn't succeeded by this deadline, give up.
  totalBudgetMs: Number(process.env.COMPLETION_TOTAL_BUDGET_MS) || 55_000,

  // Hedged execution: fire the first N providers in parallel.
  // 1 = pure sequential (safe default). 2-3 = hedged (faster P99
  // but consumes more upstream quota). Tunable at runtime.
  hedgeConcurrency: 2,

  // Max keys to try per provider before moving to the next provider
  // in the waterfall.
  maxKeysPerProvider: 4,

  // Per-provider concurrency cap. Prevents a burst of requests from
  // hammering a single provider's rate limiter.
  providerMaxConcurrency: Number(process.env.PROVIDER_MAX_CONCURRENCY) || 8,

  // Coalesce window: identical non-streaming requests within this
  // window share one upstream call.
  coalesceWindowMs: 3000,

  // Circuit breaker thresholds.
  cb: {
    // After this many consecutive failures, a key goes into open state.
    failureThreshold: 3,
    // Base cooldown for exponential backoff.
    baseCooldownMs: 5_000,
    // Maximum cooldown (cap for exponential backoff).
    maxCooldownMs: 10 * 60_000,
    // After a cooldown expires, the key enters half-open: one probe
    // request is allowed. If it succeeds, the key is fully restored.
    // If it fails, the cooldown restarts.
    halfOpenProbeTimeoutMs: 10_000,
    // Models that return 404 are dead for this long.
    modelDeadCooldownMs: 30 * 60_000
  },

  // Adaptive timeout: multiply the provider's EMA latency by this
  // factor to get the per-attempt timeout. If the provider usually
  // responds in 800ms, a 30s timeout is wasteful — 3.5s gives plenty
  // of headroom while failing fast on true stalls.
  adaptiveTimeoutFactor: 3.5,
  adaptiveTimeoutMinMs: 5_000,
  adaptiveTimeoutMaxMs: 45_000,
  // Need at least this many samples before trusting adaptive timeout.
  adaptiveMinSamples: 5,

  // Bounded cache sizes (prevents unbounded memory growth).
  maxInflightCoalesce: 200,
  maxKeyHealthEntries: 500,
  maxModelHealthEntries: 200,
  maxAttemptLogPerRequest: 30,

  // Content inspection.
  longContextCharThreshold: 24_000,
  nsfwTriggerWords: [
    'fuck', 'bitch', 'cunt', 'dick', 'cock', 'pussy', 'porn',
    'sex', 'blood', 'gore', 'kill', 'rape', 'taboo'
  ],

  // Request limits.
  maxMessages: 500,
  maxBodyBytes: '2mb',
  maxOutputTokens: 4096,

  // Rate limits.
  completionsRateLimit: { windowMs: 15 * 60_000, limit: 150 },
  adminRateLimit: { windowMs: 60_000, limit: 20 },

  // CORS.
  allowedOrigins: ['https://janitorai.com', 'https://janitorai.me', 'http://localhost:3000'],

  // Logging.
  logLevel: process.env.LOG_LEVEL || 'info' // debug | info | warn | error
};

// ─── Settings (mutable at runtime via /api/settings) ──────────────────
const SETTINGS_PATH = path.join(__dirname, 'data', 'settings.json');
const DEFAULT_SETTINGS = {
  autoPilotFallback: true,
  contentInspection: true,
  hedgeConcurrency: CONFIG.hedgeConcurrency,
  longContextCharThreshold: CONFIG.longContextCharThreshold,
  providerEnabled: {}
};

function loadSettings() {
  try {
    const raw = fs.readFileSync(SETTINGS_PATH, 'utf8');
    const parsed = JSON.parse(raw);
    return {
      ...DEFAULT_SETTINGS,
      ...parsed,
      providerEnabled: { ...DEFAULT_SETTINGS.providerEnabled, ...(parsed.providerEnabled || {}) },
      hedgeConcurrency: Math.max(1, Math.min(5, parsed.hedgeConcurrency || CONFIG.hedgeConcurrency))
    };
  } catch {
    return { ...DEFAULT_SETTINGS, providerEnabled: { ...DEFAULT_SETTINGS.providerEnabled } };
  }
}

let settings = loadSettings();

function saveSettings() {
  try {
    fs.mkdirSync(path.dirname(SETTINGS_PATH), { recursive: true });
    fs.writeFileSync(SETTINGS_PATH, JSON.stringify(settings, null, 2));
  } catch (err) {
    log('warn', null, 'settings persist failed', { error: err.message });
  }
}

// Watch for external settings changes (e.g. edited on disk by another
// process). This lets you hot-reload config without restarting.
let settingsMtime = 0;
try { settingsMtime = fs.statSync(SETTINGS_PATH).mtimeMs; } catch {}
setInterval(() => {
  try {
    const stat = fs.statSync(SETTINGS_PATH);
    if (stat.mtimeMs !== settingsMtime) {
      settingsMtime = stat.mtimeMs;
      const old = settings;
      settings = loadSettings();
      log('info', null, 'settings hot-reloaded from disk', {
        autoPilot: settings.autoPilotFallback,
        hedge: settings.hedgeConcurrency
      });
    }
  } catch {}
}, 10_000).unref();

// ══════════════════════════════════════════════════════════════════════
// SECTION 2 — STRUCTURED LOGGING
// JSON log lines with request IDs. Designed for grep/jq/dataldog.
// Never logs API keys, message content, or PII.
// ══════════════════════════════════════════════════════════════════════

const LOG_LEVELS = { debug: 10, info: 20, warn: 30, error: 40 };
const MIN_LOG_LEVEL = LOG_LEVELS[CONFIG.logLevel] || 20;

function log(level, reqId, msg, meta) {
  if ((LOG_LEVELS[level] || 20) < MIN_LOG_LEVEL) return;
  const entry = {
    ts: new Date().toISOString(),
    level,
    msg,
    ...(reqId ? { reqId } : {}),
    ...(meta ? { ...meta } : {})
  };
  const line = JSON.stringify(entry);
  if (level === 'error') console.error(line);
  else if (level === 'warn') console.warn(line);
  else console.log(line);
}

// ══════════════════════════════════════════════════════════════════════
// SECTION 3 — PROVIDER REGISTRY + CAPABILITY MATRIX
// Each provider declares what it supports. This drives payload
// sanitization: if a provider doesn't support `frequency_penalty`,
// we strip it before sending — instead of getting a 400 back and
// burning a waterfall slot on a known-incompatible param.
// ══════════════════════════════════════════════════════════════════════

const providers = {
  huggingface: {
    url: 'https://router.huggingface.co/v1/chat/completions',
    token: process.env.HF_TOKEN,
    // HF router is strict about unknown params.
    stripParams: ['frequency_penalty', 'presence_penalty', 'logit_bias', 'seed', 'top_k'],
    extraHeaders: {},
    supportsStream: true
  },
  openrouter: {
    url: 'https://openrouter.ai/api/v1/chat/completions',
    token: process.env.OR_TOKEN,
    stripParams: [],
    // OpenRouter asks for a referer for attribution.
    extraHeaders: { 'HTTP-Referer': 'https://janitorai.com' },
    supportsStream: true
  },
  groq: {
    url: 'https://api.groq.com/openai/v1/chat/completions',
    token: process.env.GROQ_TOKEN,
    stripParams: ['seed'],
    extraHeaders: {},
    supportsStream: true
  },
  google: {
    url: 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions',
    token: process.env.GOOGLE_TOKEN,
    // Google's OpenAI-compat layer rejects several OpenAI params.
    stripParams: ['frequency_penalty', 'presence_penalty', 'logit_bias', 'seed'],
    extraHeaders: {},
    supportsStream: true
  },
  cerebras: {
    url: 'https://api.cerebras.ai/v1/chat/completions',
    token: process.env.CEREBRAS_TOKEN,
    stripParams: ['seed'],
    extraHeaders: {},
    supportsStream: true
  },
  mistral: {
    url: 'https://api.mistral.ai/v1/chat/completions',
    token: process.env.MISTRAL_TOKEN,
    stripParams: ['logit_bias'],
    extraHeaders: {},
    supportsStream: true
  },
  cohere: {
    url: 'https://api.cohere.ai/compatibility/v1/chat/completions',
    token: process.env.COHERE_TOKEN,
    stripParams: ['logit_bias', 'seed'],
    extraHeaders: {},
    supportsStream: true
  },
  zenmux: {
    url: 'https://zenmux.ai/api/v1/chat/completions',
    token: process.env.ZENMUX_TOKEN,
    stripParams: [],
    extraHeaders: {},
    supportsStream: true
  },
  ainative: {
    url: 'https://api.ainative.studio/v1/chat/completions',
    token: process.env.AINATIVE_TOKEN,
    stripParams: [],
    extraHeaders: {},
    supportsStream: true
  },
  puter: {
    url: 'https://api.puter.com/v1/chat/completions',
    token: process.env.PUTER_TOKEN,
    stripParams: [],
    extraHeaders: {},
    supportsStream: true
  }
};

const PROVIDER_NAMES = Object.keys(providers);

const getKeys = (keyString) => {
  if (!keyString) return [];
  return keyString.split(',')
    .map(k => k.trim().replace(/^['"]|['"]$/g, '').trim())
    .filter(k => k !== '');
};

function providerHasKey(name) {
  return getKeys(providers[name]?.token).length > 0;
}
function providerUsable(name) {
  return settings.providerEnabled[name] !== false && providerHasKey(name);
}

// ─── Payload sanitization per provider ────────────────────────────────
function sanitizeForProvider(payload, provider) {
  const config = providers[provider];
  if (!config?.stripParams?.length) return payload;
  const cleaned = { ...payload };
  for (const key of config.stripParams) delete cleaned[key];
  return cleaned;
}

// ══════════════════════════════════════════════════════════════════════
// SECTION 4 — CIRCUIT BREAKER (per-key) + MODEL HEALTH
//
// Three states: CLOSED → OPEN → HALF_OPEN → CLOSED (or back to OPEN)
//
// CLOSED:   Key is healthy. All requests go through.
// OPEN:     Key has failed enough consecutive times. All requests
//           bypass this key until the cooldown expires.
// HALF_OPEN: Cooldown expired. One probe request is allowed through.
//           If it succeeds → CLOSED (fully restored).
//           If it fails → OPEN (cooldown restarts, doubled).
//
// This is more sophisticated than the old "cool down for N seconds"
// approach because the half-open probe prevents a wave of requests
// from hitting a still-broken key the instant the cooldown expires.
// ══════════════════════════════════════════════════════════════════════

const keyHealth = new Map(); // `${provider}:${keyHash}` -> KeyState
const modelHealth = new Map(); // `${provider}:${model}` -> cooldownUntil

// We store a hash of the key, not the key itself, so that logs and
// debug dumps never leak credentials.
function keyHash(provider, apiKey) {
  return crypto.createHash('sha256').update(`${provider}:${apiKey}`).digest('hex').slice(0, 16);
}
function keyId(provider, apiKey) { return `${provider}:${keyHash(provider, apiKey)}`; }
function modelId(provider, model) { return `${provider}:${model}`; }

// ── Model health (simple cooldown, no half-open needed) ───────────────
function isModelDead(provider, model) {
  const until = modelHealth.get(modelId(provider, model));
  return !!until && until > Date.now();
}
function markModelDead(provider, model) {
  if (modelHealth.size >= CONFIG.maxModelHealthEntries) {
    // Evict the oldest entry (lowest cooldownUntil).
    let oldestKey = null, oldestVal = Infinity;
    for (const [k, v] of modelHealth) {
      if (v < oldestVal) { oldestVal = v; oldestKey = k; }
    }
    if (oldestKey) modelHealth.delete(oldestKey);
  }
  modelHealth.set(modelId(provider, model), Date.now() + CONFIG.cb.modelDeadCooldownMs);
}
function modelDeadRemaining(provider, model) {
  const until = modelHealth.get(modelId(provider, model));
  return until ? Math.max(0, until - Date.now()) : 0;
}

// ── Key circuit breaker ───────────────────────────────────────────────
// State transitions are driven by markKeySuccess / markKeyFailure.
// isKeyAvailable returns { available, state, cooldownMs } so the
// caller can decide whether to use the key (available) or skip it.

function isKeyAvailable(provider, apiKey) {
  const id = keyId(provider, apiKey);
  const state = keyHealth.get(id);
  if (!state) return { available: true, state: 'closed', cooldownMs: 0 };

  const now = Date.now();

  // OPEN: check if cooldown has expired → transition to HALF_OPEN
  if (state.state === 'open') {
    const until = state.retryAfterUntil || state.cooldownUntil;
    if (until > now) {
      return { available: false, state: 'open', cooldownMs: until - now };
    }
    // Cooldown expired → half-open. Allow one probe.
    state.state = 'half-open';
    state.probeStartedAt = now;
    return { available: true, state: 'half-open', cooldownMs: 0 };
  }

  // HALF_OPEN: only one probe at a time. If a probe is already in
  // flight, skip this key.
  if (state.state === 'half-open') {
    if (state.probeStartedAt && now - state.probeStartedAt < CONFIG.cb.halfOpenProbeTimeoutMs) {
      return { available: false, state: 'half-open', cooldownMs: CONFIG.cb.halfOpenProbeTimeoutMs - (now - state.probeStartedAt) };
    }
    // Previous probe timed out — allow another.
    state.probeStartedAt = now;
    return { available: true, state: 'half-open', cooldownMs: 0 };
  }

  return { available: true, state: 'closed', cooldownMs: 0 };
}

function markKeySuccess(provider, apiKey) {
  keyHealth.delete(keyId(provider, apiKey));
}

function markKeyFailure(provider, apiKey, retryAfterMs) {
  const id = keyId(provider, apiKey);

  // Bound the map size — evict the oldest entry if full.
  if (keyHealth.size >= CONFIG.maxKeyHealthEntries && !keyHealth.has(id)) {
    let oldestKey = null, oldestVal = Infinity;
    for (const [k, v] of keyHealth) {
      const until = v.retryAfterUntil || v.cooldownUntil;
      if (until < oldestVal) { oldestVal = until; oldestKey = k; }
    }
    if (oldestKey) keyHealth.delete(oldestKey);
  }

  const prev = keyHealth.get(id) || { state: 'closed', failCount: 0 };
  const failCount = prev.failCount + 1;

  // If in half-open and the probe failed, go back to open with
  // doubled cooldown.
  if (prev.state === 'half-open') {
    const cooldownMs = Math.min(
      CONFIG.cb.baseCooldownMs * 2 ** Math.min(failCount - 1, 8),
      CONFIG.cb.maxCooldownMs
    );
    keyHealth.set(id, {
      state: 'open',
      failCount,
      cooldownUntil: Date.now() + cooldownMs,
      retryAfterUntil: retryAfterMs ? Date.now() + Math.min(retryAfterMs, CONFIG.cb.maxCooldownMs) : undefined
    });
    return;
  }

  // CLOSED → OPEN if failure threshold reached.
  if (failCount >= CONFIG.cb.failureThreshold) {
    // Exponential backoff with jitter to prevent thundering herd:
    // when N keys all cool down at the same time (e.g. a provider
    // goes down), they'd all recover simultaneously and hammer the
    // provider. Jitter spreads recovery over a window.
    const baseCooldown = Math.min(
      CONFIG.cb.baseCooldownMs * 2 ** Math.min(failCount - CONFIG.cb.failureThreshold, 8),
      CONFIG.cb.maxCooldownMs
    );
    // Jitter: ±25% of the base cooldown.
    const jitter = baseCooldown * 0.25 * (Math.random() * 2 - 1);
    const cooldownMs = Math.max(1000, baseCooldown + jitter);

    keyHealth.set(id, {
      state: 'open',
      failCount,
      cooldownUntil: Date.now() + cooldownMs,
      retryAfterUntil: retryAfterMs ? Date.now() + Math.min(retryAfterMs, CONFIG.cb.maxCooldownMs) : undefined
    });
  } else {
    // Below threshold — track the failure but keep the key available.
    keyHealth.set(id, {
      state: 'closed',
      failCount,
      cooldownUntil: 0,
      retryAfterUntil: undefined
    });
  }
}

// ── Key ordering: freshest first, weighted by availability ───────────
function orderKeys(provider, keys) {
  // Shuffle first to distribute load across keys evenly.
  const shuffled = [...keys];
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }

  const available = shuffled.filter(k => isKeyAvailable(provider, k).available);
  if (available.length > 0) return available;

  // All keys are cooling down — return them sorted by soonest recovery.
  // The caller will try the one that recovers first.
  return shuffled.sort((a, b) => {
    const ra = isKeyAvailable(provider, a).cooldownMs;
    const rb = isKeyAvailable(provider, b).cooldownMs;
    return ra - rb;
  });
}

// ══════════════════════════════════════════════════════════════════════
// SECTION 5 — PROVIDER METRICS (EMA-based)
//
// We track an exponential moving average of success rate and latency
// per provider. EMA is better than a simple average because:
// - It weights recent behavior more heavily (a provider that was
//   great yesterday but broken today should be deprioritized).
// - It's O(1) memory and computation (no window to maintain).
// - It degrades gracefully with sparse data.
//
// alpha=0.3 means ~3-4 samples to shift meaningfully. A single fluke
// won't dominate, but a sustained change is reflected quickly.
// ══════════════════════════════════════════════════════════════════════

const EMA_ALPHA = 0.3;

class ProviderMetrics {
  constructor() {
    this.attempts = 0;
    this.successes = 0;
    this.failures = 0;
    this.totalLatencyMs = 0;
    this.successEma = 0.5;     // Start neutral (0.5 = 50% success)
    this.latencyEma = 1000;    // Start at 1s (reasonable default)
    this.sampleCount = 0;
    this.lastError = null;
    // Bytes tracking for observability.
    this.bytesIn = 0;
    this.bytesOut = 0;
  }

  recordSuccess(latencyMs, bytesOut = 0) {
    this.successes++;
    this.totalLatencyMs += latencyMs;
    this.successEma = EMA_ALPHA * 1 + (1 - EMA_ALPHA) * this.successEma;
    this.latencyEma = EMA_ALPHA * latencyMs + (1 - EMA_ALPHA) * this.latencyEma;
    this.sampleCount++;
    this.bytesOut += bytesOut;
  }

  recordFailure(detail) {
    this.failures++;
    this.successEma = EMA_ALPHA * 0 + (1 - EMA_ALPHA) * this.successEma;
    if (detail) this.lastError = { ...detail, at: Date.now() };
  }

  recordBytesIn(n) { this.bytesIn += n; }
  recordBytesOut(n) { this.bytesOut += n; }

  // Score for waterfall ordering: higher = better.
  // Combines success rate (weight: 70%) and latency (weight: 30%).
  // Providers with insufficient data get a neutral score so they
  // aren't penalized for being new.
  score() {
    if (this.sampleCount < 3) return 1.0;
    const latencyPenalty = Math.min(this.latencyEma / 2000, 1);
    return this.successEma * (1 - 0.3 * latencyPenalty);
  }

  // Adaptive timeout: based on EMA latency, with headroom.
  // If a provider usually responds in 800ms, a 30s timeout is
  // wasteful — 2.8s (3.5x) gives plenty of headroom while failing
  // fast on true stalls. This means a stalled provider gets abandoned
  // in seconds instead of 30s, which is critical for the waterfall.
  adaptiveTimeout() {
    if (this.sampleCount < CONFIG.adaptiveMinSamples) return CONFIG.completionTimeoutMs;
    const adaptive = this.latencyEma * CONFIG.adaptiveTimeoutFactor;
    return Math.round(Math.max(
      CONFIG.adaptiveTimeoutMinMs,
      Math.min(adaptive, CONFIG.adaptiveTimeoutMaxMs)
    ));
  }

  snapshot() {
    return {
      attempts: this.attempts,
      successes: this.successes,
      failures: this.failures,
      avgLatencyMs: this.successes > 0 ? Math.round(this.totalLatencyMs / this.successes) : null,
      successEma: Math.round(this.successEma * 1000) / 1000,
      latencyEma: Math.round(this.latencyEma),
      sampleCount: this.sampleCount,
      adaptiveTimeoutMs: this.adaptiveTimeout(),
      score: Math.round(this.score() * 1000) / 1000,
      lastError: this.lastError,
      bytesIn: this.bytesIn,
      bytesOut: this.bytesOut
    };
  }
}

const providerMetrics = new Map(
  PROVIDER_NAMES.map(n => [n, new ProviderMetrics()])
);

function recordAttempt(provider) {
  const m = providerMetrics.get(provider);
  if (m) m.attempts += 1;
}
function recordSuccess(provider, latencyMs, bytesOut) {
  providerMetrics.get(provider)?.recordSuccess(latencyMs, bytesOut);
}
function recordFailure(provider, detail) {
  providerMetrics.get(provider)?.recordFailure(detail);
}
function recordBytesOut(provider, n) {
  providerMetrics.get(provider)?.recordBytesOut(n);
}
function getAdaptiveTimeout(provider) {
  return providerMetrics.get(provider)?.adaptiveTimeout() || CONFIG.completionTimeoutMs;
}

// ══════════════════════════════════════════════════════════════════════
// SECTION 6 — PER-PROVIDER CONCURRENCY SEMAPHORE
//
// Without a cap, a burst of 50 concurrent requests all hitting the
// same provider can trigger its rate limiter harder than the requests
// would individually. A small semaphore smooths fan-out.
//
// The semaphore is a simple counter + FIFO queue. No priority —
// all requests are equal.
// ══════════════════════════════════════════════════════════════════════

class Semaphore {
  constructor(max) {
    this.max = max;
    this.current = 0;
    this.queue = [];
  }

  async acquire() {
    if (this.current < this.max) {
      this.current++;
      return;
    }
    await new Promise(resolve => this.queue.push(resolve));
    this.current++;
  }

  release() {
    this.current = Math.max(0, this.current - 1);
    const next = this.queue.shift();
    if (next) next();
  }

  get pending() { return this.queue.length; }
  get available() { return Math.max(0, this.max - this.current); }
}

const semaphores = new Map(
  PROVIDER_NAMES.map(n => [n, new Semaphore(CONFIG.providerMaxConcurrency)])
);

// ══════════════════════════════════════════════════════════════════════
// SECTION 7 — REQUEST COALESCING + STREAMING FAN-OUT
//
// Coalescing: identical non-streaming requests within a short window
// share one upstream call. Saves quota and latency.
//
// Streaming fan-out: identical streaming requests share one upstream
// SSE connection. Each client gets its own response stream, but the
// chunks are replicated from a single upstream read. This is more
// complex than non-stream coalescing because SSE is a live stream,
// but the savings are even bigger (streaming requests are long-lived).
// ══════════════════════════════════════════════════════════════════════

// ── Non-streaming coalescing ──────────────────────────────────────────
const inflightNonStream = new Map(); // hashKey -> { promise, expires }

// Coalesce key includes the resolved category (not body.model) so that
// requests routed to the same category — even when the client sends
// different friendly model strings that resolve to the same category —
// share an upstream call. This avoids cache misses when the only
// difference is the cosmetic model field.
function coalesceHash(body, targetKey) {
  const relevant = {
    category: targetKey,
    messages: body.messages,
    temperature: body.temperature,
    max_tokens: body.max_tokens,
    top_p: body.top_p
  };
  return crypto.createHash('sha256').update(JSON.stringify(relevant)).digest('hex').slice(0, 16);
}

function getOrCreateInflight(hashKey, factory) {
  const existing = inflightNonStream.get(hashKey);
  if (existing && existing.expires > Date.now()) return existing.promise;

  // Opportunistic cleanup of expired entries.
  if (inflightNonStream.size > CONFIG.maxInflightCoalesce) {
    const now = Date.now();
    for (const [k, v] of inflightNonStream) {
      if (v.expires <= now) inflightNonStream.delete(k);
    }
  }

  const promise = factory();
  inflightNonStream.set(hashKey, { promise, expires: Date.now() + CONFIG.coalesceWindowMs });
  const cleanup = () => {
    const entry = inflightNonStream.get(hashKey);
    if (entry && entry.promise === promise) inflightNonStream.delete(hashKey);
  };
  promise.then(cleanup, cleanup);
  return promise;
}

// ── Streaming fan-out multiplexer ─────────────────────────────────────
// When two identical streaming requests arrive, we open ONE upstream
// connection and replicate chunks to all subscribers. The upstream
// read loop runs once; each subscriber has its own response writer.
//
// If the upstream stream ends, all subscribers get [DONE].
// If a subscriber disconnects, it's removed from the list — the
// upstream read continues for remaining subscribers.
// If the LAST subscriber disconnects, the upstream is aborted.

class StreamMultiplexer {
  constructor() {
    this.subscribers = new Set(); // { res, alive }
    this.upstreamReader = null;
    this.upstreamController = null; // AbortController for upstream
    this.firstChunkSent = false;
    this.closed = false;
    this.bytesRelayed = 0;
  }

  addSubscriber(res) {
    const sub = { res, alive: true };
    this.subscribers.add(sub);

    // When this subscriber's connection closes, remove it.
    res.on('close', () => {
      sub.alive = false;
      this.subscribers.delete(sub);
      // If no more subscribers, abort the upstream.
      if (this.subscribers.size === 0 && this.upstreamController && !this.closed) {
        this.upstreamController.abort();
      }
    });

    return sub;
  }

  async pipeFromUpstream(response, { reqId, provider, model }) {
    this.upstreamController = new AbortController();
    let keepaliveTimer = null;
    try {
      this.upstreamReader = response.body.getReader();
      while (true) {
        const { done, value } = await this.upstreamReader.read();
        if (done) break;

        // ── First-chunk validation (before relaying to subscribers) ──
        // If the upstream returned JSON instead of an SSE stream, send
        // a 502 to every subscriber and abort the upstream read.
        if (!this.firstChunkSent) {
          const text = Buffer.from(value).toString('utf8').trimStart();
          if (text.startsWith('{')) {
            log('warn', reqId, 'stream multiplexer first chunk is JSON, not SSE — returning 502', { provider, model, snippet: summarizeErrorBody(text) });
            for (const sub of this.subscribers) {
              if (!sub.alive) continue;
              try {
                if (!sub.res.headersSent) {
                  sub.res.status(502).json({ error: 'Upstream returned a non-SSE response (JSON body).', provider });
                } else if (!sub.res.writableEnded) {
                  sub.res.write(`data: ${JSON.stringify({ error: 'upstream returned JSON instead of SSE', provider })}\n\n`);
                  sub.res.end();
                }
              } catch { sub.alive = false; }
            }
            try { this.upstreamController.abort(); } catch {}
            try { await this.upstreamReader.cancel(); } catch {}
            return;
          }
          // Valid SSE — set SSE headers on subscribers that don't have
          // them yet, flush, and start the keepalive heartbeat.
          for (const sub of this.subscribers) {
            if (!sub.alive) continue;
            try {
              if (!sub.res.headersSent) {
                sub.res.setHeader('Cache-Control', 'no-cache');
                sub.res.setHeader('Connection', 'keep-alive');
                sub.res.setHeader('Content-Type', 'text/event-stream');
                sub.res.flushHeaders();
              }
            } catch { sub.alive = false; }
          }
          this.firstChunkSent = true;
          keepaliveTimer = setInterval(() => {
            for (const sub of this.subscribers) {
              if (!sub.alive) continue;
              try {
                if (!sub.res.writableEnded) sub.res.write(': keepalive\n\n');
              } catch { sub.alive = false; }
            }
          }, 15_000);
          log('debug', reqId, 'stream multiplexer first chunk', { provider, model, subs: this.subscribers.size });
        }

        // Relay to all alive subscribers with backpressure handling.
        const dead = [];
        for (const sub of this.subscribers) {
          if (!sub.alive) { dead.push(sub); continue; }
          try {
            if (!sub.res.writableEnded) {
              const ok = sub.res.write(value);
              if (!ok) {
                await new Promise(resolve => sub.res.once('drain', resolve));
              }
              this.bytesRelayed += value.length;
            }
          } catch {
            sub.alive = false;
            dead.push(sub);
          }
        }
        for (const d of dead) this.subscribers.delete(d);
      }

      // Send [DONE] to all remaining subscribers.
      for (const sub of this.subscribers) {
        if (sub.alive && !sub.res.writableEnded) {
          sub.res.write('data: [DONE]\n\n');
        }
      }
    } catch (err) {
      if (this.subscribers.size > 0) {
        log('warn', reqId, 'stream multiplexer upstream error', { provider, error: err.message });
        for (const sub of this.subscribers) {
          if (sub.alive && !sub.res.writableEnded) {
            try {
              sub.res.write(`data: ${JSON.stringify({ error: 'stream_interrupted', provider })}\n\n`);
            } catch {}
          }
        }
      }
    } finally {
      if (keepaliveTimer) clearInterval(keepaliveTimer);
      this.closed = true;
      for (const sub of this.subscribers) {
        if (!sub.res.writableEnded) {
          try { sub.res.end(); } catch {}
        }
      }
      this.subscribers.clear();
    }
  }
}

const inflightStreams = new Map(); // hashKey -> { multiplexer, expires }

function getOrCreateStream(hashKey) {
  const existing = inflightStreams.get(hashKey);
  if (existing && !existing.multiplexer.closed) return existing.multiplexer;

  // Cleanup
  if (inflightStreams.size > 50) {
    for (const [k, v] of inflightStreams) {
      if (v.multiplexer.closed) inflightStreams.delete(k);
    }
  }

  const multiplexer = new StreamMultiplexer();
  inflightStreams.set(hashKey, { multiplexer, expires: Date.now() + 120_000 });
  const cleanup = () => {
    if (multiplexer.closed) {
      const entry = inflightStreams.get(hashKey);
      if (entry && entry.multiplexer === multiplexer) inflightStreams.delete(hashKey);
    }
  };
  // Check periodically if the multiplexer is done.
  const checker = setInterval(() => {
    if (multiplexer.closed) { clearInterval(checker); cleanup(); }
  }, 5000).unref();

  return multiplexer;
}

// ══════════════════════════════════════════════════════════════════════
// SECTION 8 — ROUTING MATRIX + MODEL CATALOG
// ══════════════════════════════════════════════════════════════════════

const routingMatrix = {
  '[Speed] Llama 3.3 70B': [
    { provider: 'groq', model: 'llama-3.3-70b-versatile' },
    { provider: 'cerebras', model: 'llama-3.3-70b' },
    { provider: 'zenmux', model: 'meta-llama/Llama-3.3-70B-Instruct' },
    { provider: 'huggingface', model: 'meta-llama/Llama-3.3-70B-Instruct:fastest' },
    { provider: 'openrouter', model: 'meta-llama/llama-3.3-70b-instruct:free' }
  ],
  '[Context] Deep Logic': [
    { provider: 'google', model: 'gemini-2.5-flash' },
    { provider: 'google', model: 'gemini-3-flash-preview' },
    { provider: 'huggingface', model: 'deepseek-ai/DeepSeek-V4-Flash:fastest' },
    { provider: 'openrouter', model: 'google/gemini-2.5-flash:free' },
    { provider: 'ainative', model: 'deepseek-v4-flash' }
  ],
  '[Roleplay] Maximum Intelligence': [
    { provider: 'puter', model: 'claude-3-haiku' },
    { provider: 'huggingface', model: 'NousResearch/Hermes-3-Llama-3.1-70B:fastest' },
    { provider: 'openrouter', model: 'nousresearch/hermes-3-llama-3.1-405b:free' },
    { provider: 'cohere', model: 'command-r-plus' },
    { provider: 'mistral', model: 'mistral-large-latest' }
  ],
  '[NSFW] Uncensored Fast': [
    { provider: 'huggingface', model: 'cognitivecomputations/dolphin-2.9-llama3-8b:fastest' },
    { provider: 'openrouter', model: 'cognitivecomputations/dolphin-llama-3-8b:free' }
  ],
  '[Enigma] Auto-Pilot Gateway': [
    { provider: 'groq', model: 'llama-3.3-70b-versatile' }
  ]
};

const modelCatalog = [
  { id: 'auto', label: 'Auto Pilot', tagline: 'Just pick the best one for me', description: "Not sure what to pick? Send your message and we'll choose based on it.", recommended: true, family: ['auto', 'autopilot', 'pilot', 'enigma', 'surprise', 'default', 'any'], variant: [], categoryKey: '[Enigma] Auto-Pilot Gateway' },
  { id: 'llama-fast', label: 'Llama 3.3', tagline: 'Fast & free', description: 'Free and quick — great for casual back-and-forth chat.', family: ['llama'], variant: ['meta', 'fast', 'quick', 'speed', '70b', 'instruct', 'versatile'], categoryKey: '[Speed] Llama 3.3 70B' },
  { id: 'gemini-flash', label: 'Gemini Flash', tagline: 'Smart, handles long chats', description: "Google's fast model — holds up well in longer conversations.", family: ['gemini', 'google'], variant: ['flash'], categoryKey: '[Context] Deep Logic', preferred: { provider: 'google', model: 'gemini-2.5-flash' } },
  { id: 'gemini-pro', label: 'Gemini Pro', tagline: 'Smartest, best for long chats', description: "Google's most capable model — best for long, detailed conversations.", family: ['gemini', 'google'], variant: ['pro', 'smart', 'smartest'], categoryKey: '[Context] Deep Logic', preferred: { provider: 'google', model: 'gemini-3-flash-preview' } },
  { id: 'deepseek-fast', label: 'DeepSeek Fast', tagline: 'Quick replies (V4 Flash)', description: 'A quick DeepSeek model — short wait, snappy replies.', family: ['deepseek'], variant: ['fast', 'quick', 'speed', 'v4', 'flash', 'fastest'], categoryKey: '[Context] Deep Logic', preferred: { provider: 'huggingface', model: 'deepseek-ai/DeepSeek-V4-Flash:fastest' } },
  { id: 'deepseek-smart', label: 'DeepSeek Smart', tagline: 'Best for long, complex chats', description: 'Built for long, detailed roleplay and involved answers.', family: ['deepseek'], variant: ['smart', 'smartest', 'context', 'long', 'chat'], categoryKey: '[Context] Deep Logic', preferred: { provider: 'ainative', model: 'deepseek-v4-flash' } },
  { id: 'claude-roleplay', label: 'Claude', tagline: 'Great for roleplay', description: 'Warm and expressive — stays in character naturally.', family: ['claude', 'anthropic'], variant: ['roleplay', 'haiku'], categoryKey: '[Roleplay] Maximum Intelligence', preferred: { provider: 'puter', model: 'claude-3-haiku' } },
  { id: 'hermes-roleplay', label: 'Hermes 3', tagline: 'Great for roleplay', description: 'Tuned specifically for immersive, creative roleplay.', family: ['hermes', 'nous'], variant: ['roleplay'], categoryKey: '[Roleplay] Maximum Intelligence', preferred: { provider: 'huggingface', model: 'NousResearch/Hermes-3-Llama-3.1-70B:fastest' } },
  { id: 'mistral-roleplay', label: 'Mistral Large', tagline: 'Great for roleplay', description: 'A strong, dependable all-rounder for roleplay and storytelling.', family: ['mistral'], variant: ['roleplay', 'large', 'latest'], categoryKey: '[Roleplay] Maximum Intelligence', preferred: { provider: 'mistral', model: 'mistral-large-latest' } },
  { id: 'command-roleplay', label: 'Command R+', tagline: 'Great for roleplay', description: 'Careful with instructions and character detail.', family: ['command', 'cohere'], variant: ['roleplay', 'plus'], categoryKey: '[Roleplay] Maximum Intelligence', preferred: { provider: 'cohere', model: 'command-r-plus' } },
  { id: 'dolphin-nsfw', label: 'Dolphin', tagline: 'Uncensored / NSFW', description: 'No filters, no refusals.', family: ['dolphin', 'nsfw', 'uncensored', 'taboo'], variant: ['fast'], categoryKey: '[NSFW] Uncensored Fast' }
];

const NSFW_REGEX = new RegExp('\\b(' + CONFIG.nsfwTriggerWords.join('|') + ')\\b', 'i');
const GENERIC_ARCH_WORDS = ['llama', 'instruct', 'chat', 'model', 'ai'];

// ─── Model resolution ─────────────────────────────────────────────────
function normalize(str) {
  return String(str || '').toLowerCase().replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim();
}
function tokenize(str) {
  return normalize(str).split(' ').filter(t => t.length >= 2);
}
function tokenHits(tokens, keyword) {
  return tokens.some(t => t === keyword || t.includes(keyword) || keyword.includes(t));
}

function resolveFriendlyModel(rawInput) {
  const tokens = tokenize(rawInput);
  if (tokens.length === 0) return null;
  const scored = [];
  for (const entry of modelCatalog) {
    if (!entry.family.some(f => tokenHits(tokens, f))) continue;
    const variantScore = entry.variant.reduce((acc, v) => acc + (tokenHits(tokens, v) ? 1 : 0), 0);
    const genericOnly = entry.family.every(f => GENERIC_ARCH_WORDS.includes(f));
    scored.push({ entry, variantScore, genericOnly });
  }
  if (scored.length === 0) return null;
  const hasSpecific = scored.some(s => !s.genericOnly);
  const filtered = hasSpecific ? scored.filter(s => !s.genericOnly) : scored;
  const maxVariant = Math.max(...filtered.map(s => s.variantScore));
  const top = filtered.filter(s => s.variantScore === maxVariant).map(s => s.entry);
  if (top.length === 1) return { entry: top[0] };
  return { ambiguous: top };
}

// ─── Waterfall construction ───────────────────────────────────────────
function buildWaterfall(categoryKey, preferred) {
  let base = (routingMatrix[categoryKey] || [])
    .filter(e => providerUsable(e.provider))
    .filter(e => !isModelDead(e.provider, e.model));

  // Health-weighted re-ranking: healthy, fast providers float to the
  // top over time. Preserves relative order for ties and providers
  // with insufficient data (neutral score = 1.0).
  base.sort((a, b) => providerMetrics.get(b.provider).score() - providerMetrics.get(a.provider).score());

  if (!preferred || !providerUsable(preferred.provider) || isModelDead(preferred.provider, preferred.model)) {
    return base;
  }
  const rest = base.filter(e => !(e.provider === preferred.provider && e.model === preferred.model));
  return [{ ...preferred }, ...rest];
}

// ══════════════════════════════════════════════════════════════════════
// SECTION 9 — UTILITIES
// ══════════════════════════════════════════════════════════════════════

function maskKey(k) {
  if (k.length <= 10) return '••••';
  return `${k.slice(0, 6)}…${k.slice(-4)}`;
}

function summarizeErrorBody(text) {
  if (!text) return '';
  const scrubbed = String(text)
    .replace(/(sk|hf|gsk|pk|or|gco)[-_][A-Za-z0-9_-]{8,}/g, '[redacted]')
    .slice(0, 300);
  return scrubbed;
}

function recentPlainText(messages, maxMessages = 4, maxChars = 4000) {
  let out = '';
  for (let i = messages.length - 1; i >= 0 && messages.length - i <= maxMessages; i--) {
    const c = messages[i]?.content;
    if (typeof c === 'string') out += c + ' ';
    if (out.length >= maxChars) break;
  }
  return out.slice(0, maxChars);
}

function estimateTotalChars(messages) {
  let total = 0;
  for (const m of messages) {
    if (typeof m.content === 'string') total += m.content.length;
  }
  return total;
}

// Rough token estimation (~4 chars/token for English). Used to
// pre-flight reject oversized requests before wasting an upstream
// call, and to choose providers with sufficient context windows.
function estimateTokens(messages) {
  return Math.ceil(estimateTotalChars(messages) / 4);
}

// Parse Retry-After header (seconds or HTTP date).
function parseRetryAfter(headerValue) {
  if (!headerValue) return null;
  const seconds = parseFloat(headerValue);
  if (!isNaN(seconds)) return seconds * 1000;
  const date = Date.parse(headerValue);
  if (!isNaN(date)) return Math.max(0, date - Date.now());
  return null;
}

// Parse X-RateLimit-Reset / X-RateLimit-Remaining headers.
function parseRateLimitHeaders(headers) {
  const remaining = headers.get('x-ratelimit-remaining');
  const reset = headers.get('x-ratelimit-reset');
  const result = {};
  if (remaining !== null) result.remaining = parseInt(remaining, 10);
  if (reset !== null) {
    const resetSec = parseFloat(reset);
    if (!isNaN(resetSec)) result.resetMs = resetSec * 1000;
  }
  return Object.keys(result).length > 0 ? result : null;
}

// Validate that the upstream response has the expected OpenAI shape.
// A provider that returns 200 but garbage (e.g. an HTML error page
// with a 200 status) would otherwise be forwarded to the client as
// a "success."
function validateUpstreamResponse(json) {
  if (!json || typeof json !== 'object') return false;
  if (!Array.isArray(json.choices) || json.choices.length === 0) return false;
  const choice = json.choices[0];
  if (!choice || typeof choice !== 'object') return false;
  // Non-streaming: must have message.content or finish_reason.
  // Streaming: handled separately (chunk validation in pipeStream).
  if (choice.message && typeof choice.message.content !== 'undefined') return true;
  if (choice.finish_reason) return true;
  return false;
}

// ══════════════════════════════════════════════════════════════════════
// SECTION 10 — RESPONSE HELPERS
// ══════════════════════════════════════════════════════════════════════

function sendAssistantMessage(req, res, text) {
  const id = `chatcmpl-${crypto.randomBytes(12).toString('hex')}`;
  const created = Math.floor(Date.now() / 1000);
  res.setHeader('X-Resolved-Model', 'clarification');
  res.setHeader('X-Resolved-Provider', 'proxy-assistant');
  if (req.body && req.body.stream) {
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.setHeader('Content-Type', 'text/event-stream');
    res.flushHeaders();
    const chunk = { id, object: 'chat.completion.chunk', created, model: 'proxy-assistant', choices: [{ index: 0, delta: { role: 'assistant', content: text }, finish_reason: null }] };
    const doneChunk = { id, object: 'chat.completion.chunk', created, model: 'proxy-assistant', choices: [{ index: 0, delta: {}, finish_reason: 'stop' }] };
    res.write(`data: ${JSON.stringify(chunk)}\n\n`);
    res.write(`data: ${JSON.stringify(doneChunk)}\n\n`);
    res.write('data: [DONE]\n\n');
    return res.end();
  }
  return res.json({
    id, object: 'chat.completion', created, model: 'proxy-assistant',
    choices: [{ index: 0, message: { role: 'assistant', content: text }, finish_reason: 'stop' }],
    usage: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 }
  });
}

function sendErrorMessage(req, res, status, text) {
  if (req.body && req.body.stream) return sendAssistantMessage(req, res, text);
  return res.status(status).json({ error: text });
}

function clarificationText(rawInput, options) {
  const list = options.map((o, i) => `${i + 1}. **${o.label} — ${o.tagline}** — type \`${o.id}\``).join('\n');
  return `I found a few models matching "${rawInput}" — which one do you want?\n\n${list}\n\nJust change the Model field to one of the names above (like \`${options[0].id}\`) and send your message again. Not sure? Type \`auto\` and I'll pick the best one for you.`;
}

function noMatchText(rawInput) {
  const list = modelCatalog.map(o => `- \`${o.id}\` — ${o.label} (${o.tagline})`).join('\n');
  return `"${rawInput}" doesn't match a model, and Auto Pilot fallback is currently switched off by the gateway admin. Type one of these into the Model field instead:\n\n${list}`;
}

// ══════════════════════════════════════════════════════════════════════
// SECTION 11 — EXPRESS APP SETUP
// ══════════════════════════════════════════════════════════════════════

const app = express();
app.set('trust proxy', 1);
app.disable('x-powered-by');

app.use(helmet({
  contentSecurityPolicy: {
    directives: {
      defaultSrc: ["'self'"],
      styleSrc: ["'self'", "'unsafe-inline'", 'https://fonts.googleapis.com'],
      fontSrc: ["'self'", 'https://fonts.gstatic.com'],
      scriptSrc: ["'self'"],
      imgSrc: ["'self'", 'data:'],
      connectSrc: ["'self'"],
      frameAncestors: ["'self'", 'https://huggingface.co', 'https://*.hf.space']
    }
  },
  frameguard: false,
  crossOriginEmbedderPolicy: false
}));

// Don't compress SSE streams — they're already incremental and
// compression adds buffering latency that breaks the streaming UX.
app.use(compression({
  filter: (req, res) => {
    if (req.path.startsWith('/v1/chat/completions') || req.path.startsWith('/chat/completions')) return false;
    return compression.filter(req, res);
  }
}));

app.use(morgan('combined', { skip: (req) => req.path === '/health' }));

const restrictedCors = cors({
  origin: (origin, callback) => {
    if (!origin || CONFIG.allowedOrigins.includes(origin)) return callback(null, true);
    const err = new Error('CORS policy violation');
    err.statusCode = 403;
    callback(err);
  }
});

app.use(express.json({ limit: CONFIG.maxBodyBytes }));

// Track in-flight requests for graceful shutdown reporting.
app.use((req, res, next) => {
  inflightCount++;
  res.on('close', () => inflightCount--);
  next();
});

app.use(express.static(path.join(__dirname, 'public'), {
  maxAge: '1h',
  setHeaders: (res, filePath) => {
    if (filePath.endsWith('.html')) res.setHeader('Cache-Control', 'no-cache');
  }
}));

// ─── Auth: constant-time comparison ───────────────────────────────────
// isAuthorized       — gates chat completions (PROXY_PASSWORD).
// isAuthorizedAdmin  — gates settings/metrics/diagnose/reset-metrics
//                      (ADMIN_PASSWORD, or PROXY_PASSWORD if unset).
// These are deliberately separate credentials so a proxy user's
// password doesn't also grant them admin control.
function isAuthorized(req) {
  const header = req.headers.authorization || '';
  const headerBuf = Buffer.from(header);
  if (headerBuf.length !== EXPECTED_AUTH_BUF.length) {
    // Burn time to keep timing roughly constant even on length mismatch.
    crypto.timingSafeEqual(EXPECTED_AUTH_BUF, EXPECTED_AUTH_BUF);
    return false;
  }
  return crypto.timingSafeEqual(headerBuf, EXPECTED_AUTH_BUF);
}

function isAuthorizedAdmin(req) {
  const header = req.headers.authorization || '';
  const headerBuf = Buffer.from(header);
  if (headerBuf.length !== EXPECTED_ADMIN_AUTH_BUF.length) {
    crypto.timingSafeEqual(EXPECTED_ADMIN_AUTH_BUF, EXPECTED_ADMIN_AUTH_BUF);
    return false;
  }
  return crypto.timingSafeEqual(headerBuf, EXPECTED_ADMIN_AUTH_BUF);
}

// ══════════════════════════════════════════════════════════════════════
// SECTION 12 — API ROUTES (status, metrics, diagnose, settings)
// ══════════════════════════════════════════════════════════════════════

// ── Health check (no auth, minimal) ───────────────────────────────────
app.get('/health', (req, res) => {
  res.json({
    status: 'ok',
    uptimeSeconds: Math.floor((Date.now() - CONFIG.bootTime) / 1000)
  });
});

// ── Status (no auth, safe summary) ────────────────────────────────────
app.get('/api/status', (req, res) => {
  const now = Date.now();
  res.json({
    status: 'ok',
    uptimeSeconds: Math.floor((Date.now() - CONFIG.bootTime) / 1000),
    autoPilotFallback: settings.autoPilotFallback,
    contentInspection: settings.contentInspection,
    hedgeConcurrency: settings.hedgeConcurrency,
    providers: PROVIDER_NAMES.map(name => {
      const keys = getKeys(providers[name]?.token);
      const m = providerMetrics.get(name);
      const coolingDown = keys.filter(k => !isKeyAvailable(name, k).available).length;
      return {
        name,
        configured: keys.length > 0,
        enabled: settings.providerEnabled[name] !== false,
        degraded: keys.length > 0 && coolingDown === keys.length,
        successRate: m.sampleCount > 0 ? Math.round(m.successEma * 100) / 100 : null,
        avgLatencyMs: m.sampleCount > 0 ? Math.round(m.latencyEma) : null,
        adaptiveTimeoutMs: m.adaptiveTimeout(),
        concurrencyInUse: semaphores.get(name).current,
        concurrencyPending: semaphores.get(name).pending
      };
    }),
    deadModels: [...modelHealth.entries()]
      .filter(([, until]) => until > now)
      .map(([id, until]) => {
        const sep = id.indexOf(':');
        return { provider: id.slice(0, sep), model: id.slice(sep + 1), cooldownRemainingMs: until - now };
      })
  });
});

// ── Metrics (auth required, detailed) ─────────────────────────────────
const adminLimiter = rateLimit(CONFIG.adminRateLimit);

app.get('/api/metrics', adminLimiter, (req, res) => {
  if (!isAuthorizedAdmin(req)) return res.status(401).json({ error: 'Invalid Admin Password supplied.' });
  res.json(PROVIDER_NAMES.map(name => {
    const m = providerMetrics.get(name);
    const keys = getKeys(providers[name]?.token);
    return {
      name,
      ...m.snapshot(),
      keys: keys.map(k => {
        const avail = isKeyAvailable(name, k);
        return {
          key: maskKey(k),
          ...avail,
          failCount: keyHealth.get(keyId(name, k))?.failCount || 0
        };
      })
    };
  }));
});

// ── Prometheus-format metrics endpoint ────────────────────────────────
app.get('/metrics', adminLimiter, (req, res) => {
  if (!isAuthorizedAdmin(req)) return res.status(401).json({ error: 'Invalid Admin Password supplied.' });
  res.setHeader('Content-Type', 'text/plain; version=0.0.4');
  const lines = [];
  lines.push('# HELP enigma_provider_attempts_total Total attempts per provider');
  lines.push('# TYPE enigma_provider_attempts_total counter');
  lines.push('# HELP enigma_provider_successes_total Total successes per provider');
  lines.push('# TYPE enigma_provider_successes_total counter');
  lines.push('# HELP enigma_provider_failures_total Total failures per provider');
  lines.push('# TYPE enigma_provider_failures_total counter');
  lines.push('# HELP enigma_provider_success_ema Exponential moving average of success rate');
  lines.push('# TYPE enigma_provider_success_ema gauge');
  lines.push('# HELP enigma_provider_latency_ema_ms EMA of success latency in ms');
  lines.push('# TYPE enigma_provider_latency_ema_ms gauge');
  lines.push('# HELP enigma_provider_concurrency_inuse Current in-use concurrency slots');
  lines.push('# TYPE enigma_provider_concurrency_inuse gauge');
  lines.push('# HELP enigma_uptime_seconds Process uptime in seconds');
  lines.push('# TYPE enigma_uptime_seconds gauge');

  for (const name of PROVIDER_NAMES) {
    const m = providerMetrics.get(name);
    const sem = semaphores.get(name);
    const labels = `provider="${name}"`;
    lines.push(`enigma_provider_attempts_total{${labels}} ${m.attempts}`);
    lines.push(`enigma_provider_successes_total{${labels}} ${m.successes}`);
    lines.push(`enigma_provider_failures_total{${labels}} ${m.failures}`);
    lines.push(`enigma_provider_success_ema{${labels}} ${m.successEma}`);
    lines.push(`enigma_provider_latency_ema_ms{${labels}} ${Math.round(m.latencyEma)}`);
    lines.push(`enigma_provider_concurrency_inuse{${labels}} ${sem.current}`);
  }
  lines.push(`enigma_uptime_seconds ${Math.floor((Date.now() - CONFIG.bootTime) / 1000)}`);
  res.send(lines.join('\n') + '\n');
});

// ── Diagnose (auth required, live probe all providers in parallel) ────
// Probes EVERY key for each provider in parallel (not just the first
// key), returning per-key results with masked identifiers so the
// health of each individual key is visible.
app.get('/api/diagnose', adminLimiter, async (req, res) => {
  if (!isAuthorizedAdmin(req)) return res.status(401).json({ error: 'Invalid Admin Password supplied.' });

  const probePayload = {
    messages: [{ role: 'user', content: 'Reply with exactly: OK' }],
    max_tokens: 5,
    temperature: 0
  };

  const results = await Promise.all(PROVIDER_NAMES.map(async (name) => {
    const config = providers[name];
    const keys = getKeys(config?.token);
    if (keys.length === 0) return { name, configured: false, skipped: 'no key set' };
    if (settings.providerEnabled[name] === false) return { name, configured: true, skipped: 'disabled in settings' };

    const firstEntry = Object.values(routingMatrix).flat().find(e => e.provider === name);
    const probeModel = firstEntry?.model;
    if (!probeModel) return { name, configured: true, skipped: 'no model mapped' };

    // Probe ALL keys for this provider in parallel.
    const keyResults = await Promise.all(keys.map(async (key) => {
      const started = Date.now();
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 15_000);
      try {
        const headers = { 'Content-Type': 'application/json', 'Authorization': `Bearer ${key}`, ...config.extraHeaders };
        const response = await fetch(config.url, {
          method: 'POST', headers,
          body: JSON.stringify(sanitizeForProvider({ ...probePayload, model: probeModel }, name)),
          signal: controller.signal
        });
        clearTimeout(timeout);
        const latencyMs = Date.now() - started;
        if (response.ok) return { key: maskKey(key), ok: true, latencyMs };
        const bodySnippet = summarizeErrorBody(await response.text().catch(() => ''));
        return { key: maskKey(key), ok: false, status: response.status, error: bodySnippet, latencyMs };
      } catch (err) {
        clearTimeout(timeout);
        return {
          key: maskKey(key), ok: false,
          error: err.name === 'AbortError' ? 'timed out after 15000ms' : err.message,
          latencyMs: Date.now() - started
        };
      }
    }));

    const okCount = keyResults.filter(r => r.ok).length;
    return {
      name, configured: true, model: probeModel,
      ok: okCount > 0,
      keysOk: okCount,
      keysTotal: keys.length,
      keys: keyResults
    };
  }));

  res.json({ checkedAt: new Date().toISOString(), results });
});

// ── Settings (auth required) ──────────────────────────────────────────
app.get('/api/settings', adminLimiter, (req, res) => {
  if (!isAuthorizedAdmin(req)) return res.status(401).json({ error: 'Invalid Admin Password supplied.' });
  res.json({
    ...settings,
    providers: PROVIDER_NAMES.map(name => ({ name, configured: providerHasKey(name), enabled: settings.providerEnabled[name] !== false }))
  });
});

app.post('/api/settings', adminLimiter, (req, res) => {
  if (!isAuthorizedAdmin(req)) return res.status(401).json({ error: 'Invalid Admin Password supplied.' });
  const body = req.body || {};
  if (typeof body.autoPilotFallback === 'boolean') settings.autoPilotFallback = body.autoPilotFallback;
  if (typeof body.contentInspection === 'boolean') settings.contentInspection = body.contentInspection;
  if (typeof body.hedgeConcurrency === 'number' && body.hedgeConcurrency >= 1 && body.hedgeConcurrency <= 5) {
    settings.hedgeConcurrency = Math.floor(body.hedgeConcurrency);
  }
  if (Number.isFinite(body.longContextCharThreshold) && body.longContextCharThreshold > 0) {
    settings.longContextCharThreshold = Math.floor(body.longContextCharThreshold);
    CONFIG.longContextCharThreshold = settings.longContextCharThreshold;
  }
  if (body.providerEnabled && typeof body.providerEnabled === 'object') {
    for (const name of PROVIDER_NAMES) {
      if (typeof body.providerEnabled[name] === 'boolean') settings.providerEnabled[name] = body.providerEnabled[name];
    }
  }
  saveSettings();
  res.json({
    ...settings,
    providers: PROVIDER_NAMES.map(name => ({ name, configured: providerHasKey(name), enabled: settings.providerEnabled[name] !== false }))
  });
});

// ── Reset metrics (auth required) ────────────────────────────────────
// Clears all provider metrics, key circuit-breaker state, and model
// health cooldowns. Useful after an incident or for a clean slate.
app.post('/api/reset-metrics', adminLimiter, (req, res) => {
  if (!isAuthorizedAdmin(req)) return res.status(401).json({ error: 'Invalid Admin Password supplied.' });

  // Replace each provider's metrics with a fresh instance.
  for (const name of PROVIDER_NAMES) {
    providerMetrics.set(name, new ProviderMetrics());
  }
  keyHealth.clear();
  modelHealth.clear();

  log('info', null, 'metrics reset', { providers: PROVIDER_NAMES.length });
  res.json({
    reset: true,
    checkedAt: new Date().toISOString(),
    cleared: {
      providerMetrics: PROVIDER_NAMES.length,
      keyHealthEntries: 0,
      modelHealthEntries: 0
    }
  });
});

// ── Model catalog (no auth, public) ───────────────────────────────────
const OPENAI_MODELS_RESPONSE = {
  object: 'list',
  data: modelCatalog.map(e => ({ id: e.label, object: 'model', created: Date.now(), owned_by: 'enigma-edge' }))
};
app.options(['/v1/chat/completions', '/chat/completions', '/models', '/v1/models', '/v1/chat/completions/models'], restrictedCors);
app.get(['/models', '/v1/models', '/v1/chat/completions/models'], restrictedCors, (req, res) => {
  res.json(OPENAI_MODELS_RESPONSE);
});

const PUBLIC_CATALOG = modelCatalog.map(e => ({
  id: e.id, label: e.label, tagline: e.tagline, description: e.description, recommended: !!e.recommended
}));
app.get('/api/catalog', (req, res) => res.json(PUBLIC_CATALOG));

// ══════════════════════════════════════════════════════════════════════
// SECTION 13 — SINGLE ATTEMPT
//
// One provider + one key. Returns a discriminated result so the
// caller can decide what to do without re-inspecting raw responses.
//
// Result shapes:
//   { ok: true, response, provider, model, key, latencyMs }
//   { retry: true, status, provider, model, key, bodySnippet, retryAfterMs? }
//   { softRetry: true, status, provider, model, key, bodySnippet }  — payload issue
//   { modelDead: true, provider, model, status, bodySnippet }       — 404
//   { fatal: true, status, body, provider, model }                  — non-retryable
//   { networkError: true, message, provider, model, key, timedOut }
// ══════════════════════════════════════════════════════════════════════

const RETRYABLE_STATUS = new Set([401, 402, 403, 408, 409, 429, 500, 502, 503, 529]);
const SOFT_RETRYABLE_STATUS = new Set([400]);
const MODEL_DEAD_STATUS = new Set([404]);

async function singleAttempt({ provider, model, key, payloadBody, config, externalSignal, waveSignal, reqId }) {
  const sem = semaphores.get(provider);
  await sem.acquire();

  const timeoutMs = getAdaptiveTimeout(provider);
  const attemptStarted = Date.now();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  // Chain external abort (client disconnect) into our controller.
  const onExternalAbort = () => controller.abort();
  if (externalSignal) externalSignal.addEventListener('abort', onExternalAbort);
  // Chain the per-wave abort signal (hedged race loser) into our
  // controller so that when a sibling task wins the race, this losing
  // attempt aborts its upstream fetch instead of burning quota.
  const onWaveAbort = () => controller.abort();
  if (waveSignal) waveSignal.addEventListener('abort', onWaveAbort);

  try {
    recordAttempt(provider);
    const fetchHeaders = {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${key}`,
      ...config.extraHeaders
    };

    const response = await fetch(config.url, {
      method: 'POST', headers: fetchHeaders, body: payloadBody, signal: controller.signal
    });
    const latencyMs = Date.now() - attemptStarted;

    if (response.ok) {
      markKeySuccess(provider, key);
      recordSuccess(provider, latencyMs);
      log('debug', reqId, 'upstream ok', { provider, model, latencyMs, timeoutMs });
      return { ok: true, response, provider, model, key, latencyMs };
    }

    // Read body ONCE — never twice (the old code's double-read bug).
    const bodyText = await response.text().catch(() => '');
    const bodySnippet = summarizeErrorBody(bodyText);

    // Parse rate-limit headers for smarter cooldown.
    const rateLimit = parseRateLimitHeaders(response.headers);
    const retryAfterMs = parseRetryAfter(response.headers.get('retry-after'));
    // If we have X-RateLimit-Remaining=0, treat like a 429 even if
    // the status is 200 (some providers do this).
    if (rateLimit?.remaining === 0 && !retryAfterMs && rateLimit.resetMs) {
      markKeyFailure(provider, key, rateLimit.resetMs);
      recordFailure(provider, { status: response.status, message: 'rate-limited (X-RateLimit-Remaining=0)', provider, model });
      return { retry: true, status: 429, provider, model, key, bodySnippet, retryAfterMs: rateLimit.resetMs };
    }

    if (MODEL_DEAD_STATUS.has(response.status)) {
      markModelDead(provider, model);
      recordFailure(provider, { status: response.status, message: bodySnippet, provider, model });
      log('warn', reqId, 'model dead (404)', { provider, model, snippet: bodySnippet });
      return { modelDead: true, provider, model, status: response.status, bodySnippet };
    }

    if (RETRYABLE_STATUS.has(response.status)) {
      markKeyFailure(provider, key, retryAfterMs);
      recordFailure(provider, { status: response.status, message: bodySnippet, provider, model });
      log('warn', reqId, 'upstream retryable error', { provider, model, status: response.status, snippet: bodySnippet, retryAfterMs });
      return { retry: true, status: response.status, provider, model, key, bodySnippet, retryAfterMs };
    }

    if (SOFT_RETRYABLE_STATUS.has(response.status)) {
      // Payload quirk — not the key's fault. Try next provider.
      recordFailure(provider, { status: response.status, message: bodySnippet, provider, model });
      log('warn', reqId, 'upstream soft-retryable (400)', { provider, model, snippet: bodySnippet });
      return { softRetry: true, status: response.status, provider, model, key, bodySnippet };
    }

    // Non-retryable (e.g. 422). Return body to client.
    recordFailure(provider, { status: response.status, message: bodySnippet, provider, model });
    log('warn', reqId, 'upstream fatal', { provider, model, status: response.status, snippet: bodySnippet });
    return { fatal: true, status: response.status, body: bodySnippet || bodyText, provider, model };

  } catch (err) {
    const externallyAborted = (externalSignal && externalSignal.aborted) || (waveSignal && waveSignal.aborted);
    const timedOut = err.name === 'AbortError' && !externallyAborted;
    const reason = timedOut ? `timed out after ${timeoutMs}ms` : err.message;
    markKeyFailure(provider, key);
    recordFailure(provider, { status: null, message: reason, provider, model });
    log('warn', reqId, 'upstream network error', { provider, model, reason, timedOut });
    return { networkError: true, message: reason, provider, model, key, timedOut };
  } finally {
    clearTimeout(timer);
    if (externalSignal) externalSignal.removeEventListener('abort', onExternalAbort);
    if (waveSignal) waveSignal.removeEventListener('abort', onWaveAbort);
    sem.release();
  }
}

// ══════════════════════════════════════════════════════════════════════
// SECTION 14 — STREAM PIPE (single-client)
//
// Relays an upstream SSE response to the client with proper
// backpressure. Detects mid-stream errors and logs them without
// crashing. Aborts cleanly on client disconnect.
// ══════════════════════════════════════════════════════════════════════

async function pipeStream(response, res, { reqId, provider, model }) {
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('Content-Type', 'text/event-stream');
  // NOTE: headers are flushed only after the first chunk is validated
  // as SSE, so we can still return a proper 502 if the upstream sends
  // a JSON error body instead of an event stream.

  let bytesRelayed = 0;
  let keepaliveTimer = null;
  try {
    const reader = response.body.getReader();
    let firstChunk = true;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      if (firstChunk) {
        firstChunk = false;
        // ── First-chunk validation ───────────────────────────────────
        // A healthy SSE stream's first bytes start with 'data:' or a
        // comment line (':'). If the upstream returned JSON (starts
        // with '{'), it's almost certainly an error body — abort and
        // return 502 instead of relaying garbage to the client.
        const text = Buffer.from(value).toString('utf8').trimStart();
        if (text.startsWith('{')) {
          log('warn', reqId, 'stream first chunk is JSON, not SSE — returning 502', { provider, model, snippet: summarizeErrorBody(text) });
          try { await reader.cancel(); } catch {}
          if (!res.headersSent) {
            return res.status(502).json({ error: 'Upstream returned a non-SSE response (JSON body).', provider });
          }
          if (!res.writableEnded) {
            res.write(`data: ${JSON.stringify({ error: 'upstream returned JSON instead of SSE', provider })}\n\n`);
          }
          break;
        }
        // Valid SSE — flush headers and start the keepalive heartbeat.
        res.flushHeaders();
        keepaliveTimer = setInterval(() => {
          if (!res.writableEnded) {
            try { res.write(': keepalive\n\n'); } catch {}
          }
        }, 15_000);
        log('debug', reqId, 'stream started', { provider, model });
      }

      // Backpressure: wait for drain if the internal buffer is full.
      if (!res.write(value)) {
        await new Promise(resolve => res.once('drain', resolve));
      }
      bytesRelayed += value.length;
    }
  } catch (streamErr) {
    if (!res.writableEnded) {
      log('warn', reqId, 'stream broke mid-response', { provider, error: streamErr.message });
      try {
        res.write(`data: ${JSON.stringify({ error: 'stream_interrupted', provider })}\n\n`);
      } catch {}
    }
  } finally {
    if (keepaliveTimer) clearInterval(keepaliveTimer);
    if (!res.writableEnded) res.end();
    // Update bytes-out metric only (latency already recorded in singleAttempt).
    const m = providerMetrics.get(provider);
    if (m) m.bytesOut += bytesRelayed;
  }
}

// ══════════════════════════════════════════════════════════════════════
// SECTION 15 — HEDGED WATERFALL EXECUTION
//
// Wave 1: Fire the first N providers in parallel (hedged execution).
//         First ok wins; losers are left to complete (their upstream
//         fetch will be aborted when the client gets a response or
//         when the request's AbortController fires).
// Wave 2+: Sequential fallback for remaining providers until the
//          total budget is exhausted.
//
// Within each provider, keys are tried sequentially (racing keys
// against the same endpoint just doubles rate-limit consumption).
// ══════════════════════════════════════════════════════════════════════

async function runProviderKeys({ target, reqBody, externalSignal, waveSignal, reqId, attemptLog }) {
  const config = providers[target.provider];
  const keyInventory = getKeys(config?.token);
  if (keyInventory.length === 0) {
    return { retry: true, status: null, provider: target.provider, model: target.model, bodySnippet: 'no keys configured' };
  }

  if (isModelDead(target.provider, target.model)) {
    attemptLog.push({ provider: target.provider, model: target.model, status: null, error: 'skipped — model dead' });
    return { modelDead: true, provider: target.provider, model: target.model };
  }

  const keys = orderKeys(target.provider, keyInventory).slice(0, CONFIG.maxKeysPerProvider);
  const payloadBody = JSON.stringify(sanitizeForProvider({ ...reqBody, model: target.model }, target.provider));

  let lastResult = null;
  for (const key of keys) {
    if (externalSignal?.aborted) {
      return { networkError: true, message: 'client disconnected', provider: target.provider, model: target.model, key: maskKey(key), timedOut: false };
    }

    // Check if this key is available (circuit breaker).
    const avail = isKeyAvailable(target.provider, key);
    if (!avail.available) {
      attemptLog.push({ provider: target.provider, model: target.model, key: maskKey(key), status: null, error: `circuit open (${avail.state}), cooldown ${Math.round(avail.cooldownMs)}ms` });
      continue;
    }

    const result = await singleAttempt({
      provider: target.provider, model: target.model, key,
      payloadBody, config, externalSignal, waveSignal, reqId
    });

    if (result.ok) {
      attemptLog.push({ provider: target.provider, model: target.model, key: maskKey(key), status: 200, latencyMs: result.latencyMs });
      return result;
    }

    attemptLog.push({
      provider: target.provider, model: target.model, key: maskKey(key),
      status: result.status ?? null,
      error: result.bodySnippet || result.message || result.body || 'unknown'
    });

    if (result.modelDead) return result;     // skip remaining keys
    if (result.fatal) return result;         // return to client immediately
    if (result.softRetry) return result;     // try next provider, not next key
    // retry or networkError → try next key
    lastResult = result;
  }

  return lastResult || { retry: true, status: null, provider: target.provider, model: target.model, bodySnippet: 'all keys failed or circuit-open' };
}

// Race N promises, return the first { ok: true }. If all fail, return
// the best non-ok result (prefer fatal over retry over networkError).
async function raceFirstOk(tasks) {
  return new Promise((resolve) => {
    let remaining = tasks.length;
    let settled = false;
    const results = new Array(tasks.length);

    const checkAllFailed = () => {
      if (settled) return;
      settled = true;
      // Pick the best result: fatal > softRetry > retry > modelDead > networkError
      const priority = ['fatal', 'softRetry', 'retry', 'modelDead', 'networkError'];
      for (const p of priority) {
        const found = results.find(r => r && r[p]);
        if (found) return resolve(found);
      }
      resolve({ retry: true });
    };

    tasks.forEach((task, i) => {
      task.then(r => {
        results[i] = r;
        if (settled) return;
        if (r && r.ok) {
          settled = true;
          resolve(r);
          return;
        }
        remaining--;
        if (remaining === 0) checkAllFailed();
      }).catch(() => {
        results[i] = { networkError: true, message: 'task rejected' };
        remaining--;
        if (remaining === 0 && !settled) checkAllFailed();
      });
    });
  });
}

async function executeWaterfall({ waterfall, reqBody, externalSignal, budgetDeadline, reqId }) {
  const attemptLog = [];
  const hedgeN = Math.max(1, Math.min(settings.hedgeConcurrency || 1, waterfall.length));

  log('info', reqId, 'waterfall starting', {
    providers: waterfall.map(w => `${w.provider}/${w.model}`),
    hedge: hedgeN,
    budgetMs: budgetDeadline - Date.now()
  });

  // ── Wave 1: hedged parallel ────────────────────────────────────────
  // A per-wave AbortController lets us abort losing tasks the moment a
  // sibling wins the race, so their in-flight upstream fetches are
  // cancelled instead of consuming quota for a result we'll discard.
  const waveController = new AbortController();
  const wave1Tasks = [];
  for (let p = 0; p < hedgeN; p++) {
    wave1Tasks.push(runProviderKeys({
      target: waterfall[p], reqBody, externalSignal, waveSignal: waveController.signal, reqId, attemptLog
    }));
  }

  const wave1Result = await raceFirstOk(wave1Tasks);

  if (wave1Result.ok) {
    // Abort the wave so losing tasks cancel their upstream fetches.
    waveController.abort();
    log('info', reqId, 'waterfall succeeded (wave 1 hedged)', {
      provider: wave1Result.provider, model: wave1Result.model,
      latencyMs: wave1Result.latencyMs, hedgeUsed: hedgeN > 1
    });
    return { ...wave1Result, attemptLog, hedgeUsed: hedgeN > 1 };
  }
  // No winner — abort any still-running losers before moving on, so
  // they don't linger and consume concurrency slots into wave 2.
  waveController.abort();

  // ── Wave 2+: sequential fallback ───────────────────────────────────
  for (let p = hedgeN; p < waterfall.length; p++) {
    if (externalSignal?.aborted) {
      attemptLog.push({ note: 'aborted — client disconnected' });
      break;
    }
    if (Date.now() > budgetDeadline) {
      attemptLog.push({ note: 'stopped — total budget exceeded' });
      log('warn', reqId, 'waterfall budget exceeded', { elapsedMs: Date.now() - (budgetDeadline - CONFIG.totalBudgetMs) });
      break;
    }

    const result = await runProviderKeys({
      target: waterfall[p], reqBody, externalSignal, reqId, attemptLog
    });

    if (result.ok) {
      log('info', reqId, 'waterfall succeeded (wave 2+)', {
        provider: result.provider, model: result.model, latencyMs: result.latencyMs
      });
      return { ...result, attemptLog, hedgeUsed: false };
    }
    if (result.fatal) {
      return { ...result, attemptLog, hedgeUsed: false };
    }
    // retry / softRetry / modelDead / networkError → continue
  }

  return { exhausted: true, attemptLog, hedgeUsed: hedgeN > 1 };
}

// ══════════════════════════════════════════════════════════════════════
// SECTION 16 — MAIN COMPLETIONS ROUTE
// ══════════════════════════════════════════════════════════════════════

const completionsLimiter = rateLimit(CONFIG.completionsRateLimit);

app.post(['/v1/chat/completions', '/chat/completions'], restrictedCors, completionsLimiter, async (req, res) => {
    const reqId = crypto.randomBytes(4).toString('hex');
    res.setHeader('X-Request-Id', reqId);
    const startedAt = Date.now();

    // ── Auth ───────────────────────────────────────────────────────────
    if (!isAuthorized(req)) {
    log('warn', reqId, 'auth failed', { ip: req.ip });
    return res.status(401).json({ error: 'Invalid Proxy Password supplied.' });
  }

  // ── Payload validation ─────────────────────────────────────────────
  if (!req.body || typeof req.body !== 'object' || !Array.isArray(req.body.messages)) {
    return res.status(400).json({ error: 'Malformed API payload: messages array required.' });
  }
  if (req.body.messages.length === 0) {
    return res.status(400).json({ error: 'Messages array is empty.' });
  }
  if (req.body.messages.length > CONFIG.maxMessages) {
    return sendErrorMessage(req, res, 400, `That request has too many messages (max ${CONFIG.maxMessages}). Trim the history and try again.`);
  }

  // Validate each message has required fields.
  for (let i = 0; i < req.body.messages.length; i++) {
    const msg = req.body.messages[i];
    if (!msg || typeof msg.role !== 'string' || typeof msg.content === 'undefined') {
      return res.status(400).json({ error: `Message at index ${i} is malformed (needs role and content).` });
    }
  }

  // ── ONLINE probe detection ─────────────────────────────────────────
  // JanitorAI sends a single-message "ONLINE" probe to check if the
  // proxy is alive. Short-circuit it without touching any provider.
  const firstMsg = req.body.messages[0]?.content;
  if (req.body.messages.length === 1 && typeof firstMsg === 'string' && firstMsg.includes('ONLINE')) {
    req.body.messages = [
      { role: 'system', content: 'Reply precisely with "ONLINE".' },
      { role: 'user', content: 'Probe.' }
    ];
    req.body.max_tokens = 5;
    req.body.temperature = 0.0;
  } else {
    // Clean up the payload: remove empty messages, cap max_tokens,
    // strip params that most providers don't support.
    req.body.messages = req.body.messages.filter(
      msg => msg.content && typeof msg.content === 'string' && msg.content.trim() !== ''
    );
    if (req.body.max_tokens && req.body.max_tokens > CONFIG.maxOutputTokens) {
      req.body.max_tokens = CONFIG.maxOutputTokens;
    }
    delete req.body.repetition_penalty;
    delete req.body.top_k;
  }

  // ── Model resolution ───────────────────────────────────────────────
  let requested = typeof req.body.model === 'string' ? req.body.model : '';
  const resolved = resolveFriendlyModel(requested);

  if (resolved && resolved.ambiguous) {
    return sendAssistantMessage(req, res, clarificationText(requested, resolved.ambiguous));
  }

  let entry;
  if (resolved) {
    entry = resolved.entry;
  } else if (settings.autoPilotFallback) {
    entry = modelCatalog.find(e => e.id === 'auto');
  } else {
    return sendErrorMessage(req, res, 400, noMatchText(requested));
  }

  // ── Build the waterfall ────────────────────────────────────────────
  let targetKey = entry.categoryKey;
  let waterfall = buildWaterfall(entry.categoryKey, entry.preferred);

  // ── AUTO PILOT: content-aware routing ──────────────────────────────
  if (targetKey === '[Enigma] Auto-Pilot Gateway') {
    if (!settings.contentInspection) {
      targetKey = '[Roleplay] Maximum Intelligence';
    } else {
      const totalChars = estimateTotalChars(req.body.messages);
      const isNSFW = NSFW_REGEX.test(recentPlainText(req.body.messages));
      const threshold = settings.longContextCharThreshold || CONFIG.longContextCharThreshold;
      if (totalChars > threshold) {
        targetKey = '[Context] Deep Logic';
        log('debug', reqId, 'autopilot → long context', { chars: totalChars, threshold });
      } else if (isNSFW) {
        targetKey = '[NSFW] Uncensored Fast';
        log('debug', reqId, 'autopilot → NSFW');
      } else {
        targetKey = '[Roleplay] Maximum Intelligence';
        log('debug', reqId, 'autopilot → roleplay (default)');
      }
    }
    waterfall = buildWaterfall(targetKey);
    if (waterfall.length === 0) waterfall = buildWaterfall('[Speed] Llama 3.3 70B');
  }

  if (waterfall.length === 0) {
    log('error', reqId, 'no providers available', { category: targetKey });
    return sendErrorMessage(req, res, 503, 'No providers are currently available for this model category. Check /api/status and your provider keys.');
  }

  // ── Set up request lifecycle ───────────────────────────────────────
  const disconnectController = new AbortController();
  const externalSignal = disconnectController.signal;
  req.on('close', () => disconnectController.abort());

  const budgetDeadline = startedAt + CONFIG.totalBudgetMs;
  const isStream = !!req.body.stream;

  log('info', reqId, 'request received', {
    model: requested, resolved: entry.id, category: targetKey,
    stream: isStream, messageCount: req.body.messages.length,
    estTokens: estimateTokens(req.body.messages),
    waterfallDepth: waterfall.length
  });

  // ══════ NON-STREAMING PATH ════════
  if (!isStream) {
    const hashKey = coalesceHash(req.body, targetKey);
    const shared = getOrCreateInflight(hashKey, async () => {
      const result = await executeWaterfall({
        waterfall, reqBody: req.body, externalSignal, budgetDeadline, reqId
      });

      if (result.ok) {
        // Read and validate the upstream response.
        const responseText = await result.response.text();
        // Track both directions: bytesIn is the raw upstream payload we
        // just read; bytesOut is what we'll ultimately send back to the
        // client (same size here, since non-streaming responses are
        // forwarded as-is). The streaming path already tracks this via
        // bytesRelayed in pipeStream — this closes the gap for non-stream.
        providerMetrics.get(result.provider)?.recordBytesIn(responseText.length);
        recordBytesOut(result.provider, responseText.length);

        let payload;
        try {
          payload = JSON.parse(responseText);
        } catch {
          log('error', reqId, 'upstream returned invalid JSON', { provider: result.provider, snippet: summarizeErrorBody(responseText) });
          return { kind: 'fatal', status: 502, body: 'Upstream returned invalid JSON.' };
        }

        if (!validateUpstreamResponse(payload)) {
          log('error', reqId, 'upstream response failed validation', { provider: result.provider });
          return { kind: 'fatal', status: 502, body: 'Upstream returned a malformed response.' };
        }

        payload.model = result.model;
        return { kind: 'ok', payload, provider: result.provider, model: result.model };
      }

      if (result.fatal) {
        return { kind: 'fatal', status: result.status, body: result.body };
      }

      return { kind: 'exhausted', attemptLog: result.attemptLog, elapsedMs: Date.now() - startedAt };
    });

    const outcome = await shared;

    if (externalSignal.aborted) return;

    if (outcome.kind === 'ok') {
      res.setHeader('X-Resolved-Model', outcome.model);
      res.setHeader('X-Resolved-Provider', outcome.provider);
      log('info', reqId, 'request completed', { provider: outcome.provider, model: outcome.model, elapsedMs: Date.now() - startedAt });
      return res.json(outcome.payload);
    }

    if (outcome.kind === 'fatal') {
      log('warn', reqId, 'request failed (fatal)', { status: outcome.status, elapsedMs: Date.now() - startedAt });
      return res.status(outcome.status).send(outcome.body);
    }

    // exhausted
    log('error', reqId, 'all providers exhausted', { elapsedMs: outcome.elapsedMs, attempts: outcome.attemptLog.length });
    return res.status(503).json({
      error: 'Routing Fault: All integrated cloud providers exhausted.',
      elapsedMs: outcome.elapsedMs,
      attempts: outcome.attemptLog.slice(-CONFIG.maxAttemptLogPerRequest)
    });
  }

  // ══════ STREAMING PATH ════════
  // Try to fan-out from an existing stream multiplexer for identical
  // concurrent requests. If none exists, create one.
  const streamHash = coalesceHash(req.body, targetKey);
  let mux = getOrCreateStream(streamHash);

  // If this multiplexer already has an upstream running (i.e. another
  // request started it) and is not closed, subscribe to it.
  if (mux.upstreamReader && !mux.closed) {
    mux.addSubscriber(res);
    log('info', reqId, 'stream fan-out subscriber added', { subs: mux.subscribers.size });
    return; // pipeFromUpstream is already running for this mux
  }

  // The mux was closed or never started. Get a fresh one for our
  // exclusive use to avoid colliding with a stale multiplexer.
  if (mux.closed) {
    inflightStreams.delete(streamHash);
    mux = getOrCreateStream(streamHash);
  }

  // Start a fresh waterfall for this stream.
  const result = await executeWaterfall({
    waterfall, reqBody: req.body, externalSignal, budgetDeadline, reqId
  });

  if (externalSignal.aborted) return;

  if (result.ok) {
    res.setHeader('X-Resolved-Model', result.model);
    res.setHeader('X-Resolved-Provider', result.provider);

    // If other subscribers arrived while the waterfall was running,
    // use the multiplexer to fan out to all of them (including us).
    // Otherwise, pipe directly — simpler and lower overhead.
    if (mux.subscribers.size > 0) {
      mux.addSubscriber(res);
      await mux.pipeFromUpstream(result.response, { reqId, provider: result.provider, model: result.model });
    } else {
      await pipeStream(result.response, res, { reqId, provider: result.provider, model: result.model });
    }

    log('info', reqId, 'stream completed', { provider: result.provider, model: result.model, elapsedMs: Date.now() - startedAt });
    return;
  }

  if (result.fatal) {
    log('warn', reqId, 'stream failed (fatal)', { status: result.status, elapsedMs: Date.now() - startedAt });
    return res.status(result.status).send(result.body);
  }

  if (!res.headersSent) {
    log('error', reqId, 'stream exhausted', { elapsedMs: Date.now() - startedAt, attempts: result.attemptLog.length });
    return res.status(503).json({
      error: 'Routing Fault: All integrated cloud providers exhausted.',
      elapsedMs: Date.now() - startedAt,
      attempts: result.attemptLog.slice(-CONFIG.maxAttemptLogPerRequest)
    });
  }
});

// ─── 404 + error handler ──────────────────────────────────────────────
app.use((req, res, next) => {
  if (req.path.startsWith('/v1') || req.path.startsWith('/chat')) {
    return res.status(404).json({ error: 'Not found' });
  }
  next();
});

app.use((err, req, res, next) => {
  if (err && err.message === 'CORS policy violation') {
    return res.status(403).json({ error: 'Origin not allowed.' });
  }
  // express.json body-parse error (payload too large or invalid JSON).
  if (err.type === 'entity.too.large') {
    return res.status(413).json({ error: `Request body exceeds ${CONFIG.maxBodyBytes} limit.` });
  }
  if (err.type === 'entity.parse.failed') {
    return res.status(400).json({ error: 'Invalid JSON in request body.' });
  }
  log('error', null, 'unhandled express error', { error: err.message, stack: err.stack?.split('\n')[0] });
  if (!res.headersSent) res.status(500).json({ error: 'Internal operational crash.' });
});

// ══════════════════════════════════════════════════════════════════════
// SECTION 17 — PROCESS-LIFE: boot, warm-up, shutdown, error handlers
// ══════════════════════════════════════════════════════════════════════

// ── Warm-up: fire a tiny probe to each configured provider at boot.
// This populates the EMA metrics with real latency data so the
// waterfall ordering is informed from the first real request, and
// establishes TLS connections in the pool so the first user request
// doesn't pay the handshake cost.
async function warmup() {
  const configured = PROVIDER_NAMES.filter(n => providerHasKey(n) && settings.providerEnabled[n] !== false);
  if (configured.length === 0) {
    log('warn', null, 'no providers configured — every request will fail', {});
    return;
  }

  log('info', null, 'warming up providers', { count: configured.length });

  const probePayload = {
    messages: [{ role: 'user', content: 'Reply with exactly: OK' }],
    max_tokens: 5,
    temperature: 0
  };

  await Promise.allSettled(configured.map(async (name) => {
    const config = providers[name];
    const keys = getKeys(config.token);
    const key = orderKeys(name, keys)[0];
    if (!key) return;

    const firstEntry = Object.values(routingMatrix).flat().find(e => e.provider === name);
    if (!firstEntry) return;

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10_000);
    try {
      const started = Date.now();
      const headers = { 'Content-Type': 'application/json', 'Authorization': `Bearer ${key}`, ...config.extraHeaders };
      const response = await fetch(config.url, {
        method: 'POST', headers,
        body: JSON.stringify(sanitizeForProvider({ ...probePayload, model: firstEntry.model }, name)),
        signal: controller.signal
      });
      const latencyMs = Date.now() - started;
      if (response.ok) {
        recordSuccess(name, latencyMs);
        log('info', null, 'warmup ok', { provider: name, latencyMs });
      } else {
        const snippet = summarizeErrorBody(await response.text().catch(() => ''));
        recordFailure(name, { status: response.status, message: snippet });
        log('warn', null, 'warmup failed', { provider: name, status: response.status, snippet });
      }
    } catch (err) {
      recordFailure(name, { status: null, message: err.message });
      log('warn', null, 'warmup error', { provider: name, error: err.message });
    } finally {
      clearTimeout(timeout);
    }
  }));

  log('info', null, 'warmup complete', {});
}

// ── Process-level error handlers ──────────────────────────────────────
// Never let an uncaught exception kill the process silently. Log it,
// then let the process restart (if running under a process manager)
// or continue (if the error was in an async context we can survive).
process.on('uncaughtException', (err) => {
  log('error', null, 'uncaughtException', { error: err.message, stack: err.stack?.split('\n').slice(0, 5).join(' | ') });
  // Don't exit — the error might be in an async context that doesn't
  // affect the main event loop. If it does, the health check will
  // start failing and the process manager will restart us.
});

process.on('unhandledRejection', (reason, promise) => {
  log('error', null, 'unhandledRejection', { reason: reason?.message || String(reason) });
});

// ── Memory monitoring ─────────────────────────────────────────────────
const memCheckInterval = setInterval(() => {
  const mem = process.memoryUsage();
  const heapMB = Math.round(mem.heapUsed / 1024 / 1024);
  const rssMB = Math.round(mem.rss / 1024 / 1024);
  if (heapMB > 500) {
    log('warn', null, 'high memory usage', { heapMB, rssMB, inflight: inflightCount,
      keyHealthEntries: keyHealth.size, modelHealthEntries: modelHealth.size,
      inflightCoalesce: inflightNonStream.size, inflightStreams: inflightStreams.size });
  }
}, 30_000).unref();

// ── Graceful shutdown ─────────────────────────────────────────────────
let shuttingDown = false;
function shutdown(signal) {
  if (shuttingDown) return;
  shuttingDown = true;

  log('info', null, 'shutdown initiated', { signal, inflight: inflightCount });

  // Stop accepting new connections.
  server.close(() => {
    log('info', null, 'all connections closed, exiting', {});
    process.exit(0);
  });

  // If in-flight requests don't finish in 15s, force exit.
  setTimeout(() => {
    log('warn', null, 'shutdown timeout — forcing exit', { inflight: inflightCount });
    process.exit(1);
  }, 15_000).unref();

  // Clear intervals.
  clearInterval(memCheckInterval);
}

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));

// ── Start the server ──────────────────────────────────────────────────
const server = app.listen(CONFIG.port, () => {
  log('info', null, 'Enigma Edge Gateway started', { port: CONFIG.port });
  log('info', null, 'provider keys at boot', {
    summary: PROVIDER_NAMES.map(name => `${name}=${getKeys(providers[name].token).length}key(s)`).join(', ')
  });

  const configuredCount = PROVIDER_NAMES.filter(n => providerHasKey(n)).length;
  if (configuredCount === 0) {
    log('warn', null, 'no provider has any key configured — every chat request will fail', {});
  }

  log('info', null, 'configuration', {
    hedge: settings.hedgeConcurrency,
    adaptiveTimeout: `factor=${CONFIG.adaptiveTimeoutFactor} range=[${CONFIG.adaptiveTimeoutMinMs}-${CONFIG.adaptiveTimeoutMaxMs}]ms`,
    totalBudget: `${CONFIG.totalBudgetMs}ms`,
    perProviderConcurrency: CONFIG.providerMaxConcurrency
  });

  // Fire warm-up in the background — don't block the server from
  // accepting connections while probes are running.
  warmup().catch(err => {
    log('error', null, 'warmup crashed', { error: err.message });
  });

  log('info', null, 'endpoints', {
    health: 'GET /health',
    status: 'GET /api/status',
    metrics: 'GET /api/metrics (auth) | GET /metrics (auth, prometheus)',
    diagnose: 'GET /api/diagnose (auth)',
    settings: 'GET/POST /api/settings (auth)',
    completions: 'POST /v1/chat/completions | /chat/completions'
  });
});

// ── Explicit server timeouts ───────────────────────────────────────────
// Bound how long a single request can take and how long idle keep-alive
// connections linger. headersTimeout MUST be > keepAliveTimeout to avoid
// a race where a new request on a keep-alive connection is dropped.
server.setTimeout(120000);       // 120s hard request timeout
server.keepAliveTimeout = 5000;  // 5s idle keep-alive
server.headersTimeout = 51000;   // 51s (must be > keepAliveTimeout)

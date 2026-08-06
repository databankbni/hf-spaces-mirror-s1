/**
 * THOX inference adapters — one chat contract over every backend wire shape.
 *
 * SHARED CONTRACT. This file is written to be lifted verbatim into any THOX surface
 * (thoxos-webby-edition, thoxroute, internal tools). It has no framework imports, no app state
 * and no DOM dependency beyond `fetch` — so the free-CPU fallback tier is reachable from every
 * app through the same call, not re-implemented per app.
 *
 * Why this exists: our free Hugging Face Spaces do not speak one protocol.
 *   - `thoxmythos` — Next.js `/api/chat`, newline-delimited JSON, no auth (the THOX bridge)
 *   - `openai`     — `/v1/chat/completions`, SSE `data:` frames, Bearer auth
 *   - `gradio`     — Gradio 4/5 two-step queue: POST `/gradio_api/call/<fn>` → event_id,
 *                    then GET the SSE result stream
 * Callers should not care which one answered, so each adapter reduces to `ChatDelta` callbacks.
 */

// @ts-expect-error - plain ESM shared with server.js; one implementation, no per-path drift.
import { needsIdentityGuard, withIdentitySystem, THOXMYTHOS_STOPS, applyIdentityFilter } from '../../../shared/identity-guard.mjs';

export type ThoxWireType = 'thoxmythos' | 'openai' | 'gradio' | 'webgpu' | 'proxy';

export interface ChatTurn {
    role: 'system' | 'user' | 'assistant';
    content: string;
}

export interface AdapterTarget {
    type: ThoxWireType;
    /** `proxy`: the registry model id to ask this app's own /api/v2/thoxroute/chat for. */
    modelId?: string;
    /** `webgpu`: load the ~2 GB on-device model if it is not already resident. */
    autoLoad?: boolean;
    /** Origin (thoxmythos/gradio) or API base ending in /v1 (openai). No trailing slash needed. */
    baseURL: string;
    apiKey?: string;
    /** Upstream model id for `openai`. */
    model?: string;
    /** Gradio named endpoint, default `/chat`. */
    fn?: string;
}

export interface AdapterCallbacks {
    /** Called with the FULL accumulated text so far (not the increment). */
    onChunk?: (fullText: string) => void;
    /** Reported when a target knows which sub-tier actually served the turn (e.g. the proxy). */
    onServedTier?: (tier: string) => void;
}

export interface AdapterOptions {
    maxTokens?: number;
    temperature?: number;
    signal?: AbortSignal;
    /** Vendor stop strings; set by the identity guard for ThoxMythos-family models. */
    stop?: string[];
    /** Registry model id — decides whether the identity guard applies. */
    modelId?: string;
}

/**
 * A backend failure that the router should CASCADE past rather than surface.
 *
 * Distinguishing "this backend is out of credit / asleep / overloaded" from "the model answered
 * with an error" is the whole point: only the former should silently fall through to a lower
 * tier. A 400 means our request was wrong and the next tier will reject it too.
 */
export class UpstreamUnavailable extends Error {
    readonly status: number;
    constructor(status: number, message: string) {
        super(message);
        this.name = 'UpstreamUnavailable';
        this.status = status;
    }
}

/**
 * HTTP statuses that mean "try the next tier".
 *  402 — out of credit (the case this whole tier exists for)
 *  401/403 — a credential this deployment does not hold
 *  404 — endpoint moved or Space rebuilt without the route
 *  408/425/429 — busy or rate-limited
 *  5xx — paused Space (HF serves 503 for PAUSED), crash, cold-start timeout
 *  0   — network failure / DNS / abort-by-timeout, synthesised by the adapters
 */
export function isCascadable(status: number): boolean {
    return (
        status === 0 ||
        status === 401 ||
        status === 402 ||
        status === 403 ||
        status === 404 ||
        status === 408 ||
        status === 425 ||
        status === 429 ||
        status >= 500
    );
}

const trim = (u: string) => u.replace(/\/+$/, '');

/** Flatten a turn list into a single prompt, for backends that accept only a string (Gradio). */
export function flattenTurns(messages: ChatTurn[]): string {
    const sys = messages.filter((m) => m.role === 'system').map((m) => m.content);
    const convo = messages
        .filter((m) => m.role !== 'system')
        .map((m) => `${m.role === 'user' ? 'User' : 'Assistant'}: ${m.content}`);
    // The last user turn is what the model must answer; prior turns are context.
    return [...sys, ...convo].join('\n\n');
}

// ─── thoxmythos: NDJSON bridge ───

async function callThoxMythos(
    target: AdapterTarget,
    messages: ChatTurn[],
    cb: AdapterCallbacks,
    opts: AdapterOptions
): Promise<string> {
    let resp: Response;
    try {
        resp = await fetch(`${trim(target.baseURL)}/api/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                messages: messages.map((m) => ({ role: m.role, content: m.content })),
                temperature: opts.temperature ?? 0.7,
                maxTokens: opts.maxTokens ?? 4096,
                ...(opts.stop ? { stop: opts.stop } : {}),
            }),
            signal: opts.signal,
        });
    } catch (err) {
        if (opts.signal?.aborted) throw err;
        throw new UpstreamUnavailable(0, `network error: ${(err as Error).message}`);
    }
    if (!resp.ok) {
        const detail = await resp.text().catch(() => resp.statusText);
        throw new UpstreamUnavailable(resp.status, detail.slice(0, 300));
    }
    const reader = resp.body?.getReader();
    if (!reader) throw new UpstreamUnavailable(0, 'no response body');

    const decoder = new TextDecoder();
    let full = '';
    let buffer = '';
    for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';
        for (const line of lines) {
            const t = line.trim();
            if (!t) continue;
            let o: { type?: string; text?: string; message?: string };
            try {
                o = JSON.parse(t);
            } catch {
                continue;
            }
            if (o.type === 'delta' && o.text) {
                full += o.text;
                cb.onChunk?.(full);
            } else if (o.type === 'error') {
                throw new UpstreamUnavailable(502, o.message ?? 'upstream error frame');
            }
        }
    }
    return full;
}

// ─── openai: SSE ───

async function callOpenAI(
    target: AdapterTarget,
    messages: ChatTurn[],
    cb: AdapterCallbacks,
    opts: AdapterOptions
): Promise<string> {
    let resp: Response;
    try {
        resp = await fetch(`${trim(target.baseURL)}/chat/completions`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(target.apiKey ? { Authorization: `Bearer ${target.apiKey}` } : {}),
            },
            body: JSON.stringify({
                model: target.model ?? 'default',
                messages,
                stream: true,
                ...(opts.temperature != null ? { temperature: opts.temperature } : {}),
                ...(opts.maxTokens != null ? { max_tokens: opts.maxTokens } : {}),
                ...(opts.stop ? { stop: opts.stop } : {}),
            }),
            signal: opts.signal,
        });
    } catch (err) {
        if (opts.signal?.aborted) throw err;
        throw new UpstreamUnavailable(0, `network error: ${(err as Error).message}`);
    }
    if (!resp.ok) {
        const detail = await resp.text().catch(() => resp.statusText);
        throw new UpstreamUnavailable(resp.status, detail.slice(0, 300));
    }
    const reader = resp.body?.getReader();
    if (!reader) throw new UpstreamUnavailable(0, 'no response body');

    const decoder = new TextDecoder();
    let full = '';
    let buffer = '';
    for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';
        for (const line of lines) {
            const t = line.trim();
            if (!t.startsWith('data:')) continue;
            const data = t.slice(5).trim();
            if (data === '[DONE]') continue;
            try {
                const delta = JSON.parse(data)?.choices?.[0]?.delta?.content;
                if (delta) {
                    full += delta;
                    cb.onChunk?.(full);
                }
            } catch {
                /* keep-alive or comment frame */
            }
        }
    }
    return full;
}

// ─── gradio: two-step queue ───

/**
 * Gradio 4/5 exposes `POST /gradio_api/call/<fn>` returning `{event_id}`, then
 * `GET /gradio_api/call/<fn>/<event_id>` streaming `event:`/`data:` pairs.
 *
 * Args are POSITIONAL, and for a `gr.ChatInterface(type="messages")` the handler takes TWO:
 * `(message, history)`. This is not discoverable from `/gradio_api/info`, which advertises only
 * `message` because the history is a hidden `State` component — send one arg and the Space
 * answers `event: error` with "didn't receive enough input values (needed: 2, got: 1)" in its
 * run log. Verified against tommytracx/ThoxMythos-9B-ZeroGPU on 2026-07-26.
 *
 * A Gradio `event: error` is reported as cascadable: on a free ZeroGPU Space it usually means
 * the per-visitor GPU quota is exhausted, which the next tier can still serve.
 */
async function callGradio(
    target: AdapterTarget,
    messages: ChatTurn[],
    cb: AdapterCallbacks,
    opts: AdapterOptions
): Promise<string> {
    const base = trim(target.baseURL);
    const fn = (target.fn ?? '/chat').replace(/^\//, '');
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (target.apiKey) headers.Authorization = `Bearer ${target.apiKey}`;

    // ChatInterface shape: the latest user turn, plus the prior turns as `history`. Sending the
    // real history (rather than one flattened blob) keeps multi-turn context intact and lets the
    // Space apply its own chat template.
    const lastUser = [...messages].reverse().find((m) => m.role === 'user');
    const history = messages
        .filter((m) => m !== lastUser)
        .map((m) => ({ role: m.role, content: m.content }));

    let enqueue: Response;
    try {
        enqueue = await fetch(`${base}/gradio_api/call/${fn}`, {
            method: 'POST',
            headers,
            body: JSON.stringify({ data: [lastUser?.content ?? flattenTurns(messages), history] }),
            signal: opts.signal,
        });
    } catch (err) {
        if (opts.signal?.aborted) throw err;
        throw new UpstreamUnavailable(0, `network error: ${(err as Error).message}`);
    }
    if (!enqueue.ok) {
        const detail = await enqueue.text().catch(() => enqueue.statusText);
        throw new UpstreamUnavailable(enqueue.status, detail.slice(0, 300));
    }
    const eventId = (await enqueue.json().catch(() => ({})))?.event_id;
    if (!eventId) throw new UpstreamUnavailable(502, 'gradio: no event_id returned');

    const poll = await fetch(`${base}/gradio_api/call/${fn}/${eventId}`, {
        headers: target.apiKey ? { Authorization: `Bearer ${target.apiKey}` } : {},
        signal: opts.signal,
    }).catch((err) => {
        throw new UpstreamUnavailable(0, `network error: ${(err as Error).message}`);
    });
    if (!poll.ok || !poll.body) throw new UpstreamUnavailable(poll.status || 0, 'gradio: no result stream');

    const reader = poll.body.getReader();
    const decoder = new TextDecoder();
    let full = '';
    let buffer = '';
    let event = '';
    for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';
        for (const line of lines) {
            if (line.startsWith('event:')) {
                event = line.slice(6).trim();
                continue;
            }
            if (!line.startsWith('data:')) continue;
            const raw = line.slice(5).trim();
            if (event === 'error') {
                throw new UpstreamUnavailable(503, `gradio error: ${raw || 'null'}`);
            }
            let payload: unknown;
            try {
                payload = JSON.parse(raw);
            } catch {
                continue;
            }
            // Gradio returns the fn's positional outputs as an array.
            const first = Array.isArray(payload) ? payload[0] : payload;
            const text = typeof first === 'string' ? first : undefined;
            if (text != null && text !== full) {
                full = text;
                cb.onChunk?.(full);
            }
        }
    }
    if (!full) throw new UpstreamUnavailable(502, 'gradio: empty result');
    return full;
}

// ─── proxy: this app's own cascading endpoint ───

/**
 * Delegate to `/api/v2/thoxroute/chat`, which walks the SERVER-side tier chain (paid primary ->
 * free ZeroGPU -> free CPU) using credentials the browser must never hold. One target from the
 * client's point of view; several tiers from the server's.
 */
async function callProxy(
    target: AdapterTarget,
    messages: ChatTurn[],
    cb: AdapterCallbacks,
    opts: AdapterOptions
): Promise<string> {
    let resp: Response;
    try {
        resp = await fetch('/api/v2/thoxroute/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                modelId: target.modelId,
                messages,
                ...(opts.temperature != null ? { temperature: opts.temperature } : {}),
                ...(opts.maxTokens != null ? { max_tokens: opts.maxTokens } : {}),
            }),
            signal: opts.signal,
        });
    } catch (err) {
        if (opts.signal?.aborted) throw err;
        throw new UpstreamUnavailable(0, `network error: ${(err as Error).message}`);
    }
    if (!resp.ok) {
        const detail = await resp.json().catch(() => ({}) as Record<string, unknown>);
        throw new UpstreamUnavailable(resp.status, String(detail.error ?? resp.statusText));
    }
    // The server reports which of ITS tiers answered; surface it so the UI can label a degraded turn.
    const tier = resp.headers.get('x-thox-tier');
    if (tier) cb.onServedTier?.(tier);

    const reader = resp.body?.getReader();
    if (!reader) throw new UpstreamUnavailable(0, 'no response body');
    const decoder = new TextDecoder();
    let full = '', buffer = '';
    for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';
        for (const line of lines) {
            const t = line.trim();
            if (!t.startsWith('data:')) continue;
            const data = t.slice(5).trim();
            if (data === '[DONE]') continue;
            try {
                const delta = JSON.parse(data)?.choices?.[0]?.delta?.content;
                if (delta) {
                    full += delta;
                    cb.onChunk?.(full);
                }
            } catch { /* keep-alive */ }
        }
    }
    if (!full) throw new UpstreamUnavailable(502, 'proxy returned an empty completion');
    return full;
}

// ─── webgpu: fully on-device ───

/**
 * The offline floor. Imported lazily so a deployment that never reaches this tier never pays for
 * the runtime, and so `adapters.ts` stays liftable into surfaces that ship no WebGPU bundle.
 */
async function callWebGPU(
    target: AdapterTarget,
    messages: ChatTurn[],
    cb: AdapterCallbacks,
    opts: AdapterOptions
): Promise<string> {
    let mod: typeof import('./webgpu');
    try {
        mod = await import('./webgpu');
    } catch (err) {
        throw new UpstreamUnavailable(0, `webgpu runtime missing: ${(err as Error).message}`);
    }
    const probe = await mod.probeWebGPU();
    if (!probe.supported) {
        // Not an error the user should see — this browser simply cannot host the tier.
        throw new UpstreamUnavailable(0, `webgpu unsupported (${probe.reason})`);
    }
    if (!mod.isWebGPUModelLoaded() && !target.autoLoad) {
        throw new UpstreamUnavailable(0, 'webgpu model not loaded');
    }
    try {
        return await mod.generateWebGPU(messages, (full) => cb.onChunk?.(full), {
            maxNewTokens: opts.maxTokens,
            signal: opts.signal,
            autoLoad: target.autoLoad,
        });
    } catch (err) {
        if (opts.signal?.aborted) throw err;
        throw new UpstreamUnavailable(0, `webgpu: ${(err as Error).message}`);
    }
}

// ─── dispatch ───

/** Call one backend. Throws `UpstreamUnavailable` when the router should try the next tier. */
export function callAdapter(
    target: AdapterTarget,
    messages: ChatTurn[],
    cb: AdapterCallbacks = {},
    opts: AdapterOptions = {}
): Promise<string> {
    switch (target.type) {
        case 'thoxmythos':
            return callThoxMythos(target, messages, cb, opts);
        case 'openai':
            return callOpenAI(target, messages, cb, opts);
        case 'gradio':
            return callGradio(target, messages, cb, opts);
        case 'proxy':
            return callProxy(target, messages, cb, opts);
        case 'webgpu':
            return callWebGPU(target, messages, cb, opts);
        default:
            return Promise.reject(new Error(`Unknown wire type: ${(target as AdapterTarget).type}`));
    }
}

export interface CascadeResult {
    text: string;
    /** Index in `targets` that actually answered. */
    servedBy: number;
    /** Tiers that were tried and failed, for telemetry and honest UI. */
    failures: { index: number; status: number; message: string }[];
}

/**
 * Try each target in order, cascading past *unavailable* backends only.
 *
 * Two deliberate rules:
 *  - A non-cascadable error (e.g. 400) stops the chain. Retrying a malformed request against a
 *    slower free tier just wastes the user's time and still fails.
 *  - Cascade only happens BEFORE any text has been emitted. Once a tier has streamed a partial
 *    answer, switching backends mid-answer would splice two different models' prose together;
 *    better to fail the turn than to hand back a Frankenstein reply.
 */
export async function cascadeChat(
    targets: AdapterTarget[],
    messages: ChatTurn[],
    cb: AdapterCallbacks = {},
    opts: AdapterOptions = {}
): Promise<CascadeResult> {
    // ─── Identity guard (client side) ───
    // Applies to the DIRECT wire paths. The `proxy` target is already guarded server-side, and
    // double-scrubbing there would be harmless but pointless; the browser cannot be the only
    // enforcement point anyway, since external callers hit the proxy directly.
    const guarded = needsIdentityGuard(opts.modelId);
    if (guarded) {
        messages = withIdentitySystem(messages) as ChatTurn[];
        opts = { ...opts, stop: opts.stop ?? THOXMYTHOS_STOPS };
    }
    const failures: CascadeResult['failures'] = [];
    for (let i = 0; i < targets.length; i++) {
        let emitted = false;
        // Adapters emit the FULL accumulated text, so the scrubber can be applied to the whole
        // string on every tick — no chunk-boundary hazard on this path.
        const wrapped: AdapterCallbacks = {
            onChunk: (t) => {
                emitted = true;
                cb.onChunk?.(guarded ? (applyIdentityFilter(t) as string) : t);
            },
            onServedTier: cb.onServedTier,
        };
        try {
            const text = await callAdapter(targets[i], messages, wrapped, opts);
            return { text, servedBy: i, failures };
        } catch (err) {
            if (opts.signal?.aborted) throw err;
            const status = err instanceof UpstreamUnavailable ? err.status : -1;
            const message = (err as Error).message ?? String(err);
            if (emitted || status === -1 || !isCascadable(status)) throw err;
            failures.push({ index: i, status, message });
        }
    }
    const last = failures[failures.length - 1];
    throw new UpstreamUnavailable(
        last?.status ?? 0,
        `all ${targets.length} tier(s) unavailable${last ? `; last: ${last.message}` : ''}`
    );
}

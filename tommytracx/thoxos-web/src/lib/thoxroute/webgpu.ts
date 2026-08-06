/**
 * In-browser WebGPU tier — the local-first floor of the ThoxRoute cascade.
 *
 * Ported from `ttracx/thox-webby` (ThoxyWeb), which is the reference implementation for running a
 * THOX model fully on-device. The runtime bundle `public/gemma-4-e2b.js` is vendored BYTE-IDENTICAL
 * from that repo (md5 1c04912696ae2f1b1a8861566fc08178); its contract is:
 *
 *     import { Gemma4Mobile } from "/gemma-4-e2b.js";
 *     const model = await Gemma4Mobile.load(null, { onProgress });
 *     for await (const { text } of model.generate(messages, { maxNewTokens, signal })) { … }
 *
 * `generate` yields the FULL accumulated text per step, which is already the shape `onChunk` wants.
 *
 * Why this tier is last: it is the only one that keeps working with no network at all, but it costs
 * the user a ~2 GB first load and needs a real GPU adapter. So it sits BELOW every remote tier and
 * is only reported available once WebGPU has actually been feature-detected — never assumed.
 */

/** Served from public/ — vendored byte-identical from ttracx/thox-webby (ThoxyWeb). */
const RUNTIME_URL = '/gemma-4-e2b.js';

export type WebGPUReason = 'ok' | 'no-webgpu-api' | 'no-adapter' | 'error' | 'not-loaded';

export interface WebGPUProbe {
    supported: boolean;
    reason: WebGPUReason;
    detail?: string;
}

let probeCache: WebGPUProbe | null = null;

/**
 * Feature-detect WebGPU exactly as ThoxyWeb does: `navigator.gpu` must exist AND actually hand
 * back an adapter. The API being present is not enough — Linux/older Chrome expose `navigator.gpu`
 * and then return `null` from requestAdapter(), which would strand a turn on a tier that cannot run.
 */
export async function probeWebGPU(force = false): Promise<WebGPUProbe> {
    if (probeCache && !force) return probeCache;
    const nav = navigator as Navigator & { gpu?: { requestAdapter(): Promise<unknown> } };
    if (!('gpu' in navigator) || !nav.gpu) {
        probeCache = { supported: false, reason: 'no-webgpu-api' };
        return probeCache;
    }
    try {
        const adapter = await nav.gpu.requestAdapter();
        probeCache = adapter
            ? { supported: true, reason: 'ok' }
            : { supported: false, reason: 'no-adapter', detail: 'No usable WebGPU adapter' };
    } catch (err) {
        probeCache = {
            supported: false,
            reason: 'error',
            detail: err instanceof Error ? err.message : String(err),
        };
    }
    return probeCache;
}

interface Gemma4Model {
    generate(
        messages: { role: string; content: string }[],
        opts: { maxNewTokens?: number; signal?: AbortSignal }
    ): AsyncIterable<{ text: string }>;
}

/**
 * The runtime's progress payload — verified live, not guessed: it reports a phase plus, during the
 * weights download, real byte counts. Total observed for Gemma-4 E2B: 2,118,302,910 bytes.
 */
export interface WebGPULoadProgress {
    status: string;
    message?: string;
    kind?: string;
    loaded?: number;
    total?: number;
    fraction?: number;
    fromCache?: boolean;
}

interface Gemma4Ctor {
    load(
        url: string | null,
        opts?: {
            onProgress?: (p: WebGPULoadProgress) => void;
            /** Forwarded to the runtime's WebGPU device creation (see DISABLED_FEATURES). */
            runtimeOptions?: { disabledFeatures?: string[] };
        }
    ): Promise<Gemma4Model>;
}

/**
 * WebGPU device features to refuse when creating the runtime.
 *
 * The runtime picks f16 kernels when the adapter reports `shader-f16`
 * (`qa()` gates `f16Ok`/`f16Allowed` on `device.features.has("shader-f16")`), and
 * `runtimeOptions.disabledFeatures` is filtered out of the requested feature set by `ps()` —
 * so listing it here forces the f32 path.
 *
 * Why this knob exists: the runtime produces fluent-but-incoherent output on some adapters, with
 * no error — the signature of a silent low-precision numerical failure rather than a crash. Set
 * `VITE_THOX_WEBGPU_DISABLED_FEATURES=shader-f16` to test or work around that on a given GPU.
 * Empty by default so the fast path is unchanged where it is correct.
 */
const DISABLED_FEATURES: string[] = (import.meta.env.VITE_THOX_WEBGPU_DISABLED_FEATURES ?? '')
    .split(',')
    .map((s: string) => s.trim())
    .filter(Boolean);

let modelPromise: Promise<Gemma4Model> | null = null;
let loadedModel: Gemma4Model | null = null;

export function isWebGPUModelLoaded(): boolean {
    return loadedModel !== null;
}

/** Progress listeners for the (large) first load, so the UI can show a real bar. */
type ProgressFn = (p: WebGPULoadProgress) => void;
const progressListeners = new Set<ProgressFn>();
export function onWebGPUProgress(fn: ProgressFn): () => void {
    progressListeners.add(fn);
    return () => progressListeners.delete(fn);
}

/**
 * Load the on-device model, once. The bundle is imported lazily and by URL (not bundled by Vite)
 * so the ~540 KB runtime and the ~2 GB weights are never on the critical path of a normal visit —
 * a user who never falls through to this tier never pays for it.
 */
export function loadWebGPUModel(): Promise<Gemma4Model> {
    if (modelPromise) return modelPromise;
    modelPromise = (async () => {
        const probe = await probeWebGPU();
        if (!probe.supported) {
            throw new Error(`WebGPU unavailable (${probe.reason})${probe.detail ? `: ${probe.detail}` : ''}`);
        }
        // Runtime URL import of the vendored bundle in public/. The specifier is a variable on
        // purpose: it keeps the 539 KB runtime out of the app bundle AND out of TS resolution,
        // since public/ assets have no declaration file.
        const runtimeUrl = RUNTIME_URL;
        const mod = (await import(/* @vite-ignore */ runtimeUrl)) as { Gemma4Mobile: Gemma4Ctor };
        const model = await mod.Gemma4Mobile.load(null, {
            onProgress: (p: WebGPULoadProgress) => progressListeners.forEach((fn) => fn(p)),
            ...(DISABLED_FEATURES.length
                ? { runtimeOptions: { disabledFeatures: DISABLED_FEATURES } }
                : {}),
        });
        loadedModel = model;
        return model;
    })();
    modelPromise.catch(() => {
        // Let a failed load be retried rather than poisoning the tier forever.
        modelPromise = null;
    });
    return modelPromise;
}

/**
 * Run a turn fully on-device.
 *
 * `autoLoad` is false by default: silently pulling ~2 GB because a remote Space happened to be
 * down would be a hostile surprise on a phone. The cascade only reaches here automatically once
 * the model is already resident; otherwise the UI offers the download explicitly.
 */
export async function generateWebGPU(
    messages: { role: string; content: string }[],
    onChunk: (fullText: string) => void,
    opts: { maxNewTokens?: number; signal?: AbortSignal; autoLoad?: boolean } = {}
): Promise<string> {
    const model = loadedModel ?? (opts.autoLoad ? await loadWebGPUModel() : null);
    if (!model) throw new Error('WebGPU model is not loaded');
    let full = '';
    for await (const step of model.generate(messages, {
        maxNewTokens: opts.maxNewTokens ?? 4096,
        signal: opts.signal,
    })) {
        full = step.text;
        onChunk(full);
    }
    return full;
}

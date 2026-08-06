import type { ResolvedModel } from './thoxroute/registrySchema';
export interface ProviderModel {
    id: string;
    name: string;
    contextWindow: number;
    maxOutputTokens: number;
    /** OpenAI reasoning effort level — only for GPT-5.2 thinking variants */
    thinkingLevel?: 'low' | 'medium' | 'high' | 'xhigh';
    /**
     * Wire protocol marker.
     *  - `thox-ndjson`: THOX native NDJSON bridge, called directly from the browser (no credential).
     *  - `thox-proxy`:  routed through this Space's /api/v2/thoxroute/chat so a server-held API key
     *                   never reaches the browser.
     */
    protocol?: 'thox-ndjson' | 'thox-proxy';
    /** Base origin for the backend serving this model (used by the THOX tier) */
    origin?: string;
    /** True for models contributed by the ThoxRoute registry rather than hardcoded here. */
    fromRegistry?: boolean;
    /** Ordered free/lower-cost tiers to cascade through when the primary is unavailable. */
    fallbacks?: { origin: string; type: 'thoxmythos' | 'openai' | 'gradio'; tier?: string }[];
    /** Registry audience — `internal` models are usable but flagged in the picker. */
    audience?: 'public' | 'internal' | 'gated';
}

export interface Provider {
    id: string;
    name: string;
    icon: string;
    models: ProviderModel[];
    endpointUrl: string;
    keyPrefix: string;
}

// ─── THOX fleet origins ───
// Read from Vite env with the live deployed backends as defaults.
// ThoxRoute (orchestrator) falls back to the ThoxMythos origin until its own service is live.
const THOXMYTHOS_ORIGIN =
    import.meta.env.VITE_THOXMYTHOS_URL || 'https://thox-ai-thoxmythos-9b-space.hf.space';
const THOXMINI_ORIGIN =
    import.meta.env.VITE_THOXMINI_URL || 'https://tommytracx-thoxmythos-9b-space-cpu.hf.space';
const THOXROUTE_ORIGIN = import.meta.env.VITE_THOXROUTE_URL || THOXMYTHOS_ORIGIN;

export const providers: Provider[] = [
    {
        id: 'thox',
        name: 'THOX',
        icon: '🐝',
        // No browser key: the THOX tier uses a public native stream. endpointUrl points at
        // the orchestrator origin; per-model origins live on each model's `origin` field.
        endpointUrl: THOXROUTE_ORIGIN,
        keyPrefix: '',
        models: [
            { id: 'thoxroute', name: 'ThoxRoute — auto', contextWindow: 32768, maxOutputTokens: 4096, protocol: 'thox-ndjson', origin: THOXROUTE_ORIGIN },
            { id: 'thoxmini-3b', name: 'ThoxMini 3B — fast', contextWindow: 32768, maxOutputTokens: 4096, protocol: 'thox-ndjson', origin: THOXMINI_ORIGIN },
            { id: 'thoxmythos-9b', name: 'ThoxMythos 9B — quality', contextWindow: 32768, maxOutputTokens: 4096, protocol: 'thox-ndjson', origin: THOXMYTHOS_ORIGIN },
        ],
    },
    {
        id: 'openai',
        name: 'OpenAI',
        icon: '🟢',
        endpointUrl: 'https://api.openai.com/v1/chat/completions',
        keyPrefix: 'sk-',
        models: [
            { id: 'gpt-5.2:low', name: 'GPT-5.2 (Low)', contextWindow: 128000, maxOutputTokens: 128000, thinkingLevel: 'low' },
            { id: 'gpt-5.2:medium', name: 'GPT-5.2 (Medium)', contextWindow: 128000, maxOutputTokens: 128000, thinkingLevel: 'medium' },
            { id: 'gpt-5.2:high', name: 'GPT-5.2 (High)', contextWindow: 128000, maxOutputTokens: 128000, thinkingLevel: 'high' },
            { id: 'gpt-5.2:xhigh', name: 'GPT-5.2 (xHigh)', contextWindow: 128000, maxOutputTokens: 128000, thinkingLevel: 'xhigh' },
            { id: 'gpt-5.2-mini', name: 'GPT-5.2 Mini', contextWindow: 128000, maxOutputTokens: 128000 },
        ],
    },
    {
        id: 'anthropic',
        name: 'Anthropic',
        icon: '🟠',
        endpointUrl: 'https://api.anthropic.com/v1/messages',
        keyPrefix: 'sk-ant-',
        models: [
            { id: 'claude-opus-4-6', name: 'Claude 4.6 Opus', contextWindow: 1000000, maxOutputTokens: 128000 },
            { id: 'claude-sonnet-4-5-20250929', name: 'Claude 4.5 Sonnet', contextWindow: 200000, maxOutputTokens: 64000 },
            { id: 'claude-haiku-4-5-20251001', name: 'Claude 4.5 Haiku', contextWindow: 200000, maxOutputTokens: 64000 },
        ],
    },
    {
        id: 'gemini',
        name: 'Google Gemini',
        icon: '🔵',
        endpointUrl: 'https://generativelanguage.googleapis.com/v1beta/models',
        keyPrefix: 'AI',
        models: [
            { id: 'gemini-3-flash-preview', name: 'Gemini 3 Flash', contextWindow: 1000000, maxOutputTokens: 65536 },
            { id: 'gemini-3-pro-preview', name: 'Gemini 3 Pro', contextWindow: 2000000, maxOutputTokens: 65536 },
        ],
    },
    {
        id: 'grok',
        name: 'xAI Grok',
        icon: '⚡',
        endpointUrl: 'https://api.x.ai/v1/chat/completions',
        keyPrefix: 'xai-',
        models: [
            { id: 'grok-4.1-fast', name: 'Grok 4.1 Fast (Reasoning)', contextWindow: 2000000, maxOutputTokens: 131072 },
            { id: 'grok-4.1-fast-no-reasoning', name: 'Grok 4.1 Fast (No Reasoning)', contextWindow: 2000000, maxOutputTokens: 131072 },
        ],
    },
];

const KEYS_PREFIX = 'thoxos_key_';
const ACTIVE_PROVIDER_KEY = 'thoxos_active_provider';
const ACTIVE_MODEL_KEY = 'thoxos_active_model';

export function getApiKey(providerId: string): string {
    return localStorage.getItem(`${KEYS_PREFIX}${providerId}`) || '';
}

export function setApiKey(providerId: string, key: string) {
    if (key) {
        localStorage.setItem(`${KEYS_PREFIX}${providerId}`, key);
    } else {
        localStorage.removeItem(`${KEYS_PREFIX}${providerId}`);
    }
}

export function getActiveProvider(): string {
    return localStorage.getItem(ACTIVE_PROVIDER_KEY) || 'thox';
}

export function setActiveProvider(providerId: string) {
    localStorage.setItem(ACTIVE_PROVIDER_KEY, providerId);
}

export function getActiveModel(): string {
    const stored = localStorage.getItem(ACTIVE_MODEL_KEY) || 'thoxroute';
    // Validate the stored model still exists in current provider list
    const exists = providers.some((p) => p.models.some((m) => m.id === stored));
    if (exists) return stored;
    // Stale model ID — fall back to the first model of the active provider
    const activeProvider = getProvider(getActiveProvider());
    const fallback = activeProvider?.models[0]?.id || 'thoxroute';
    localStorage.setItem(ACTIVE_MODEL_KEY, fallback);
    return fallback;
}

export function setActiveModel(modelId: string) {
    localStorage.setItem(ACTIVE_MODEL_KEY, modelId);
}

export function getProvider(id: string): Provider | undefined {
    return providers.find((p) => p.id === id);
}

export function getProviderForModel(modelId: string): Provider | undefined {
    return providers.find((p) => p.models.some((m) => m.id === modelId));
}

// ─── Voice Provider Settings ───

const STT_PROVIDER_KEY = 'thoxos_stt_provider';
const TTS_PROVIDER_KEY = 'thoxos_tts_provider';
const STT_KEY_PREFIX = 'thoxos_stt_key_';
const TTS_KEY_PREFIX = 'thoxos_tts_key_';

export type STTProvider = 'whisper' | 'elevenlabs-scribe';
export type TTSProvider = 'openai-tts' | 'elevenlabs-tts';

// ─── TTS Voice Options ───

export const openaiVoices = [
    { id: 'alloy', name: 'Alloy' },
    { id: 'ash', name: 'Ash' },
    { id: 'coral', name: 'Coral' },
    { id: 'echo', name: 'Echo' },
    { id: 'fable', name: 'Fable' },
    { id: 'nova', name: 'Nova' },
    { id: 'onyx', name: 'Onyx' },
    { id: 'sage', name: 'Sage' },
    { id: 'shimmer', name: 'Shimmer' },
];

export const elevenLabsVoices = [
    { id: '21m00Tcm4TlvDq8ikWAM', name: 'Rachel' },
    { id: 'wBXNqKUATyqu0RtYt25i', name: 'Adam' },
    { id: 'AZnzlk1XvdvUeBnXmlld', name: 'Domi' },
    { id: 'MF3mGyEYCl7XYWbV9V6O', name: 'Elli' },
    { id: 'TxGEqnHWrfWFTfGW9XjX', name: 'Josh' },
    { id: 'yoZ06aMxZJJ28mfd3POQ', name: 'Sam' },
    { id: 'EXAVITQu4vr4xnSDxMaL', name: 'Bella' },
    { id: 'ErXwobaYiN019PkySvjV', name: 'Antoni' },
];

const TTS_VOICE_KEY = 'thoxos_tts_voice';

export function getTTSVoice(): string {
    return localStorage.getItem(TTS_VOICE_KEY) || '';
}

export function setTTSVoice(voiceId: string) {
    localStorage.setItem(TTS_VOICE_KEY, voiceId);
}

/** Get the effective voice ID for the current TTS provider */
export function getEffectiveTTSVoice(): string {
    const stored = getTTSVoice();
    const provider = getTTSProvider();
    if (provider === 'openai-tts') {
        const valid = openaiVoices.some((v) => v.id === stored);
        return valid ? stored : 'alloy';
    } else {
        const valid = elevenLabsVoices.some((v) => v.id === stored);
        return valid ? stored : 'EXAVITQu4vr4xnSDxMaL';
    }
}

export function getSTTProvider(): STTProvider {
    return (localStorage.getItem(STT_PROVIDER_KEY) as STTProvider) || 'whisper';
}

export function setSTTProvider(provider: STTProvider) {
    localStorage.setItem(STT_PROVIDER_KEY, provider);
}

export function getTTSProvider(): TTSProvider {
    return (localStorage.getItem(TTS_PROVIDER_KEY) as TTSProvider) || 'openai-tts';
}

export function setTTSProvider(provider: TTSProvider) {
    localStorage.setItem(TTS_PROVIDER_KEY, provider);
}

export function getVoiceApiKey(type: 'stt' | 'tts', provider: string): string {
    const prefix = type === 'stt' ? STT_KEY_PREFIX : TTS_KEY_PREFIX;
    return localStorage.getItem(`${prefix}${provider}`) || '';
}

export function setVoiceApiKey(type: 'stt' | 'tts', provider: string, key: string) {
    const prefix = type === 'stt' ? STT_KEY_PREFIX : TTS_KEY_PREFIX;
    if (key) {
        localStorage.setItem(`${prefix}${provider}`, key);
    } else {
        localStorage.removeItem(`${prefix}${provider}`);
    }
}

// ─── Tavily ───

const TAVILY_KEY = 'thoxos_tavily_key';
const WEB_SEARCH_ENABLED = 'thoxos_web_search_enabled';

export function getTavilyApiKey(): string {
    return localStorage.getItem(TAVILY_KEY) || '';
}

export function setTavilyApiKey(key: string) {
    if (key) localStorage.setItem(TAVILY_KEY, key);
    else localStorage.removeItem(TAVILY_KEY);
}

export function getWebSearchEnabled(): boolean {
    return localStorage.getItem(WEB_SEARCH_ENABLED) === 'true';
}

export function setWebSearchEnabled(enabled: boolean) {
    localStorage.setItem(WEB_SEARCH_ENABLED, String(enabled));
}

// ─── ThoxRoute registry integration ───
// The THOX tier's model list is CONFIG-DRIVEN: it is rebuilt at boot from
// /api/v2/thoxroute/status, which resolves models/thoxroute-registry.json against this
// deployment's env. A model whose endpoint goes live later appears here on the next load with no
// code change and no rebuild. The hardcoded entries above are only the fallback for a deployment
// where the status endpoint is unreachable.

/** Models the registry says are servable, mapped onto the picker's shape. */
export function thoxModelsFromRegistry(resolved: ResolvedModel[]): ProviderModel[] {
    const out: ProviderModel[] = [];
    for (const r of resolved) {
        if (!r.available) continue;
        const m = r.model;
        // Browser-local models are served by an in-page runtime, not a URL; they are only listed
        // once that runtime actually exists (status reports `runtime_missing` until then).
        if (m.endpoint.type === 'browser') continue;
        const fbs = r.fallbacks ?? [];
        out.push({
            id: m.id,
            name: m.displayName,
            contextWindow: 32768,
            maxOutputTokens: 4096,
            // A keyed primary must go through the server proxy. A model whose ONLY reachable
            // tier is a credential-free fallback can be called straight from the browser.
            protocol:
                m.endpoint.type === 'openai' && r.baseURL
                    ? 'thox-proxy'
                    : fbs.some((f) => f.hasApiKey)
                      ? 'thox-proxy'
                      : 'thox-ndjson',
            origin: r.baseURL,
            fromRegistry: true,
            audience: m.audience,
            ...(fbs.length
                ? {
                      fallbacks: fbs.map((f) => ({
                          origin: f.baseURL,
                          type: f.type as 'thoxmythos' | 'openai' | 'gradio',
                          tier: f.tier,
                      })),
                  }
                : {}),
        });
    }
    return out;
}

/**
 * Replace the THOX tier's model list with the registry's view, keeping the ThoxRoute "auto" entry
 * pinned first. Called once at boot; safe to call again after a status refresh.
 */
export function applyThoxRouteRegistry(resolved: ResolvedModel[]): void {
    const thox = providers.find((p) => p.id === 'thox');
    if (!thox) return;
    const fresh = thoxModelsFromRegistry(resolved);
    if (fresh.length === 0) return; // nothing live — keep the built-in defaults rather than empty
    const auto = thox.models.find((m) => m.id === 'thoxroute');
    thox.models = auto ? [auto, ...fresh] : fresh;
}

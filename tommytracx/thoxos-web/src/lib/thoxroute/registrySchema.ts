/**
 * ThoxRoute serving-registry types + a light runtime validator.
 *
 * SOURCE OF TRUTH: `src/lib/thoxroute/registrySchema.ts` in ttracx/thoxos-webby-edition, which
 * validates with zod. This is a MIRROR for the Space runtime, which is a browser SPA and does not
 * carry zod. The shapes are deliberately identical so `models/thoxroute-registry.json` stays a
 * single file shared byte-for-byte between the two surfaces.
 *
 * DO NOT widen these types locally. If the registry needs a new field, change it upstream and
 * re-mirror — a divergent copy is worse than a missing field, because both surfaces keep
 * compiling while they disagree about what a model is allowed to do.
 */

export type ThoxCapabilityName = 'tools' | 'vision' | 'reasoning' | 'local';

/** Who may be served this model. `gated` is never selected automatically — only by explicit pin. */
export type ThoxAudience = 'public' | 'internal' | 'gated';

export type ThoxLocality = 'browser' | 'server';

export type ThoxEndpointType = 'openai' | 'thoxmythos' | 'browser' | 'gradio';

/**
 * A lower-cost tier to cascade to when the primary is unavailable (out of credit, paused,
 * rate-limited). It carries its OWN wire `type` because a fallback frequently speaks a different
 * protocol than the primary — a paid NDJSON bridge can fall back to a free Gradio Space.
 *
 * Upstream (`thoxos-webby-edition`) parses the registry with plain `z.object`, which strips
 * unknown keys, so adding this block is additive: that app keeps working untouched and adopts
 * cascading whenever it chooses to read the field.
 */
export interface RegistryFallback {
    type: ThoxEndpointType;
    baseUrlEnv: string;
    apiKeyEnv?: string;
    modelEnv?: string;
    /** Free-form label, e.g. "free-cpu" / "free-zerogpu". Surfaced in the Fleet panel. */
    tier?: string;
    displayName?: string;
    notes?: string;
}

export interface RegistryEndpoint {
    type: ThoxEndpointType;
    /** Name of the env var that holds the base URL. Empty value ⇒ the model is unavailable. */
    baseUrlEnv: string;
    apiKeyEnv?: string;
    modelEnv?: string;
    /**
     * Ordered cascade tiers, best first. Accepts a single object or an array — one model can have
     * several free tiers (e.g. a free GPU Space, then a free CPU Space), and order is the
     * preference: try the GPU before degrading to CPU.
     */
    fallback?: RegistryFallback | RegistryFallback[];
}

export interface RegistryModel {
    id: string;
    displayName: string;
    description?: string;
    endpoint: RegistryEndpoint;
    locality: ThoxLocality;
    audience: ThoxAudience;
    capabilities: Partial<Record<ThoxCapabilityName, boolean>>;
    strengths: Record<string, number>;
    priority: number;
    logo?: string;
    modelUrl?: string;
    notes?: string;
}

export interface RegistryRoute {
    name: string;
    description?: string;
    /** Capabilities a model MUST have to serve this route at all. */
    requires: ThoxCapabilityName[];
    weights: Record<string, number>;
    /**
     * Local-first expressed as data: a per-locality score bonus. A light route biases toward
     * on-device localities so a smaller local model beats a stronger remote one; `hard` sets no
     * bias, so the flagship still wins there.
     */
    localityBias?: Record<string, number>;
}

export interface RegistryClassifier {
    id: string;
    displayName?: string;
    description?: string;
    baseUrlEnv: string;
    apiKeyEnv?: string;
    modelEnv?: string;
}

export interface ThoxRouteRegistry {
    version: string;
    notes?: string[];
    routes: RegistryRoute[];
    models: RegistryModel[];
    classifier?: RegistryClassifier;
}

/** Why a described model cannot take a turn right now. Mirrors the upstream reason union. */
export type UnavailableReason =
    | 'endpoint_unset'
    | 'gated_disabled'
    | 'runtime_missing'
    | 'duplicate_id';

function parseFallbackList(input: unknown): RegistryFallback[] | undefined {
    if (!input) return undefined;
    const arr = Array.isArray(input) ? input : [input];
    const out = arr.map(parseOneFallback).filter((f): f is RegistryFallback => !!f);
    return out.length ? out : undefined;
}

function parseOneFallback(input: unknown): RegistryFallback | undefined {
    const f = input as Record<string, unknown> | undefined;
    if (!f || typeof f !== 'object' || typeof f.baseUrlEnv !== 'string') return undefined;
    return {
        type: (f.type as ThoxEndpointType) ?? 'thoxmythos',
        baseUrlEnv: f.baseUrlEnv,
        apiKeyEnv: typeof f.apiKeyEnv === 'string' ? f.apiKeyEnv : undefined,
        modelEnv: typeof f.modelEnv === 'string' ? f.modelEnv : undefined,
        tier: typeof f.tier === 'string' ? f.tier : undefined,
        displayName: typeof f.displayName === 'string' ? f.displayName : undefined,
        notes: typeof f.notes === 'string' ? f.notes : undefined,
    };
}

/** A resolved fallback tier, ready to call. Never carries a secret to the browser. */
export interface ResolvedFallback {
    type: ThoxEndpointType;
    baseURL: string;
    tier?: string;
    displayName?: string;
    upstreamModelId?: string;
    hasApiKey?: boolean;
}

export interface ResolvedModel {
    model: RegistryModel;
    available: boolean;
    reason?: UnavailableReason;
    /** Empty string when unavailable. Never carries a secret — API keys stay server-side. */
    baseURL: string;
    upstreamModelId: string;
    /**
     * Configured cascade tiers, best first. A model can be servable with NO primary when a
     * fallback resolves — exactly the out-of-credit case — so availability is primary OR fallback.
     */
    fallbacks?: ResolvedFallback[];
}

/**
 * Parse a registry document. Defaults `requires` to `[]` so a route may omit it, exactly as the
 * shared JSON does. Throws on structural damage rather than limping on: a malformed registry is
 * an operator mistake that must be visible, and the caller falls back to the bundled copy.
 */
export function parseRegistry(input: unknown): ThoxRouteRegistry {
    const raw = input as Record<string, unknown>;
    if (!raw || typeof raw !== 'object') throw new Error('registry: not an object');
    if (!Array.isArray(raw.models)) throw new Error('registry: models[] missing');
    if (!Array.isArray(raw.routes)) throw new Error('registry: routes[] missing');

    const routes: RegistryRoute[] = (raw.routes as Record<string, unknown>[]).map((r) => {
        if (typeof r.name !== 'string') throw new Error('registry: route.name missing');
        return {
            name: r.name,
            description: typeof r.description === 'string' ? r.description : undefined,
            requires: Array.isArray(r.requires) ? (r.requires as ThoxCapabilityName[]) : [],
            weights: (r.weights as Record<string, number>) ?? {},
            localityBias: (r.localityBias as Record<string, number>) ?? {},
        };
    });

    const models: RegistryModel[] = (raw.models as Record<string, unknown>[]).map((m) => {
        if (typeof m.id !== 'string') throw new Error('registry: model.id missing');
        const ep = m.endpoint as Record<string, unknown>;
        if (!ep || typeof ep.baseUrlEnv !== 'string') {
            throw new Error(`registry: ${m.id} endpoint.baseUrlEnv missing`);
        }
        return {
            id: m.id,
            displayName: typeof m.displayName === 'string' ? m.displayName : m.id,
            description: typeof m.description === 'string' ? m.description : undefined,
            endpoint: {
                type: (ep.type as ThoxEndpointType) ?? 'openai',
                baseUrlEnv: ep.baseUrlEnv,
                apiKeyEnv: typeof ep.apiKeyEnv === 'string' ? ep.apiKeyEnv : undefined,
                modelEnv: typeof ep.modelEnv === 'string' ? ep.modelEnv : undefined,
                fallback: parseFallbackList(ep.fallback),
            },
            locality: (m.locality as ThoxLocality) ?? 'server',
            audience: (m.audience as ThoxAudience) ?? 'public',
            capabilities: (m.capabilities as Record<ThoxCapabilityName, boolean>) ?? {},
            strengths: (m.strengths as Record<string, number>) ?? {},
            priority: typeof m.priority === 'number' ? m.priority : 0,
            logo: typeof m.logo === 'string' ? m.logo : undefined,
            modelUrl: typeof m.modelUrl === 'string' ? m.modelUrl : undefined,
            notes: typeof m.notes === 'string' ? m.notes : undefined,
        };
    });

    const c = raw.classifier as Record<string, unknown> | undefined;
    return {
        version: typeof raw.version === 'string' ? raw.version : '0',
        notes: Array.isArray(raw.notes) ? (raw.notes as string[]) : undefined,
        routes,
        models,
        classifier:
            c && typeof c.baseUrlEnv === 'string'
                ? {
                      id: (c.id as string) ?? 'thoxroute',
                      displayName: c.displayName as string | undefined,
                      description: c.description as string | undefined,
                      baseUrlEnv: c.baseUrlEnv,
                      apiKeyEnv: c.apiKeyEnv as string | undefined,
                      modelEnv: c.modelEnv as string | undefined,
                  }
                : undefined,
    };
}

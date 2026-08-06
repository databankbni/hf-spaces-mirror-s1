/**
 * ThoxRoute client for the Space runtime.
 *
 * The browser cannot read Space secrets, so availability is resolved SERVER-side by
 * `GET /api/v2/thoxroute/status` (see server.js) and consumed here. That keeps two promises at
 * once: the model list is config-driven (a model goes live the moment its endpoint env var is
 * set, with no rebuild), and no API key ever reaches the client.
 *
 * Selection itself is the shared pure logic in ./select — the same code path as
 * thoxos-webby-edition, so both surfaces answer "which model should take this turn?" identically.
 */
import type { ResolvedModel, RegistryRoute } from './registrySchema';
import { selectRoute, type RouteSignals, type RouteDecision } from './select';

export interface ThoxRouteStatus {
    version: string;
    routes: RegistryRoute[];
    models: (ResolvedModel & { hasApiKey?: boolean })[];
    gatedEnabled: boolean;
    browserReady: boolean;
    classifier: { id: string; configured: boolean } | null;
}

const EMPTY: ThoxRouteStatus = {
    version: '0',
    routes: [],
    models: [],
    gatedEnabled: false,
    browserReady: false,
    classifier: null,
};

let cached: ThoxRouteStatus | null = null;
let inflight: Promise<ThoxRouteStatus> | null = null;

/**
 * Fetch (and memoise) the serving status. A failure degrades to an empty registry rather than
 * throwing: ThoxRoute being unreachable must cost you routing, never the ability to chat with a
 * BYO-key provider.
 */
export async function getThoxRouteStatus(force = false): Promise<ThoxRouteStatus> {
    if (cached && !force) return cached;
    if (inflight && !force) return inflight;
    inflight = fetch('/api/v2/thoxroute/status')
        .then((r) => (r.ok ? r.json() : EMPTY))
        .then((s: ThoxRouteStatus) => {
            // Defensive: `requires` is optional in the registry JSON but the selection logic
            // treats it as an array. Normalise here too so a hand-edited override that skips the
            // server's normalisation can never throw mid-turn.
            cached = {
                ...s,
                routes: (s.routes ?? []).map((r) => ({ ...r, requires: r.requires ?? [] })),
                models: s.models ?? [],
            };
            return cached;
        })
        .catch(() => EMPTY)
        .finally(() => {
            inflight = null;
        });
    return inflight;
}

export function cachedStatus(): ThoxRouteStatus | null {
    return cached;
}

/** Models this deployment can actually serve, best-priority first. */
export function availableModels(status: ThoxRouteStatus): ResolvedModel[] {
    return status.models.filter((m) => m.available);
}

/**
 * Models an operator can see but ThoxRoute will not pick on its own — the uncensored/gated line
 * and anything still waiting on an endpoint. Surfaced so the status panel can explain a gap.
 */
export function unavailableModels(status: ThoxRouteStatus): ResolvedModel[] {
    return status.models.filter((m) => !m.available);
}

export interface ThoxRouteChoice {
    decision: RouteDecision;
    candidates: ResolvedModel[];
    chosen: ResolvedModel | null;
}

/**
 * Pick the best model for a turn. `pinnedModelId` is an explicit user choice and wins over every
 * heuristic — including for gated models, which is the ONLY way one is ever selected.
 */
export function chooseModel(
    status: ThoxRouteStatus,
    signals: RouteSignals,
    pinnedModelId?: string
): ThoxRouteChoice {
    const { decision, candidates } = selectRoute(signals, status.models, status.routes, {
        pinnedModelId,
    });
    return { decision, candidates, chosen: candidates[0] ?? null };
}

/** Heuristic signals for a turn. Kept here so ChatView does not grow routing knowledge. */
export function buildSignals(
    prompt: string,
    turnCount: number,
    opts: { hasImageInput?: boolean; hasToolsActive?: boolean; requirePrivate?: boolean } = {}
): RouteSignals {
    return {
        prompt,
        turnCount,
        hasImageInput: !!opts.hasImageInput,
        hasToolsActive: !!opts.hasToolsActive,
        requirePrivate: !!opts.requirePrivate,
    };
}

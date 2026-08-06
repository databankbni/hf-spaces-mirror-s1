/**
 * ThoxRoute best-model selection.
 *
 * Everything here is pure: signals in, an ordered candidate list out. No fetches, no config
 * reads, no clock. That is what makes "which model should answer this?" a testable question
 * rather than a behaviour you can only observe in production.
 *
 * ISOMORPHIC ON PURPOSE. This module lives outside `$lib/server` because two hosts run it: the
 * SvelteKit server (`server/thoxroute/endpoint.ts`) and the standalone browser app
 * (`standalone/`), which has no server at all. One routing brain, two hosts — a second
 * client-side implementation would drift, and "which model answered, and why?" would depend on
 * which build you happened to be looking at.
 *
 * Two stages, deliberately separate:
 *  1. `classifyRoute` — what KIND of request is this? Local heuristics today; the ThoxRoute
 *     classifier model can override this upstream without touching stage 2.
 *  2. `rankCandidates` — given a route, which available models can serve it, best first?
 *     Ranking reads the registry's declared strengths, so a model that ships later competes
 *     on its own description instead of needing to be inserted into a hand-ordered list.
 */
import type { RegistryRoute, ResolvedModel, ThoxCapabilityName } from "./registrySchema";

export const ROUTE_QUICK = "quick";
export const ROUTE_GENERAL = "general";
export const ROUTE_CODE = "code";
export const ROUTE_HARD = "hard";
export const ROUTE_MULTIMODAL = "multimodal";
export const ROUTE_AGENTIC = "agentic";
export const ROUTE_PRIVATE = "private";

export interface RouteSignals {
	/** The user's latest turn, plain text. */
	prompt: string;
	/** Number of prior turns in the conversation. */
	turnCount: number;
	hasImageInput: boolean;
	hasToolsActive: boolean;
	/** The user asked for this turn to stay on-device. */
	requirePrivate: boolean;
}

export interface RouteDecision {
	route: string;
	/** Short, human-readable justification. Surfaced to operators, not to end users. */
	rationale: string;
}

/** Fenced blocks, import/def/function keywords, shell prompts, file paths with code extensions. */
const CODE_PATTERNS = [
	/```/,
	/\b(?:function|const|let|var|class|def|import|export|async|await|return)\s/,
	/\b(?:npm|pnpm|yarn|cargo|pip|git)\s+\w+/,
	/\.(?:ts|tsx|js|jsx|py|rs|go|java|rb|c|cpp|h|sh|sql|svelte)\b/,
	/\b(?:stack ?trace|traceback|compile error|type ?error|segfault)\b/i,
];

/** Multi-step / analytical asks that reward the strongest model. */
const HARD_PATTERNS = [
	/\b(?:step[- ]by[- ]step|compare|trade[- ]?offs?|analyse|analyze|derive|prove|architect|design a|migration plan|root cause)\b/i,
	/\b(?:why does|how would you|what are the implications)\b/i,
];

const QUICK_MAX_CHARS = 120;
const HARD_MIN_CHARS = 600;

export function classifyRoute(signals: RouteSignals): RouteDecision {
	// Ordered by how strongly the signal constrains the answer. Privacy comes before every
	// quality consideration: a turn the user marked on-device cannot be improved by a better
	// remote model, because sending it is the failure.
	if (signals.requirePrivate) {
		return { route: ROUTE_PRIVATE, rationale: "user requested an on-device turn" };
	}
	if (signals.hasImageInput) {
		return { route: ROUTE_MULTIMODAL, rationale: "request carries image input" };
	}
	if (signals.hasToolsActive) {
		return { route: ROUTE_AGENTIC, rationale: "tools/MCP servers are active" };
	}

	const prompt = signals.prompt ?? "";
	const trimmed = prompt.trim();

	if (CODE_PATTERNS.some((re) => re.test(prompt))) {
		return { route: ROUTE_CODE, rationale: "code markers in the prompt" };
	}
	if (trimmed.length >= HARD_MIN_CHARS || HARD_PATTERNS.some((re) => re.test(prompt))) {
		return { route: ROUTE_HARD, rationale: "long or multi-step analytical request" };
	}
	// A short opener is a quick turn; a short follow-up deep into a conversation usually is not,
	// because the real context is the history the short message refers to.
	if (trimmed.length <= QUICK_MAX_CHARS && signals.turnCount <= 2) {
		return { route: ROUTE_QUICK, rationale: "short opening turn" };
	}
	return { route: ROUTE_GENERAL, rationale: "no specialised signal" };
}

function hasCapability(resolved: ResolvedModel, capability: string): boolean {
	const caps = resolved.model.capabilities as Record<string, boolean | undefined>;
	return caps[capability as ThoxCapabilityName] === true;
}

export function scoreModel(resolved: ResolvedModel, route: RegistryRoute): number {
	let score = 0;
	// `?? {}` for the same reason as `requires` in rankCandidates: routes reach this function from
	// zod-parsed config on the server and from raw bundled JSON in the browser.
	for (const [strength, weight] of Object.entries(route.weights ?? {})) {
		score += (resolved.model.strengths?.[strength] ?? 0) * weight;
	}
	// Local-first, expressed as data. A light route biases toward on-device localities so a
	// smaller local model beats a stronger remote one; `hard` sets no bias, so the flagship still
	// wins there even though it is remote. See registryRouteSchema.localityBias.
	// Optional-chained: zod fills this in on parse, but the standalone app also builds routes from
	// runtime config, and a missing bias should cost you the preference, not throw mid-turn.
	score += route.localityBias?.[resolved.model.locality] ?? 0;
	// Priority is a tie-break, not a thumb on the scale: /100 keeps it below one strength point.
	return score + resolved.model.priority / 100;
}

export interface RankOptions {
	/** An explicit user pick. Honoured ahead of every heuristic, including for gated models. */
	pinnedModelId?: string;
}

/**
 * Ordered candidates for a route, best first.
 *
 * Gated models are excluded from automatic ranking unconditionally — being switched on by the
 * operator makes them *selectable*, never *selected*. The only way one answers is `pinnedModelId`.
 */
export function rankCandidates(
	routeName: string,
	resolved: ResolvedModel[],
	routes: RegistryRoute[],
	opts: RankOptions = {}
): ResolvedModel[] {
	const usable = resolved.filter((r) => r.available);

	if (opts.pinnedModelId) {
		const pinned = usable.find((r) => r.model.id === opts.pinnedModelId);
		if (pinned) {
			return [pinned, ...rankCandidates(routeName, resolved, routes).filter((r) => r !== pinned)];
		}
	}

	const autoEligible = usable.filter((r) => r.model.audience !== "gated");
	const route = routes.find((r) => r.name === routeName);

	// `requires` is defaulted by zod on the server path, but the standalone app hands us routes
	// straight from bundled JSON where an omitted key really is undefined. Treating that as "no
	// requirements" is both correct and the only safe reading — the alternative is a throw in the
	// middle of routing a live turn.
	const requires = route?.requires ?? [];

	const forRoute = route
		? autoEligible.filter((r) => requires.every((cap) => hasCapability(r, cap)))
		: autoEligible;

	const ranked = route
		? [...forRoute].sort((a, b) => scoreModel(b, route) - scoreModel(a, route))
		: [...forRoute].sort((a, b) => b.model.priority - a.model.priority);

	// Everything else, by priority, as the tail of the fallback chain. A route with a hard
	// `requires` (multimodal, private) deliberately keeps this tail: if no model can satisfy the
	// requirement, answering with a model that cannot is worse than the caller seeing an empty
	// candidate list, so requires-routes return only their qualified set.
	if (route && requires.length > 0) return ranked;

	const rest = autoEligible
		.filter((r) => !ranked.includes(r))
		.sort((a, b) => b.model.priority - a.model.priority);

	return [...ranked, ...rest];
}

/** Convenience: classify then rank in one call. */
export function selectRoute(
	signals: RouteSignals,
	resolved: ResolvedModel[],
	routes: RegistryRoute[],
	opts: RankOptions = {}
): { decision: RouteDecision; candidates: ResolvedModel[] } {
	const decision = classifyRoute(signals);
	let candidates = rankCandidates(decision.route, resolved, routes, opts);

	// A requires-route with nothing to serve it degrades to `general` rather than failing the
	// turn — except `private`, where degrading would cross the boundary the route exists to hold.
	if (candidates.length === 0 && decision.route !== ROUTE_PRIVATE) {
		candidates = rankCandidates(ROUTE_GENERAL, resolved, routes, opts);
		return {
			decision: {
				route: ROUTE_GENERAL,
				rationale: `${decision.route} had no available model; fell back to general`,
			},
			candidates,
		};
	}

	return { decision, candidates };
}

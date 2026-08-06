// Session-scoped cache of simulation results so the matchups grid and the
// game-detail page share one run per game (mirrors MrSim's persisted sims).
import { api, type SimResult, type SimulateOptions } from './api';

// Bump this whenever SimResult gains a field the UI renders. A cached run
// from an older shape would otherwise be shown against the new columns and
// display NaN — which is exactly what a stale `pitches`-less sim did.
const KEY = 'thebeast-sims-v2';

let mem: Record<string, SimResult> = {};
let stampMem: Record<string, string> = {};

function load(): void {
	if (typeof sessionStorage === 'undefined') return;
	try {
		const raw = sessionStorage.getItem(KEY);
		if (raw) {
			const parsed = JSON.parse(raw);
			mem = parsed.sims ?? {};
			stampMem = parsed.stamps ?? {};
		}
	} catch {
		/* corrupted cache — start fresh */
	}
}

function save(): void {
	if (typeof sessionStorage === 'undefined') return;
	try {
		sessionStorage.setItem(KEY, JSON.stringify({ sims: mem, stamps: stampMem }));
	} catch {
		/* storage full — cache stays in-memory only */
	}
}

load();

export function getSim(gameId: string): SimResult | null {
	return mem[gameId] ?? null;
}

export function getStamp(gameId: string): string | null {
	return stampMem[gameId] ?? null;
}

export function putSim(gameId: string, result: SimResult): void {
	mem[gameId] = result;
	stampMem[gameId] = new Date().toISOString();
	save();
}

/** Forget these games' results so the next `ensureSim` re-fetches them.
 *
 * Paired with a server-side re-run. Dropping the server's runs while this copy
 * survived would leave the page showing the old numbers indefinitely — it never
 * asks again for a game it already has. */
export function clearSims(gameIds: string[]): void {
	for (const id of gameIds) {
		delete mem[id];
		delete stampMem[id];
	}
	save();
}

/** Simulate (or return the cached run) for one game. */
export async function ensureSim(
	gameId: string,
	opts: Partial<SimulateOptions> = {},
	force = false
): Promise<SimResult> {
	if (!force) {
		const hit = getSim(gameId);
		if (hit) return hit;
	}
	const result = await api.simulate({ game_id: gameId, n: opts.n ?? 2000, seed: opts.seed ?? 7, ...opts });
	putSim(gameId, result);
	return result;
}

// In-memory cache of simulation results, so the matchups grid and the
// game-detail page share one run per game across a navigation.
//
// It used to persist to sessionStorage, and that was the more expensive half of
// a bug. The server holds the authoritative runs and answers from them in about
// 30ms; a browser copy that outlives the page adds nothing to that but a way to
// disagree with it. It did: after a container restart the tab still had every
// result and never asked for one, so the page looked fully simulated while the
// server held nothing — which is how the assistant ended up with no cached run
// to read and simulated games itself.
//
// What survives is the part that was actually earning its keep: not re-fetching
// fifteen games when you click into a matchup and back out. That wants one page
// session, which is what a module-level object already is. A reload now always
// re-reads the server, so the two can no longer drift apart.
import { api, type SimResult, type SimulateOptions } from './api';

let mem: Record<string, SimResult> = {};
let stampMem: Record<string, string> = {};

export function getSim(gameId: string): SimResult | null {
	return mem[gameId] ?? null;
}

export function getStamp(gameId: string): string | null {
	return stampMem[gameId] ?? null;
}

export function putSim(gameId: string, result: SimResult): void {
	mem[gameId] = result;
	stampMem[gameId] = new Date().toISOString();
}

/** Forget these games' results so the next `ensureSim` re-fetches them.
 *
 * Paired with a server-side re-run, and with a lineup landing: the server
 * re-simulates that game itself, and this is what makes the page go and look. */
export function clearSims(gameIds: string[]): void {
	for (const id of gameIds) {
		delete mem[id];
		delete stampMem[id];
	}
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
	const result = await api.simulate({
		game_id: gameId,
		n: opts.n ?? 2000,
		seed: opts.seed ?? 7,
		...opts
	});
	putSim(gameId, result);
	return result;
}

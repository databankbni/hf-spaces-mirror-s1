import type { GameSchedule } from './api';

/** Human-readable game state: "LIVE · Bot 6", "FINAL", or the scheduled start time. */
export function statusLabel(
	g: Pick<GameSchedule, 'status' | 'inning' | 'inning_half' | 'first_pitch'>
): string {
	if (g.status === 'Live') {
		const half = g.inning_half === 'Top' ? 'Top' : g.inning_half === 'Bottom' ? 'Bot' : '';
		return g.inning ? `LIVE · ${half} ${g.inning}` : 'LIVE';
	}
	if (g.status === 'Final') return 'FINAL';
	if (g.first_pitch) {
		return new Date(g.first_pitch).toLocaleTimeString(undefined, {
			hour: 'numeric',
			minute: '2-digit'
		});
	}
	return '';
}

/** Whether a game is over. MLB uses several terminal states, not just "Final",
 *  and the pregame poll needs to know when to stop — checking only for "Final"
 *  would leave it polling a suspended slate all night. */
export function isFinal(status: string | null | undefined): boolean {
	const s = (status ?? '').toLowerCase();
	return s === 'final' || s === 'game over' || s === 'completed early';
}

/** For a doubleheader's 2nd+ game the id carries a "-g{N}" suffix. Returns
 *  that game number (2, 3, …) or null for a single game / DH game 1. */
export function doubleheaderGame(gameId: string): number | null {
	const m = gameId.match(/-g(\d+)$/);
	return m ? Number(m[1]) : null;
}

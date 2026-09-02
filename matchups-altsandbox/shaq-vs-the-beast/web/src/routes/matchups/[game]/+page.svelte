<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import {
		api,
		type SimResult,
		type BettingEdge,
		type TeamAggregate,
		type PlayerLine,
		type PitcherLine,
		type PlayLogEntry,
		type GameAccuracy,
		type LiveSim,
		type GameSchedule,
		type GameLinescore,
		type GameBoxscore,
		type TeamBoxscore,
		type BatterBoxLine,
		type NextAtBat
	} from '$lib/api';
	import { ensureSim } from '$lib/simstore';
	import { statusLabel, doubleheaderGame } from '$lib/gameStatus';
	import TeamLogo from '$lib/TeamLogo.svelte';
	import PlayerPhoto from '$lib/PlayerPhoto.svelte';
	import StatEditor from '$lib/StatEditor.svelte';
	import DistChart from '$lib/DistChart.svelte';
	import { teamName, teamVenue } from '$lib/teams';

	const gameId = $derived($page.params.game ?? '');

	// game_id convention: YYYY-MM-DD-AWAY-HOME
	const parsed = $derived.by(() => {
		const parts = gameId.split('-');
		if (parts.length >= 5) {
			return {
				date: parts.slice(0, 3).join('-'),
				away: parts[3],
				home: parts[4]
			};
		}
		return { date: '', away: '', home: '' };
	});

	let result = $state<SimResult | null>(null);
	// The unconditioned projection stays here so the score steppers keep their
	// default and "reset to projection" can restore it after a conditioned run.
	let baseResult = $state<SimResult | null>(null);
	// The first, un-edited projection — the stable reference edits multiply
	// against, so repeated edit-runs never compound.
	let originalResult = $state<SimResult | null>(null);
	let conditioning = $state(false);
	let conditionError = $state('');

	// Per-batter what-if edits: player_id → { hits?, home_runs?, bb?, k? } as the
	// raw strings the user typed (parsed to multipliers at run time).
	let edits = $state<Record<string, Record<string, string>>>({});
	let editRunning = $state(false);
	let editError = $state('');
	const EDIT_STATS = ['hits', 'home_runs', 'bb', 'k'] as const;
	// Per-pitcher what-if edits, same shape as `edits` but keyed by pitcher id.
	let pitcherEdits = $state<Record<string, Record<string, string>>>({});
	const PITCHER_EDIT_STATS = ['hits_allowed', 'hr_allowed', 'bb_allowed', 'k'] as const;
	const hasEdits = $derived(
		Object.values(edits).some((s) => Object.values(s).some((v) => v.trim() !== '')) ||
			Object.values(pitcherEdits).some((s) => Object.values(s).some((v) => v.trim() !== ''))
	);
	let loading = $state(true);
	let simRunning = $state(false);
	let error = $state('');
	let mode = $state<'live' | 'preview' | 'prediction'>('preview');
	let userPickedMode = false;
	let jumpOpen = $state(false);

	// Preview data
	let teamstats = $state<TeamAggregate[]>([]);

	// Real sportsbook lines (hero display + defaults for the edge analyzer below)

	// Post-game accuracy (sim vs. actual) — loaded once a game is Final.
	let accuracy = $state<GameAccuracy | null>(null);
	let accuracyLoading = $state(false);
	let accuracyError = $state('');
	let accuracyRequested = false;

	// Live sim: simulation of the rest of an in-progress game, run on demand.
	let liveSim = $state<LiveSim | null>(null);
	let liveSimRunning = $state(false);
	let liveSimError = $state('');
	let liveSimAt = $state<Date | null>(null);
	// Re-runs itself on the live poll while on, so the projection tracks the game.
	let liveSimAuto = $state(false);

	async function runLiveSim() {
		if (liveSimRunning) return;
		liveSimRunning = true;
		liveSimError = '';
		try {
			liveSim = await api.liveSim(gameId);
			liveSimAt = new Date();
		} catch (e) {
			liveSimError = String(e);
		} finally {
			liveSimRunning = false;
		}
	}

	// The pitch-by-pitch forecast for the at-bat that hasn't started yet.
	// Refreshed on the same poll as everything else in the live area, because
	// the hitter it's about changes the moment the current one is out.
	let nextAtBat = $state<NextAtBat | null>(null);
	let nextAtBatLoading = $state(true);
	// Its own timer, faster than the rest of the live area. The count moves
	// between pitches, so a twenty-second refresh is stale for most of its
	// life; the box score and the score line change far more slowly and would
	// be wasted work at this rate. The server caches the payload for two
	// seconds, so polling this hard costs one call to MLB every couple of
	// seconds however many people are watching.
	const AT_BAT_POLL_MS = 4_000;
	let atBatTimer: ReturnType<typeof setTimeout> | null = null;
	let atBatGen = 0;

	async function refreshAtBat() {
		const gen = ++atBatGen;
		try {
			const n = await api.nextAtBat(gameId);
			// A slow response must never overwrite a fresher one — at four
			// seconds a request can easily still be in flight when the next
			// fires, and out-of-order writes would show a count that has
			// already moved on.
			if (gen === atBatGen) nextAtBat = n;
		} catch (e) {
			console.warn('next-at-bat fetch failed', e);
		} finally {
			if (gen === atBatGen) nextAtBatLoading = false;
		}
	}

	function scheduleAtBatPoll() {
		stopAtBatPoll();
		if (liveGame?.status !== 'Live') return;
		atBatTimer = setTimeout(async () => {
			await refreshAtBat();
			scheduleAtBatPoll();
		}, AT_BAT_POLL_MS);
	}

	function stopAtBatPoll() {
		if (atBatTimer !== null) {
			clearTimeout(atBatTimer);
			atBatTimer = null;
		}
	}

	// Live game state (score/inning/status) — polled while the game is in progress.
	let liveGame = $state<GameSchedule | null>(null);
	let linescore = $state<GameLinescore | null>(null);
	let linescoreLoading = $state(true);
	let boxscore = $state<GameBoxscore | null>(null);
	let livePollTimer: ReturnType<typeof setTimeout> | null = null;

	// "Live" while in progress, "Game Recap" once final; hidden for games that
	// haven't started (Preview) or never got live data (odds/API unreachable).
	const liveTabLabel = $derived(
		liveGame?.status === 'Live' ? 'Live' : liveGame?.status === 'Final' ? 'Game Recap' : ''
	);

	interface RealLeader {
		cat: string;
		player: BatterBoxLine;
		main: string;
		sub: string;
	}
	function realLeadersFor(team: TeamBoxscore | undefined): RealLeader[] {
		if (!team || !team.batters.length) return [];
		const by = (key: keyof BatterBoxLine) =>
			[...team.batters].sort((a, b) => ((b[key] as number) ?? 0) - ((a[key] as number) ?? 0))[0];
		const out: RealLeader[] = [];
		const hits = by('hits');
		if (hits && (hits.hits ?? 0) > 0)
			out.push({ cat: 'Hits', player: hits, main: `${hits.hits} H`, sub: `${hits.at_bats ?? 0} AB` });
		const hr = by('home_runs');
		if (hr && (hr.home_runs ?? 0) > 0)
			out.push({ cat: 'Home Runs', player: hr, main: `${hr.home_runs} HR`, sub: `${hr.rbi ?? 0} RBI` });
		const rbi = by('rbi');
		if (rbi && (rbi.rbi ?? 0) > 0 && !out.some((l) => l.player.name === rbi.name && l.cat === 'Home Runs'))
			out.push({ cat: 'RBI', player: rbi, main: `${rbi.rbi} RBI`, sub: `${rbi.hits ?? 0} H` });
		return out;
	}
	const awayLeaders = $derived(realLeadersFor(boxscore?.away));
	const homeLeaders = $derived(realLeadersFor(boxscore?.home));

	// Betting
	let homeMl = $state(-120);
	let awayMl = $state(100);
	let totalLine = $state(8.5);
	let kelly = $state(0.25);
	let edges = $state<BettingEdge[]>([]);
	let betting = $state(false);

	// Box score (simulated, Prediction tab)
	let boxTeam = $state<'away' | 'home'>('away');

	// User-adjusted final score (Prediction tab "what-if"): null until the
	// user touches a stepper, so the box score shows the pure projection
	// until then. Once set, the box score + leaders rescale to this final.
	let customAway = $state<number | null>(null);
	let customHome = $state<number | null>(null);

	// Box score (real, Live/Game Recap tab)
	let liveBoxTeam = $state<'away' | 'home'>('away');

	// Distributions
	let distPick = $state<'totals' | 'home_runs' | 'away_runs'>('totals');

	onMount(async () => {
		// Opening the page runs the simulation automatically — ensureSim
		// returns the cached result instantly if one already exists for this
		// game, so this only costs a real Monte Carlo run the first time.
		try {
			const [sim, stats] = await Promise.all([
				ensureSim(gameId, { n: 2000 }),
				api.teamstats().catch(() => [] as TeamAggregate[])
			]);
			result = sim;
			baseResult = sim;
			originalResult = sim;
			teamstats = stats;
		} catch (e) {
			error = String(e);
		} finally {
			loading = false;
		}
		// Live score/status — also best-effort. Poll only while the game is
		// actually in progress; stop once it's final (or never was live).
		await refreshLiveGame();
		// A finished game can be scored against what actually happened.
		if (liveGame?.status === 'Final') loadAccuracy();
		// Default to the Live/Game Recap tab when there's actually something
		// to show there — but only on this first load, and only if the user
		// hasn't already clicked a tab themselves in the meantime.
		if (!userPickedMode && liveTabLabel) mode = 'live';
		scheduleLivePoll();
	});

	onDestroy(() => {
		stopLivePolling();
		// A four-second timer left running after navigation is the kind of
		// thing that quietly polls forever in a background tab.
		stopAtBatPoll();
	});

	// Keeps watching before first pitch, not only during the game. The old
	// version stopped the moment it saw a game that wasn't already Live, so a
	// page opened pregame never noticed first pitch — it sat on Preview until
	// someone reloaded it, and the Live tab it should have grown never appeared.
	function scheduleLivePoll() {
		stopLivePolling();
		if (liveGame?.status === 'Final') return;
		// Twenty seconds in-game so the score keeps up; a minute before it
		// starts, where the only thing that can change is that it has.
		const wait = liveGame?.status === 'Live' ? 20_000 : 60_000;
		livePollTimer = setTimeout(async () => {
			const wasFinal = liveGame?.status === 'Final';
			await refreshLiveGame();
			// The moment it goes final it can be graded against what happened.
			if (!wasFinal && liveGame?.status === 'Final') loadAccuracy();
			scheduleLivePoll();
		}, wait);
	}

	function stopLivePolling() {
		if (livePollTimer !== null) {
			clearTimeout(livePollTimer);
			livePollTimer = null;
		}
	}

	function pickMode(m: 'live' | 'preview' | 'prediction') {
		userPickedMode = true;
		mode = m;
	}

	// Bumped at the start of every refresh; a response only gets to write
	// state if it's still the most recent request in flight. Without this, a
	// poll tick that happens to take longer than the 20s interval (a slow
	// linescore/boxscore call, say) can resolve *after* a later tick and
	// clobber fresher data with stale odds/scores — which looks exactly like
	// "the odds aren't updating".
	let livePollGen = 0;

	async function refreshLiveGame() {
		const gen = ++livePollGen;
		let game;
		try {
			game = await api.game(gameId);
		} catch (e) {
			console.warn('live game fetch failed', e);
			return;
		}
		if (gen !== livePollGen) return; // superseded by a newer tick
		liveGame = game;

		// Box score/situation only exist once the game has a real gamePk
		// (i.e. it's actually started or finished) — skip the extra calls
		// for games that are still just "Preview". Fetched concurrently and
		// independently so one slow/failing call (e.g. boxscore) never
		// blocks or delays the others — in particular, odds must not sit
		// behind linescore+boxscore in a serial chain.
		if (game.status === 'Live' || game.status === 'Final') {
			const tasks: Promise<void>[] = [
				api
					.linescore(gameId)
					.then((ls) => {
						if (gen === livePollGen) linescore = ls;
					})
					.catch((e) => console.warn('linescore fetch failed', e))
					.finally(() => {
						if (gen === livePollGen) linescoreLoading = false;
					}),
				api
					.boxscore(gameId)
					.then((bx) => {
						if (gen === livePollGen) boxscore = bx;
					})
					.catch((e) => console.warn('boxscore fetch failed', e))
			];
			// The at-bat forecast runs on its own faster timer rather than
			// riding this one — see `scheduleAtBatPoll`. Kicked here so it
			// starts the moment the game is known to be live, and so a game
			// that goes live mid-session picks it up.
			if (game.status === 'Live' && atBatTimer === null) {
				refreshAtBat();
				scheduleAtBatPoll();
			} else if (game.status !== 'Live') {
				stopAtBatPoll();
			}
			await Promise.all(tasks);
			// Keep the live projection tracking the game when auto-run is on.
			if (game.status === 'Live' && liveSimAuto && !liveSimRunning) runLiveSim();
			// Once the game goes final, score the prediction against reality.
			if (game.status === 'Final') loadAccuracy();
		} else {
			linescoreLoading = false;
		}
	}

	// Fetch the post-game accuracy comparison once (it runs two sims server-side,
	// so it's deliberately one-shot per finished game, not polled).
	async function loadAccuracy() {
		if (accuracyRequested) return;
		accuracyRequested = true;
		accuracyLoading = true;
		accuracyError = '';
		try {
			accuracy = await api.accuracy(gameId);
		} catch (e) {
			accuracyError = String(e);
			accuracyRequested = false; // allow a retry after a transient failure
		} finally {
			accuracyLoading = false;
		}
	}

	async function runSimulation() {
		simRunning = true;
		error = '';
		try {
			result = await ensureSim(gameId, { n: 2000 }, true);
			baseResult = result;
			originalResult = result;
			edits = {};
			pitcherEdits = {};
			customAway = null;
			customHome = null;
			conditionError = '';
			editError = '';
		} catch (e) {
			error = String(e);
		} finally {
			simRunning = false;
		}
	}

	// ── Per-batter what-if edits ───────────────────────────────────────────────
	function cellValue(p: PlayerLine, stat: string): string {
		const e = edits[String(p.player_id)]?.[stat];
		if (e !== undefined) return e;
		return ((p[stat] as number) ?? 0).toFixed(2);
	}
	function isEdited(pid: number, stat: string): boolean {
		const v = edits[String(pid)]?.[stat];
		return v !== undefined && v.trim() !== '';
	}
	function setEdit(pid: number, stat: string, raw: string) {
		// Store the raw string as-typed, including an empty string. Keeping the
		// blank (rather than dropping the entry) lets a user clear the whole cell
		// and type a fresh value — otherwise cellValue would immediately snap the
		// projected number back in and the field could never go empty.
		const key = String(pid);
		const forPlayer = { ...(edits[key] ?? {}), [stat]: raw };
		edits = { ...edits, [key]: forPlayer };
	}
	// On blur, drop a cell the user left blank so it falls back to the projected
	// value instead of lingering empty (a blank is treated as "no edit" anyway).
	function commitEdit(pid: number, stat: string) {
		const key = String(pid);
		const cur = edits[key]?.[stat];
		if (cur === undefined || cur.trim() !== '') return;
		const forPlayer = { ...(edits[key] ?? {}) };
		delete forPlayer[stat];
		const next = { ...edits };
		if (Object.keys(forPlayer).length) next[key] = forPlayer;
		else delete next[key];
		edits = next;
	}
	function clearEdits() {
		edits = {};
		pitcherEdits = {};
		editError = '';
		if (originalResult) {
			baseResult = originalResult;
			result = originalResult;
			customAway = null;
			customHome = null;
			conditionError = '';
		}
	}

	// Turn the typed edits into per-batter rate multipliers relative to the
	// original (un-edited) projection.
	// ── Per-pitcher what-if edits ──────────────────────────────────────────────
	// The league-average placeholder starter is shared by both teams (id 0), so
	// an edit to it would silently change the opposing starter too. Real
	// pitchers and each team's bullpen aggregate (a negative, team-specific id)
	// are safe to edit.
	function pitcherEditable(p: PitcherLine): boolean {
		return p.player_id !== 0;
	}
	function pitcherCellValue(p: PitcherLine, stat: string): string {
		const e = pitcherEdits[String(p.player_id)]?.[stat];
		if (e !== undefined) return e;
		return ((p[stat] as number) ?? 0).toFixed(2);
	}
	function isPitcherEdited(pid: number, stat: string): boolean {
		const v = pitcherEdits[String(pid)]?.[stat];
		return v !== undefined && v.trim() !== '';
	}
	function setPitcherEdit(pid: number, stat: string, raw: string) {
		const key = String(pid);
		pitcherEdits = { ...pitcherEdits, [key]: { ...(pitcherEdits[key] ?? {}), [stat]: raw } };
	}
	function commitPitcherEdit(pid: number, stat: string) {
		// Drop a cell left blank so it falls back to the projected number.
		const key = String(pid);
		const forPitcher = pitcherEdits[key];
		if (!forPitcher || (forPitcher[stat] ?? '').trim() !== '') return;
		const { [stat]: _drop, ...rest } = forPitcher;
		const next = { ...pitcherEdits };
		if (Object.keys(rest).length) next[key] = rest;
		else delete next[key];
		pitcherEdits = next;
	}

	// Turn typed pitcher targets into rate multipliers, same approach as the
	// batter version: divide the target by the unedited projection.
	function buildPitcherOverrides(): Record<string, Record<string, number>> | undefined {
		if (!originalResult?.pitcher_lines) return undefined;
		const clamp = (v: number) => Math.min(10, Math.max(0, v));
		const out: Record<string, Record<string, number>> = {};
		for (const [pidStr, stats] of Object.entries(pitcherEdits)) {
			const base = originalResult.pitcher_lines.find((p) => String(p.player_id) === pidStr);
			if (!base) continue;
			const m: Record<string, number> = {};
			for (const [stat, rawVal] of Object.entries(stats)) {
				const target = parseFloat(rawVal);
				if (!isFinite(target)) continue;
				if (stat === 'hr_allowed') m.hr_allowed = clamp(target / Math.max(base.hr_allowed, 0.01));
				else if (stat === 'bb_allowed') m.bb_allowed = clamp(target / Math.max(base.bb_allowed, 0.01));
				else if (stat === 'k') m.k = clamp(target / Math.max(base.k, 0.01));
				else if (stat === 'hits_allowed') {
					// "hits_allowed" scales non-HR hits; back out the HR share so the
					// H column lands near the typed target.
					const baseNonHr = Math.max(base.hits_allowed - base.hr_allowed, 0.05);
					const tgtNonHr = Math.max(target - base.hr_allowed, 0);
					m.hits_allowed = clamp(tgtNonHr / baseNonHr);
				}
			}
			if (Object.keys(m).length) out[pidStr] = m;
		}
		return Object.keys(out).length ? out : undefined;
	}

	function buildOverrides(): Record<string, Record<string, number>> | undefined {
		if (!originalResult) return undefined;
		const clamp = (v: number) => Math.min(10, Math.max(0, v));
		const out: Record<string, Record<string, number>> = {};
		for (const [pidStr, stats] of Object.entries(edits)) {
			const base = originalResult.player_lines.find((p) => String(p.player_id) === pidStr);
			if (!base) continue;
			const m: Record<string, number> = {};
			for (const [stat, rawVal] of Object.entries(stats)) {
				const target = parseFloat(rawVal);
				if (!isFinite(target)) continue;
				if (stat === 'home_runs') m.home_runs = clamp(target / Math.max(base.home_runs as number, 0.01));
				else if (stat === 'bb') m.bb = clamp(target / Math.max(base.bb as number, 0.01));
				else if (stat === 'k') m.k = clamp(target / Math.max(base.k as number, 0.01));
				else if (stat === 'hits') {
					// The "hits" multiplier scales non-HR hits; back out the HR share
					// so the total-H column lands near the typed target.
					const baseNonHr = Math.max((base.hits as number) - (base.home_runs as number), 0.05);
					const tgtNonHr = Math.max(target - (base.home_runs as number), 0);
					m.hits = clamp(tgtNonHr / baseNonHr);
				}
			}
			// RBI isn't a per-batter rate — it emerges from hits/HR plus who's on
			// base. Approximate an RBI target by scaling the hitter's run-producing
			// power (hits + HR) toward it, folded on top of any explicit H/HR edit.
			// This nudges the H/HR columns too and won't hit the target exactly.
			const rbiRaw = stats['rbi'];
			if (rbiRaw !== undefined && rbiRaw.trim() !== '') {
				const targetRbi = parseFloat(rbiRaw);
				if (isFinite(targetRbi)) {
					const rbiMult = clamp(targetRbi / Math.max(base.rbi as number, 0.01));
					m.hits = clamp((m.hits ?? 1) * rbiMult);
					m.home_runs = clamp((m.home_runs ?? 1) * rbiMult);
				}
			}
			if (Object.keys(m).length) out[pidStr] = m;
		}
		return Object.keys(out).length ? out : undefined;
	}

	// Re-run a full Monte Carlo with the edited player rates; the new projection
	// (final total, everyone's box line) reflects the domino effect.
	async function runWithEdits() {
		const overrides = buildOverrides();
		const pitcherOvr = buildPitcherOverrides();
		if (!overrides && !pitcherOvr) return;
		editRunning = true;
		editError = '';
		try {
			const res = await api.simulate({
				game_id: gameId,
				n: 2000,
				seed: 7,
				rate_overrides: overrides,
				pitcher_overrides: pitcherOvr
			});
			result = res;
			baseResult = res;
			customAway = null;
			customHome = null;
			conditionError = '';
		} catch (e) {
			editError = String(e);
		} finally {
			editRunning = false;
		}
	}

	// True conditioned Monte Carlo: keep only sims that finish exactly the
	// chosen final and average the box score over those. Honors any active
	// player edits. Replaces the shown result (baseResult preserved for reset).
	async function runConditioned() {
		if (!baseResult) return;
		conditioning = true;
		conditionError = '';
		try {
			const res = await api.simulate({
				game_id: gameId,
				n: 2000,
				seed: 7,
				target_away: finalAway,
				target_home: finalHome,
				rate_overrides: buildOverrides(),
				pitcher_overrides: buildPitcherOverrides()
			});
			if (res.conditioned && res.conditioned.matches === 0) {
				conditionError = `No simulated game ended ${finalAway}–${finalHome} in ${res.conditioned.games_run.toLocaleString()} tries — pick a more likely final.`;
				return;
			}
			result = res;
		} catch (e) {
			conditionError = String(e);
		} finally {
			conditioning = false;
		}
	}

	const awayStats = $derived(teamstats.find((t) => t.team === parsed.away) ?? null);
	const homeStats = $derived(teamstats.find((t) => t.team === parsed.home) ?? null);

	// The headline prediction (win bar + summary card) stays pinned to the base
	// simulation, so a custom final score or player-stat what-if never rewrites
	// it — those only move the box score / leaders below. originalResult is that
	// stable base; it's re-seeded only by an explicit "Run simulation".
	const awayWin = $derived(originalResult != null && originalResult.home_win_probability < 0.5);
	const homeProbPct = $derived(originalResult ? (originalResult.home_win_probability * 100).toFixed(1) : '');
	const awayProbPct = $derived(originalResult ? ((1 - originalResult.home_win_probability) * 100).toFixed(1) : '');

	// Whole-number cell that tolerates a missing value. Guards against a
	// cached result predating a newly added field, which would otherwise
	// render as NaN.
	function fmtCount(v: unknown): string {
		const n = typeof v === 'number' ? v : NaN;
		return Number.isFinite(n) ? String(Math.round(n)) : '—';
	}

	// One tap on a stat ticker. Home runs and the like sit near zero, so a
	// 0.1 step would swing them by most of their value — those move finer.
	const TICK_STEP: Record<string, number> = {
		hits: 0.1, home_runs: 0.05, rbi: 0.1, bb: 0.1, k: 0.1,
		hits_allowed: 0.1, hr_allowed: 0.05, bb_allowed: 0.1
	};
	function tickStep(stat: string): number {
		return TICK_STEP[stat] ?? 0.1;
	}

	const STAT_LABEL: Record<string, string> = {
		hits: 'Hits', home_runs: 'Home runs', rbi: 'RBI', bb: 'Walks', k: 'Strikeouts',
		hits_allowed: 'Hits allowed', hr_allowed: 'HR allowed',
		bb_allowed: 'Walks allowed'
	};

	// Which cell is being edited, if any. Adjusting a number inline in a dense
	// table is awkward on a phone, so a tap opens the focused editor instead.
	type EditTarget = { kind: 'batter' | 'pitcher'; pid: number; stat: string; who: string };
	let editTarget = $state<EditTarget | null>(null);

	function openEditor(kind: 'batter' | 'pitcher', pid: number, name: string, stat: string) {
		if (editRunning) return;
		editTarget = { kind, pid, stat, who: name };
	}
	const editValue = $derived.by(() => {
		const t = editTarget;
		if (!t) return '';
		if (t.kind === 'batter') {
			const p = boxLines.find((x) => x.player_id === t.pid);
			return p ? cellValue(p, t.stat) : '';
		}
		const p = boxPitchers.find((x) => x.player_id === t.pid);
		return p ? pitcherCellValue(p, t.stat) : '';
	});
	// The unedited projection, so the editor can show what you're deviating from.
	const editBase = $derived.by(() => {
		const t = editTarget;
		if (!t || !originalResult) return null;
		const src = t.kind === 'batter' ? originalResult.player_lines : originalResult.pitcher_lines;
		const p = (src as { player_id: number }[]).find((x) => x.player_id === t.pid);
		const v = p ? (p as Record<string, unknown>)[t.stat] : undefined;
		return typeof v === 'number' ? v : null;
	});
	function setEditorValue(raw: string) {
		const t = editTarget;
		if (!t) return;
		if (t.kind === 'batter') setEdit(t.pid, t.stat, raw);
		else setPitcherEdit(t.pid, t.stat, raw);
	}
	function closeEditor() {
		const t = editTarget;
		if (t) {
			// Drops the entry if it was left blank, so it falls back to the projection.
			if (t.kind === 'batter') commitEdit(t.pid, t.stat);
			else commitPitcherEdit(t.pid, t.stat);
		}
		editTarget = null;
	}
	function resetEditorValue() {
		setEditorValue('');
		closeEditor();
	}

	// Colour tone for an accuracy percentage (green good → red poor).
	function pctTone(v: number | undefined): string {
		if (v == null) return '';
		return v >= 66 ? 'good' : v >= 40 ? 'ok' : 'bad';
	}

	function fmtMl(ml: number): string {
		return ml >= 0 ? `+${ml}` : `${ml}`;
	}
	function fmtLine(v: number): string {
		return v >= 0 ? `+${v}` : `${v}`;
	}
	function fmtSpread(line: number, odds: number | null): string {
		return odds != null ? `${fmtLine(line)} (${fmtMl(odds)})` : fmtLine(line);
	}

	function fmtDate(d: string): string {
		if (!d) return '';
		return new Date(d + 'T12:00:00').toLocaleDateString(undefined, {
			weekday: 'short',
			month: 'short',
			day: 'numeric'
		});
	}

	// ── Comparison rows (mrsim team-rankings pattern, baseball stats) ──────────
	interface CompareRow {
		label: string;
		key: string;
		fmt: (v: number) => string;
	}
	const COMPARE: CompareRow[] = [
		{ label: 'Lineup wOBA', key: 'lineup_woba', fmt: (v) => v.toFixed(3) },
		{ label: 'Lineup xwOBA', key: 'lineup_xwoba', fmt: (v) => v.toFixed(3) },
		{ label: 'ISO Power', key: 'lineup_iso', fmt: (v) => v.toFixed(3) },
		{ label: 'HR Rate', key: 'lineup_hr_rate', fmt: (v) => (v * 100).toFixed(1) + '%' },
		{ label: 'BB Rate', key: 'lineup_bb_rate', fmt: (v) => (v * 100).toFixed(1) + '%' },
		{ label: 'K Rate', key: 'lineup_k_rate', fmt: (v) => (v * 100).toFixed(1) + '%' },
		{ label: 'Sprint Speed', key: 'sprint_speed', fmt: (v) => v.toFixed(1) + ' ft/s' },
		{ label: 'Bullpen FIP', key: 'bullpen_fip', fmt: (v) => v.toFixed(2) }
	];

	function tier(rank: number | null | undefined): string {
		if (rank == null) return '';
		if (rank <= 5) return 'tier-elite';
		if (rank <= 12) return 'tier-good';
		if (rank <= 22) return 'tier-avg';
		return 'tier-poor';
	}

	function statOf(agg: TeamAggregate | null, key: string): number | null {
		const v = agg?.[key];
		return typeof v === 'number' ? v : null;
	}
	function rankOf(agg: TeamAggregate | null, key: string): number | null {
		const v = agg?.[`${key}_rank`];
		return typeof v === 'number' ? v : null;
	}

	// ── Adjustable final score (drives a true conditioned re-sim) ──────────────
	// Steppers default to the base projection's mean, rounded. finalAway/
	// finalHome are the values the user will run; scoreAdjusted flags that the
	// currently shown box score came from a conditioned run.
	const projAwayRuns = $derived(baseResult ? Math.max(0, Math.round(baseResult.away_run_mean)) : 0);
	const projHomeRuns = $derived(baseResult ? Math.max(0, Math.round(baseResult.home_run_mean)) : 0);
	const finalAway = $derived(customAway ?? projAwayRuns);
	const finalHome = $derived(customHome ?? projHomeRuns);
	const conditionInfo = $derived(result?.conditioned ?? null);
	const scoreAdjusted = $derived(conditionInfo != null);
	// The stepped final differs from the one currently shown (or nothing has
	// been run yet) → a fresh conditioned run is available.
	const canRunConditioned = $derived(
		!conditionInfo || conditionInfo.target_away !== finalAway || conditionInfo.target_home !== finalHome
	);

	function bumpAway(d: number) {
		customAway = Math.max(0, finalAway + d);
	}
	function bumpHome(d: number) {
		customHome = Math.max(0, finalHome + d);
	}
	function resetScore() {
		customAway = null;
		customHome = null;
		conditionError = '';
		if (baseResult) result = baseResult;
	}

	// ── Leaders (top performers per team, from the shown result) ───────────────
	interface Leader {
		cat: string;
		player: PlayerLine;
		main: string;
		sub: string;
	}
	function leadersFor(team: string): Leader[] {
		if (!result) return [];
		const lines = result.player_lines.filter((p) => p.team === team);
		const by = (key: string) => [...lines].sort((a, b) => (b[key] as number) - (a[key] as number))[0];
		const out: Leader[] = [];
		const hits = by('hits');
		if (hits) out.push({ cat: 'Hits', player: hits, main: (hits.hits as number).toFixed(2), sub: `${(hits.pa as number).toFixed(1)} PA` });
		const hr = by('home_runs');
		if (hr) out.push({ cat: 'Home Runs', player: hr, main: (hr.home_runs as number).toFixed(2), sub: `${(hr.hits as number).toFixed(2)} H` });
		const rbi = by('rbi');
		if (rbi) out.push({ cat: 'RBI', player: rbi, main: (rbi.rbi as number).toFixed(2), sub: `${(rbi.bb as number).toFixed(2)} BB` });
		return out;
	}


	// ── Box score ──────────────────────────────────────────────────────────────
	const boxLines = $derived.by(() => {
		if (!result) return [] as PlayerLine[];
		const team = boxTeam === 'away' ? parsed.away : parsed.home;
		return result.player_lines
			.filter((p) => p.team === team)
			.sort((a, b) => {
				// Real batting-order slot is authoritative; PA is only a
				// correlate of it and can't be trusted to reproduce the order
				// (that's how a leadoff hitter could end up displayed last).
				const sa = a.lineup_slot, sb = b.lineup_slot;
				if (sa != null && sb != null) return sa - sb;
				return (b.pa as number) - (a.pa as number);
			});
	});

	// Projected pitching lines for the box-score team, workhorse (most IP) first.
	const boxPitchers = $derived.by(() => {
		if (!result?.pitcher_lines) return [];
		const team = boxTeam === 'away' ? parsed.away : parsed.home;
		return result.pitcher_lines
			.filter((p) => p.team === team)
			.sort((a, b) => b.ip - a.ip);
	});

	// Real (not simulated) box score for the Live/Game Recap tab.
	const liveTeamBox = $derived(liveBoxTeam === 'away' ? boxscore?.away : boxscore?.home);
	const liveBatters = $derived(
		[...(liveTeamBox?.batters ?? [])].sort((a, b) => {
			// MLB's own lineup_slot is authoritative; at_bats is only a
			// correlate (and can misorder early in a game or after subs).
			if (a.lineup_slot != null && b.lineup_slot != null) return a.lineup_slot - b.lineup_slot;
			return (b.at_bats ?? 0) - (a.at_bats ?? 0);
		})
	);
	const livePitchers = $derived(
		[...(liveTeamBox?.pitchers ?? [])].sort(
			(a, b) => parseFloat(b.innings_pitched ?? '0') - parseFloat(a.innings_pitched ?? '0')
		)
	);

	// ── Game log grouped by half-inning ───────────────────────────────────────
	const logGroups = $derived.by(() => {
		const log = result?.representative?.play_log ?? [];
		const groups: { label: string; entries: PlayLogEntry[] }[] = [];
		for (const e of log) {
			const label = `${e.half === 'Top' ? 'Top' : 'Bottom'} ${e.inning}`;
			const last = groups.at(-1);
			if (last && last.label === label) last.entries.push(e);
			else groups.push({ label, entries: [e] });
		}
		return groups;
	});

	const OUTCOME_LABEL: Record<string, string> = {
		'1B': 'Single',
		'2B': 'Double',
		'3B': 'Triple',
		HR: 'Home run',
		BB: 'Walk',
		HBP: 'Hit by pitch',
		K: 'Strikeout',
		IPO: 'In-play out'
	};

	async function runBet() {
		betting = true;
		error = '';
		try {
			edges = await api.bet({
				game_id: gameId,
				odds: { home_ml: homeMl, away_ml: awayMl, total_line: totalLine, over_ml: -110, under_ml: -110 },
				kelly_fraction: kelly,
				n: 2000,
				seed: 7
			});
		} catch (e) {
			error = String(e);
		} finally {
			betting = false;
		}
	}

	const SECTIONS = [
		{ id: 'summary', label: 'Summary' },
		{ id: 'scoring', label: 'Scoring' },
		{ id: 'leaders', label: 'Leaders' },
		{ id: 'boxscore', label: 'Box score' },
		{ id: 'gamelog', label: 'Game log' },
		{ id: 'distributions', label: 'Distributions' }
	];

	function jumpTo(id: string) {
		jumpOpen = false;
		document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
	}

	const distHist = $derived(result ? result.histograms[distPick] : null);
	const distMean = $derived(
		!result ? null
		: distPick === 'totals' ? result.total_mean
		: distPick === 'home_runs' ? result.home_run_mean
		: result.away_run_mean
	);
	const distTitle = $derived(
		distPick === 'totals' ? 'Total runs'
		: distPick === 'home_runs' ? `${parsed.home} runs`
		: `${parsed.away} runs`
	);
</script>

<svelte:head>
	<title>{parsed.away} @ {parsed.home} — The Beast</title>
</svelte:head>

<div class="back-row">
	<a class="back" href="/matchups">‹ Matchups</a>
	{#if mode === 'prediction' && result}
		<span class="back-divider">|</span>
		<div class="jump-wrap">
			<button class="jump-btn" onclick={() => (jumpOpen = !jumpOpen)}>
				Jump to <span class="jump-arrow">▾</span>
			</button>
			{#if jumpOpen}
				<div class="jump-menu">
					{#each SECTIONS as s}
						<button class="jump-item" onclick={() => jumpTo(s.id)}>{s.label}</button>
					{/each}
				</div>
			{/if}
		</div>
	{/if}
</div>

<div class="hero">
	{#if liveGame && statusLabel(liveGame)}
		<div class="hero-status" class:is-live={liveGame.status === 'Live'} class:is-final={liveGame.status === 'Final'}>
			{#if liveGame.status === 'Live'}<span class="live-dot"></span>{/if}
			{statusLabel(liveGame)}
		</div>
	{/if}
	<div class="hero-team away">
		<TeamLogo abbr={parsed.away} size={72} />
		<div class="hero-abbr">{parsed.away}</div>
		{#if liveGame?.away_score != null}
			<div class="hero-real-score" class:trail={liveGame.home_score != null && liveGame.away_score < liveGame.home_score}>
				{liveGame.away_score}
			</div>
		{/if}
		<div class="hero-label">Away</div>
	</div>
	<div class="hero-center">
		<div class="hero-at">@</div>
		<div class="hero-meta">{fmtDate(parsed.date)}</div>
		{#if doubleheaderGame(gameId)}<div class="hero-dh">Doubleheader · Game {doubleheaderGame(gameId)}</div>{/if}
	</div>
	<div class="hero-team home">
		<TeamLogo abbr={parsed.home} size={72} />
		<div class="hero-abbr">{parsed.home}</div>
		{#if liveGame?.home_score != null}
			<div class="hero-real-score" class:trail={liveGame.away_score != null && liveGame.home_score < liveGame.away_score}>
				{liveGame.home_score}
			</div>
		{/if}
		<div class="hero-label">Home</div>
	</div>
	{#if originalResult}
		<div class="hero-winbar">
			<div class="hwb-labels">
				<span class:lead={awayWin}>{parsed.away} {awayProbPct}%</span>
				<span class="hwb-cap">Win probability <span class="hwb-sims">· {originalResult.n.toLocaleString()} sims</span></span>
				<span class:lead={!awayWin}>{parsed.home} {homeProbPct}%</span>
			</div>
			<div class="hwb-track">
				<div class="hwb-fill" style={`width:${awayProbPct}%;background:var(--accent-vegas)`}></div>
				<div class="hwb-fill" style={`width:${homeProbPct}%;background:var(--accent-pred)`}></div>
			</div>
		</div>
	{/if}
</div>

<div class="mode-tabs">
	{#if liveTabLabel}
		<button class="mode-tab tab-live" class:active={mode === 'live'} onclick={() => pickMode('live')}>
			{#if liveGame?.status === 'Live'}<span class="live-dot"></span>{/if}
			{liveTabLabel}
		</button>
		<span class="mode-divider">|</span>
	{/if}
	<button class="mode-tab tab-preview" class:active={mode === 'preview'} onclick={() => pickMode('preview')}>Preview</button>
	<span class="mode-divider">|</span>
	<button class="mode-tab tab-predicted" class:active={mode === 'prediction'} onclick={() => pickMode('prediction')}>Matchups Prediction</button>
</div>

{#if error}<div class="error">{error}</div>{/if}
{#if loading}
	<div class="loading"><span class="spinner"></span> Running Monte Carlo…</div>
{/if}

{#if mode === 'live'}
	<div class="live-panel">
		{#if liveGame?.status === 'Live'}
			<details class="block live-sim-block" id="run-live-sim" open>
				<summary>Run Live Sim <span class="muted-inline">· simulate the rest of the game from where it stands now</span></summary>
				<div class="block-body">
					<div class="ls-actions">
						<button class="ls-run" onclick={runLiveSim} disabled={liveSimRunning}>
							{liveSimRunning ? 'Simulating…' : liveSim?.live ? 'Re-run from current state' : 'Run live sim'}
						</button>
						<label class="ls-auto">
							<input type="checkbox" bind:checked={liveSimAuto} />
							Keep updating
						</label>
						{#if liveSimAt && liveSim?.live}
							<span class="ls-stamp">as of {liveSimAt.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit', second: '2-digit' })}</span>
						{/if}
					</div>

					{#if liveSimError}
						<div class="loading">Couldn't run the live sim: {liveSimError}</div>
					{:else if liveSimRunning && !liveSim}
						<div class="loading"><span class="spinner"></span> Reading the live game state and playing it out…</div>
					{:else if liveSim && !liveSim.live}
						<div class="loading">Nothing to simulate — {liveSim.reason ?? 'no live state available'}.</div>
					{:else if liveSim?.live && liveSim.state && liveSim.projected_final}
						{@const st = liveSim.state}
						{@const pf = liveSim.projected_final}
						<div class="ls-from">
							Picked up from
							<strong>{st.half === 'top' ? 'Top' : 'Bot'} {st.inning}</strong>,
							{st.outs} out{st.outs === 1 ? '' : 's'},
							{#if st.on_first || st.on_second || st.on_third}
								runners on {[st.on_first ? '1st' : null, st.on_second ? '2nd' : null, st.on_third ? '3rd' : null].filter(Boolean).join(' & ')}
							{:else}bases empty{/if},
							<strong>{parsed.away} {st.away_score}–{st.home_score} {parsed.home}</strong>.
							Due up: {parsed.away} #{st.away_due_up_slot}, {parsed.home} #{st.home_due_up_slot}.
						</div>

						<div class="ls-win">
							<div class="ls-win-row">
								<span class="ls-win-team">{parsed.away}</span>
								<div class="ls-bar"><div class="ls-bar-fill away" style={`width:${(liveSim.away_win_probability ?? 0) * 100}%`}></div></div>
								<span class="ls-win-pct">{((liveSim.away_win_probability ?? 0) * 100).toFixed(1)}%</span>
							</div>
							<div class="ls-win-row">
								<span class="ls-win-team">{parsed.home}</span>
								<div class="ls-bar"><div class="ls-bar-fill home" style={`width:${(liveSim.home_win_probability ?? 0) * 100}%`}></div></div>
								<span class="ls-win-pct">{((liveSim.home_win_probability ?? 0) * 100).toFixed(1)}%</span>
							</div>
							{#if (liveSim.extras_probability ?? 0) > 0.001}
								<div class="ls-extras">
									Still tied after 9 in {((liveSim.extras_probability ?? 0) * 100).toFixed(1)}% of runs — those go to extra innings, which the model doesn't play out.
								</div>
							{/if}
						</div>

						<div class="ls-grid">
							<div class="ls-cell">
								<div class="ls-cell-val">{pf.away_mean.toFixed(1)} – {pf.home_mean.toFixed(1)}</div>
								<div class="ls-cell-key">Projected final</div>
							</div>
							<div class="ls-cell">
								<div class="ls-cell-val">+{liveSim.runs_to_come?.away.toFixed(1)} / +{liveSim.runs_to_come?.home.toFixed(1)}</div>
								<div class="ls-cell-key">Runs still to come ({parsed.away}/{parsed.home})</div>
							</div>
							<div class="ls-cell">
								<div class="ls-cell-val">{pf.total_mean.toFixed(1)}</div>
								<div class="ls-cell-key">Projected total</div>
							</div>
						</div>

						{#if liveSim.likely_finals?.length}
							<div class="ls-sub-head">Most likely finals</div>
							<div class="ls-finals">
								{#each liveSim.likely_finals as f}
									<div class="ls-final">
										<span class="ls-final-score">{f.away}–{f.home}</span>
										<span class="ls-final-pct">{f.pct.toFixed(1)}%</span>
									</div>
								{/each}
							</div>
						{/if}

						{#if liveSim.player_lines?.length}
							<div class="ls-sub-head">Rest-of-game projections</div>
							<div class="ls-note">Averages over the remaining plate appearances only — what each hitter is projected to add from here.</div>
							<div class="table-scroll">
								<table class="acc-table">
									<thead>
										<tr><th class="acc-stat-h">Batter</th><th>PA</th><th>H</th><th>HR</th><th>RBI</th></tr>
									</thead>
									<tbody>
										{#each liveSim.player_lines as p (p.player_id)}
											<tr>
												<td class="acc-stat">
													<a class="player-link" href={`/players/${p.player_id}`}>{p.name}</a>
													<span class="acc-team-tag">{p.team}</span>
												</td>
												<td>{(p.pa as number).toFixed(1)}</td>
												<td>{(p.hits as number).toFixed(2)}</td>
												<td>{(p.home_runs as number).toFixed(2)}</td>
												<td>{(p.rbi as number).toFixed(2)}</td>
											</tr>
										{/each}
									</tbody>
								</table>
							</div>
						{/if}

						{#if liveSim.pitcher_lines?.length}
							<div class="ls-sub-head">Rest-of-game pitching</div>
							<div class="ls-note">Projected workload from here — innings still to be thrown and what they're expected to give up.</div>
							<div class="table-scroll">
								<table class="acc-table">
									<thead>
										<tr><th class="acc-stat-h">Pitcher</th><th>IP</th><th>P</th><th>H</th><th>ER</th><th>BB</th><th>K</th><th>HR</th></tr>
									</thead>
									<tbody>
										{#each liveSim.pitcher_lines as p (`${p.team}-${p.player_id}`)}
											<tr>
												<td class="acc-stat">
													{#if p.player_id > 0}<a class="player-link" href={`/players/${p.player_id}`}>{p.name}</a>{:else}{p.name}{/if}
													<span class="acc-team-tag">{p.team}</span>
												</td>
												<td>{p.ip.toFixed(1)}</td>
												<td>{fmtCount(p.pitches)}</td>
												<td>{p.hits_allowed.toFixed(2)}</td>
												<td>{p.er.toFixed(2)}</td>
												<td>{p.bb_allowed.toFixed(2)}</td>
												<td>{p.k.toFixed(2)}</td>
												<td>{p.hr_allowed.toFixed(2)}</td>
											</tr>
										{/each}
									</tbody>
								</table>
							</div>
						{/if}
					{:else}
						<div class="ls-idle">
							Runs {liveSim?.n ? liveSim.n.toLocaleString() : 'thousands of'} simulations of the rest of this game,
							starting from the current inning, outs, baserunners, score and spot in each batting order.
						</div>
					{/if}
				</div>
			</details>
		{/if}
		<details class="block" id="live-scoring" open>
			<summary>
				Scoring
				<span class="muted-inline">
					· {liveGame?.status === 'Live' ? statusLabel(liveGame) : 'final'}
				</span>
			</summary>
			<div class="block-body">
				{#if linescoreLoading}
					<div class="loading"><span class="spinner"></span> Loading box score…</div>
				{:else if linescore && linescore.innings.length}
					<div class="table-scroll">
						<table class="box-table">
							<thead>
								<tr>
									<th class="box-team-col"></th>
									{#each linescore.innings as inn}<th>{inn.num}</th>{/each}
									<th class="box-total">R</th>
									<th class="box-total">H</th>
									<th class="box-total">E</th>
								</tr>
							</thead>
							<tbody>
								<tr>
									<td class="box-team-col"><span class="box-team-inner"><TeamLogo abbr={parsed.away} size={18} /> {parsed.away}</span></td>
									{#each linescore.innings as inn}<td>{inn.away_runs ?? '—'}</td>{/each}
									<td class="box-total">{linescore.away_totals.runs ?? '—'}</td>
									<td class="box-total">{linescore.away_totals.hits ?? '—'}</td>
									<td class="box-total">{linescore.away_totals.errors ?? '—'}</td>
								</tr>
								<tr>
									<td class="box-team-col"><span class="box-team-inner"><TeamLogo abbr={parsed.home} size={18} /> {parsed.home}</span></td>
									{#each linescore.innings as inn}<td>{inn.home_runs ?? '—'}</td>{/each}
									<td class="box-total">{linescore.home_totals.runs ?? '—'}</td>
									<td class="box-total">{linescore.home_totals.hits ?? '—'}</td>
									<td class="box-total">{linescore.home_totals.errors ?? '—'}</td>
								</tr>
							</tbody>
						</table>
					</div>
				{:else}
					<div class="loading">Box score not available yet.</div>
				{/if}

				{#if liveGame?.status === 'Live' && linescore?.situation && linescore.situation.outs != null}
					<div class="situation-card">
						<div class="situation-row">
							<div class="bases" aria-hidden="true">
								<div class="base base-2" class:on={linescore.situation.on_second}></div>
								<div class="base base-3" class:on={linescore.situation.on_third}></div>
								<div class="base base-1" class:on={linescore.situation.on_first}></div>
							</div>
							<div class="situation-details">
								<div class="sit-count">
									{linescore.situation.balls ?? 0}-{linescore.situation.strikes ?? 0} count,
									{linescore.situation.outs} out{linescore.situation.outs === 1 ? '' : 's'}
								</div>
								{#if linescore.situation.batter}
									<div class="sit-line"><span class="sit-key">At bat</span> {linescore.situation.batter}</div>
								{/if}
								{#if linescore.situation.pitcher}
									<div class="sit-line"><span class="sit-key">Pitching</span> {linescore.situation.pitcher}</div>
								{/if}
								{#if linescore.situation.on_deck}
									<div class="sit-line"><span class="sit-key">On deck</span> {linescore.situation.on_deck}</div>
								{/if}
							</div>
						</div>
					</div>
				{/if}
			</div>
		</details>

		<!-- The at-bat that hasn't happened yet. Sits directly under the live
		     situation because that's the state it's forecasting *from* — the
		     hitter on deck against the pitcher currently on the mound.

		     Everything here is a probability, and the panel is built so that it
		     cannot be read as anything else: every row carries how likely it is
		     to exist at all, and the single most likely exact sequence is
		     printed with its own (small) odds so the rows can't be mistaken for
		     a script of what is about to happen. -->
		{#if liveGame?.status === 'Live'}
			<details class="block" id="next-at-bat" open>
				<summary>
					{nextAtBat?.subject === 'on_deck' ? 'Next at-bat' : 'This at-bat'}
					<span class="muted-inline">· pitch by pitch</span>
				</summary>
				<div class="block-body">
					{#if nextAtBatLoading && !nextAtBat}
						<div class="loading">Working out the next at-bat…</div>
					{:else if !nextAtBat?.available}
						<div class="loading">{nextAtBat?.reason ?? 'Nothing to forecast yet.'}</div>
					{:else if nextAtBat.forecast}
						{@const f = nextAtBat.forecast}
						<div class="nab-head">
							<div class="nab-who">
								<span class="nab-label"
									>{nextAtBat.subject === 'on_deck' ? 'Up next' : 'At the plate'}</span
								>
								<span class="nab-batter">{nextAtBat.batter}</span>
								<span class="nab-vs">vs</span>
								<span class="nab-pitcher">{nextAtBat.pitcher}</span>
								<span class="nab-hands">
									{nextAtBat.forecast.batter_hand}HB · {nextAtBat.forecast.pitcher_hand}HP
								</span>
								<!-- The count is part of who this forecast is about, not
								     background detail: the same hitter at 0-0 and at 1-2 is
								     two different propositions. -->
								<span class="nab-oncount">on {f.start_count}</span>
								<!-- Marked on the header rather than only in the note
								     underneath: about a fifth of hitters on a night have no
								     season line, and a baseline forecast that looks identical
								     to a real one is the wrong kind of quiet. -->
								{#if nextAtBat.batter_profile === 'league' || nextAtBat.pitcher_profile === 'league'}
									<span class="nab-standin" title="No season line for this player yet">
										league profile
									</span>
								{/if}
							</div>
							{#if nextAtBat.on_deck}
								<div class="nab-sub">
									On deck: {nextAtBat.on_deck}{#if nextAtBat.in_hole}
										· in the hole: {nextAtBat.in_hole}{/if}
								</div>
							{/if}
						</div>

						<!-- The whole panel: how many more pitches, and how sure.
						     A single expectation with no spread looks authoritative and
						     says nothing — an at-bat that averages four pitches is very
						     rarely four pitches — so the scale is not decoration. -->
						<div class="nab-estimate">
							<span class="nab-est-n">{f.likely_pitches}</span>
							<span class="nab-est-t">
								{f.start_count === '0-0' ? 'pitches' : 'more pitches'}
								<span class="nab-est-sub">
									{f.expected_pitches.toFixed(1)} average{#if f.started_expected_pitches !== null}
										· {f.started_expected_pitches.toFixed(1)} at 0-0{/if}
								</span>
							</span>
						</div>

						<!-- More / exactly / fewer, as one bar. Neutral colours on
						     purpose: a long at-bat is good news for one dugout and bad
						     for the other, and nothing here should take a side. -->
						<div class="nab-scale">
							<div class="nab-scale-bar" aria-hidden="true">
								<span class="scale fewer" style="width:{f.fewer_pct}%"></span>
								<span class="scale same" style="width:{f.same_pct}%"></span>
								<span class="scale more" style="width:{f.more_pct}%"></span>
							</div>
							<div class="nab-scale-keys">
								<span class="k fewer"
									>Fewer than {f.likely_pitches}<b>{f.fewer_pct.toFixed(0)}%</b></span
								>
								<span class="k same">Exactly {f.likely_pitches}<b>{f.same_pct.toFixed(0)}%</b></span>
								<span class="k more"
									>More than {f.likely_pitches}<b>{f.more_pct.toFixed(0)}%</b></span
								>
							</div>
						</div>

						<!-- The full shape behind those three numbers. -->
						{@const peak = Math.max(...f.distribution.map((d) => d.pct), 1)}
						<div class="nab-dist">
							{#each f.distribution as d (d.n)}
								<div class="nab-dbar" class:at={d.n === f.likely_pitches}>
									<span class="nab-dv">{d.pct >= 5 ? d.pct.toFixed(0) : ''}</span>
									<!-- The fill sits in its own fixed-height track. Without it
									     the value label above only exists on some columns, and
									     the bars stop sharing a baseline — which turns a
									     distribution into a staircase. -->
									<span class="nab-dtrack">
										<span class="nab-dfill" style="height:{(d.pct / peak) * 100}%"
										></span>
									</span>
									<span class="nab-dn">{d.n}{d.plus ? '+' : ''}</span>
								</div>
							{/each}
						</div>
						<div class="nab-dist-cap">
							chance the at-bat ends on that pitch
						</div>

						<!-- How it ends, for context on why the length is what it is.
						     A strikeout takes at least three pitches; a ball in play can
						     take one. -->
						<div class="nab-outcomes">
							{#each [{ k: 'In play', v: f.in_play_pct, was: f.started_in_play_pct, c: 'ip' }, { k: 'Strikeout', v: f.strikeout_pct, was: f.started_strikeout_pct, c: 'k' }, { k: 'Walk', v: f.walk_pct, was: f.started_walk_pct, c: 'bb' }] as o (o.k)}
								<div class="nab-out {o.c}">
									<span class="nab-out-v">{o.v.toFixed(0)}%</span>
									<span class="nab-out-k">{o.k}</span>
									{#if o.was !== null && o.was !== undefined && Math.abs(o.v - o.was) >= 1}
										<span class="nab-was">
											{o.v > o.was ? '▲' : '▼'}
											{Math.abs(o.v - o.was).toFixed(0)} from {o.was.toFixed(0)}%
										</span>
									{/if}
								</div>
							{/each}
						</div>

						{#each [...f.notes, ...nextAtBat.notes] as n}
							<p class="nab-note">{n}</p>
						{/each}
					{/if}

					<!-- The game-level countdown. Deliberately outside the branches
					     above: it needs only the inning, so it survives a batter or
					     a reliever we hold no profile for — and that reliever is
					     exactly when somebody wants the number. -->
					{#if nextAtBat?.team_pitches?.length}
						<div class="tpc">
							<div class="tpc-head">
								Team pitches remaining
								{#if nextAtBat.extra_innings}
									<span class="tpc-extra">extras — current half only</span>
								{/if}
							</div>
							<div class="tpc-teams">
								{#each nextAtBat.team_pitches as t (t.side)}
									<div class="tpc-team" class:on={t.is_pitching} class:over={t.over_estimate > 0}>
										<div class="tpc-top">
											<TeamLogo abbr={t.team} size={16} />
											<span class="tpc-abbr">{t.team}</span>
											{#if t.is_pitching}<span class="tpc-now">on the mound</span>{/if}
										</div>
										<!-- The estimate and the real count side by side. The
										     estimate alone reads as arithmetic on the innings —
										     which is what it was — so the number actually thrown
										     sits next to it rather than in the small print.

										     Past the estimate the left-hand figure stops counting
										     down and starts counting up: insisting on a countdown
										     once it has run out shows a zero that means nothing,
										     when what you want is how far over they are. -->
										<div class="tpc-nums">
											<span class="tpc-fig">
												{#if t.over_estimate > 0}
													<span class="tpc-n over">+{t.over_estimate}</span>
													<span class="tpc-nlab">over</span>
												{:else}
													<span class="tpc-n">{t.expected_remaining}</span>
													<span class="tpc-nlab">{t.complete ? 'left' : 'more'}</span>
												{/if}
											</span>
											{#if t.thrown !== null}
												<span class="tpc-fig actual">
													<span class="tpc-n thrown">{t.thrown}</span>
													<span class="tpc-nlab">thrown</span>
												</span>
											{/if}
										</div>
										<!-- The bar is what makes it read as a countdown rather
										     than as one more statistic. It fills red past the
										     estimate rather than draining. -->
										<div class="tpc-bar" aria-hidden="true">
											{#if t.over_estimate > 0}
												<span
													class="over"
													style="width:{Math.min(
														100,
														(t.over_estimate / t.expected_total) * 100
													)}%"
												></span>
											{:else}
												<span style="width:{Math.min(100, t.pct_remaining)}%"></span>
											{/if}
										</div>
										<div class="tpc-sub">
											{#if t.complete}
												staff done
											{:else}
												{t.outs_remaining} out{t.outs_remaining === 1 ? '' : 's'} left
											{/if}
											{#if t.projected_total !== null}
												· ~{t.projected_total} projected
											{:else}
												· ~{t.expected_total} typical
											{/if}
											{#if t.outs_recorded > 0 && t.thrown !== null}
												<!-- Their own rate tonight, which is what the
												     projection is actually built on. The league is
												     5.4; a staff reading 6.8 is having a long night
												     and the number to its left follows it. -->
												· {t.pace.toFixed(1)}/out
											{/if}
										</div>
									</div>
								{/each}
							</div>
							<p class="nab-note tpc-note">
								Each staff's own pitches per out so far, eased towards the league's
								5.4 while the sample is small, against the outs they still have to
								record. Not a per-pitcher projection — the arms change.
							</p>
						</div>
					{/if}
				</div>
			</details>
		{/if}

		{#if awayLeaders.length || homeLeaders.length}
			<details class="block" id="live-leaders" open>
				<summary>Leaders <span class="muted-inline">· this game</span></summary>
				<div class="block-body">
					<div class="leaders-grid">
						{#each [{ abbr: parsed.away, leaders: awayLeaders }, { abbr: parsed.home, leaders: homeLeaders }] as t}
							{#if t.leaders.length}
								<div class="leaders-team">
									<div class="leaders-team-header"><TeamLogo abbr={t.abbr} size={20} /> {t.abbr}</div>
									<div class="leaders-row">
										{#each t.leaders as l}
											<div class="leader">
												<div class="leader-cat">{l.cat}</div>
												<div class="leader-photo-wrap"><PlayerPhoto playerId={l.player.player_id} name={l.player.name} size={44} /></div>
												<div class="leader-name">
													{#if l.player.player_id}
														<a class="player-link" href={`/players/${l.player.player_id}`}>{l.player.name}</a>
													{:else}
														{l.player.name}
													{/if}
												</div>
												<div class="leader-main">{l.main}</div>
												<div class="leader-subs"><span class="leader-sub">{l.sub}</span></div>
											</div>
										{/each}
									</div>
								</div>
							{/if}
						{/each}
					</div>
				</div>
			</details>
		{/if}
		{#if boxscore && (boxscore.away.batters.length || boxscore.home.batters.length)}
			<details class="block" id="live-boxscore" open>
				<summary>Box score <span class="muted-inline">· full lineup, this game</span></summary>
				<div class="block-body">
					<div class="box-tabs">
						<button class:active={liveBoxTeam === 'away'} onclick={() => (liveBoxTeam = 'away')}>{parsed.away}</button>
						<button class:active={liveBoxTeam === 'home'} onclick={() => (liveBoxTeam = 'home')}>{parsed.home}</button>
					</div>
					<div class="stat-block">
						<div class="stat-block-label">Batting</div>
						<div class="table-scroll">
							<table class="stat-table">
								<thead>
									<tr>
										<th class="name-col">Player</th><th>Pos</th><th>AB</th><th>H</th><th>HR</th><th>RBI</th><th>BB</th><th>K</th>
									</tr>
								</thead>
								<tbody>
									{#each liveBatters as p (p.name)}
										<tr>
											<td class="name-col">
												{#if p.player_id}
													<a class="player-link" href={`/players/${p.player_id}`}>{p.name}</a>
												{:else}
													{p.name}
												{/if}
											</td>
											<td>{p.position ?? '—'}</td>
											<td>{p.at_bats ?? '—'}</td>
											<td>{p.hits ?? '—'}</td>
											<td>{p.home_runs ?? '—'}</td>
											<td>{p.rbi ?? '—'}</td>
											<td>{p.walks ?? '—'}</td>
											<td>{p.strikeouts ?? '—'}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					</div>
					{#if livePitchers.length}
						<div class="stat-block">
							<div class="stat-block-label">Pitching</div>
							<div class="table-scroll">
								<table class="stat-table">
									<thead>
										<tr>
											<th class="name-col">Player</th><th>IP</th><th>P</th><th>H</th><th>ER</th><th>BB</th><th>K</th>
										</tr>
									</thead>
									<tbody>
										{#each livePitchers as p (p.name)}
											<tr>
												<td class="name-col">
													{#if p.player_id}
														<a class="player-link" href={`/players/${p.player_id}`}>{p.name}</a>
													{:else}
														{p.name}
													{/if}
												</td>
												<td>{p.innings_pitched ?? '—'}</td>
												<td>{p.pitches ?? '—'}</td>
												<td>{p.hits_allowed ?? '—'}</td>
												<td>{p.earned_runs ?? '—'}</td>
												<td>{p.walks_allowed ?? '—'}</td>
												<td>{p.strikeouts ?? '—'}</td>
											</tr>
										{/each}
									</tbody>
								</table>
							</div>
						</div>
					{/if}
				</div>
			</details>
		{/if}

		{#if liveGame?.status === 'Final'}
			<details class="block accuracy-block" open>
				<summary>Prediction Accuracy <span class="muted-inline">· simulation vs. what actually happened</span></summary>
				<div class="block-body">
					{#if accuracyLoading}
						<div class="loading"><span class="spinner"></span> Scoring the simulation against the final…</div>
					{:else if accuracyError}
						<div class="loading">Couldn't score this game: {accuracyError}</div>
					{:else if accuracy?.final && accuracy.prediction && accuracy.actual}
						{@const acc = accuracy.prediction}
						{@const act = accuracy.actual}
						<div class="acc-call" class:hit={acc.picked_winner} class:miss={acc.picked_winner === false}>
							<div class="acc-call-icon">{acc.picked_winner ? '✓' : acc.picked_winner === false ? '✗' : '—'}</div>
							<div class="acc-call-text">
								<div class="acc-call-head">
									{#if acc.picked_winner}Model picked the winner{:else if acc.picked_winner === false}Model missed the winner{:else}Tie game{/if}
								</div>
								<div class="acc-call-sub">
									Gave {act.winner === 'away' ? parsed.away : parsed.home} a {(acc.winner_prob * 100).toFixed(0)}% chance ·
									final {parsed.away} {act.away_runs}–{act.home_runs} {parsed.home}
								</div>
							</div>
						</div>

						<div class="acc-scorecard">
							<div class="acc-chip {pctTone(acc.accuracy_pct.winner)}">
								<span class="acc-chip-val">{acc.accuracy_pct.winner.toFixed(0)}%</span>
								<span class="acc-chip-key">Winner</span>
							</div>
							<div class="acc-chip {pctTone(acc.accuracy_pct.spread)}">
								<span class="acc-chip-val">{acc.accuracy_pct.spread.toFixed(0)}%</span>
								<span class="acc-chip-key">Margin</span>
							</div>
							<div class="acc-chip {pctTone(acc.accuracy_pct.total)}">
								<span class="acc-chip-val">{acc.accuracy_pct.total.toFixed(0)}%</span>
								<span class="acc-chip-key">Total runs</span>
							</div>
						</div>
						<div class="acc-chip-note">
							Winner % = the win chance the model gave {act.winner === 'away' ? parsed.away : parsed.home} (who won).
							Margin / total % = how centrally the real result sat in the forecast (100% = dead-on the model's median).
						</div>

						<div class="table-scroll">
							<table class="acc-table">
								<thead>
									<tr><th class="acc-stat-h"></th><th>Projected</th><th>Range 10–90</th><th>Actual</th><th>Δ</th><th>Acc</th></tr>
								</thead>
								<tbody>
									<tr>
										<td class="acc-stat">{parsed.away} runs</td>
										<td>{acc.away_runs.mean.toFixed(1)}</td>
										<td class="acc-range" class:within={acc.away_runs.within_range}>{acc.away_runs.p10}–{acc.away_runs.p90}</td>
										<td class="acc-actual">{acc.away_runs.actual}</td>
										<td class:acc-pos={acc.away_runs.error > 0} class:acc-neg={acc.away_runs.error < 0}>{acc.away_runs.error > 0 ? '+' : ''}{acc.away_runs.error.toFixed(1)}</td>
										<td class="acc-pctcol {pctTone(acc.away_runs.centrality_pct)}">{acc.away_runs.centrality_pct?.toFixed(0)}%</td>
									</tr>
									<tr>
										<td class="acc-stat">{parsed.home} runs</td>
										<td>{acc.home_runs.mean.toFixed(1)}</td>
										<td class="acc-range" class:within={acc.home_runs.within_range}>{acc.home_runs.p10}–{acc.home_runs.p90}</td>
										<td class="acc-actual">{acc.home_runs.actual}</td>
										<td class:acc-pos={acc.home_runs.error > 0} class:acc-neg={acc.home_runs.error < 0}>{acc.home_runs.error > 0 ? '+' : ''}{acc.home_runs.error.toFixed(1)}</td>
										<td class="acc-pctcol {pctTone(acc.home_runs.centrality_pct)}">{acc.home_runs.centrality_pct?.toFixed(0)}%</td>
									</tr>
									<tr>
										<td class="acc-stat">Total</td>
										<td>{acc.total.mean.toFixed(1)}</td>
										<td class="acc-range" class:within={acc.total.within_range}>{acc.total.p10}–{acc.total.p90}</td>
										<td class="acc-actual">{acc.total.actual}</td>
										<td class:acc-pos={acc.total.error > 0} class:acc-neg={acc.total.error < 0}>{acc.total.error > 0 ? '+' : ''}{acc.total.error.toFixed(1)}</td>
										<td class="acc-pctcol {pctTone(acc.total.centrality_pct)}">{acc.total.centrality_pct?.toFixed(0)}%</td>
									</tr>
									<tr>
										<td class="acc-stat">Margin</td>
										<td>{acc.spread.mean.toFixed(1)}</td>
										<td class="acc-range" class:within={acc.spread.within_range}>{acc.spread.p10}–{acc.spread.p90}</td>
										<td class="acc-actual">{acc.spread.actual > 0 ? '+' : ''}{acc.spread.actual}</td>
										<td class:acc-pos={acc.spread.error > 0} class:acc-neg={acc.spread.error < 0}>{acc.spread.error > 0 ? '+' : ''}{acc.spread.error.toFixed(1)}</td>
										<td class="acc-pctcol {pctTone(acc.spread.centrality_pct)}">{acc.spread.centrality_pct?.toFixed(0)}%</td>
									</tr>
								</tbody>
							</table>
						</div>
						{#if acc.total.over_pct != null}
							<div class="acc-ou">
								On the total of {acc.total.actual}, the model had it going
								<strong>over {acc.total.over_pct.toFixed(0)}%</strong> ·
								under {acc.total.under_pct?.toFixed(0)}% ·
								exactly {acc.total.actual} in {acc.total.hit_pct?.toFixed(0)}% of sims.
							</div>
						{/if}
						<div class="acc-exact">
							The sim reproduced the exact final in <strong>{(acc.exact_score_prob * 100).toFixed(1)}%</strong>
							of {acc.n.toLocaleString()} simulated games.
						</div>

						{#if accuracy.score_match}
							{@const sm = accuracy.score_match}
							<div class="acc-sub-head">Of the sims that nailed the score…</div>
							<div class="acc-sub-note">
								{sm.matches.toLocaleString()} of {sm.games_run.toLocaleString()} games
								({(sm.match_rate * 100).toFixed(1)}%) ended exactly {parsed.away} {sm.target_away}–{sm.target_home} {parsed.home}.
								Each cell reads <strong>prediction → score-matched{#if sm.has_boxscore} / actual{/if}</strong>.
								{#if !sm.has_boxscore}<em>real box score unavailable — projections only.</em>{/if}
							</div>
							{#if sm.has_boxscore && (sm.batter_accuracy_pct.hits != null || sm.base_vs_match_pct.hits != null)}
								<div class="acc-pct-summary">
									{#if sm.batter_accuracy_pct.hits != null}
										<div class="acc-pct-line">
											<span class="acc-pct-label">Score-matched vs. actual</span>
											<span class="acc-pct-chip {pctTone(sm.batter_accuracy_pct.hits)}">H {sm.batter_accuracy_pct.hits?.toFixed(0)}%</span>
											<span class="acc-pct-chip {pctTone(sm.batter_accuracy_pct.home_runs)}">HR {sm.batter_accuracy_pct.home_runs?.toFixed(0)}%</span>
											<span class="acc-pct-chip {pctTone(sm.batter_accuracy_pct.rbi)}">RBI {sm.batter_accuracy_pct.rbi?.toFixed(0)}%</span>
										</div>
									{/if}
									{#if sm.base_vs_match_pct.hits != null}
										<div class="acc-pct-line">
											<span class="acc-pct-label">Prediction vs. score-matched</span>
											<span class="acc-pct-chip {pctTone(sm.base_vs_match_pct.hits)}">H {sm.base_vs_match_pct.hits?.toFixed(0)}%</span>
											<span class="acc-pct-chip {pctTone(sm.base_vs_match_pct.home_runs)}">HR {sm.base_vs_match_pct.home_runs?.toFixed(0)}%</span>
											<span class="acc-pct-chip {pctTone(sm.base_vs_match_pct.rbi)}">RBI {sm.base_vs_match_pct.rbi?.toFixed(0)}%</span>
										</div>
									{/if}
								</div>
							{/if}
							<div class="table-scroll">
								<table class="acc-table acc-box-table">
									<thead>
										<tr><th class="acc-stat-h">Batter</th><th>H</th><th>HR</th><th>RBI</th></tr>
									</thead>
									<tbody>
										{#each sm.batters as b}
											<tr>
												<td class="acc-stat">
													{#if b.player_id > 0}<a class="player-link" href={`/players/${b.player_id}`}>{b.name}</a>{:else}{b.name}{/if}
													<span class="acc-team-tag">{b.team}</span>
												</td>
												<td>{#if b.base_hits != null}<span class="acc-base">{b.base_hits.toFixed(1)}→</span>{/if}{b.proj_hits.toFixed(1)}{#if b.actual_hits != null}<span class="acc-real"> / {b.actual_hits}</span>{/if}</td>
												<td>{#if b.base_home_runs != null}<span class="acc-base">{b.base_home_runs.toFixed(2)}→</span>{/if}{b.proj_home_runs.toFixed(2)}{#if b.actual_home_runs != null}<span class="acc-real"> / {b.actual_home_runs}</span>{/if}</td>
												<td>{#if b.base_rbi != null}<span class="acc-base">{b.base_rbi.toFixed(1)}→</span>{/if}{b.proj_rbi.toFixed(1)}{#if b.actual_rbi != null}<span class="acc-real"> / {b.actual_rbi}</span>{/if}</td>
											</tr>
										{/each}
									</tbody>
								</table>
							</div>
							{#if sm.batter_mae.hits != null}
								<div class="acc-mae">
									Avg. miss per batter (score-matched vs. actual) — H {sm.batter_mae.hits?.toFixed(2)} · HR {sm.batter_mae.home_runs?.toFixed(2)} · RBI {sm.batter_mae.rbi?.toFixed(2)}
								</div>
							{/if}
							<div class="acc-legend"><span class="acc-base">prediction→</span>score-matched{#if sm.has_boxscore} / <span class="acc-real">actual</span>{/if}</div>
						{/if}
					{:else}
						<div class="loading">Accuracy scoring becomes available once the game is final.</div>
					{/if}
				</div>
			</details>
		{/if}
	</div>
{/if}

{#if mode === 'preview'}
	<div class="preview">
		<div class="pcard">
			<div class="pcard-label">Game info</div>
			<div class="gi-rows">
				<div class="gi-row"><span class="gi-key">Stadium</span><span class="gi-val">{teamVenue(parsed.home)}</span></div>
				<div class="gi-row"><span class="gi-key">Home</span><span class="gi-val">{teamName(parsed.home)}</span></div>
				<div class="gi-row"><span class="gi-key">Away</span><span class="gi-val">{teamName(parsed.away)}</span></div>
				{#if statOf(homeStats, 'park_runs_factor') != null}
					<div class="gi-row"><span class="gi-key">Park factor</span><span class="gi-val">{statOf(homeStats, 'park_runs_factor')?.toFixed(2)} runs</span></div>
				{/if}
				<div class="gi-row"><span class="gi-key">Date</span><span class="gi-val">{fmtDate(parsed.date)}</span></div>
			</div>
		</div>

		{#if awayStats && homeStats}
			<div class="pcard">
				<div class="pcard-label">Team comparison</div>
				<div class="ts-grid-header">
					<div class="ts-col-hdr-outer"><TeamLogo abbr={parsed.away} size={22} /> <span class="ts-abbr">{parsed.away}</span></div>
					<div class="ts-col-hdr">Rnk</div>
					<div class="ts-col-hdr">Type</div>
					<div class="ts-col-hdr">Rnk</div>
					<div class="ts-col-hdr-outer ts-col-hdr-outer-r"><span class="ts-abbr">{parsed.home}</span> <TeamLogo abbr={parsed.home} size={22} /></div>
				</div>
				{#each COMPARE as row}
					{@const av = statOf(awayStats, row.key)}
					{@const hv = statOf(homeStats, row.key)}
					{#if av != null || hv != null}
						<div class="ts-row">
							<div class="ts-col-val"><span>{av != null ? row.fmt(av) : '—'}</span></div>
							<div class="ts-col-rk"><span class={`rk ${tier(rankOf(awayStats, row.key))}`}>{rankOf(awayStats, row.key) ?? '—'}</span></div>
							<div class="ts-col-lbl">{row.label}</div>
							<div class="ts-col-rk"><span class={`rk ${tier(rankOf(homeStats, row.key))}`}>{rankOf(homeStats, row.key) ?? '—'}</span></div>
							<div class="ts-col-val"><span>{hv != null ? row.fmt(hv) : '—'}</span></div>
						</div>
					{/if}
				{/each}
				<div class="ts-rk-key">
					<span class="key-item tier-elite">Top 5</span>
					<span class="key-item tier-good">Top 12</span>
					<span class="key-item tier-avg">Middle</span>
					<span class="key-item tier-poor">Bottom</span>
				</div>
			</div>
		{/if}

		<div class="pcard">
			<div class="pcard-label">Betting edge</div>
			<div class="odds-inputs">
				<label>Home ML <input type="number" bind:value={homeMl} /></label>
				<label>Away ML <input type="number" bind:value={awayMl} /></label>
				<label>Total <input type="number" step="0.5" bind:value={totalLine} /></label>
				<label>Kelly <input type="number" step="0.05" min="0.05" max="1" bind:value={kelly} /></label>
				<button class="btn" onclick={runBet} disabled={betting}>{betting ? 'Analyzing…' : 'Analyze'}</button>
			</div>
			{#if edges.length}
				<div class="table-scroll">
					<table class="etable">
						<thead>
							<tr><th>Market</th><th>Model</th><th>Implied</th><th>Edge</th><th>Stake</th><th>EV</th></tr>
						</thead>
						<tbody>
							{#each edges as e}
								<tr class:bet-row={e.recommended_stake_pct > 0}>
									<td class="mkt">{e.market}</td>
									<td>{(e.model_probability * 100).toFixed(1)}%</td>
									<td>{(e.implied_probability * 100).toFixed(1)}%</td>
									<td class:pos={e.edge > 0} class:neg={e.edge <= 0}>{(e.edge * 100).toFixed(1)}%</td>
									<td>{(e.recommended_stake_pct * 100).toFixed(2)}%</td>
									<td>{e.expected_value.toFixed(3)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</div>
	</div>
{:else if mode === 'prediction' && result && originalResult}
	<!-- ── Summary — always the base simulation, never the custom-score/stat run ── -->
	<section class="summary" id="summary">
		<table class="sim-table">
			<thead>
				<tr>
					<th class="sim-th away">{parsed.away} <span class="sim-side-label">Away</span></th>
					<th class="sim-th label"></th>
					<th class="sim-th home">{parsed.home} <span class="sim-side-label">Home</span></th>
				</tr>
			</thead>
			<tbody>
				<tr class="sim-row score-row">
					<td class="sim-val away" class:winval={awayWin}>{originalResult.away_run_mean.toFixed(1)}</td>
					<td class="sim-label">Proj. runs</td>
					<td class="sim-val home" class:winval={!awayWin}>{originalResult.home_run_mean.toFixed(1)}</td>
				</tr>
				<tr class="sim-row">
					<td class="sim-val away" class:winval={awayWin}>{awayProbPct}%</td>
					<td class="sim-label">Win %</td>
					<td class="sim-val home" class:winval={!awayWin}>{homeProbPct}%</td>
				</tr>
				<tr class="sim-row">
					<td class="sim-val away muted-val">{originalResult.away_run_p10.toFixed(0)}–{originalResult.away_run_p90.toFixed(0)}</td>
					<td class="sim-label">P10–P90</td>
					<td class="sim-val home muted-val">{originalResult.home_run_p10.toFixed(0)}–{originalResult.home_run_p90.toFixed(0)}</td>
				</tr>
				<tr class="sim-row divider-row">
					<td class="sim-val away muted-val">{originalResult.spread_mean >= 0 ? '+' : ''}{originalResult.spread_mean.toFixed(1)}</td>
					<td class="sim-label">Spread</td>
					<td class="sim-val home muted-val">{-originalResult.spread_mean >= 0 ? '+' : ''}{(-originalResult.spread_mean).toFixed(1)}</td>
				</tr>
				<tr class="sim-row">
					<td colspan="3" class="sim-center-row">
						<span class="sim-meta-pill">Total {originalResult.total_mean.toFixed(1)}</span>
						<span class="sim-meta-pill">Extras {(originalResult.extra_inning_pct * 100).toFixed(1)}%</span>
						<span class="sim-meta-pill">{originalResult.n.toLocaleString()} sims</span>
						{#if originalResult.home_win_probability_raw != null}
							<span class="sim-meta-pill cal-pill">CAL ✦ raw {(originalResult.home_win_probability_raw * 100).toFixed(1)}%</span>
						{/if}
					</td>
				</tr>
			</tbody>
		</table>
	</section>

	<!-- ── Custom final score → true conditioned Monte Carlo ── -->
	<div class="score-adjust" class:adjusted={scoreAdjusted}>
		<div class="sa-head">
			<span class="sa-title">Custom final score</span>
			<span class="sa-note">Set a final, then run a Monte Carlo of only the games that end that way</span>
		</div>
		<div class="sa-body">
			<div class="sa-team">
				<TeamLogo abbr={parsed.away} size={26} />
				<span class="sa-abbr">{parsed.away}</span>
				<div class="sa-stepper">
					<button aria-label="Away runs down" onclick={() => bumpAway(-1)} disabled={finalAway <= 0 || conditioning}>−</button>
					<span class="sa-num">{finalAway}</span>
					<button aria-label="Away runs up" onclick={() => bumpAway(1)} disabled={conditioning}>+</button>
				</div>
			</div>
			<span class="sa-at">–</span>
			<div class="sa-team">
				<TeamLogo abbr={parsed.home} size={26} />
				<span class="sa-abbr">{parsed.home}</span>
				<div class="sa-stepper">
					<button aria-label="Home runs down" onclick={() => bumpHome(-1)} disabled={finalHome <= 0 || conditioning}>−</button>
					<span class="sa-num">{finalHome}</span>
					<button aria-label="Home runs up" onclick={() => bumpHome(1)} disabled={conditioning}>+</button>
				</div>
			</div>
		</div>
		<div class="sa-actions">
			<button class="sa-run" onclick={runConditioned} disabled={conditioning || !canRunConditioned}>
				{conditioning ? 'Simulating…' : `Run ${finalAway}–${finalHome} final`}
			</button>
			{#if scoreAdjusted}
				<button class="sa-reset" onclick={resetScore} disabled={conditioning}>Reset to projection</button>
			{/if}
		</div>
		{#if conditionError}
			<div class="sa-error">{conditionError}</div>
		{:else if conditionInfo}
			<div class="sa-meta">
				Averaged over <strong>{conditionInfo.matches.toLocaleString()}</strong> simulated games that ended
				{conditionInfo.target_away}–{conditionInfo.target_home}
				<span class="sa-meta-dim">(of {conditionInfo.games_run.toLocaleString()} run)</span>
			</div>
		{/if}
	</div>

	<!-- ── Scoring (representative line score) ── -->
	{#if result.representative}
		{@const rep = result.representative}
		<details class="block" id="scoring" open>
			<summary>Scoring <span class="muted-inline">· {conditionInfo ? 'a simulated game with this final' : 'representative game (closest to mean)'}</span></summary>
			<div class="block-body">
				<div class="table-scroll">
					<table class="qtable">
						<thead>
							<tr>
								<th class="qname">Team</th>
								{#each rep.away_by_inning as _, i}<th>{i + 1}</th>{/each}
								<th class="qtotal">R</th>
							</tr>
						</thead>
						<tbody>
							<tr>
								<td class="qname">{parsed.away}</td>
								{#each rep.away_by_inning as r}<td>{r}</td>{/each}
								<td class="qtotal">{rep.away_score}</td>
							</tr>
							<tr>
								<td class="qname">{parsed.home}</td>
								{#each rep.home_by_inning as r}<td>{r}</td>{/each}
								<td class="qtotal">{rep.home_score}</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>
		</details>
	{/if}

	<!-- ── Leaders ── -->
	<details class="block" id="leaders" open>
		<summary>Leaders <span class="muted-inline">· {conditionInfo ? `games ending ${conditionInfo.target_away}–${conditionInfo.target_home}` : 'projected per game'}</span></summary>
		<div class="block-body">
			<div class="leaders-grid">
				{#each [parsed.away, parsed.home] as team}
					<div class="leaders-team">
						<div class="leaders-team-header"><TeamLogo abbr={team} size={20} /> {team}</div>
						<div class="leaders-row">
							{#each leadersFor(team) as l}
								<div class="leader">
									<div class="leader-cat">{l.cat}</div>
									<div class="leader-photo-wrap"><PlayerPhoto playerId={l.player.player_id} name={String(l.player.name ?? '')} size={44} /></div>
									<div class="leader-name"><a class="player-link" href={`/players/${l.player.player_id}`}>{l.player.name}</a></div>
									<div class="leader-main">{l.main}</div>
									<div class="leader-subs"><span class="leader-sub">{l.sub}</span></div>
								</div>
							{/each}
						</div>
					</div>
				{/each}
			</div>
		</div>
	</details>

	<!-- ── Box score (editable) ── -->
	<details class="block" id="boxscore" open>
		<summary>Box score <span class="muted-inline">· {conditionInfo ? `avg over games ending ${conditionInfo.target_away}–${conditionInfo.target_home}` : 'edit H / HR / RBI / BB / K, then re-run'}</span></summary>
		<div class="block-body">
			<div class="box-tabs">
				<button class:active={boxTeam === 'away'} onclick={() => (boxTeam = 'away')}>{parsed.away}</button>
				<button class:active={boxTeam === 'home'} onclick={() => (boxTeam = 'home')}>{parsed.home}</button>
				{#if result.lineups}
					{@const st = boxTeam === 'away' ? result.lineups.away : result.lineups.home}
					<span class="lineup-badge" class:confirmed={st.confirmed} title={st.confirmed ? 'Official MLB lineup' : 'Not yet posted by MLB — estimated from the roster, batting order and starters may change'}>
						{st.confirmed ? '✓ Confirmed lineup' : '◷ Projected lineup'}
					</span>
				{/if}
			</div>
			{#if result.lineups && !(boxTeam === 'away' ? result.lineups.away.confirmed : result.lineups.home.confirmed)}
				<div class="lineup-note">
					MLB hasn't posted this lineup yet — it's a projection from the roster, so the batting order and starters may change. It updates automatically once the official card is out.
				</div>
			{/if}
			<div class="stat-block">
				<div class="stat-block-label">Batting <span class="edit-hint">· tap a number to adjust it, then re-run · RBI is an approximate power nudge</span></div>
				<div class="table-scroll">
					<table class="stat-table">
						<thead>
							<tr>
								<th class="name-col">Player</th><th class="pos-col">Pos</th><th>PA</th><th>H</th><th>HR</th><th>RBI</th><th>BB</th><th>K</th>
							</tr>
						</thead>
						<tbody>
							{#each boxLines as p (p.player_id)}
								<tr>
									<td class="name-col"><a class="player-link" href={`/players/${p.player_id}`}>{p.name}</a></td>
									<!-- Blank rather than a dash when unknown: an empty cell reads as
									     "not recorded", a placeholder reads as a position. Dimmed when
									     it's his usual position rather than tonight's card — the DH
									     only exists on the card, so without that distinction a lineup
									     of nine fielders looks like a posted one. -->
									<td
										class="pos-col"
										class:pos-usual={p.position_source === 'roster'}
										title={p.position_source === 'roster'
											? 'Usual position — MLB has not posted this lineup yet, so the DH is not assigned'
											: undefined}>{p.position ?? ''}</td>
									<td class="ro-cell">{(p.pa as number).toFixed(1)}</td>
									{#each ['hits', 'home_runs'] as stat}
										<td class="edit-cell">
											<button type="button" class="stat-cell" class:edited={isEdited(p.player_id, stat)}
												disabled={editRunning}
												onclick={() => openEditor('batter', p.player_id, p.name ?? String(p.player_id), stat)}>{cellValue(p, stat)}</button>
										</td>
									{/each}
									<td class="edit-cell">
										<button type="button" class="stat-cell" class:edited={isEdited(p.player_id, 'rbi')}
											disabled={editRunning}
											onclick={() => openEditor('batter', p.player_id, p.name ?? String(p.player_id), 'rbi')}>{cellValue(p, 'rbi')}</button>
									</td>
									{#each ['bb', 'k'] as stat}
										<td class="edit-cell">
											<button type="button" class="stat-cell" class:edited={isEdited(p.player_id, stat)}
												disabled={editRunning}
												onclick={() => openEditor('batter', p.player_id, p.name ?? String(p.player_id), stat)}>{cellValue(p, stat)}</button>
										</td>
									{/each}
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
				<div class="edit-actions">
					<button class="edit-run" onclick={runWithEdits} disabled={!hasEdits || editRunning}>
						{editRunning ? 'Simulating…' : 'Re-run with edits'}
					</button>
					{#if hasEdits}
						<button class="edit-clear" onclick={clearEdits} disabled={editRunning}>Clear edits</button>
					{/if}
					{#if editError}<span class="edit-err">{editError}</span>{/if}
				</div>
			</div>
			{#if boxPitchers.length}
				<div class="stat-block">
					<div class="stat-block-label">Pitching <span class="edit-hint">· tap a number to adjust it, then re-run</span></div>
					<div class="table-scroll">
						<table class="stat-table">
							<thead>
								<tr>
									<th class="name-col">Pitcher</th><th>IP</th><th>P</th><th>H</th><th>ER</th><th>BB</th><th>K</th><th>HR</th>
								</tr>
							</thead>
							<tbody>
								{#each boxPitchers as p (p.player_id)}
									<tr>
										<td class="name-col">
											{#if p.player_id > 0}
												<a class="player-link" href={`/players/${p.player_id}`}>{p.name}</a>
											{:else}
												{p.name}
											{/if}
										</td>
										<td class="ro-cell">{p.ip.toFixed(1)}</td>
										<td class="ro-cell">{fmtCount(p.pitches)}</td>
										{#if pitcherEditable(p)}
											<td class="edit-cell">
												<button type="button" class="stat-cell" class:edited={isPitcherEdited(p.player_id, 'hits_allowed')}
													disabled={editRunning}
													onclick={() => openEditor('pitcher', p.player_id, p.name ?? String(p.player_id), 'hits_allowed')}>{pitcherCellValue(p, 'hits_allowed')}</button>
											</td>
										{:else}
											<td class="ro-cell">{p.hits_allowed.toFixed(1)}</td>
										{/if}
										<td class="ro-cell">{p.er.toFixed(2)}</td>
										{#each ['bb_allowed', 'k', 'hr_allowed'] as stat}
											{#if pitcherEditable(p)}
												<td class="edit-cell">
													<button type="button" class="stat-cell" class:edited={isPitcherEdited(p.player_id, stat)}
														disabled={editRunning}
														onclick={() => openEditor('pitcher', p.player_id, p.name ?? String(p.player_id), stat)}>{pitcherCellValue(p, stat)}</button>
												</td>
											{:else}
												<td class="ro-cell">{(p[stat] as number).toFixed(1)}</td>
											{/if}
										{/each}
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				</div>
			{/if}
		</div>
	</details>

	<!-- ── Game log ── -->
	{#if result.representative && result.representative.play_log.length}
		<details class="block" id="gamelog">
			<summary>Game log <span class="muted-inline">· one representative simulated game</span></summary>
			<div class="block-body">
				<div class="gamelog">
					{#each logGroups as g}
						<div class="log-inning">{g.label}</div>
						{#each g.entries as e}
							<div class="log-line" class:log-scoring={e.runs > 0}>
								<span class="log-batter">{e.batter}</span>
								<span class="log-out">{OUTCOME_LABEL[e.outcome] ?? e.outcome}</span>
								{#if e.runs > 0}<span class="log-runs">+{e.runs} R</span>{/if}
							</div>
						{/each}
					{/each}
				</div>
			</div>
		</details>
	{/if}

	<!-- ── Distributions ── -->
	<details class="block" id="distributions" open>
		<summary>Score distributions</summary>
		<div class="block-body">
			<p class="charts-hint">
				Distribution of runs across {result.n.toLocaleString()} simulated games. The dashed line marks the mean.
			</p>
			<div class="dist-picker">
				<select class="dist-select" bind:value={distPick}>
					<option value="totals">Total runs</option>
					<option value="away_runs">{parsed.away} runs</option>
					<option value="home_runs">{parsed.home} runs</option>
				</select>
			</div>
			<div class="dist-chart">
				{#if distHist}
					<DistChart hist={distHist} title={distTitle} mean={distMean} />
				{/if}
			</div>
		</div>
	</details>
{#if editTarget}
	<StatEditor
		who={editTarget.who}
		label={STAT_LABEL[editTarget.stat] ?? editTarget.stat}
		value={editValue}
		base={editBase}
		step={tickStep(editTarget.stat)}
		onset={setEditorValue}
		onreset={resetEditorValue}
		onclose={closeEditor}
	/>
{/if}

{:else if mode === 'prediction'}
	<div class="run-prompt">
		<p class="run-prompt-text">The simulation didn't come back — try again.</p>
		<button class="run-prompt-btn" onclick={runSimulation} disabled={simRunning}>
			{simRunning ? 'Simulating…' : 'Run simulation'}
		</button>
	</div>
{/if}

<style>
	.back-row {
		display: flex;
		justify-content: flex-start;
		align-items: center;
		gap: 0.75rem;
		margin-bottom: 1.5rem;
	}
	.back {
		color: #fff;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		font-size: 0.78rem;
		font-weight: 800;
		text-decoration: none;
	}
	.back:hover {
		color: var(--text-2);
	}
	.back-divider {
		color: #2e3dda;
		font-weight: 800;
	}
	.jump-wrap {
		position: relative;
	}
	.jump-btn {
		color: #fff;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		cursor: pointer;
		white-space: nowrap;
		background: none;
		border: none;
		padding: 0;
		font-family: inherit;
		font-size: 0.78rem;
		font-weight: 800;
	}
	.jump-arrow {
		color: var(--accent-pred);
	}
	.jump-menu {
		z-index: 30;
		background: var(--bg-card);
		border: 1px solid var(--border);
		border-radius: 8px;
		display: flex;
		flex-direction: column;
		gap: 0.1rem;
		min-width: 11rem;
		padding: 0.35rem;
		position: absolute;
		top: calc(100% + 0.35rem);
		left: 0;
		box-shadow: 0 8px 24px #00000080;
	}
	.jump-item {
		color: var(--text-2);
		letter-spacing: 0.04em;
		white-space: nowrap;
		border-radius: 5px;
		border: none;
		background: none;
		text-align: left;
		cursor: pointer;
		padding: 0.5rem 0.7rem;
		font-size: 0.82rem;
		font-weight: 700;
	}
	.jump-item:hover {
		background: var(--border-input);
		color: var(--text);
	}

	.hero {
		display: grid;
		grid-template-columns: 1fr auto 1fr;
		align-items: center;
		gap: 1.5rem;
		margin-bottom: 2rem;
		padding: 1rem 0 2rem;
		position: relative;
	}
	.hero::after {
		content: '';
		background: #2e3dda;
		width: 100vw;
		height: 2px;
		position: absolute;
		bottom: 0;
		left: 50%;
		transform: translateX(-50%);
	}
	.hero-status {
		grid-column: 1 / -1;
		justify-self: center;
		color: var(--text-label);
		letter-spacing: 0.08em;
		text-transform: uppercase;
		display: flex;
		align-items: center;
		gap: 0.45rem;
		margin-bottom: 0.5rem;
		font-size: 0.72rem;
		font-weight: 800;
	}
	.hero-status.is-live {
		color: var(--accent-actual, #00fff2);
	}
	.hero-status.is-final {
		color: var(--text-2);
	}
	.live-dot {
		background: #ff3b3b;
		border-radius: 50%;
		width: 7px;
		height: 7px;
		display: inline-block;
		animation: pulse 1.4s ease-in-out infinite;
	}
	@keyframes pulse {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.35; }
	}
	.hero-team {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.4rem;
	}
	.hero-abbr {
		letter-spacing: 0.06em;
		text-transform: uppercase;
		font-size: 1.6rem;
		font-weight: 800;
	}
	.hero-real-score {
		color: var(--text);
		font-variant-numeric: tabular-nums;
		font-size: 2.4rem;
		font-weight: 900;
		line-height: 1;
	}
	.hero-real-score.trail {
		color: var(--text-label);
	}
	.hero-label {
		text-transform: uppercase;
		letter-spacing: 0.1em;
		color: var(--text-label);
		font-size: 0.7rem;
		font-weight: 700;
	}
	.hero-ml.fav {
		color: var(--accent-pred);
	}
	.hero-center {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.25rem;
	}
	/* ── Post-game accuracy ── */
	.acc-call {
		display: flex;
		align-items: center;
		gap: 0.7rem;
		padding: 0.6rem 0.8rem;
		border-radius: 8px;
		background: #0a1020;
		border: 1px solid var(--border);
		margin-bottom: 0.8rem;
	}
	.acc-call.hit {
		border-color: color-mix(in srgb, var(--accent-actual, #00d68f) 55%, var(--border));
	}
	.acc-call.miss {
		border-color: color-mix(in srgb, #ff5a6a 45%, var(--border));
	}
	.acc-call-icon {
		font-size: 1.5rem;
		font-weight: 900;
		line-height: 1;
	}
	.acc-call.hit .acc-call-icon {
		color: var(--accent-actual, #00d68f);
	}
	.acc-call.miss .acc-call-icon {
		color: #ff5a6a;
	}
	.acc-call-head {
		font-weight: 800;
		font-size: 0.95rem;
		color: var(--text);
	}
	.acc-call-sub {
		color: var(--text-label);
		font-size: 0.78rem;
		font-weight: 600;
		margin-top: 0.1rem;
	}
	.acc-table {
		width: 100%;
		border-collapse: collapse;
		font-variant-numeric: tabular-nums;
	}
	.acc-table th {
		color: var(--text-label);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		text-align: right;
		font-size: 0.6rem;
		font-weight: 700;
		padding: 0 0.4rem 0.3rem;
	}
	.acc-table th.acc-stat-h {
		text-align: left;
	}
	.acc-table td {
		text-align: right;
		font-size: 0.85rem;
		font-weight: 700;
		color: var(--text);
		padding: 0.2rem 0.4rem;
		border-top: 1px solid var(--border);
	}
	.acc-table td.acc-stat {
		text-align: left;
		color: var(--text-2);
		font-weight: 800;
	}
	.acc-range {
		color: var(--text-label);
		font-weight: 600;
	}
	.acc-range.within {
		color: var(--accent-actual, #00d68f);
	}
	.acc-actual {
		color: var(--accent-actual, #00d68f);
		font-weight: 900;
	}
	.acc-pos {
		color: #ffb020;
	}
	.acc-neg {
		color: #57b6ff;
	}
	.acc-exact {
		color: var(--text-2);
		font-size: 0.82rem;
		font-weight: 600;
		margin-top: 0.7rem;
		padding: 0.5rem 0.7rem;
		background: #0a1020;
		border-radius: 6px;
	}
	.acc-exact strong {
		color: var(--accent-pred);
		font-weight: 900;
	}
	.acc-sub-head {
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-label);
		font-size: 0.68rem;
		font-weight: 800;
		margin: 1rem 0 0.35rem;
	}
	.acc-sub-note {
		color: var(--text-label);
		font-size: 0.76rem;
		font-weight: 600;
		margin-bottom: 0.5rem;
		line-height: 1.4;
	}
	.acc-sub-note em {
		color: var(--text-2);
	}
	.acc-team-tag {
		color: var(--text-label);
		font-size: 0.62rem;
		font-weight: 800;
		text-transform: uppercase;
		margin-left: 0.35rem;
	}
	.acc-real {
		color: var(--accent-actual, #00d68f);
		font-weight: 900;
	}
	.acc-mae {
		color: var(--text-2);
		font-size: 0.78rem;
		font-weight: 700;
		margin-top: 0.5rem;
	}
	.acc-legend {
		color: var(--text-label);
		font-size: 0.68rem;
		font-weight: 600;
		margin-top: 0.3rem;
	}
	/* ── Run Live Sim ── */
	.live-sim-block {
		border-color: color-mix(in srgb, var(--accent-actual, #00d68f) 35%, var(--border));
	}
	.ls-actions {
		display: flex;
		align-items: center;
		gap: 0.7rem;
		flex-wrap: wrap;
		margin-bottom: 0.7rem;
	}
	.ls-run {
		background: var(--accent-actual, #00d68f);
		color: #04121c;
		border: none;
		border-radius: 7px;
		padding: 0.45rem 0.9rem;
		font-size: 0.82rem;
		font-weight: 800;
		cursor: pointer;
	}
	.ls-run:disabled {
		opacity: 0.55;
		cursor: default;
	}
	.ls-auto {
		display: inline-flex;
		align-items: center;
		gap: 0.3rem;
		color: var(--text-2);
		font-size: 0.75rem;
		font-weight: 700;
		cursor: pointer;
	}
	.ls-stamp {
		color: var(--text-label);
		font-size: 0.7rem;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}
	.ls-idle,
	.ls-note {
		color: var(--text-label);
		font-size: 0.76rem;
		font-weight: 600;
		line-height: 1.45;
	}
	.ls-from {
		color: var(--text-2);
		font-size: 0.8rem;
		font-weight: 600;
		line-height: 1.45;
		padding: 0.5rem 0.7rem;
		background: #0a1020;
		border-radius: 6px;
		margin-bottom: 0.7rem;
	}
	.ls-from strong {
		color: var(--text);
		font-weight: 900;
	}
	.ls-win {
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
		margin-bottom: 0.8rem;
	}
	.ls-win-row {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}
	.ls-win-team {
		min-width: 3rem;
		color: var(--text-2);
		font-size: 0.78rem;
		font-weight: 900;
		text-transform: uppercase;
		font-style: italic;
	}
	.ls-bar {
		flex: 1;
		height: 12px;
		border-radius: 6px;
		background: #0a1020;
		overflow: hidden;
	}
	.ls-bar-fill {
		height: 100%;
		border-radius: 6px;
	}
	/* Two clearly distinct hues — the theme's pred/actual accents are both
	   green-cyan and read as the same colour side by side. */
	.ls-bar-fill.home {
		background: var(--accent-actual, #00fff2);
	}
	.ls-bar-fill.away {
		background: #ffb020;
	}
	.ls-win-pct {
		min-width: 3.4rem;
		text-align: right;
		font-size: 0.9rem;
		font-weight: 900;
		font-variant-numeric: tabular-nums;
		color: var(--text);
	}
	.ls-extras {
		color: var(--text-label);
		font-size: 0.7rem;
		font-weight: 600;
		line-height: 1.4;
		margin-top: 0.15rem;
	}
	.ls-grid {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 0.5rem;
		margin-bottom: 0.4rem;
	}
	.ls-cell {
		background: #0a1020;
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: 0.5rem 0.4rem;
		text-align: center;
	}
	.ls-cell-val {
		font-size: 1.05rem;
		font-weight: 900;
		font-variant-numeric: tabular-nums;
		color: var(--text);
	}
	.ls-cell-key {
		color: var(--text-label);
		font-size: 0.58rem;
		font-weight: 800;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		margin-top: 0.15rem;
	}
	.ls-sub-head {
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-label);
		font-size: 0.68rem;
		font-weight: 800;
		margin: 0.9rem 0 0.35rem;
	}
	.ls-finals {
		display: flex;
		gap: 0.4rem;
		flex-wrap: wrap;
	}
	.ls-final {
		display: flex;
		flex-direction: column;
		align-items: center;
		background: #0a1020;
		border: 1px solid var(--border);
		border-radius: 7px;
		padding: 0.35rem 0.6rem;
	}
	.ls-final-score {
		font-size: 0.85rem;
		font-weight: 900;
		font-variant-numeric: tabular-nums;
		color: var(--text);
	}
	.ls-final-pct {
		color: var(--accent-pred);
		font-size: 0.65rem;
		font-weight: 800;
		font-variant-numeric: tabular-nums;
	}
	@media (max-width: 560px) {
		.ls-grid {
			grid-template-columns: 1fr;
		}
	}
	/* Headline accuracy percentages */
	.acc-scorecard {
		display: flex;
		gap: 0.5rem;
		margin-bottom: 0.5rem;
	}
	.acc-chip {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.1rem;
		padding: 0.5rem 0.4rem;
		border-radius: 8px;
		background: #0a1020;
		border: 1px solid var(--border);
	}
	.acc-chip-val {
		font-size: 1.35rem;
		font-weight: 900;
		line-height: 1;
		font-variant-numeric: tabular-nums;
		color: var(--text);
	}
	.acc-chip-key {
		font-size: 0.6rem;
		font-weight: 800;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-label);
	}
	.acc-chip.good,
	.acc-pct-chip.good {
		border-color: color-mix(in srgb, var(--accent-actual, #00d68f) 55%, var(--border));
	}
	.acc-chip.good .acc-chip-val {
		color: var(--accent-actual, #00d68f);
	}
	.acc-chip.ok .acc-chip-val {
		color: #ffb020;
	}
	.acc-chip.bad,
	.acc-pct-chip.bad {
		border-color: color-mix(in srgb, #ff5a6a 45%, var(--border));
	}
	.acc-chip.bad .acc-chip-val {
		color: #ff5a6a;
	}
	.acc-chip-note {
		color: var(--text-label);
		font-size: 0.68rem;
		font-weight: 600;
		line-height: 1.35;
		margin-bottom: 0.8rem;
	}
	.acc-pctcol {
		font-weight: 900;
		font-variant-numeric: tabular-nums;
	}
	.acc-pctcol.good {
		color: var(--accent-actual, #00d68f);
	}
	.acc-pctcol.ok {
		color: #ffb020;
	}
	.acc-pctcol.bad {
		color: #ff5a6a;
	}
	.acc-ou {
		color: var(--text-2);
		font-size: 0.8rem;
		font-weight: 600;
		margin-top: 0.6rem;
	}
	.acc-ou strong {
		color: var(--accent-pred);
		font-weight: 900;
	}
	/* Per-stat accuracy % chips in the score-match block */
	.acc-pct-summary {
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
		margin-bottom: 0.6rem;
	}
	.acc-pct-line {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		flex-wrap: wrap;
	}
	.acc-pct-label {
		color: var(--text-label);
		font-size: 0.68rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		min-width: 12rem;
	}
	.acc-pct-chip {
		font-size: 0.72rem;
		font-weight: 800;
		font-variant-numeric: tabular-nums;
		padding: 0.12rem 0.45rem;
		border-radius: 5px;
		background: #0a1020;
		border: 1px solid var(--border);
		color: var(--text);
	}
	.acc-pct-chip.good {
		color: var(--accent-actual, #00d68f);
	}
	.acc-pct-chip.ok {
		color: #ffb020;
	}
	/* Base (overall) projection prefix, muted before the score-matched value */
	.acc-base {
		color: var(--text-label);
		font-weight: 600;
	}
	.hero-at {
		color: var(--text-label);
		font-size: 1.6rem;
		font-weight: 300;
	}
	.hero-meta {
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--text-label);
		font-size: 0.78rem;
		font-weight: 700;
	}
	.hero-dh {
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--accent-pred);
		font-size: 0.62rem;
		font-weight: 800;
		margin-top: 0.2rem;
	}
	.hero-winbar {
		grid-column: 1 / -1;
		width: 100%;
		max-width: 440px;
		margin: 1rem auto 0;
	}
	.hwb-labels {
		color: var(--text-label);
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		margin-bottom: 0.4rem;
		font-size: 0.78rem;
		font-weight: 700;
	}
	.hwb-labels .lead {
		color: var(--accent-pred);
	}
	.hwb-cap {
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--text-dim);
		font-size: 0.6rem;
		font-weight: 700;
	}
	.hwb-sims {
		text-transform: none;
		letter-spacing: 0;
		font-weight: 600;
		opacity: 0.8;
	}
	.hwb-track {
		background: var(--bg-surface);
		border-radius: 3px;
		height: 6px;
		display: flex;
		overflow: hidden;
	}
	.hwb-fill {
		height: 100%;
		transition: width 0.3s;
	}

	.mode-tabs {
		display: flex;
		justify-content: center;
		align-items: center;
		gap: 0.25rem;
		margin-bottom: 1.75rem;
	}
	.mode-divider {
		color: var(--slate);
		user-select: none;
		font-size: 0.9rem;
		font-weight: 800;
	}
	.mode-tab {
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--slate);
		cursor: pointer;
		background: none;
		border: none;
		padding: 0.35rem 0.9rem;
		font-size: 0.905rem;
		font-weight: 800;
		transition: color 0.15s;
	}
	.mode-tab:hover {
		color: var(--text-label);
	}
	.tab-preview.active {
		color: var(--text);
	}
	.tab-predicted.active {
		color: var(--accent-pred);
	}
	.tab-live {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
	}
	.tab-live.active {
		color: var(--accent-actual, #00fff2);
	}

	.error {
		color: var(--danger);
		margin: 1rem 0;
	}
	.loading {
		color: var(--text-label);
		display: flex;
		align-items: center;
		gap: 0.7rem;
		padding: 2rem 0;
		font-size: 0.95rem;
	}
	.run-prompt {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 1rem;
		padding: 3rem 0;
		text-align: center;
	}
	.run-prompt-text {
		color: var(--text-label);
		font-size: 0.92rem;
		margin: 0;
	}
	.run-prompt-btn {
		background: var(--accent-pred);
		color: #04240a;
		border: none;
		padding: 0.65rem 1.6rem;
		border-radius: 5px;
		cursor: pointer;
		font-size: 0.9rem;
		font-weight: 800;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}
	.run-prompt-btn:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}
	.spinner {
		border: 2px solid var(--border-input);
		border-top-color: var(--accent-pred);
		border-radius: 50%;
		width: 1.1rem;
		height: 1.1rem;
		animation: spin 0.7s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	/* ── Preview cards ── */
	.preview {
		display: flex;
		flex-direction: column;
		gap: 0.85rem;
	}
	.pcard {
		border: 1px solid var(--border);
		background: #0c1428;
		border-radius: 8px;
		padding: 1.15rem;
		box-shadow: 0 2px 10px #00000059;
	}
	.pcard-label {
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: #fff;
		margin-bottom: 1rem;
		font-size: 0.82rem;
		font-weight: 900;
	}
	.gi-rows {
		display: flex;
		flex-direction: column;
		gap: 0.55rem;
	}
	.gi-row {
		display: flex;
		justify-content: space-between;
		gap: 1rem;
		font-size: 0.88rem;
	}
	.gi-key {
		color: var(--text-label);
		text-transform: uppercase;
		letter-spacing: 0.06em;
		font-size: 0.72rem;
		font-weight: 700;
		padding-top: 0.15rem;
	}
	.gi-val {
		color: var(--text-2);
		font-weight: 600;
		text-align: right;
	}

	.ts-grid-header,
	.ts-row {
		display: grid;
		grid-template-columns: 1fr 3rem minmax(6rem, auto) 3rem 1fr;
		align-items: center;
		gap: 0.5rem;
	}
	.ts-grid-header {
		border-bottom: 1px solid var(--border);
		padding-bottom: 0.6rem;
		margin-bottom: 0.35rem;
	}
	.ts-col-hdr-outer {
		display: flex;
		align-items: center;
		gap: 0.45rem;
		font-weight: 800;
	}
	.ts-col-hdr-outer-r {
		justify-content: flex-end;
	}
	.ts-abbr {
		font-size: 0.95rem;
		font-weight: 800;
	}
	.ts-col-hdr {
		color: var(--text-label);
		text-transform: uppercase;
		letter-spacing: 0.06em;
		font-size: 0.62rem;
		font-weight: 700;
		text-align: center;
	}
	.ts-row {
		padding: 0.45rem 0;
		border-bottom: 1px solid var(--border-faint);
	}
	.ts-row:last-of-type {
		border-bottom: none;
	}
	.ts-col-val {
		font-variant-numeric: tabular-nums;
		font-weight: 700;
		font-size: 0.92rem;
	}
	.ts-col-val:last-child {
		text-align: right;
	}
	.ts-col-lbl {
		color: var(--text-label);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-size: 0.68rem;
		font-weight: 700;
		text-align: center;
	}
	.ts-col-rk {
		text-align: center;
	}
	.rk {
		display: inline-block;
		min-width: 1.9rem;
		border-radius: 4px;
		padding: 0.12rem 0.3rem;
		font-size: 0.72rem;
		font-weight: 800;
		font-variant-numeric: tabular-nums;
	}
	.tier-elite {
		color: #052;
		background: var(--accent-pred);
	}
	.tier-good {
		color: #dfffd0;
		background: #2c5c17;
	}
	.tier-avg {
		color: var(--text-2);
		background: var(--bg-badge);
	}
	.tier-poor {
		color: #ffd9cf;
		background: #5c2317;
	}
	.ts-rk-key {
		display: flex;
		gap: 0.5rem;
		flex-wrap: wrap;
		margin-top: 0.9rem;
	}
	.key-item {
		border-radius: 4px;
		padding: 0.15rem 0.5rem;
		font-size: 0.62rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.odds-inputs {
		display: flex;
		gap: 0.8rem;
		flex-wrap: wrap;
		align-items: end;
		margin-bottom: 1rem;
	}
	.odds-inputs label {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		color: var(--text-label);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-size: 0.68rem;
		font-weight: 700;
	}
	.odds-inputs input {
		background: var(--bg-surface);
		border: 1px solid var(--border-input);
		color: var(--text);
		padding: 0.45rem 0.55rem;
		border-radius: 5px;
		font-size: 0.95rem;
		width: 90px;
	}
	.btn {
		background: var(--bg-badge);
		color: var(--text);
		border: 1px solid var(--border-input);
		padding: 0.5rem 1rem;
		border-radius: 5px;
		cursor: pointer;
		font-size: 0.85rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}
	.btn:hover:not(:disabled) {
		border-color: var(--accent-pred);
		color: var(--accent-pred);
	}
	.btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.table-scroll {
		overflow-x: auto;
		-webkit-overflow-scrolling: touch;
	}
	.etable {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.88rem;
		font-variant-numeric: tabular-nums;
	}
	.etable th {
		color: var(--text-label);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-size: 0.68rem;
		font-weight: 700;
		text-align: right;
		padding: 0.4rem 0.55rem;
		border-bottom: 1px solid var(--border);
	}
	.etable td {
		text-align: right;
		padding: 0.45rem 0.55rem;
		border-bottom: 1px solid var(--border-faint);
	}
	.etable th:first-child,
	.etable td:first-child {
		text-align: left;
	}
	.mkt {
		font-weight: 700;
	}
	.bet-row {
		background: color-mix(in srgb, var(--accent-pred) 7%, transparent);
	}
	.pos {
		color: var(--accent-pred);
	}
	.neg {
		color: var(--danger);
	}

	/* ── Live / box score ── */
	.live-panel {
		display: flex;
		flex-direction: column;
		gap: 1.25rem;
	}
	.box-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.88rem;
		font-variant-numeric: tabular-nums;
	}
	.box-table th {
		color: var(--text-label);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-size: 0.66rem;
		font-weight: 700;
		text-align: center;
		padding: 0.5rem 0.6rem;
		border-bottom: 1px solid var(--border);
	}
	.box-table td {
		text-align: center;
		padding: 0.55rem 0.6rem;
		border-bottom: 1px solid var(--border-faint);
		font-weight: 700;
	}
	.box-team-col {
		text-align: left !important;
		font-weight: 800;
		white-space: nowrap;
	}
	.box-team-inner {
		display: inline-flex;
		align-items: center;
		gap: 0.5rem;
	}
	th.box-total,
	td.box-total {
		border-left: 1px solid var(--border);
		color: var(--text);
		font-weight: 900;
	}
	/* ── Next at-bat ──────────────────────────────────────────────────────
	   Three colours do all the work and they map to the three things that can
	   happen to a count, not to good/bad: strike, ball, ball in play. Nothing
	   here should suggest an outcome is desirable — the same pitch is good
	   news for one dugout and bad for the other. */
	.nab-head {
		margin-bottom: 0.8rem;
	}
	.nab-who {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 0.45rem;
	}
	.nab-label {
		font-size: 0.6rem;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--text-label);
		border: 1px solid var(--border);
		border-radius: 999px;
		padding: 0.1rem 0.45rem;
	}
	.nab-batter,
	.nab-pitcher {
		font-size: 0.95rem;
		font-weight: 600;
	}
	.nab-vs {
		color: var(--text-dim);
		font-size: 0.75rem;
	}
	.nab-hands {
		font-size: 0.65rem;
		color: var(--text-label);
	}
	.nab-sub {
		margin-top: 0.25rem;
		font-size: 0.7rem;
		color: var(--text-dim);
	}
	/* The count, treated as part of the subject line rather than as detail —
	   the same hitter at 0-0 and at 1-2 is two different propositions. */
	.nab-oncount {
		font-size: 0.7rem;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		color: var(--text-dim);
		border: 1px solid var(--border);
		border-radius: 4px;
		padding: 0.05rem 0.35rem;
	}
	/* A forecast built on a league baseline rather than this player's own line.
	   Caveat-coloured so it reads as a qualification of the number beside it,
	   not as another fact about the matchup. */
	.nab-standin {
		font-size: 0.58rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--caveat);
		border: 1px solid var(--caveat);
		border-radius: 4px;
		padding: 0.05rem 0.3rem;
		opacity: 0.85;
	}
	/* What the count has already done. Neutral in colour on purpose: a rising
	   strikeout chance is good news for one dugout and bad for the other, and
	   nothing here should take a side. */
	.nab-was {
		font-size: 0.58rem;
		color: var(--text-label);
		font-variant-numeric: tabular-nums;
		margin-top: 0.15rem;
	}
	.nab-outcomes {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
		margin-bottom: 0.9rem;
	}
	.nab-out {
		flex: 1 1 5.5rem;
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 0.45rem 0.55rem;
		background: var(--bg-badge);
		display: flex;
		flex-direction: column;
		gap: 0.1rem;
	}
	.nab-out-v {
		font-size: 1.05rem;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}
	.nab-out-k {
		font-size: 0.62rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-label);
	}
	.nab-out.ip {
		border-left: 2px solid #4a9d6f;
	}
	.nab-out.k {
		border-left: 2px solid #c2604a;
	}
	.nab-out.bb {
		border-left: 2px solid #5b7fc4;
	}
	.nab-out.hbp,
	.nab-out.pitches {
		border-left: 2px solid var(--border);
	}
	/* How long the at-bat runs, as a count of pitches rather than one more
	   percentage. It sat in the tile row before and read as a probability. */
	.nab-estimate {
		display: flex;
		align-items: baseline;
		gap: 0.5rem;
		padding: 0.5rem 0.7rem;
		margin-bottom: 0.6rem;
		border: 1px solid var(--border);
		border-left: 2px solid var(--accent-pred);
		border-radius: 6px;
		background: var(--bg-badge);
	}
	.nab-est-n {
		font-size: 1.5rem;
		font-weight: 600;
		line-height: 1;
		font-variant-numeric: tabular-nums;
	}
	.nab-est-t {
		font-size: 0.72rem;
		color: var(--text-dim);
	}
	.nab-est-sub {
		color: var(--text-label);
		font-size: 0.66rem;
	}
	/* ── The scale ────────────────────────────────────────────────────────
	   Fewer / exactly / more, as one bar. Neutral by design: a long at-bat is
	   good news for one dugout and bad for the other, so nothing here reads as
	   a verdict. The middle band is the lightest because "exactly" is the
	   least interesting of the three. */
	.nab-scale {
		margin-bottom: 0.9rem;
	}
	.nab-scale-bar {
		display: flex;
		height: 0.65rem;
		border-radius: 4px;
		overflow: hidden;
		background: var(--bg-surface);
	}
	.scale.fewer {
		background: #4a7fa5;
	}
	.scale.same {
		background: #6b7280;
	}
	.scale.more {
		background: #a57a4a;
	}
	.nab-scale-keys {
		display: flex;
		justify-content: space-between;
		gap: 0.5rem;
		margin-top: 0.35rem;
		font-size: 0.66rem;
		color: var(--text-label);
	}
	.nab-scale-keys .k {
		display: flex;
		flex-direction: column;
	}
	.nab-scale-keys .k:nth-child(2) {
		text-align: center;
	}
	.nab-scale-keys .k:last-child {
		text-align: right;
	}
	.nab-scale-keys b {
		font-size: 0.95rem;
		color: var(--text);
		font-variant-numeric: tabular-nums;
	}
	.nab-scale-keys .k.fewer b {
		color: #7fb0d4;
	}
	.nab-scale-keys .k.more b {
		color: #d4a97f;
	}

	/* The full shape behind those three numbers. Small on purpose — it is the
	   evidence for the scale above, not a second thing to read. */
	.nab-dist {
		display: flex;
		align-items: stretch;
		gap: 3px;
		height: 4.4rem;
	}
	.nab-dbar {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
	}
	/* Fixed height whether or not it holds a number, so every column's track
	   starts at the same line and the bars can be compared by eye. */
	.nab-dv {
		height: 0.8rem;
		font-size: 0.55rem;
		color: var(--text-label);
		font-variant-numeric: tabular-nums;
		line-height: 1;
	}
	.nab-dtrack {
		flex: 1;
		width: 100%;
		display: flex;
		align-items: flex-end;
	}
	.nab-dfill {
		width: 100%;
		background: #3c5878;
		border-radius: 2px 2px 0 0;
		min-height: 1px;
	}
	.nab-dbar.at .nab-dfill {
		background: #6b7280;
	}
	.nab-dbar.at .nab-dn {
		color: var(--text);
		font-weight: 600;
	}
	.nab-dn {
		font-size: 0.6rem;
		color: var(--text-label);
		font-variant-numeric: tabular-nums;
		line-height: 1;
	}
	/* ── Team pitch countdown ─────────────────────────────────────────────
	   A game-level number sitting under an at-bat-level one, so it is fenced
	   off with a rule rather than left to look like more of the same. */
	.tpc {
		margin-top: 0.9rem;
		padding-top: 0.8rem;
		border-top: 1px solid var(--border-faint);
	}
	.tpc-head {
		display: flex;
		align-items: baseline;
		gap: 0.5rem;
		font-size: 0.62rem;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-label);
		margin-bottom: 0.5rem;
	}
	.tpc-extra {
		text-transform: none;
		letter-spacing: 0;
		color: var(--caveat);
	}
	.tpc-teams {
		display: flex;
		gap: 0.5rem;
	}
	.tpc-team {
		flex: 1;
		border: 1px solid var(--border-faint);
		border-radius: 6px;
		padding: 0.5rem 0.6rem;
		background: var(--bg-badge);
	}
	/* The staff actually on the mound. Marked, because its number is the one
	   moving while you watch and the other is standing still. */
	.tpc-team.on {
		border-color: var(--border);
		background: var(--bg-surface);
	}
	.tpc-top {
		display: flex;
		align-items: center;
		gap: 0.3rem;
	}
	.tpc-abbr {
		font-size: 0.72rem;
		font-weight: 600;
	}
	.tpc-now {
		margin-left: auto;
		font-size: 0.56rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--accent-vegas);
	}
	/* Estimate on the left, real count on the right. The real one is the
	   quieter of the two by design — it is context for the projection, not a
	   rival headline — but it is present, which the estimate alone was not. */
	.tpc-nums {
		display: flex;
		align-items: baseline;
		gap: 0.75rem;
	}
	.tpc-fig {
		display: flex;
		align-items: baseline;
		gap: 0.25rem;
	}
	.tpc-fig.actual {
		margin-left: auto;
	}
	.tpc-n {
		font-size: 1.6rem;
		font-weight: 600;
		line-height: 1.1;
		font-variant-numeric: tabular-nums;
	}
	.tpc-n.thrown {
		font-size: 1.15rem;
		color: var(--text-dim);
	}
	.tpc-nlab {
		font-size: 0.58rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-label);
	}
	.tpc-bar {
		height: 0.3rem;
		border-radius: 2px;
		background: var(--bg-surface);
		overflow: hidden;
		margin: 0.2rem 0 0.25rem;
	}
	.tpc-team.on .tpc-bar {
		background: var(--slate);
	}
	.tpc-bar span {
		display: block;
		height: 100%;
		background: #4a7fa5;
		border-radius: 2px;
	}
	/* Past the estimate. Warm rather than alarming — a long night for a
	   bullpen is information, not a fault, and it reads the same whichever
	   dugout you're sitting in. */
	.tpc-team.over {
		border-color: #6b4a3a;
	}
	.tpc-n.over,
	.tpc-bar span.over {
		color: #d99a6c;
	}
	.tpc-bar span.over {
		background: #b5763f;
	}
	.tpc-sub {
		font-size: 0.62rem;
		color: var(--text-label);
		font-variant-numeric: tabular-nums;
	}
	.tpc-note {
		margin-top: 0.55rem;
		color: var(--text-label);
	}

	.nab-dist-cap {
		margin-top: 0.3rem;
		margin-bottom: 0.9rem;
		font-size: 0.62rem;
		color: var(--text-label);
	}

	.nab-note {
		margin: 0.4rem 0 0;
		font-size: 0.66rem;
		line-height: 1.45;
		color: var(--caveat);
		max-width: 62ch;
	}

	.situation-card {
		border: 1px solid var(--border);
		background: #0c1428;
		border-radius: 8px;
		padding: 1.15rem;
		margin-top: 1.15rem;
	}
	.situation-row {
		display: flex;
		align-items: center;
		gap: 1.5rem;
	}
	.bases {
		position: relative;
		width: 64px;
		height: 64px;
		flex-shrink: 0;
	}
	.base {
		position: absolute;
		width: 18px;
		height: 18px;
		background: var(--bg-surface);
		border: 2px solid var(--border-input);
		transform: rotate(45deg);
	}
	.base.on {
		background: var(--accent-pred);
		border-color: var(--accent-pred);
	}
	.base-2 {
		top: 0;
		left: 50%;
		margin-left: -9px;
	}
	.base-3 {
		top: 50%;
		left: 0;
		margin-top: -9px;
	}
	.base-1 {
		top: 50%;
		right: 0;
		margin-top: -9px;
	}
	.situation-details {
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
	}
	.sit-count {
		color: var(--text);
		font-weight: 800;
		font-size: 0.95rem;
	}
	.sit-line {
		color: var(--text-2);
		font-size: 0.85rem;
	}
	.sit-key {
		color: var(--text-label);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-size: 0.66rem;
		font-weight: 700;
		margin-right: 0.4rem;
	}

	/* ── Prediction blocks ── */
	.summary {
		border-bottom: 1px solid var(--border);
		margin-bottom: 1.5rem;
		padding: 0 0 1.5rem;
	}
	.sim-table {
		border-collapse: collapse;
		font-variant-numeric: tabular-nums;
		width: 100%;
	}
	.sim-th {
		letter-spacing: 0.08em;
		text-transform: uppercase;
		border-bottom: 1px solid var(--border);
		padding: 0 0.5rem 0.75rem;
		font-size: 1rem;
		font-weight: 800;
	}
	.sim-th.home {
		text-align: right;
	}
	.sim-th.away {
		text-align: left;
	}
	.sim-side-label {
		color: var(--text-label);
		letter-spacing: 0.1em;
		margin-top: 0.1rem;
		font-size: 0.6rem;
		font-weight: 700;
		display: block;
	}
	.sim-row td {
		border-bottom: 1px solid var(--bg-surface);
		padding: 0.55rem 0.5rem;
	}
	.sim-row:last-child td {
		border-bottom: 0;
	}
	.sim-val {
		color: var(--text);
		font-size: 1.5rem;
		font-weight: 700;
	}
	.sim-val.home {
		text-align: right;
	}
	.sim-val.away {
		text-align: left;
	}
	.score-row .sim-val {
		font-size: 2rem;
	}
	.sim-val.winval {
		color: var(--accent-pred);
	}
	.muted-val {
		color: var(--text-label) !important;
		font-size: 1rem !important;
		font-weight: 500 !important;
	}
	.sim-label {
		text-align: center;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--text-label);
		white-space: nowrap;
		font-size: 0.68rem;
		font-weight: 700;
	}
	.divider-row td {
		border-top: 1px solid var(--border);
		padding-top: 0.65rem;
	}
	.sim-center-row {
		text-align: center;
		padding: 0.5rem 0 0 !important;
	}
	.sim-meta-pill {
		color: var(--text-label);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		margin: 0 0.35rem;
		font-size: 0.7rem;
		font-weight: 600;
		display: inline-block;
	}
	.cal-pill {
		color: var(--accent-pred);
	}

	/* ── Adjustable final score ── */
	.score-adjust {
		border: 1px solid var(--border);
		background: #0c1428;
		border-radius: 8px;
		padding: 1rem 1.15rem 1.15rem;
		margin-bottom: 1.5rem;
		box-shadow: 0 2px 10px #00000059;
	}
	.score-adjust.adjusted {
		border-color: var(--accent-pred);
	}
	.sa-head {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 0.5rem 0.7rem;
		margin-bottom: 0.9rem;
	}
	.sa-title {
		color: #fff;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		font-size: 0.82rem;
		font-weight: 900;
	}
	.sa-note {
		color: var(--text-label);
		font-size: 0.74rem;
	}
	.sa-body {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 1.25rem;
	}
	.sa-team {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.5rem;
	}
	.sa-abbr {
		font-size: 1rem;
		font-weight: 800;
		font-style: italic;
		letter-spacing: 0.03em;
	}
	.sa-stepper {
		display: flex;
		align-items: center;
		gap: 0.6rem;
	}
	.sa-stepper button {
		width: 2rem;
		height: 2rem;
		border-radius: 6px;
		border: 1px solid var(--border-input);
		background: var(--bg-surface);
		color: var(--text);
		font-size: 1.2rem;
		font-weight: 800;
		line-height: 1;
		cursor: pointer;
		transition: color 0.15s, border-color 0.15s;
	}
	.sa-stepper button:hover:not(:disabled) {
		color: var(--accent-pred);
		border-color: var(--accent-pred);
	}
	.sa-stepper button:disabled {
		opacity: 0.35;
		cursor: not-allowed;
	}
	.sa-num {
		min-width: 1.6rem;
		text-align: center;
		font-size: 1.7rem;
		font-weight: 900;
		font-variant-numeric: tabular-nums;
	}
	.sa-at {
		color: var(--text-label);
		font-size: 1.3rem;
		font-weight: 300;
		padding-top: 1.4rem;
	}
	.sa-actions {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: center;
		gap: 1rem;
		margin-top: 1.2rem;
	}
	.sa-run {
		background: var(--accent-pred);
		color: #04240a;
		border: none;
		padding: 0.6rem 1.5rem;
		border-radius: 6px;
		cursor: pointer;
		font-size: 0.85rem;
		font-weight: 800;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-variant-numeric: tabular-nums;
	}
	.sa-run:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}
	.sa-reset {
		background: none;
		border: none;
		color: var(--slate);
		text-transform: uppercase;
		letter-spacing: 0.06em;
		font-size: 0.68rem;
		font-weight: 700;
		cursor: pointer;
		transition: color 0.15s;
	}
	.sa-reset:hover:not(:disabled) {
		color: var(--accent-pred);
	}
	.sa-reset:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}
	.sa-meta {
		margin-top: 0.9rem;
		text-align: center;
		color: var(--text-label);
		font-size: 0.8rem;
	}
	.sa-meta strong {
		color: var(--accent-pred);
	}
	.sa-meta-dim {
		opacity: 0.7;
	}
	.sa-error {
		margin-top: 0.9rem;
		text-align: center;
		color: var(--caveat);
		font-size: 0.82rem;
	}

	details.block {
		margin: 0 0 1.5rem;
	}
	details.block > summary {
		color: var(--text);
		text-transform: uppercase;
		letter-spacing: 0.1em;
		border-bottom: 1px solid var(--border);
		user-select: none;
		cursor: pointer;
		display: flex;
		align-items: center;
		gap: 0.6rem;
		padding: 0.5rem 0;
		font-size: 0.78rem;
		font-weight: 800;
		list-style: none;
	}
	details.block > summary::-webkit-details-marker {
		display: none;
	}
	.block-body {
		padding: 1rem 0 0;
	}
	.muted-inline {
		color: var(--text-label);
		text-transform: none;
		letter-spacing: 0;
		font-size: 0.75rem;
		font-weight: 400;
	}

	.qtable {
		border-collapse: collapse;
		font-variant-numeric: tabular-nums;
		width: 100%;
	}
	.qtable th {
		text-align: right;
		color: var(--text-label);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		border-bottom: 1px solid var(--border);
		padding: 0.5rem 0.6rem;
		font-size: 0.72rem;
		font-weight: 500;
	}
	.qtable td {
		text-align: right;
		color: var(--text-2);
		border-bottom: 1px solid var(--border);
		padding: 0.5rem 0.6rem;
	}
	.qtable tbody tr:last-child td {
		border-bottom: 0;
	}
	.qname {
		text-align: left !important;
		letter-spacing: 0.05em;
		font-weight: 700;
	}
	.qtotal {
		color: var(--text) !important;
		font-weight: 700;
	}

	.leaders-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
		gap: 1.25rem;
	}
	.leaders-team-header {
		display: flex;
		align-items: center;
		gap: 0.45rem;
		font-weight: 800;
		letter-spacing: 0.04em;
		margin-bottom: 0.75rem;
	}
	.leaders-row {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 0.75rem;
	}
	.leader {
		background: var(--bg-surface);
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: 0.7rem 0.5rem;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.3rem;
		text-align: center;
	}
	.leader-cat {
		color: var(--text-label);
		text-transform: uppercase;
		letter-spacing: 0.07em;
		font-size: 0.6rem;
		font-weight: 700;
	}
	.leader-name {
		font-size: 0.78rem;
		font-weight: 700;
		line-height: 1.2;
	}
	.leader-main {
		color: var(--accent-pred);
		font-size: 1.05rem;
		font-weight: 800;
		font-variant-numeric: tabular-nums;
	}
	.leader-sub {
		color: var(--text-label);
		font-size: 0.68rem;
	}
	.player-link {
		color: inherit;
		text-decoration: none;
	}
	.player-link:hover {
		color: var(--accent-pred);
	}

	.box-tabs {
		display: flex;
		gap: 0;
		align-items: center;
		border-bottom: 1px solid var(--border);
		margin-bottom: 1rem;
	}
	.lineup-badge {
		margin-left: auto;
		align-self: center;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-size: 0.62rem;
		font-weight: 800;
		padding: 0.2rem 0.5rem;
		border-radius: 999px;
		white-space: nowrap;
		/* projected = amber caution */
		color: var(--caveat, #e0a340);
		background: color-mix(in srgb, var(--caveat, #e0a340) 15%, transparent);
		border: 1px solid color-mix(in srgb, var(--caveat, #e0a340) 40%, transparent);
	}
	.lineup-badge.confirmed {
		color: var(--accent-pred);
		background: color-mix(in srgb, var(--accent-pred) 15%, transparent);
		border-color: color-mix(in srgb, var(--accent-pred) 40%, transparent);
	}
	.lineup-note {
		color: var(--caveat, #e0a340);
		font-size: 0.72rem;
		line-height: 1.4;
		margin: -0.5rem 0 1rem;
	}
	.box-tabs button {
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--text-label);
		cursor: pointer;
		background: none;
		border: none;
		border-bottom: 2px solid transparent;
		padding: 0.5rem 1rem;
		font-size: 0.78rem;
		font-weight: 800;
	}
	.box-tabs button.active {
		color: var(--text);
		border-bottom-color: var(--accent-pred);
	}
	.stat-block-label {
		color: var(--text-label);
		text-transform: uppercase;
		letter-spacing: 0.07em;
		font-size: 0.68rem;
		font-weight: 800;
		margin-bottom: 0.4rem;
	}
	.stat-block + .stat-block {
		margin-top: 1.5rem;
	}
	.stat-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.86rem;
		font-variant-numeric: tabular-nums;
	}
	.stat-table th {
		color: var(--text-label);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		text-align: right;
		border-bottom: 1px solid var(--border);
		padding: 0.4rem 0.5rem;
		font-size: 0.68rem;
		font-weight: 700;
	}
	.stat-table td {
		text-align: right;
		border-bottom: 1px solid var(--border-faint);
		padding: 0.42rem 0.5rem;
		color: var(--text-2);
	}
	.name-col {
		text-align: left !important;
	}
	/* Narrow and quiet — it labels the name beside it rather than competing
	   with the numbers, and every entry is two or three characters. */
	.pos-col {
		width: 2.6rem;
		color: var(--text-label);
		font-size: 0.72rem;
		letter-spacing: 0.02em;
		white-space: nowrap;
	}
	/* A usual position, not tonight's assignment — held at arm's length so it
	   doesn't read as a posted card. */
	.pos-usual {
		opacity: 0.55;
		font-style: italic;
	}
	.edit-hint {
		color: var(--text-label);
		text-transform: none;
		letter-spacing: 0;
		font-size: 0.68rem;
		font-weight: 400;
	}
	.stat-table td.edit-cell {
		padding: 0.25rem 0.3rem;
	}
	.stat-cell {
		width: 3.4rem;
		padding: 0.34rem 0.4rem;
		border-radius: 7px;
		border: 1px solid var(--border);
		background: var(--bg-surface);
		color: var(--text-2);
		font-size: 0.84rem;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		text-align: center;
		cursor: pointer;
		transition: border-color 0.15s, color 0.15s;
	}
	.stat-cell:hover:not(:disabled) {
		border-color: var(--accent-pred);
		color: var(--text);
	}
	.stat-cell.edited {
		border-color: var(--accent-pred);
		color: var(--accent-pred);
	}
	.stat-cell:disabled {
		opacity: 0.5;
		cursor: default;
	}
	.cell-input {
		width: 3.2rem;
		text-align: right;
		background: var(--bg-surface);
		border: 1px solid transparent;
		border-radius: 4px;
		color: var(--text-2);
		font-size: 0.84rem;
		font-variant-numeric: tabular-nums;
		padding: 0.28rem 0.35rem;
		-moz-appearance: textfield;
		appearance: textfield;
		transition: border-color 0.15s, color 0.15s;
	}
	.cell-input::-webkit-outer-spin-button,
	.cell-input::-webkit-inner-spin-button {
		-webkit-appearance: none;
		margin: 0;
	}
	.cell-input:hover:not(:disabled) {
		border-color: var(--border-input);
	}
	.cell-input:focus {
		outline: none;
		border-color: var(--accent-pred);
		color: var(--text);
	}
	.cell-input.edited {
		border-color: var(--accent-pred);
		color: var(--accent-pred);
		font-weight: 800;
	}
	.cell-input:disabled {
		opacity: 0.6;
	}
	.ro-cell {
		color: var(--text-footnote, var(--text-label));
	}
	.edit-actions {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.9rem;
		margin-top: 1rem;
	}
	.edit-run {
		background: var(--accent-pred);
		color: #04240a;
		border: none;
		padding: 0.5rem 1.2rem;
		border-radius: 5px;
		cursor: pointer;
		font-size: 0.8rem;
		font-weight: 800;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}
	.edit-run:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}
	.edit-clear {
		background: none;
		border: none;
		color: var(--slate);
		text-transform: uppercase;
		letter-spacing: 0.06em;
		font-size: 0.68rem;
		font-weight: 700;
		cursor: pointer;
	}
	.edit-clear:hover:not(:disabled) {
		color: var(--accent-pred);
	}
	.edit-err {
		color: var(--caveat);
		font-size: 0.8rem;
	}

	.gamelog {
		max-height: 46vh;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
		font-size: 0.84rem;
	}
	.log-inning {
		color: var(--accent-pred);
		text-transform: uppercase;
		letter-spacing: 0.07em;
		font-size: 0.68rem;
		font-weight: 800;
		padding: 0.65rem 0 0.25rem;
		border-bottom: 1px solid var(--border-faint);
	}
	.log-line {
		display: flex;
		gap: 0.6rem;
		align-items: baseline;
		padding: 0.22rem 0;
		color: var(--text-2);
	}
	.log-scoring {
		color: var(--text);
	}
	.log-batter {
		font-weight: 700;
		min-width: 11rem;
	}
	.log-out {
		color: var(--text-label);
	}
	.log-scoring .log-out {
		color: var(--text-2);
	}
	.log-runs {
		color: var(--accent-pred);
		font-weight: 800;
	}

	.charts-hint {
		color: var(--text-label);
		margin: 0 0 1rem;
		font-size: 0.78rem;
		line-height: 1.4;
	}
	.dist-picker {
		margin-bottom: 0.85rem;
	}
	.dist-select {
		appearance: none;
		color: var(--text);
		cursor: pointer;
		background-color: transparent;
		background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='7' viewBox='0 0 10 7'%3E%3Cpath d='M1 1l4 4 4-4' stroke='%2366FF00' stroke-width='1.6' fill='none' stroke-linecap='round'/%3E%3C/svg%3E");
		background-position: 100%;
		background-repeat: no-repeat;
		border: none;
		padding: 0.45rem 1.2rem 0.45rem 0;
		font-family: inherit;
		font-size: 0.95rem;
		font-weight: 700;
	}
	.dist-select:focus {
		outline: none;
	}
	.dist-select option {
		background: var(--bg-surface);
		color: var(--text);
	}
	.dist-chart {
		max-width: 480px;
	}

	@media (max-width: 600px) {
		.hero {
			gap: 0.75rem;
		}
		.hero-abbr {
			font-size: 1.2rem;
		}
		.leaders-row {
			grid-template-columns: repeat(3, 1fr);
			gap: 0.4rem;
		}
		.log-batter {
			min-width: 8rem;
		}
		.ts-grid-header,
		.ts-row {
			grid-template-columns: 1fr 2.4rem minmax(4.5rem, auto) 2.4rem 1fr;
			gap: 0.3rem;
		}
	}
</style>

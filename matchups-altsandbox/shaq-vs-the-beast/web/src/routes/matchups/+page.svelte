<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import {
		api,
		type GameSchedule,
		type SimResult,
		type SlateStatus
	} from '$lib/api';
	import { ensureSim, getSim, getStamp, clearSims } from '$lib/simstore';
	import { statusLabel, doubleheaderGame, isFinal } from '$lib/gameStatus';
	import TeamLogo from '$lib/TeamLogo.svelte';

	// Today's date, local time zone, ISO (YYYY-MM-DD) — the app's single
	// source of truth for "today" so nav math and the header stay in sync.
	function todayIso(): string {
		const d = new Date();
		const tz = d.getTimezoneOffset();
		return new Date(d.getTime() - tz * 60_000).toISOString().slice(0, 10);
	}
	function addDays(iso: string, n: number): string {
		const d = new Date(iso + 'T12:00:00');
		d.setDate(d.getDate() + n);
		return d.toISOString().slice(0, 10);
	}

	const TODAY = todayIso();
	let selectedDate = $state(TODAY);
	let games = $state<GameSchedule[]>([]);
	let loading = $state(true);
	// Ranked plays for the slate. Built server-side from the posted lines vs.
	// our simulation, cached there for three hours, so this is normally a
	// warm read rather than a fresh run of the whole slate.
	let error = $state('');
	let simming = $state<Record<string, boolean>>({});
	let simmingAll = $state(false);
	// How far the server has got simulating this slate. Everything on this page
	// reads those runs, so this is what the cards, the ranked plays and the
	// assistant are all actually waiting for.
	let slate = $state<SlateStatus | null>(null);
	let slateTimer: ReturnType<typeof setInterval> | null = null;
	// Bumped whenever a sim finishes so cached-result lookups re-run.
	let simVersion = $state(0);
	// Bumped on every navigation so a slow background refresh from a stale
	// date can't clobber the games list after the user has moved on.
	let loadToken = 0;

	// Live scores only matter for "today" — a fixed interval that stops
	// itself once nothing's actually in progress, so viewing a live slate
	// doesn't require a manual refresh to see runs post.
	const LIVE_POLL_MS = 20_000;
	// A slate is ~15 runs of a few seconds each, so a couple of seconds between
	// polls keeps the count moving visibly without hammering the server that is
	// busy doing the actual work.
	const SLATE_POLL_MS = 2_500;
	let pollTimer: ReturnType<typeof setInterval> | null = null;

	function stopPolling() {
		if (pollTimer !== null) {
			clearInterval(pollTimer);
			pollTimer = null;
		}
	}

	// Re-fetch the viewed date's schedule from MLB and merge it in, so
	// reschedules and newly-added doubleheader games appear without a manual
	// reload. Fire-and-forget; the stored slate has already rendered.
	async function refreshDateSchedule(date: string, token: number) {
		try {
			const fresh = await api.gamesLive(date);
			if (token !== loadToken || !fresh.length) return;
			const byId = new Map(games.map((g) => [g.game_id, g]));
			for (const g of fresh) byId.set(g.game_id, g);
			games = [...byId.values()];
		} catch (e) {
			console.warn('date schedule refresh failed (using stored slate)', e);
		}
	}

	/** Re-read the slate from the server's own storage — no MLB call.
	 *
	 * The server watcher fetches MLB every few minutes and writes what it finds
	 * here, so pregame this is the same information as going to MLB directly and
	 * costs 4ms instead of 600. The page used to make its own fetch every 20
	 * seconds regardless: 180 schedule fetches an hour per open tab, against the
	 * watcher's 12, for data the watcher had already collected.
	 */
	async function refreshStored(date: string, token: number) {
		try {
			const stored = await api.games(date);
			if (token !== loadToken || !stored.length) return;
			const byId = new Map(games.map((g) => [g.game_id, g]));
			for (const g of stored) byId.set(g.game_id, g);
			games = [...byId.values()];
		} catch {
			// A dropped poll is not worth an error banner.
		}
	}

	async function refreshLive(date: string, token: number) {
		try {
			const live = await api.upcoming(0);
			if (token !== loadToken || !live.length) return;
			const byId = new Map(games.map((g) => [g.game_id, g]));
			// The backend fetches a one-day buffer around "today" to cover
			// server/caller calendar-day drift, but each game's own `date`
			// is now the real MLB schedule day (fixed at the source), so an
			// exact match here is correct — no need to admit adjacent days.
			for (const g of live) if (g.date === date) byId.set(g.game_id, g);
			games = [...byId.values()];
		} catch (e) {
			console.warn('live schedule refresh failed (using stored slate)', e);
		}
	}

	/**
	 * Follow the server's slate simulation, and pull everything that depends on
	 * it once it's done.
	 *
	 * The page used to drive the simulations itself: fifteen sequential
	 * `/api/simulate` calls, with the best-bets build racing alongside them. It
	 * skipped any game already in sessionStorage, which is how the page could
	 * look fully simulated while the server held nothing — after a restart, the
	 * browser still had every result and never asked for one, so the assistant
	 * had no cached run to read and ran its own.
	 *
	 * Now the server does it once and this waits. The card fetches afterwards
	 * are cache hits.
	 */
	function watchSlate(date: string, token: number) {
		stopSlatePolling();
		slate = null;
		simmingAll = true;

		const tick = async () => {
			if (token !== loadToken) return stopSlatePolling();
			try {
				const s = await api.slateStatus(date);
				if (token !== loadToken) return;
				slate = s;
				if (!s.running) {
					// `running` rather than `state === 'ready'`: a slate that
					// finished with games missing is still finished, and waiting
					// for a state it will never reach would leave the ranked
					// plays and the assistant shut forever.
					stopSlatePolling();
					simmingAll = false;
					// A read of work already done.
					simAll(token);
				}
			} catch {
				// A dropped poll is not worth an error banner — the next one
				// will pick the count back up.
			}
		};
		tick();
		slateTimer = setInterval(tick, SLATE_POLL_MS);
	}

	function stopSlatePolling() {
		if (slateTimer) clearInterval(slateTimer);
		slateTimer = null;
	}

	/** Genuinely re-run the slate: drop the server's runs, then wait for the new
	 *  ones. Clearing only the browser's copy re-fetched the same numbers and
	 *  presented them as fresh. */
	async function rerunSlate() {
		const token = loadToken;
		simmingAll = true;
		error = '';
		try {
			await api.slateRerun(selectedDate);
			clearSims(games.map((g) => g.game_id));
			simVersion++;
			watchSlate(selectedDate, token);
		} catch (e) {
			if (token === loadToken) {
				error = String(e);
				simmingAll = false;
			}
		}
	}

	async function load(date: string) {
		const token = ++loadToken;
		stopPolling();
		loading = true;
		error = '';
		games = [];
		try {
			// Stored, local-DB read — fast and never depends on reaching the
			// live MLB API, so this is what actually renders the page.
			games = await api.games(date);
		} catch (e) {
			if (token === loadToken) error = String(e);
		} finally {
			if (token === loadToken) loading = false;
		}
		// Requesting the slate is what starts the server simulating it. The
		// cards, the ranked plays and the assistant then all read those runs
		// instead of each starting their own — which is what they used to do,
		// three times over, for the same fifteen games.
		watchSlate(date, token);
		// Best-effort live enrichment (real probable starters / scores) —
		// fire-and-forget so a slow or unreachable live source can never
		// hang the page; the stored slate above already rendered.
		if (date === TODAY) {
			await refreshLive(date, token);
			if (token === loadToken) {
				pollTimer = setInterval(() => {
					if (token !== loadToken) return;
					// Nothing left to watch once every game is over.
					if (!games.some((g) => !isFinal(g.status))) return;

					// Only a live score needs MLB directly — it moves by the
					// pitch and the server's five-minute watcher is too slow for
					// it. Pregame, that watcher is already fetching MLB and
					// writing what it finds to storage, so reading storage is
					// the same information without a second fetch. Going to MLB
					// on every tick regardless was 180 schedule fetches an hour
					// per open tab against the watcher's 12, at 600ms a call
					// instead of 4.
					if (games.some((g) => g.status === 'Live')) {
						refreshLive(date, token);
					} else {
						refreshStored(date, token);
					}

					// Cheap either way, and this is how a lineup posted since
					// the last tick reaches the page: the server re-simulates
					// that game itself and bumps the count.
					api
						.slateStatus(date)
						.then((s) => {
							if (token !== loadToken) return;
							const wasResimulated = (slate?.resimulated ?? 0) !== s.resimulated;
							slate = s;
							if (wasResimulated) {
								clearSims(games.map((g) => g.game_id));
								simAll(token);
							}
						})
						.catch(() => {});
				}, LIVE_POLL_MS);
			}
		} else {
			// Other dates aren't polled, but still re-check MLB once on open so
			// reschedules / doubleheaders on that day show up.
			refreshDateSchedule(date, token);
		}
	}


	onMount(() => {
		load(selectedDate);
	});
	onDestroy(() => {
		stopPolling();
		stopSlatePolling();
	});

	function goToday() {
		selectedDate = TODAY;
		load(selectedDate);
	}
	function shiftDay(n: number) {
		selectedDate = addDays(selectedDate, n);
		load(selectedDate);
	}

	function fmtDate(d: string): string {
		const dt = new Date(d + 'T12:00:00');
		return dt.toLocaleDateString(undefined, {
			weekday: 'long',
			month: 'long',
			day: 'numeric'
		});
	}

	function fmtWhen(iso: string): string {
		const d = new Date(iso);
		return d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
	}


	function fmtStamp(iso: string | null): string {
		if (!iso) return '';
		const dt = new Date(iso);
		return `last run ${dt.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}`;
	}

	function sim(gameId: string): SimResult | null {
		void simVersion;
		return getSim(gameId);
	}

	async function runOne(gameId: string) {
		simming[gameId] = true;
		try {
			await ensureSim(gameId, { n: 2000 }, true);
			simVersion++;
		} catch (e) {
			error = String(e);
		} finally {
			simming[gameId] = false;
		}
	}

	/**
	 * Simulate the whole slate, one game at a time.
	 *
	 * Runs automatically once the slate renders (force = false, so already-run
	 * games are skipped and it's a no-op on a revisit), and again on demand
	 * from the button (force = true, which re-runs everything fresh).
	 *
	 * Sequential on purpose: a slate is ~15 Monte Carlo runs and firing them
	 * at once would bury the server. `token` is the navigation token — if the
	 * user changes date mid-run, the stale loop stops instead of writing
	 * results for a slate that's no longer on screen.
	 */
	async function simAll(token: number, force = false) {
		simmingAll = true;
		error = '';
		try {
			for (const g of games) {
				if (token !== loadToken) return;
				if (!force && getSim(g.game_id)) continue;
				simming[g.game_id] = true;
				try {
					await ensureSim(g.game_id, { n: 2000 }, force);
					simVersion++;
				} catch (e) {
					// One unsimulatable game (missing lineup, bad id) must not
					// stop the rest of the slate from running.
					console.warn(`simulation failed for ${g.game_id}`, e);
				} finally {
					simming[g.game_id] = false;
				}
			}
		} finally {
			if (token === loadToken) simmingAll = false;
		}
	}

	const anyStamp = $derived.by(() => {
		void simVersion;
		const stamps = games.map((g) => getStamp(g.game_id)).filter(Boolean) as string[];
		return stamps.length ? stamps.sort().at(-1)! : null;
	});
</script>

<svelte:head>
	<title>Matchups — The Beast</title>
</svelte:head>

<div class="controls-bar">
	<div class="controls-left">
		<div class="date-nav">
			<button class="nav-btn" onclick={() => shiftDay(-1)} aria-label="Previous day">‹</button>
			<div class="ctrl">
				<span class="ctrl-label">{selectedDate === TODAY ? 'Today' : 'Slate'}</span>
				<span class="ctrl-value">{fmtDate(selectedDate)}</span>
			</div>
			<button class="nav-btn" onclick={() => shiftDay(1)} aria-label="Next day">›</button>
			{#if selectedDate !== TODAY}
				<button class="btn-today" onclick={goToday}>Today</button>
			{/if}
		</div>
	</div>
	<div class="controls-right">
		<span class="stamp cal" title="Win probabilities are Platt-calibrated on a held-out season">CAL ✦</span>
		{#if anyStamp}<span class="stamp stamp-lastrun">{fmtStamp(anyStamp)}</span>{/if}
		<button
			class="btn-sim-all"
			onclick={rerunSlate}
			disabled={simmingAll || loading || !games.length}
		>
			{simmingAll ? 'Simulating…' : 'Run new simulation'}
		</button>
		<span class="sim-key"><span class="sim-asterisk">*</span> Predicted score</span>
	</div>
</div>

{#if error}<div class="error">{error}</div>{/if}

{#if slate && !slate.running && slate.watching && slate.lineup_slots > 0}
	<!-- Lineups arrive a few hours before first pitch, one side at a time. The
	     count is worth showing because a projection and a posted card are
	     different claims and the cards look identical either way. -->
	<div class="slate-warm slate-warm-quiet">
		<span class="slate-warm-label">
			{slate.confirmed} of {slate.lineup_slots} lineups posted
			{#if slate.resimulated}· {slate.resimulated} re-simulated as cards landed{/if}
		</span>
		<span class="slate-warm-note">
			Checking MLB every few minutes; a game re-simulates itself the moment its
			card is posted.
		</span>
	</div>
{/if}

{#if slate && slate.running}
	<!-- The cards, the ranked plays and the assistant are all waiting on this
	     one run. Saying so — with a moving count — is the difference between a
	     wait and a page that looks broken. -->
	<div class="slate-warm">
		<span class="slate-warm-label">
			Simulating the slate — {slate.done} of {slate.total}
		</span>
		<div class="slate-bar" role="progressbar" aria-valuenow={slate.done} aria-valuemin="0" aria-valuemax={slate.total}>
			<div class="slate-bar-fill" style="width: {slate.total ? (100 * slate.done) / slate.total : 0}%"></div>
		</div>
		<span class="slate-warm-note">
			Cards, ranked plays and the assistant all read this run, so they wait for it.
			{#if slate.attempts > 1}Retrying {slate.failed.length} that didn't take (pass {slate.attempts}).{/if}
		</span>
	</div>
{:else if slate && slate.failed.length}
	<div class="slate-warm slate-warm-partial">
		<span class="slate-warm-label">
			{slate.failed.length} of {slate.total} game{slate.total === 1 ? '' : 's'} couldn't be
			simulated after {slate.attempts} attempts
		</span>
		<span class="slate-warm-note">
			Missing from the ranked plays — not games the model sees no edge in.
		</span>
		<!-- The reason, not a guess at it. This banner used to say "usually a
		     lineup that hasn't been posted yet", which was a plausible story and
		     the wrong one: the games were failing because the injury filter had
		     left their lineups a batter short. -->
		{#each slate.failed as gid (gid)}
			<span class="slate-warm-why">{gid} — {slate.reasons?.[gid] ?? 'no reason recorded'}</span>
		{/each}
	</div>
{/if}

{#if loading}
	<div class="loading"><span class="spinner"></span> Loading {selectedDate === TODAY ? "today's" : ''} slate…</div>
{:else if !games.length}
	<div class="loading">No games {selectedDate === TODAY ? 'today' : 'scheduled'}.</div>
{:else}
	<div class="matchup-groups">
		<div class="grid">
			{#each games as g (g.game_id)}
				{@const r = sim(g.game_id)}
				{@const awayWin = r != null && r.home_win_probability < 0.5}
					{@const dh = doubleheaderGame(g.game_id)}
				<div class="card">
					{#if statusLabel(g) || dh}
						<div class="game-status" class:is-live={g.status === 'Live'} class:is-final={g.status === 'Final'}>
							{#if g.status === 'Live'}<span class="live-dot"></span>{/if}
							{statusLabel(g)}
							{#if dh}<span class="dh-badge">Doubleheader · Game {dh}</span>{/if}
						</div>
					{/if}
					<div class="matchup-rows">
						<div class="team-row">
							<a class="team-left" href={`/teams/${g.away_team_id}`}>
								<TeamLogo abbr={g.away_team_id} size={38} />
								<div class="team-names">
									<span class="team-abbr">{g.away_team_id}</span>
									<span class="team-rec">Away</span>
								</div>
							</a>
							<div class="score-stack">
								{#if g.away_score != null}
									<span class="real-score" class:trail={g.home_score != null && g.away_score < g.home_score}>{g.away_score}</span>
								{/if}
								{#if r}
									<span class="team-score" class:pred-win={awayWin} class:loss={!awayWin}>
										{r.away_run_mean.toFixed(1)}<span class="asterisk">*</span>
									</span>
								{:else if simming[g.game_id]}
									<span class="spinner small"></span>
								{/if}
							</div>
						</div>
						<div class="team-row">
							<a class="team-left" href={`/teams/${g.home_team_id}`}>
								<TeamLogo abbr={g.home_team_id} size={38} />
								<div class="team-names">
									<span class="team-abbr">{g.home_team_id}</span>
									<span class="team-rec">Home</span>
								</div>
							</a>
							<div class="score-stack">
								{#if g.home_score != null}
									<span class="real-score" class:trail={g.away_score != null && g.home_score < g.away_score}>{g.home_score}</span>
								{/if}
								{#if r}
									<span class="team-score" class:pred-win={!awayWin} class:loss={awayWin}>
										{r.home_run_mean.toFixed(1)}<span class="asterisk">*</span>
									</span>
								{/if}
							</div>
						</div>
					</div>
					<div class="card-bottom">
						<div class="cb-left">
							{#if r}
								<div class="footer-meta">
									<span class="spread">
										{r.home_win_probability >= 0.5 ? g.home_team_id : g.away_team_id}
										{(Math.max(r.home_win_probability, 1 - r.home_win_probability) * 100).toFixed(0)}%
									</span>
								</div>
							{:else}
								<div class="footer-meta">
									<span class="pending">
										{simming[g.game_id] ? 'Simulating…' : 'Awaiting simulation'}
									</span>
								</div>
							{/if}
						</div>
						<a class="detail-cta" href={`/matchups/${g.game_id}`}>
							Game Stats <span class="cta-arrow">→</span>
						</a>
					</div>
				</div>
			{/each}
		</div>
	</div>
{/if}

<style>
	.controls-bar {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		align-items: flex-end;
		gap: 0.75rem;
		padding-bottom: 1.25rem;
	}
	.controls-left {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		gap: 2.25rem;
	}
	.date-nav {
		display: flex;
		align-items: flex-end;
		gap: 0.6rem;
	}
	.nav-btn {
		color: var(--text-2);
		background: var(--bg-surface);
		border: 1px solid var(--border-input);
		border-radius: 5px;
		cursor: pointer;
		width: 1.9rem;
		height: 1.9rem;
		line-height: 1;
		font-size: 1.05rem;
		font-weight: 700;
		transition: color 0.15s, border-color 0.15s;
	}
	.nav-btn:hover {
		color: var(--accent-pred);
		border-color: var(--accent-pred);
	}
	.btn-today {
		color: var(--slate);
		background: none;
		border: none;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		cursor: pointer;
		font-size: 0.68rem;
		font-weight: 700;
		padding-bottom: 0.3rem;
		transition: color 0.15s;
	}
	.btn-today:hover {
		color: var(--accent-pred);
	}
	.ctrl {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
	}
	.ctrl-label {
		color: var(--accent-pred);
		text-transform: uppercase;
		letter-spacing: 0.07em;
		font-size: 0.72rem;
		font-weight: 700;
	}
	.ctrl-value {
		font-size: 0.95rem;
		font-weight: 700;
	}
	.controls-right {
		display: flex;
		flex-wrap: wrap;
		justify-content: flex-end;
		align-items: flex-end;
		gap: 1rem;
	}
	.stamp {
		color: var(--text-label);
		padding-bottom: 0.15rem;
		font-size: 0.72rem;
		line-height: 1;
	}
	.stamp.cal {
		color: var(--accent-pred);
		letter-spacing: 0.06em;
		cursor: default;
		font-weight: 700;
	}
	.stamp-lastrun {
		font-style: italic;
	}
	.btn-sim-all {
		color: var(--slate);
		letter-spacing: 0.06em;
		text-transform: uppercase;
		cursor: pointer;
		background: none;
		border: none;
		padding: 0 0 0.15rem;
		font-size: 0.62rem;
		font-weight: 700;
		transition: color 0.15s;
	}
	.btn-sim-all:hover:not(:disabled) {
		color: var(--accent-pred);
	}
	.btn-sim-all:disabled {
		opacity: 0.4;
		cursor: default;
	}
	.sim-key {
		color: var(--text-label);
		letter-spacing: 0.04em;
		white-space: nowrap;
		font-size: 0.72rem;
		font-weight: 700;
		padding-bottom: 0.1rem;
	}
	.sim-asterisk {
		color: var(--accent-pred);
		font-weight: 900;
	}
	.error {
		color: var(--danger);
		margin: 1rem 0;
	}
	.slate-warm {
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
		margin: 0 0 1rem;
		padding: 0.6rem 0.75rem;
		border: 1px solid var(--border);
		border-radius: 10px;
	}
	.slate-warm-label {
		font-size: 0.78rem;
	}
	.slate-warm-note {
		font-size: 0.68rem;
		color: var(--text-muted);
	}
	.slate-bar {
		height: 4px;
		border-radius: 999px;
		background: var(--border);
		overflow: hidden;
	}
	.slate-bar-fill {
		height: 100%;
		background: currentColor;
		opacity: 0.65;
		transition: width 0.4s ease;
	}
	.slate-warm-partial {
		border-color: var(--danger);
	}
	.slate-warm-quiet {
		border-style: dashed;
	}
	.slate-warm-why {
		font-size: 0.62rem;
		color: var(--text-muted);
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		overflow-wrap: anywhere;
	}
	.loading {
		color: var(--text-muted);
		display: flex;
		align-items: center;
		gap: 0.7rem;
		padding: 2rem 0;
		font-size: 0.95rem;
	}
	.spinner {
		border: 2px solid var(--border-input);
		border-top-color: var(--accent-pred);
		border-radius: 50%;
		flex-shrink: 0;
		width: 1.1rem;
		height: 1.1rem;
		animation: spin 0.7s linear infinite;
	}
	.spinner.small {
		width: 0.9rem;
		height: 0.9rem;
		display: inline-block;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	.grid {
		display: flex;
		flex-direction: column;
		gap: 0.85rem;
		margin-top: 0.85rem;
	}
	.card {
		border: 1px solid var(--border);
		background: #0c1428;
		border-radius: 8px;
		padding: 0;
		overflow: hidden;
		box-shadow: 0 2px 10px #00000059;
	}
	.game-status {
		color: var(--text-label);
		letter-spacing: 0.06em;
		text-transform: uppercase;
		display: flex;
		align-items: center;
		gap: 0.4rem;
		padding: 0.4rem 1.15rem;
		font-size: 0.68rem;
		font-weight: 800;
		border-bottom: 1px solid var(--border);
		background: var(--bg-surface);
	}
	.game-status.is-live {
		color: var(--accent-actual, #00fff2);
	}
	.dh-badge {
		margin-left: auto;
		color: var(--accent-pred);
		letter-spacing: 0.05em;
		font-size: 0.62rem;
		font-weight: 800;
	}
	.game-status.is-final {
		color: var(--text-2);
	}
	.live-dot {
		background: #ff3b3b;
		border-radius: 50%;
		width: 6px;
		height: 6px;
		display: inline-block;
		animation: pulse 1.4s ease-in-out infinite;
	}
	@keyframes pulse {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.35; }
	}
	.score-stack {
		display: flex;
		align-items: center;
		gap: 0.6rem;
	}
	.real-score {
		color: var(--text);
		font-variant-numeric: tabular-nums;
		font-size: 1.6rem;
		font-weight: 900;
		min-width: 1.4rem;
		text-align: right;
	}
	.real-score.trail {
		color: var(--text-label);
		font-weight: 700;
	}
	.matchup-rows {
		display: flex;
		flex-direction: column;
	}
	.team-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 0.75rem;
		padding: 0.7rem 1.15rem;
	}
	.team-row + .team-row {
		border-top: 1px solid var(--border);
	}
	.team-left {
		display: flex;
		align-items: center;
		gap: 0.65rem;
		min-width: 0;
		color: inherit;
		text-decoration: none;
	}
	.team-left:hover .team-abbr {
		color: var(--accent-pred);
	}
	.team-names {
		display: flex;
		flex-direction: column;
		min-width: 0;
		line-height: 1.2;
	}
	.team-abbr {
		text-transform: uppercase;
		color: var(--text);
		letter-spacing: 0.02em;
		font-size: 1.18rem;
		font-style: italic;
		font-weight: 800;
		transition: color 0.15s;
	}
	.team-rec {
		color: var(--text-label);
		font-size: 0.775rem;
		font-weight: 600;
	}
	.team-score {
		color: var(--text-label);
		font-variant-numeric: tabular-nums;
		text-align: right;
		min-width: 2.5rem;
		font-size: 1.6rem;
		font-weight: 800;
	}
	.team-score.pred-win {
		color: var(--accent-pred);
	}
	.team-score.loss {
		color: var(--slate-deep);
	}
	.asterisk {
		color: var(--accent-pred);
		vertical-align: super;
		margin-left: 1px;
		font-size: 0.75rem;
		font-weight: 900;
	}
	.team-score.loss .asterisk {
		color: var(--text-label);
	}
	@media (max-width: 640px) {
	}
	@media (max-width: 560px) {
	}
	@media (max-width: 520px) {
	}
	@media (min-width: 720px) {
	}
	/* Marks a play on a game already under way. The pulse is what draws the
	   eye to the one thing on this panel that expires in minutes. */
	.live-dot {
		display: inline-block;
		width: 0.44em;
		height: 0.44em;
		border-radius: 50%;
		background: #ff3b30;
		margin-right: 0.42em;
		vertical-align: 0.12em;
		animation: live-pulse 1.6s ease-in-out infinite;
	}
	@keyframes live-pulse {
		0%,
		100% {
			opacity: 1;
			box-shadow: 0 0 0 0 rgba(255, 59, 48, 0.65);
		}
		50% {
			opacity: 0.55;
			box-shadow: 0 0 0 0.28em rgba(255, 59, 48, 0);
		}
	}
	/* Motion is decoration here — the colour already carries the meaning. */
	@media (prefers-reduced-motion: reduce) {
		.live-dot {
			animation: none;
		}
	}
	@media (min-width: 720px) {
	}
	@media (min-width: 720px) {
	}
	@media (min-width: 720px) {
	}
	@media (min-width: 720px) {
	}
	@media (min-width: 720px) {
	}
	.card-bottom {
		border-top: 1px solid var(--border);
		background: #0a1020;
		display: flex;
		align-items: stretch;
	}
	.cb-left {
		display: flex;
		flex-direction: column;
		flex: 1;
		justify-content: center;
		min-width: 0;
	}
	.footer-meta {
		color: var(--text-label);
		display: flex;
		align-items: center;
		gap: 0.9rem;
		padding: 0.55rem 1.15rem 0.7rem;
		font-size: 0.75rem;
	}
	.spread {
		color: var(--text-2);
		font-weight: 700;
	}
	.pending {
		color: var(--caveat);
		font-size: 0.72rem;
		font-style: italic;
	}
	.detail-cta {
		border-left: 1px solid var(--border);
		letter-spacing: 0.07em;
		text-transform: uppercase;
		color: var(--text);
		display: flex;
		justify-content: center;
		align-items: center;
		gap: 0.45rem;
		flex-shrink: 0;
		padding: 0.8rem 1.35rem;
		font-size: 0.8rem;
		font-weight: 800;
		text-decoration: none;
		transition: background 0.15s;
	}
	.detail-cta:hover {
		background: color-mix(in srgb, var(--accent-pred) 12%, transparent);
	}
	.cta-arrow {
		color: var(--accent-pred);
		font-size: 1.05rem;
		line-height: 0;
		transition: transform 0.15s;
	}
	.detail-cta:hover .cta-arrow {
		transform: translateX(3px);
	}
</style>

<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import {
		api,
		type GameSchedule,
		type SimResult,
		type BestBet,
		type BestBetsReport,
		type AccuracyReport,
		type TrendsReport,
		type ExpectedTrend,
		type SlateStatus
	} from '$lib/api';
	import { ensureSim, getSim, getStamp, clearSims } from '$lib/simstore';
	import { statusLabel, doubleheaderGame, isFinal } from '$lib/gameStatus';
	import TeamLogo from '$lib/TeamLogo.svelte';
	import ChatPanel from '$lib/ChatPanel.svelte';

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
	let bestBets = $state<BestBetsReport | null>(null);
	let bestBetsLoading = $state(false);
	let bestBetsError = $state('');
	let bestBetsOpen = $state(true);
	// Collapsed by default: it's background reading about the league, not
	// anything you need to get past to see tonight's games.
	let trendsOpen = $state(false);
	// How the model actually did, over two windows so they can be compared: the
	// single day just graded, and the five days around it. One night is a small
	// sample and swings hard; the five-day figure is what it usually does. Both
	// are read-only aggregations over stored scorecards — the grading itself
	// runs nightly in CI — so neither blocks the slate.
	let accuracy = $state<AccuracyReport | null>(null);
	let accuracyDay = $state<AccuracyReport | null>(null);
	const ACC_DAYS = 5;
	// Below this many graded games, a night is not evidence of anything and the
	// better/worse marks come off. A rained-out Monday can leave one game on the
	// board, and "100% of winners picked" off a single call would read as a good
	// night rather than as a coin landing heads once.
	const ACC_MIN_COMPARE = 5;
	const dayGames = $derived(accuracyDay?.window.games ?? 0);
	const comparable = $derived(
		dayGames >= ACC_MIN_COMPARE && (accuracy?.window.games ?? 0) >= ACC_MIN_COMPARE
	);
	// The most recent night that actually has anything graded. Only needed to
	// explain an empty "yesterday" column, so it comes out of the window report
	// already fetched rather than costing another call.
	const latestGraded = $derived(
		(accuracy?.games ?? []).reduce<string | null>(
			(newest, g) => (newest === null || g.date > newest ? g.date : newest),
			null
		)
	);
	// What the model expects to get wrong, and how those expectations have
	// held up. Issued and graded by the scheduled job, so this is a read.
	let trends = $state<TrendsReport | null>(null);
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
					// Both of these are now reads of work already done.
					simAll(token);
					loadBestBets(date, token);
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

	async function loadBestBets(date: string, token: number, refresh = false) {
		bestBetsLoading = true;
		bestBetsError = '';
		try {
			const r = await api.bestBets(date, refresh);
			if (token === loadToken) bestBets = r;
		} catch (e) {
			if (token === loadToken) bestBetsError = String(e);
		} finally {
			if (token === loadToken) bestBetsLoading = false;
		}
	}

	// Manual re-run: throws away the cached simulations for this slate and
	// re-prices from scratch against whatever the books are showing now.
	function rerunBestBets() {
		loadBestBets(selectedDate, loadToken, true);
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
		bestBets = null;
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
					// Two windows matter, and only one of them used to be polled.
					// A live game's score moves. But lineups are *posted* hours
					// before first pitch, while every game is still Preview — so
					// gating this on "something is Live" meant the app never
					// looked during the window lineups actually arrive, and a
					// posted card showed up whenever someone happened to reload.
					const live = games.some((g) => g.status === 'Live');
					const pregame = games.some(
						(g) => g.status !== 'Live' && !isFinal(g.status)
					);
					if (live || pregame) {
						refreshLive(date, token);
						// The slate re-checks its own lineups server-side; this
						// picks up the count so the page can say how many are
						// confirmed, and re-reads the cards when one changes.
						api
							.slateStatus(date)
							.then((s) => {
								if (token !== loadToken) return;
								const wasResimulated = (slate?.resimulated ?? 0) !== s.resimulated;
								slate = s;
								if (wasResimulated) {
									clearSims(games.map((g) => g.game_id));
									simAll(token);
									if (!bestBetsLoading) loadBestBets(date, token);
								}
							})
							.catch(() => {});
						if (live && !bestBetsLoading) loadBestBets(date, token);
					}
				}, LIVE_POLL_MS);
			}
		} else {
			// Other dates aren't polled, but still re-check MLB once on open so
			// reschedules / doubleheaders on that day show up.
			refreshDateSchedule(date, token);
		}
	}

	// The accuracy window ends yesterday: today's games haven't finished, so
	// including them would only ever dilute the sample with unscoreable rows.
	async function loadAccuracy() {
		// Both windows end on the same day, so the five-day figure contains the
		// one-day figure. That's deliberate: the question is whether last night
		// was normal, and the answer is what it looks like against the stretch
		// it belongs to.
		const end = addDays(TODAY, -1);
		const [day, window] = await Promise.allSettled([
			api.accuracyReport({ date: end, days: 1 }),
			api.accuracyReport({ date: end, days: ACC_DAYS })
		]);
		// A missing scorecard is not worth an error banner, and one window
		// failing shouldn't take the other down with it.
		accuracyDay = day.status === 'fulfilled' ? day.value : null;
		accuracy = window.status === 'fulfilled' ? window.value : null;
	}

	async function loadTrends() {
		try {
			trends = await api.trends();
		} catch {
			trends = null; // no forecasts yet is not an error worth a banner
		}
	}

	// Most quantities hold steady most weeks, and a column of "unchanged" buries
	// the two or three things that did move. The quiet ones stay one click away
	// rather than being dropped, so the section can't flatter itself by only
	// ever showing the metrics that happen to look interesting.
	let showSteady = $state(false);
	let showAllNext = $state(false);
	const NEXT_SHOWN = 5;

	let movers = $derived(trends?.this_week.filter((t) => t.moving) ?? []);
	let steady = $derived(trends?.this_week.filter((t) => !t.moving) ?? []);
	let nextWeek = $derived(
		showAllNext ? (trends?.next_week ?? []) : (trends?.next_week ?? []).slice(0, NEXT_SHOWN)
	);
	let hiddenNext = $derived(Math.max(0, (trends?.next_week.length ?? 0) - NEXT_SHOWN));

	onMount(() => {
		load(selectedDate);
		loadAccuracy();
		loadTrends();
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

	function fmtPct(v: number): string {
		// Never print a bare 100% (or 0%). These are Monte Carlo estimates, and
		// rounding 99.95% up to "100.0%" claims a certainty the sample can't
		// support — the model is saying "no failures in 2000 tries", which is
		// not the same as "cannot lose".
		if (v >= 0.999) return '>99.9%';
		if (v > 0 && v < 0.001) return '<0.1%';
		return `${(v * 100).toFixed(1)}%`;
	}

	// Two market families — player props only. The server ranks and caps within each one, and
	// makes sure each carries both pregame and in-progress plays, so this just
	// splits the already-ranked list back into its panels. Live plays sit in
	// their own family rather than a panel of their own: a live strikeout prop
	// is still a pitcher prop, and the bullet is what marks it.
	const QUADRANTS: { key: string; title: string; empty: string }[] = [
		{ key: 'pitcher_prop', title: 'Pitcher props', empty: 'No pitcher prop cleared the bar.' },
		{ key: 'batter_prop', title: 'Batter props', empty: 'No batter prop cleared the bar.' }
	];
	function playsIn(cat: string): BestBet[] {
		return (bestBets?.bets ?? []).filter((b) => b.category === cat);
	}

	/**
	 * The rows of the accuracy comparison.
	 *
	 * `better` returns +1 if yesterday beat the window, -1 if it fell short, 0
	 * if they're level — and the direction is per-metric, which is the part
	 * worth being careful about. A higher percentage of winners picked is good;
	 * a higher average miss on the total is bad. Coverage is different again:
	 * it targets 80%, so both 60% and 95% are wrong and the comparison is which
	 * one sits closer to the target, not which is larger.
	 */
	type AccRow = {
		label: string;
		note: string;
		pick: (r: AccuracyReport | null) => number | null;
		fmt: (v: number | null) => string;
		better: (day: number, span: number) => number;
	};
	const sign = (x: number) => (x > 0 ? 1 : x < 0 ? -1 : 0);
	const higherWins = (d: number, s: number) => sign(d - s);
	const lowerWins = (d: number, s: number) => sign(s - d);
	const closerTo80 = (d: number, s: number) => sign(Math.abs(s - 80) - Math.abs(d - 80));
	const pct = (v: number | null) => (v === null ? '—' : `${v}%`);

	const ACC_ROWS: AccRow[] = [
		{
			label: 'winners picked',
			note: 'share of games called right',
			pick: (r) => r?.outcomes.winner_accuracy_pct ?? null,
			fmt: pct,
			better: higherWins
		},
		{
			label: 'runs off the total',
			note: 'average miss, lower is better',
			pick: (r) => r?.outcomes.total_mae ?? null,
			fmt: (v) => (v === null ? '—' : v.toFixed(2)),
			better: lowerWins
		},
		{
			label: 'totals in range',
			note: 'target 80% — not higher',
			pick: (r) => r?.outcomes.total_coverage_pct ?? null,
			fmt: pct,
			better: closerTo80
		},
		{
			label: 'batter hits',
			note: 'per-player lines called right',
			pick: (r) => r?.batting?.hits?.accuracy_pct ?? null,
			fmt: pct,
			better: higherWins
		},
		{
			label: 'pitcher outs',
			note: 'per-pitcher lines called right',
			pick: (r) => r?.pitching?.outs?.accuracy_pct ?? null,
			fmt: pct,
			better: higherWins
		}
	];
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

{#snippet play(b: BestBet, i: number)}
	<a class="bb-row" href={`/matchups/${b.game_id}`}>
		<span class="bb-rank">{i + 1}</span>
		<span class="bb-pick">
			<span class="bb-sel"
				>{#if b.is_live}<span class="live-dot" title="Game in progress"></span>{/if}{b.selection}</span
			>
			<span class="bb-game">{b.away} @ {b.home}{b.book ? ` · ${b.book}` : ''}</span>
			<span class="bb-meta">
				<span class="bb-price">{b.price >= 0 ? `+${b.price}` : b.price}</span>
				<span class="bb-edge" class:flat={!b.has_edge}
					>{(b.edge * 100).toFixed(1)}% edge</span
				>
				<span class="bb-hit">{fmtPct(b.model_probability)} to hit</span>
			</span>
		</span>
	</a>
{/snippet}

<section class="bb" class:open={bestBetsOpen}>
	<!-- A row, not one big button: the re-run control has to be its own
	     button, and a button inside a button is invalid markup. -->
	<div class="bb-head">
		<button class="bb-toggle" onclick={() => (bestBetsOpen = !bestBetsOpen)}>
			<span class="bb-title">Best bets</span>
			<span class="bb-sub">
				{#if bestBetsLoading && !bestBets}building…
				{:else if bestBets?.bets?.length}{bestBets.bets.filter((b) => b.has_edge)
						.length} of {bestBets.bets.length} with an edge
				{:else}nothing priced on this slate{/if}
			</span>
		</button>
		<button
			class="bb-rerun"
			onclick={() => rerunBestBets()}
			disabled={bestBetsLoading}
			title="Re-simulate and re-price against the current lines"
		>
			{bestBetsLoading ? 'Re-running…' : 'Re-run'}
		</button>
		<button
			class="bb-caret"
			onclick={() => (bestBetsOpen = !bestBetsOpen)}
			aria-label={bestBetsOpen ? 'Collapse best bets' : 'Expand best bets'}
		>
			{bestBetsOpen ? '▾' : '▸'}
		</button>
	</div>

	{#if bestBetsOpen}
		<div class="bb-body">
			{#if bestBetsLoading && !bestBets}
				<div class="bb-msg"><span class="spinner"></span> Simulating the slate against the posted lines…</div>
			{:else if bestBetsError}
				<div class="bb-msg">Couldn't build best bets: {bestBetsError}</div>
			{:else if bestBets}
				<div class="bb-quads">
					{#each QUADRANTS as q}
						<div class="bb-quad">
							<div class="bb-quad-head">
								<span>{q.title}</span>
								{#if playsIn(q.key).length}
									<span class="bb-more">
										{bestBets.counts?.[q.key] ?? 0} of {bestBets.priced_counts?.[q.key] ?? 0} qualify
									</span>
								{/if}
							</div>
							{#each playsIn(q.key) as b, i}
								{@render play(b, i)}
							{:else}
								<div class="bb-empty">
									{#if !bestBets.props_available}
										No props priced yet.
									{:else}
										{q.empty}
									{/if}
								</div>
							{/each}
						</div>
					{/each}
				</div>
				<div class="bb-foot">
					Up to five of each, ranked by edge over the posted price (vig included). A
					greyed edge is below our bar — shown for context, not as a play.
					{bestBets.games_priced} of {bestBets.games_considered} games priced
					{#if bestBets.generated_at}· as of {fmtWhen(bestBets.generated_at)}{/if}
					{#if bestBets.cached}· cached{/if}
				</div>
			{/if}
		</div>
	{/if}
</section>

<ChatPanel slate={slate} />

{#if trends && (trends.this_week.length || trends.next_week.length || trends.scorecard.graded)}
	<section class="tr" class:open={trendsOpen}>
		<!-- A row rather than one big button, for the same reason best bets is:
		     the score badge carries a tooltip and shouldn't be swallowed by the
		     toggle's hit area. -->
		<div class="tr-head">
			<button
				class="tr-toggle"
				onclick={() => (trendsOpen = !trendsOpen)}
				aria-expanded={trendsOpen}
			>
				<h2>Trends</h2>
				<span class="tr-sub">
					what we have been seeing lately, and where it should land this coming week
					{#if trends.history.games}
						— from {trends.history.games.toLocaleString()} league games across
						{trends.history.seasons.length} season{trends.history.seasons.length === 1
							? ''
							: 's'}
					{:else}
						— from {trends.record_games} finished games
					{/if}
				</span>
			</button>
			{#if trends.scorecard.graded > 0}
				{@const ov = trends.scorecard.overall}
				<span
					class="tr-score"
					title="Every forecast carries an 80% range, so about one in five is supposed to miss. Far above 80% would mean the ranges are too wide to be worth reading; far below means we are overconfident."
				>
					forecasts right {Math.round((ov.hit_rate ?? 0) * 100)}%
					<span class="tr-of">of {trends.scorecard.graded} graded</span>
				</span>
			{:else if trends.scorecard.open > 0}
				<span class="tr-score tr-pending">{trends.scorecard.open} awaiting their week</span>
			{/if}
			<button
				class="tr-caret"
				onclick={() => (trendsOpen = !trendsOpen)}
				aria-label={trendsOpen ? 'Collapse trends' : 'Expand trends'}
			>
				{trendsOpen ? '▾' : '▸'}
			</button>
		</div>

		{#if trendsOpen}
			<div class="tr-cols">
				<div class="tr-col">
					<div class="tr-col-head">
						<span class="tr-title">What we've been seeing</span>
						{#if trends.this_week.length}
							<span class="tr-window">last {trends.this_week[0].days} days, through today</span>
						{/if}
					</div>
					<p class="tr-blurb">
						What has stood out in the games just played, measured against the season so
						far — not against last week, which is one small sample judging another.
					</p>
					{#each movers as t (t.metric)}
						<div class="tr-row">
							<div class="tr-line">
								<span class="tr-arrow {t.direction}" class:soft={!t.firm} aria-hidden="true">
									{t.direction === 'up' ? '▲' : t.direction === 'down' ? '▼' : '■'}
								</span>
								<span class="tr-text">{t.headline}</span>
							</div>
							<div class="tr-meta">{t.detail}</div>
						</div>
					{:else}
						<div class="tr-empty">
							Nothing has moved much — the last few days look like ordinary baseball.
						</div>
					{/each}
					{#if steady.length}
						<button class="tr-more" onclick={() => (showSteady = !showSteady)}>
							{showSteady ? 'Hide' : 'Show'}
							{steady.length} holding steady
						</button>
						{#if showSteady}
							{#each steady as t (t.metric)}
								<div class="tr-row tr-quiet">
									<div class="tr-line">
										<span class="tr-arrow flat" aria-hidden="true">■</span>
										<span class="tr-text">{t.headline}</span>
									</div>
									<div class="tr-meta">{t.detail}</div>
								</div>
							{/each}
						{/if}
					{/if}
				</div>

				<div class="tr-col">
					<div class="tr-col-head">
						<span class="tr-title">The week ahead</span>
						{#if trends.next_week.length}
							<span class="tr-window">
								{trends.next_week[0].window_start} → {trends.next_week[0].window_end}
							</span>
						{/if}
					</div>
					<p class="tr-blurb">
						The next seven days. The season's level, adjusted for how this stretch of
						the calendar has behaved in past years, plus whatever share of the current
						swing history says survives. Written down now so it can be marked later.
					</p>
					{#each nextWeek as t (t.id)}
						<div class="tr-row">
							<div class="tr-line">
								<span class="tr-dot {t.confidence}" aria-hidden="true"></span>
								<span class="tr-text">{t.headline}</span>
							</div>
							<div class="tr-meta">
								{t.detail}
								<span class="tr-band">Likely range {t.range_display}.</span>
								{#if t.source === 'graded_record'}
									<span class="tr-thin" title="No league-wide feed splits innings by starter or reliever, so this one rests on our own graded games rather than seasons of league data.">
										our games only
									</span>
								{/if}
							</div>
						</div>
					{:else}
						<div class="tr-empty">
							Not enough finished games yet to forecast next week.
						</div>
					{/each}
					{#if hiddenNext > 0}
						<button class="tr-more" onclick={() => (showAllNext = !showAllNext)}>
							{showAllNext ? 'Show fewer' : `Show ${hiddenNext} more`}
						</button>
					{/if}
				</div>
			</div>

			{#if trends.recent_graded.length}
				<div class="tr-graded">
					<span class="tr-graded-label">How earlier calls did</span>
					{#each trends.recent_graded.slice(0, 6) as t (t.id)}
						<span
							class="tr-chip"
							class:hit={t.hit}
							class:miss={!t.hit}
							title="{t.headline} — called {t.predicted_display ?? t.predicted}, came in at {t.actual_display ??
								t.actual} across {t.n_window} games"
						>
							{t.hit ? '✓' : '✗'}
							{t.label ?? t.metric}
						</span>
					{/each}
				</div>
			{/if}
		{/if}
	</section>
{/if}

{#if accuracy}
	<a class="acc-card" href="/accuracy" data-sveltekit-preload-data="hover">
		<div class="acc-head">
			<h2>Model accuracy</h2>
			<span class="acc-window">last night against the {ACC_DAYS} days it belongs to</span>
			<span class="acc-more">Full report →</span>
		</div>
		{#if accuracy.window.games === 0 && (accuracyDay?.window.games ?? 0) === 0}
			<!-- An empty window is a real state, not a failure: grading runs
			     overnight, so before the first run of the day there is genuinely
			     nothing to show. Saying so beats hiding the card, which reads as
			     the feature being broken. -->
			<p class="acc-empty">
				Games are graded against their box scores every night. Nothing has been graded
				for {accuracy.window.start} to {accuracy.window.end} yet — open the report to
				grade it now.
			</p>
		{:else}
			<!-- A grid rather than two sets of tiles: the whole request was to be
			     able to compare the two, and comparison wants the numbers on the
			     same row, not in two blocks the eye has to travel between. -->
			<div class="acc-grid">
				<div class="acc-gh acc-metric">&nbsp;</div>
				<div class="acc-gh acc-day">
					<span class="acc-col-lab">Yesterday</span>
					<span class="acc-col-sub">
						{accuracyDay?.window.end ?? '—'}
						{#if dayGames === 0}
							· not graded yet
						{:else}
							· {dayGames} game{dayGames === 1 ? '' : 's'}
							{#if !comparable}· too few to compare{/if}
						{/if}
					</span>
				</div>
				<div class="acc-gh acc-span">
					<span class="acc-col-lab">Last {ACC_DAYS} days</span>
					<span class="acc-col-sub">
						{accuracy.window.start} → {accuracy.window.end} ·
						{accuracy.window.games} game{accuracy.window.games === 1 ? '' : 's'}
					</span>
				</div>

				{#each ACC_ROWS as row (row.label)}
					{@const d = row.pick(accuracyDay)}
					{@const w = row.pick(accuracy)}
					<div class="acc-metric">
						<span class="acc-lab">{row.label}</span>
						<span class="acc-sub">{row.note}</span>
					</div>
					<div class="acc-cell acc-day" class:acc-pending={dayGames === 0}>
						<span class="acc-val">{dayGames === 0 ? '·' : row.fmt(d)}</span>
						{#if d !== null && w !== null && comparable}
							{@const delta = row.better(d, w)}
							<span class="acc-delta" class:up={delta > 0} class:down={delta < 0}>
								{delta > 0 ? '▲ better' : delta < 0 ? '▼ worse' : '■ level'}
							</span>
						{/if}
					</div>
					<div class="acc-cell acc-span">
						<span class="acc-val">{row.fmt(w)}</span>
					</div>
				{/each}
			</div>
			{#if dayGames === 0}
				<!-- An empty column with no explanation reads as a bug. It usually
				     isn't one: grading runs overnight in CI, so a night is blank
				     until that run has been round. -->
				<p class="acc-note">
					Nothing graded for {accuracyDay?.window.end ?? 'yesterday'} yet — grading runs
					overnight, and the last night in the record is
					{latestGraded ?? 'earlier'}.
				</p>
			{/if}
		{/if}
	</a>
{/if}

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
	.bb {
		border: 1px solid color-mix(in srgb, var(--accent-pred) 40%, var(--border));
		border-radius: 12px;
		background: #0a1020;
		margin-bottom: 0.9rem;
		overflow: hidden;
	}
	/* Expected trends — two horizons side by side, with the forecasts' own
	   track record in the header so the section is accountable for itself. */
	.tr {
		border: 1px solid var(--border);
		border-radius: 12px;
		background: #0a1020;
		margin-bottom: 0.9rem;
		padding: 0.7rem 0.9rem 0.8rem;
	}
	/* Collapsed, the header is the whole section, so it shouldn't carry the
	   bottom margin that separates it from content that isn't there. */
	.tr:not(.open) {
		padding-bottom: 0.7rem;
	}
	.tr:not(.open) .tr-head {
		margin-bottom: 0;
	}
	.tr-head {
		display: flex;
		align-items: baseline;
		gap: 0.6rem;
		flex-wrap: wrap;
		margin-bottom: 0.55rem;
	}
	.tr-toggle {
		flex: 1;
		min-width: 0;
		display: flex;
		align-items: baseline;
		gap: 0.6rem;
		flex-wrap: wrap;
		background: none;
		border: none;
		padding: 0;
		color: inherit;
		font: inherit;
		cursor: pointer;
		text-align: left;
	}
	.tr-caret {
		background: none;
		border: none;
		color: var(--muted);
		font-size: 0.8rem;
		padding: 0 0.15rem;
		cursor: pointer;
	}
	.tr-head h2 {
		margin: 0;
		font-size: 0.95rem;
		letter-spacing: 0.02em;
	}
	.tr-sub {
		font-size: 0.72rem;
		color: var(--muted);
		min-width: 0;
	}
	.tr-score {
		margin-left: auto;
		font-size: 0.72rem;
		color: var(--accent-pred);
		white-space: nowrap;
		cursor: help;
	}
	.tr-of {
		color: var(--muted);
	}
	.tr-pending {
		color: var(--muted);
		cursor: default;
	}
	.tr-cols {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 0.5rem;
	}
	.tr-col {
		min-width: 0;
		padding-top: 0.35rem;
	}
	.tr-col + .tr-col {
		border-left: 1px solid var(--border);
		padding-left: 0.6rem;
	}
	.tr-col-head {
		display: flex;
		align-items: baseline;
		gap: 0.4rem;
	}
	.tr-title {
		font-size: 0.78rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.tr-window {
		font-size: 0.65rem;
		color: var(--muted);
		font-variant-numeric: tabular-nums;
	}
	.tr-blurb {
		margin: 0.15rem 0 0.45rem;
		font-size: 0.66rem;
		color: var(--muted);
		line-height: 1.3;
	}
	.tr-row {
		padding: 0.35rem 0;
		border-top: 1px solid var(--border);
	}
	.tr-line {
		display: flex;
		align-items: baseline;
		gap: 0.4rem;
	}
	.tr-dot {
		flex: none;
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--muted);
	}
	.tr-dot.high {
		background: #4ade80;
	}
	.tr-dot.medium {
		background: #fbbf24;
	}
	.tr-dot.low {
		background: #64748b;
	}
	.tr-arrow {
		flex: none;
		width: 6px;
		font-size: 0.55rem;
		line-height: 1.4;
		color: var(--muted);
	}
	.tr-arrow.up {
		color: #4ade80;
	}
	.tr-arrow.down {
		color: #f87171;
	}
	/* A reading the record can only half stand behind should not shout in the
	   same colour as one it can. */
	.tr-arrow.soft {
		opacity: 0.5;
	}
	.tr-text {
		font-size: 0.78rem;
		line-height: 1.25;
	}
	.tr-meta {
		font-size: 0.65rem;
		color: var(--muted);
		margin-left: 0.85rem;
		line-height: 1.35;
	}
	.tr-band {
		opacity: 0.75;
	}
	/* Says out loud that a card rests on a thinner record than its neighbours,
	   rather than letting it borrow their authority by sitting next to them. */
	.tr-thin {
		display: inline-block;
		margin-left: 0.2rem;
		padding: 0 0.28rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		font-size: 0.58rem;
		opacity: 0.8;
		cursor: help;
	}
	.tr-quiet .tr-text {
		color: var(--muted);
	}
	.tr-more {
		margin-top: 0.4rem;
		padding: 0;
		border: 0;
		background: none;
		color: var(--muted);
		font: inherit;
		font-size: 0.65rem;
		text-decoration: underline;
		text-underline-offset: 2px;
		cursor: pointer;
	}
	.tr-more:hover {
		color: inherit;
	}
	.tr-empty {
		font-size: 0.7rem;
		color: var(--muted);
		padding: 0.3rem 0;
	}
	.tr-graded {
		display: flex;
		align-items: center;
		gap: 0.3rem;
		flex-wrap: wrap;
		margin-top: 0.6rem;
		padding-top: 0.5rem;
		border-top: 1px solid var(--border);
	}
	.tr-graded-label {
		font-size: 0.65rem;
		color: var(--muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.tr-chip {
		font-size: 0.64rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		padding: 0.05rem 0.4rem;
		white-space: nowrap;
		cursor: help;
	}
	.tr-chip.hit {
		color: #4ade80;
	}
	.tr-chip.miss {
		color: #f87171;
	}
	@media (max-width: 640px) {
		.tr-cols {
			grid-template-columns: 1fr;
		}
		.tr-col + .tr-col {
			border-left: none;
			border-top: 1px solid var(--border);
			padding-left: 0;
			padding-top: 0.5rem;
			margin-top: 0.3rem;
		}
	}

	/* Accuracy snapshot — the whole card is the link into the full report. */
	.acc-card {
		display: block;
		border: 1px solid var(--border);
		border-radius: 12px;
		background: #0a1020;
		margin-bottom: 0.9rem;
		padding: 0.7rem 0.9rem 0.85rem;
		text-decoration: none;
		color: inherit;
		transition: border-color 0.15s ease, background 0.15s ease;
	}
	.acc-card:hover,
	.acc-card:focus-visible {
		border-color: color-mix(in srgb, var(--accent-pred) 55%, var(--border));
		background: #0c1426;
	}
	.acc-head {
		display: flex;
		align-items: baseline;
		gap: 0.6rem;
		flex-wrap: wrap;
		margin-bottom: 0.6rem;
	}
	.acc-head h2 {
		margin: 0;
		font-size: 0.95rem;
		letter-spacing: 0.02em;
	}
	.acc-window {
		font-size: 0.72rem;
		color: var(--muted);
		min-width: 0;
	}
	.acc-more {
		margin-left: auto;
		font-size: 0.72rem;
		color: var(--accent-pred);
		white-space: nowrap;
	}
	/* Metric name, then the two windows. Fixed columns for the numbers so the
	   two are the same width and the eye can run straight down each. */
	.acc-grid {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(5.5rem, 8rem) minmax(5.5rem, 10rem);
		gap: 0.15rem 0.5rem;
		align-items: center;
	}
	.acc-gh {
		display: flex;
		flex-direction: column;
		gap: 0.05rem;
		padding-bottom: 0.3rem;
		border-bottom: 1px solid var(--border);
		margin-bottom: 0.2rem;
	}
	.acc-col-lab {
		font-size: 0.72rem;
		font-weight: 600;
	}
	.acc-col-sub {
		font-size: 0.62rem;
		color: var(--muted);
	}
	/* The two windows are shaded differently on purpose — the request was to be
	   able to tell them apart at a glance, and a shared border isn't enough. */
	.acc-day {
		background: #101a2e;
		border-radius: 6px;
		padding-left: 0.45rem;
		padding-right: 0.45rem;
	}
	.acc-span {
		background: #0d1526;
		border-radius: 6px;
		padding-left: 0.45rem;
		padding-right: 0.45rem;
	}
	.acc-metric {
		display: flex;
		flex-direction: column;
		gap: 0.02rem;
		min-width: 0;
		padding: 0.3rem 0;
	}
	.acc-cell {
		display: flex;
		flex-direction: column;
		gap: 0.02rem;
		padding: 0.3rem 0.45rem;
		min-width: 0;
	}
	.acc-delta {
		font-size: 0.6rem;
		color: var(--muted);
	}
	.acc-delta.up {
		color: var(--accent-pred);
	}
	.acc-delta.down {
		color: var(--danger);
	}
	/* A column awaiting its overnight run is dimmed rather than blank, so it
	   reads as "not yet" instead of "broken". */
	.acc-pending .acc-val {
		color: var(--muted);
		opacity: 0.5;
	}
	.acc-note {
		margin: 0.5rem 0 0;
		font-size: 0.66rem;
		color: var(--muted);
	}
	.acc-empty {
		margin: 0;
		font-size: 0.75rem;
		color: var(--muted);
		max-width: 70ch;
	}
	.acc-val {
		font-size: 1.05rem;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		line-height: 1.1;
	}
	.acc-lab {
		font-size: 0.7rem;
		color: var(--text);
		line-height: 1.15;
	}
	.acc-sub {
		font-size: 0.65rem;
		color: var(--muted);
	}
	@media (max-width: 520px) {
		.acc-grid {
			grid-template-columns: minmax(0, 1fr) minmax(4rem, 5rem) minmax(4rem, 6rem);
			gap: 0.15rem 0.25rem;
		}
		/* The per-metric note is the first thing to go when there's no room. */
		.acc-metric .acc-sub {
			display: none;
		}
		.acc-delta {
			font-size: 0.55rem;
		}
	}
	.bb-head {
		width: 100%;
		display: flex;
		align-items: baseline;
		gap: 0.6rem;
		padding: 0.7rem 0.9rem;
	}
	.bb-toggle {
		flex: 1;
		min-width: 0;
		display: flex;
		align-items: baseline;
		gap: 0.6rem;
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
		text-align: left;
	}
	.bb-rerun {
		flex: none;
		background: none;
		border: 1px solid var(--border);
		border-radius: 5px;
		color: var(--text-2);
		cursor: pointer;
		font-size: 0.62rem;
		font-weight: 800;
		letter-spacing: 0.05em;
		padding: 0.22rem 0.5rem;
		text-transform: uppercase;
		white-space: nowrap;
	}
	.bb-rerun:hover:not(:disabled) {
		border-color: var(--accent-pred);
		color: var(--accent-pred);
	}
	.bb-rerun:disabled {
		opacity: 0.45;
		cursor: progress;
	}
	.bb-title {
		color: var(--accent-pred);
		font-size: 0.95rem;
		font-weight: 900;
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}
	.bb-sub {
		flex: 1;
		color: var(--text-label);
		font-size: 0.74rem;
		font-weight: 600;
	}
	.bb-caret {
		flex: none;
		background: none;
		border: none;
		padding: 0 0 0 0.1rem;
		cursor: pointer;
		color: var(--text-label);
		font-size: 0.8rem;
	}
	.bb-body {
		padding: 0 0.9rem 0.8rem;
	}
	.bb-msg,
	.bb-foot {
		color: var(--text-label);
		font-size: 0.74rem;
		font-weight: 600;
		line-height: 1.45;
	}
	.bb-msg {
		padding: 0.4rem 0;
	}
	.bb-foot {
		margin-top: 0.5rem;
	}
	/* Both market families side by side at every width — seeing them at once is
	   the point, so they stay in columns rather than reflowing. The gaps, rank
	   gutter and type still tighten below 720px: a half-width column has to
	   hold a player name and three numbers without spilling. */
	.bb-quads {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 0.5rem;
	}
	.bb-quad {
		display: flex;
		flex-direction: column;
		min-width: 0;
		padding-top: 0.45rem;
	}
	.bb-quad + .bb-quad {
		border-left: 1px solid var(--border);
		padding-left: 0.5rem;
	}
	@media (min-width: 720px) {
		.bb-quads {
			gap: 0.5rem 0.9rem;
		}
		.bb-quad + .bb-quad {
			padding-left: 0.9rem;
		}
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
	.bb-quad-head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 0.4rem;
		color: var(--accent-pred);
		font-size: 0.62rem;
		font-weight: 900;
		text-transform: uppercase;
		letter-spacing: 0.07em;
		padding-bottom: 0.3rem;
	}
	.bb-more {
		/* Supplementary — a ~91px column can't fit it next to the title, and
		   the title is the part that has to be readable. */
		display: none;
		color: var(--text-label);
		font-size: 0.55rem;
		font-weight: 700;
		letter-spacing: 0.02em;
		text-transform: none;
		white-space: nowrap;
	}
	@media (min-width: 720px) {
		.bb-more {
			display: inline;
		}
	}
	.bb-empty {
		color: var(--text-label);
		font-size: 0.68rem;
		font-weight: 600;
		line-height: 1.4;
		border-top: 1px solid var(--border);
		padding: 0.5rem 0;
	}
	.bb-row {
		display: grid;
		/* The rank gutter is sized to a single digit — at three columns on a
		   phone every pixel it takes comes off the player's name. */
		grid-template-columns: 0.65rem 1fr;
		align-items: start;
		gap: 0.25rem;
		padding: 0.4rem 0;
		border-top: 1px solid var(--border);
		text-decoration: none;
	}
	@media (min-width: 720px) {
		.bb-row {
			grid-template-columns: 1rem 1fr;
			gap: 0.4rem;
			padding: 0.45rem 0;
		}
	}
	.bb-rank {
		color: var(--text-label);
		font-size: 0.7rem;
		font-weight: 800;
		line-height: 1.35;
	}
	.bb-pick {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.bb-sel {
		color: var(--text);
		font-size: 0.72rem;
		font-weight: 800;
		line-height: 1.22;
		/* Long player names have to break rather than push the column wide. */
		overflow-wrap: anywhere;
	}
	@media (min-width: 720px) {
		.bb-sel {
			font-size: 0.82rem;
			line-height: 1.25;
		}
	}
	.bb-game {
		color: var(--text-label);
		font-size: 0.58rem;
		font-weight: 600;
		/* At three narrow columns this wraps rather than truncating: clipped to
		   "NYY @ BOS · D…" the book name says nothing, and which book is
		   holding the price is the difference between a placeable bet and a
		   number on a screen. Wide enough to fit, it goes back to one line. */
		overflow-wrap: anywhere;
	}
	@media (min-width: 720px) {
		.bb-game {
			font-size: 0.62rem;
			white-space: nowrap;
			overflow: hidden;
			text-overflow: ellipsis;
		}
	}
	.bb-meta {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 0 0.4rem;
		margin-top: 0.15rem;
	}
	.bb-price {
		color: var(--text-2);
		font-size: 0.7rem;
		font-weight: 800;
		font-variant-numeric: tabular-nums;
	}
	.bb-edge {
		color: var(--accent-pred);
		font-size: 0.7rem;
		font-weight: 900;
		font-variant-numeric: tabular-nums;
	}
	@media (min-width: 720px) {
		.bb-price,
		.bb-edge {
			font-size: 0.78rem;
		}
	}
	/* Below the bar: still worth seeing, but it must not wear the same colour
	   as a play we're actually backing. */
	.bb-edge.flat {
		color: var(--text-label);
		font-weight: 700;
	}
	.bb-hit {
		color: var(--text-label);
		font-size: 0.64rem;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
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

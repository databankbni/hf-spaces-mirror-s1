<script lang="ts">
	import { onMount } from 'svelte';
	import {
		api,
		type AccuracyReport,
		type StatAccuracy,
		type StatBlock,
		type PlayerAccuracy,
		type ScoredGame
	} from '$lib/api';
	import TeamLogo from '$lib/TeamLogo.svelte';

	function todayIso(): string {
		const d = new Date();
		return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
	}
	function addDays(iso: string, n: number): string {
		const d = new Date(iso + 'T12:00:00');
		d.setDate(d.getDate() + n);
		return d.toISOString().slice(0, 10);
	}

	// The window ends yesterday: today's games have not finished, so including
	// them can only add rows that cannot be scored.
	let endDate = $state(addDays(todayIso(), -1));
	let days = $state(5);
	let report = $state<AccuracyReport | null>(null);
	let loading = $state(true);
	let refreshing = $state(false);
	let error = $state('');

	// Which section is open. The report is large, so it opens on the summary
	// and the reader chooses what to expand rather than scrolling past it all.
	let tab = $state<'outcomes' | 'positions' | 'players' | 'games'>('outcomes');
	let openPosition = $state<string | null>(null);
	let playerFilter = $state('');
	let playerSide = $state<'all' | 'batter' | 'pitcher'>('all');
	let sortStat = $state('');
	let openGame = $state<string | null>(null);
	let gameDetail = $state<ScoredGame | null>(null);
	let gameLoading = $state(false);

	let token = 0;

	async function load(refresh = false) {
		const mine = ++token;
		if (refresh) refreshing = true;
		else loading = true;
		error = '';
		try {
			const r = await api.accuracyReport({ date: endDate, days, refresh });
			if (mine === token) report = r;
		} catch (e) {
			if (mine === token) error = String(e);
		} finally {
			if (mine === token) {
				loading = false;
				refreshing = false;
			}
		}
	}

	onMount(() => load());

	async function toggleGame(gameId: string) {
		if (openGame === gameId) {
			openGame = null;
			gameDetail = null;
			return;
		}
		openGame = gameId;
		gameDetail = null;
		gameLoading = true;
		try {
			gameDetail = await api.accuracyGame(gameId);
		} catch (e) {
			error = String(e);
		} finally {
			gameLoading = false;
		}
	}

	const STAT_LABELS: Record<string, string> = {
		pa: 'PA', ab: 'AB', hits: 'H', home_runs: 'HR', rbi: 'RBI', bb: 'BB', k: 'K',
		outs: 'Outs', hits_allowed: 'H allowed', runs_allowed: 'ER',
		bb_allowed: 'BB allowed', pitches: 'Pitches'
	};
	const label = (s: string) => STAT_LABELS[s] ?? s;

	// Green when the model is close, amber in the middle, red when it is not.
	// Thresholds are deliberately generous: a per-game count stat is noisy and
	// 80% on a single hitter's hits is a good forecast, not a poor one.
	function tone(pct: number | null | undefined): string {
		if (pct === null || pct === undefined) return '';
		if (pct >= 80) return 'good';
		if (pct >= 60) return 'ok';
		return 'poor';
	}
	function biasTone(bias: number, scale = 0.25): string {
		return Math.abs(bias) <= scale ? 'good' : Math.abs(bias) <= scale * 2 ? 'ok' : 'poor';
	}
	const sign = (v: number) => (v > 0 ? `+${v.toFixed(2)}` : v.toFixed(2));

	let statKeys = $derived.by(() => {
		const b = Object.keys(report?.batting ?? {});
		const p = Object.keys(report?.pitching ?? {});
		return { batting: b, pitching: p };
	});

	let filteredPlayers = $derived.by(() => {
		let list: PlayerAccuracy[] = report?.players ?? [];
		if (playerSide !== 'all') list = list.filter((p) => p.side === playerSide);
		const q = playerFilter.trim().toLowerCase();
		if (q) {
			list = list.filter(
				(p) => p.name.toLowerCase().includes(q) || p.team.toLowerCase().includes(q)
			);
		}
		if (sortStat) {
			list = [...list].sort((a, b) => {
				const av = a.stats[sortStat]?.accuracy_pct;
				const bv = b.stats[sortStat]?.accuracy_pct;
				if (av === undefined && bv === undefined) return 0;
				if (av === undefined) return 1;
				if (bv === undefined) return -1;
				return av - bv; // worst first — that is what needs looking at
			});
		}
		return list;
	});

	let positionPlayers = $derived.by(() =>
		openPosition ? (report?.players ?? []).filter((p) => p.position === openPosition) : []
	);
</script>

<svelte:head><title>Model accuracy · The Beast</title></svelte:head>

<div class="head">
	<div>
		<h1>Model accuracy</h1>
		<p class="sub">
			Every finished game re-scored against its box score — the score, the outcome, and
			every player who appeared.
		</p>
	</div>
	<a class="back" href="/matchups">← Slate</a>
</div>

<div class="controls">
	<label>
		<span>Window ends</span>
		<input type="date" bind:value={endDate} onchange={() => load()} />
	</label>
	<label>
		<span>Days</span>
		<select bind:value={days} onchange={() => load()}>
			<option value={5}>5</option>
			<option value={10}>10</option>
			<option value={15}>15</option>
			<option value={30}>30</option>
		</select>
	</label>
	<button class="refresh" onclick={() => load(true)} disabled={refreshing || loading}>
		{refreshing ? 'Scoring…' : 'Score new games'}
	</button>
	{#if report?.refreshed}
		<span class="refreshed">
			{report.refreshed.newly_scored} newly scored · {report.refreshed.already_scored} already
		</span>
	{/if}
</div>

{#if loading}
	<div class="msg">Loading…</div>
{:else if error}
	<div class="msg err">{error}</div>
{:else if !report || report.window.games === 0}
	<div class="msg">
		No games scored in this window yet. Press <strong>Score new games</strong> to grade the
		finished games in it — that runs a simulation per game, so it takes a moment.
	</div>
{:else}
	<div class="window">
		{report.window.games} games · {report.window.start} to {report.window.end}
		{#if report.window.resimulated_games > 0}
			<span
				class="caveat"
				title="These games were re-simulated after the fact, so the season statlines behind the projection already include the game being graded. The effect of one game on a season line is small, but it flatters the model."
				>· {report.window.resimulated_games} re-simulated ⓘ</span
			>
		{/if}
	</div>

	<nav class="tabs">
		<button class:active={tab === 'outcomes'} onclick={() => (tab = 'outcomes')}>
			Scores &amp; outcomes
		</button>
		<button class:active={tab === 'positions'} onclick={() => (tab = 'positions')}>
			By position
		</button>
		<button class:active={tab === 'players'} onclick={() => (tab = 'players')}>
			Players ({report.players.length})
		</button>
		<button class:active={tab === 'games'} onclick={() => (tab = 'games')}>
			Games ({report.games.length})
		</button>
	</nav>

	{#if tab === 'outcomes'}
		<section class="grid">
			<div class="stat-card">
				<span class="big {tone(report.outcomes.winner_accuracy_pct)}">
					{report.outcomes.winner_accuracy_pct ?? '—'}%
				</span>
				<span class="cap">Winners picked</span>
				<span class="note">
					{report.outcomes.winners_correct} of {report.outcomes.games_scored}
					{#if report.outcomes.ties}· {report.outcomes.ties} tie(s) excluded{/if}
				</span>
			</div>
			<div class="stat-card">
				<span class="big">{report.outcomes.brier ?? '—'}</span>
				<span class="cap">Brier score</span>
				<span class="note">lower is better · 0.25 = a coin flip</span>
			</div>
			<div class="stat-card">
				<span class="big">{report.outcomes.log_loss ?? '—'}</span>
				<span class="cap">Log loss</span>
				<span class="note">lower is better · 0.69 = a coin flip</span>
			</div>
			<div class="stat-card">
				<span class="big">{report.outcomes.total_mae?.toFixed(2) ?? '—'}</span>
				<span class="cap">Total runs, average miss</span>
				<span class="note">runs between projected and actual</span>
			</div>
			<div class="stat-card">
				<span class="big">{report.outcomes.run_mae?.toFixed(2) ?? '—'}</span>
				<span class="cap">Team runs, average miss</span>
				<span class="note">per team, per game</span>
			</div>
			<div class="stat-card">
				<span class="big">{report.outcomes.spread_mae?.toFixed(2) ?? '—'}</span>
				<span class="cap">Margin, average miss</span>
				<span class="note">home minus away</span>
			</div>
			<div class="stat-card">
				<span class="big">{report.outcomes.total_coverage_pct ?? '—'}%</span>
				<span class="cap">Totals inside the range</span>
				<span class="note">the p10–p90 band should catch 80%</span>
			</div>
			<div class="stat-card">
				<span class="big">{report.outcomes.team_runs_coverage_pct ?? '—'}%</span>
				<span class="cap">Team runs inside the range</span>
				<span class="note">same 80% target</span>
			</div>
			<div class="stat-card">
				<span class="big">{report.outcomes.mean_exact_score_pct?.toFixed(1) ?? '—'}%</span>
				<span class="cap">Chance given to the exact final</span>
				<span class="note">averaged over games</span>
			</div>
		</section>

		{#if report.outcomes.calibration.length}
			<h3>Win-probability calibration</h3>
			<p class="hint">
				Of the games called at a given confidence, how many actually happened. Close
				agreement means the number means what it says.
			</p>
			<table>
				<thead>
					<tr>
						<th>Confidence</th><th class="num">Games</th><th class="num">Predicted</th>
						<th class="num">Actual</th><th class="num">Gap (pp)</th>
					</tr>
				</thead>
				<tbody>
					{#each report.outcomes.calibration as b}
						<tr>
							<td>{b.range}</td>
							<td class="num">{b.n}</td>
							<td class="num">{(b.predicted * 100).toFixed(1)}%</td>
							<td class="num">{(b.actual * 100).toFixed(1)}%</td>
							<td class="num {biasTone(b.actual - b.predicted, 0.08)}">
								{sign((b.actual - b.predicted) * 100)}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}

		<h3>Batting, all players</h3>
		{@render statTable(report.batting, statKeys.batting)}
		<h3>Pitching, all pitchers</h3>
		{@render statTable(report.pitching, statKeys.pitching)}

		{#if report.by_lineup_slot.length}
			<h3>By lineup slot</h3>
			<p class="hint">
				A model that is accurate at the top of the order and poor at the bottom is making a
				different mistake from one that is evenly off.
			</p>
			<table>
				<thead>
					<tr>
						<th>Slot</th>
						{#each statKeys.batting as s}<th class="num">{label(s)}</th>{/each}
					</tr>
				</thead>
				<tbody>
					{#each report.by_lineup_slot as row}
						<tr>
							<td>{row.slot}</td>
							{#each statKeys.batting as s}
								<td class="num {tone(row.stats[s]?.accuracy_pct)}">
									{row.stats[s] ? `${row.stats[s].accuracy_pct}%` : '—'}
								</td>
							{/each}
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}

		<p class="coverage">
			{report.coverage.unprojected_appearances} appearance(s) the model never projected
			(pinch-hitters, callups) · {report.coverage.projected_but_absent} projected player(s) who
			did not appear. Both are counted as coverage gaps rather than quietly dropped.
		</p>
	{/if}

	{#if tab === 'positions'}
		<p class="hint">Pick a position to see every player graded at it.</p>
		<div class="pos-grid">
			{#each report.by_position as pos}
				<button
					class="pos-card"
					class:open={openPosition === pos.position}
					onclick={() => (openPosition = openPosition === pos.position ? null : pos.position)}
				>
					<span class="pos-name">{pos.position}</span>
					<span class="pos-n">{pos.players} player{pos.players === 1 ? '' : 's'}</span>
					<div class="pos-stats">
						{#each Object.entries(pos.stats).slice(0, 4) as [s, v]}
							<span class="chip {tone(v.accuracy_pct)}">{label(s)} {v.accuracy_pct}%</span>
						{/each}
					</div>
				</button>
			{/each}
		</div>

		{#if openPosition}
			{@const pos = report.by_position.find((p) => p.position === openPosition)}
			{#if pos}
				<h3>{openPosition} — every stat</h3>
				{@render statTable(pos.stats, Object.keys(pos.stats))}
			{/if}
			<h3>{openPosition} — players</h3>
			{@render playerTable(positionPlayers)}
		{/if}
	{/if}

	{#if tab === 'players'}
		<div class="filters">
			<input placeholder="Filter by name or team" bind:value={playerFilter} />
			<select bind:value={playerSide}>
				<option value="all">All</option>
				<option value="batter">Batters</option>
				<option value="pitcher">Pitchers</option>
			</select>
			<select bind:value={sortStat}>
				<option value="">Sort: most games</option>
				{#each [...new Set([...statKeys.batting, ...statKeys.pitching])] as s}
					<option value={s}>Sort: worst {label(s)}</option>
				{/each}
			</select>
			<span class="count">{filteredPlayers.length} shown</span>
		</div>
		{@render playerTable(filteredPlayers)}
	{/if}

	{#if tab === 'games'}
		<table class="games">
			<thead>
				<tr>
					<th>Date</th><th>Game</th><th>Final</th><th class="num">Win prob</th>
					<th>Pick</th><th class="num">Proj total</th><th class="num">Miss</th><th>In range</th>
				</tr>
			</thead>
			<tbody>
				{#each report.games as g}
					<tr class="clickable" onclick={() => toggleGame(g.game_id)}>
						<td>{g.date}</td>
						<td class="matchup">
							<TeamLogo abbr={g.away} size={16} /> {g.away}
							<span class="at">@</span>
							<TeamLogo abbr={g.home} size={16} /> {g.home}
						</td>
						<td class="num">{g.actual.away_runs}–{g.actual.home_runs}</td>
						<td class="num">
							{g.home_win_probability !== null
								? `${(g.home_win_probability * 100).toFixed(0)}%`
								: '—'}
						</td>
						<td>
							{#if g.picked_winner === null}<span class="muted">tie</span>
							{:else if g.picked_winner}<span class="good">✓</span>
							{:else}<span class="poor">✗</span>{/if}
						</td>
						<td class="num">{g.predicted_total?.toFixed(1) ?? '—'}</td>
						<td class="num">{g.total_error !== null ? sign(g.total_error) : '—'}</td>
						<td>{g.total_covered ? '✓' : '✗'}</td>
					</tr>
					{#if openGame === g.game_id}
						<tr class="detail-row">
							<td colspan="8">
								{#if gameLoading}
									<div class="msg">Loading box score…</div>
								{:else if gameDetail}
									{@render gameCard(gameDetail)}
								{:else}
									<div class="msg">No scorecard available for this game.</div>
								{/if}
							</td>
						</tr>
					{/if}
				{/each}
			</tbody>
		</table>
	{/if}
{/if}

{#snippet statTable(stats: StatBlock, keys: string[])}
	<div class="scroll">
		<table>
			<thead>
				<tr>
					<th>Stat</th><th class="num">Lines</th><th class="num">Projected</th>
					<th class="num">Actual</th><th class="num">Avg miss</th><th class="num">Bias</th>
					<th class="num">Exact</th><th class="num">Accuracy</th>
				</tr>
			</thead>
			<tbody>
				{#each keys as s}
					{@const v = stats[s]}
					{#if v}
						<tr>
							<td>{label(s)}</td>
							<td class="num">{v.n}</td>
							<td class="num">{v.proj_per_game.toFixed(2)}</td>
							<td class="num">{v.actual_per_game.toFixed(2)}</td>
							<td class="num">{v.mae.toFixed(2)}</td>
							<td class="num {biasTone(v.bias)}">{sign(v.bias)}</td>
							<td class="num">{v.exact_pct}%</td>
							<td class="num {tone(v.accuracy_pct)}">{v.accuracy_pct}%</td>
						</tr>
					{/if}
				{/each}
			</tbody>
		</table>
	</div>
{/snippet}

{#snippet playerTable(players: PlayerAccuracy[])}
	<div class="scroll">
		<table class="players">
			<thead>
				<tr>
					<th>Player</th><th>Team</th><th>Pos</th><th class="num">G</th>
					<th>Stat accuracy (projected → actual, average miss)</th>
				</tr>
			</thead>
			<tbody>
				<!-- Aggregate rows (the bullpen, an unidentified starter) all carry
				     player_id 0, so id + team + side is not unique; the server keys
				     them by position too and the key here has to match or the list
				     throws and renders nothing. -->
				{#each players as p (`${p.side}-${p.player_id}-${p.team}-${p.position ?? ''}-${p.name}`)}
					<tr>
						<td class="pname">{p.name}</td>
						<td>{p.team}</td>
						<td>{p.position ?? '—'}</td>
						<td class="num">{p.games}</td>
						<td>
							<div class="chips">
								{#each Object.entries(p.stats) as [s, v]}
									<span
										class="chip {tone(v.accuracy_pct)}"
										title="{label(s)}: projected {v.proj_per_game.toFixed(
											2
										)} per game, actual {v.actual_per_game.toFixed(
											2
										)}, average miss {v.mae.toFixed(2)}, bias {sign(v.bias)}"
									>
										{label(s)} {v.accuracy_pct}%
									</span>
								{/each}
							</div>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
	{#if !players.length}<div class="msg">No players match.</div>{/if}
{/snippet}

{#snippet gameCard(g: ScoredGame)}
	<div class="gc">
		<div class="gc-head">
			<strong>{g.away} @ {g.home}</strong>
			<span>final {g.actual.away_runs}–{g.actual.home_runs}</span>
			<span>{g.n.toLocaleString()} sims</span>
			{#if !g.has_boxscore}<span class="warn">no box score — players not graded</span>{/if}
		</div>

		<h4>Hitters</h4>
		{@render scoredRows(g.batters, ['pa', 'ab', 'hits', 'home_runs', 'rbi', 'bb', 'k'])}
		<h4>Pitchers</h4>
		{@render scoredRows(g.pitchers, [
			'outs',
			'hits_allowed',
			'runs_allowed',
			'bb_allowed',
			'k',
			'pitches'
		])}
	</div>
{/snippet}

{#snippet scoredRows(rows: ScoredGame['batters'], keys: string[])}
	<div class="scroll">
		<table class="scored">
			<thead>
				<tr>
					<th>Player</th><th>Pos</th>
					{#each keys as s}<th class="num">{label(s)}</th>{/each}
				</tr>
			</thead>
			<tbody>
				{#each rows as r}
					<tr class:absent={!r.played} class:unprojected={!r.projected}>
						<td class="pname">
							{r.name}
							{#if !r.projected}<span class="tag">not projected</span>{/if}
							{#if !r.played}<span class="tag">did not play</span>{/if}
							{#if r.starter_changed}<span class="tag">starter changed</span>{/if}
							{#if r.aggregate}<span class="tag">{r.arms_used} arms</span>{/if}
						</td>
						<td>{r.position ?? '—'}</td>
						{#each keys as s}
							{@const v = r.stats[s]}
							<td class="num">
								{#if !v}—
								{:else}
									<span class="proj">{v.projected?.toFixed(2) ?? '—'}</span>
									<span class="arrow">→</span>
									<span class="act">{v.actual ?? '—'}</span>
								{/if}
							</td>
						{/each}
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/snippet}

<style>
	.head {
		display: flex;
		align-items: flex-start;
		gap: 1rem;
		margin-bottom: 0.8rem;
	}
	h1 {
		margin: 0;
		font-size: 1.3rem;
	}
	.sub {
		margin: 0.25rem 0 0;
		color: var(--muted);
		font-size: 0.8rem;
		max-width: 60ch;
	}
	.back {
		margin-left: auto;
		color: var(--accent-pred);
		text-decoration: none;
		font-size: 0.8rem;
		white-space: nowrap;
	}
	.controls {
		display: flex;
		align-items: flex-end;
		gap: 0.7rem;
		flex-wrap: wrap;
		margin-bottom: 0.7rem;
	}
	.controls label {
		display: flex;
		flex-direction: column;
		gap: 0.2rem;
		font-size: 0.7rem;
		color: var(--muted);
	}
	.controls input,
	.controls select,
	.filters input,
	.filters select {
		background: #0d1526;
		border: 1px solid var(--border);
		border-radius: 6px;
		color: var(--text);
		padding: 0.3rem 0.45rem;
		font-size: 0.8rem;
	}
	.refresh {
		background: none;
		border: 1px solid var(--border);
		border-radius: 6px;
		color: var(--text);
		padding: 0.35rem 0.7rem;
		font-size: 0.78rem;
		cursor: pointer;
	}
	.refresh:hover:not(:disabled) {
		border-color: var(--accent-pred);
	}
	.refresh:disabled {
		opacity: 0.55;
		cursor: default;
	}
	.refreshed,
	.count {
		font-size: 0.72rem;
		color: var(--muted);
	}
	.window {
		font-size: 0.75rem;
		color: var(--muted);
		margin-bottom: 0.6rem;
	}
	.caveat {
		cursor: help;
		border-bottom: 1px dotted var(--muted);
	}
	.tabs {
		display: flex;
		gap: 0.35rem;
		flex-wrap: wrap;
		border-bottom: 1px solid var(--border);
		margin-bottom: 0.9rem;
	}
	.tabs button {
		background: none;
		border: none;
		border-bottom: 2px solid transparent;
		color: var(--muted);
		padding: 0.4rem 0.6rem;
		font-size: 0.8rem;
		cursor: pointer;
	}
	.tabs button.active {
		color: var(--text);
		border-bottom-color: var(--accent-pred);
	}
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
		gap: 0.6rem;
		margin-bottom: 1.2rem;
	}
	.stat-card {
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
		border: 1px solid var(--border);
		border-radius: 9px;
		background: #0d1526;
		padding: 0.6rem 0.7rem;
	}
	.big {
		font-size: 1.4rem;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
	}
	.cap {
		font-size: 0.75rem;
	}
	.note {
		font-size: 0.66rem;
		color: var(--muted);
	}
	h3 {
		font-size: 0.9rem;
		margin: 1.1rem 0 0.4rem;
	}
	h4 {
		font-size: 0.8rem;
		margin: 0.7rem 0 0.3rem;
		color: var(--muted);
	}
	.hint {
		font-size: 0.73rem;
		color: var(--muted);
		margin: 0 0 0.5rem;
		max-width: 70ch;
	}
	.scroll {
		overflow-x: auto;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.78rem;
	}
	th,
	td {
		text-align: left;
		padding: 0.32rem 0.5rem;
		border-bottom: 1px solid var(--border);
		white-space: nowrap;
	}
	th {
		color: var(--muted);
		font-weight: 600;
		font-size: 0.7rem;
		text-transform: uppercase;
		letter-spacing: 0.03em;
	}
	.num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	.good {
		color: #4ade80;
	}
	.ok {
		color: #fbbf24;
	}
	.poor {
		color: #f87171;
	}
	.muted {
		color: var(--muted);
	}
	.pos-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
		gap: 0.55rem;
		margin-bottom: 1rem;
	}
	.pos-card {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		align-items: flex-start;
		border: 1px solid var(--border);
		border-radius: 9px;
		background: #0d1526;
		padding: 0.55rem 0.6rem;
		cursor: pointer;
		text-align: left;
		color: inherit;
	}
	.pos-card:hover,
	.pos-card.open {
		border-color: var(--accent-pred);
	}
	.pos-name {
		font-size: 1rem;
		font-weight: 700;
	}
	.pos-n {
		font-size: 0.68rem;
		color: var(--muted);
	}
	.pos-stats,
	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: 0.25rem;
	}
	.chip {
		font-size: 0.66rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		padding: 0.05rem 0.4rem;
		white-space: nowrap;
	}
	.filters {
		display: flex;
		gap: 0.5rem;
		align-items: center;
		flex-wrap: wrap;
		margin-bottom: 0.6rem;
	}
	.pname {
		white-space: normal;
		min-width: 11rem;
	}
	.players td,
	.scored td {
		vertical-align: top;
	}
	.games .clickable {
		cursor: pointer;
	}
	.games .clickable:hover {
		background: #0d1526;
	}
	.matchup {
		display: flex;
		align-items: center;
		gap: 0.25rem;
	}
	.at {
		color: var(--muted);
		margin: 0 0.1rem;
	}
	.detail-row td {
		background: #0a1020;
		white-space: normal;
	}
	.gc-head {
		display: flex;
		gap: 0.8rem;
		flex-wrap: wrap;
		font-size: 0.76rem;
		color: var(--muted);
		margin-bottom: 0.3rem;
	}
	.warn {
		color: #fbbf24;
	}
	.tag {
		font-size: 0.6rem;
		color: var(--muted);
		border: 1px solid var(--border);
		border-radius: 999px;
		padding: 0 0.3rem;
		margin-left: 0.25rem;
		white-space: nowrap;
	}
	.absent,
	.unprojected {
		opacity: 0.72;
	}
	.proj {
		color: var(--muted);
	}
	.arrow {
		color: var(--border);
		margin: 0 0.15rem;
	}
	.act {
		font-weight: 600;
	}
	.msg {
		padding: 0.8rem;
		font-size: 0.82rem;
		color: var(--muted);
	}
	.msg.err {
		color: #f87171;
	}
	.coverage {
		font-size: 0.72rem;
		color: var(--muted);
		margin-top: 1rem;
		max-width: 75ch;
	}
</style>

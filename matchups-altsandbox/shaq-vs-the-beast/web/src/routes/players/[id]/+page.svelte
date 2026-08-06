<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import {
		api,
		type PlayerDetail,
		type BatterRow,
		type PitcherRow,
		type PlayerGameLog
	} from '$lib/api';
	import TeamLogo from '$lib/TeamLogo.svelte';
	import PlayerPhoto from '$lib/PlayerPhoto.svelte';

	const playerId = Number($page.params.id);

	let detail = $state<PlayerDetail | null>(null);
	let loading = $state(true);
	let error = $state('');

	// Season game log (per-game lines, live entries flagged + polled).
	let gameLog = $state<PlayerGameLog | null>(null);
	let logLoading = $state(true);
	let logGroup = $state<'hitting' | 'pitching'>('hitting');
	let logPollTimer: ReturnType<typeof setInterval> | null = null;

	onMount(async () => {
		try {
			detail = await api.player(playerId);
			logGroup = detail.batting.length ? 'hitting' : 'pitching';
		} catch (e) {
			error = String(e);
		} finally {
			loading = false;
		}
		if (detail) await loadGameLog();
	});
	onDestroy(stopLogPolling);

	function stopLogPolling() {
		if (logPollTimer !== null) {
			clearInterval(logPollTimer);
			logPollTimer = null;
		}
	}

	async function loadGameLog() {
		stopLogPolling();
		logLoading = true;
		const season =
			(logGroup === 'hitting' ? detail?.batting.at(-1)?.season : detail?.pitching.at(-1)?.season) ??
			undefined;
		try {
			gameLog = await api.playerGameLog(playerId, logGroup, season);
		} catch (e) {
			console.warn('game log fetch failed', e);
			gameLog = null;
		} finally {
			logLoading = false;
		}
		// Poll while a game in the log is live so its accumulating line updates.
		logPollTimer = setInterval(() => {
			if (gameLog?.games.some((g) => g.status === 'Live')) loadGameLog();
			else stopLogPolling();
		}, 20_000);
	}

	function pickGroup(g: 'hitting' | 'pitching') {
		if (logGroup === g) return;
		logGroup = g;
		loadGameLog();
	}

	function fmtLogDate(d: string): string {
		if (!d) return '';
		return new Date(d + 'T12:00:00').toLocaleDateString(undefined, {
			month: 'short',
			day: 'numeric'
		});
	}
	function liveLabel(g: { inning: number | null; inning_half: string | null }): string {
		const half = g.inning_half === 'Top' ? 'Top' : g.inning_half === 'Bottom' ? 'Bot' : '';
		return g.inning ? `${half} ${g.inning}` : 'LIVE';
	}

	const HIT_COLS = [
		['ab', 'AB'], ['r', 'R'], ['h', 'H'], ['hr', 'HR'], ['rbi', 'RBI'],
		['bb', 'BB'], ['k', 'K'], ['sb', 'SB']
	] as const;
	const PIT_COLS = [
		['ip', 'IP'], ['h', 'H'], ['r', 'R'], ['er', 'ER'], ['bb', 'BB'],
		['k', 'K'], ['hr', 'HR']
	] as const;
	const logCols = $derived(logGroup === 'hitting' ? HIT_COLS : PIT_COLS);

	const latestBat = $derived(detail?.batting.at(-1) ?? null);
	const latestPit = $derived(detail?.pitching.at(-1) ?? null);

	// Eight-bucket outcome mix for the latest batting season.
	const RATE_KEYS: { key: keyof BatterRow; label: string }[] = [
		{ key: 'single_rate', label: '1B' },
		{ key: 'double_rate', label: '2B' },
		{ key: 'triple_rate', label: '3B' },
		{ key: 'hr_rate', label: 'HR' },
		{ key: 'bb_rate', label: 'BB' },
		{ key: 'hbp_rate', label: 'HBP' },
		{ key: 'k_rate', label: 'K' },
		{ key: 'ipo_rate', label: 'IPO' }
	];

</script>

<svelte:head>
	<title>{detail?.name ?? 'Player'} — The Beast</title>
</svelte:head>

<div class="back-row">
	<a class="back" href="/players">‹ Players</a>
</div>

{#if error}<div class="error">{error}</div>{/if}
{#if loading}
	<div class="loading"><span class="spinner"></span> Loading player…</div>
{:else if detail}
	<div class="hero">
		<PlayerPhoto playerId={detail.player_id} name={detail.name} size={72} />
		<div class="hero-info">
			<h1>{detail.name}</h1>
			<div class="hero-sub">
				{#if latestBat?.team}<span class="team"><TeamLogo abbr={latestBat.team} size={20} /> {latestBat.team}</span>{/if}
				{#if latestBat}<span>Bats {latestBat.hand}</span>{/if}
				{#if latestPit}<span>Throws {latestPit.hand} · {latestPit.role}</span>{/if}
			</div>
		</div>
	</div>

	{#if latestBat}
		<h2>Metrics <span class="muted-inline">· {latestBat.season} season</span></h2>
		<div class="metric-grid">
			<div class="metric"><span class="m-label">wOBA</span><span class="m-value">{latestBat.woba.toFixed(3)}</span></div>
			<div class="metric"><span class="m-label">xwOBA</span><span class="m-value">{latestBat.xwoba.toFixed(3)}</span></div>
			<div class="metric"><span class="m-label">ISO</span><span class="m-value">{latestBat.iso.toFixed(3)}</span></div>
			<div class="metric"><span class="m-label">BABIP</span><span class="m-value">{latestBat.babip.toFixed(3)}</span></div>
			<div class="metric">
				<span class="m-label">Sprint speed</span>
				<span class="m-value">{latestBat.sprint_speed_ft_s != null ? latestBat.sprint_speed_ft_s.toFixed(1) + ' ft/s' : '—'}</span>
			</div>
			<div class="metric"><span class="m-label">PA</span><span class="m-value">{latestBat.pa}</span></div>
		</div>

		<h2>PA outcome mix <span class="muted-inline">· share of plate appearances</span></h2>
		<div class="rates">
			{#each RATE_KEYS as rk}
				{@const v = latestBat[rk.key] as number}
				<div class="rate-row">
					<span class="rate-label">{rk.label}</span>
					<div class="rate-track"><div class="rate-fill" style={`width:${Math.min(100, v * 100 * 2.2)}%`}></div></div>
					<span class="rate-val">{(v * 100).toFixed(1)}%</span>
				</div>
			{/each}
		</div>

		<h2>Platoon splits</h2>
		<div class="metric-grid narrow">
			<div class="metric"><span class="m-label">vs LHP</span><span class="m-value">×{latestBat.platoon_split['vL']?.toFixed(2) ?? '1.00'}</span></div>
			<div class="metric"><span class="m-label">vs RHP</span><span class="m-value">×{latestBat.platoon_split['vR']?.toFixed(2) ?? '1.00'}</span></div>
		</div>
	{/if}

	{#if latestPit}
		<h2>Pitching metrics <span class="muted-inline">· {latestPit.season} season</span></h2>
		<div class="metric-grid">
			<div class="metric"><span class="m-label">FIP</span><span class="m-value">{latestPit.fip.toFixed(2)}</span></div>
			<div class="metric"><span class="m-label">K%</span><span class="m-value">{(latestPit.k_rate * 100).toFixed(1)}%</span></div>
			<div class="metric"><span class="m-label">BB%</span><span class="m-value">{(latestPit.bb_allowed * 100).toFixed(1)}%</span></div>
			<div class="metric"><span class="m-label">HR%</span><span class="m-value">{(latestPit.hr_allowed * 100).toFixed(1)}%</span></div>
			<div class="metric"><span class="m-label">BF</span><span class="m-value">{latestPit.bf}</span></div>
			<div class="metric"><span class="m-label">Role</span><span class="m-value">{latestPit.role}</span></div>
		</div>
	{/if}

	{#if detail.batting.length}
		<h2>Season totals — batting</h2>
		<div class="table-scroll">
			<table>
				<thead>
					<tr><th>Season</th><th>PA</th><th>wOBA</th><th>xwOBA</th><th>ISO</th><th>HR%</th><th>BB%</th><th>K%</th><th>SPD</th></tr>
				</thead>
				<tbody>
					{#each [...detail.batting].reverse() as b (b.season)}
						<tr>
							<td class="seasoncell">{b.season}</td>
							<td>{b.pa}</td>
							<td>{b.woba.toFixed(3)}</td>
							<td>{b.xwoba.toFixed(3)}</td>
							<td>{b.iso.toFixed(3)}</td>
							<td>{(b.hr_rate * 100).toFixed(1)}</td>
							<td>{(b.bb_rate * 100).toFixed(1)}</td>
							<td>{(b.k_rate * 100).toFixed(1)}</td>
							<td>{b.sprint_speed_ft_s != null ? b.sprint_speed_ft_s.toFixed(1) : '—'}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}

	{#if detail.pitching.length}
		<h2>Season totals — pitching</h2>
		<div class="table-scroll">
			<table>
				<thead>
					<tr><th>Season</th><th>Role</th><th>BF</th><th>FIP</th><th>K%</th><th>BB%</th><th>HR%</th></tr>
				</thead>
				<tbody>
					{#each [...detail.pitching].reverse() as p (p.season)}
						<tr>
							<td class="seasoncell">{p.season}</td>
							<td>{p.role}</td>
							<td>{p.bf}</td>
							<td>{p.fip.toFixed(2)}</td>
							<td>{(p.k_rate * 100).toFixed(1)}</td>
							<td>{(p.bb_allowed * 100).toFixed(1)}</td>
							<td>{(p.hr_allowed * 100).toFixed(1)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}

	<!-- ── Season game log ── -->
	<h2>
		Game log <span class="muted-inline">· {(gameLog?.season ?? latestBat?.season ?? latestPit?.season) ?? ''} season</span>
		{#if detail.batting.length && detail.pitching.length}
			<span class="log-group-tabs">
				<button class:active={logGroup === 'hitting'} onclick={() => pickGroup('hitting')}>Hitting</button>
				<button class:active={logGroup === 'pitching'} onclick={() => pickGroup('pitching')}>Pitching</button>
			</span>
		{/if}
	</h2>
	{#if logLoading}
		<div class="loading"><span class="spinner"></span> Loading game log…</div>
	{:else if gameLog && gameLog.games.length}
		<div class="table-scroll">
			<table class="log-table">
				<thead>
					<tr>
						<th class="when-col">Date</th>
						<th class="opp-col">Opp</th>
						{#each logCols as [, label]}<th>{label}</th>{/each}
					</tr>
				</thead>
				<tbody>
					{#each gameLog.games as g (g.game_pk ?? g.date)}
						<tr class:live-row={g.status === 'Live'}>
							<td class="when-col">
								{#if g.status === 'Live'}
									<span class="live-pill"><span class="live-dot"></span>{liveLabel(g)}</span>
								{:else}
									{fmtLogDate(g.date)}
								{/if}
							</td>
							<td class="opp-col">
								<span class="opp-inner">
									<span class="opp-ha">{g.is_home ? 'vs' : '@'}</span>
									<TeamLogo abbr={g.opponent} size={16} /> {g.opponent}
								</span>
							</td>
							{#each logCols as [key]}
								<td>{g.stats[key] ?? '—'}</td>
							{/each}
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else}
		<div class="log-empty">No game log available for this season.</div>
	{/if}
{/if}

<style>
	.back-row {
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
	.error {
		color: var(--danger);
		margin: 1rem 0;
	}
	.loading {
		color: var(--text-muted);
		display: flex;
		align-items: center;
		gap: 0.7rem;
		padding: 2rem 0;
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
	.hero {
		display: flex;
		align-items: center;
		gap: 1.2rem;
		margin-bottom: 2rem;
		padding-bottom: 1.5rem;
		border-bottom: 1px solid var(--border);
	}
	h1 {
		margin: 0 0 0.3rem;
		font-size: 1.6rem;
		font-weight: 900;
		font-style: italic;
		text-transform: uppercase;
		letter-spacing: 0.02em;
	}
	.hero-sub {
		display: flex;
		flex-wrap: wrap;
		gap: 1rem;
		color: var(--text-label);
		font-size: 0.82rem;
		font-weight: 600;
	}
	.team {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
	}
	h2 {
		text-transform: uppercase;
		letter-spacing: 0.08em;
		font-size: 0.82rem;
		font-weight: 800;
		border-bottom: 1px solid var(--border);
		padding-bottom: 0.5rem;
		margin: 2rem 0 1rem;
	}
	.muted-inline {
		color: var(--text-label);
		text-transform: none;
		letter-spacing: 0;
		font-size: 0.75rem;
		font-weight: 400;
	}
	.metric-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
		gap: 0.7rem;
	}
	.metric-grid.narrow {
		max-width: 320px;
	}
	.metric {
		background: var(--bg-surface);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 0.6rem 0.7rem;
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}
	.m-label {
		font-size: 0.64rem;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-label);
		font-weight: 700;
	}
	.m-value {
		font-size: 1.15rem;
		font-weight: 800;
		font-variant-numeric: tabular-nums;
	}
	.rates {
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
		max-width: 520px;
	}
	.rate-row {
		display: grid;
		grid-template-columns: 2.6rem 1fr 3.4rem;
		align-items: center;
		gap: 0.6rem;
	}
	.rate-label {
		color: var(--text-label);
		text-transform: uppercase;
		font-size: 0.7rem;
		font-weight: 800;
	}
	.rate-track {
		background: var(--bg-surface);
		border-radius: 3px;
		height: 8px;
		overflow: hidden;
	}
	.rate-fill {
		background: var(--accent-pred);
		height: 100%;
	}
	.rate-val {
		text-align: right;
		font-size: 0.78rem;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
	}
	.table-scroll {
		overflow-x: auto;
		border: 1px solid var(--border);
		border-radius: 8px;
		background: #0c1428;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.86rem;
		font-variant-numeric: tabular-nums;
	}
	th {
		color: var(--text-label);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-size: 0.66rem;
		font-weight: 700;
		text-align: right;
		padding: 0.55rem 0.6rem;
		border-bottom: 1px solid var(--border);
		background: var(--bg-surface);
	}
	td {
		text-align: right;
		padding: 0.45rem 0.6rem;
		border-bottom: 1px solid var(--border-faint);
		color: var(--text-2);
	}
	th:first-child,
	td:first-child {
		text-align: left;
	}
	.seasoncell {
		font-weight: 800;
		color: var(--text);
	}

	/* ── Game log ── */
	.log-group-tabs {
		display: inline-flex;
		gap: 0.25rem;
		margin-left: 0.6rem;
		vertical-align: middle;
	}
	.log-group-tabs button {
		background: none;
		border: none;
		border-bottom: 2px solid transparent;
		color: var(--text-label);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-size: 0.66rem;
		font-weight: 800;
		padding: 0.2rem 0.4rem;
		cursor: pointer;
	}
	.log-group-tabs button.active {
		color: var(--text);
		border-bottom-color: var(--accent-pred);
	}
	.log-table th.when-col,
	.log-table td.when-col {
		text-align: left;
		white-space: nowrap;
	}
	.log-table th.opp-col,
	.log-table td.opp-col {
		text-align: left;
	}
	.opp-inner {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		font-weight: 700;
		white-space: nowrap;
	}
	.opp-ha {
		color: var(--text-label);
		font-weight: 600;
		width: 1.1rem;
		display: inline-block;
	}
	.live-row td {
		background: color-mix(in srgb, var(--accent-actual, #00fff2) 8%, transparent);
	}
	.live-pill {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		color: var(--accent-actual, #00fff2);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		font-size: 0.66rem;
		font-weight: 800;
	}
	.live-dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: #ff3b3b;
		display: inline-block;
		animation: pulse 1.4s ease-in-out infinite;
	}
	@keyframes pulse {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.35; }
	}
	.log-empty {
		color: var(--text-muted);
		padding: 1rem 0;
		font-size: 0.9rem;
	}
</style>

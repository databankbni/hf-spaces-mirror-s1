<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { api, type TeamAggregate } from '$lib/api';
	import TeamLogo from '$lib/TeamLogo.svelte';
	import { teamName, teamVenue } from '$lib/teams';

	const abbr = $derived(($page.params.abbr ?? '').toUpperCase());

	let team = $state<TeamAggregate | null>(null);
	let stats = $state<TeamAggregate[]>([]);
	let loading = $state(true);
	let error = $state('');

	onMount(async () => {
		try {
			const [t, s] = await Promise.all([
				api.team($page.params.abbr ?? ''),
				api.teamstats().catch(() => [] as TeamAggregate[])
			]);
			team = t;
			stats = s;
		} catch (e) {
			error = String(e);
		} finally {
			loading = false;
		}
	});

	const withRanks = $derived(stats.find((t) => t.team === abbr) ?? null);

	interface RankRow {
		label: string;
		key: string;
		fmt: (v: number) => string;
	}
	const RANKINGS: RankRow[] = [
		{ label: 'Lineup wOBA', key: 'lineup_woba', fmt: (v) => v.toFixed(3) },
		{ label: 'Lineup xwOBA', key: 'lineup_xwoba', fmt: (v) => v.toFixed(3) },
		{ label: 'ISO Power', key: 'lineup_iso', fmt: (v) => v.toFixed(3) },
		{ label: 'HR Rate', key: 'lineup_hr_rate', fmt: (v) => (v * 100).toFixed(1) + '%' },
		{ label: 'BB Rate', key: 'lineup_bb_rate', fmt: (v) => (v * 100).toFixed(1) + '%' },
		{ label: 'K Rate', key: 'lineup_k_rate', fmt: (v) => (v * 100).toFixed(1) + '%' },
		{ label: 'Sprint Speed', key: 'sprint_speed', fmt: (v) => v.toFixed(1) + ' ft/s' },
		{ label: 'Bullpen FIP', key: 'bullpen_fip', fmt: (v) => v.toFixed(2) }
	];

	function tier(rank: number | null): string {
		if (rank == null) return '';
		if (rank <= 5) return 'tier-elite';
		if (rank <= 12) return 'tier-good';
		if (rank <= 22) return 'tier-avg';
		return 'tier-poor';
	}
	function statOf(key: string): number | null {
		const v = withRanks?.[key] ?? team?.[key];
		return typeof v === 'number' ? v : null;
	}
	function rankOf(key: string): number | null {
		const v = withRanks?.[`${key}_rank`];
		return typeof v === 'number' ? v : null;
	}

	const roster = $derived(team?.roster ?? []);
</script>

<svelte:head>
	<title>{abbr} — The Beast</title>
</svelte:head>

<div class="back-row">
	<a class="back" href="/teams">‹ Teams</a>
</div>

{#if error}<div class="error">{error}</div>{/if}
{#if loading}
	<div class="loading"><span class="spinner"></span> Loading team…</div>
{:else if team}
	<div class="hero">
		<TeamLogo abbr={abbr} size={84} />
		<div class="hero-info">
			<h1>{teamName(abbr)}</h1>
			<div class="hero-sub">
				<span>{teamVenue(abbr)}</span>
				{#if statOf('park_runs_factor') != null}
					<span>Park factor {statOf('park_runs_factor')?.toFixed(2)}</span>
				{/if}
			</div>
		</div>
	</div>

	<h2>Team rankings</h2>
	<div class="table-scroll">
		<table class="rank-table">
			<thead>
				<tr><th>Category</th><th class="num">Value</th><th class="num">Rank</th></tr>
			</thead>
			<tbody>
				{#each RANKINGS as row}
					{@const v = statOf(row.key)}
					{#if v != null}
						<tr>
							<td class="rcat">{row.label}</td>
							<td class="num rval">{row.fmt(v)}</td>
							<td class="num"><span class={`rk ${tier(rankOf(row.key))}`}>{rankOf(row.key) ?? '—'}</span></td>
						</tr>
					{/if}
				{/each}
			</tbody>
		</table>
	</div>
	<div class="rank-key">
		<span class="key-item tier-elite">Top 5</span>
		<span class="key-item tier-good">Top 12</span>
		<span class="key-item tier-avg">Middle</span>
		<span class="key-item tier-poor">Bottom</span>
	</div>

	<h2>Roster <span class="muted-inline">· most-used lineup, current season</span></h2>
	<div class="table-scroll">
		<table>
			<thead>
				<tr><th>Player</th><th class="num">PA</th><th class="num">wOBA</th><th class="num">ISO</th><th class="num">HR%</th><th class="num">BB%</th><th class="num">K%</th><th class="num">SPD</th></tr>
			</thead>
			<tbody>
				{#each roster as b (b.player_id)}
					<tr>
						<td class="namecell"><a href={`/players/${b.player_id}`}>{b.name}</a></td>
						<td class="num">{b.pa}</td>
						<td class="num">{b.woba.toFixed(3)}</td>
						<td class="num">{b.iso.toFixed(3)}</td>
						<td class="num">{(b.hr_rate * 100).toFixed(1)}</td>
						<td class="num">{(b.bb_rate * 100).toFixed(1)}</td>
						<td class="num">{(b.k_rate * 100).toFixed(1)}</td>
						<td class="num">{b.sprint_speed_ft_s != null ? b.sprint_speed_ft_s.toFixed(1) : '—'}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
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
		gap: 1.4rem;
		margin-bottom: 2rem;
		padding-bottom: 1.5rem;
		border-bottom: 1px solid var(--border);
	}
	h1 {
		margin: 0 0 0.3rem;
		font-size: 1.7rem;
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
		text-align: left;
		padding: 0.55rem 0.7rem;
		border-bottom: 1px solid var(--border);
		background: var(--bg-surface);
	}
	td {
		padding: 0.45rem 0.7rem;
		border-bottom: 1px solid var(--border-faint);
		color: var(--text-2);
	}
	.num {
		text-align: right;
	}
	.rcat {
		color: var(--text-label);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-size: 0.72rem;
		font-weight: 700;
	}
	.rval {
		font-weight: 700;
		color: var(--text);
	}
	.rk {
		display: inline-block;
		min-width: 1.9rem;
		border-radius: 4px;
		padding: 0.12rem 0.3rem;
		font-size: 0.72rem;
		font-weight: 800;
		text-align: center;
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
	.rank-key {
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
	.namecell a {
		color: var(--text);
		font-weight: 700;
		text-decoration: none;
	}
	.namecell a:hover {
		color: var(--accent-pred);
	}
</style>

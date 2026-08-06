<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type BatterRow, type PitcherRow } from '$lib/api';
	import TeamLogo from '$lib/TeamLogo.svelte';

	let kind = $state<'batters' | 'pitchers'>('batters');
	let rows = $state<(BatterRow | PitcherRow)[]>([]);
	let loading = $state(true);
	let error = $state('');
	let search = $state('');
	let sortKey = $state('pa');
	let sortDir = $state(-1);

	async function load() {
		loading = true;
		error = '';
		try {
			rows = await api.players(kind);
			sortKey = kind === 'batters' ? 'pa' : 'bf';
			sortDir = -1;
		} catch (e) {
			error = String(e);
		} finally {
			loading = false;
		}
	}

	onMount(load);

	function pick(k: 'batters' | 'pitchers') {
		if (kind === k) return;
		kind = k;
		load();
	}

	const BATTER_COLS = [
		{ key: 'name', label: 'Player', num: false },
		{ key: 'team', label: 'Team', num: false },
		{ key: 'pa', label: 'PA', num: true, fmt: (v: number) => v.toFixed(0) },
		{ key: 'woba', label: 'wOBA', num: true, fmt: (v: number) => v.toFixed(3) },
		{ key: 'xwoba', label: 'xwOBA', num: true, fmt: (v: number) => v.toFixed(3) },
		{ key: 'iso', label: 'ISO', num: true, fmt: (v: number) => v.toFixed(3) },
		{ key: 'hr_rate', label: 'HR%', num: true, fmt: (v: number) => (v * 100).toFixed(1) },
		{ key: 'bb_rate', label: 'BB%', num: true, fmt: (v: number) => (v * 100).toFixed(1) },
		{ key: 'k_rate', label: 'K%', num: true, fmt: (v: number) => (v * 100).toFixed(1) },
		{ key: 'sprint_speed_ft_s', label: 'SPD', num: true, fmt: (v: number) => v.toFixed(1) }
	];
	const PITCHER_COLS = [
		{ key: 'name', label: 'Player', num: false },
		{ key: 'team', label: 'Team', num: false },
		{ key: 'role', label: 'Role', num: false },
		{ key: 'bf', label: 'BF', num: true, fmt: (v: number) => v.toFixed(0) },
		{ key: 'fip', label: 'FIP', num: true, fmt: (v: number) => v.toFixed(2) },
		{ key: 'k_rate', label: 'K%', num: true, fmt: (v: number) => (v * 100).toFixed(1) },
		{ key: 'bb_allowed', label: 'BB%', num: true, fmt: (v: number) => (v * 100).toFixed(1) },
		{ key: 'hr_allowed', label: 'HR%', num: true, fmt: (v: number) => (v * 100).toFixed(1) }
	];
	const cols = $derived(kind === 'batters' ? BATTER_COLS : PITCHER_COLS);

	function sortBy(key: string) {
		if (sortKey === key) sortDir = -sortDir;
		else {
			sortKey = key;
			const col = cols.find((c) => c.key === key);
			sortDir = col?.num ? -1 : 1;
		}
	}

	const visible = $derived.by(() => {
		const q = search.trim().toLowerCase();
		let out = rows;
		if (q) {
			out = out.filter(
				(r) => r.name.toLowerCase().includes(q) || r.team.toLowerCase().includes(q)
			);
		}
		return [...out].sort((a, b) => {
			const av = (a as unknown as Record<string, unknown>)[sortKey];
			const bv = (b as unknown as Record<string, unknown>)[sortKey];
			if (av == null && bv == null) return 0;
			if (av == null) return 1;
			if (bv == null) return -1;
			if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * sortDir;
			return String(av).localeCompare(String(bv)) * sortDir;
		});
	});

	function cell(r: Record<string, unknown>, col: (typeof BATTER_COLS)[number]): string {
		const v = r[col.key];
		if (v == null) return '—';
		if (typeof v === 'number' && col.fmt) return col.fmt(v);
		return String(v);
	}
</script>

<svelte:head>
	<title>Players — The Beast</title>
</svelte:head>

<div class="controls-bar">
	<div class="controls-left">
		<div class="kind-tabs">
			<button class:active={kind === 'batters'} onclick={() => pick('batters')}>Batters</button>
			<button class:active={kind === 'pitchers'} onclick={() => pick('pitchers')}>Pitchers</button>
		</div>
	</div>
	<input class="search" type="search" placeholder="Search player or team…" bind:value={search} />
</div>

{#if error}<div class="error">{error}</div>{/if}
{#if loading}
	<div class="loading"><span class="spinner"></span> Loading statlines…</div>
{:else}
	<p class="count">{visible.length} {kind} · current-season Statcast statlines</p>
	<div class="table-scroll">
		<table>
			<thead>
				<tr>
					<th class="idx">#</th>
					{#each cols as col}
						<th class="sortable" class:numcol={col.num} onclick={() => sortBy(col.key)}>
							{col.label}{#if sortKey === col.key}<span class="arrow">{sortDir === -1 ? ' ▼' : ' ▲'}</span>{/if}
						</th>
					{/each}
				</tr>
			</thead>
			<tbody>
				{#each visible as r, i (r.player_id)}
					<tr>
						<td class="idx">{i + 1}</td>
						{#each cols as col}
							{#if col.key === 'name'}
								<td class="namecell"><a href={`/players/${r.player_id}`}>{r.name}</a></td>
							{:else if col.key === 'team'}
								<td class="teamcell">
									{#if r.team}<TeamLogo abbr={r.team} size={16} /> {r.team}{:else}—{/if}
								</td>
							{:else}
								<td class:numcol={col.num}>{cell(r as unknown as Record<string, unknown>, col)}</td>
							{/if}
						{/each}
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/if}

<style>
	.controls-bar {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		align-items: flex-end;
		gap: 0.75rem;
		padding-bottom: 1rem;
	}
	.kind-tabs {
		display: flex;
		gap: 0;
		border-bottom: 1px solid var(--border);
	}
	.kind-tabs button {
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--text-label);
		cursor: pointer;
		background: none;
		border: none;
		border-bottom: 2px solid transparent;
		padding: 0.5rem 1rem;
		font-size: 0.82rem;
		font-weight: 800;
	}
	.kind-tabs button.active {
		color: var(--text);
		border-bottom-color: var(--accent-pred);
	}
	.search {
		background: var(--bg-surface);
		border: 1px solid var(--border-input);
		color: var(--text);
		padding: 0.5rem 0.7rem;
		border-radius: 6px;
		font-size: 0.9rem;
		min-width: 240px;
	}
	.count {
		color: var(--text-label);
		font-size: 0.78rem;
		margin: 0 0 0.8rem;
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
	.table-scroll {
		overflow-x: auto;
		max-height: 72vh;
		overflow-y: auto;
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
	thead th {
		position: sticky;
		top: 0;
		background: var(--bg-surface);
		z-index: 1;
		color: var(--text-label);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-size: 0.66rem;
		font-weight: 700;
		text-align: left;
		padding: 0.55rem 0.6rem;
		border-bottom: 1px solid var(--border);
	}
	th.sortable {
		cursor: pointer;
		user-select: none;
		white-space: nowrap;
	}
	th.sortable:hover {
		color: var(--text);
	}
	.arrow {
		color: var(--accent-pred);
	}
	td {
		padding: 0.42rem 0.6rem;
		border-bottom: 1px solid var(--border-faint);
		color: var(--text-2);
	}
	.numcol {
		text-align: right;
	}
	.idx {
		color: var(--text-footnote);
		width: 2.2rem;
		text-align: right;
	}
	.namecell a {
		color: var(--text);
		font-weight: 700;
		text-decoration: none;
	}
	.namecell a:hover {
		color: var(--accent-pred);
	}
	.teamcell {
		white-space: nowrap;
	}
</style>

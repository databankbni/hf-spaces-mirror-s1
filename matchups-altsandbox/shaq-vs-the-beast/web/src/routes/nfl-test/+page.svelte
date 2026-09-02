<script lang="ts">
	// A browser over PrizePicks' NFL board, and nothing more. There is no NFL
	// simulator, so there is nothing here to compare a line against — the page
	// shows what's on offer and says so, rather than implying a read it can't
	// support.
	//
	// There are no odds columns either, and that is not an omission: PrizePicks
	// posts no price on a pick, because the payout is on the slip. The MLB
	// board derives a break-even so it can compute an edge; here there is
	// nothing to take an edge against, so showing a number would be inventing
	// one.
	import { api, type NFLProp, type NFLPropSearch } from '$lib/api';

	let query = $state('');
	let result = $state<NFLPropSearch | null>(null);
	let loading = $state(false);
	let error = $state('');
	// Bumped per request; a slow response only writes if it's still the newest.
	// Without it a fast search for "ma" lands after "mahomes" and replaces it.
	let gen = 0;
	let timer: ReturnType<typeof setTimeout> | null = null;

	// A search per keystroke would be a call per keystroke. 250ms is under the
	// gap between words, so it fires when you pause rather than as you type.
	const DEBOUNCE_MS = 250;

	async function run(q: string) {
		const mine = ++gen;
		if (!q.trim()) {
			result = null;
			error = '';
			loading = false;
			return;
		}
		loading = true;
		error = '';
		try {
			const r = await api.nflProps(q);
			if (mine === gen) result = r;
		} catch (e) {
			if (mine === gen) {
				error = String(e);
				result = null;
			}
		} finally {
			if (mine === gen) loading = false;
		}
	}

	function onInput() {
		if (timer !== null) clearTimeout(timer);
		timer = setTimeout(() => run(query), DEBOUNCE_MS);
	}

	function submit(e: Event) {
		e.preventDefault();
		if (timer !== null) clearTimeout(timer);
		run(query);
	}

	// One player's markets in one card. The feed is a flat list of lines, but
	// the question being asked is about a player, so the grouping matches the
	// question rather than the payload.
	type Grouped = { name: string; team: string | null; position: string | null; props: NFLProp[] };
	const grouped = $derived.by<Grouped[]>(() => {
		const by = new Map<string, Grouped>();
		for (const p of result?.props ?? []) {
			const g = by.get(p.player_key) ?? {
				name: p.player_name,
				team: p.team,
				position: p.position,
				props: []
			};
			g.props.push(p);
			by.set(p.player_key, g);
		}
		return [...by.values()];
	});
</script>

<svelte:head><title>NFL test · The Beast</title></svelte:head>

<h1>NFL test</h1>
<p class="lede">
	Search PrizePicks' NFL player props by name. This is a look at what's on offer — there's no NFL
	simulator behind it, so nothing here is being compared against a projection.
</p>

<form class="search" onsubmit={submit}>
	<input
		type="search"
		bind:value={query}
		oninput={onInput}
		placeholder="Player name — e.g. Mahomes"
		aria-label="Search NFL player props by name"
		autocomplete="off"
	/>
	<button type="submit" disabled={!query.trim()}>Search</button>
</form>

{#if loading}
	<p class="state"><span class="spinner"></span> Searching PrizePicks…</p>
{:else if error}
	<!-- PrizePicks is an undocumented app endpoint, so a failure here is a real
	     possibility rather than a remote one. Say which it was. -->
	<p class="state err">Couldn't reach PrizePicks: {error}</p>
{:else if result && result.count === 0}
	<p class="state" class:err={result.unreachable}>{result.note ?? 'Nothing found.'}</p>
{:else if result}
	<p class="state">
		{result.count} prop{result.count === 1 ? '' : 's'} across {result.players} player{result.players ===
		1
			? ''
			: 's'}
	</p>

	{#each grouped as g (g.name)}
		<section class="player">
			<header>
				<h2>{g.name}</h2>
				{#if g.position}<span class="tag">{g.position}</span>{/if}
				{#if g.team}<span class="tag">{g.team}</span>{/if}
			</header>
			<div class="table-scroll">
				<table>
					<thead>
						<tr>
							<th class="left">Market</th>
							<th>Line</th>
							<th class="left">Pick</th>
							<th class="left">Game</th>
						</tr>
					</thead>
					<tbody>
						{#each g.props as p (p.market + p.line + p.odds_type)}
							<tr>
								<td class="left">{p.market_label}</td>
								<td class="num">{p.line}</td>
								<td class="left status">
									<!-- Demons and goblins move the line for a bigger or smaller
									     share of the slip. Shown, because they're real picks on
									     their board and this page is a browser, not a bet. -->
									{#if p.odds_type && p.odds_type !== 'standard'}
										<span class="special">{p.odds_type}</span>
									{:else}more / less{/if}
									{#if p.is_promo}<span class="special">promo</span>{/if}
								</td>
								<td class="left status">
									{#if p.is_live}<span class="live">live</span>{:else}pregame{/if}
									{#if p.opponent}<span class="opp">{p.opponent}</span>{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</section>
	{/each}
{:else}
	<p class="state muted">Type a player's name to search.</p>
{/if}

<p class="foot">
	PrizePicks posts lines for the current slate only, so a player with no game up has none. Markets
	are shown under PrizePicks' own names — nothing is dropped for being unrecognised. There are no
	odds because PrizePicks posts none: a pick is a line and a side, and the payout is on the slip.
</p>

<style>
	h1 {
		margin: 0 0 0.3rem;
		font-size: 1.25rem;
	}
	.lede {
		margin: 0 0 1rem;
		font-size: 0.8rem;
		line-height: 1.5;
		color: var(--muted);
		max-width: 60ch;
	}
	.search {
		display: flex;
		gap: 0.5rem;
		margin-bottom: 1rem;
		max-width: 30rem;
	}
	.search input {
		flex: 1;
		padding: 0.5rem 0.65rem;
		border: 1px solid var(--border);
		border-radius: 8px;
		background: #0a1020;
		color: inherit;
		font-size: 0.85rem;
	}
	.search input:focus {
		outline: none;
		border-color: var(--accent-pred);
	}
	.search button {
		padding: 0.5rem 0.9rem;
		border: 1px solid var(--border);
		border-radius: 8px;
		background: #0a1020;
		color: inherit;
		font-size: 0.8rem;
		cursor: pointer;
	}
	.search button:disabled {
		opacity: 0.45;
		cursor: default;
	}
	.state {
		margin: 0 0 0.8rem;
		font-size: 0.78rem;
		color: var(--muted);
		display: flex;
		align-items: center;
		gap: 0.4rem;
	}
	.state.err {
		color: var(--accent-vegas);
	}
	.state.muted {
		color: var(--text-label);
	}
	.spinner {
		width: 0.75rem;
		height: 0.75rem;
		border: 2px solid var(--border);
		border-top-color: var(--accent-pred);
		border-radius: 50%;
		display: inline-block;
		animation: spin 0.7s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	.player {
		border: 1px solid var(--border);
		border-radius: 12px;
		background: #0a1020;
		padding: 0.7rem 0.9rem 0.8rem;
		margin-bottom: 0.8rem;
	}
	.player header {
		display: flex;
		align-items: baseline;
		gap: 0.5rem;
		margin-bottom: 0.5rem;
		flex-wrap: wrap;
	}
	.player h2 {
		margin: 0;
		font-size: 0.9rem;
	}
	.tag {
		font-size: 0.65rem;
		padding: 0.08rem 0.4rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		color: var(--text-label);
	}
	.table-scroll {
		overflow-x: auto;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.76rem;
	}
	th {
		text-align: right;
		padding: 0.3rem 0.5rem;
		font-size: 0.66rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--text-label);
		font-weight: 500;
		border-bottom: 1px solid var(--border-faint);
	}
	td {
		text-align: right;
		padding: 0.35rem 0.5rem;
		border-bottom: 1px solid var(--border-faint);
	}
	.left {
		text-align: left;
	}
	.num {
		font-variant-numeric: tabular-nums;
	}
	.status {
		color: var(--text-label);
		font-size: 0.7rem;
	}
	.live {
		color: var(--accent-vegas);
	}
	/* Demons, goblins and promos. Marked rather than hidden — they are on
	   PrizePicks' board, and a browser that quietly dropped them would be
	   showing a different board from the app. */
	.special {
		margin-left: 0.3rem;
		font-size: 0.62rem;
		text-transform: uppercase;
		letter-spacing: 0.03em;
		padding: 0.05rem 0.32rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		color: var(--text-label);
	}
	.opp {
		margin-left: 0.35rem;
		opacity: 0.75;
	}
	.foot {
		margin: 1rem 0 0;
		font-size: 0.68rem;
		line-height: 1.5;
		color: var(--muted);
		max-width: 60ch;
	}
</style>

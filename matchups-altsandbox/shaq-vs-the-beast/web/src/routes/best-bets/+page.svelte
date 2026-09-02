<script lang="ts">
	// A pick'em board, with our number on it. The layout is PrizePicks' own —
	// a tab per stat, a card per prop, the line in the middle and the two sides
	// beneath — because the point is to read this against their app, and making
	// someone re-learn a layout to do that would cost more than it gains.
	//
	// What's added is the only thing they can't show: what our simulation says
	// each side's chance actually is, next to the bar it has to clear.
	//
	// The source is whatever the backend was configured with — PrizePicks by
	// default — and is named everywhere it's referred to rather than hardcoded,
	// because a board labelled with the wrong book is worse than an unlabelled
	// one.
	import { onMount } from 'svelte';
	import { api, type PropBoard, type PropCard } from '$lib/api';

	let board = $state<PropBoard | null>(null);
	let loading = $state(true);
	let error = $state('');
	let active = $state('');
	// '' means every game, like the app's ALL GAMES chip. Independent of the
	// stat tab: picking a game narrows whichever stat you're already looking at
	// rather than sending you back to the top.
	let activeGame = $state('');
	// Cards are cheap individually and there can be thousands. Rendering a tab
	// at a time keeps that bounded, and this caps how much of one tab lands at
	// once — the tail of a tab is sorted worst-first anyway.
	let shown = $state(60);
	const PAGE = 60;
	let retry: ReturnType<typeof setTimeout> | null = null;

	async function load() {
		loading = true;
		error = '';
		try {
			const b = await api.propBoard();
			board = b;
			// The slate is still simulating. Every percentage here comes from
			// those runs, so there's nothing to show yet — come back rather
			// than render a board that's missing games without saying so.
			if (!b.ready) {
				retry = setTimeout(load, 10_000);
				return;
			}
			if (!active || !b.groups.some((g) => tabId(g) === active)) {
				active = b.groups.length ? tabId(b.groups[0]) : '';
			}
		} catch (e) {
			error = String(e);
			board = null;
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		load();
		return () => {
			if (retry !== null) clearTimeout(retry);
		};
	});

	// Batter and pitcher strikeouts are both "k" — the side is what tells them
	// apart, so it belongs in the id.
	const tabId = (g: { side: string; stat: string }) => `${g.side}:${g.stat}`;

	const games = $derived(board?.games ?? []);

	const inGame = (c: PropCard) => !activeGame || c.game_id === activeGame;

	// Tabs carry a count, and the count has to follow the game filter — a tab
	// reading 40 that shows 3 once a game is picked is worse than no count.
	// Tabs emptied by the filter drop out entirely rather than sitting at zero.
	const groups = $derived(
		(board?.groups ?? [])
			.map((g) => ({ ...g, cards: g.cards.filter(inGame) }))
			.filter((g) => g.cards.length)
	);
	const current = $derived(groups.find((g) => tabId(g) === active) ?? groups[0] ?? null);
	const visible = $derived(current ? current.cards.slice(0, shown) : []);

	function pick(id: string) {
		active = id;
		shown = PAGE;
	}

	function pickGame(id: string) {
		activeGame = id;
		shown = PAGE;
	}

	// Whoever the board came from. Defaulted rather than left blank so the copy
	// still reads as a sentence on an older payload that predates the field.
	const book = $derived(board?.book || 'the props feed');
	// Set only by a source that posts no odds of its own. Its presence is what
	// tells the page that "needs 58%" is a break-even we chose, not a price
	// anyone quoted — and the page has to say so where the number appears, not
	// only in a footnote.
	const derivedPricing = $derived(!!board?.pricing_note);

	const pct = (v: number) => `${v.toFixed(0)}%`;
	const mult = (m: number | null) => (m === null ? '—' : `${m.toFixed(2)}x`);
	const edge = (v: number) => `${v > 0 ? '+' : ''}${v.toFixed(1)}%`;

	function firstPitch(iso: string | null): string {
		if (!iso) return '';
		const d = new Date(iso);
		return isNaN(d.getTime())
			? ''
			: d.toLocaleTimeString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' });
	}
</script>

<svelte:head><title>Best bets · The Beast</title></svelte:head>

<div class="head">
	<h1>Best bets</h1>
	{#if board?.ready}
		<span class="sub">
			{board.totals.cards} props across {board.totals.players} players ·
			<strong class="edge-count">{board.totals.with_edge}</strong> where our number beats the price
		</span>
	{/if}
</div>

<p class="lede">
	Every prop {book} is offering that our simulation keeps a distribution for, both sides, with our
	model's chance next to the bar it has to clear. A side is only marked when our number beats that
	bar — a 70% shot that needs 75% is not a bet.
</p>

{#if board?.pricing_note}
	<!-- Stated up top, not buried. A pick'em board's "needs" number is an
	     assumption of ours; a sportsbook's is a price somebody posted. Reading
	     one as the other is the single most misleading thing this page could
	     do, so it says which it is before showing any of them. -->
	<p class="assumption">{board.pricing_note}</p>
{/if}

{#if loading && !board}
	<p class="state"><span class="spinner"></span> Loading the board…</p>
{:else if error}
	<p class="state err">Couldn't load the board: {error}</p>
{:else if board && !board.ready}
	<p class="state">
		<span class="spinner"></span>
		{board.notes?.[0] ?? 'Simulating the slate…'}
	</p>
{:else if board && !groups.length}
	<p class="state">
		No props are being offered for this slate that our simulation covers.
		{#if board.props_available === false}The props feed returned nothing.{/if}
	</p>
{:else if board}
	<!-- The games strip, as the app has it: ALL GAMES, then one card per
	     game. No win-loss records — the app doesn't hold them, and a made-up
	     record next to a real price is exactly the wrong kind of filler. -->
	{#if games.length > 1}
		<div class="games">
			<button class="gcard all" class:active={activeGame === ''} onclick={() => pickGame('')}>
				<span class="gall">ALL<br />GAMES</span>
			</button>
			{#each games as g (g.game_id)}
				<button
					class="gcard"
					class:active={activeGame === g.game_id}
					class:live={g.is_live}
					onclick={() => pickGame(g.game_id)}
				>
					<span class="gteams">
						<span class="gteam">{g.away}</span>
						<span class="gteam">{g.home}</span>
					</span>
					<span class="gfoot">
						{#if g.is_live}<span class="live-tag">live</span>{:else}{firstPitch(
								g.first_pitch
							) || '—'}{/if}
						<span class="gn" class:has={g.with_edge > 0}>
							{g.with_edge > 0 ? `${g.with_edge} edge` : `${g.cards}`}
						</span>
					</span>
				</button>
			{/each}
		</div>
	{/if}

	<!-- A tab per stat, like the app. The count rides along because an empty
	     tab and a tab with nothing worth backing are different things. -->
	<div class="tabs">
		{#each groups as g (tabId(g))}
			<button class="tab" class:active={tabId(g) === active} onclick={() => pick(tabId(g))}>
				{g.label}
				{#if g.side === 'pitcher'}<span class="side-mark" title="Pitcher prop">◆</span>{/if}
				<span class="tab-n">{g.cards.length}</span>
			</button>
		{/each}
	</div>

	{#if current}
		<!-- Per-stat coverage, right above the cards it explains. "1 card" and
		     "1 of 16 quoted" are completely different facts and only one of
		     them is a bug. -->
		<!-- Always shown, never only when something is missing. "1 of 1 quoted"
		     is the answer to "why is there one card here" and it looks nothing
		     like "1 of 16" — but only if the number is on screen either way. -->
		{@const quoted = activeGame
			? (board.coverage?.[`${activeGame}|${current.side}/${current.stat}`] ?? current.offered ?? current.cards.length)
			: (current.offered ?? current.cards.length)}
		<p class="coverage">
			Showing <strong>{current.cards.length}</strong> of
			<strong>{quoted}</strong>
			{current.label.toLowerCase()} prop{quoted === 1 ? '' : 's'} in {book}'s public feed{activeGame
				? ' for this game'
				: ''}.
			{#if quoted > current.cards.length && current.unmatched}
				The other {quoted - current.cards.length} are on players not in a lineup we simulated.
			{:else if quoted <= current.cards.length}
				That's everything their public feed carries at a straight line.
			{/if}
		</p>
		<div class="grid">
			{#each visible as c (c.game_id + c.player + c.stat + c.line + c.is_live)}
				<article class="card" class:live={c.is_live}>
					<header>
						<div class="who">
							<span class="name">{c.player}</span>
							<span class="meta">
								{#if c.team}<span class="team">{c.team}</span> · {/if}{c.matchup}
							</span>
							<span class="when">
								{#if c.is_live}<span class="live-tag">live</span>{:else}{firstPitch(
										c.first_pitch
									)}{/if}
							</span>
						</div>
					</header>

					<div class="line">
						<span class="line-val">{c.line}</span>
						<span class="line-lab">{current.label}</span>
					</div>

					<!-- MORE / LESS, as the app labels them. Under each: our
					     model's chance, and what the price implies. Those two
					     numbers side by side are the whole point of the page. -->
					<div class="sides">
						{#each [{ k: 'over', word: 'MORE', arrow: '↑', s: c.over }, { k: 'under', word: 'LESS', arrow: '↓', s: c.under }] as row (row.k)}
							<div class="side" class:picked={c.best === row.k} class:dead={!row.s}>
								{#if row.s}
									<span class="word">{row.arrow} {row.word}</span>
									<span class="model">{pct(row.s.model_pct)}</span>
									<span class="model-lab">our chance</span>
									<span class="vs">
										<!-- No multiple on a pick'em card. The price behind it is a
										     break-even we derived, so rendering it as a payout would
										     put a number on screen that nobody offers. -->
										{#if row.s.multiplier !== null}
											<span class="mx">{mult(row.s.multiplier)}</span>
										{/if}
										<span class="imp">needs {pct(row.s.implied_pct)}</span>
									</span>
									<span class="edge" class:good={row.s.has_edge}>{edge(row.s.edge_pct)}</span>
								{:else}
									<span class="word">{row.arrow} {row.word}</span>
									<span class="model">—</span>
									<span class="model-lab">not offered</span>
								{/if}
							</div>
						{/each}
					</div>
				</article>
			{/each}
		</div>

		{#if current.cards.length > visible.length}
			<button class="more" onclick={() => (shown += PAGE)}>
				Show {Math.min(PAGE, current.cards.length - visible.length)} more of {current.cards.length}
			</button>
		{/if}
	{/if}

	<p class="foot">
		Percentages come from the same simulations behind the matchup cards — {visible[0]?.n_sims ??
			2000} runs a game — so a prop and the game total it belongs to can never disagree.
		{#if derivedPricing}
			"Needs" is the break-even a power play requires, which is why a side can be well over 50%
			and still not be worth taking.
		{:else}
			"Needs" is the price's own break-even including the vig, which is why a side can be over
			50% and still not be a bet.
		{/if}
		Live props are priced against the rest of the game, not the whole one.
		{#if board.unmapped_stats?.length}
			Not shown: {board.unmapped_stats.join(', ')}.
		{/if}
	</p>

	<!-- Where props went that never became a card. On the page rather than
	     behind a probe URL, because "the app offers this and you don't show it"
	     should be answerable by looking. -->
	{#if board.source && board.source.offered > board.source.priced}
		<details class="acct">
			<summary>
				{book} quoted {board.source.quoted || board.source.offered};
				{board.source.priced} became cards. Where the rest went ↓
			</summary>
			<ul>
				{#if board.source.unmatched_player}
					<li>
						<strong>{board.source.unmatched_player}</strong> — quoted on a player who isn't in
						a lineup we simulated. No per-player distribution to price against, so there's
						nothing honest to put on the card.
					</li>
				{/if}
				{#each Object.entries(board.source.dropped) as [reason, n] (reason)}
					<li><strong>{n}</strong> — {reason.replace(/_/g, ' ')}</li>
				{/each}
			</ul>
			{#if board.source.by_stat && Object.keys(board.source.by_stat).length}
				<p class="acct-sub">What their public feed carries, per market, slate-wide:</p>
				<ul class="acct-stats">
					{#each Object.entries(board.source.by_stat) as [k, n] (k)}
						<li><strong>{n}</strong> {k.replace('/', ' ').replace(/_/g, ' ')}</li>
					{/each}
				</ul>
			{/if}
			<p class="acct-foot">
				A market we don't recognise is dropped rather than guessed at: pricing a
				<em>first-inning</em> home run off a whole-game distribution would look fine and be
				wrong. If a market you can see in the app is listed here as unmapped, its name is the
				one thing needed to add it. Demons and goblins are dropped for the same reason — they
				move the line without saying what the leg now pays.
			</p>
		</details>
	{/if}

	<p class="foot">
		{#each board.notes ?? [] as n}<span class="note">{n}</span>{/each}
	</p>
{/if}

<style>
	.head {
		display: flex;
		align-items: baseline;
		gap: 0.6rem;
		flex-wrap: wrap;
		margin-bottom: 0.2rem;
	}
	h1 {
		margin: 0;
		font-size: 1.25rem;
	}
	.sub {
		font-size: 0.74rem;
		color: var(--text-label);
	}
	.edge-count {
		color: var(--accent-pred);
	}
	.lede {
		margin: 0 0 0.9rem;
		font-size: 0.76rem;
		line-height: 1.5;
		color: var(--muted);
		max-width: 70ch;
	}
	/* The one number on this page that is a decision rather than a measurement.
	   Marked so it doesn't read as another line of explanatory blurb. */
	.assumption {
		margin: 0 0 0.9rem;
		padding: 0.5rem 0.7rem;
		font-size: 0.74rem;
		line-height: 1.5;
		color: var(--muted);
		max-width: 70ch;
		border-left: 2px solid var(--accent, #6b7cff);
		background: color-mix(in srgb, var(--accent, #6b7cff) 7%, transparent);
		border-radius: 0 4px 4px 0;
	}
	.state {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		font-size: 0.78rem;
		color: var(--muted);
	}
	.state.err {
		color: var(--accent-vegas);
	}
	.spinner {
		width: 0.75rem;
		height: 0.75rem;
		border: 2px solid var(--border);
		border-top-color: var(--accent-pred);
		border-radius: 50%;
		animation: spin 0.7s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	/* The games strip. Cards rather than pills, because a matchup is two lines
	   of text and a pill would either wrap or truncate a team out of it. */
	.games {
		display: flex;
		gap: 0.5rem;
		overflow-x: auto;
		padding-bottom: 0.5rem;
		margin-bottom: 0.6rem;
		scrollbar-width: thin;
	}
	.gcard {
		flex: 0 0 auto;
		display: flex;
		flex-direction: column;
		justify-content: space-between;
		gap: 0.35rem;
		min-width: 7.5rem;
		padding: 0.5rem 0.6rem;
		border: 1px solid var(--border);
		border-radius: 10px;
		background: #0a1020;
		color: inherit;
		text-align: left;
		cursor: pointer;
	}
	.gcard.active {
		border-color: var(--accent-pred);
		box-shadow: inset 0 0 0 1px var(--accent-pred);
	}
	.gcard.live {
		border-color: color-mix(in srgb, var(--accent-vegas) 45%, var(--border));
	}
	.gcard.all {
		min-width: 5.5rem;
		align-items: center;
		justify-content: center;
	}
	.gall {
		font-size: 0.7rem;
		font-weight: 700;
		letter-spacing: 0.06em;
		text-align: center;
		line-height: 1.3;
	}
	.gteams {
		display: flex;
		flex-direction: column;
		gap: 0.1rem;
	}
	.gteam {
		font-size: 0.85rem;
		font-weight: 700;
		line-height: 1.1;
	}
	.gfoot {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 0.4rem;
		font-size: 0.6rem;
		color: var(--text-label);
	}
	.gn {
		font-variant-numeric: tabular-nums;
	}
	.gn.has {
		color: var(--accent-pred);
		font-weight: 700;
	}

	.tabs {
		display: flex;
		gap: 0.4rem;
		overflow-x: auto;
		padding-bottom: 0.5rem;
		margin-bottom: 0.8rem;
		scrollbar-width: thin;
	}
	.tab {
		flex: 0 0 auto;
		display: inline-flex;
		align-items: center;
		gap: 0.3rem;
		padding: 0.4rem 0.8rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		background: #0a1020;
		color: var(--muted);
		font-size: 0.76rem;
		font-weight: 600;
		cursor: pointer;
		white-space: nowrap;
	}
	.tab.active {
		background: var(--text);
		color: #0a1020;
		border-color: var(--text);
	}
	.tab-n {
		font-size: 0.66rem;
		opacity: 0.7;
		font-variant-numeric: tabular-nums;
	}
	.side-mark {
		font-size: 0.5rem;
		opacity: 0.7;
	}

	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr));
		gap: 0.7rem;
	}
	.card {
		border: 1px solid var(--border);
		border-radius: 12px;
		background: #0a1020;
		padding: 0.6rem 0.7rem 0;
		overflow: hidden;
		display: flex;
		flex-direction: column;
	}
	.card.live {
		border-color: color-mix(in srgb, var(--accent-vegas) 45%, var(--border));
	}
	.who {
		display: flex;
		flex-direction: column;
		gap: 0.1rem;
	}
	.name {
		font-size: 0.9rem;
		font-weight: 700;
		line-height: 1.2;
	}
	.meta {
		font-size: 0.66rem;
		color: var(--text-label);
	}
	.team {
		color: var(--accent-pred);
		font-weight: 600;
	}
	.when {
		font-size: 0.62rem;
		color: var(--text-label);
	}
	.live-tag {
		color: var(--accent-vegas);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.line {
		display: flex;
		flex-direction: column;
		align-items: center;
		padding: 0.7rem 0 0.6rem;
	}
	.line-val {
		font-size: 1.5rem;
		font-weight: 700;
		line-height: 1;
		font-variant-numeric: tabular-nums;
	}
	.line-lab {
		font-size: 0.6rem;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-label);
		margin-top: 0.15rem;
	}

	.sides {
		display: grid;
		grid-template-columns: 1fr 1fr;
		margin: 0 -0.7rem;
		border-top: 1px solid var(--border-faint);
	}
	.side {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.05rem;
		padding: 0.5rem 0.3rem 0.55rem;
	}
	.side + .side {
		border-left: 1px solid var(--border-faint);
	}
	/* The side our model prefers at the posted price. Filled rather than
	   outlined so it reads at a glance across a grid of forty cards. */
	.side.picked {
		background: color-mix(in srgb, var(--accent-pred) 12%, transparent);
	}
	.side.dead {
		opacity: 0.45;
	}
	.word {
		font-size: 0.62rem;
		font-weight: 700;
		letter-spacing: 0.04em;
		color: var(--text-label);
	}
	.model {
		font-size: 1.05rem;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		line-height: 1.15;
	}
	.model-lab {
		font-size: 0.55rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-label);
	}
	.vs {
		display: flex;
		gap: 0.3rem;
		align-items: baseline;
		margin-top: 0.2rem;
		font-size: 0.62rem;
		color: var(--muted);
		font-variant-numeric: tabular-nums;
	}
	.mx {
		font-weight: 600;
	}
	.imp {
		color: var(--text-label);
	}
	.edge {
		font-size: 0.64rem;
		font-variant-numeric: tabular-nums;
		color: var(--text-label);
	}
	.edge.good {
		color: var(--accent-pred);
		font-weight: 700;
	}

	.more {
		display: block;
		margin: 0.9rem auto 0;
		padding: 0.45rem 1rem;
		border: 1px solid var(--border);
		border-radius: 8px;
		background: #0a1020;
		color: inherit;
		font-size: 0.76rem;
		cursor: pointer;
	}
	.foot {
		margin: 1.2rem 0 0;
		font-size: 0.66rem;
		line-height: 1.55;
		color: var(--muted);
		max-width: 75ch;
	}
	.note {
		display: block;
		margin-top: 0.3rem;
	}
	.coverage {
		margin: 0 0 0.7rem;
		font-size: 0.72rem;
		line-height: 1.5;
		color: var(--muted);
		padding: 0.4rem 0.6rem;
		border-left: 2px solid var(--border);
	}
	.acct {
		margin: 0.8rem 0 0;
		border: 1px solid var(--border);
		border-radius: 10px;
		padding: 0.5rem 0.7rem;
		background: #0a1020;
		font-size: 0.7rem;
		color: var(--muted);
	}
	.acct summary {
		cursor: pointer;
		color: var(--text-label);
	}
	.acct ul {
		margin: 0.5rem 0 0;
		padding-left: 1.1rem;
		line-height: 1.55;
	}
	.acct-sub {
		margin: 0.6rem 0 0.2rem;
		color: var(--text-label);
	}
	.acct-stats {
		margin: 0;
		padding-left: 1.1rem;
		columns: 2;
		line-height: 1.5;
	}
	.acct-foot {
		margin: 0.5rem 0 0;
		font-size: 0.66rem;
		line-height: 1.5;
	}
	@media (max-width: 520px) {
		.grid {
			grid-template-columns: 1fr 1fr;
			gap: 0.5rem;
		}
		.name {
			font-size: 0.8rem;
		}
		.line-val {
			font-size: 1.3rem;
		}
	}
</style>

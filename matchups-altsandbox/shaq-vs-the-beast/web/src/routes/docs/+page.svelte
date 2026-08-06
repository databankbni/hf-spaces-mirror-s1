<svelte:head>
	<title>Docs — The Beast</title>
</svelte:head>

<h1>How The Beast works</h1>

<h2>At a glance</h2>
<p>
	The Beast is a Monte Carlo simulator for MLB games. Every matchup is simulated thousands of
	times, plate appearance by plate appearance, through a 24-state base-out Markov engine. Each
	batter-vs-pitcher plate appearance draws from a <strong>Bayesian Log5</strong> distribution
	that blends the batter's and pitcher's Statcast-derived outcome rates against league average,
	with platoon splits, park factors, weather, fielding quality, and runner speed folded in.
	Win probabilities are Platt-calibrated on a held-out season so they're honest, not just confident.
</p>

<h2>Data sources</h2>
<div class="table-scroll">
	<table>
		<thead>
			<tr><th>Source</th><th>What it feeds</th><th>How</th></tr>
		</thead>
		<tbody>
			<tr>
				<td class="src">Baseball Savant / Statcast<br /><span class="via">via pybaseball</span></td>
				<td>Per-player outcome rates — the eight PA buckets (1B, 2B, 3B, HR, BB, HBP, K, in-play out), wOBA, xwOBA, ISO, BABIP, platoon splits</td>
				<td>Season-wide PA-level pull, ingested offline into the bundled SQLite DB</td>
			</tr>
			<tr>
				<td class="src">MLB Stats API</td>
				<td>Schedules, probable starters, confirmed lineups, player names</td>
				<td>Fetched live for upcoming slates (with roster fallbacks pre-lineup)</td>
			</tr>
			<tr>
				<td class="src">Baseball Savant sprint speed</td>
				<td>Runner advancement — fast lineups take the extra base more often (1st-to-3rd on singles, scoring from 2nd)</td>
				<td>Sprint-speed leaderboard (ft/s) scales the advancement matrix relative to the ~27 ft/s league average</td>
			</tr>
			<tr>
				<td class="src">FIP / FanGraphs xFIP</td>
				<td>Pitcher quality descriptor shown across the app</td>
				<td>Computed from each pitcher's stored HR/BB/HBP/K rates (Tango FIP, constant 3.10); FanGraphs xFIP can be ingested offline</td>
			</tr>
			<tr>
				<td class="src">Baseball Savant team OAA</td>
				<td>Fielding quality — better defenses convert more balls in play into outs against opposing hitters</td>
				<td>Team Outs Above Average → multiplicative in-play-out factor in the Log5 blend</td>
			</tr>
			<tr>
				<td class="src">Park factors + weather</td>
				<td>Run environment — hitter's parks lift all offense; heat and wind move home-run rates</td>
				<td>Internal park factor table keyed by venue; weather converts to an HR multiplier</td>
			</tr>
			<tr>
				<td class="src">Retrosheet 2021–2024</td>
				<td>League-average runner advancement probabilities (the baseline matrix sprint speed personalizes)</td>
				<td>Empirical play-by-play frequencies, hardcoded</td>
			</tr>
		</tbody>
	</table>
</div>

<h2>Architecture</h2>
<ol class="arch">
	<li><strong>Data</strong> — Statcast statlines, schedules, lineups, park factors, and weather live in a bundled SQLite repository (JSON-blob schema, cheap to evolve).</li>
	<li><strong>Matchup</strong> — BatterDNA × PitcherDNA → Log5 PA distribution per batter-pitcher pair, shrunk toward league average by sample size, blended across seasons with geometric decay.</li>
	<li><strong>Simulator</strong> — 24-state inning engine samples each PA, advances runners (speed-adjusted), swaps in the bullpen after the starter's innings, and plays out 9+ innings with extras.</li>
	<li><strong>Calibration</strong> — Platt scaling de-biases win probability; a totals calibrator removes the engine's slight over-scoring.</li>
	<li><strong>Betting</strong> — model vs. market implied probability → edge, fractional Kelly staking, expected value.</li>
</ol>

<h2>Reading the numbers</h2>
<div class="table-scroll">
	<table>
		<thead>
			<tr><th>Metric</th><th>Meaning</th></tr>
		</thead>
		<tbody>
			<tr><td class="src">Proj. runs<span class="ast">*</span></td><td>Mean runs across all simulated games — the asterisk marks simulated numbers everywhere in the app</td></tr>
			<tr><td class="src">Win %</td><td>Calibrated probability of winning (ties excluded); the raw pre-calibration number is shown alongside</td></tr>
			<tr><td class="src">P10–P90</td><td>The middle 80% of simulated run totals — a range, because baseball</td></tr>
			<tr><td class="src">Spread</td><td>Mean run differential (negative = that side wins on average)</td></tr>
			<tr><td class="src">Edge</td><td>Model probability minus the market's implied probability, after the vig</td></tr>
			<tr><td class="src">Kelly stake</td><td>Fraction of bankroll at the chosen Kelly multiplier — 0 means pass</td></tr>
		</tbody>
	</table>
</div>

<style>
	h1 {
		font-size: 1.4rem;
		font-weight: 900;
		font-style: italic;
		text-transform: uppercase;
		letter-spacing: 0.03em;
		margin: 0 0 1.5rem;
	}
	h2 {
		text-transform: uppercase;
		letter-spacing: 0.08em;
		font-size: 0.82rem;
		font-weight: 800;
		border-bottom: 1px solid var(--border);
		padding-bottom: 0.5rem;
		margin: 2.2rem 0 1rem;
	}
	p {
		color: var(--text-2);
		line-height: 1.65;
		font-size: 0.92rem;
		max-width: 70ch;
	}
	.arch {
		color: var(--text-2);
		line-height: 1.65;
		font-size: 0.92rem;
		max-width: 70ch;
		padding-left: 1.2rem;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
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
	}
	th {
		color: var(--text-label);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-size: 0.66rem;
		font-weight: 700;
		text-align: left;
		padding: 0.55rem 0.8rem;
		border-bottom: 1px solid var(--border);
		background: var(--bg-surface);
	}
	td {
		padding: 0.6rem 0.8rem;
		border-bottom: 1px solid var(--border-faint);
		color: var(--text-2);
		vertical-align: top;
		line-height: 1.5;
	}
	.src {
		color: var(--text);
		font-weight: 700;
		white-space: nowrap;
	}
	.via {
		color: var(--text-label);
		font-weight: 400;
		font-size: 0.75rem;
	}
	.ast {
		color: var(--accent-pred);
		font-weight: 900;
	}
	strong {
		color: var(--text);
	}
</style>

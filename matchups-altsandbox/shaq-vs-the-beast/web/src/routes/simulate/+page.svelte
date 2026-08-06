<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type GameSchedule, type SimResult } from '$lib/api';
	import { putSim } from '$lib/simstore';
	import TeamLogo from '$lib/TeamLogo.svelte';
	import DistChart from '$lib/DistChart.svelte';

	let allGames = $state<GameSchedule[]>([]);
	let selectedGame = $state('');
	let loadingGames = $state(true);
	let running = $state(false);
	let error = $state('');
	let result = $state<SimResult | null>(null);

	// Pipeline knobs (mrsim PipelineKnobs pattern)
	let nSims = $state(2000);
	let seed = $state<number | null>(7);
	let shrinkPa = $state(200);
	let shrinkBf = $state(300);
	let useBullpen = $state(true);
	let useContext = $state(true);
	let calibrate = $state(true);
	let calibrateTotals = $state(true);

	onMount(async () => {
		try {
			allGames = await api.upcoming(4);
			if (!allGames.length) {
				const dates = await api.dates();
				if (dates.length) {
					allGames = (await Promise.all(dates.slice(-3).map((d) => api.games(d)))).flat();
				}
			}
			if (allGames.length) selectedGame = allGames[0].game_id;
		} catch (e) {
			error = String(e);
		} finally {
			loadingGames = false;
		}
	});

	async function run() {
		if (!selectedGame) return;
		running = true;
		error = '';
		try {
			result = await api.simulate({
				game_id: selectedGame,
				n: nSims,
				seed,
				shrink_pa: shrinkPa,
				shrink_bf: shrinkBf,
				use_bullpen: useBullpen,
				use_context: useContext,
				calibrate,
				calibrate_totals: calibrateTotals
			});
			putSim(selectedGame, result);
		} catch (e) {
			error = String(e);
			result = null;
		} finally {
			running = false;
		}
	}

	const selected = $derived(allGames.find((g) => g.game_id === selectedGame) ?? null);
</script>

<svelte:head>
	<title>Simulate — The Beast</title>
</svelte:head>

<h1>Simulation lab</h1>
<p class="lede">
	Run a matchup with your own pipeline knobs — sample size, shrinkage priors, bullpen usage,
	park/weather context, and calibration toggles.
</p>

{#if error}<div class="error">{error}</div>{/if}

<div class="lab">
	<div class="panel">
		<div class="panel-label">Matchup</div>
		<label class="field">
			<span>Game</span>
			<select bind:value={selectedGame}>
				{#if !allGames.length}<option value="">{loadingGames ? 'loading…' : 'no games'}</option>{/if}
				{#each allGames as g}
					<option value={g.game_id}>{g.date} · {g.away_team_id} @ {g.home_team_id}</option>
				{/each}
			</select>
		</label>
		{#if selected}
			<div class="peek">
				<TeamLogo abbr={selected.away_team_id} size={34} />
				<span class="pk-abbr">{selected.away_team_id}</span>
				<span class="pk-at">@</span>
				<TeamLogo abbr={selected.home_team_id} size={34} />
				<span class="pk-abbr">{selected.home_team_id}</span>
			</div>
		{/if}
	</div>

	<div class="panel">
		<div class="panel-label">Pipeline knobs</div>
		<div class="knob-grid">
			<label class="field"><span>Simulations</span><input type="number" min="100" max="50000" step="100" bind:value={nSims} /></label>
			<label class="field"><span>Seed</span><input type="number" bind:value={seed} /></label>
			<label class="field"><span>Batter shrink (PA)</span><input type="number" min="0" max="2000" step="50" bind:value={shrinkPa} /></label>
			<label class="field"><span>Pitcher shrink (BF)</span><input type="number" min="0" max="2000" step="50" bind:value={shrinkBf} /></label>
		</div>
		<div class="toggles">
			<label class="toggle"><input type="checkbox" bind:checked={useBullpen} /> Bullpen takeover</label>
			<label class="toggle"><input type="checkbox" bind:checked={useContext} /> Park + weather context</label>
			<label class="toggle"><input type="checkbox" bind:checked={calibrate} /> Win-prob calibration</label>
			<label class="toggle"><input type="checkbox" bind:checked={calibrateTotals} /> Totals calibration</label>
		</div>
		<button class="run" onclick={run} disabled={running || !selectedGame}>
			{running ? 'Simulating…' : 'Run simulation'}
		</button>
	</div>
</div>

{#if result}
	<div class="results">
		<div class="res-head">
			<span class="res-team"><TeamLogo abbr={result.away} size={26} /> {result.away}</span>
			<span class="res-score">{result.away_run_mean.toFixed(1)} – {result.home_run_mean.toFixed(1)}<span class="ast">*</span></span>
			<span class="res-team">{result.home} <TeamLogo abbr={result.home} size={26} /></span>
		</div>
		<div class="metric-grid">
			<div class="metric"><span class="m-label">{result.home} win %</span><span class="m-value">{(result.home_win_probability * 100).toFixed(1)}%</span></div>
			{#if result.home_win_probability_raw != null}
				<div class="metric"><span class="m-label">Raw (uncal.)</span><span class="m-value">{(result.home_win_probability_raw * 100).toFixed(1)}%</span></div>
			{/if}
			<div class="metric"><span class="m-label">Total mean</span><span class="m-value">{result.total_mean.toFixed(2)}</span></div>
			<div class="metric"><span class="m-label">Total P10–P90</span><span class="m-value">{result.total_p10.toFixed(0)}–{result.total_p90.toFixed(0)}</span></div>
			<div class="metric"><span class="m-label">Extras</span><span class="m-value">{(result.extra_inning_pct * 100).toFixed(1)}%</span></div>
			<div class="metric"><span class="m-label">Spread</span><span class="m-value">{result.spread_mean.toFixed(2)}</span></div>
		</div>
		<div class="charts">
			<DistChart hist={result.histograms.away_runs} title={`${result.away} runs`} color="var(--accent-vegas)" mean={result.away_run_mean} />
			<DistChart hist={result.histograms.home_runs} title={`${result.home} runs`} mean={result.home_run_mean} />
			<DistChart hist={result.histograms.totals} title="Total runs" color="var(--accent-actual)" mean={result.total_mean} />
		</div>
		<p class="deeplink"><a href={`/matchups/${result.game_id}`}>Full game breakdown →</a></p>
	</div>
{/if}

<style>
	h1 {
		font-size: 1.4rem;
		font-weight: 900;
		font-style: italic;
		text-transform: uppercase;
		letter-spacing: 0.03em;
		margin: 0 0 0.5rem;
	}
	.lede {
		color: var(--text-label);
		font-size: 0.88rem;
		margin: 0 0 1.5rem;
		max-width: 62ch;
	}
	.error {
		color: var(--danger);
		margin: 1rem 0;
	}
	.lab {
		display: grid;
		grid-template-columns: minmax(240px, 1fr) 2fr;
		gap: 0.85rem;
		margin-bottom: 1.5rem;
	}
	@media (max-width: 700px) {
		.lab {
			grid-template-columns: 1fr;
		}
	}
	.panel {
		border: 1px solid var(--border);
		background: #0c1428;
		border-radius: 8px;
		padding: 1.15rem;
		box-shadow: 0 2px 10px #00000059;
	}
	.panel-label {
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: #fff;
		margin-bottom: 1rem;
		font-size: 0.82rem;
		font-weight: 900;
	}
	.field {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
		margin-bottom: 0.8rem;
	}
	.field span {
		color: var(--text-label);
		text-transform: uppercase;
		letter-spacing: 0.06em;
		font-size: 0.66rem;
		font-weight: 700;
	}
	select,
	input[type='number'] {
		background: var(--bg-surface);
		border: 1px solid var(--border-input);
		color: var(--text);
		padding: 0.5rem 0.6rem;
		border-radius: 5px;
		font-size: 0.92rem;
		width: 100%;
	}
	.peek {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		justify-content: center;
		padding: 0.9rem 0 0.2rem;
	}
	.pk-abbr {
		font-weight: 800;
		font-style: italic;
		font-size: 1.05rem;
	}
	.pk-at {
		color: var(--text-label);
	}
	.knob-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
		gap: 0.6rem;
	}
	.toggles {
		display: flex;
		flex-wrap: wrap;
		gap: 0.8rem 1.4rem;
		margin: 0.4rem 0 1.1rem;
	}
	.toggle {
		display: flex;
		align-items: center;
		gap: 0.45rem;
		color: var(--text-2);
		font-size: 0.82rem;
		font-weight: 600;
		cursor: pointer;
	}
	.toggle input {
		accent-color: #6f0;
	}
	.run {
		background: var(--accent-pred);
		color: #04240a;
		border: none;
		padding: 0.6rem 1.4rem;
		border-radius: 5px;
		cursor: pointer;
		font-size: 0.88rem;
		font-weight: 800;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}
	.run:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}
	.results {
		border-top: 1px solid var(--border);
		padding-top: 1.5rem;
	}
	.res-head {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 1.2rem;
		margin-bottom: 1.2rem;
	}
	.res-team {
		display: inline-flex;
		align-items: center;
		gap: 0.45rem;
		font-weight: 800;
		font-style: italic;
		font-size: 1.1rem;
	}
	.res-score {
		font-size: 1.7rem;
		font-weight: 800;
		font-variant-numeric: tabular-nums;
		color: var(--accent-pred);
	}
	.ast {
		vertical-align: super;
		font-size: 0.6em;
		opacity: 0.8;
	}
	.metric-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
		gap: 0.7rem;
		margin-bottom: 1.2rem;
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
	.charts {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
		gap: 1rem;
	}
	.deeplink {
		margin-top: 1.2rem;
	}
	.deeplink a {
		color: var(--accent-pred);
		font-weight: 800;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		font-size: 0.8rem;
		text-decoration: none;
	}
</style>

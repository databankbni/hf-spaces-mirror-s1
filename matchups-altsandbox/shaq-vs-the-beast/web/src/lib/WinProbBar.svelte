<script lang="ts">
	interface Props {
		away: string;
		home: string;
		homeProb: number;
	}
	let { away, home, homeProb }: Props = $props();

	const awayPct = $derived(((1 - homeProb) * 100).toFixed(1));
	const homePct = $derived((homeProb * 100).toFixed(1));
</script>

<div class="winprob">
	<div class="labels">
		<span class="away">{away} {awayPct}%</span>
		<span class="home">{home} {homePct}%</span>
	</div>
	<div class="bar" role="img" aria-label={`${home} win probability ${homePct}%`}>
		<div class="seg away-seg" style={`width:${awayPct}%`}></div>
		<div class="seg home-seg" style={`width:${homePct}%`}></div>
	</div>
</div>

<style>
	.winprob {
		width: 100%;
	}
	.labels {
		display: flex;
		justify-content: space-between;
		font-size: 0.95rem;
		font-weight: 600;
		margin-bottom: 0.35rem;
	}
	.away {
		color: #ff8a5c;
	}
	.home {
		color: #4a9cff;
	}
	.bar {
		display: flex;
		height: 22px;
		border-radius: 5px;
		overflow: hidden;
		border: 1px solid #1a2a45;
	}
	.away-seg {
		background: #ff8a5c;
	}
	.home-seg {
		background: #4a9cff;
	}
</style>

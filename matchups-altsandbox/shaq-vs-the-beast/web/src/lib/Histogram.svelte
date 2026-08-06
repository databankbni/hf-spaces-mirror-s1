<script lang="ts">
	import type { Histogram } from './api';

	interface Props {
		hist: Histogram;
		title?: string;
		color?: string;
	}

	let { hist, title, color = '#4a9cff' }: Props = $props();

	const width = 380;
	const height = 140;
	const padding = { top: 8, right: 8, bottom: 22, left: 8 };

	const maxCount = $derived(Math.max(1, ...hist.counts));
	const total = $derived(hist.counts.reduce((s, c) => s + c, 0));
	const innerW = width - padding.left - padding.right;
	const innerH = height - padding.top - padding.bottom;
	const barW = $derived(innerW / Math.max(1, hist.counts.length));
	const tickIdxs = $derived([0, Math.floor(hist.edges.length / 2), hist.edges.length - 1]);
</script>

<figure>
	{#if title}<figcaption>{title}</figcaption>{/if}
	<svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title ?? 'histogram'}>
		{#each hist.counts as c, i}
			{@const h = (c / maxCount) * innerH}
			{@const x = padding.left + i * barW}
			{@const y = padding.top + (innerH - h)}
			<rect {x} {y} width={Math.max(1, barW - 1)} height={h} fill={color} opacity={c > 0 ? 0.9 : 0.2}>
				<title>{hist.edges[i]} runs: {c} ({((c / total) * 100).toFixed(1)}%)</title>
			</rect>
		{/each}
		{#each tickIdxs as i}
			<text
				x={padding.left + i * barW}
				y={height - 6}
				font-size="10"
				fill="#677686"
				text-anchor={i === 0 ? 'start' : i === hist.edges.length - 1 ? 'end' : 'middle'}
			>{hist.edges[i]}</text>
		{/each}
	</svg>
</figure>

<style>
	figure {
		margin: 0;
	}
	figcaption {
		font-size: 0.8rem;
		color: #9aa7b6;
		margin-bottom: 0.3rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}
	svg {
		width: 100%;
		height: auto;
		background: #0d1426;
		border: 1px solid #1a2a45;
		border-radius: 4px;
	}
</style>

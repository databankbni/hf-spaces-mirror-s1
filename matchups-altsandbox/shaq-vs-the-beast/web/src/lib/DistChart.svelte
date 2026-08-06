<script lang="ts">
	import type { Histogram } from './api';

	interface Props {
		hist: Histogram;
		title?: string;
		color?: string;
		mean?: number | null;
	}

	let { hist, title, color = 'var(--accent-pred)', mean = null }: Props = $props();

	const width = 480;
	const height = 180;
	const pad = { top: 26, right: 10, bottom: 22, left: 10 };

	const maxCount = $derived(Math.max(1, ...hist.counts));
	const total = $derived(Math.max(1, hist.counts.reduce((s, c) => s + c, 0)));
	const innerW = width - pad.left - pad.right;
	const innerH = height - pad.top - pad.bottom;
	const barW = $derived(innerW / Math.max(1, hist.counts.length));
	const modeIdx = $derived(hist.counts.indexOf(Math.max(...hist.counts)));
	const meanX = $derived(
		mean == null ? null : pad.left + (mean - hist.edges[0] + 0.5) * barW
	);
	const tickIdxs = $derived([0, Math.floor((hist.edges.length - 1) / 2), hist.edges.length - 2]);
</script>

<figure>
	{#if title}<figcaption>{title}</figcaption>{/if}
	<svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title ?? 'distribution'}>
		<line
			x1={pad.left} y1={height - pad.bottom}
			x2={width - pad.right} y2={height - pad.bottom}
			stroke="var(--border-input)" stroke-width="1"
		/>
		{#each hist.counts as c, i}
			{@const h = (c / maxCount) * innerH}
			{@const x = pad.left + i * barW}
			{@const y = pad.top + (innerH - h)}
			<rect {x} {y} width={Math.max(1, barW - 1.5)} height={h} fill={color} opacity={c > 0 ? (i === modeIdx ? 1 : 0.55) : 0.12}>
				<title>{hist.edges[i]} runs · {c} games ({((c / total) * 100).toFixed(1)}%)</title>
			</rect>
		{/each}
		{#if modeIdx >= 0 && hist.counts[modeIdx] > 0}
			{@const mx = pad.left + modeIdx * barW + barW / 2}
			{@const my = pad.top + (innerH - (hist.counts[modeIdx] / maxCount) * innerH)}
			<text x={mx} y={my - 12} font-size="10" font-weight="700" fill="var(--text)" text-anchor="middle">{hist.edges[modeIdx]}</text>
			<text x={mx} y={my - 3} font-size="8" fill="var(--text-dim)" text-anchor="middle">most likely</text>
		{/if}
		{#if meanX != null && meanX > pad.left && meanX < width - pad.right}
			<line x1={meanX} y1={pad.top - 4} x2={meanX} y2={height - pad.bottom} stroke="var(--text)" stroke-width="1" stroke-dasharray="3 3" opacity="0.6" />
			<!-- anchor the label away from the mode annotation to avoid overlap -->
			<text x={meanX + 5} y={height - pad.bottom - 6} font-size="9" font-weight="700" fill="var(--text)" text-anchor="start">μ {mean?.toFixed(1)}</text>
		{/if}
		{#each tickIdxs as i}
			{#if hist.edges[i] != null}
				<text
					x={pad.left + i * barW + barW / 2}
					y={height - 7}
					font-size="9"
					fill="var(--text-dim)"
					text-anchor="middle">{hist.edges[i]}</text>
			{/if}
		{/each}
	</svg>
</figure>

<style>
	figure {
		margin: 0;
	}
	figcaption {
		color: var(--text-2);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		margin-bottom: 0.3rem;
		font-size: 0.8rem;
		font-weight: 700;
	}
	svg {
		background: var(--bg-surface);
		border: 1px solid var(--border);
		border-radius: 6px;
		width: 100%;
		height: auto;
		padding: 0.25rem;
	}
</style>

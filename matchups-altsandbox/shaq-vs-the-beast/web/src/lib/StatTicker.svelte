<script lang="ts">
	// A compact vertical ticker for an editable projected stat.
	//
	// The current value sits bold in the middle with the next step up and down
	// faded above and below, so the cell reads as a wheel you can nudge rather
	// than a bare text box. Tapping a faded neighbour steps to it; the middle
	// stays a real input so an exact figure can still be typed.
	interface Props {
		value: string;
		/** How much one tap moves the value. Small-magnitude stats use a finer step. */
		step?: number;
		edited?: boolean;
		disabled?: boolean;
		label?: string;
		onset: (raw: string) => void;
		oncommit: () => void;
	}
	let {
		value,
		step = 0.1,
		edited = false,
		disabled = false,
		label = 'value',
		onset,
		oncommit
	}: Props = $props();

	const current = $derived.by(() => {
		const n = parseFloat(value);
		return Number.isFinite(n) ? n : 0;
	});
	// Rounded to two places so repeated taps can't drift into float dust.
	const up = $derived(Math.round((current + step) * 100) / 100);
	const down = $derived(Math.max(0, Math.round((current - step) * 100) / 100));

	function bump(to: number) {
		if (disabled) return;
		onset(to.toFixed(2));
	}
</script>

<div class="ticker" class:edited class:disabled>
	<button
		type="button"
		class="tick"
		tabindex="-1"
		{disabled}
		aria-label={`increase ${label}`}
		onclick={() => bump(up)}>{up.toFixed(2)}</button
	>
	<input
		class="tick-val"
		type="text"
		inputmode="decimal"
		aria-label={label}
		{value}
		{disabled}
		oninput={(e) => onset(e.currentTarget.value)}
		onblur={oncommit}
	/>
	<button
		type="button"
		class="tick"
		tabindex="-1"
		{disabled}
		aria-label={`decrease ${label}`}
		onclick={() => bump(down)}>{down.toFixed(2)}</button
	>
</div>

<style>
	.ticker {
		display: flex;
		flex-direction: column;
		align-items: stretch;
		width: 3.4rem;
		margin-left: auto;
		border-radius: 8px;
		background: var(--bg-surface);
		border: 1px solid transparent;
		overflow: hidden;
		transition: border-color 0.15s;
	}
	.ticker:hover:not(.disabled) {
		border-color: var(--border-input);
	}
	.ticker.edited {
		border-color: var(--accent-pred);
	}
	.ticker.disabled {
		opacity: 0.55;
	}
	/* Faded neighbours — the wheel positions you'd scroll to next. */
	.tick {
		border: none;
		background: none;
		color: var(--text-label);
		font-size: 0.58rem;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		line-height: 1;
		padding: 0.18rem 0.3rem;
		cursor: pointer;
		text-align: center;
		transition: color 0.12s;
	}
	.tick:hover:not(:disabled) {
		color: var(--text-2);
	}
	.tick:disabled {
		cursor: default;
	}
	/* The selected value: the one in focus on the wheel. */
	.tick-val {
		width: 100%;
		border: none;
		border-top: 1px solid var(--border);
		border-bottom: 1px solid var(--border);
		background: none;
		color: var(--text);
		font-size: 0.86rem;
		font-weight: 800;
		font-variant-numeric: tabular-nums;
		text-align: center;
		padding: 0.2rem 0.15rem;
		-moz-appearance: textfield;
		appearance: textfield;
	}
	.tick-val:focus {
		outline: none;
		color: var(--accent-pred);
	}
	.ticker.edited .tick-val {
		color: var(--accent-pred);
	}
	.tick-val::-webkit-outer-spin-button,
	.tick-val::-webkit-inner-spin-button {
		-webkit-appearance: none;
		margin: 0;
	}
</style>

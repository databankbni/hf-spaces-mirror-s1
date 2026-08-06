<script lang="ts">
	// Focused editor for one projected stat, opened by tapping a cell.
	//
	// Adjusting a number inside a dense table is fiddly on a phone, so the cell
	// itself stays a compact read-out and the actual editing happens here: a
	// large centre value with the next step up and down faded above and below,
	// full-width stepper targets, and a field for typing an exact figure.
	interface Props {
		who: string;
		label: string;
		value: string;
		/** The unedited projection, shown for reference and used by Reset. */
		base: number | null;
		step?: number;
		onset: (raw: string) => void;
		onreset: () => void;
		onclose: () => void;
	}
	let { who, label, value, base, step = 0.1, onset, onreset, onclose }: Props = $props();

	const current = $derived.by(() => {
		const n = parseFloat(value);
		return Number.isFinite(n) ? n : 0;
	});
	// Rounded to two places so repeated taps can't drift into float dust.
	const up = $derived(Math.round((current + step) * 100) / 100);
	const down = $derived(Math.max(0, Math.round((current - step) * 100) / 100));
	const changed = $derived(base !== null && Math.abs(current - base) > 0.005);

	function bump(to: number) {
		onset(to.toFixed(2));
	}
	function onKey(e: KeyboardEvent) {
		if (e.key === 'Escape') onclose();
		else if (e.key === 'ArrowUp') { e.preventDefault(); bump(up); }
		else if (e.key === 'ArrowDown') { e.preventDefault(); bump(down); }
		else if (e.key === 'Enter') onclose();
	}
</script>

<svelte:window onkeydown={onKey} />

<!-- Backdrop: tapping outside closes, same as the stepper's Done. -->
<div
	class="se-backdrop"
	role="button"
	tabindex="-1"
	aria-label="close editor"
	onclick={onclose}
	onkeydown={() => {}}
></div>

<div class="se-card" role="dialog" aria-modal="true" aria-label={`${who} ${label}`}>
	<div class="se-head">
		<div class="se-who">{who}</div>
		<div class="se-stat">{label}</div>
	</div>

	<div class="se-wheel">
		<button type="button" class="se-neighbour" onclick={() => bump(up)}>
			{up.toFixed(2)}
		</button>
		<div class="se-current" class:changed>{current.toFixed(2)}</div>
		<button type="button" class="se-neighbour" onclick={() => bump(down)}>
			{down.toFixed(2)}
		</button>
	</div>

	<div class="se-steppers">
		<button type="button" class="se-step" onclick={() => bump(down)} aria-label="decrease">−</button>
		<input
			class="se-input"
			type="text"
			inputmode="decimal"
			aria-label={`${label} value`}
			{value}
			oninput={(e) => onset(e.currentTarget.value)}
		/>
		<button type="button" class="se-step" onclick={() => bump(up)} aria-label="increase">+</button>
	</div>

	{#if base !== null}
		<div class="se-base">
			Projected <strong>{base.toFixed(2)}</strong>
			{#if changed}· you set {current.toFixed(2)}{/if}
		</div>
	{/if}

	<div class="se-actions">
		<button type="button" class="se-reset" onclick={onreset} disabled={!changed}>
			Reset to projection
		</button>
		<button type="button" class="se-done" onclick={onclose}>Done</button>
	</div>
</div>

<style>
	.se-backdrop {
		position: fixed;
		inset: 0;
		background: rgba(2, 6, 16, 0.72);
		z-index: 90;
		border: none;
		padding: 0;
	}
	.se-card {
		position: fixed;
		z-index: 91;
		left: 50%;
		top: 50%;
		transform: translate(-50%, -50%);
		width: min(20rem, calc(100vw - 2rem));
		background: var(--bg-surface, #0d1424);
		border: 1px solid var(--border);
		border-radius: 14px;
		padding: 1rem;
		box-shadow: 0 18px 48px rgba(0, 0, 0, 0.55);
	}
	.se-head {
		text-align: center;
		margin-bottom: 0.6rem;
	}
	.se-who {
		color: var(--text);
		font-size: 0.95rem;
		font-weight: 800;
	}
	.se-stat {
		color: var(--text-label);
		font-size: 0.66rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		margin-top: 0.1rem;
	}
	/* The wheel: faded neighbours above and below the value in focus. */
	.se-wheel {
		display: flex;
		flex-direction: column;
		align-items: stretch;
		background: #070d1a;
		border-radius: 10px;
		padding: 0.2rem 0;
		margin-bottom: 0.7rem;
	}
	.se-neighbour {
		border: none;
		background: none;
		color: var(--text-label);
		opacity: 0.55;
		font-size: 0.9rem;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		padding: 0.4rem;
		cursor: pointer;
	}
	.se-neighbour:hover {
		opacity: 0.9;
	}
	.se-current {
		text-align: center;
		color: var(--text);
		font-size: 2.1rem;
		font-weight: 900;
		font-variant-numeric: tabular-nums;
		line-height: 1.1;
		padding: 0.1rem 0;
		border-top: 1px solid var(--border);
		border-bottom: 1px solid var(--border);
	}
	.se-current.changed {
		color: var(--accent-pred);
	}
	.se-steppers {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		margin-bottom: 0.6rem;
	}
	.se-step {
		flex: 0 0 2.6rem;
		height: 2.6rem;
		border-radius: 9px;
		border: 1px solid var(--border);
		background: #0a1020;
		color: var(--text);
		font-size: 1.35rem;
		font-weight: 800;
		line-height: 1;
		cursor: pointer;
	}
	.se-step:hover {
		border-color: var(--accent-pred);
		color: var(--accent-pred);
	}
	.se-input {
		flex: 1;
		height: 2.6rem;
		border-radius: 9px;
		border: 1px solid var(--border);
		background: #0a1020;
		color: var(--text);
		font-size: 1rem;
		font-weight: 800;
		font-variant-numeric: tabular-nums;
		text-align: center;
	}
	.se-input:focus {
		outline: none;
		border-color: var(--accent-pred);
	}
	.se-base {
		color: var(--text-label);
		font-size: 0.72rem;
		font-weight: 600;
		text-align: center;
		margin-bottom: 0.7rem;
	}
	.se-base strong {
		color: var(--text-2);
	}
	.se-actions {
		display: flex;
		gap: 0.5rem;
	}
	.se-reset {
		flex: 1;
		padding: 0.55rem;
		border-radius: 9px;
		border: 1px solid var(--border);
		background: none;
		color: var(--text-2);
		font-size: 0.78rem;
		font-weight: 700;
		cursor: pointer;
	}
	.se-reset:disabled {
		opacity: 0.4;
		cursor: default;
	}
	.se-done {
		flex: 1;
		padding: 0.55rem;
		border-radius: 9px;
		border: none;
		background: var(--accent-pred);
		color: #04121c;
		font-size: 0.82rem;
		font-weight: 800;
		cursor: pointer;
	}
</style>

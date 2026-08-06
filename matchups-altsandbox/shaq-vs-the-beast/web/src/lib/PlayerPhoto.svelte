<script lang="ts">
	// MLB's official headshot CDN, keyed by the MLBAM person id already used as
	// player_id throughout this app. Unlike team logos, player photos can't be
	// pre-bundled (too many players, rosters change), so this hotlinks and
	// falls back to an initials circle if the id is missing or the image 404s.
	const HEADSHOT_URL = (id: number) =>
		`https://img.mlbstatic.com/mlb-photos/image/upload/w_213,q_auto:best/v1/people/${id}/headshot/67/current`;

	interface Props {
		playerId?: number | null;
		name?: string;
		size?: number;
	}
	let { playerId = null, name = '', size = 40 }: Props = $props();

	let failed = $state(false);
	$effect(() => {
		playerId; // reset the fallback flag when this instance is reused for a different player
		failed = false;
	});

	function initials(n: string): string {
		return n
			.split(/\s+/)
			.filter(Boolean)
			.map((w) => w[0])
			.slice(0, 2)
			.join('')
			.toUpperCase();
	}

	const src = $derived(playerId && !failed ? HEADSHOT_URL(playerId) : '');
</script>

{#if src}
	<img
		class="photo"
		{src}
		alt={name}
		width={size}
		height={size}
		style={`width:${size}px;height:${size}px`}
		loading="lazy"
		onerror={() => (failed = true)}
	/>
{:else}
	<div class="photo-fallback" style={`width:${size}px;height:${size}px;font-size:${size * 0.36}px`}>
		{initials(name)}
	</div>
{/if}

<style>
	.photo {
		border-radius: 50%;
		object-fit: cover;
		vertical-align: middle;
		background: var(--bg-badge);
		border: 1px solid var(--border-input);
		flex-shrink: 0;
	}
	.photo-fallback {
		border-radius: 50%;
		background: var(--bg-badge);
		border: 1px solid var(--border-input);
		display: flex;
		align-items: center;
		justify-content: center;
		font-weight: 800;
		color: var(--text-2);
		flex-shrink: 0;
	}
</style>

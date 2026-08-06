<script lang="ts">
	// MLBAM team ids → official SVG logos (mlbstatic.com).
	const TEAM_ID: Record<string, number> = {
		ATH: 133, PIT: 134, SD: 135, SEA: 136, SF: 137, STL: 138, TB: 139, TEX: 140,
		TOR: 141, MIN: 142, PHI: 143, ATL: 144, CWS: 145, MIA: 146, NYY: 147, MIL: 158,
		LAA: 108, AZ: 109, BAL: 110, BOS: 111, CHC: 112, CIN: 113, CLE: 114, COL: 115,
		DET: 116, HOU: 117, KC: 118, LAD: 119, WSH: 120, NYM: 121,
		// legacy abbreviations that older schedules may use
		OAK: 133, ARI: 109, CHW: 145, KCR: 118, SDP: 135, SFG: 137, TBR: 139, WSN: 120
	};

	interface Props {
		abbr: string;
		size?: number;
	}
	let { abbr, size = 28 }: Props = $props();
	const id = $derived(TEAM_ID[abbr]);
	// Served same-origin (web/static/logos) so a strict CSP can't block them.
	const src = $derived(id ? `/logos/${id}.svg` : '');
</script>

{#if src}
	<img class="logo" {src} alt={abbr} title={abbr} width={size} height={size} />
{:else}
	<span class="abbr" style={`font-size:${size * 0.5}px`}>{abbr}</span>
{/if}

<style>
	.logo {
		object-fit: contain;
		vertical-align: middle;
	}
	.abbr {
		font-weight: 700;
	}
</style>

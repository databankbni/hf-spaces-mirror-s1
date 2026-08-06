<script lang="ts">
	// Mirrors MrSim: the root route simply forwards to the matchups slate.
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	onMount(() => {
		goto('/matchups', { replaceState: true });
	});
</script>

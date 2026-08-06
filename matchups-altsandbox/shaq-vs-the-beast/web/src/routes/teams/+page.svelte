<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import TeamLogo from '$lib/TeamLogo.svelte';
	import { teamName } from '$lib/teams';

	let teams = $state<string[]>([]);
	let loading = $state(true);
	let error = $state('');

	onMount(async () => {
		try {
			teams = await api.teams();
		} catch (e) {
			error = String(e);
		} finally {
			loading = false;
		}
	});
</script>

<svelte:head>
	<title>Teams — The Beast</title>
</svelte:head>

<h1>Teams</h1>

{#if error}<div class="error">{error}</div>{/if}
{#if loading}
	<div class="loading"><span class="spinner"></span> Loading teams…</div>
{:else}
	<div class="grid">
		{#each teams as t (t)}
			<a class="team-card" href={`/teams/${t}`}>
				<TeamLogo abbr={t} size={56} />
				<span class="abbr">{t}</span>
				<span class="name">{teamName(t)}</span>
			</a>
		{/each}
	</div>
{/if}

<style>
	h1 {
		font-size: 1.4rem;
		font-weight: 900;
		font-style: italic;
		text-transform: uppercase;
		letter-spacing: 0.03em;
		margin: 0 0 1.5rem;
	}
	.error {
		color: var(--danger);
		margin: 1rem 0;
	}
	.loading {
		color: var(--text-muted);
		display: flex;
		align-items: center;
		gap: 0.7rem;
		padding: 2rem 0;
	}
	.spinner {
		border: 2px solid var(--border-input);
		border-top-color: var(--accent-pred);
		border-radius: 50%;
		width: 1.1rem;
		height: 1.1rem;
		animation: spin 0.7s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
		gap: 0.85rem;
	}
	.team-card {
		border: 1px solid var(--border);
		background: #0c1428;
		border-radius: 8px;
		padding: 1.2rem 0.8rem;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.5rem;
		text-decoration: none;
		color: var(--text);
		box-shadow: 0 2px 10px #00000059;
		transition: border-color 0.15s, transform 0.15s;
	}
	.team-card:hover {
		border-color: var(--accent-pred);
		transform: translateY(-2px);
	}
	.abbr {
		font-size: 1.1rem;
		font-weight: 800;
		font-style: italic;
		letter-spacing: 0.03em;
	}
	.name {
		color: var(--text-label);
		font-size: 0.72rem;
		font-weight: 600;
		text-align: center;
	}
</style>

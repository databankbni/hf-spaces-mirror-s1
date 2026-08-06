<script lang="ts">
	import { page } from '$app/stores';
	let { children } = $props();

	let scrolled = $state(false);
	let menuOpen = $state(false);

	const NAV = [
		{ href: '/matchups', label: 'Matchups' },
		{ href: '/players', label: 'Players' },
		{ href: '/teams', label: 'Teams' },
		{ href: '/simulate', label: 'Simulate' },
		{ href: '/accuracy', label: 'Accuracy' },
		{ href: '/docs', label: 'Docs' }
	];

	function isActive(href: string, path: string): boolean {
		return path === href || path.startsWith(href + '/');
	}

	function onScroll() {
		scrolled = window.scrollY > 8;
	}
</script>

<svelte:window on:scroll={onScroll} />

<svelte:head>
	<title>The Beast — MLB Monte Carlo</title>
</svelte:head>

<header class:scrolled>
	<div class="header-inner">
		<a href="/matchups" class="logo-link" onclick={() => (menuOpen = false)}>
			<span class="logo-mark">🐕⚾</span>
			<span class="logo-text">The <em>Beast</em></span>
		</a>
		<button
			class="hamburger"
			class:open={menuOpen}
			aria-label="menu"
			onclick={() => (menuOpen = !menuOpen)}
		>
			<span></span><span></span><span></span>
		</button>
		<nav class="main-nav" class:open={menuOpen}>
			{#each NAV as item}
				<a
					href={item.href}
					class:active={isActive(item.href, $page.url.pathname)}
					onclick={() => (menuOpen = false)}>{item.label}</a
				>
			{/each}
		</nav>
		<div class="icon-actions">
			<a
				class="icon-btn"
				href="https://github.com/null-signal-19/thebeast"
				target="_blank"
				rel="noreferrer"
				title="Source"
				aria-label="Source on GitHub"
			>
				<svg width="18" height="18" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
					<path
						d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"
					/>
				</svg>
			</a>
			<a class="icon-btn" href="/api/_swagger" target="_blank" rel="noreferrer" title="API docs" aria-label="API docs">
				<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
					<polyline points="16 18 22 12 16 6"></polyline>
					<polyline points="8 6 2 12 8 18"></polyline>
				</svg>
			</a>
		</div>
	</div>
</header>

<div class="page-bg" aria-hidden="true"></div>

<main>
	{@render children()}
</main>

<style>
	:global(:root) {
		--accent-pred: #6f0;
		--accent-actual: #00fff2;
		--accent-vegas: #ffc400;
		--accent-neg: #ff2f00;
		--danger: #ff7a7a;
		--danger-strong: #ff5a5a;
		--caveat: #d6b34a;
		--bg-page: #0a0f1e;
		--bg-surface: #0d1426;
		--bg-card: #0f1830;
		--bg-hover: #121d35;
		--bg-badge: #16233d;
		--border: #1a2a45;
		--border-nav: #1a2540;
		--border-input: #1e3050;
		--border-faint: #111c33;
		--text: #e8eef5;
		--text-2: #c5d2e0;
		--text-muted: #9aa7b6;
		--text-label: #8a9db5;
		--text-dim: #8b97a6;
		--text-footnote: #6e7a8b;
		--slate: #7a828c;
		--slate-deep: #5a616d;
		--slate-light: #a2aab4;
		--link: #9cc2ff;
		--link-accent: #4a9cff;
	}
	:global(body) {
		background: var(--bg-page);
		color: var(--text);
		margin: 0;
		font-family: ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif;
	}
	:global(*) {
		box-sizing: border-box;
	}

	/* Faded drunk-baseball wallpaper behind everything (mrsim mx-bg pattern). */
	.page-bg {
		position: fixed;
		inset: 0;
		z-index: -1;
		background: url('/drunk-baseball.svg') repeat;
		background-size: 130px 130px;
		opacity: 0.07;
		-webkit-mask-image: linear-gradient(#000 0%, #0000 65%);
		mask-image: linear-gradient(#000 0%, #0000 65%);
	}

	header {
		position: sticky;
		top: 0;
		z-index: 300;
		background: transparent;
		border-bottom: 1px solid transparent;
		transition: background 0.2s, border-color 0.2s;
	}
	header.scrolled {
		background: var(--bg-surface);
		border-bottom-color: var(--border-nav);
	}
	.header-inner {
		display: flex;
		align-items: center;
		gap: 1.5rem;
		max-width: 1100px;
		margin: 0 auto;
		padding: 1rem 2rem;
	}
	.logo-link {
		display: flex;
		align-items: center;
		gap: 0.45rem;
		flex-shrink: 0;
		margin-right: 0.5rem;
		text-decoration: none;
		color: var(--text);
	}
	.logo-mark {
		font-size: 1.35rem;
		line-height: 1;
	}
	.logo-text {
		font-size: 1.15rem;
		font-weight: 900;
		font-style: italic;
		letter-spacing: 0.02em;
		text-transform: uppercase;
	}
	.logo-text em {
		font-style: italic;
		color: var(--accent-pred);
	}
	.main-nav {
		display: flex;
		gap: 1.25rem;
		flex: 1;
	}
	.main-nav a {
		color: var(--text-muted);
		letter-spacing: 0.06em;
		text-transform: uppercase;
		white-space: nowrap;
		border-bottom: 2px solid transparent;
		padding: 0.3rem 0;
		font-size: 0.78rem;
		font-weight: 600;
		text-decoration: none;
	}
	.main-nav a:hover {
		color: var(--text);
	}
	.main-nav a.active {
		color: var(--text);
		border-bottom-color: var(--accent-pred);
	}
	.icon-actions {
		display: flex;
		align-items: center;
		gap: 0.1rem;
		margin-left: auto;
		flex-shrink: 0;
	}
	.icon-btn {
		width: 34px;
		height: 34px;
		color: var(--text);
		border-radius: 6px;
		display: flex;
		justify-content: center;
		align-items: center;
		text-decoration: none;
		transition: color 0.15s, background 0.15s;
	}
	.icon-btn:hover {
		color: #fff;
		background: var(--bg-hover);
	}
	.hamburger {
		display: none;
		cursor: pointer;
		background: none;
		border: 0;
		flex-direction: column;
		justify-content: center;
		gap: 5px;
		width: 34px;
		height: 34px;
		padding: 0;
	}
	.hamburger span {
		background: var(--text);
		border-radius: 2px;
		width: 22px;
		height: 2.75px;
		margin: 0 auto;
		transition: transform 0.2s, opacity 0.2s;
		display: block;
	}
	.hamburger.open span:first-child {
		transform: translateY(7px) rotate(45deg);
	}
	.hamburger.open span:nth-child(2) {
		opacity: 0;
	}
	.hamburger.open span:nth-child(3) {
		transform: translateY(-7px) rotate(-45deg);
	}
	main {
		max-width: 1100px;
		margin: 0 auto;
		padding: 2rem;
		padding-bottom: 5rem;
	}

	@media (max-width: 700px) {
		.header-inner {
			flex-wrap: wrap;
			gap: 1rem;
			padding: 0.85rem 1.25rem;
			position: relative;
		}
		.hamburger {
			display: flex;
		}
		.main-nav {
			display: none;
			flex-direction: column;
			flex: none;
			gap: 0;
			width: 100%;
			position: absolute;
			top: 100%;
			left: 0;
			right: 0;
			z-index: 200;
			backdrop-filter: blur(10px);
			-webkit-backdrop-filter: blur(10px);
			background: #0d1426e6;
			border-bottom: 1px solid var(--border-nav);
			padding: 0.5rem 1.25rem 0.75rem;
			box-shadow: 0 12px 28px #0000008c;
		}
		.main-nav.open {
			display: flex;
		}
		.main-nav a {
			border-bottom: 1px solid var(--border-nav);
			padding: 0.75rem 0.25rem;
		}
		.main-nav a.active {
			border-bottom-color: var(--border-nav);
			color: var(--accent-pred);
		}
		main {
			padding: 1.25rem;
			padding-bottom: 4rem;
		}
	}
</style>

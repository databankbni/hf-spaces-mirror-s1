<script lang="ts">
	import { tick } from 'svelte';
	import { api, type ChatEvent, type ChatMessage, type SlateStatus } from '$lib/api';

	// The assistant reads the slate's simulations rather than running its own,
	// so until those exist it has nothing to read — and asking anyway would send
	// it off to simulate games one at a time, which is the thing it is here to
	// avoid. The input is therefore closed, not merely annotated, until the
	// slate is done. The server refuses on the same signal; this is the half
	// that stops a question being typed in the first place.
	let { slate = null }: { slate?: SlateStatus | null } = $props();
	const waitingOnSlate = $derived(slate !== null && slate.running === true);
	const slateProgress = $derived(
		slate ? `${slate.done} of ${slate.total}` : ''
	);

	// Four states, because "I can't see it" has to be answerable. Hiding the
	// panel whenever it isn't ready made an unset API key look exactly like a
	// failed deploy or a broken build, which left the one person who could fix
	// it with nothing to go on. Now it says which.
	type Status = 'checking' | 'ready' | 'suspect' | 'unconfigured' | 'unreachable';
	let status = $state<Status>('checking');
	let model = $state<string | null>(null);
	let open = $state(false);

	let history = $state<ChatMessage[]>([]);
	let draft = $state('');
	let streaming = $state(false);
	let partial = $state('');
	let activeTool = $state<string | null>(null);
	let error = $state<string | null>(null);
	let log: HTMLDivElement | undefined = $state();
	let controller: AbortController | null = null;

	const TOOL_LABELS: Record<string, string> = {
		list_games: 'checking the slate',
		simulate_game: 'running the simulation',
		get_trends: 'reading the trends',
		get_accuracy: 'checking the accuracy record',
		get_league_history: 'looking up league history',
		find_player: 'looking up the player'
	};

	const PROMPTS = [
		"What's on tonight and which game is closest?",
		'How accurate has the model been lately?',
		'What trends are you seeing in the league?'
	];

	$effect(() => {
		api
			.chatStatus()
			.then((s) => {
				status = !s.available ? 'unconfigured' : s.key_suspect ? 'suspect' : 'ready';
				model = s.model;
			})
			.catch(() => {
				// The endpoint itself didn't answer — an older build still running,
				// or the app is down. Distinct from "no key", and a different fix.
				status = 'unreachable';
			});
	});

	async function scrollToEnd() {
		await tick();
		if (log) log.scrollTop = log.scrollHeight;
	}

	async function send(text: string) {
		const body = text.trim();
		if (!body || streaming) return;
		error = null;
		draft = '';
		history = [...history, { role: 'user', content: body }];
		streaming = true;
		partial = '';
		activeTool = null;
		await scrollToEnd();

		controller = new AbortController();
		try {
			await api.chat(
				history,
				(e: ChatEvent) => {
					if (e.type === 'text') {
						activeTool = null;
						partial += e.text;
						scrollToEnd();
					} else if (e.type === 'tool') {
						activeTool = TOOL_LABELS[e.name] ?? e.name;
					} else if (e.type === 'error') {
						error = e.message;
					}
				},
				controller.signal
			);
		} catch (err) {
			// An abort is the user's own doing — keep whatever arrived and say
			// nothing, rather than reporting their own click back as a failure.
			if ((err as Error).name !== 'AbortError') {
				error = (err as Error).message || 'The assistant is unavailable.';
			}
		} finally {
			if (partial) history = [...history, { role: 'assistant', content: partial }];
			partial = '';
			activeTool = null;
			streaming = false;
			controller = null;
			scrollToEnd();
		}
	}

	function stop() {
		controller?.abort();
	}

	function onKey(e: KeyboardEvent) {
		// Enter sends; shift+enter is a newline, which is what anyone who has
		// used a chat box expects.
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			send(draft);
		}
	}

	function reset() {
		stop();
		history = [];
		partial = '';
		error = null;
	}
</script>

{#if status !== 'checking'}
	<section class="ch" class:open>
		<button class="ch-head" onclick={() => (open = !open)} aria-expanded={open}>
			<h2>Ask about the slate</h2>
			<span class="ch-sub">
				{#if status === 'unconfigured'}
					needs an API key before it can answer
				{:else if status === 'suspect'}
					the configured key doesn't look right
				{:else if status === 'unreachable'}
					not responding
				{:else if waitingOnSlate}
					opens when the slate finishes simulating — {slateProgress}
				{:else}
					{open ? 'questions about tonight, the projections, or baseball' : 'chat with Claude'}
				{/if}
			</span>
			<span class="ch-toggle" aria-hidden="true">{open ? '−' : '+'}</span>
		</button>

		{#if open && status === 'unconfigured'}
			<div class="ch-setup">
				<p>
					The assistant is built and deployed, but it has no API key to call, so it
					can't answer yet.
				</p>
				<p>
					Add <code>ANTHROPIC_API_KEY</code> under <strong>Settings → Variables and
					secrets → New secret</strong> on the Space. It restarts on its own, and this
					panel becomes a chat box a minute or so later — no redeploy needed.
				</p>
			</div>
		{:else if open && status === 'suspect'}
			<div class="ch-setup">
				<p>
					A key is set, but it doesn't start with <code>sk-ant-</code>, so Anthropic
					will reject it. That usually means a partial paste, or a value copied from
					somewhere other than the API keys page.
				</p>
				<p>
					Replace the <code>ANTHROPIC_API_KEY</code> secret with a full key from
					console.anthropic.com → API keys.
				</p>
			</div>
		{:else if open && status === 'unreachable'}
			<div class="ch-setup">
				<p>
					The chat endpoint didn't answer. Usually that means the Space is still
					rebuilding, or it's serving a build from before the assistant was added —
					give it a minute and reload.
				</p>
			</div>
		{:else if open && waitingOnSlate}
			<div class="ch-setup">
				<p>
					Simulating tonight's slate — <strong>{slateProgress}</strong> games.
				</p>
				<div class="ch-bar" role="progressbar" aria-valuenow={slate?.done ?? 0}
					aria-valuemin="0" aria-valuemax={slate?.total ?? 0}>
					<div
						class="ch-bar-fill"
						style="width: {slate?.total ? (100 * (slate?.done ?? 0)) / slate.total : 0}%"
					></div>
				</div>
				<p>
					I answer from those simulations rather than running my own, so there is
					nothing to read yet. This opens the moment they finish — the same numbers
					the cards and the ranked plays are built on.
				</p>
			</div>
		{:else if open}
			<div class="ch-log" bind:this={log}>
				{#if history.length === 0 && !streaming}
					<p class="ch-hint">
						I read tonight's simulations — the same ones behind the cards and the ranked
						plays — so answers come back straight away rather than being re-run. Ask me
						to change something about a matchup and I'll simulate that fresh. Ask me
						anything about baseball too.
					</p>
					<div class="ch-prompts">
						{#each PROMPTS as p}
							<button class="ch-prompt" onclick={() => send(p)}>{p}</button>
						{/each}
					</div>
				{/if}

				{#each history as m, i (i)}
					<div class="ch-msg {m.role}">
						<span class="ch-who">{m.role === 'user' ? 'You' : 'Claude'}</span>
						<div class="ch-text">{m.content}</div>
					</div>
				{/each}

				{#if streaming}
					<div class="ch-msg assistant">
						<span class="ch-who">Claude</span>
						<div class="ch-text">
							{partial}{#if activeTool}<span class="ch-tool">{activeTool}…</span>{:else if !partial}<span
									class="ch-tool">thinking…</span
								>{/if}
						</div>
					</div>
				{/if}

				{#if error}
					<div class="ch-error">{error}</div>
				{/if}
			</div>

			<div class="ch-input">
				<textarea
					bind:value={draft}
					onkeydown={onKey}
					rows="2"
					placeholder="Ask about a game, a player, or how the model has been doing…"
					disabled={streaming}
				></textarea>
				{#if streaming}
					<button class="ch-send" onclick={stop}>Stop</button>
				{:else}
					<button class="ch-send" onclick={() => send(draft)} disabled={!draft.trim()}>
						Send
					</button>
				{/if}
			</div>

			<div class="ch-foot">
				{#if model}<span>{model}</span>{/if}
				<span>· it reads the live slate and the graded record, but it can still be wrong</span>
				{#if history.length}
					<button class="ch-clear" onclick={reset}>Clear</button>
				{/if}
			</div>
		{/if}
	</section>
{/if}

<style>
	.ch {
		border: 1px solid var(--border);
		border-radius: 10px;
		background: var(--panel, transparent);
		margin-bottom: 1rem;
		overflow: hidden;
	}
	.ch-head {
		display: flex;
		align-items: baseline;
		gap: 0.5rem;
		width: 100%;
		padding: 0.6rem 0.75rem;
		background: none;
		border: 0;
		color: inherit;
		font: inherit;
		text-align: left;
		cursor: pointer;
	}
	.ch-head h2 {
		margin: 0;
		font-size: 0.95rem;
	}
	.ch-sub {
		font-size: 0.68rem;
		color: var(--muted);
		flex: 1;
	}
	.ch-toggle {
		font-size: 1rem;
		color: var(--muted);
	}
	.ch-log {
		max-height: 22rem;
		overflow-y: auto;
		padding: 0 0.75rem 0.5rem;
		border-top: 1px solid var(--border);
	}
	.ch-setup {
		padding: 0.65rem 0.75rem;
		border-top: 1px solid var(--border);
		font-size: 0.74rem;
		line-height: 1.5;
		color: var(--muted);
	}
	.ch-setup p {
		margin: 0 0 0.5rem;
	}
	.ch-setup p:last-child {
		margin-bottom: 0;
	}
	.ch-bar {
		height: 4px;
		border-radius: 999px;
		background: var(--border);
		overflow: hidden;
		margin: 0 0 0.5rem;
	}
	.ch-bar-fill {
		height: 100%;
		background: currentColor;
		opacity: 0.65;
		transition: width 0.4s ease;
	}
	.ch-setup code {
		font-size: 0.72rem;
		padding: 0.05rem 0.25rem;
		border: 1px solid var(--border);
		border-radius: 4px;
	}
	.ch-hint {
		font-size: 0.72rem;
		color: var(--muted);
		line-height: 1.45;
		margin: 0.6rem 0 0.5rem;
	}
	.ch-prompts {
		display: flex;
		flex-wrap: wrap;
		gap: 0.3rem;
		margin-bottom: 0.5rem;
	}
	.ch-prompt {
		font: inherit;
		font-size: 0.68rem;
		padding: 0.2rem 0.5rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		background: none;
		color: var(--muted);
		cursor: pointer;
	}
	.ch-prompt:hover {
		color: inherit;
	}
	.ch-msg {
		margin: 0.55rem 0;
	}
	.ch-who {
		display: block;
		font-size: 0.6rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--muted);
		margin-bottom: 0.1rem;
	}
	.ch-text {
		font-size: 0.8rem;
		line-height: 1.5;
		/* Model replies are prose with real paragraph breaks; collapsing them
		   would run the whole answer together. */
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	.ch-msg.user .ch-text {
		color: var(--muted);
	}
	.ch-tool {
		color: var(--muted);
		font-style: italic;
	}
	.ch-error {
		font-size: 0.72rem;
		color: #f87171;
		padding: 0.4rem 0;
	}
	.ch-input {
		display: flex;
		gap: 0.4rem;
		padding: 0.5rem 0.75rem;
		border-top: 1px solid var(--border);
	}
	.ch-input textarea {
		flex: 1;
		resize: none;
		font: inherit;
		font-size: 0.78rem;
		padding: 0.35rem 0.45rem;
		border: 1px solid var(--border);
		border-radius: 6px;
		background: none;
		color: inherit;
	}
	.ch-send {
		align-self: flex-end;
		font: inherit;
		font-size: 0.72rem;
		padding: 0.35rem 0.7rem;
		border: 1px solid var(--border);
		border-radius: 6px;
		background: none;
		color: inherit;
		cursor: pointer;
	}
	.ch-send:disabled {
		opacity: 0.4;
		cursor: default;
	}
	.ch-foot {
		display: flex;
		align-items: center;
		gap: 0.3rem;
		flex-wrap: wrap;
		padding: 0 0.75rem 0.6rem;
		font-size: 0.62rem;
		color: var(--muted);
	}
	.ch-clear {
		margin-left: auto;
		font: inherit;
		font-size: 0.62rem;
		background: none;
		border: 0;
		color: var(--muted);
		text-decoration: underline;
		cursor: pointer;
	}
	@media (max-width: 640px) {
		.ch-log {
			max-height: 16rem;
		}
	}
</style>

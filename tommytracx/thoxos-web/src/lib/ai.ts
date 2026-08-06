import { getProvider, getProviderForModel, type Provider, type ProviderModel } from './providers';
import { cascadeChat, type AdapterTarget, type ChatTurn } from './thoxroute/adapters';
import { isWebGPUModelLoaded } from './thoxroute/webgpu';
import type { Attachment } from './db';

export interface ChatMessage {
    role: 'user' | 'assistant' | 'system';
    content: string;
    attachments?: Attachment[];
}

export interface StreamCallbacks {
    onChunk: (text: string) => void;
    onDone: (fullText: string) => void;
    onError: (error: Error) => void;
    /**
     * Fired when a turn was served by something other than the primary endpoint — e.g. the free
     * CPU fallback after the paid Space returned 402/503. The label is surfaced to the user
     * because a degraded answer should never look like a normal one.
     */
    onTier?: (label: string) => void;
}

/** Resolve a composite model ID (e.g. "gpt-5.2:high") into base model + optional thinking level */
function resolveModelId(modelId: string): { baseModel: string; thinkingLevel?: string; modelDef?: ProviderModel } {
    // Find the model definition to check for thinkingLevel
    const provider = getProviderForModel(modelId);
    const modelDef = provider?.models.find((m) => m.id === modelId);
    if (modelDef?.thinkingLevel) {
        // Strip the ":level" suffix to get the actual API model name
        const baseModel = modelId.split(':')[0];
        return { baseModel, thinkingLevel: modelDef.thinkingLevel, modelDef };
    }
    return { baseModel: modelId, modelDef: modelDef || undefined };
}

// ─── Helpers ───

/** Extract raw base64 data from a data URL */
function dataUrlToBase64(dataUrl: string): string {
    return dataUrl.split(',')[1] || '';
}

/** Build OpenAI/Grok-compatible content array for a message with attachments */
function buildOpenAIContent(msg: ChatMessage): string | Array<Record<string, unknown>> {
    if (!msg.attachments?.length) return msg.content;

    const parts: Array<Record<string, unknown>> = [];

    // Text files: prepend their content
    const textAttachments = msg.attachments.filter((a) => a.type === 'file');
    let textContent = msg.content;
    for (const att of textAttachments) {
        const decoded = atob(dataUrlToBase64(att.dataUrl));
        textContent = `[File: ${att.name}]\n${decoded}\n\n${textContent}`;
    }

    parts.push({ type: 'text', text: textContent });

    // Images
    for (const att of msg.attachments.filter((a) => a.type === 'image')) {
        parts.push({
            type: 'image_url',
            image_url: { url: att.dataUrl },
        });
    }

    return parts;
}

/** Build Anthropic content array for a message with attachments */
function buildAnthropicContent(msg: ChatMessage): string | Array<Record<string, unknown>> {
    if (!msg.attachments?.length) return msg.content;

    const parts: Array<Record<string, unknown>> = [];

    // Images first (Anthropic convention)
    for (const att of msg.attachments.filter((a) => a.type === 'image')) {
        parts.push({
            type: 'image',
            source: {
                type: 'base64',
                media_type: att.mimeType,
                data: dataUrlToBase64(att.dataUrl),
            },
        });
    }

    // Text files: prepend their content
    const textAttachments = msg.attachments.filter((a) => a.type === 'file');
    let textContent = msg.content;
    for (const att of textAttachments) {
        const decoded = atob(dataUrlToBase64(att.dataUrl));
        textContent = `[File: ${att.name}]\n${decoded}\n\n${textContent}`;
    }

    parts.push({ type: 'text', text: textContent });

    return parts;
}

/** Build Gemini parts array for a message with attachments */
function buildGeminiParts(msg: ChatMessage): Array<Record<string, unknown>> {
    const parts: Array<Record<string, unknown>> = [];

    // Text files: prepend their content
    const textAttachments = msg.attachments?.filter((a) => a.type === 'file') || [];
    let textContent = msg.content;
    for (const att of textAttachments) {
        const decoded = atob(dataUrlToBase64(att.dataUrl));
        textContent = `[File: ${att.name}]\n${decoded}\n\n${textContent}`;
    }

    parts.push({ text: textContent });

    // Images
    for (const att of (msg.attachments || []).filter((a) => a.type === 'image')) {
        parts.push({
            inlineData: {
                mimeType: att.mimeType,
                data: dataUrlToBase64(att.dataUrl),
            },
        });
    }

    return parts;
}

/** Build a plain-text THOX message body for a message with attachments.
 *  Text files are inlined into the content; images are unsupported on the THOX
 *  tier for now, so they are dropped with a short note. */
function buildThoxContent(msg: ChatMessage): string {
    let textContent = msg.content;

    // Text files: prepend their content (same convention as the other providers)
    const textAttachments = msg.attachments?.filter((a) => a.type === 'file') || [];
    for (const att of textAttachments) {
        const decoded = atob(dataUrlToBase64(att.dataUrl));
        textContent = `[File: ${att.name}]\n${decoded}\n\n${textContent}`;
    }

    // Images: not supported on the THOX tier yet — note their presence instead of sending.
    const imageAttachments = msg.attachments?.filter((a) => a.type === 'image') || [];
    if (imageAttachments.length) {
        const names = imageAttachments.map((a) => a.name).join(', ');
        textContent = `${textContent}\n\n[Note: ${imageAttachments.length} image attachment(s) omitted — images are not yet supported on the THOX tier: ${names}]`;
    }

    return textContent;
}

// ─── Main Entry ───

export async function streamChat(
    messages: ChatMessage[],
    providerId: string,
    modelId: string,
    apiKey: string,
    systemPrompt: string,
    callbacks: StreamCallbacks,
    signal?: AbortSignal
): Promise<void> {
    const provider = getProvider(providerId);
    if (!provider) {
        callbacks.onError(new Error(`Unknown provider: ${providerId}`));
        return;
    }

    const allMessages: ChatMessage[] = [
        { role: 'system', content: systemPrompt },
        ...messages,
    ];

    try {
        switch (providerId) {
            case 'openai':
            case 'grok':
                await streamOpenAICompatible(provider, modelId, apiKey, allMessages, callbacks, signal);
                break;
            case 'anthropic':
                await streamAnthropic(provider, modelId, apiKey, allMessages, callbacks, signal);
                break;
            case 'gemini':
                await streamGemini(modelId, apiKey, allMessages, callbacks, signal);
                break;
            case 'thox':
                await streamThoxTiers(modelId, allMessages, callbacks, signal);
                break;
            default:
                callbacks.onError(new Error(`Unsupported provider: ${providerId}`));
        }
    } catch (err) {
        if (signal?.aborted) return;
        callbacks.onError(err instanceof Error ? err : new Error(String(err)));
    }
}

// ─── OpenAI / Grok (compatible) ───

async function streamOpenAICompatible(
    provider: Provider,
    model: string,
    apiKey: string,
    messages: ChatMessage[],
    callbacks: StreamCallbacks,
    signal?: AbortSignal
) {
    const { baseModel, thinkingLevel, modelDef } = resolveModelId(model);

    const formattedMessages = messages.map((m) => ({
        role: m.role,
        content: buildOpenAIContent(m),
    }));

    const body: Record<string, unknown> = { model: baseModel, messages: formattedMessages, stream: true };
    if (thinkingLevel) {
        body.reasoning_effort = thinkingLevel;
    }
    if (modelDef?.maxOutputTokens) {
        body.max_completion_tokens = modelDef.maxOutputTokens;
    }

    const resp = await fetch(provider.endpointUrl, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${apiKey}`,
        },
        body: JSON.stringify(body),
        signal,
    });

    if (!resp.ok) {
        const errorText = await resp.text().catch(() => resp.statusText);
        throw new Error(`${provider.name} error (${resp.status}): ${errorText}`);
    }

    const reader = resp.body?.getReader();
    if (!reader) throw new Error('No response body');

    const decoder = new TextDecoder();
    let fullText = '';
    let buffer = '';

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed || !trimmed.startsWith('data: ')) continue;
            const data = trimmed.slice(6);
            if (data === '[DONE]') continue;

            try {
                const json = JSON.parse(data);
                const content = json.choices?.[0]?.delta?.content;
                if (content) {
                    fullText += content;
                    callbacks.onChunk(fullText);
                }
            } catch {
                // skip malformed JSON
            }
        }
    }

    callbacks.onDone(fullText);
}

// ─── Anthropic ───

async function streamAnthropic(
    provider: Provider,
    model: string,
    apiKey: string,
    messages: ChatMessage[],
    callbacks: StreamCallbacks,
    signal?: AbortSignal
) {
    const systemMsg = messages.find((m) => m.role === 'system');
    const nonSystemMsgs = messages.filter((m) => m.role !== 'system');

    const { modelDef } = resolveModelId(model);
    const maxTokens = modelDef?.maxOutputTokens || 8192;

    const formattedMessages = nonSystemMsgs.map((m) => ({
        role: m.role,
        content: buildAnthropicContent(m),
    }));

    const resp = await fetch(provider.endpointUrl, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'x-api-key': apiKey,
            'anthropic-version': '2023-06-01',
            'anthropic-dangerous-direct-browser-access': 'true',
        },
        body: JSON.stringify({
            model,
            max_tokens: maxTokens,
            system: systemMsg?.content || '',
            messages: formattedMessages,
            stream: true,
        }),
        signal,
    });

    if (!resp.ok) {
        const errorText = await resp.text().catch(() => resp.statusText);
        throw new Error(`Anthropic error (${resp.status}): ${errorText}`);
    }

    const reader = resp.body?.getReader();
    if (!reader) throw new Error('No response body');

    const decoder = new TextDecoder();
    let fullText = '';
    let buffer = '';

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed || !trimmed.startsWith('data: ')) continue;
            const data = trimmed.slice(6);

            try {
                const json = JSON.parse(data);
                if (json.type === 'content_block_delta' && json.delta?.text) {
                    fullText += json.delta.text;
                    callbacks.onChunk(fullText);
                }
            } catch {
                // skip
            }
        }
    }

    callbacks.onDone(fullText);
}

// ─── Gemini ───

async function streamGemini(
    model: string,
    apiKey: string,
    messages: ChatMessage[],
    callbacks: StreamCallbacks,
    signal?: AbortSignal
) {
    const systemInstruction = messages.find((m) => m.role === 'system');
    const chatMessages = messages.filter((m) => m.role !== 'system');

    const contents = chatMessages.map((m) => ({
        role: m.role === 'assistant' ? 'model' : 'user',
        parts: buildGeminiParts(m),
    }));

    const { modelDef } = resolveModelId(model);
    const maxOutputTokens = modelDef?.maxOutputTokens || 8192;

    const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:streamGenerateContent?key=${apiKey}&alt=sse`;

    const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            contents,
            systemInstruction: systemInstruction
                ? { parts: [{ text: systemInstruction.content }] }
                : undefined,
            generationConfig: { maxOutputTokens },
        }),
        signal,
    });

    if (!resp.ok) {
        const errorText = await resp.text().catch(() => resp.statusText);
        throw new Error(`Gemini error (${resp.status}): ${errorText}`);
    }

    const reader = resp.body?.getReader();
    if (!reader) throw new Error('No response body');

    const decoder = new TextDecoder();
    let fullText = '';
    let buffer = '';

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed || !trimmed.startsWith('data: ')) continue;
            const data = trimmed.slice(6);

            try {
                const json = JSON.parse(data);
                const text = json.candidates?.[0]?.content?.parts?.[0]?.text;
                if (text) {
                    fullText += text;
                    callbacks.onChunk(fullText);
                }
            } catch {
                // skip
            }
        }
    }

    callbacks.onDone(fullText);
}

// ─── THOX (native NDJSON stream) ───

/** One line of the THOX native stream. The response is newline-delimited JSON:
 *  repeated {"type":"delta","text":"..."}, then {"type":"done","stats":{...}},
 *  and on failure {"type":"error","message":"..."}. */
type ThoxStreamLine =
    | { type: 'delta'; text: string }
    | { type: 'done'; stats?: Record<string, unknown> }
    | { type: 'error'; message?: string };

/**
 * Registry models whose endpoint needs a server-held credential (ThoxIntel and any future
 * `openai`-type entry) are streamed through this Space's own proxy. The browser never sees the
 * key; the proxy resolves it from the Space secret named in the registry.
 */
async function streamThoxProxy(
    model: string,
    messages: ChatMessage[],
    callbacks: StreamCallbacks,
    signal?: AbortSignal
) {
    const { modelDef } = resolveModelId(model);
    const resp = await fetch('/api/v2/thoxroute/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            modelId: model,
            messages: messages.map((m) => ({ role: m.role, content: buildThoxContent(m) })),
            temperature: 0.7,
            max_tokens: modelDef?.maxOutputTokens || 4096,
        }),
        signal,
    });

    // The proxy reports which tier answered; anything but `primary` is a degraded answer.
    const servedTier = resp.headers.get('x-thox-tier');
    if (servedTier && servedTier !== 'primary') {
        callbacks.onTier?.(`${servedTier} tier (primary unavailable)`);
    }

    if (!resp.ok) {
        // Surface the upstream reason verbatim — "holding mode" (503) must not look like a bug.
        const detail = await resp.json().catch(() => ({}) as Record<string, unknown>);
        throw new Error(
            `THOX route error (${resp.status}): ${detail.error || resp.statusText}${
                detail.detail ? ` — ${detail.detail}` : ''
            }`
        );
    }

    const reader = resp.body?.getReader();
    if (!reader) throw new Error('No response body');

    const decoder = new TextDecoder();
    let fullText = '';
    let buffer = '';

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed.startsWith('data: ')) continue;
            const data = trimmed.slice(6);
            if (data === '[DONE]') continue;
            try {
                const parsed = JSON.parse(data);
                const delta = parsed.choices?.[0]?.delta?.content;
                if (delta) {
                    fullText += delta;
                    callbacks.onChunk(fullText);
                }
            } catch {
                // Ignore malformed keep-alive/comment frames.
            }
        }
    }

    await callbacks.onDone(fullText);
}

/**
 * THOX tiering: one client-side cascade that ends on-device.
 *
 * Order is deliberate — remote first, browser last:
 *   1. the server proxy (which itself walks paid -> free ZeroGPU -> free CPU using credentials the
 *      browser must never hold), or the direct network tiers when no credential is involved;
 *   2. the in-browser WebGPU model, which is the only tier that still answers with NO network.
 *
 * The WebGPU tier is appended ONLY when the model is already resident (or the caller opted in), so
 * a remote outage never silently triggers a ~2 GB download on someone's phone.
 */
async function streamThoxTiers(
    model: string,
    messages: ChatMessage[],
    callbacks: StreamCallbacks,
    signal?: AbortSignal
) {
    const { modelDef } = resolveModelId(model);
    const targets: AdapterTarget[] = [];

    if (modelDef?.protocol === 'thox-proxy') {
        targets.push({ type: 'proxy', modelId: model, baseURL: '' });
    } else {
        if (modelDef?.origin) targets.push({ type: 'thoxmythos', baseURL: modelDef.origin });
        for (const f of modelDef?.fallbacks ?? []) {
            targets.push({ type: f.type as AdapterTarget['type'], baseURL: f.origin });
        }
    }

    // Offline floor. Only offered when it can actually answer right now.
    if (isWebGPUModelLoaded()) {
        targets.push({ type: 'webgpu', baseURL: '', autoLoad: false });
    }

    if (targets.length === 0) throw new Error(`No THOX endpoint configured for model: ${model}`);

    const turns: ChatTurn[] = messages.map((m) => ({
        role: m.role as ChatTurn['role'],
        content: buildThoxContent(m),
    }));

    let serverTier: string | null = null;
    const result = await cascadeChat(
        targets,
        turns,
        {
            onChunk: (full) => callbacks.onChunk(full),
            onServedTier: (t) => {
                serverTier = t;
            },
        },
        { maxTokens: modelDef?.maxOutputTokens || 4096, temperature: 0.7, signal, modelId: model }
    );

    const served = targets[result.servedBy];
    if (served?.type === 'webgpu') {
        callbacks.onTier?.('on-device WebGPU (all network tiers unavailable)');
    } else if (serverTier && serverTier !== 'primary') {
        callbacks.onTier?.(`${serverTier} tier (primary unavailable)`);
    } else if (result.servedBy > 0) {
        const tier = modelDef?.fallbacks?.[result.servedBy - (modelDef?.origin ? 1 : 0)]?.tier;
        callbacks.onTier?.(`${tier ?? 'fallback'} tier (primary unavailable)`);
    }
    await callbacks.onDone(result.text);
}

async function streamThoxNDJSON(
    model: string,
    messages: ChatMessage[],
    callbacks: StreamCallbacks,
    signal?: AbortSignal
) {
    const { modelDef } = resolveModelId(model);
    const origin = modelDef?.origin;
    if (!origin) throw new Error(`No THOX origin configured for model: ${model}`);
    const maxTokens = modelDef?.maxOutputTokens || 4096;

    const formattedMessages = messages.map((m) => ({
        role: m.role,
        content: buildThoxContent(m),
    }));

    // Public native stream — no Authorization header (that is the private /api/v1 tier).
    const resp = await fetch(`${origin}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            messages: formattedMessages,
            temperature: 0.7,
            maxTokens,
        }),
        signal,
    });

    if (!resp.ok) {
        const errorText = await resp.text().catch(() => resp.statusText);
        throw new Error(`THOX error (${resp.status}): ${errorText}`);
    }

    const reader = resp.body?.getReader();
    if (!reader) throw new Error('No response body');

    const decoder = new TextDecoder();
    let fullText = '';
    let buffer = '';

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed) continue;

            let parsed: ThoxStreamLine;
            try {
                parsed = JSON.parse(trimmed) as ThoxStreamLine;
            } catch {
                // skip malformed line
                continue;
            }

            if (parsed.type === 'delta' && typeof parsed.text === 'string') {
                fullText += parsed.text;
                callbacks.onChunk(fullText);
            } else if (parsed.type === 'error') {
                // Propagates to streamChat's try/catch → callbacks.onError
                throw new Error(parsed.message || 'THOX stream error');
            }
            // parsed.type === 'done' → stream finished (stats in parsed.stats); loop ends when body closes
        }
    }

    callbacks.onDone(fullText);
}

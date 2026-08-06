import type { SearchSource } from './db';

// ─── ThoxSearch — real-time web grounding ───
//
// Local-first: search only runs when the user has explicitly enabled web
// grounding (see providers.getWebSearchEnabled) AND has configured a key for
// the selected provider. If no key is available, searchWeb resolves to an
// empty result set so the caller can answer ungrounded — it never throws for a
// missing key.

export type SearchProvider = 'tavily' | 'brave';

// localStorage keys. The Tavily key mirrors the one written by providers.ts
// (getTavilyApiKey/setTavilyApiKey) so existing settings keep working.
const TAVILY_KEY = 'thoxos_tavily_key';
const BRAVE_KEY = 'thoxos_brave_key';
const SEARCH_PROVIDER_KEY = 'thoxos_search_provider';

const DEFAULT_MAX_RESULTS = 8;

// Optional build-time fallbacks (see env-additions/search.env). Runtime
// settings always take precedence over these.
function envVar(name: string): string {
    try {
        const env = (import.meta as unknown as { env?: Record<string, string | undefined> }).env;
        return env?.[name] || '';
    } catch {
        return '';
    }
}

function readStorage(key: string): string {
    try {
        return (typeof localStorage !== 'undefined' && localStorage.getItem(key)) || '';
    } catch {
        return '';
    }
}

// ─── Settings accessors ───

/** The currently selected search provider (defaults to Tavily). */
export function getSearchProvider(): SearchProvider {
    return readStorage(SEARCH_PROVIDER_KEY) === 'brave' ? 'brave' : 'tavily';
}

export function setSearchProvider(provider: SearchProvider) {
    try {
        localStorage.setItem(SEARCH_PROVIDER_KEY, provider);
    } catch {
        // storage unavailable — ignore
    }
}

/** Resolve the API key for a provider from settings, then build-time env. */
export function getSearchApiKey(provider: SearchProvider): string {
    if (provider === 'brave') {
        return readStorage(BRAVE_KEY) || envVar('VITE_BRAVE_API_KEY');
    }
    return readStorage(TAVILY_KEY) || envVar('VITE_TAVILY_API_KEY');
}

export function getBraveApiKey(): string {
    return readStorage(BRAVE_KEY) || envVar('VITE_BRAVE_API_KEY');
}

export function setBraveApiKey(key: string) {
    try {
        if (key) localStorage.setItem(BRAVE_KEY, key);
        else localStorage.removeItem(BRAVE_KEY);
    } catch {
        // storage unavailable — ignore
    }
}

// ─── Public search API ───

export interface SearchOptions {
    /** Override the selected provider for this call. */
    provider?: SearchProvider;
    /** Override the resolved API key for this call. */
    apiKey?: string;
    /** Max results to request (clamped 1–20). */
    maxResults?: number;
    signal?: AbortSignal;
}

export interface SearchResponse {
    results: SearchSource[];
    /** Provider-supplied direct answer, when available (Tavily). */
    answer?: string;
    provider: SearchProvider;
}

/**
 * Run a real web search and return normalized {title, url, content(snippet)}
 * results. The second positional argument accepts a Tavily key for backward
 * compatibility with existing callers; richer control is available via options.
 *
 * Returns an empty result set (never throws) when the query is blank or no key
 * is configured for the active provider, so the caller can answer ungrounded.
 */
export async function searchWeb(
    query: string,
    apiKey?: string,
    options: SearchOptions = {}
): Promise<SearchResponse> {
    const provider = options.provider ?? getSearchProvider();

    if (!query.trim()) {
        return { results: [], provider };
    }

    // Prefer the stored/env key for the active provider; fall back to an
    // explicitly-passed key only when it matches the provider (Tavily). This
    // keeps legacy `searchWeb(query, tavilyKey)` calls working while allowing
    // Brave to be driven entirely from settings.
    const key =
        options.apiKey ||
        getSearchApiKey(provider) ||
        (provider === 'tavily' ? apiKey || '' : '');

    if (!key) {
        return { results: [], provider };
    }

    const maxResults = Math.min(Math.max(options.maxResults ?? DEFAULT_MAX_RESULTS, 1), 20);

    if (provider === 'brave') {
        const results = await searchBrave(query, key, maxResults, options.signal);
        return { results, provider };
    }

    return { ...(await searchTavily(query, key, maxResults, options.signal)), provider };
}

// ─── Tavily (POST) ───

async function searchTavily(
    query: string,
    apiKey: string,
    maxResults: number,
    signal?: AbortSignal
): Promise<{ results: SearchSource[]; answer?: string }> {
    const resp = await fetch('https://api.tavily.com/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            api_key: apiKey,
            query,
            search_depth: 'basic',
            include_answer: true,
            max_results: maxResults,
        }),
        signal,
    });

    if (!resp.ok) {
        const errorText = await resp.text().catch(() => resp.statusText);
        throw new Error(`Tavily search error (${resp.status}): ${errorText}`);
    }

    const data = await resp.json();
    const results: SearchSource[] = (data.results || []).map(
        (r: { title: string; url: string; content: string; score?: number }) => ({
            title: r.title,
            url: r.url,
            content: r.content,
            score: r.score,
        })
    );

    return { results, answer: data.answer };
}

// ─── Brave Search (GET) ───

async function searchBrave(
    query: string,
    apiKey: string,
    maxResults: number,
    signal?: AbortSignal
): Promise<SearchSource[]> {
    const params = new URLSearchParams({
        q: query,
        count: String(maxResults),
    });

    const resp = await fetch(`https://api.search.brave.com/res/v1/web/search?${params.toString()}`, {
        method: 'GET',
        headers: {
            Accept: 'application/json',
            'Accept-Encoding': 'gzip',
            'X-Subscription-Token': apiKey,
        },
        signal,
    });

    if (!resp.ok) {
        const errorText = await resp.text().catch(() => resp.statusText);
        throw new Error(`Brave search error (${resp.status}): ${errorText}`);
    }

    const data = await resp.json();
    const webResults: Array<{ title?: string; url?: string; description?: string }> =
        data?.web?.results || [];

    return webResults
        .filter((r) => r.url)
        .map((r) => ({
            title: r.title || r.url || 'Untitled',
            url: r.url as string,
            // Brave descriptions can contain <strong> highlight markup — strip it.
            content: stripHtml(r.description || ''),
        }));
}

function stripHtml(input: string): string {
    return input.replace(/<[^>]*>/g, '').trim();
}

// ─── Grounding context ───

/**
 * Format normalized results into a system-appendable grounding block with
 * inline citation markers ([1], [2], …) that line up with SourcesPanel.
 */
export function buildGroundingContext(results: SearchSource[]): string {
    if (!results.length) return '';

    let formatted =
        '\n\n---\n\n**🔍 LIVE WEB SEARCH RESULTS** (use these as your PRIMARY source — they are more current than your training data)\n\n';
    formatted += `Search returned ${results.length} result${results.length !== 1 ? 's' : ''}. Cite them inline using [1], [2], etc.\n\n`;

    results.forEach((r, i) => {
        formatted += `**[${i + 1}] ${r.title}**\n`;
        formatted += `${r.content}\n`;
        formatted += `Source: ${r.url}\n\n`;
    });

    formatted += '---\n\n**REMINDER:** Base your answer primarily on the above search results. Cite sources inline with the matching [n] marker.\n';

    return formatted;
}

/** Backward-compatible alias for existing callers. */
export const formatSearchResultsForPrompt = buildGroundingContext;

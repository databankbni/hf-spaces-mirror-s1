import { useRef, useState, useCallback, useEffect } from 'react';
import { ArrowDown, PanelLeft } from 'lucide-react';
import { useApp } from '../context/AppContext';
import { useMessages, addMessage, updateMessage, autoTitleConversation, createConversation } from '../lib/hooks';
import { streamChat, type ChatMessage } from '../lib/ai';
import { buildSystemPrompt } from '../lib/systemPrompts';
import { getApiKey, getTavilyApiKey, getProvider } from '../lib/providers';
import { getThoxRouteStatus, chooseModel, buildSignals } from '../lib/thoxroute/client';
import { searchWeb, formatSearchResultsForPrompt } from '../lib/search';
import type { Attachment } from '../lib/db';
import MessageBubble from './MessageBubble';
import ChatInput from './ChatInput';

export default function ChatView() {
    const {
        activeConversationId,
        setActiveConversationId,
        activeProviderId,
        activeModelId,
        isStreaming,
        setIsStreaming,
        toggleSidebar,
        sidebarOpen,
        routeStatus,
    } = useApp();

    const messages = useMessages(activeConversationId);
    const [streamingContent, setStreamingContent] = useState('');
    const [showScrollBtn, setShowScrollBtn] = useState(false);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const scrollContainerRef = useRef<HTMLDivElement>(null);
    const abortRef = useRef<AbortController | null>(null);

    const scrollToBottom = useCallback((smooth = true) => {
        messagesEndRef.current?.scrollIntoView({ behavior: smooth ? 'smooth' : 'instant' });
    }, []);

    useEffect(() => {
        scrollToBottom(false);
    }, [messages.length, scrollToBottom]);

    useEffect(() => {
        if (streamingContent) scrollToBottom();
    }, [streamingContent, scrollToBottom]);

    const handleScroll = useCallback(() => {
        const el = scrollContainerRef.current;
        if (!el) return;
        const isScrollable = el.scrollHeight > el.clientHeight + 50;
        const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
        setShowScrollBtn(isScrollable && !atBottom);
    }, []);

    const handleSend = useCallback(
        async (text: string, webSearch: boolean, visualMode: boolean = true, attachments: Attachment[] = []) => {
            let conversationId = activeConversationId;

            if (!conversationId) {
                conversationId = await createConversation(activeProviderId, activeModelId);
                setActiveConversationId(conversationId);
            }

            const apiKey = getApiKey(activeProviderId);
            const requiresKey = (getProvider(activeProviderId)?.keyPrefix ?? 'x') !== '';
            if (requiresKey && !apiKey) {
                alert(`Please set your ${activeProviderId} API key in Settings.`);
                return;
            }

            // ─── ThoxRoute best-model selection ───
            // The "ThoxRoute — auto" tier is not itself a model: it classifies the turn and hands
            // it to the strongest AVAILABLE model for that route (local-first for light turns,
            // escalating to the server/cloud tiers for hard ones). Gated models are never chosen
            // here — only an explicit pick can reach them.
            let effectiveModelId = activeModelId;
            let routeNote: string | null = null;
            let tierNote: string | null = null;
            if (activeProviderId === 'thox' && activeModelId === 'thoxroute') {
                // Routing is an optimisation, never a precondition: any failure here degrades to
                // the built-in default model rather than costing the user their turn.
                try {
                    const status = routeStatus ?? (await getThoxRouteStatus());
                    const signals = buildSignals(text, messages.length, {
                        hasImageInput: attachments.some((a) => a.type === 'image'),
                    });
                    const choice = chooseModel(status, signals);
                    if (choice.chosen) {
                        effectiveModelId = choice.chosen.model.id;
                        routeNote = `${choice.decision.route} → ${choice.chosen.model.displayName}`;
                    }
                } catch (err) {
                    console.warn('[thoxroute] selection failed; using default model', err);
                }
            }

            await addMessage(conversationId, 'user', text, undefined, attachments.length > 0 ? attachments : undefined);

            // Auto-title on first message
            const msgCount = messages.length;
            if (msgCount === 0) {
                autoTitleConversation(conversationId, text);
            }

            // Build system prompt with date and web search awareness
            const currentDate = new Date().toLocaleDateString('en-US', {
                weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
            });

            let searchContext = '';

            // Web search — fetch results and build context block
            if (webSearch) {
                const tavilyKey = getTavilyApiKey();
                if (tavilyKey) {
                    try {
                        const searchResults = await searchWeb(text, tavilyKey);
                        searchContext = formatSearchResultsForPrompt(searchResults.results);
                    } catch {
                        // Graceful fallback — proceed without search
                    }
                }
            }

            const systemPrompt = buildSystemPrompt(webSearch, currentDate, visualMode);

            const chatMessages: ChatMessage[] = [
                ...messages.map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content, attachments: m.attachments })),
                { role: 'user' as const, content: searchContext ? text + searchContext : text, attachments: attachments.length > 0 ? attachments : undefined },
            ];

            setIsStreaming(true);
            setStreamingContent('');
            const abort = new AbortController();
            abortRef.current = abort;

            const assistantMsgId = await addMessage(conversationId, 'assistant', '');

            await streamChat(
                chatMessages,
                activeProviderId,
                effectiveModelId,
                apiKey,
                systemPrompt,
                {
                    onChunk: (fullText) => {
                        setStreamingContent(fullText);
                    },
                    onTier: (label) => {
                        tierNote = label;
                    },
                    onDone: async (fullText) => {
                        setStreamingContent('');
                        setIsStreaming(false);
                        abortRef.current = null;
                        // Persist the routing decision with the turn: which model answered and
                        // why is part of the record, not just a transient UI hint.
                        await updateMessage(
                            assistantMsgId,
                            fullText,
                            undefined,
                            [routeNote, tierNote].filter(Boolean).join(' · ') || undefined
                        );
                    },
                    onError: async (error) => {
                        setStreamingContent('');
                        setIsStreaming(false);
                        abortRef.current = null;
                        await updateMessage(assistantMsgId, `⚠️ Error: ${error.message}`);
                    },
                },
                abort.signal
            );
        },
        [activeConversationId, activeProviderId, activeModelId, messages, setActiveConversationId, setIsStreaming, routeStatus]
    );

    const handleStop = useCallback(() => {
        abortRef.current?.abort();
        setIsStreaming(false);
        setStreamingContent('');
    }, [setIsStreaming]);

    const suggestedPrompts = [
        '✨ Explain quantum computing simply',
        '📊 Compare React vs Vue vs Svelte',
        '🧮 Solve a calculus integral step by step',
        '📝 Create a project planning template',
    ];

    return (
        <div className="flex-1 flex flex-col h-full min-w-0 bg-bg-primary relative">
            {/* Mobile Header */}
            <div className="flex items-center gap-3 px-4 py-3 border-b border-border md:hidden">
                <button
                    onClick={toggleSidebar}
                    className="p-1.5 rounded-lg hover:bg-bg-surface-hover text-text-secondary transition-colors"
                >
                    <PanelLeft size={20} />
                </button>
                <img src="/logo.svg" alt="" style={{ width: 22, height: 22, borderRadius: 5 }} />
                <span className="text-sm font-medium text-text-primary truncate">ThoxOS Web Edition</span>
            </div>

            {/* Desktop toggle when sidebar is hidden */}
            {!sidebarOpen && (
                <div className="hidden md:flex items-center gap-3 px-4 py-3 border-b border-border">
                    <button
                        onClick={toggleSidebar}
                        className="p-1.5 rounded-lg hover:bg-bg-surface-hover text-text-secondary transition-colors"
                    >
                        <PanelLeft size={20} />
                    </button>
                    <img src="/logo.svg" alt="" style={{ width: 22, height: 22, borderRadius: 5 }} />
                    <span className="text-sm font-medium text-text-primary">ThoxOS Web Edition</span>
                </div>
            )}

            {/* Messages */}
            <div
                ref={scrollContainerRef}
                onScroll={handleScroll}
                className="flex-1 overflow-y-auto"
            >
                {!activeConversationId || messages.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-full px-4 py-12">
                        {/* THOX brand lockup */}
                        <div className="flex items-center gap-3 mb-6">
                            <img
                                src="/logo.svg"
                                alt="THOX"
                                className="w-11 h-11 rounded-xl shadow-[0_0_20px_rgba(16,185,129,0.15)]"
                            />
                            <div className="flex flex-col leading-none">
                                <span className="font-mono font-bold text-2xl tracking-tight text-text-primary">
                                    Thox<span className="text-accent">.ai</span>
                                </span>
                                <span className="text-[11px] font-medium uppercase tracking-[0.18em] text-text-tertiary mt-1.5">
                                    Web Edition
                                </span>
                            </div>
                        </div>
                        <h1 className="text-xl md:text-2xl font-semibold text-text-primary mb-2 text-center">
                            How can I help you today?
                        </h1>
                        <p className="text-sm text-text-secondary mb-8 text-center max-w-md">
                            Private, local-first AI on the THOX fleet — <span className="text-text-primary font-medium">ThoxRoute</span> auto-selects ThoxMini-3B or ThoxMythos-9B. Bring your own keys anytime.
                        </p>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-lg">
                            {suggestedPrompts.map((prompt) => (
                                <button
                                    key={prompt}
                                    onClick={() => handleSend(prompt.replace(/^[^\s]+\s/, ''), false)}
                                    className="text-left px-4 py-3 rounded-xl border border-border bg-bg-surface hover:bg-bg-surface-hover text-sm text-text-secondary hover:text-text-primary transition-all hover:border-border-active"
                                >
                                    {prompt}
                                </button>
                            ))}
                        </div>
                    </div>
                ) : (
                    <div className="max-w-4xl mx-auto px-4 py-6 space-y-1">
                        {messages.map((msg) => (
                            <MessageBubble
                                key={msg.id}
                                message={msg}
                                isStreaming={false}
                            />
                        ))}
                        {isStreaming && streamingContent && (
                            <MessageBubble
                                message={{
                                    id: 'streaming',
                                    conversationId: activeConversationId!,
                                    role: 'assistant',
                                    content: streamingContent,
                                    createdAt: Date.now(),
                                }}
                                isStreaming={true}
                            />
                        )}
                        <div ref={messagesEndRef} />
                    </div>
                )}
                {/* Scroll to bottom button */}
                {showScrollBtn && (
                    <button
                        onClick={() => scrollToBottom()}
                        className="absolute bottom-4 left-1/2 -translate-x-1/2 p-2 rounded-full bg-bg-surface border border-border shadow-md hover:bg-bg-surface-hover transition-all animate-fade-in z-10"
                    >
                        <ArrowDown size={16} className="text-text-secondary" />
                    </button>
                )}
            </div>

            {/* Input */}
            <ChatInput
                onSend={handleSend}
                onStop={handleStop}
                isStreaming={isStreaming}
            />
        </div>
    );
}

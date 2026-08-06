import { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import { Mic, X, Loader2, Volume2 } from 'lucide-react';
import {
    getApiKey, getVoiceApiKey, getSTTProvider,
    getTTSProvider, getEffectiveTTSVoice,
} from '../lib/providers';
import { startSTT, resolveSTTEngine, browserSTTSupported, type STTSession } from '../lib/voice/stt';
import {
    speakOpenAI, speakElevenLabs, speakBrowser,
    stopPlayback, browserTTSSupported, stripMarkdownForSpeech,
} from '../lib/voice/tts';
import { useApp } from '../context/AppContext';
import { useMessages } from '../lib/hooks';

interface VoiceModePanelProps {
    onResult: (transcript: string) => void;
    onExit: () => void;
}

type VoiceState = 'idle' | 'recording' | 'processing' | 'speaking';

export default function VoiceModePanel({ onResult, onExit }: VoiceModePanelProps) {
    const { activeConversationId, isStreaming } = useApp();
    const messages = useMessages(activeConversationId);

    const [state, setState] = useState<VoiceState>('idle');
    const sessionRef = useRef<STTSession | null>(null);

    // ─── STT setup (cloud engine, degrading to the free browser engine) ───
    const sttProvider = getSTTProvider();
    const sttApiKey = sttProvider === 'whisper'
        ? getApiKey('openai')
        : getVoiceApiKey('stt', 'elevenlabs');
    const sttEngine = resolveSTTEngine(sttProvider, sttApiKey);
    const canCapture = !!sttApiKey || browserSTTSupported();

    // ─── Speak the assistant reply once it finishes streaming ───
    // Only speak messages that appear after this panel mounted, so opening
    // voice mode never re-reads earlier history.
    const mountTimeRef = useRef(Date.now());
    const spokenIdRef = useRef<string | null>(null);

    const lastAssistant = useMemo(
        () => [...messages].reverse().find((m) => m.role === 'assistant'),
        [messages]
    );

    const speakReply = useCallback(async (raw: string) => {
        const text = stripMarkdownForSpeech(raw);
        if (!text) return;

        const ttsProvider = getTTSProvider();
        const ttsApiKey = ttsProvider === 'openai-tts'
            ? getApiKey('openai')
            : getVoiceApiKey('tts', 'elevenlabs');
        const voice = getEffectiveTTSVoice();

        setState('speaking');
        try {
            if (ttsApiKey && ttsProvider === 'openai-tts') {
                await speakOpenAI(text, ttsApiKey, voice);
            } else if (ttsApiKey && ttsProvider === 'elevenlabs-tts') {
                await speakElevenLabs(text, ttsApiKey, voice);
            } else if (browserTTSSupported()) {
                // Free fallback when no cloud TTS key is configured.
                await speakBrowser(text);
            }
        } catch (err) {
            console.error('TTS error:', err);
        } finally {
            setState((s) => (s === 'speaking' ? 'idle' : s));
        }
    }, []);

    useEffect(() => {
        if (state === 'recording' || state === 'processing') return; // don't interrupt capture
        if (isStreaming) return;                                      // wait for the reply to finish
        if (!lastAssistant) return;
        if (lastAssistant.createdAt <= mountTimeRef.current) return;  // pre-existing history
        if (!lastAssistant.content.trim()) return;
        if (spokenIdRef.current === lastAssistant.id) return;         // already spoke this one

        spokenIdRef.current = lastAssistant.id;
        void speakReply(lastAssistant.content);
    }, [lastAssistant, isStreaming, state, speakReply]);

    // Stop any playback when leaving voice mode.
    useEffect(() => () => stopPlayback(), []);

    const handlePointerDown = useCallback(async () => {
        if (!canCapture || state === 'processing' || state === 'recording') return;
        // Tapping while a reply plays just stops playback (barge-in); the user
        // then holds again to talk.
        if (state === 'speaking') {
            stopPlayback();
            setState('idle');
            return;
        }
        try {
            sessionRef.current = await startSTT(sttEngine, sttApiKey);
            setState('recording');
        } catch (err) {
            console.error('Mic access error:', err);
            setState('idle');
        }
    }, [canCapture, state, sttEngine, sttApiKey]);

    const handlePointerUp = useCallback(async () => {
        if (state !== 'recording' || !sessionRef.current) return;
        const session = sessionRef.current;
        sessionRef.current = null;
        setState('processing');
        try {
            const text = await session.stop();
            if (text && text.trim()) {
                onResult(text.trim());
                // The reply is spoken by the effect above once it streams in.
            }
        } catch (err) {
            console.error('STT error:', err);
        } finally {
            setState((s) => (s === 'processing' ? 'idle' : s));
        }
    }, [state, onResult]);

    return (
        <div className="voice-mode-panel">
            {/* Exit button */}
            <button
                onClick={onExit}
                className="voice-mode-exit"
                title="Back to text input"
            >
                <X size={18} />
            </button>

            {/* Status text */}
            <span className="voice-mode-label">
                {state === 'idle' && 'Hold to talk'}
                {state === 'recording' && 'Listening…'}
                {state === 'processing' && 'Processing…'}
                {state === 'speaking' && 'Speaking… (tap to stop)'}
            </span>

            {/* Big mic button */}
            <button
                onPointerDown={handlePointerDown}
                onPointerUp={handlePointerUp}
                onPointerLeave={state === 'recording' ? handlePointerUp : undefined}
                disabled={state === 'processing' || !canCapture}
                className={`voice-mode-mic ${state === 'recording' ? 'voice-mode-mic-active' : ''}`}
            >
                {state === 'processing' ? (
                    <Loader2 size={28} className="animate-spin" />
                ) : state === 'speaking' ? (
                    <Volume2 size={28} />
                ) : (
                    <Mic size={28} />
                )}
                {(state === 'recording' || state === 'speaking') && (
                    <>
                        <span className="voice-pulse-ring voice-pulse-ring-1" />
                        <span className="voice-pulse-ring voice-pulse-ring-2" />
                        <span className="voice-pulse-ring voice-pulse-ring-3" />
                    </>
                )}
            </button>
        </div>
    );
}

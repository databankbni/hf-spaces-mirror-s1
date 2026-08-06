import { useState, useRef } from 'react';
import { Mic, MicOff, Loader2 } from 'lucide-react';
import { getApiKey, getVoiceApiKey, getSTTProvider } from '../lib/providers';
import { startSTT, resolveSTTEngine, browserSTTSupported, type STTSession } from '../lib/voice/stt';

interface VoiceButtonProps {
    onResult: (transcript: string) => void;
}

export default function VoiceButton({ onResult }: VoiceButtonProps) {
    const [recording, setRecording] = useState(false);
    const [processing, setProcessing] = useState(false);
    const sessionRef = useRef<STTSession | null>(null);

    const sttProvider = getSTTProvider();
    const apiKey = sttProvider === 'whisper'
        ? getApiKey('openai')
        : getVoiceApiKey('stt', 'elevenlabs');

    // Usable if a cloud key is set, or the free browser engine is available.
    if (!apiKey && !browserSTTSupported()) return null;

    const engine = resolveSTTEngine(sttProvider, apiKey);

    const handleToggle = async () => {
        if (processing) return;

        if (recording) {
            // Stop recording → transcribe
            setRecording(false);
            const session = sessionRef.current;
            if (session) {
                sessionRef.current = null;
                setProcessing(true);
                try {
                    const text = await session.stop();
                    if (text && text.trim()) onResult(text.trim());
                } catch (err) {
                    console.error('STT error:', err);
                } finally {
                    setProcessing(false);
                }
            }
        } else {
            // Start recording
            try {
                sessionRef.current = await startSTT(engine, apiKey);
                setRecording(true);
            } catch (err) {
                console.error('Mic access error:', err);
            }
        }
    };

    return (
        <button
            onClick={handleToggle}
            disabled={processing}
            className={`p-1.5 rounded-md transition-all ${recording
                    ? 'text-error bg-error-muted animate-pulse-glow'
                    : processing
                        ? 'text-text-tertiary'
                        : 'text-text-tertiary hover:text-text-secondary hover:bg-bg-surface-hover'
                }`}
            title={recording ? 'Stop recording' : processing ? 'Processing…' : 'Voice input'}
        >
            {processing ? (
                <Loader2 size={14} className="animate-spin" />
            ) : recording ? (
                <MicOff size={14} />
            ) : (
                <Mic size={14} />
            )}
        </button>
    );
}

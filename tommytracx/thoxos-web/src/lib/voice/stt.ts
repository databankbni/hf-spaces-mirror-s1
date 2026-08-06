export async function startRecording(): Promise<{ stop: () => Promise<Blob> }> {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
    const chunks: Blob[] = [];

    mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.push(e.data);
    };

    mediaRecorder.start();

    return {
        stop: () =>
            new Promise<Blob>((resolve) => {
                mediaRecorder.onstop = () => {
                    stream.getTracks().forEach((t) => t.stop());
                    resolve(new Blob(chunks, { type: 'audio/webm' }));
                };
                mediaRecorder.stop();
            }),
    };
}

export async function transcribeWhisper(blob: Blob, apiKey: string): Promise<string> {
    const form = new FormData();
    form.append('file', blob, 'audio.webm');
    form.append('model', 'whisper-1');

    const resp = await fetch('https://api.openai.com/v1/audio/transcriptions', {
        method: 'POST',
        headers: { Authorization: `Bearer ${apiKey}` },
        body: form,
    });

    if (!resp.ok) throw new Error(`Whisper error (${resp.status})`);
    const data = await resp.json();
    return data.text || '';
}

export async function transcribeElevenLabs(blob: Blob, apiKey: string): Promise<string> {
    const form = new FormData();
    form.append('file', blob, 'audio.webm');
    form.append('model_id', 'scribe_v1');

    const resp = await fetch('https://api.elevenlabs.io/v1/speech-to-text', {
        method: 'POST',
        headers: { 'xi-api-key': apiKey },
        body: form,
    });

    if (!resp.ok) throw new Error(`ElevenLabs STT error (${resp.status})`);
    const data = await resp.json();
    return data.text || '';
}

// ─── Unified STT session ───
//
// Cloud engines (Whisper / ElevenLabs Scribe) record with MediaRecorder and
// transcribe the resulting blob on stop(). The browser engine uses the free
// Web Speech API (SpeechRecognition) and needs no key — it is the graceful
// fallback used whenever the selected cloud key is missing or unset.

export type STTEngine = 'whisper' | 'elevenlabs-scribe' | 'browser';

export interface STTSession {
    readonly engine: STTEngine;
    /** Stop capturing and resolve the final transcript. */
    stop: () => Promise<string>;
    /** Abort capture without transcribing. */
    cancel: () => void;
}

// Minimal typings for the Web Speech API — not part of the standard TS DOM lib.
interface SpeechRecognitionAlternativeLike {
    readonly transcript: string;
}
interface SpeechRecognitionResultLike {
    readonly isFinal: boolean;
    readonly length: number;
    readonly [index: number]: SpeechRecognitionAlternativeLike;
}
interface SpeechRecognitionResultListLike {
    readonly length: number;
    readonly [index: number]: SpeechRecognitionResultLike;
}
interface SpeechRecognitionEventLike {
    readonly resultIndex: number;
    readonly results: SpeechRecognitionResultListLike;
}
interface SpeechRecognitionLike {
    lang: string;
    continuous: boolean;
    interimResults: boolean;
    start: () => void;
    stop: () => void;
    abort: () => void;
    onresult: ((e: SpeechRecognitionEventLike) => void) | null;
    onerror: ((e: Event) => void) | null;
    onend: (() => void) | null;
}
type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

function getSpeechRecognitionCtor(): SpeechRecognitionCtor | null {
    if (typeof window === 'undefined') return null;
    const w = window as unknown as {
        SpeechRecognition?: SpeechRecognitionCtor;
        webkitSpeechRecognition?: SpeechRecognitionCtor;
    };
    return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

/** Whether the free browser speech-recognition fallback is available. */
export function browserSTTSupported(): boolean {
    return getSpeechRecognitionCtor() !== null;
}

/**
 * Pick the engine to actually use. Honours the user's chosen cloud engine when
 * its key is present; otherwise degrades to the free browser engine.
 */
export function resolveSTTEngine(
    preferred: 'whisper' | 'elevenlabs-scribe',
    apiKey: string
): STTEngine {
    if (apiKey) return preferred;
    if (browserSTTSupported()) return 'browser';
    return preferred;
}

async function startBrowserRecognition(): Promise<STTSession> {
    const Ctor = getSpeechRecognitionCtor();
    if (!Ctor) throw new Error('Browser speech recognition not supported');

    const rec = new Ctor();
    rec.lang = (typeof navigator !== 'undefined' && navigator.language) || 'en-US';
    rec.continuous = true;
    rec.interimResults = false;

    let transcript = '';
    let ended = false;
    let onEnd: (() => void) | null = null;

    rec.onresult = (e) => {
        for (let i = e.resultIndex; i < e.results.length; i++) {
            const result = e.results[i];
            if (result.isFinal && result.length > 0) {
                transcript += result[0].transcript;
            }
        }
    };
    rec.onend = () => {
        ended = true;
        onEnd?.();
    };

    rec.start();

    return {
        engine: 'browser',
        stop: () =>
            new Promise<string>((resolve) => {
                if (ended) {
                    resolve(transcript.trim());
                    return;
                }
                onEnd = () => resolve(transcript.trim());
                try {
                    rec.stop();
                } catch {
                    resolve(transcript.trim());
                }
            }),
        cancel: () => {
            try {
                rec.abort();
            } catch {
                /* ignore */
            }
        },
    };
}

async function startCloudRecognition(
    engine: 'whisper' | 'elevenlabs-scribe',
    apiKey: string
): Promise<STTSession> {
    const recorder = await startRecording();
    let done = false;

    return {
        engine,
        stop: async () => {
            done = true;
            const blob = await recorder.stop();
            return engine === 'whisper'
                ? transcribeWhisper(blob, apiKey)
                : transcribeElevenLabs(blob, apiKey);
        },
        cancel: () => {
            if (done) return;
            done = true;
            // Stop the recorder and discard the audio.
            recorder.stop().catch(() => {
                /* discard */
            });
        },
    };
}

/**
 * Begin an STT capture session for the given (already-resolved) engine.
 * Use resolveSTTEngine() first to apply the missing-key → browser fallback.
 */
export async function startSTT(engine: STTEngine, apiKey: string): Promise<STTSession> {
    if (engine === 'browser') return startBrowserRecognition();
    return startCloudRecognition(engine, apiKey);
}

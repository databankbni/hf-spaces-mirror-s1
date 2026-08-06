"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { VerseRef } from "../types";
import { MicIcon, StopIcon, BookIcon, ChevronIcon } from "./Icons";

// Minimal Web Speech API typing (continuous recognition).
interface SpeechResult {
  isFinal: boolean;
  0: { transcript: string };
}
interface SpeechRec {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((e: { resultIndex: number; results: ArrayLike<SpeechResult> }) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
}

function getRecognition(): SpeechRec | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: new () => SpeechRec;
    webkitSpeechRecognition?: new () => SpeechRec;
  };
  const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
  return Ctor ? new Ctor() : null;
}

interface Detection extends VerseRef {
  snippet: string;
  exact: boolean;
  at: number;
  normalized_ref?: string;
  trigger?: "direct" | "cue_phrase" | "semantic";
}

type RefStyle = "colon" | "v";
const REF_STYLE_KEY = "verseo.ref_style";
const AUDIO_DEVICE_KEY = "verseo.audio_input";

export default function ActiveListening({
  version,
  spokenLang,
  disabled,
  testKey = "",
  onOpenRef,
}: {
  version: string;
  spokenLang: string;
  disabled?: boolean;
  testKey?: string;
  onOpenRef: (ref: string) => void;
}) {
  const [supported, setSupported] = useState(true);
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [detections, setDetections] = useState<Detection[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refStyle, setRefStyle] = useState<RefStyle>("colon");

  // Audio input picker
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceId, setDeviceId] = useState<string>("");
  const [showDevices, setShowDevices] = useState(false);

  const recogRef = useRef<SpeechRec | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const activeRef = useRef(false); // keep latest "listening" for onend restart
  const lastRefRef = useRef<string>(""); // dedupe consecutive same verse

  useEffect(() => {
    // Client-only detection (avoids an SSR hydration mismatch).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSupported(getRecognition() !== null);
    try {
      const s = localStorage.getItem(REF_STYLE_KEY);
      if (s === "colon" || s === "v") setRefStyle(s);
      const d = localStorage.getItem(AUDIO_DEVICE_KEY);
      if (d) setDeviceId(d);
    } catch {
      /* ignore */
    }
  }, []);

  // Enumerate audio input devices (labels appear after mic permission is granted).
  const loadDevices = useCallback(async () => {
    try {
      const all = await navigator.mediaDevices.enumerateDevices();
      setDevices(all.filter((d) => d.kind === "audioinput"));
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    // On-mount enumeration; also refresh when devices are hot-plugged.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadDevices();
    const onChange = () => void loadDevices();
    navigator.mediaDevices?.addEventListener?.("devicechange", onChange);
    return () => navigator.mediaDevices?.removeEventListener?.("devicechange", onChange);
  }, [loadDevices]);

  const detect = useCallback(
    async (text: string) => {
      try {
        const headers: Record<string, string> = { "Content-Type": "application/json" };
        if (testKey) headers["X-Test-Key"] = testKey;
        const res = await fetch("/api/listen", {
          method: "POST",
          headers,
          body: JSON.stringify({ text, version, ref_style: refStyle }),
        });
        const data = await res.json();
        if (data.matched && data.result) {
          const ref: string = data.result.ref;
          if (ref === lastRefRef.current) return; // skip immediate repeat
          lastRefRef.current = ref;
          navigator.vibrate?.(14);
          setDetections((prev) =>
            [
              {
                ...data.result,
                snippet: data.snippet ?? text,
                exact: !!data.exact,
                normalized_ref: data.normalized_ref,
                trigger: data.trigger,
                at: Date.now(),
              },
              ...prev,
            ].slice(0, 30),
          );
        }
      } catch {
        /* ignore a single failed chunk */
      }
    },
    [version, refStyle, testKey],
  );

  const stop = useCallback(() => {
    activeRef.current = false;
    setListening(false);
    setInterim("");
    recogRef.current?.stop();
    recogRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  const start = useCallback(async () => {
    const recog = getRecognition();
    if (!recog) {
      setSupported(false);
      return;
    }
    setError(null);
    setDetections([]);
    lastRefRef.current = "";

    // Bind mic permission to the chosen input device. The Web Speech API
    // itself doesn't take a deviceId, but requesting a live track on it
    // pins the OS default audio route while we listen.
    try {
      const constraints: MediaStreamConstraints = {
        audio: deviceId
          ? { deviceId: { exact: deviceId }, echoCancellation: true, noiseSuppression: true }
          : { echoCancellation: true, noiseSuppression: true },
      };
      streamRef.current = await navigator.mediaDevices.getUserMedia(constraints);
      // After first permission grant, device labels become populated.
      void loadDevices();
    } catch (e) {
      setError(
        e instanceof Error && e.name === "NotAllowedError"
          ? "Microphone permission denied."
          : "Could not access the selected microphone.",
      );
      return;
    }

    recog.lang = spokenLang === "es" ? "es-ES" : "en-US";
    recog.continuous = true;
    recog.interimResults = true;
    recog.onresult = (e) => {
      let live = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) {
          const text = r[0].transcript.trim();
          if (text) void detect(text);
        } else {
          live += r[0].transcript;
        }
      }
      setInterim(live);
    };
    recog.onerror = (ev) => {
      if (ev.error === "not-allowed" || ev.error === "service-not-allowed") {
        setError("Microphone permission denied.");
        stop();
      }
    };
    recog.onend = () => {
      if (activeRef.current) {
        try {
          recog.start();
        } catch {
          /* already starting */
        }
      }
    };
    try {
      recog.start();
      recogRef.current = recog;
      activeRef.current = true;
      setListening(true);
    } catch {
      setError("Could not start listening. Try again.");
    }
  }, [spokenLang, detect, stop, deviceId, loadDevices]);

  useEffect(() => () => stop(), [stop]); // cleanup on unmount

  const chooseDevice = (id: string) => {
    setDeviceId(id);
    setShowDevices(false);
    try {
      localStorage.setItem(AUDIO_DEVICE_KEY, id);
    } catch {
      /* ignore */
    }
    if (listening) {
      // Re-bind to the newly chosen device.
      stop();
      setTimeout(() => void start(), 100);
    }
  };
  const chooseStyle = (s: RefStyle) => {
    setRefStyle(s);
    try {
      localStorage.setItem(REF_STYLE_KEY, s);
    } catch {
      /* ignore */
    }
  };

  const currentDeviceLabel =
    devices.find((d) => d.deviceId === deviceId)?.label ||
    (deviceId ? "Selected input" : "System default");

  if (!supported) {
    return (
      <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-400/20 dark:bg-amber-500/10 dark:text-amber-200">
        Active listening needs a browser with speech recognition (e.g. Chrome).
        Try the Speak or Type modes instead.
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center gap-5">
      {/* Input source + reference format controls */}
      <div className="flex w-full flex-wrap items-center justify-center gap-2 text-xs">
        <div className="relative">
          <button
            type="button"
            onClick={() => setShowDevices((s) => !s)}
            className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 font-medium text-slate-600 transition hover:border-slate-300 dark:border-white/10 dark:bg-white/5 dark:text-slate-300"
          >
            🎤 <span className="max-w-[10rem] truncate">{currentDeviceLabel}</span>
            <ChevronIcon size={12} className={showDevices ? "rotate-180 transition" : "transition"} />
          </button>
          {showDevices && (
            <div
              className="absolute left-0 top-full z-30 mt-1 w-64 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg dark:border-white/10 dark:bg-slate-900"
              onMouseLeave={() => setShowDevices(false)}
            >
              <button
                type="button"
                onClick={() => chooseDevice("")}
                className={["block w-full px-3 py-2 text-left text-sm hover:bg-slate-100 dark:hover:bg-white/10", !deviceId ? "font-semibold" : ""].join(" ")}
              >
                System default
              </button>
              {devices.length === 0 && (
                <p className="px-3 py-2 text-xs text-slate-400">Grant mic access to see input devices.</p>
              )}
              {devices.map((d) => (
                <button
                  key={d.deviceId}
                  type="button"
                  onClick={() => chooseDevice(d.deviceId)}
                  className={["block w-full truncate px-3 py-2 text-left text-sm hover:bg-slate-100 dark:hover:bg-white/10", d.deviceId === deviceId ? "font-semibold text-fuchsia-600 dark:text-fuchsia-300" : ""].join(" ")}
                  title={d.label}
                >
                  {d.label || `Microphone (${d.deviceId.slice(0, 6)}…)`}
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="flex overflow-hidden rounded-full border border-slate-200 bg-white text-xs font-medium dark:border-white/10 dark:bg-white/5">
          <button
            type="button"
            onClick={() => chooseStyle("colon")}
            className={["px-3 py-1.5 transition", refStyle === "colon" ? "bg-gradient-to-r from-violet-600 to-fuchsia-500 text-white" : "text-slate-500"].join(" ")}
            title="e.g. Matthew 5:2"
          >
            5:2
          </button>
          <button
            type="button"
            onClick={() => chooseStyle("v")}
            className={["px-3 py-1.5 transition", refStyle === "v" ? "bg-gradient-to-r from-violet-600 to-fuchsia-500 text-white" : "text-slate-500"].join(" ")}
            title="e.g. Matthew 5v2"
          >
            5v2
          </button>
        </div>
      </div>

      <button
        type="button"
        onClick={listening ? stop : () => void start()}
        disabled={disabled}
        aria-pressed={listening}
        className={[
          "relative flex h-24 w-24 items-center justify-center rounded-full text-white shadow-xl transition active:scale-95 disabled:cursor-not-allowed disabled:opacity-50",
          listening
            ? "bg-gradient-to-br from-rose-500 to-rose-600"
            : "bg-gradient-to-br from-violet-600 via-fuchsia-500 to-pink-500 hover:brightness-110",
        ].join(" ")}
      >
        {listening && <span className="absolute h-full w-full animate-ping rounded-full bg-rose-500/40" />}
        <span className="relative">{listening ? <StopIcon size={30} /> : <MicIcon size={34} />}</span>
      </button>

      <p className="text-sm font-medium text-slate-500 dark:text-slate-400" aria-live="polite">
        {listening ? "Listening for scripture references…" : "Tap to start active listening"}
      </p>

      {listening && (
        <div className="flex items-center gap-2 text-xs text-slate-400">
          <span className="flex gap-0.5">
            {[0, 1, 2].map((i) => (
              <span key={i} className="h-1.5 w-1.5 animate-bounce rounded-full bg-fuchsia-500" style={{ animationDelay: `${i * 120}ms` }} />
            ))}
          </span>
          <span className="max-w-xs truncate italic">{interim || "…"}</span>
        </div>
      )}

      {error && <p className="text-sm text-rose-600">{error}</p>}

      {detections.length > 0 && (
        <div className="w-full">
          <p className="mb-3 text-xs font-medium uppercase tracking-widest text-slate-400">
            Detected scriptures ({detections.length})
          </p>
          <ul className="space-y-2">
            {detections.map((d) => (
              <li
                key={`${d.ref}-${d.at}`}
                className="animate-[fadeIn_0.3s_ease] rounded-xl border border-fuchsia-200/60 bg-gradient-to-br from-violet-50/70 to-fuchsia-50/60 p-3 text-left dark:border-fuchsia-400/20 dark:from-violet-500/10 dark:to-fuchsia-500/10"
              >
                <div className="flex items-center justify-between gap-2">
                  <button
                    type="button"
                    onClick={() => onOpenRef(d.ref)}
                    className="font-semibold text-slate-800 hover:text-fuchsia-600 dark:text-slate-100"
                  >
                    {d.normalized_ref || d.ref}{" "}
                    <span className="text-xs font-normal text-slate-400">{d.version}</span>
                  </button>
                  <div className="flex items-center gap-1">
                    {d.trigger && d.trigger !== "direct" && (
                      <span
                        className={[
                          "rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                          d.trigger === "cue_phrase" ? "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300" : "bg-slate-100 text-slate-500 dark:bg-white/5 dark:text-slate-400",
                        ].join(" ")}
                        title={d.trigger === "cue_phrase" ? "Triggered by a cue phrase" : "Triggered by semantic match"}
                      >
                        {d.trigger === "cue_phrase" ? "cue" : "semantic"}
                      </span>
                    )}
                    <button
                      type="button"
                      onClick={() => onOpenRef(d.ref)}
                      title="Open verse"
                      className="rounded-md p-1 text-slate-400 hover:text-fuchsia-600"
                    >
                      <BookIcon size={15} />
                    </button>
                  </div>
                </div>
                <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{d.text}</p>
                <p className="mt-1 text-[11px] italic text-slate-400">heard: “{d.snippet}”</p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

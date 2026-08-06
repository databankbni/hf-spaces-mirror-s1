"use client";

import { useEffect, useRef, useState } from "react";
import { MicIcon, StopIcon, Spinner } from "./Icons";

type Status = "idle" | "recording" | "processing" | "done" | "error";

const BARS = 28;

export default function MicButton({
  status,
  stream,
  disabled,
  onStart,
  onStop,
}: {
  status: Status;
  stream: MediaStream | null;
  disabled?: boolean;
  onStart: () => void;
  onStop: () => void;
}) {
  const recording = status === "recording";
  const processing = status === "processing";

  const [level, setLevel] = useState(0);
  const [bars, setBars] = useState<number[]>(() => new Array(BARS).fill(0.06));
  const rafRef = useRef<number | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const pressStart = useRef<number>(0);

  // Drive the live waveform from the mic stream while recording.
  useEffect(() => {
    if (!stream) {
      // Reset the visualizer when recording stops.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setLevel(0);
      setBars(new Array(BARS).fill(0.06));
      return;
    }
    const AC =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext })
        .webkitAudioContext;
    const ctx = new AC();
    ctxRef.current = ctx;
    const src = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 64;
    analyser.smoothingTimeConstant = 0.75;
    src.connect(analyser);
    const freq = new Uint8Array(analyser.frequencyBinCount);

    const tick = () => {
      analyser.getByteFrequencyData(freq);
      let sum = 0;
      const next = new Array(BARS).fill(0);
      for (let i = 0; i < BARS; i++) {
        const v = (freq[i % freq.length] ?? 0) / 255;
        next[i] = Math.max(0.06, v);
        sum += v;
      }
      setBars(next);
      setLevel(Math.min(1, (sum / BARS) * 1.6));
      rafRef.current = requestAnimationFrame(tick);
    };
    tick();

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      src.disconnect();
      ctx.close().catch(() => undefined);
      ctxRef.current = null;
    };
  }, [stream]);

  const haptic = () => navigator.vibrate?.(12);

  // Tap toggles; press-and-hold is push-to-talk (release to stop).
  const onPointerDown = () => {
    if (disabled || processing) return;
    pressStart.current = Date.now();
    if (!recording) {
      haptic();
      onStart();
    }
  };
  const onPointerUp = () => {
    if (disabled || processing) return;
    const held = Date.now() - pressStart.current;
    if (recording && held >= 300) {
      haptic();
      onStop(); // push-to-talk release
    } else if (recording && held < 300 && pressStart.current === 0) {
      haptic();
      onStop(); // tap while already recording -> stop
    }
  };
  // Separate tap handler for the "tap again to stop" case.
  const onClick = () => {
    if (disabled || processing) return;
    const held = Date.now() - pressStart.current;
    if (recording && held < 300) {
      pressStart.current = 0;
      haptic();
      onStop();
    }
  };

  const ringScale = 1 + level * 0.45;

  return (
    <div className="flex flex-col items-center gap-4">
      <div className="relative flex h-36 w-36 items-center justify-center">
        {/* Voice-reactive halo rings */}
        {recording && (
          <>
            <span
              className="absolute rounded-full bg-rose-500/20 transition-transform duration-75"
              style={{ width: 144, height: 144, transform: `scale(${ringScale})` }}
            />
            <span
              className="absolute rounded-full bg-rose-500/10 transition-transform duration-150"
              style={{ width: 144, height: 144, transform: `scale(${ringScale * 1.25})` }}
            />
          </>
        )}
        {!recording && !processing && (
          <span className="absolute h-28 w-28 animate-ping rounded-full bg-fuchsia-500/20" />
        )}

        <button
          type="button"
          onPointerDown={onPointerDown}
          onPointerUp={onPointerUp}
          onClick={onClick}
          disabled={disabled || processing}
          aria-label={recording ? "Stop recording" : "Start recording"}
          aria-pressed={recording}
          className={[
            "relative flex h-24 w-24 select-none items-center justify-center rounded-full text-white shadow-xl transition-transform active:scale-95 focus:outline-none focus-visible:ring-4 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-slate-900",
            disabled || processing
              ? "cursor-not-allowed bg-slate-400"
              : recording
                ? "bg-gradient-to-br from-rose-500 to-rose-600 focus-visible:ring-rose-300"
                : "bg-gradient-to-br from-violet-600 via-fuchsia-500 to-pink-500 shadow-fuchsia-500/30 hover:brightness-110 focus-visible:ring-fuchsia-300",
          ].join(" ")}
          style={recording ? { transform: `scale(${1 + level * 0.08})` } : undefined}
        >
          {processing ? <Spinner size={34} /> : recording ? <StopIcon size={30} /> : <MicIcon size={36} />}
        </button>
      </div>

      {/* Live waveform */}
      <div
        className="flex h-10 items-center justify-center gap-[3px]"
        aria-hidden
      >
        {bars.map((h, i) => (
          <span
            key={i}
            className={[
              "w-[3px] rounded-full transition-[height] duration-75",
              recording ? "bg-rose-500" : "bg-slate-300 dark:bg-white/15",
            ].join(" ")}
            style={{ height: `${Math.round((recording ? h : 0.12) * 38)}px` }}
          />
        ))}
      </div>
    </div>
  );
}

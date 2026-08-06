"use client";

import { useRef, useState } from "react";

interface Slide {
  emoji: string;
  title: string;
  body: string;
}

const SLIDES: Slide[] = [
  {
    emoji: "🎙️",
    title: "Speak, type, or ask",
    body: "Use your voice, type a phrase, or ask a full question — Verseo finds the closest scriptures across translations and languages.",
  },
  {
    emoji: "🔍",
    title: "Search across translations",
    body: "Switch between public-domain translations and scopes (Old/New Testament, specific books) to narrow your results.",
  },
  {
    emoji: "💬",
    title: "Grounded AI answers",
    body: "Ask a question in plain English and get an answer generated from real passages — with the verses it drew from shown alongside.",
  },
  {
    emoji: "⭐",
    title: "Save favorites & history",
    body: "Star verses to save them, and revisit your recent searches any time from the \"Saved & recent\" panel.",
  },
  {
    emoji: "🚀",
    title: "You're all set",
    body: "That's the essentials — jump in and start exploring Scripture.",
  },
];

export default function Onboarding({ onDone }: { onDone: () => void }) {
  const [index, setIndex] = useState(0);
  const touchStartX = useRef<number | null>(null);
  const last = index === SLIDES.length - 1;

  const next = () => (last ? onDone() : setIndex((i) => i + 1));
  const back = () => setIndex((i) => Math.max(0, i - 1));

  const onTouchStart = (e: React.TouchEvent) => {
    touchStartX.current = e.touches[0].clientX;
  };
  const onTouchEnd = (e: React.TouchEvent) => {
    if (touchStartX.current === null) return;
    const dx = e.changedTouches[0].clientX - touchStartX.current;
    touchStartX.current = null;
    if (dx < -40) next();
    else if (dx > 40) back();
  };

  const slide = SLIDES[index];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 px-5 backdrop-blur-sm">
      <div
        className="relative w-full max-w-md overflow-hidden rounded-3xl border border-white/60 bg-white p-8 shadow-2xl dark:border-white/10 dark:bg-slate-900"
        onTouchStart={onTouchStart}
        onTouchEnd={onTouchEnd}
      >
        <button
          type="button"
          onClick={onDone}
          className="absolute right-4 top-4 text-xs font-medium text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
        >
          Skip
        </button>

        <div className="flex flex-col items-center text-center">
          <div className="mb-5 flex h-20 w-20 items-center justify-center rounded-3xl bg-gradient-to-br from-violet-100 to-fuchsia-100 text-4xl dark:from-violet-500/15 dark:to-fuchsia-500/15">
            {slide.emoji}
          </div>
          <h2 className="text-xl font-bold">{slide.title}</h2>
          <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">{slide.body}</p>
        </div>

        <div className="mt-7 flex items-center justify-center gap-1.5">
          {SLIDES.map((_, i) => (
            <button
              key={i}
              type="button"
              aria-label={`Go to slide ${i + 1}`}
              onClick={() => setIndex(i)}
              className={`h-1.5 rounded-full transition-all ${
                i === index ? "w-6 bg-violet-500" : "w-1.5 bg-slate-200 dark:bg-white/15"
              }`}
            />
          ))}
        </div>

        <div className="mt-7 flex items-center justify-between gap-3">
          <button
            type="button"
            onClick={back}
            disabled={index === 0}
            className="rounded-xl px-4 py-2.5 text-sm font-medium text-slate-500 disabled:opacity-0 dark:text-slate-400"
          >
            Back
          </button>
          <button
            type="button"
            onClick={next}
            className="rounded-xl bg-gradient-to-r from-violet-600 to-fuchsia-500 px-6 py-2.5 text-sm font-medium text-white transition hover:brightness-110"
          >
            {last ? "Get started" : "Next"}
          </button>
        </div>
      </div>
    </div>
  );
}

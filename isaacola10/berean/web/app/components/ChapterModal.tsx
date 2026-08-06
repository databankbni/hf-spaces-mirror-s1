"use client";

import { useEffect, useRef, useState } from "react";
import type { ChapterResponse } from "../types";
import { CloseIcon, Spinner } from "./Icons";

const SIZES = ["text-sm", "text-[15px]", "text-lg", "text-xl"];

export default function ChapterModal({
  data,
  loading,
  highlightVerse,
  onClose,
}: {
  data: ChapterResponse | null;
  loading: boolean;
  highlightVerse?: number;
  onClose: () => void;
}) {
  const highlightRef = useRef<HTMLLIElement>(null);
  // Reading mode: font size + serif toggle for comfortable reading.
  const [sizeIdx, setSizeIdx] = useState(1);
  const [serif, setSerif] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    if (data && highlightRef.current) {
      highlightRef.current.scrollIntoView({ block: "center" });
    }
  }, [data]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-0 backdrop-blur-sm sm:items-center sm:p-6"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-t-3xl border border-slate-200 bg-white shadow-2xl sm:rounded-3xl dark:border-white/10 dark:bg-slate-900"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4 dark:border-white/10">
          <h2 className="text-lg font-semibold">
            {data ? `${data.book} ${data.chapter}` : "Loading chapter…"}
            {data && (
              <span className="ml-2 text-xs font-medium text-slate-400">
                {data.version}
              </span>
            )}
          </h2>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setSerif((s) => !s)}
              title="Toggle serif"
              className={[
                "rounded-md px-2 py-1 text-xs font-medium transition",
                serif ? "bg-indigo-100 text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-200" : "text-slate-500 hover:bg-slate-100 dark:hover:bg-white/10",
              ].join(" ")}
            >
              Serif
            </button>
            <button
              type="button"
              onClick={() => setSizeIdx((i) => Math.max(0, i - 1))}
              aria-label="Smaller text"
              className="rounded-md px-2 py-1 text-xs text-slate-500 transition hover:bg-slate-100 dark:hover:bg-white/10"
            >
              A−
            </button>
            <button
              type="button"
              onClick={() => setSizeIdx((i) => Math.min(SIZES.length - 1, i + 1))}
              aria-label="Larger text"
              className="rounded-md px-2 py-1 text-sm text-slate-500 transition hover:bg-slate-100 dark:hover:bg-white/10"
            >
              A+
            </button>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="ml-1 rounded-full p-1.5 text-slate-500 transition hover:bg-slate-100 dark:hover:bg-white/10"
            >
              <CloseIcon />
            </button>
          </div>
        </div>

        <div className="overflow-y-auto px-5 py-4">
          {loading && (
            <div className="flex items-center justify-center gap-2 py-12 text-slate-500">
              <Spinner /> Loading…
            </div>
          )}
          {data && (
            <ol className={["space-y-2 leading-relaxed", SIZES[sizeIdx], serif ? "font-serif" : ""].join(" ")}>
              {data.verses.map((v) => {
                const isHit = v.verse === highlightVerse;
                return (
                  <li
                    key={v.verse}
                    ref={isHit ? highlightRef : undefined}
                    className={[
                      "rounded-lg px-3 py-2",
                      isHit
                        ? "bg-indigo-50 ring-1 ring-indigo-200 dark:bg-indigo-500/15 dark:ring-indigo-400/30"
                        : "",
                    ].join(" ")}
                  >
                    <sup className="mr-1 text-xs font-semibold text-indigo-500">
                      {v.verse}
                    </sup>
                    <span className="text-slate-700 dark:text-slate-200">
                      {v.text}
                    </span>
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      </div>
    </div>
  );
}

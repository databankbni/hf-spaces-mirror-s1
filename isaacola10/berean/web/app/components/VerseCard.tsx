"use client";

import { useState } from "react";
import type { Confidence, VerseRef, VerseResult } from "../types";
import { highlightParts, refToSlug } from "../lib/bible";
import {
  BookIcon,
  ChevronIcon,
  CopyIcon,
  ShareIcon,
  StarIcon,
} from "./Icons";

const CONFIDENCE_STYLES: Record<Confidence, string> = {
  high: "bg-emerald-100 text-emerald-800 ring-emerald-600/20 dark:bg-emerald-500/15 dark:text-emerald-300 dark:ring-emerald-400/20",
  medium:
    "bg-amber-100 text-amber-800 ring-amber-600/20 dark:bg-amber-500/15 dark:text-amber-300 dark:ring-amber-400/20",
  low: "bg-rose-100 text-rose-800 ring-rose-600/20 dark:bg-rose-500/15 dark:text-rose-300 dark:ring-rose-400/20",
};

export default function VerseCard({
  result,
  top,
  query,
  isFavorite,
  onToggleFavorite,
  onShare,
  onReadChapter,
  onOpenRef,
}: {
  result: VerseResult;
  top: boolean;
  query: string;
  isFavorite: boolean;
  onToggleFavorite: () => void;
  onShare: () => void;
  onReadChapter: () => void;
  onOpenRef: (ref: string) => void;
}) {
  const [copied, setCopied] = useState(false);
  const others = result.translations.filter((t) => t.version !== result.version);
  const parts = highlightParts(result.text, query);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(`${result.text} — ${result.ref} (${result.version})`);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <li
      className={[
        "rounded-2xl border p-5 transition",
        top
          ? "border-fuchsia-300/60 bg-gradient-to-br from-violet-50/80 to-fuchsia-50/70 shadow-md shadow-fuchsia-500/10 backdrop-blur-xl dark:border-fuchsia-400/30 dark:from-violet-500/10 dark:to-fuchsia-500/10"
          : "border-white/60 bg-white/70 backdrop-blur-xl hover:border-slate-300 dark:border-white/10 dark:bg-white/5 dark:hover:border-white/20",
      ].join(" ")}
    >
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {top && (
            <span className="rounded-full bg-gradient-to-br from-violet-600 to-fuchsia-500 px-2 py-0.5 text-xs font-semibold text-white">
              {result.exact ? "Exact match" : "Best match"}
            </span>
          )}
          <h2 className={["font-semibold", top ? "text-xl" : "text-base"].join(" ")}>
            {result.ref}
          </h2>
          <span
            className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600 ring-1 ring-inset ring-slate-200 dark:bg-white/10 dark:text-slate-200 dark:ring-white/10"
            title={`${result.version} · ${result.languageName}`}
          >
            {result.version}
          </span>
        </div>
        <span
          className={[
            "shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset",
            CONFIDENCE_STYLES[result.confidence],
          ].join(" ")}
        >
          {result.confidence}
        </span>
      </div>

      <div className="mb-3 flex items-center gap-2">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-200 dark:bg-white/10">
          <div
            className={
              top
                ? "h-full rounded-full bg-gradient-to-r from-violet-500 to-fuchsia-500"
                : "h-full rounded-full bg-slate-400 dark:bg-slate-500"
            }
            style={{ width: `${Math.max(2, result.relevance)}%` }}
          />
        </div>
        <span className="w-10 text-right text-xs font-medium tabular-nums text-slate-500 dark:text-slate-400">
          {result.relevance}%
        </span>
      </div>

      <p className={["leading-relaxed text-slate-700 dark:text-slate-200", top ? "text-lg" : "text-sm"].join(" ")}>
        {parts.map((p, i) =>
          p.hit ? (
            <mark
              key={i}
              className="rounded bg-amber-200/70 px-0.5 text-inherit dark:bg-amber-400/25"
            >
              {p.text}
            </mark>
          ) : (
            <span key={i}>{p.text}</span>
          ),
        )}
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
        <ActionButton onClick={copy} label={copied ? "Copied!" : "Copy"}>
          <CopyIcon size={14} />
        </ActionButton>
        <ActionButton onClick={onShare} label="Share">
          <ShareIcon size={14} />
        </ActionButton>
        <a
          href={`/verse/${refToSlug(result.ref)}`}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1 font-medium text-slate-600 transition hover:bg-slate-200 dark:bg-white/5 dark:text-slate-300 dark:hover:bg-white/10"
        >
          <ShareIcon size={14} /> Card
        </a>
        <ActionButton onClick={onReadChapter} label="Chapter">
          <BookIcon size={14} />
        </ActionButton>
        <ActionButton onClick={onToggleFavorite} label={isFavorite ? "Saved" : "Save"} active={isFavorite}>
          <StarIcon size={14} filled={isFavorite} />
        </ActionButton>
      </div>

      {/* Cross-references + similar verses (lazy) */}
      <div className="mt-3 space-y-2">
        <RefSection
          label="Cross-references"
          endpoint={`/api/crossrefs?book_no=${result.book_no}&chapter=${result.chapter}&verse=${result.verse}`}
          pick={(d) => (d as { refs: VerseRef[] }).refs}
          onOpenRef={onOpenRef}
        />
        <RefSection
          label="Similar verses"
          endpoint={`/api/similar?book_no=${result.book_no}&chapter=${result.chapter}&verse=${result.verse}`}
          pick={(d) => (d as { results: VerseRef[] }).results}
          onOpenRef={onOpenRef}
        />
      </div>

      {others.length > 0 && (
        <details className="group mt-3">
          <summary className="flex cursor-pointer select-none items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-500 dark:text-indigo-300 dark:hover:text-indigo-200">
            <ChevronIcon className="transition group-open:rotate-180" />
            Compare {others.length} other translation{others.length > 1 ? "s" : ""}
          </summary>
          <ul className="mt-3 space-y-3 border-t border-slate-200 pt-3 dark:border-white/10">
            {others.map((t) => (
              <li key={t.version}>
                <span
                  className="mb-1 inline-block rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-500 dark:bg-white/5 dark:text-slate-400"
                  title={`${t.version} · ${t.languageName}`}
                >
                  {t.version}
                </span>
                <p className="text-sm leading-relaxed text-slate-600 dark:text-slate-300">{t.text}</p>
              </li>
            ))}
          </ul>
        </details>
      )}
    </li>
  );
}

function RefSection({
  label,
  endpoint,
  pick,
  onOpenRef,
}: {
  label: string;
  endpoint: string;
  pick: (data: unknown) => VerseRef[];
  onOpenRef: (ref: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<VerseRef[] | null>(null);
  const [loading, setLoading] = useState(false);

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && items === null) {
      setLoading(true);
      try {
        const data = await (await fetch(endpoint)).json();
        setItems(pick(data));
      } catch {
        setItems([]);
      } finally {
        setLoading(false);
      }
    }
  };

  return (
    <details open={open}>
      <summary
        onClick={(e) => {
          e.preventDefault();
          void toggle();
        }}
        className="flex cursor-pointer select-none items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-500 dark:text-indigo-300 dark:hover:text-indigo-200"
      >
        <ChevronIcon className={open ? "rotate-180 transition" : "transition"} />
        {label}
      </summary>
      {open && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {loading && <span className="text-xs text-slate-400">Loading…</span>}
          {items?.length === 0 && !loading && (
            <span className="text-xs text-slate-400">None found.</span>
          )}
          {items?.map((v) => (
            <button
              key={`${v.ref}-${v.version}`}
              type="button"
              onClick={() => onOpenRef(v.ref)}
              title={v.text}
              className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-600 transition hover:border-indigo-300 hover:text-indigo-600 dark:border-white/10 dark:bg-white/5 dark:text-slate-300 dark:hover:border-indigo-400/40"
            >
              {v.ref}
            </button>
          ))}
        </div>
      )}
    </details>
  );
}

function ActionButton({
  onClick,
  label,
  active = false,
  children,
}: {
  onClick: () => void;
  label: string;
  active?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-medium transition",
        active
          ? "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300"
          : "bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-white/5 dark:text-slate-300 dark:hover:bg-white/10",
      ].join(" ")}
    >
      {children}
      {label}
    </button>
  );
}

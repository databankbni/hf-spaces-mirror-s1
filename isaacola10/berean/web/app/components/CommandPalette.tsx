"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Topic } from "../types";
import { SearchIcon, SparkleIcon, BookIcon } from "./Icons";

type Item = { id: string; label: string; hint: string; icon: React.ReactNode; run: () => void };

export default function CommandPalette({
  open,
  onClose,
  topics,
  onRun,
}: {
  open: boolean;
  onClose: () => void;
  topics: Topic[];
  onRun: (query: string, mode: "type" | "ask") => void;
}) {
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      // Reset the palette each time it opens.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setQ("");
      setActive(0);
      setTimeout(() => inputRef.current?.focus(), 30);
    }
  }, [open]);

  const items: Item[] = useMemo(() => {
    const trimmed = q.trim();
    const list: Item[] = [];
    if (trimmed) {
      list.push({
        id: "search",
        label: `Search for “${trimmed}”`,
        hint: "Find verse",
        icon: <SearchIcon size={16} />,
        run: () => onRun(trimmed, "type"),
      });
      list.push({
        id: "ask",
        label: `Ask “${trimmed}”`,
        hint: "Q&A",
        icon: <SparkleIcon size={16} />,
        run: () => onRun(trimmed, "ask"),
      });
    }
    const matched = topics.filter(
      (t) => !trimmed || t.label.toLowerCase().includes(trimmed.toLowerCase()),
    );
    for (const t of matched.slice(0, trimmed ? 4 : 8)) {
      list.push({
        id: `topic-${t.label}`,
        label: `${t.emoji} ${t.label}`,
        hint: "Topic",
        icon: <BookIcon size={16} />,
        run: () => onRun(t.query, "type"),
      });
    }
    return list;
  }, [q, topics, onRun]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowDown") {
        e.preventDefault();
        setActive((a) => Math.min(a + 1, items.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActive((a) => Math.max(a - 1, 0));
      } else if (e.key === "Enter") {
        items[active]?.run();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, items, active, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 pt-[12vh] backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-white/10 dark:bg-slate-900"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-slate-200 px-4 dark:border-white/10">
          <SearchIcon className="text-slate-400" />
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setActive(0);
            }}
            placeholder="Search a verse, topic, or ask a question…"
            className="w-full bg-transparent py-3.5 text-[15px] outline-none placeholder:text-slate-400"
          />
          <kbd className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-400 dark:bg-white/10">
            esc
          </kbd>
        </div>
        <ul className="max-h-80 overflow-y-auto p-2">
          {items.length === 0 && (
            <li className="px-3 py-6 text-center text-sm text-slate-400">
              Type to search verses or ask a question.
            </li>
          )}
          {items.map((it, i) => (
            <li key={it.id}>
              <button
                type="button"
                onMouseEnter={() => setActive(i)}
                onClick={it.run}
                className={[
                  "flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition",
                  i === active
                    ? "bg-indigo-50 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-200"
                    : "text-slate-700 dark:text-slate-200",
                ].join(" ")}
              >
                <span className="text-slate-400">{it.icon}</span>
                <span className="flex-1 truncate">{it.label}</span>
                <span className="text-[10px] uppercase tracking-wide text-slate-400">
                  {it.hint}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

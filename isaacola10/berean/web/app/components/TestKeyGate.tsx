"use client";

import { useState } from "react";
import { testKeyStore } from "../lib/storage";

// Full-screen gate shown when the app is in test mode and the visitor has no
// (or an invalid) test key. Validates the key against /api/test/access and
// stores it locally on success.
export default function TestKeyGate({ onUnlocked }: { onUnlocked: () => void }) {
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = key.trim();
    if (!trimmed) return;
    setError(null);
    setChecking(true);
    try {
      const res = await fetch("/api/test/access", {
        method: "POST",
        headers: { "X-Test-Key": trimmed },
      });
      const data = await res.json();
      if (!res.ok || !data.valid) {
        setError(data.detail ?? "Invalid test key.");
        return;
      }
      testKeyStore.set(trimmed);
      onUnlocked();
    } catch {
      setError("Could not reach the server. Try again.");
    } finally {
      setChecking(false);
    }
  };

  return (
    <main className="flex flex-1 items-center justify-center px-5 py-16">
      <div className="w-full max-w-md rounded-3xl border border-white/60 bg-white/70 p-8 shadow-lg backdrop-blur-xl dark:border-white/10 dark:bg-white/5">
        <div className="mb-4 inline-flex items-center gap-2 rounded-full bg-amber-100 px-3 py-1 text-xs font-medium text-amber-800 dark:bg-amber-500/15 dark:text-amber-300">
          🧪 Closed beta
        </div>
        <h1 className="mb-1 bg-gradient-to-r from-violet-600 via-fuchsia-500 to-pink-500 bg-clip-text text-3xl font-bold tracking-tight text-transparent">
          Verseo
        </h1>
        <p className="mb-6 text-sm text-slate-500 dark:text-slate-400">
          Verseo is in test mode. Enter your test key to continue.
        </p>
        <form onSubmit={submit} className="flex flex-col gap-3">
          <input
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="vrs-…"
            autoFocus
            className="rounded-xl border border-slate-200 bg-white px-4 py-2.5 font-mono outline-none focus:border-violet-400 focus:ring-2 focus:ring-violet-400/30 dark:border-white/10 dark:bg-black/20"
          />
          <button
            type="submit"
            disabled={checking || !key.trim()}
            className="rounded-xl bg-gradient-to-r from-violet-600 to-fuchsia-500 px-4 py-2.5 font-medium text-white transition hover:brightness-110 disabled:opacity-50"
          >
            {checking ? "Checking…" : "Enter"}
          </button>
          {error && <p className="text-sm text-rose-600">{error}</p>}
          <p className="mt-2 text-xs text-slate-400">
            Don&apos;t have a key? Ask the admin for one.
          </p>
        </form>
      </div>
    </main>
  );
}

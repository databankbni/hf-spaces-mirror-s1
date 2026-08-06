"use client";

import { useAuth } from "@clerk/nextjs";
import Link from "next/link";
import { useEffect, useState } from "react";
import type { Sermon, SermonPoint } from "../types";
import { Spinner, BookIcon } from "../components/Icons";

type ArcTemplateId = "classic" | "expository" | "blank";

const ARC_TEMPLATES: Record<ArcTemplateId, { label: string; blurb: string; beats: string[] }> = {
  classic: {
    label: "Classic Arc",
    blurb: "Hook → tension → turning point → application → call to action.",
    beats: ["Hook", "Tension", "Turning Point", "Application", "Call to Action"],
  },
  expository: {
    label: "Expository",
    blurb: "Walk through a passage point by point.",
    beats: ["Introduction", "Point 1", "Point 2", "Point 3", "Conclusion"],
  },
  blank: { label: "Blank outline", blurb: "Start from nothing and add your own points.", beats: [] },
};

function emptyPoint(beat: string): SermonPoint {
  return { beat, title: "", notes: "", verse_refs: [] };
}

export default function StudioPage() {
  const { isLoaded, isSignedIn, getToken } = useAuth();
  const [plan, setPlan] = useState<string | null>(null);
  const [sermons, setSermons] = useState<Sermon[] | null>(null);
  const [title, setTitle] = useState("");
  const [template, setTemplate] = useState<ArcTemplateId>("classic");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoaded) return;
    if (!isSignedIn) {
      window.location.replace("/sign-in?redirect_url=/studio");
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const token = await getToken();
        const me = await (
          await fetch("/api/me", { headers: { Authorization: `Bearer ${token}` } })
        ).json();
        if (cancelled) return;
        const userPlan = me.user?.plan ?? "free";
        setPlan(userPlan);
        if (userPlan !== "speaker") return;
        const data = await (
          await fetch("/api/sermons", { headers: { Authorization: `Bearer ${token}` } })
        ).json();
        if (!cancelled) setSermons(data.sermons ?? []);
      } catch {
        if (!cancelled) setPlan("free");
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoaded, isSignedIn]);

  const createSermon = async () => {
    if (!title.trim()) {
      setError("Give your sermon a title first.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const token = await getToken();
      const res = await fetch("/api/sermons", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          title: title.trim(),
          points: ARC_TEMPLATES[template].beats.map(emptyPoint),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? "Could not create sermon");
      window.location.assign(`/studio/${data.sermon.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create sermon");
      setBusy(false);
    }
  };

  if (!isLoaded || plan === null) {
    return (
      <main className="flex flex-1 items-center justify-center py-24">
        <Spinner size={22} />
      </main>
    );
  }

  if (plan !== "speaker") {
    return (
      <main className="mx-auto w-full max-w-lg flex-1 px-5 py-16 text-center">
        <div className="mb-5 flex justify-center text-violet-500">
          <BookIcon size={40} />
        </div>
        <h1 className="text-2xl font-bold">Sermon Studio</h1>
        <p className="mt-3 text-slate-500 dark:text-slate-400">
          Plan out a sermon with a storytelling arc and link the passages that
          back each point — built for the Speaker plan.
        </p>
        <Link
          href="/pricing"
          className="mt-6 inline-block rounded-xl bg-gradient-to-r from-violet-600 to-fuchsia-500 px-5 py-2.5 text-sm font-medium text-white transition hover:brightness-110"
        >
          Upgrade to Speaker
        </Link>
      </main>
    );
  }

  return (
    <main className="mx-auto w-full max-w-2xl flex-1 px-5 py-12">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Sermon Studio</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Your saved outlines — storytelling arc + linked passages.
          </p>
        </div>
        <Link href="/" className="text-sm text-slate-500 hover:underline dark:text-slate-400">
          ← Back to Verseo
        </Link>
      </div>

      <div className="mb-8 rounded-3xl border border-white/60 bg-white/70 p-6 backdrop-blur-xl dark:border-white/10 dark:bg-white/5">
        <h2 className="mb-3 text-sm font-semibold">New sermon</h2>
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="e.g. The Prodigal Son"
          className="mb-3 w-full rounded-xl border border-slate-200 bg-white px-4 py-2.5 outline-none focus:border-violet-400 focus:ring-2 focus:ring-violet-400/30 dark:border-white/10 dark:bg-black/20"
        />
        <div className="mb-4 grid gap-2 sm:grid-cols-3">
          {(Object.keys(ARC_TEMPLATES) as ArcTemplateId[]).map((id) => (
            <button
              key={id}
              type="button"
              onClick={() => setTemplate(id)}
              className={`rounded-xl border p-3 text-left text-xs transition ${
                template === id
                  ? "border-violet-400 bg-violet-50 dark:border-violet-400/50 dark:bg-violet-500/10"
                  : "border-slate-200 hover:border-slate-300 dark:border-white/10"
              }`}
            >
              <div className="font-semibold">{ARC_TEMPLATES[id].label}</div>
              <div className="mt-0.5 text-slate-500 dark:text-slate-400">{ARC_TEMPLATES[id].blurb}</div>
            </button>
          ))}
        </div>
        {error && <p className="mb-3 text-sm text-rose-600">{error}</p>}
        <button
          type="button"
          onClick={() => void createSermon()}
          disabled={busy}
          className="rounded-xl bg-gradient-to-r from-violet-600 to-fuchsia-500 px-5 py-2.5 text-sm font-medium text-white transition hover:brightness-110 disabled:opacity-50"
        >
          {busy ? "Creating…" : "Create sermon"}
        </button>
      </div>

      <h2 className="mb-3 text-sm font-semibold text-slate-500 dark:text-slate-400">Your sermons</h2>
      {sermons === null ? (
        <div className="flex justify-center py-8">
          <Spinner size={20} />
        </div>
      ) : sermons.length === 0 ? (
        <p className="text-sm text-slate-500 dark:text-slate-400">
          No sermons yet — create your first one above.
        </p>
      ) : (
        <ul className="space-y-2">
          {sermons.map((s) => (
            <li key={s.id}>
              <Link
                href={`/studio/${s.id}`}
                className="block rounded-2xl border border-slate-200 bg-white p-4 transition hover:border-violet-300 dark:border-white/10 dark:bg-white/5"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="font-medium">{s.title}</span>
                  <span className="text-xs text-slate-400">{s.points.length} points</span>
                </div>
                {s.description && (
                  <p className="mt-1 truncate text-sm text-slate-500 dark:text-slate-400">{s.description}</p>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}

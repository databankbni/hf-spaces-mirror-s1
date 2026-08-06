"use client";

import { useAuth } from "@clerk/nextjs";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import type { PredictResponse, Sermon, SermonPoint, SermonVerseLink } from "../../types";
import { Spinner, CloseIcon, SearchIcon } from "../../components/Icons";

function VerseLinker({ onAdd }: { onAdd: (v: SermonVerseLink) => void }) {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<SermonVerseLink | null>(null);
  const [busy, setBusy] = useState(false);
  const [notFound, setNotFound] = useState(false);

  const search = async () => {
    if (!query.trim()) return;
    setBusy(true);
    setNotFound(false);
    setResult(null);
    try {
      const data: PredictResponse = await (
        await fetch("/api/search", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: query.trim(), top_k: 1 }),
        })
      ).json();
      const top = data.results?.[0];
      if (top) setResult({ ref: top.ref, version: top.version, text: top.text });
      else setNotFound(true);
    } catch {
      setNotFound(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-2">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void search();
        }}
        className="flex items-center gap-2"
      >
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Link a passage — e.g. John 3:16 or the lord is my shepherd"
          className="flex-1 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm outline-none focus:border-violet-400 focus:ring-2 focus:ring-violet-400/30 dark:border-white/10 dark:bg-black/20"
        />
        <button
          type="submit"
          disabled={busy}
          className="rounded-lg border border-slate-200 p-1.5 text-slate-500 transition hover:border-slate-300 disabled:opacity-50 dark:border-white/10"
        >
          {busy ? <Spinner size={14} /> : <SearchIcon size={14} />}
        </button>
      </form>
      {notFound && <p className="mt-1 text-xs text-rose-500">No matching verse found.</p>}
      {result && (
        <div className="mt-2 flex items-start justify-between gap-2 rounded-lg border border-violet-200 bg-violet-50 p-2 text-xs dark:border-violet-400/20 dark:bg-violet-500/10">
          <div>
            <span className="font-semibold">{result.ref}</span>{" "}
            <span className="text-slate-400">({result.version})</span>
            <p className="mt-0.5 text-slate-600 dark:text-slate-300">{result.text}</p>
          </div>
          <button
            type="button"
            onClick={() => {
              onAdd(result);
              setResult(null);
              setQuery("");
            }}
            className="shrink-0 rounded-md bg-violet-600 px-2 py-1 font-medium text-white"
          >
            Add
          </button>
        </div>
      )}
    </div>
  );
}

export default function SermonEditorPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { isLoaded, isSignedIn, getToken } = useAuth();
  const [sermon, setSermon] = useState<Sermon | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [points, setPoints] = useState<SermonPoint[]>([]);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const loaded = useRef(false);

  useEffect(() => {
    if (!isLoaded || loaded.current) return;
    if (!isSignedIn) {
      window.location.replace(`/sign-in?redirect_url=/studio/${id}`);
      return;
    }
    loaded.current = true;
    void (async () => {
      try {
        const token = await getToken();
        const res = await fetch(`/api/sermons/${id}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) throw new Error("Sermon not found");
        const data = await res.json();
        setSermon(data.sermon);
        setTitle(data.sermon.title);
        setDescription(data.sermon.description ?? "");
        setPoints(data.sermon.points);
      } catch {
        setError("Couldn't load this sermon.");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, isLoaded, isSignedIn]);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const token = await getToken();
      const res = await fetch(`/api/sermons/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ title, description, points }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? "Could not save");
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save");
    } finally {
      setSaving(false);
    }
  };

  const archive = async () => {
    if (!window.confirm("Archive this sermon? You can still find it later if needed.")) return;
    try {
      const token = await getToken();
      await fetch(`/api/sermons/${id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      router.push("/studio");
    } catch {
      setError("Could not archive this sermon.");
    }
  };

  const updatePoint = (i: number, patch: Partial<SermonPoint>) => {
    setPoints((pts) => pts.map((p, idx) => (idx === i ? { ...p, ...patch } : p)));
  };
  const removePoint = (i: number) => setPoints((pts) => pts.filter((_, idx) => idx !== i));
  const movePoint = (i: number, dir: -1 | 1) => {
    setPoints((pts) => {
      const j = i + dir;
      if (j < 0 || j >= pts.length) return pts;
      const next = [...pts];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  };
  const addPoint = () => setPoints((pts) => [...pts, { beat: "", title: "", notes: "", verse_refs: [] }]);
  const addVerse = (i: number, v: SermonVerseLink) =>
    updatePoint(i, { verse_refs: [...points[i].verse_refs, v] });
  const removeVerse = (i: number, vi: number) =>
    updatePoint(i, { verse_refs: points[i].verse_refs.filter((_, idx) => idx !== vi) });

  if (!sermon && !error) {
    return (
      <main className="flex flex-1 items-center justify-center py-24">
        <Spinner size={22} />
      </main>
    );
  }

  if (!sermon) {
    return (
      <main className="mx-auto w-full max-w-lg flex-1 px-5 py-16 text-center">
        <p className="text-slate-500">{error}</p>
        <Link href="/studio" className="mt-4 inline-block text-violet-600 hover:underline">
          ← Back to Sermon Studio
        </Link>
      </main>
    );
  }

  return (
    <main className="mx-auto w-full max-w-2xl flex-1 px-5 py-12">
      <div className="mb-6 flex items-center justify-between">
        <Link href="/studio" className="text-sm text-slate-500 hover:underline dark:text-slate-400">
          ← Sermon Studio
        </Link>
        <div className="flex items-center gap-2">
          {saved && <span className="text-xs text-emerald-600">Saved</span>}
          <button
            type="button"
            onClick={() => void save()}
            disabled={saving}
            className="rounded-lg bg-gradient-to-r from-violet-600 to-fuchsia-500 px-4 py-1.5 text-sm font-medium text-white transition hover:brightness-110 disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save"}
          </button>
          <button
            type="button"
            onClick={() => void archive()}
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-500 transition hover:border-rose-300 hover:text-rose-600 dark:border-white/10"
          >
            Archive
          </button>
        </div>
      </div>

      {error && <p className="mb-4 text-sm text-rose-600">{error}</p>}

      <input
        type="text"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Sermon title"
        className="mb-2 w-full border-none bg-transparent text-2xl font-bold outline-none placeholder:text-slate-300"
      />
      <textarea
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="One-line summary of what this sermon is about…"
        rows={1}
        className="mb-8 w-full resize-none border-none bg-transparent text-sm text-slate-500 outline-none placeholder:text-slate-400 dark:text-slate-400"
      />

      <div className="space-y-4">
        {points.map((p, i) => (
          <div
            key={i}
            className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-white/10 dark:bg-white/5"
          >
            <div className="mb-2 flex items-center gap-2">
              <input
                type="text"
                value={p.beat}
                onChange={(e) => updatePoint(i, { beat: e.target.value })}
                placeholder="Beat (e.g. Hook)"
                className="w-40 rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs font-semibold uppercase tracking-wide text-violet-600 outline-none focus:border-violet-400 dark:border-white/10 dark:bg-black/20 dark:text-violet-300"
              />
              <div className="ml-auto flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => movePoint(i, -1)}
                  disabled={i === 0}
                  aria-label="Move up"
                  className="rounded-md px-1.5 py-0.5 text-slate-400 hover:bg-slate-100 disabled:opacity-30 dark:hover:bg-white/10"
                >
                  ↑
                </button>
                <button
                  type="button"
                  onClick={() => movePoint(i, 1)}
                  disabled={i === points.length - 1}
                  aria-label="Move down"
                  className="rounded-md px-1.5 py-0.5 text-slate-400 hover:bg-slate-100 disabled:opacity-30 dark:hover:bg-white/10"
                >
                  ↓
                </button>
                <button
                  type="button"
                  onClick={() => removePoint(i)}
                  aria-label="Remove point"
                  className="rounded-md p-1 text-slate-400 hover:bg-rose-50 hover:text-rose-600 dark:hover:bg-rose-500/10"
                >
                  <CloseIcon size={14} />
                </button>
              </div>
            </div>
            <input
              type="text"
              value={p.title}
              onChange={(e) => updatePoint(i, { title: e.target.value })}
              placeholder="Point title"
              className="mb-2 w-full border-none bg-transparent font-medium outline-none placeholder:text-slate-300"
            />
            <textarea
              value={p.notes}
              onChange={(e) => updatePoint(i, { notes: e.target.value })}
              placeholder="Notes for this point…"
              rows={2}
              className="mb-2 w-full resize-none rounded-lg border border-slate-100 bg-slate-50 p-2 text-sm outline-none focus:border-violet-300 dark:border-white/5 dark:bg-black/10"
            />
            {p.verse_refs.length > 0 && (
              <div className="mb-2 flex flex-wrap gap-1.5">
                {p.verse_refs.map((v, vi) => (
                  <span
                    key={vi}
                    className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium dark:bg-white/10"
                    title={v.text}
                  >
                    {v.ref}
                    <button
                      type="button"
                      onClick={() => removeVerse(i, vi)}
                      aria-label={`Remove ${v.ref}`}
                      className="text-slate-400 hover:text-rose-600"
                    >
                      <CloseIcon size={10} />
                    </button>
                  </span>
                ))}
              </div>
            )}
            <VerseLinker onAdd={(v) => addVerse(i, v)} />
          </div>
        ))}
      </div>

      <button
        type="button"
        onClick={addPoint}
        className="mt-4 w-full rounded-2xl border border-dashed border-slate-300 py-3 text-sm text-slate-500 transition hover:border-violet-300 hover:text-violet-600 dark:border-white/10"
      >
        + Add point
      </button>
    </main>
  );
}

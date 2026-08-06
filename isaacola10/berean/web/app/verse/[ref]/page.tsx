import type { Metadata } from "next";
import Link from "next/link";
import type { PredictResponse, VerseResult } from "../../types";

const PYTHON_API_URL = process.env.PYTHON_API_URL ?? "http://127.0.0.1:8000";

async function lookup(slug: string): Promise<VerseResult | null> {
  const query = decodeURIComponent(slug).replace(/-/g, " ");
  try {
    const res = await fetch(`${PYTHON_API_URL}/api/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: query, top_k: 1 }),
      cache: "no-store",
    });
    const data: PredictResponse = await res.json();
    return data.results?.[0] ?? null;
  } catch {
    return null;
  }
}

export async function generateMetadata(props: {
  params: Promise<{ ref: string }>;
}): Promise<Metadata> {
  const { ref } = await props.params;
  const v = await lookup(ref);
  if (!v) return { title: "Verse — Verseo" };
  const desc = v.text.length > 180 ? v.text.slice(0, 177) + "…" : v.text;
  return {
    title: `${v.ref} (${v.version}) — Verseo`,
    description: desc,
    openGraph: { title: `${v.ref} · ${v.version}`, description: desc },
    twitter: { card: "summary_large_image", title: `${v.ref} · ${v.version}`, description: desc },
  };
}

export default async function VersePage(props: {
  params: Promise<{ ref: string }>;
}) {
  const { ref } = await props.params;
  const v = await lookup(ref);

  return (
    <main className="flex flex-1 flex-col items-center justify-center px-5 py-16">
      {v ? (
        <article className="w-full max-w-xl rounded-3xl border border-slate-200 bg-white p-8 shadow-sm dark:border-white/10 dark:bg-white/5">
          <div className="mb-4 flex items-center gap-2">
            <h1 className="text-2xl font-bold">{v.ref}</h1>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600 dark:bg-white/10 dark:text-slate-300">
              {v.version}
            </span>
          </div>
          <p className="text-xl leading-relaxed text-slate-800 dark:text-slate-100">
            {v.text}
          </p>
          {v.translations.length > 1 && (
            <div className="mt-6 space-y-3 border-t border-slate-200 pt-5 dark:border-white/10">
              {v.translations
                .filter((t) => t.version !== v.version)
                .map((t) => (
                  <div key={t.version}>
                    <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                      {t.version}
                    </span>
                    <p className="text-sm text-slate-600 dark:text-slate-300">{t.text}</p>
                  </div>
                ))}
            </div>
          )}
          <Link
            href={`/?mode=type&q=${encodeURIComponent(v.ref)}`}
            className="mt-6 inline-block rounded-full bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-700"
          >
            Open in Verseo →
          </Link>
        </article>
      ) : (
        <div className="text-center">
          <h1 className="text-2xl font-bold">Verse not found</h1>
          <Link href="/" className="mt-4 inline-block text-indigo-600 hover:underline">
            Back to Verseo
          </Link>
        </div>
      )}
    </main>
  );
}

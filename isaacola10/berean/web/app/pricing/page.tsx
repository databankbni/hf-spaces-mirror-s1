"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@clerk/nextjs";

const TIERS = [
  {
    id: "free", name: "Free", price: "$0",
    blurb: "Everything you need to find scripture.",
    features: ["Speak, type & listen search", "All translations & languages", "Cross-references & similar verses", "Limited AI questions"],
    cta: "Current plan",
  },
  {
    id: "plus", name: "Plus", price: "$6/mo",
    blurb: "For daily study.",
    features: ["Everything in Free", "Unlimited AI questions", "Priority processing", "Early access to new features"],
    cta: "Upgrade to Plus",
  },
  {
    id: "speaker", name: "Speaker", price: "$19/mo",
    blurb: "For pastors & teachers.",
    features: ["Everything in Plus", "Sermon Studio — storytelling arc & passage linking", "Live service tools", "Priority support"],
    cta: "Upgrade to Speaker",
  },
] as const;

export default function PricingPage() {
  const { isSignedIn, getToken } = useAuth();
  const [plan, setPlan] = useState<string>("free");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isSignedIn) return;
    let cancelled = false;
    void (async () => {
      try {
        const token = await getToken();
        const me = await (
          await fetch("/api/me", { headers: { Authorization: `Bearer ${token}` } })
        ).json();
        if (!cancelled && me.user?.plan) setPlan(me.user.plan);
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
    // getToken intentionally omitted — see AuthGate.tsx for why including it
    // caused an infinite refetch loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSignedIn]);

  const checkout = async (tier: string) => {
    setError(null);
    if (!isSignedIn) {
      window.location.assign("/sign-in?redirect_url=/pricing");
      return;
    }
    const token = await getToken();
    setBusy(tier);
    try {
      const res = await fetch("/api/billing/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ plan: tier, origin: window.location.origin }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? "Could not start checkout");
      window.location.assign(data.url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start checkout");
    } finally {
      setBusy(null);
    }
  };

  return (
    <main className="mx-auto w-full max-w-4xl flex-1 px-5 py-12">
      <div className="mb-10 text-center">
        <Link href="/" className="bg-gradient-to-r from-violet-600 via-fuchsia-500 to-pink-500 bg-clip-text text-3xl font-bold tracking-tight text-transparent">
          Verseo
        </Link>
        <h1 className="mt-4 text-2xl font-bold">Choose your plan</h1>
        <p className="mt-2 text-slate-500 dark:text-slate-400">Start free. Upgrade any time — cancel any time.</p>
      </div>

      {error && (
        <div className="mx-auto mb-6 max-w-md rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-400/20 dark:bg-rose-500/10 dark:text-rose-200">
          {error}
        </div>
      )}

      <div className="grid gap-5 sm:grid-cols-3">
        {TIERS.map((t) => {
          const isCurrent = plan === t.id;
          const highlight = t.id === "plus";
          return (
            <div
              key={t.id}
              className={[
                "flex flex-col rounded-3xl border p-6 backdrop-blur-xl",
                highlight
                  ? "border-fuchsia-300/70 bg-gradient-to-b from-violet-50/80 to-fuchsia-50/60 shadow-lg shadow-fuchsia-500/10 dark:border-fuchsia-400/30 dark:from-violet-500/10 dark:to-fuchsia-500/10"
                  : "border-white/60 bg-white/70 dark:border-white/10 dark:bg-white/5",
              ].join(" ")}
            >
              <h2 className="text-lg font-semibold">{t.name}</h2>
              <div className="mt-1 text-3xl font-bold">{t.price}</div>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{t.blurb}</p>
              <ul className="mt-4 flex-1 space-y-2 text-sm">
                {t.features.map((f) => (
                  <li key={f} className="flex items-start gap-2">
                    <span className="mt-0.5 text-emerald-500">✓</span>
                    {f}
                  </li>
                ))}
              </ul>
              {t.id === "free" ? (
                <Link href="/" className="mt-5 rounded-xl border border-slate-200 px-4 py-2.5 text-center text-sm font-medium transition hover:bg-slate-50 dark:border-white/10 dark:hover:bg-white/5">
                  {isCurrent && isSignedIn ? "Current plan" : "Use free"}
                </Link>
              ) : (
                <button
                  onClick={() => void checkout(t.id)}
                  disabled={busy !== null || isCurrent}
                  className={[
                    "mt-5 rounded-xl px-4 py-2.5 text-sm font-medium text-white transition disabled:opacity-50",
                    highlight
                      ? "bg-gradient-to-r from-violet-600 to-fuchsia-500 hover:brightness-110"
                      : "bg-slate-900 hover:bg-slate-800 dark:bg-white/15 dark:hover:bg-white/25",
                  ].join(" ")}
                >
                  {isCurrent ? "Current plan" : busy === t.id ? "Redirecting…" : t.cta}
                </button>
              )}
            </div>
          );
        })}
      </div>

      <p className="mt-8 text-center text-xs text-slate-400">
        Payments are processed by Stripe. Manage or cancel from your account menu any time.
      </p>
    </main>
  );
}

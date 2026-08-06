"use client";

import { useAuth, useClerk, useUser } from "@clerk/nextjs";
import Link from "next/link";
import { useEffect, useState } from "react";

// Responsive account menu for the top bar. Signed-in users always see who
// they are and a logout button — inline on desktop, inside a full-width
// panel on mobile. Auth identity comes from Clerk; plan/billing state comes
// from our backend (Supabase-backed users table).
export default function AccountMenu() {
  const { isLoaded, isSignedIn, getToken } = useAuth();
  const { user } = useUser();
  const { signOut } = useClerk();
  const [plan, setPlan] = useState<string>("free");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loadTimedOut, setLoadTimedOut] = useState(false);

  useEffect(() => {
    // Safety net: Clerk's client SDK can get stuck not-loaded on this
    // deployment (dev-instance session bootstrap on a non-localhost domain)
    // — without this, a signed-in user who refreshes sees the whole account
    // menu vanish with no way to reach "Sign out". Fall back to a "Sign in"
    // link after a few seconds; clicking it while still actually signed in
    // just bounces back home, so this degrades safely either way.
    if (isLoaded) return;
    const t = setTimeout(() => setLoadTimedOut(true), 4000);
    return () => clearTimeout(t);
  }, [isLoaded]);

  useEffect(() => {
    if (!isSignedIn) return;
    let cancelled = false;
    void (async () => {
      try {
        const token = await getToken();
        const data = await (
          await fetch("/api/me", { headers: { Authorization: `Bearer ${token}` } })
        ).json();
        if (!cancelled && data.user?.plan) setPlan(data.user.plan);
      } catch {
        /* backend unreachable */
      }
    })();
    return () => {
      cancelled = true;
    };
    // getToken intentionally omitted — see AuthGate.tsx for why including it
    // caused an infinite refetch loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSignedIn, user?.id]);

  const managePortal = async () => {
    setBusy(true);
    try {
      const token = await getToken();
      const res = await fetch("/api/billing/portal", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ origin: window.location.origin }),
      });
      const data = await res.json();
      if (res.ok && data.url) window.location.assign(data.url);
      else window.location.assign("/pricing");
    } finally {
      setBusy(false);
    }
  };

  if (!isLoaded && !loadTimedOut) return null;

  if (!isSignedIn || !user) {
    return (
      <Link
        href="/sign-in"
        className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:border-slate-300 dark:border-white/10 dark:bg-white/5 dark:text-slate-300"
      >
        Sign in
      </Link>
    );
  }

  const email = user.primaryEmailAddress?.emailAddress ?? "";
  const name = user.fullName ?? "";
  const initial = (name || email || "?").trim().charAt(0).toUpperCase();
  const planColor =
    plan === "speaker"
      ? "bg-fuchsia-100 text-fuchsia-700 dark:bg-fuchsia-500/15 dark:text-fuchsia-300"
      : plan === "plus"
        ? "bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300"
        : "bg-slate-100 text-slate-500 dark:bg-white/10 dark:text-slate-400";

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label="Account menu"
        aria-expanded={open}
        className="flex items-center gap-2 rounded-full border border-transparent bg-transparent py-0.5 pl-0.5 pr-1 transition hover:border-slate-200 sm:pr-3 dark:hover:border-white/10"
      >
        {user.imageUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={user.imageUrl}
            alt=""
            className="h-8 w-8 shrink-0 rounded-full object-cover"
          />
        ) : (
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-violet-600 to-fuchsia-500 text-sm font-semibold text-white shadow-sm">
            {initial}
          </span>
        )}
        <span className="hidden max-w-[10rem] truncate text-sm font-medium text-slate-600 sm:inline dark:text-slate-300">
          {name || email}
        </span>
      </button>

      {open && (
        <>
          {/* Backdrop closes the menu on outside tap (mobile-friendly). */}
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="fixed inset-x-4 top-[4.5rem] z-40 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl sm:absolute sm:inset-x-auto sm:right-0 sm:top-full sm:mt-2 sm:w-64 dark:border-white/10 dark:bg-slate-900">
            <div className="flex items-center gap-3 border-b border-slate-100 px-4 py-3.5 dark:border-white/10">
              {user.imageUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={user.imageUrl}
                  alt=""
                  className="h-9 w-9 shrink-0 rounded-full object-cover"
                />
              ) : (
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-violet-600 to-fuchsia-500 text-sm font-semibold text-white">
                  {initial}
                </span>
              )}
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{name || email}</p>
                {name && <p className="truncate text-xs text-slate-400">{email}</p>}
              </div>
            </div>
            <div className="px-4 py-2.5">
              <span className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${planColor}`}>
                {plan} plan
              </span>
            </div>
            {plan === "free" ? (
              <a href="/pricing" className="block px-4 py-2.5 text-sm text-violet-600 hover:bg-slate-50 dark:text-violet-300 dark:hover:bg-white/5">
                ✨ Upgrade plan
              </a>
            ) : (
              <button onClick={() => void managePortal()} disabled={busy} className="block w-full px-4 py-2.5 text-left text-sm hover:bg-slate-50 disabled:opacity-50 dark:hover:bg-white/5">
                {busy ? "Opening…" : "Manage billing"}
              </button>
            )}
            <button
              onClick={() => void signOut({ redirectUrl: "/sign-in" })}
              className="block w-full border-t border-slate-100 px-4 py-2.5 text-left text-sm font-medium text-rose-600 hover:bg-rose-50 dark:border-white/10 dark:text-rose-400 dark:hover:bg-rose-500/10"
            >
              Sign out
            </button>
          </div>
        </>
      )}
    </div>
  );
}

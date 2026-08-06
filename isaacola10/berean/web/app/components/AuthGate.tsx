"use client";

import { useAuth, useUser } from "@clerk/nextjs";
import { useCallback, useEffect, useState } from "react";
import { Spinner } from "./Icons";
import Onboarding from "./Onboarding";

type Status = "checking" | "redirecting" | "onboarding" | "ready";

// Client-side sign-in guard. Edge (middleware) protection is intentionally not
// used — the dev Clerk instance behind HF's proxy can't verify sessions
// server-side reliably, which broke every navigation on refresh. Here we read
// the session from the browser (reliable) and redirect signed-out users to
// sign-in ourselves. Data is still protected server-side by the backend.
export default function AuthGate({ children }: { children: React.ReactNode }) {
  const { isLoaded, isSignedIn, getToken } = useAuth();
  const { user } = useUser();
  const [status, setStatus] = useState<Status>("checking");

  useEffect(() => {
    // Last-resort safety net: if Clerk's client never finishes loading, don't
    // hang on a spinner forever — fall through so the page is usable (data
    // stays protected server-side regardless).
    const bail = setTimeout(() => {
      setStatus((s) => (s === "checking" ? "ready" : s));
    }, 8000);

    if (!isLoaded) return () => clearTimeout(bail);

    if (!isSignedIn) {
      clearTimeout(bail);
      const here = window.location.pathname + window.location.search;
      window.location.replace(`/sign-in?redirect_url=${encodeURIComponent(here)}`);
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setStatus("redirecting");
      return;
    }

    let cancelled = false;
    void (async () => {
      try {
        const token = await getToken();
        const res = await fetch("/api/me", { headers: { Authorization: `Bearer ${token}` } });
        const me = await res.json();
        if (!cancelled) setStatus(me.user && !me.user.onboarded ? "onboarding" : "ready");
      } catch {
        if (!cancelled) setStatus("ready");
      } finally {
        clearTimeout(bail);
      }
    })();
    return () => {
      cancelled = true;
      clearTimeout(bail);
    };
    // getToken intentionally omitted from deps: it's memoized against Clerk's
    // internal client instance, not something this effect needs to react to.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoaded, isSignedIn, user?.id]);

  const finishOnboarding = useCallback(() => {
    setStatus("ready");
    void (async () => {
      try {
        const token = await getToken();
        await fetch("/api/me/onboarded", {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
        });
      } catch {
        /* best-effort — won't block the app */
      }
    })();
  }, [getToken]);

  // Signed-out users get a spinner while we bounce them to sign-in — never the
  // real app content.
  if (status === "checking" || status === "redirecting") {
    return (
      <div className="flex flex-1 items-center justify-center py-24">
        <Spinner size={22} />
      </div>
    );
  }

  return (
    <>
      {status === "onboarding" && <Onboarding onDone={finishOnboarding} />}
      {children}
    </>
  );
}

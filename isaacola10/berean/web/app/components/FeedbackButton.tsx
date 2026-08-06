"use client";

import { useState } from "react";

// Floating feedback widget shown to test users. Posts to /api/feedback with
// the tester's stored test key.
export default function FeedbackButton({ testKey }: { testKey: string }) {
  const [open, setOpen] = useState(false);
  const [rating, setRating] = useState<number | null>(null);
  const [message, setMessage] = useState("");
  const [sent, setSent] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async () => {
    if (!message.trim()) return;
    setSending(true);
    setError(null);
    try {
      const res = await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Test-Key": testKey },
        body: JSON.stringify({ rating, message }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail ?? "Failed to send feedback");
      }
      setSent(true);
      setMessage("");
      setRating(null);
      setTimeout(() => {
        setOpen(false);
        setSent(false);
      }, 1500);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to send feedback");
    } finally {
      setSending(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed bottom-5 right-5 z-40 inline-flex items-center gap-1.5 rounded-full bg-gradient-to-r from-violet-600 to-fuchsia-500 px-4 py-2.5 text-sm font-medium text-white shadow-lg shadow-fuchsia-500/30 transition hover:brightness-110"
      >
        💬 Feedback
      </button>
      {open && (
        <div
          className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-0 backdrop-blur-sm sm:items-center sm:p-6"
          onClick={() => setOpen(false)}
        >
          <div
            className="w-full max-w-md rounded-t-3xl border border-slate-200 bg-white p-6 shadow-2xl sm:rounded-3xl dark:border-white/10 dark:bg-slate-900"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="mb-1 text-lg font-semibold">Send feedback</h2>
            <p className="mb-4 text-sm text-slate-500">
              Tell us what worked or what didn&apos;t. The admin will see this on the console.
            </p>
            <div className="mb-3 flex items-center gap-1.5">
              {[1, 2, 3, 4, 5].map((n) => (
                <button
                  key={n}
                  type="button"
                  onClick={() => setRating(n)}
                  className={[
                    "h-8 w-8 rounded-full text-lg transition",
                    (rating ?? 0) >= n ? "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300" : "text-slate-300 hover:text-slate-500",
                  ].join(" ")}
                  aria-label={`Rate ${n}`}
                >
                  ★
                </button>
              ))}
            </div>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              rows={4}
              placeholder="What happened, what would you change…"
              className="w-full resize-none rounded-xl border border-slate-200 bg-white px-3 py-2 outline-none focus:border-violet-400 focus:ring-2 focus:ring-violet-400/30 dark:border-white/10 dark:bg-black/20"
            />
            {error && <p className="mt-2 text-sm text-rose-600">{error}</p>}
            <div className="mt-4 flex items-center justify-between">
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="text-sm text-slate-500 hover:text-slate-700"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={send}
                disabled={sending || !message.trim()}
                className="rounded-full bg-gradient-to-r from-violet-600 to-fuchsia-500 px-4 py-2 text-sm font-medium text-white transition hover:brightness-110 disabled:opacity-50"
              >
                {sent ? "Sent ✓" : sending ? "Sending…" : "Send"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

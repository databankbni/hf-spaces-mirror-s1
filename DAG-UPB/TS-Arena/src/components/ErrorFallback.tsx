'use client';

import { useEffect, useRef, useSyncExternalStore } from 'react';

/** The `?debug=1` flag lives in the URL, which React does not own. */
const subscribeToNothing = () => () => {};
const readDebugFlag = () =>
  new URLSearchParams(window.location.search).get('debug') === '1';
// Server snapshot: the flag is unknowable until there is a `window`, and claiming `false`
// keeps server and client output identical until React re-renders on the client.
const debugFlagOnServer = () => false;

interface ErrorFallbackProps {
  error: Error & { digest?: string };
  reset: () => void;
}

/**
 * What a visitor sees when a client-side exception escapes to an error boundary.
 *
 * Without a boundary Next.js renders its own bare "Application error: a client-side
 * exception has occurred" stub, which tells the visitor nothing and — more importantly —
 * leaves us with no record that anything happened at all.
 *
 * Raw exception text is deliberately **not** shown by default. Next.js strips server error
 * messages in production and substitutes `digest` precisely so internals do not leak, and
 * this is a public site. Visitors get the digest as a short reference; the full message and
 * stack go to the server log, and are additionally rendered inline when the URL carries
 * `?debug=1` so the fault can be read straight off a phone or tablet with no devtools.
 */
export default function ErrorFallback({ error, reset }: ErrorFallbackProps) {
  const showDetail = useSyncExternalStore(
    subscribeToNothing,
    readDebugFlag,
    debugFlagOnServer,
  );
  // Reporting is idempotent per mount: React may re-render the boundary (e.g. Strict Mode
  // double-invokes effects in development) and one fault should produce one log line.
  const reported = useRef(false);

  useEffect(() => {
    if (reported.current) return;
    reported.current = true;

    // Fire-and-forget. A failure to report must never surface to the visitor or throw from
    // inside the boundary that is already handling an error. `keepalive` lets the request
    // outlive the page if they navigate away immediately.
    try {
      void fetch('/api/client-error', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: error.message,
          stack: error.stack,
          digest: error.digest,
          pathname: window.location.pathname + window.location.search,
          userAgent: navigator.userAgent,
        }),
        keepalive: true,
      }).catch(() => {});
    } catch {
      // Ignore: serialisation or a blocked request must not escalate.
    }
  }, [error]);

  return (
    <div className="min-h-screen bg-gray-50 p-4 sm:p-6 lg:p-8">
      <main className="max-w-2xl mx-auto">
        <div className="bg-white rounded-lg shadow-md p-6 sm:p-8 mt-8">
          <h1 className="text-2xl font-semibold text-gray-900">Something went wrong</h1>
          <p className="mt-3 text-gray-600">
            This page hit an unexpected error. Trying again usually works — the rankings and
            forecast data themselves are unaffected.
          </p>

          <div className="mt-6 flex flex-wrap gap-3">
            <button
              onClick={reset}
              className="px-4 py-2 rounded-md bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
            >
              Try again
            </button>
            {/* Deliberately a plain anchor, not next/link. The rule exists to avoid full
                page reloads, but a full reload is the point here: client-side navigation
                would route within the same broken runtime the boundary just caught, and
                `global-error` renders when the root layout itself failed. */}
            {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
            <a
              href="/"
              className="px-4 py-2 rounded-md border border-gray-300 text-gray-700 text-sm font-medium hover:bg-gray-50"
            >
              Back to homepage
            </a>
          </div>

          {error.digest && (
            <p className="mt-6 text-xs text-gray-500">
              Reference: <code className="font-mono text-gray-700">{error.digest}</code>
              <span className="block mt-1">
                Quote this if you report the problem to us.
              </span>
            </p>
          )}

          {showDetail && (
            <div className="mt-6 border-t border-gray-200 pt-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                Debug detail
              </p>
              <p className="mt-2 text-sm font-medium text-gray-900 break-words">
                {error.message || '(no message)'}
              </p>
              {error.stack && (
                <pre className="mt-3 max-h-80 overflow-auto rounded bg-gray-900 p-3 text-xs leading-relaxed text-gray-100 whitespace-pre-wrap break-words">
                  {error.stack}
                </pre>
              )}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

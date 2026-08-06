'use client';

import ErrorFallback from '@/src/components/ErrorFallback';
import './globals.css';

/**
 * Last-resort boundary for failures in the root layout itself.
 *
 * It replaces the whole document, so it has to supply its own `<html>` and `<body>` — the
 * root layout is precisely what did not render. It also imports the stylesheet directly,
 * since the layout that normally pulls it in never ran.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body>
        <ErrorFallback error={error} reset={reset} />
      </body>
    </html>
  );
}

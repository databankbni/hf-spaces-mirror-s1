'use client';

import ErrorFallback from '@/src/components/ErrorFallback';

/**
 * Route-level error boundary. Catches exceptions thrown while rendering any page below
 * the root layout; the layout itself (nav, footer) keeps rendering around it.
 *
 * A failure in the root layout escapes this one — `global-error.tsx` catches those.
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return <ErrorFallback error={error} reset={reset} />;
}

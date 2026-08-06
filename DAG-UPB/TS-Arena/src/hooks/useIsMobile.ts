'use client';

import { useSyncExternalStore } from 'react';

/**
 * Viewport width below which we consider the client a phone.
 *
 * Deliberately the complement of Tailwind's `sm` breakpoint (min-width: 640px),
 * so `useIsMobile()` and a `sm:` class always agree about which side of the
 * breakpoint we are on. Keep the two in sync if the Tailwind theme changes.
 */
export const MOBILE_MEDIA_QUERY = '(max-width: 639px)';

function hasMatchMedia(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function';
}

function subscribe(onStoreChange: () => void): () => void {
  if (!hasMatchMedia()) return () => {};

  const mediaQueryList = window.matchMedia(MOBILE_MEDIA_QUERY);
  mediaQueryList.addEventListener('change', onStoreChange);
  return () => mediaQueryList.removeEventListener('change', onStoreChange);
}

function getSnapshot(): boolean {
  if (!hasMatchMedia()) return false;
  return window.matchMedia(MOBILE_MEDIA_QUERY).matches;
}

function getServerSnapshot(): boolean {
  // No viewport exists while prerendering, so assume desktop. React re-reads the
  // real snapshot right after hydration, which cannot produce a mismatch warning.
  return false;
}

/**
 * Reactive "is this a phone-sized viewport?" flag.
 *
 * Use this only where a Tailwind responsive class cannot do the job — i.e. when a
 * breakpoint has to drive JavaScript rather than CSS. The motivating case is
 * Plotly, whose layout is a plain JS object that no stylesheet can reach.
 * For anything expressible as `class="… sm:…"`, prefer the Tailwind class:
 * CSS media queries need no hydration and never flash the wrong state.
 *
 * Notes:
 * - SSR-safe. Returns `false` during prerender and on the hydration pass, then
 *   settles to the real value. Never touches `window` at module scope.
 * - Subscribes to the media query, so rotating a device or resizing a window
 *   re-renders the consumer.
 * - Returns a primitive, so `useSyncExternalStore` will not loop on identity.
 *
 * @returns `true` when the viewport is narrower than Tailwind's `sm` breakpoint.
 */
export function useIsMobile(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

export default useIsMobile;

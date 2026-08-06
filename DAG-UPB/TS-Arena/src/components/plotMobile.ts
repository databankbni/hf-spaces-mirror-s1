import type { PlotParams } from 'react-plotly.js';

/**
 * Shared pieces of the phone-sized Plotly preset.
 *
 * Only values that are byte-for-byte the same in every chart live here. The
 * layouts themselves are deliberately *not* shared: the charts plot different
 * things and their axis objects differ (date vs. category range, rangeslider,
 * gridcolor, an explicit domain), so a common "layout builder" would need more
 * override knobs than it saves. Duplicating three axis lines is cheaper to read
 * than an abstraction that fits none of the call sites exactly.
 *
 * Pair every use of these with `useIsMobile()` — see `@/src/hooks/useIsMobile`.
 */

/**
 * Plotly config for phone-sized viewports.
 *
 * On phones the plot is only ~200px wide, so Plotly's own chrome has to go:
 * the modebar does not fit, and `dragmode: false` (set in each layout) makes
 * Plotly skip its non-passive touchmove handler so a swipe scrolls the page
 * instead of drawing a zoom box.
 */
export const MOBILE_PLOT_CONFIG: PlotParams['config'] = {
  responsive: true,
  displayModeBar: false,
  doubleClick: 'reset',
};

/**
 * Plot margins on phones.
 *
 * Just enough on the left for a y-axis label and on the bottom for one row of
 * date ticks; the top and right are trimmed to the frame. Combine with
 * `automargin: true` on both axes so Plotly can grow these if a tick label
 * genuinely needs more room.
 */
export const MOBILE_PLOT_MARGIN = { l: 44, r: 8, t: 8, b: 36 };

/**
 * Plot height on phones, as a CSS length.
 *
 * Viewport-relative so the chart never eats a whole screen, capped so it does
 * not become a letterbox on a tablet-ish phone in landscape.
 */
export const MOBILE_PLOT_HEIGHT = 'min(60vh, 360px)';

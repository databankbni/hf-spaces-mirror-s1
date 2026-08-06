'use client';

import Plotly from 'plotly.js-basic-dist-min';
import createPlotlyComponent from 'react-plotly.js/factory';

/**
 * The single entry point for Plotly in this app.
 *
 * `react-plotly.js`'s default export pulls in `plotly.js/dist/plotly.js` — the
 * *complete* distribution, ~4.5 MB decoded, every trace type from 3-D surfaces
 * to choropleths to WebGL scatter. We plot `scatter` traces and nothing else,
 * so that is roughly 3.5 MB of parse-and-execute on every visit that can never
 * run. Building the component from `plotly.js-basic-dist-min` instead (scatter
 * + bar + pie, ~1.1 MB minified) keeps everything we actually use.
 *
 * "Everything we actually use" was checked against the bundle's own
 * `PlotSchema`, not against the docs: scatter with `fill: 'tonexty'`/`'none'`,
 * `hovertemplate`, `legendgroup`/`legendgrouptitle`, `visible: 'legendonly'`,
 * and — the one that would be easy to lose silently — the desktop x-axis
 * `rangeslider`, which lives in plotly's core and so ships in every bundle.
 *
 * Import this *dynamically with `ssr: false`*. Plotly touches `document` at
 * module scope and cannot be server-rendered:
 *
 * ```ts
 * const Plot = dynamic(() => import('@/src/components/PlotlyPlot'), { ssr: false });
 * ```
 *
 * Keeping the factory call here rather than at each call site means the heavy
 * import has exactly one entry point, so Next emits one shared chunk instead of
 * one per chart component.
 */
const Plot = createPlotlyComponent(Plotly);

export default Plot;

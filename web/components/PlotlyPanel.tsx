'use client';

import { useEffect, useRef } from 'react';
import Plotly from 'plotly.js-dist-min';

/**
 * Renders an arbitrary Plotly figure ({data, layout}). This is what lets the
 * agent's generate_viz codegen produce ANY chart type — radar/polar, heatmap,
 * contour, 3D, box/violin, parallel-coords, … — not just line/scatter/bar.
 */
export default function PlotlyPanel({ fig, height = 380 }: {
  fig: { data: unknown[]; layout?: Record<string, unknown> };
  height?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  // AI-written figures often hard-code layout.height / width (e.g. 820×920).
  // Plotly draws at that size regardless of the container, so a fixed-height box
  // let the plot spill over the text below it. The box now takes the figure's
  // own height (clamped) and the plot always fits the box's width.
  const figHeight = Number((fig.layout as { height?: unknown } | undefined)?.height) || 0;
  const boxHeight = Math.min(900, Math.max(240, figHeight || height));
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const { width: _w, height: _h, ...figLayout } = (fig.layout || {}) as Record<string, unknown>;
    const layout = {
      margin: { t: 36, r: 12, b: 40, l: 52 }, font: { size: 12 }, ...figLayout,
      autosize: true, height: boxHeight,
    };
    Plotly.react(el, (fig.data || []) as unknown[], layout, { responsive: true, displaylogo: false });
    return () => { try { Plotly.purge(el); } catch { /* ignore */ } };
  }, [fig, boxHeight]);
  return <div ref={ref} style={{ width: '100%', height: boxHeight }} className="rounded-xl ring-1 ring-ink-200 bg-white overflow-hidden" />;
}

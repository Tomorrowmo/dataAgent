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
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const layout = { autosize: true, margin: { t: 36, r: 12, b: 40, l: 52 }, font: { size: 12 }, ...(fig.layout || {}) };
    Plotly.react(el, (fig.data || []) as unknown[], layout, { responsive: true, displaylogo: false });
    return () => { try { Plotly.purge(el); } catch { /* ignore */ } };
  }, [fig]);
  return <div ref={ref} style={{ width: '100%', height }} className="rounded-xl ring-1 ring-ink-200 bg-white" />;
}

'use client';

import { useMemo, useState } from 'react';
import {
  ResponsiveContainer, LineChart, Line, ScatterChart, Scatter,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ZAxis,
} from 'recharts';
import { LineChart as LineIcon, ScatterChart as ScatterIcon, BarChart3 } from 'lucide-react';
import dynamic from 'next/dynamic';
// plotly.js-dist-min is a browser build that references `self` at module top,
// so it must never be evaluated during SSR — load it client-only.
const PlotlyPanel = dynamic(() => import('@/components/PlotlyPanel'), { ssr: false });

/**
 * Interactive, agent-generated chart. The backend `visualize` action ships a
 * spec + the (downsampled) data inline; everything below — axis pickers, series
 * toggles, chart-type switch — is driven entirely client-side over that data.
 *
 * This is the "visualization dialog the AI built for you, not a hard-coded one"
 * piece: the columns offered, the defaults, and the data all come from the
 * agent's response to *this* dataset, but the user stays in control of the view.
 */

export type ChartSpec = {
  chart_type: 'line' | 'scatter' | 'bar';
  x: string;
  y: string[];
  title?: string;
  columns: string[];
  numeric_columns?: string[];
  data: Record<string, number | null>[];
  downsampled_from?: number | null;
  // Independent-series mode: each series keeps its own (x,y) points, so series
  // of different lengths / x-grids (raw points vs interpolated curve, cell A vs
  // B) coexist on one chart. When present, this supersedes columns/data above.
  mode?: 'series';
  x_label?: string;
  series?: { label: string; points: { x: number; y: number | null }[] }[];
  // Arbitrary Plotly figure (radar/polar/heatmap/3D/…) — from generate_viz
  // codegen. When present it supersedes everything above.
  plotly?: { data: unknown[]; layout?: Record<string, unknown> };
};

type ChartType = 'line' | 'scatter' | 'bar';

const SERIES_COLORS = ['#2563eb', '#dc2626', '#059669', '#d97706', '#7c3aed', '#0891b2', '#db2777', '#65a30d'];

export default function ChartPanel({ spec, height = 300 }: { spec: ChartSpec; height?: number }) {
  // An arbitrary Plotly figure (any chart type the agent generated) renders
  // directly — this is the "generate anything" path.
  if (spec.plotly?.data) {
    return (
      <div className="w-full my-2">
        <PlotlyPanel fig={spec.plotly} height={Math.max(height, 360)} />
      </div>
    );
  }
  // Independent-series charts (overlay / different-length series) take a
  // dedicated render path; the shared-column path below can't represent them.
  if (spec.mode === 'series' && spec.series?.length) {
    return <SeriesChartPanel spec={spec} height={height} />;
  }
  const cols = spec.columns ?? [];
  const numeric = spec.numeric_columns ?? cols;
  const [chartType, setChartType] = useState<ChartType>(spec.chart_type ?? 'line');
  const [xKey, setXKey] = useState<string>(spec.x ?? cols[0] ?? '');
  const [yKeys, setYKeys] = useState<string[]>(
    (spec.y ?? []).filter((c) => cols.includes(c)).length
      ? spec.y.filter((c) => cols.includes(c))
      : numeric.filter((c) => c !== spec.x).slice(0, 1),
  );

  const data = spec.data ?? [];

  const yOptions = useMemo(() => numeric.filter((c) => c !== xKey), [numeric, xKey]);

  function toggleSeries(col: string) {
    setYKeys((prev) =>
      prev.includes(col) ? prev.filter((c) => c !== col) : [...prev, col],
    );
  }

  const activeY = yKeys.filter((c) => c !== xKey);

  return (
    <div className="w-full my-2 rounded-xl ring-1 ring-ink-200 bg-white p-3">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-2 mb-3 text-xs">
        {spec.title && <span className="font-medium text-ink-700 mr-1">{spec.title}</span>}

        <div className="inline-flex rounded-lg ring-1 ring-ink-200 overflow-hidden">
          {([['line', LineIcon], ['scatter', ScatterIcon], ['bar', BarChart3]] as const).map(([t, Icon]) => (
            <button
              key={t}
              onClick={() => setChartType(t)}
              title={t}
              className={`px-2 py-1 flex items-center gap-1 ${
                chartType === t ? 'bg-brand-600 text-white' : 'bg-white text-ink-500 hover:bg-ink-50'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
            </button>
          ))}
        </div>

        <label className="inline-flex items-center gap-1 text-ink-500">
          x:
          <select
            value={xKey}
            onChange={(e) => setXKey(e.target.value)}
            className="border border-ink-200 rounded-md px-1.5 py-1 bg-white"
          >
            {cols.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>

        <span className="text-ink-500">y:</span>
        <div className="inline-flex flex-wrap gap-1">
          {yOptions.map((c, i) => (
            <button
              key={c}
              onClick={() => toggleSeries(c)}
              className={`px-2 py-1 rounded-md ring-1 transition ${
                activeY.includes(c)
                  ? 'text-white ring-transparent'
                  : 'bg-white text-ink-500 ring-ink-200 hover:bg-ink-50'
              }`}
              style={activeY.includes(c) ? { backgroundColor: SERIES_COLORS[i % SERIES_COLORS.length] } : undefined}
            >
              {c}
            </button>
          ))}
        </div>
      </div>

      {/* Chart */}
      <div style={{ width: '100%', height }}>
        <ResponsiveContainer>
          {renderChart(chartType, xKey, activeY, data)}
        </ResponsiveContainer>
      </div>

      {spec.downsampled_from ? (
        <div className="mt-1.5 text-[11px] text-ink-400">
          已从 {spec.downsampled_from.toLocaleString()} 个点降采样到 {data.length} 个点以便流畅显示。
        </div>
      ) : null}
    </div>
  );
}

function SeriesChartPanel({ spec, height = 300 }: { spec: ChartSpec; height?: number }) {
  const [chartType, setChartType] = useState<ChartType>(spec.chart_type ?? 'line');
  const series = spec.series ?? [];

  return (
    <div className="w-full my-2 rounded-xl ring-1 ring-ink-200 bg-white p-3">
      <div className="flex flex-wrap items-center gap-2 mb-3 text-xs">
        {spec.title && <span className="font-medium text-ink-700 mr-1">{spec.title}</span>}
        <div className="inline-flex rounded-lg ring-1 ring-ink-200 overflow-hidden">
          {([['line', LineIcon], ['scatter', ScatterIcon], ['bar', BarChart3]] as const).map(([t, Icon]) => (
            <button
              key={t}
              onClick={() => setChartType(t)}
              title={t}
              className={`px-2 py-1 flex items-center gap-1 ${
                chartType === t ? 'bg-brand-600 text-white' : 'bg-white text-ink-500 hover:bg-ink-50'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
            </button>
          ))}
        </div>
        {spec.x_label && <span className="text-ink-500">x: {spec.x_label}</span>}
        <span className="text-ink-400">{series.length} 条 series(各自独立 x)</span>
      </div>
      <div style={{ width: '100%', height }}>
        <ResponsiveContainer>
          {renderSeriesChart(chartType, series)}
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function renderSeriesChart(
  type: ChartType,
  series: { label: string; points: { x: number; y: number | null }[] }[],
) {
  const axisProps = { tick: { fontSize: 11 }, stroke: '#94a3b8' } as const;
  const grid = <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />;
  const tip = <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />;
  const legend = <Legend wrapperStyle={{ fontSize: 11 }} />;

  if (type === 'scatter') {
    return (
      <ScatterChart margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
        {grid}
        <XAxis type="number" dataKey="x" {...axisProps} />
        <YAxis type="number" dataKey="y" {...axisProps} />
        <ZAxis range={[28, 28]} />{tip}{legend}
        {series.map((s, i) => (
          <Scatter key={s.label} name={s.label} data={s.points} fill={SERIES_COLORS[i % SERIES_COLORS.length]} />
        ))}
      </ScatterChart>
    );
  }
  if (type === 'bar') {
    return (
      <BarChart margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
        {grid}<XAxis type="number" dataKey="x" {...axisProps} /><YAxis {...axisProps} />{tip}{legend}
        {series.map((s, i) => (
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          <Bar key={s.label} data={s.points as any} dataKey="y" name={s.label} fill={SERIES_COLORS[i % SERIES_COLORS.length]} />
        ))}
      </BarChart>
    );
  }
  return (
    <LineChart margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
      {grid}<XAxis type="number" dataKey="x" {...axisProps} /><YAxis {...axisProps} />{tip}{legend}
      {series.map((s, i) => (
        <Line key={s.label} data={s.points} dataKey="y" name={s.label}
          stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
          dot={s.points.length <= 40} strokeWidth={1.6} isAnimationActive={false} />
      ))}
    </LineChart>
  );
}

function renderChart(
  type: ChartType,
  xKey: string,
  yKeys: string[],
  data: Record<string, number | null>[],
) {
  const axisProps = { tick: { fontSize: 11 }, stroke: '#94a3b8' } as const;
  const grid = <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />;
  const x = <XAxis dataKey={xKey} {...axisProps} />;
  const y = <YAxis {...axisProps} />;
  const tip = <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />;
  const legend = <Legend wrapperStyle={{ fontSize: 11 }} />;

  if (type === 'scatter') {
    return (
      <ScatterChart margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
        {grid}{x}{y}<ZAxis range={[24, 24]} />{tip}{legend}
        {yKeys.map((k, i) => (
          <Scatter key={k} name={k} data={data.map((d) => ({ [xKey]: d[xKey], [k]: d[k] }))}
            dataKey={k} fill={SERIES_COLORS[i % SERIES_COLORS.length]} />
        ))}
      </ScatterChart>
    );
  }
  if (type === 'bar') {
    return (
      <BarChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
        {grid}{x}{y}{tip}{legend}
        {yKeys.map((k, i) => <Bar key={k} dataKey={k} fill={SERIES_COLORS[i % SERIES_COLORS.length]} />)}
      </BarChart>
    );
  }
  return (
    <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
      {grid}{x}{y}{tip}{legend}
      {yKeys.map((k, i) => (
        <Line key={k} type="monotone" dataKey={k} stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
          dot={false} strokeWidth={1.6} isAnimationActive={false} />
      ))}
    </LineChart>
  );
}

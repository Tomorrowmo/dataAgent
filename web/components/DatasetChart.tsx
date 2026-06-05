'use client';

import { useEffect, useState } from 'react';
import { Loader2, BarChart3 } from 'lucide-react';
import { api } from '@/lib/api';
import ChartPanel, { type ChartSpec } from '@/components/ChartPanel';

/**
 * Direct visualization of ANY dataset (a source, or any derived pipeline stage)
 * by its id — fetches its rows and hands them to the same interactive ChartPanel
 * the chat agent uses, so the user gets line / scatter / bar with client-side
 * x / y / series pickers without going through the agent. Numeric columns are
 * inferred from the data (no schema needed), so it works for any stage. Reused
 * in the Datasets view and the mini-program result.
 */
export default function DatasetChart({ datasetId, resultPath, name, maxPoints = 1000, height = 420 }: { datasetId?: number; resultPath?: string; name?: string; maxPoints?: number; height?: number }) {
  const [spec, setSpec] = useState<ChartSpec | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setErr(''); setSpec(null);
    const fetchRows = resultPath != null
      ? api.previewResultFile(resultPath, maxPoints)
      : api.datasetPreview(datasetId as number, maxPoints);
    fetchRows.then((p) => {
      if (cancelled) return;
      const cols = p.columns;
      // Infer numeric columns by sampling the actual values.
      const numeric = cols.filter((c) => {
        let seen = 0, num = 0;
        for (const r of p.rows) {
          const v = r[c];
          if (v === null || v === undefined || v === '') continue;
          seen++;
          if (typeof v === 'number' || (typeof v === 'string' && v.trim() !== '' && !Number.isNaN(Number(v)))) num++;
          if (seen >= 40) break;
        }
        return seen > 0 && num / seen >= 0.8;
      });
      if (numeric.length === 0) { setErr('这张表没有数值列,暂时没有可画的曲线。'); setLoading(false); return; }
      // x defaults to a non-numeric (time/label) column if present, else the
      // first numeric; y is up to 3 numeric columns that aren't x.
      const x = cols.find((c) => !numeric.includes(c)) ?? numeric[0];
      const y = numeric.filter((c) => c !== x).slice(0, 3);
      setSpec({
        chart_type: 'line', x, y: y.length ? y : numeric.slice(0, 1),
        columns: cols, numeric_columns: numeric,
        data: p.rows as unknown as Record<string, number | null>[],
        title: name,
        downsampled_from: p.total > p.rows.length ? p.total : null,
      });
      setLoading(false);
    }).catch((e) => { if (!cancelled) { setErr((e as Error).message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [datasetId, resultPath, maxPoints, name]);

  if (loading) return <div className="py-8 text-center text-sm text-ink-400"><Loader2 className="w-4 h-4 animate-spin inline-block" /> 正在读取数据…</div>;
  if (err) return <div className="py-6 text-center text-sm text-ink-400 flex items-center justify-center gap-1.5"><BarChart3 className="w-4 h-4" /> {err}</div>;
  if (!spec) return null;
  return <ChartPanel spec={spec} height={height} />;
}

'use client';

import { useEffect, useState } from 'react';
import { Database, Table2, Sparkles, AlertTriangle, Loader2, Maximize2 } from 'lucide-react';
import { api, type Dataset } from '@/lib/api';

/** Heuristic: does this dataset look structurally messy (worth an AI cleanup)? */
function looksMessy(ds: Dataset): boolean {
  const cols = ds.schema?.columns ?? [];
  if (!cols.length) return false;
  const unnamed = cols.filter((c) => /^unnamed/i.test(c.name)).length;
  const numeric = cols.filter((c) => /int|float|number|double/i.test(c.dtype)).length;
  const mostlyEmpty = cols.filter((c) => (c.n_missing ?? 0) > ds.rows * 0.6).length;
  return unnamed >= 1 || numeric === 0 || mostlyEmpty >= Math.ceil(cols.length / 2);
}

/**
 * "See the data while you analyze" — a preview of the loaded dataset(s) right
 * inside the workbench, so the user never has to guess what columns/rows the
 * agent is operating on. Schema + head are already in `dataset.schema`, so this
 * is a pure read — no backend round-trip.
 *
 * Designed to take an array so multi-dataset (compare/overlay) just adds tabs;
 * today ChatView passes the single active dataset.
 */
export default function DataPanel({ datasets, onClean, onViewFull }: { datasets: Dataset[]; onClean?: (ds: Dataset) => void; onViewFull?: (id: number) => void }) {
  const [active, setActive] = useState(0);
  // Fetch more than the stored 10-row head so this reads as a real preview.
  const activeDs = datasets[Math.min(active, Math.max(0, datasets.length - 1))];
  const [preview, setPreview] = useState<{ columns: string[]; rows: Record<string, unknown>[]; total: number } | null>(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!activeDs) { setPreview(null); return; }
    setPreview(null); setLoading(true);
    let alive = true;
    api.datasetPreview(activeDs.id, 100)
      .then((r) => { if (alive) setPreview({ columns: r.columns, rows: r.rows, total: r.total }); })
      .catch(() => { /* fall back to the stored head */ })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [activeDs?.id]);

  if (!datasets.length) {
    return (
      <div className="text-[12px] text-ink-400 italic py-6 text-center">
        还没有选择数据集。选一个后,这里会显示它的列结构和前几行。
      </div>
    );
  }

  const ds = datasets[Math.min(active, datasets.length - 1)];
  const cols = ds.schema?.columns ?? [];
  const head = ds.schema?.head ?? [];
  // Prefer the freshly-fetched rows; fall back to the stored 10-row head.
  const rows = preview?.rows ?? head;
  const colNames = preview?.columns ?? cols.map((c) => c.name);

  return (
    <div className="space-y-3">
      {/* Dataset tabs (for the multi-dataset case) */}
      {datasets.length > 1 && (
        <div className="flex flex-wrap gap-1">
          {datasets.map((d, i) => (
            <button
              key={d.id}
              onClick={() => setActive(i)}
              className={`text-[11px] px-2 py-1 rounded-md ring-1 transition ${
                i === active ? 'bg-brand-600 text-white ring-transparent' : 'bg-white text-ink-600 ring-ink-200 hover:bg-ink-50'
              }`}
            >
              {d.name}
            </button>
          ))}
        </div>
      )}

      <div className="flex items-center gap-2 text-xs flex-wrap">
        <Database className="w-3.5 h-3.5 text-brand-600 shrink-0" />
        <span className="font-medium">{ds.name}</span>
        <span className="text-ink-400">{ds.rows.toLocaleString()} 行 × {ds.columns} 列</span>
        {looksMessy(ds) && (
          <span className="inline-flex items-center gap-1 text-[10.5px] text-amber-700 bg-amber-50 ring-1 ring-amber-200 rounded px-1.5 py-0.5">
            <AlertTriangle className="w-3 h-3" /> 结构较乱
          </span>
        )}
      </div>

      {onClean && (
        <button
          onClick={() => onClean(ds)}
          className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg ring-1 transition ${
            looksMessy(ds)
              ? 'bg-brand-600 text-white ring-transparent hover:bg-brand-700'
              : 'bg-white text-ink-600 ring-ink-200 hover:bg-ink-50'
          }`}
        >
          <Sparkles className="w-3.5 h-3.5" /> 用 AI 整理这张表
        </button>
      )}

      {/* Schema */}
      <div className="rounded-lg ring-1 ring-ink-200 bg-white divide-y divide-ink-100">
        {cols.map((c) => (
          <div key={c.name} className="flex items-center gap-2 px-2.5 py-1.5 text-[11.5px]">
            <span className="font-mono font-medium truncate">{c.name}</span>
            <span className="text-ink-400 font-mono">{c.dtype}</span>
            {typeof c.n_missing === 'number' && c.n_missing > 0 && (
              <span className="ml-auto text-amber-600 shrink-0">{c.n_missing} 缺失</span>
            )}
          </div>
        ))}
      </div>

      {/* Row preview — fetched on demand (up to 100 rows), head as fallback */}
      {(rows.length > 0 || loading) && (
        <div>
          <div className="flex items-center gap-1.5 text-[11px] text-ink-500 mb-1">
            <Table2 className="w-3 h-3 shrink-0" />
            {loading && !preview
              ? <span className="inline-flex items-center gap-1"><Loader2 className="w-3 h-3 animate-spin" /> 正在加载预览…</span>
              : <>预览前 {rows.length} 行{preview ? `（共 ${preview.total.toLocaleString()} 行）` : ''}</>}
            {onViewFull && (
              <button
                onClick={() => onViewFull(ds.id)}
                title="在「数据集」里打开这条数据的完整页面：排序 / 筛选 / 图表 / 血缘 / 另存"
                className="ml-auto inline-flex items-center gap-1 text-brand-600 hover:text-brand-700 hover:underline shrink-0"
              >
                <Maximize2 className="w-3 h-3" /> 查看完整表格
              </button>
            )}
          </div>
          <div className="rounded-lg ring-1 ring-ink-200 overflow-auto max-h-96">
            <table className="text-[11px] min-w-full">
              <thead className="bg-ink-50 text-ink-500 sticky top-0">
                <tr>
                  {colNames.map((c) => (
                    <th key={c} className="text-left py-1.5 px-2 font-medium whitespace-nowrap">{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr key={i} className="border-t border-ink-100 hover:bg-ink-50/60">
                    {colNames.map((c) => (
                      <td key={c} className="py-1 px-2 font-mono whitespace-nowrap text-ink-700">
                        {fmt((row as Record<string, unknown>)[c])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function fmt(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(4);
  const s = String(v);
  return s.length > 40 ? s.slice(0, 37) + '…' : s;
}

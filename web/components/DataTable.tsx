'use client';

import { useEffect, useMemo, useState } from 'react';
import { Loader2, ArrowUp, ArrowDown, ArrowUpDown, Save, X, Filter, CheckSquare } from 'lucide-react';
import { api, type Dataset } from '@/lib/api';

/**
 * Interactive data viewer: loads up to `loadLimit` rows of a dataset and lets
 * the user SORT (click a header), FILTER per column (a filter row under the
 * headers; supports `>5`, `<=10`, `!=x`, or plain substring), SELECT rows
 * (checkboxes), and SAVE a subset as a new derived dataset.
 *
 * Two save modes, both backed by POST /datasets/{id}/subset:
 *  - rows checked  → save exactly those rows (by original index).
 *  - else filters  → the SAME filters are re-applied to the FULL dataset on the
 *                    server (not just the loaded preview), then saved.
 */

type Row = Record<string, unknown>;

const OP_MAP: Record<string, string> = { '>=': 'ge', '<=': 'le', '!=': 'ne', '>': 'gt', '<': 'lt', '=': 'eq' };

function parseFilter(raw: string): { op: string; value: string } | null {
  const s = raw.trim();
  if (!s) return null;
  const m = s.match(/^(>=|<=|!=|>|<|=)\s*(.+)$/);
  if (m) return { op: OP_MAP[m[1]], value: m[2].trim() };
  return { op: 'contains', value: s };
}

function cellStr(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(4);
  const s = String(v);
  return s.length > 80 ? s.slice(0, 77) + '…' : s;
}

function rowMatches(row: Row, col: string, filterStr: string): boolean {
  const pf = parseFilter(filterStr);
  if (!pf) return true;
  const cell = row[col];
  if (pf.op === 'contains') return String(cell ?? '').toLowerCase().includes(pf.value.toLowerCase());
  const a = Number(cell), b = Number(pf.value);
  if (Number.isNaN(a) || Number.isNaN(b)) {
    if (pf.op === 'eq') return String(cell) === pf.value;
    if (pf.op === 'ne') return String(cell) !== pf.value;
    return true; // numeric comparison on non-numeric → don't exclude
  }
  switch (pf.op) {
    case 'gt': return a > b; case 'lt': return a < b;
    case 'ge': return a >= b; case 'le': return a <= b;
    case 'eq': return a === b; case 'ne': return a !== b;
  }
  return true;
}

export default function DataTable({ ds, onSaved }: { ds: Dataset; onSaved?: (d: Dataset) => void }) {
  const [rows, setRows] = useState<Row[]>([]);
  const [columns, setColumns] = useState<string[]>([]);
  const [total, setTotal] = useState(0);
  const [loadLimit, setLoadLimit] = useState(200);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');

  const [sort, setSort] = useState<{ col: string; desc: boolean } | null>(null);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [saving, setSaving] = useState(false);
  const [savedName, setSavedName] = useState('');

  // Reset everything when the dataset changes.
  useEffect(() => {
    setSort(null); setFilters({}); setSelected(new Set()); setSavedName(''); setErr('');
  }, [ds.id]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setErr('');
    api.datasetPreview(ds.id, loadLimit).then((p) => {
      if (cancelled) return;
      setColumns(p.columns);
      setRows(p.rows as Row[]);
      setTotal(p.total);
      setLoading(false);
    }).catch((e) => { if (!cancelled) { setErr((e as Error).message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [ds.id, loadLimit]);

  // Keep each row's ORIGINAL index (the preview is head(limit), so position == row
  // number in the full dataset) so a checkbox selection maps to real rows.
  const indexed = useMemo(() => rows.map((row, i) => ({ row, i })), [rows]);

  const numericCols = useMemo(() => {
    const out = new Set<string>();
    for (const c of columns) {
      let seen = 0, num = 0;
      for (const { row } of indexed) {
        const v = row[c];
        if (v === null || v === undefined || v === '') continue;
        seen++; if (typeof v === 'number' || !Number.isNaN(Number(v))) num++;
        if (seen >= 40) break;
      }
      if (seen > 0 && num / seen >= 0.8) out.add(c);
    }
    return out;
  }, [columns, indexed]);

  const activeFilters = useMemo(
    () => Object.entries(filters).filter(([, v]) => v.trim() !== ''),
    [filters],
  );

  const view = useMemo(() => {
    let v = indexed;
    for (const [col, f] of activeFilters) v = v.filter(({ row }) => rowMatches(row, col, f));
    if (sort) {
      const num = numericCols.has(sort.col);
      v = [...v].sort((A, B) => {
        const a = A.row[sort.col], b = B.row[sort.col];
        let cmp: number;
        if (num) cmp = (Number(a) || 0) - (Number(b) || 0);
        else cmp = String(a ?? '').localeCompare(String(b ?? ''));
        return sort.desc ? -cmp : cmp;
      });
    }
    return v;
  }, [indexed, activeFilters, sort, numericCols]);

  function toggleSort(col: string) {
    setSort((s) => s?.col !== col ? { col, desc: false } : s.desc ? null : { col, desc: true });
  }
  function toggleRow(i: number) {
    setSelected((s) => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n; });
  }
  const allVisibleSelected = view.length > 0 && view.every(({ i }) => selected.has(i));
  function toggleAllVisible() {
    setSelected((s) => {
      const n = new Set(s);
      if (allVisibleSelected) view.forEach(({ i }) => n.delete(i));
      else view.forEach(({ i }) => n.add(i));
      return n;
    });
  }

  const canSave = selected.size > 0 || activeFilters.length > 0;

  async function saveSubset() {
    if (!canSave || saving) return;
    setSaving(true); setErr(''); setSavedName('');
    try {
      let d: Dataset;
      if (selected.size > 0) {
        const name = window.prompt(`把选中的 ${selected.size} 行另存为新数据集：`, `${ds.name} · 选中${selected.size}行`);
        if (!name) { setSaving(false); return; }
        d = await api.saveSubset(ds.id, { name, row_indices: [...selected].sort((a, b) => a - b) });
      } else {
        const fl = activeFilters.map(([column, raw]) => {
          const pf = parseFilter(raw)!;
          return { column, op: pf.op, value: pf.value };
        });
        const name = window.prompt('把筛选结果（应用到整个数据集）另存为新数据集：', `${ds.name} · 筛选`);
        if (!name) { setSaving(false); return; }
        d = await api.saveSubset(ds.id, { name, filters: fl, sort: sort ? { column: sort.col, desc: sort.desc } : undefined });
      }
      setSavedName(d.name);
      onSaved?.(d);
    } catch (e) { setErr((e as Error).message); }
    finally { setSaving(false); }
  }

  if (loading) return <div className="py-8 text-center text-sm text-ink-400"><Loader2 className="w-4 h-4 animate-spin inline-block" /> 正在读取数据…</div>;
  if (err && rows.length === 0) return <div className="py-6 text-center text-sm text-red-600">{err}</div>;

  return (
    <div className="space-y-2">
      {/* Toolbar */}
      <div className="flex items-center gap-2 flex-wrap text-xs">
        <span className="text-ink-500">
          显示 <b className="text-ink-700">{view.length.toLocaleString()}</b>
          {view.length !== rows.length && <span> / 已加载 {rows.length.toLocaleString()}</span>}
          <span className="text-ink-400"> （共 {total.toLocaleString()} 行）</span>
        </span>
        {selected.size > 0 && (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-brand-50 text-brand-700 ring-1 ring-brand-100">
            <CheckSquare className="w-3 h-3" /> 选中 {selected.size}
            <button onClick={() => setSelected(new Set())} className="ml-0.5 hover:text-brand-900" title="清除选择"><X className="w-3 h-3" /></button>
          </span>
        )}
        {activeFilters.length > 0 && (
          <button onClick={() => setFilters({})} className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md ring-1 ring-ink-200 text-ink-500 hover:bg-ink-50">
            <Filter className="w-3 h-3" /> 清除 {activeFilters.length} 个筛选
          </button>
        )}
        <div className="ml-auto flex items-center gap-2">
          {total > rows.length && loadLimit < 500 && (
            <button onClick={() => setLoadLimit(500)} className="px-2 py-1 rounded-lg ring-1 ring-ink-200 text-ink-600 hover:bg-ink-50">多加载到 500 行</button>
          )}
          <button onClick={saveSubset} disabled={!canSave || saving}
            title={selected.size > 0 ? '把勾选的行另存为新数据集' : activeFilters.length > 0 ? '把筛选条件应用到整个数据集后另存' : '先勾选行或设置筛选'}
            className="px-2.5 py-1 rounded-lg bg-brand-600 text-white font-medium hover:bg-brand-700 disabled:opacity-50 flex items-center gap-1.5">
            {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            {selected.size > 0 ? `另存选中 ${selected.size} 行` : '另存筛选结果'}
          </button>
        </div>
      </div>

      {savedName && (
        <div className="text-xs text-violet-700 bg-violet-50 ring-1 ring-violet-100 rounded-lg px-2.5 py-1.5">
          ✓ 已另存为「{savedName}」—— 在数据集树的「中间结果」下可见。
        </div>
      )}
      {err && rows.length > 0 && <div className="text-xs text-red-600 bg-red-50 rounded-lg px-2.5 py-1.5">{err}</div>}

      <div className="rounded-lg ring-1 ring-ink-200 overflow-auto max-h-[28rem]">
        <table className="text-xs min-w-full">
          <thead className="bg-ink-50 sticky top-0 z-10">
            <tr>
              <th className="w-8 px-2 py-1.5 border-b border-ink-200">
                <input type="checkbox" checked={allVisibleSelected} onChange={toggleAllVisible} title="选择当前可见的所有行" />
              </th>
              {columns.map((c) => (
                <th key={c} className="text-left px-2 py-1.5 border-b border-ink-200 whitespace-nowrap">
                  <button onClick={() => toggleSort(c)} className="inline-flex items-center gap-1 font-medium text-ink-700 hover:text-brand-700">
                    {c}
                    {sort?.col === c ? (sort.desc ? <ArrowDown className="w-3 h-3" /> : <ArrowUp className="w-3 h-3" />) : <ArrowUpDown className="w-3 h-3 text-ink-300" />}
                  </button>
                </th>
              ))}
            </tr>
            <tr>
              <th className="px-1 py-1 border-b border-ink-200 bg-white" />
              {columns.map((c) => (
                <th key={c} className="px-1 py-1 border-b border-ink-200 bg-white">
                  <input
                    value={filters[c] ?? ''}
                    onChange={(e) => setFilters((f) => ({ ...f, [c]: e.target.value }))}
                    placeholder={numericCols.has(c) ? '如 >5' : '筛选…'}
                    className="w-full min-w-[64px] border border-ink-200 rounded px-1.5 py-0.5 text-[11px] font-normal focus:outline-none focus:border-brand-400"
                  />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {view.map(({ row, i }) => (
              <tr key={i} className={`border-t border-ink-100 ${selected.has(i) ? 'bg-brand-50/60' : 'hover:bg-ink-50/60'}`}>
                <td className="px-2 py-1 text-center">
                  <input type="checkbox" checked={selected.has(i)} onChange={() => toggleRow(i)} />
                </td>
                {columns.map((c) => <td key={c} className="px-2 py-1 font-mono whitespace-nowrap text-ink-700">{cellStr(row[c])}</td>)}
              </tr>
            ))}
            {view.length === 0 && (
              <tr><td colSpan={columns.length + 1} className="px-2 py-6 text-center text-ink-400">没有匹配筛选条件的行</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="text-[10.5px] text-ink-400">
        点列名排序 · 列下方输入框筛选（数值列支持 <span className="font-mono">&gt; &lt; &gt;= &lt;= = !=</span>，文本为包含匹配）· 勾选行后「另存选中」精确保存这些行；只设了筛选则把条件应用到<b>整个数据集</b>再另存。
      </div>
    </div>
  );
}

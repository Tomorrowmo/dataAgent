'use client';

/**
 * 多车次对比 — the analysis mode the customer's 20260225 note asks for.
 *
 * Three panes, because a 130-run entry cannot be driven from a flat list:
 *
 *   left    run picker with state filters (Ma / β / δz / δy / δx) and search
 *   middle  the chart plus the LEGEND-AS-STATE-TABLE the requirement shows —
 *           when several runs are on one chart, what matters is not the run
 *           number but which state variable differs between them
 *   right   what to plot: abscissa (α, or any coefficient for a drag polar /
 *           stability plot), ordinates, baseline + delta/ratio, sort order
 *
 * Plus three analysis tabs the matrix makes possible: the (Ma,β) coverage
 * matrix, control effectiveness with saturation, and ±deflection symmetry.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle, BarChart3, Check, Download, Grid3x3, Layers, Loader2,
  RefreshCw, Search, Sigma, Waves,
} from 'lucide-react';
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Scatter,
  ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from 'recharts';
import {
  api, type WtCompare, type WtCoverage, type WtEffectiveness, type WtMatrix,
  type WtResponse, type WtRunList, type WtSymmetry,
} from '@/lib/api';

const COLORS = ['#2563eb', '#dc2626', '#059669', '#d97706', '#7c3aed', '#0891b2',
  '#db2777', '#65a30d', '#0369a1', '#b45309', '#4f46e5', '#be123c',
  '#047857', '#a16207'];

type Pane = 'chart' | 'matrix' | 'effect' | 'symmetry';
type XKind = 'column' | 'state';

const fmt = (v: number | null | undefined, d = 4) =>
  v == null ? '—' : Number(v.toPrecision(d)).toString();

export default function WindTunnelCompare({ batchId }: { batchId: number | null }) {
  const [pane, setPane] = useState<Pane>('chart');
  const [runs, setRuns] = useState<WtRunList | null>(null);
  const [matrix, setMatrix] = useState<WtMatrix | null>(null);
  const [cov, setCov] = useState<WtCoverage | null>(null);
  const [sel, setSel] = useState<string[]>([]);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState('');

  // filters
  const [q, setQ] = useState('');
  const [fMach, setFMach] = useState<number | ''>('');
  const [fBeta, setFBeta] = useState<number | ''>('');
  const [fSingle, setFSingle] = useState<'' | 'dz' | 'dy' | 'dx' | 'base'>('');

  // plot config
  const [xKind, setXKind] = useState<XKind>('column');
  const [xCol, setXCol] = useState('ALPHA');
  const [xState, setXState] = useState('M');
  const [ys, setYs] = useState<string[]>(['CN']);
  const [alphas, setAlphas] = useState('0 2 4');
  const [alphas2, setAlphas2] = useState('');
  const [baseline, setBaseline] = useState('');
  const [mode, setMode] = useState<'value' | 'delta' | 'ratio'>('value');
  const [sortBy, setSortBy] = useState<string[]>(['dz']);
  const [chart, setChart] = useState<WtCompare | null>(null);

  // analysis panes
  const [surface, setSurface] = useState<'dz' | 'dy' | 'dx'>('dz');
  const [eff, setEff] = useState<WtEffectiveness | null>(null);
  const [resp, setResp] = useState<WtResponse | null>(null);
  const [sym, setSym] = useState<WtSymmetry | null>(null);

  const load = useCallback(async () => {
    if (batchId == null) return;
    setErr('');
    try {
      const [r, m] = await Promise.all([api.wtRuns(batchId), api.wtMatrix(batchId)]);
      setRuns(r);
      setMatrix(m);
      api.wtCoverage(batchId).then(setCov).catch(() => setCov(null));
    } catch (e) { setErr(String(e)); }
  }, [batchId]);

  useEffect(() => { load().catch(() => {}); }, [load]);
  useEffect(() => { setSel([]); setChart(null); setEff(null); setSym(null); setResp(null); }, [batchId]);

  const filtered = useMemo(() => {
    const list = runs?.runs ?? [];
    return list.filter((r) => {
      if (q && !r.run_no.includes(q) && !r.state_text.includes(q)) return false;
      if (fMach !== '' && r.state.M !== fMach) return false;
      if (fBeta !== '' && r.state.BETA !== fBeta) return false;
      const d = { dz: r.state.dz ?? 0, dy: r.state.dy ?? 0, dx: r.state.dx ?? 0 };
      if (fSingle === 'base') return d.dz === 0 && d.dy === 0 && d.dx === 0;
      if (fSingle) {
        const others = (['dz', 'dy', 'dx'] as const).filter((k) => k !== fSingle);
        return d[fSingle] !== 0 && others.every((k) => d[k] === 0);
      }
      return true;
    });
  }, [runs, q, fMach, fBeta, fSingle]);

  const betas = useMemo(
    () => Array.from(new Set((runs?.runs ?? []).map((r) => r.state.BETA)
      .filter((v): v is number => v != null))).sort((a, b) => a - b),
    [runs]);

  const parseAlphas = (s: string) =>
    s.split(/[\s,，]+/).map((t) => Number(t)).filter((n) => Number.isFinite(n));

  async function draw() {
    if (batchId == null || sel.length === 0) { setErr('请先在左侧勾选车次'); return; }
    setBusy('draw'); setErr('');
    try {
      const out = xKind === 'column'
        ? await api.wtCompareRuns(batchId, {
            run_nos: sel, x: xCol, ys, baseline: mode === 'value' ? null : baseline,
            mode, sort_by: sortBy,
          })
        : await api.wtCompareState(batchId, {
            run_nos: sel, state_var: xState, ys, alphas: parseAlphas(alphas),
            baseline: mode === 'value' ? null : baseline, mode,
            alphas_2: parseAlphas(alphas2),
            group_label: alphas2 ? 'a' : '', group_label_2: alphas2 ? 'b' : '',
          });
      setChart(out);
    } catch (e) { setErr(String(e)); setChart(null); } finally { setBusy(''); }
  }

  async function exportCsv() {
    if (batchId == null) return;
    setBusy('csv');
    try {
      const { blob, filename } = await api.wtCompareExport(batchId,
        xKind === 'column'
          ? { kind: 'runs', run_nos: sel, x: xCol, ys, baseline: mode === 'value' ? null : baseline, mode }
          : { kind: 'state', run_nos: sel, state_var: xState, ys, alphas: parseAlphas(alphas), baseline: mode === 'value' ? null : baseline, mode });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = filename;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    } catch (e) { setErr(String(e)); } finally { setBusy(''); }
  }

  async function runAnalysis(kind: 'effect' | 'symmetry') {
    if (batchId == null) return;
    setBusy(kind); setErr('');
    const al = parseAlphas(alphas).length ? parseAlphas(alphas) : [0];
    try {
      if (kind === 'effect') {
        const [e, r] = await Promise.all([
          api.wtEffectiveness(batchId, { surface, alphas: al }),
          api.wtResponse(batchId, { surface, alphas: [al[0]] }),
        ]);
        setEff(e); setResp(r);
      } else {
        setSym(await api.wtSymmetry(batchId, { surface, alphas: al }));
      }
    } catch (e) { setErr(String(e)); } finally { setBusy(''); }
  }

  // Recharts needs one row per abscissa with a column per series.
  const rows = useMemo(() => {
    if (!chart) return [];
    const m = new Map<number, Record<string, number>>();
    chart.series.forEach((s, i) => s.x.forEach((xv, j) => {
      const key = Number(xv.toPrecision(9));
      const row = m.get(key) ?? { x: key };
      row[`s${i}`] = s.y[j];
      m.set(key, row);
    }));
    return Array.from(m.values()).sort((a, b) => a.x - b.x);
  }, [chart]);

  if (batchId == null) {
    return <div className="text-center py-20 text-sm text-ink-400">请先在「① 数据导入」中选择一个批次。</div>;
  }

  const PANES: { id: Pane; label: string; icon: React.ReactNode }[] = [
    { id: 'chart', label: '对比绘图', icon: <BarChart3 className="w-4 h-4" /> },
    { id: 'matrix', label: '状态矩阵', icon: <Grid3x3 className="w-4 h-4" /> },
    { id: 'effect', label: '舵效分析', icon: <Sigma className="w-4 h-4" /> },
    { id: 'symmetry', label: '对称性校核', icon: <Waves className="w-4 h-4" /> },
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-1">
        {PANES.map((p) => (
          <button key={p.id} onClick={() => setPane(p.id)}
            className={`px-3 py-1.5 rounded-lg text-sm inline-flex items-center gap-1.5 ${
              pane === p.id ? 'bg-brand-50 text-brand-700 ring-1 ring-brand-200'
                : 'text-ink-500 hover:bg-ink-100'}`}>
            {p.icon}{p.label}
          </button>
        ))}
        <span className="ml-auto text-xs text-ink-400">
          共 {runs?.count ?? 0} 个车次 · 已选 {sel.length}
        </span>
        <button onClick={load} className="p-1.5 text-ink-400 hover:text-brand-600" title="刷新">
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {err && (
        <div className="text-sm px-3 py-2 rounded-lg bg-red-50 text-red-800 ring-1 ring-red-200 flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <span className="flex-1">{err}</span>
          <button onClick={() => setErr('')} className="text-red-400">×</button>
        </div>
      )}

      {pane === 'chart' && (
        <div className="grid grid-cols-1 xl:grid-cols-12 gap-4">
          {/* ── run picker ── */}
          <div className="xl:col-span-3 space-y-2">
            <div className="rounded-xl border border-ink-200 bg-white p-3 space-y-2">
              <div className="flex items-center gap-1.5">
                <Search className="w-3.5 h-3.5 text-ink-400" />
                <input value={q} onChange={(e) => setQ(e.target.value)}
                  placeholder="搜索车次号或状态"
                  className="flex-1 text-xs px-2 py-1 rounded border border-ink-200" />
              </div>
              <div className="grid grid-cols-2 gap-1.5">
                <select value={fMach} onChange={(e) => setFMach(e.target.value === '' ? '' : Number(e.target.value))}
                  className="text-xs px-1.5 py-1 rounded border border-ink-200 bg-white">
                  <option value="">全部 Ma</option>
                  {(runs?.machs ?? []).map((m) => <option key={m} value={m}>Ma={m}</option>)}
                </select>
                <select value={fBeta} onChange={(e) => setFBeta(e.target.value === '' ? '' : Number(e.target.value))}
                  className="text-xs px-1.5 py-1 rounded border border-ink-200 bg-white">
                  <option value="">全部 β</option>
                  {betas.map((b) => <option key={b} value={b}>β={b}°</option>)}
                </select>
              </div>
              <select value={fSingle} onChange={(e) => setFSingle(e.target.value as typeof fSingle)}
                className="w-full text-xs px-1.5 py-1 rounded border border-ink-200 bg-white">
                <option value="">不限舵面</option>
                <option value="base">仅 δ 全零基准车次</option>
                <option value="dz">仅升降舵 δz 单独偏转</option>
                <option value="dy">仅方向舵 δy 单独偏转</option>
                <option value="dx">仅副翼 δx 单独偏转</option>
              </select>
              <div className="flex gap-1.5 text-xs">
                {/* Union, not replace. Assembling a comparison set is naturally
                    iterative — pick a deflection series, then add its δ=0
                    baseline under a different filter. Replacing would throw the
                    first half away, which is exactly what it used to do. */}
                <button onClick={() => setSel(Array.from(new Set([...sel, ...filtered.map((r) => r.run_no)])))}
                  className="flex-1 px-2 py-1 rounded border border-brand-200 text-brand-700"
                  title="把当前筛选结果加入已选车次（不会清掉之前选的）">
                  加入筛选结果 ({filtered.length})
                </button>
                <button onClick={() => setSel([])}
                  className="px-2 py-1 rounded border border-ink-200 text-ink-500">清空</button>
              </div>
            </div>
            <div className="rounded-xl border border-ink-200 bg-white max-h-[52vh] overflow-y-auto">
              {filtered.map((r) => {
                const on = sel.includes(r.run_no);
                return (
                  <label key={r.run_no}
                    className={`flex items-start gap-2 px-2.5 py-1.5 border-b border-ink-50 cursor-pointer ${on ? 'bg-brand-50/50' : 'hover:bg-ink-50'}`}>
                    <input type="checkbox" checked={on} className="mt-0.5 accent-brand-600"
                      onChange={() => setSel(on ? sel.filter((x) => x !== r.run_no) : [...sel, r.run_no])} />
                    <span className="flex-1 min-w-0">
                      <span className="font-mono text-xs text-ink-800">{r.run_no}</span>
                      <span className="block text-[10px] text-ink-500 truncate">{r.state_text}</span>
                    </span>
                    {!r.has_da && <span className="text-[10px] text-amber-600">无da</span>}
                  </label>
                );
              })}
              {filtered.length === 0 && <div className="text-xs text-ink-400 p-4 text-center">没有符合条件的车次</div>}
            </div>
          </div>

          {/* ── chart ── */}
          <div className="xl:col-span-6 space-y-3">
            <div className="rounded-xl border border-ink-200 bg-white p-3">
              {!chart && <div className="text-sm text-ink-400 py-24 text-center">选好车次与参数后点右侧「绘图」。</div>}
              {chart && (
                <>
                  <div className="text-xs text-ink-500 mb-1">
                    {chart.mode !== 'value' && (
                      <span className="mr-2 px-1.5 py-0.5 rounded bg-violet-50 text-violet-700">
                        {chart.mode === 'delta' ? '差量' : '相对基准比值'} · 基准 {chart.baseline}
                      </span>
                    )}
                    {chart.series.length} 条曲线
                  </div>
                  <div style={{ height: 400 }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={rows} margin={{ top: 8, right: 20, bottom: 30, left: 8 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                        <XAxis dataKey="x" type="number" domain={['dataMin', 'dataMax']}
                          tick={{ fontSize: 11 }}
                          label={{ value: chart.x_label, position: 'insideBottom', offset: -20, fontSize: 12 }} />
                        <YAxis tick={{ fontSize: 11 }} width={72} />
                        <Tooltip contentStyle={{ fontSize: 11 }}
                          formatter={(v: number, n: string) => {
                            const i = Number(String(n).replace('s', ''));
                            return [Number(v.toPrecision(6)), chart.series[i]?.label ?? n];
                          }} />
                        {chart.series.map((s, i) => (
                          <Line key={i} type="monotone" dataKey={`s${i}`} name={`s${i}`}
                            stroke={COLORS[i % COLORS.length]} strokeWidth={1.6}
                            dot={{ r: 2 }} connectNulls />
                        ))}
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                  {chart.notes.length > 0 && (
                    <div className="text-[11px] text-amber-700 bg-amber-50 rounded p-2 mt-2 space-y-0.5">
                      {chart.notes.slice(0, 4).map((n, i) => <div key={i}>· {n}</div>)}
                    </div>
                  )}
                </>
              )}
            </div>

            {/* legend-as-state-table — the requirement's 图例 */}
            {chart && (chart.legend?.length ?? 0) > 0 && (
              <div className="rounded-xl border border-ink-200 bg-white p-3 overflow-x-auto">
                <div className="text-xs font-medium text-ink-700 mb-1.5">
                  图例（多车次对比时，关键是看清它们差在哪个状态量）
                </div>
                <table className="w-full text-[11px]">
                  <thead className="text-ink-500 border-b border-ink-100">
                    <tr>
                      <th className="text-left py-1">色</th><th className="text-left">车次</th>
                      <th className="text-left">Ma</th><th className="text-left">β</th>
                      <th className="text-left">φ</th><th className="text-left">δz</th>
                      <th className="text-left">δy</th><th className="text-left">δx</th>
                    </tr>
                  </thead>
                  <tbody>
                    {chart.legend!.map((l, i) => (
                      <tr key={l.run_no} className="border-b border-ink-50">
                        <td className="py-1">
                          <span className="inline-block w-3 h-3 rounded-sm"
                            style={{ background: COLORS[(i * ys.length) % COLORS.length] }} />
                        </td>
                        <td className="font-mono">{l.run_no}</td>
                        <td>{fmt(l.M)}</td><td>{fmt(l.BETA)}</td><td>{fmt(l.PHI)}</td>
                        <td>{fmt(l.dz)}</td><td>{fmt(l.dy)}</td><td>{fmt(l.dx)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* ── plot config ── */}
          <div className="xl:col-span-3 space-y-3">
            <div className="rounded-xl border border-ink-200 bg-white p-3 space-y-2.5">
              <div className="text-xs font-medium text-ink-700">横轴</div>
              <div className="flex gap-1 text-xs">
                <button onClick={() => setXKind('column')}
                  className={`flex-1 px-2 py-1 rounded ${xKind === 'column' ? 'bg-brand-50 text-brand-700 ring-1 ring-brand-200' : 'text-ink-500 border border-ink-200'}`}>
                  攻角 / 系数
                </button>
                <button onClick={() => setXKind('state')}
                  className={`flex-1 px-2 py-1 rounded ${xKind === 'state' ? 'bg-brand-50 text-brand-700 ring-1 ring-brand-200' : 'text-ink-500 border border-ink-200'}`}>
                  状态量
                </button>
              </div>
              {xKind === 'column' ? (
                <select value={xCol} onChange={(e) => setXCol(e.target.value)}
                  className="w-full text-xs px-2 py-1 rounded border border-ink-200 bg-white">
                  {(runs?.columns ?? []).map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
                </select>
              ) : (
                <>
                  <select value={xState} onChange={(e) => setXState(e.target.value)}
                    className="w-full text-xs px-2 py-1 rounded border border-ink-200 bg-white">
                    {(runs?.state_vars ?? []).map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
                  </select>
                  <label className="block text-[11px] text-ink-500">
                    攻角序列（空格分隔）
                    <input value={alphas} onChange={(e) => setAlphas(e.target.value)}
                      className="mt-0.5 w-full text-xs px-2 py-1 rounded border border-ink-200 font-mono" />
                  </label>
                  <label className="block text-[11px] text-ink-500">
                    第二组攻角序列（可空）
                    <input value={alphas2} onChange={(e) => setAlphas2(e.target.value)}
                      placeholder="留空则只画一组"
                      className="mt-0.5 w-full text-xs px-2 py-1 rounded border border-ink-200 font-mono" />
                  </label>
                </>
              )}
              {xKind === 'column' && (
                <div className="text-[10px] text-ink-400 leading-relaxed">
                  取 CN 为横轴、CD 为纵轴即阻力极曲线；CN 为横轴、MZG1 为纵轴，其斜率即纵向静稳定裕度。
                </div>
              )}
            </div>

            <div className="rounded-xl border border-ink-200 bg-white p-3">
              <div className="text-xs font-medium text-ink-700 mb-1.5">纵轴（可多选）</div>
              <div className="max-h-44 overflow-y-auto space-y-0.5 pr-1">
                {(runs?.columns ?? []).filter((c) => c.key !== 'ALPHA').map((c) => (
                  <label key={c.key} className="flex items-center gap-1.5 px-1 py-0.5 rounded hover:bg-ink-50 cursor-pointer">
                    <input type="checkbox" checked={ys.includes(c.key)} className="accent-brand-600"
                      onChange={() => setYs(ys.includes(c.key) ? ys.filter((k) => k !== c.key) : [...ys, c.key])} />
                    <span className="text-[11px]">{c.label}</span>
                  </label>
                ))}
              </div>
            </div>

            <div className="rounded-xl border border-ink-200 bg-white p-3 space-y-2">
              <div className="text-xs font-medium text-ink-700">求差量</div>
              <div className="flex gap-1 text-xs">
                {(['value', 'delta', 'ratio'] as const).map((m) => (
                  <button key={m} onClick={() => setMode(m)}
                    className={`flex-1 px-1.5 py-1 rounded ${mode === m ? 'bg-brand-50 text-brand-700 ring-1 ring-brand-200' : 'text-ink-500 border border-ink-200'}`}>
                    {m === 'value' ? '原值' : m === 'delta' ? '差量' : '比值'}
                  </button>
                ))}
              </div>
              {mode !== 'value' && (
                <select value={baseline} onChange={(e) => setBaseline(e.target.value)}
                  className="w-full text-xs px-2 py-1 rounded border border-ink-200 bg-white">
                  <option value="">选择基准车次…</option>
                  {sel.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              )}
              {mode === 'delta' && (
                <div className="text-[10px] text-ink-400 leading-relaxed">
                  以 δ 全零车次为基准时，差量即该舵面的操纵增量 —— 这正是舵效试验要测的量。
                </div>
              )}
            </div>

            {xKind === 'column' && (
              <div className="rounded-xl border border-ink-200 bg-white p-3">
                <div className="text-xs font-medium text-ink-700 mb-1.5">曲线排序</div>
                <div className="flex flex-wrap gap-1">
                  {(runs?.state_vars ?? []).map((v) => (
                    <button key={v.key}
                      onClick={() => setSortBy(sortBy.includes(v.key)
                        ? sortBy.filter((k) => k !== v.key) : [...sortBy, v.key])}
                      className={`px-1.5 py-0.5 rounded text-[11px] ${sortBy.includes(v.key)
                        ? 'bg-brand-50 text-brand-700 ring-1 ring-brand-200' : 'text-ink-500 border border-ink-200'}`}>
                      {v.label.split(' ')[0]}
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div className="flex gap-2">
              <button onClick={draw} disabled={busy === 'draw'}
                className="flex-1 px-3 py-1.5 rounded-lg bg-brand-600 text-white text-sm inline-flex items-center justify-center gap-1.5 disabled:opacity-50">
                {busy === 'draw' ? <Loader2 className="w-4 h-4 animate-spin" /> : <BarChart3 className="w-4 h-4" />} 绘图
              </button>
              <button onClick={exportCsv} disabled={busy === 'csv' || !chart}
                className="px-3 py-1.5 rounded-lg border border-ink-200 text-ink-600 text-sm inline-flex items-center gap-1.5 disabled:opacity-40"
                title="保存数据（CSV，Excel 可直接打开）">
                {busy === 'csv' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── 状态矩阵 ── */}
      {pane === 'matrix' && matrix && (
        <div className="space-y-3">
          {/* Plan vs actual. Nothing in the run files can tell you a run is
              missing — only the 车次表 can. */}
          {cov?.ok ? (
            <div className="rounded-xl border border-ink-200 bg-white p-3 space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-ink-800">计划与实到核对</span>
                <span className="text-[11px] text-ink-400">来源：{cov.plan_source}</span>
              </div>
              <div className="text-xs text-ink-700">{cov.headline}</div>
              {cov.state_check && (
                <div className="text-[11px] text-emerald-700">✓ {cov.state_check}</div>
              )}
              {!!cov.missing?.length && (
                <div className="text-xs">
                  <div className="font-medium text-amber-800 mb-0.5">计划内但没有数据</div>
                  <ul className="list-disc pl-4 space-y-0.5 text-ink-600">
                    {cov.missing.map((m) => (
                      <li key={m.run_no}>
                        <span className="font-mono">{m.run_no}</span>
                        （Ma={m.mach ?? '?'}，{m.label}）{m.note ? ` — ${m.note}` : ''}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {!!cov.superseded?.length && (
                <div className="text-xs">
                  <div className="font-medium text-ink-700 mb-0.5">重做前的废弃车次（属正常）</div>
                  <ul className="list-disc pl-4 space-y-0.5 text-ink-500">
                    {cov.superseded.map((m) => (
                      <li key={m.run_no}>{m.note}</li>
                    ))}
                  </ul>
                </div>
              )}
              {!!cov.state_mismatches?.length && (
                <div className="text-xs">
                  <div className="font-medium text-red-700 mb-0.5">文件状态与车次表不一致</div>
                  <ul className="list-disc pl-4 space-y-0.5 text-ink-600">
                    {cov.state_mismatches.map((m) => <li key={m.run_no}>{m.note}</li>)}
                  </ul>
                </div>
              )}
              {!!cov.notes?.length && (
                <div className="text-[11px] text-ink-500">
                  车次表备注：{cov.notes.join('；')}
                </div>
              )}
            </div>
          ) : (
            <div className="text-[11px] text-ink-400">
              {cov?.error ?? '未导入车次表，无法核对计划与实到。'}
            </div>
          )}
          <p className="text-xs text-ink-500">
            {matrix.block_count} 个 (Ma, β) 区块。{matrix.note}
            {matrix.without_baseline.length > 0 && (
              <span className="text-amber-700"> 缺基准的区块：{matrix.without_baseline.join('、')}</span>
            )}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-ink-500 border-b border-ink-200">
                <tr>
                  <th className="text-left py-1.5">区块</th><th className="text-left">车次数</th>
                  <th className="text-left">基准车次</th><th className="text-left">δz 覆盖</th>
                  <th className="text-left">δy 覆盖</th><th className="text-left">δx 覆盖</th>
                </tr>
              </thead>
              <tbody>
                {matrix.blocks.map((b) => (
                  <tr key={b.label} className="border-b border-ink-50">
                    <td className="py-1.5 text-ink-800">{b.label}</td>
                    <td>{b.run_count}</td>
                    <td className="font-mono">{b.baseline_run ?? <span className="text-amber-600">无</span>}</td>
                    <td className="font-mono text-[11px]">{b.dz.join(' ')}</td>
                    <td className="font-mono text-[11px]">{b.dy.join(' ')}</td>
                    <td className="font-mono text-[11px]">{b.dx.join(' ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── 舵效 ── */}
      {(pane === 'effect' || pane === 'symmetry') && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-ink-600">舵面</span>
            {(['dz', 'dy', 'dx'] as const).map((s) => (
              <button key={s} onClick={() => setSurface(s)}
                className={`px-2 py-1 rounded text-xs ${surface === s ? 'bg-brand-50 text-brand-700 ring-1 ring-brand-200' : 'text-ink-500 border border-ink-200'}`}>
                {s === 'dz' ? '升降舵 δz' : s === 'dy' ? '方向舵 δy' : '副翼 δx'}
              </button>
            ))}
            <span className="text-xs text-ink-600 ml-2">攻角</span>
            <input value={alphas} onChange={(e) => setAlphas(e.target.value)}
              className="w-28 text-xs px-2 py-1 rounded border border-ink-200 font-mono" />
            <button onClick={() => runAnalysis(pane === 'effect' ? 'effect' : 'symmetry')}
              disabled={!!busy}
              className="px-3 py-1.5 rounded-lg bg-brand-600 text-white text-sm inline-flex items-center gap-1.5 disabled:opacity-50">
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />} 计算
            </button>
          </div>

          {pane === 'effect' && resp && (
            <div className="rounded-xl border border-ink-200 bg-white p-3">
              <div className="text-sm font-medium text-ink-800 mb-1">舵偏响应（各 (Ma,β) 区块）</div>
              <p className="text-[11px] text-ink-500 mb-2">{resp.method}</p>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="text-ink-500 border-b border-ink-200">
                    <tr>
                      <th className="text-left py-1">Ma</th><th className="text-left">β</th>
                      <th className="text-left">系数</th><th className="text-left">基准车次</th>
                      <th className="text-left">线性段导数/度</th><th className="text-left">最大舵偏</th>
                      <th className="text-left">饱和比</th><th className="text-left">舵偏序列</th>
                    </tr>
                  </thead>
                  <tbody>
                    {resp.blocks.map((b, i) => (
                      <tr key={i} className="border-b border-ink-50">
                        <td className="py-1">{fmt(b.mach)}</td><td>{fmt(b.beta)}</td>
                        <td>{b.coefficient}</td><td className="font-mono">{b.baseline_run}</td>
                        <td className="font-mono">{fmt(b.linear_slope_per_deg, 5)}</td>
                        <td>{fmt(b.max_deflection)}°</td>
                        <td className={b.saturation_ratio != null && b.saturation_ratio < 0.8 ? 'text-amber-700' : ''}>
                          {fmt(b.saturation_ratio, 3)}
                        </td>
                        <td className="font-mono text-[10px]">{b.deflections.join(' ')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
          {pane === 'effect' && eff && (
            <div className="rounded-xl border border-ink-200 bg-white p-3">
              <div className="text-sm font-medium text-ink-800 mb-1">
                操纵增量明细（{eff.rows.length} 条）
              </div>
              <p className="text-[11px] text-ink-500 mb-2">{eff.method}</p>
              <div className="max-h-96 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead className="text-ink-500 border-b border-ink-200 sticky top-0 bg-white">
                    <tr>
                      <th className="text-left py-1">车次</th><th className="text-left">Ma</th>
                      <th className="text-left">β</th><th className="text-left">α</th>
                      <th className="text-left">舵偏</th><th className="text-left">系数</th>
                      <th className="text-left">Δ</th><th className="text-left">Δ/Δδ</th>
                    </tr>
                  </thead>
                  <tbody>
                    {eff.rows.slice(0, 400).map((r, i) => (
                      <tr key={i} className="border-b border-ink-50">
                        <td className="py-1 font-mono">{r.run_no}</td>
                        <td>{fmt(r.mach)}</td><td>{fmt(r.beta)}</td><td>{fmt(r.alpha)}</td>
                        <td>{r.deflection > 0 ? '+' : ''}{r.deflection}°</td>
                        <td>{r.coefficient}</td>
                        <td className="font-mono">{fmt(r.delta, 5)}</td>
                        <td className="font-mono">{fmt(r.derivative_per_deg, 5)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {pane === 'symmetry' && sym && (
            <div className="rounded-xl border border-ink-200 bg-white p-3">
              <div className="text-sm font-medium text-ink-800 mb-1">±舵偏对称性</div>
              <p className="text-xs text-ink-700 mb-1">{sym.note}</p>
              <p className="text-[11px] text-ink-500 mb-2">{sym.method}</p>
              <div className="max-h-96 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead className="text-ink-500 border-b border-ink-200 sticky top-0 bg-white">
                    <tr>
                      <th className="text-left py-1">Ma</th><th className="text-left">β</th>
                      <th className="text-left">α</th><th className="text-left">±δ</th>
                      <th className="text-left">Δ(+)</th><th className="text-left">Δ(−)</th>
                      <th className="text-left">不对称度</th><th className="text-left">σ</th>
                      <th className="text-left">车次</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...sym.pairs].sort((a, b) => b.asymmetry - a.asymmetry).slice(0, 200).map((p, i) => (
                      <tr key={i} className={`border-b border-ink-50 ${p.flagged ? 'bg-amber-50' : ''}`}>
                        <td className="py-1">{fmt(p.mach)}</td><td>{fmt(p.beta)}</td>
                        <td>{fmt(p.alpha)}</td><td>±{p.deflection}°</td>
                        <td className="font-mono">{fmt(p.delta_pos, 5)}</td>
                        <td className="font-mono">{fmt(p.delta_neg, 5)}</td>
                        <td className={p.flagged ? 'text-amber-800 font-medium' : ''}>
                          {(p.asymmetry * 100).toFixed(1)}%
                        </td>
                        <td>{p.score ?? '—'}</td>
                        <td className="font-mono text-[10px]">{p.run_pos}/{p.run_neg}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

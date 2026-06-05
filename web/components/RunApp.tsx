'use client';

import { useEffect, useMemo, useState } from 'react';
import { Play, Loader2, CheckCircle2, AlertTriangle, GitBranch, ArrowRight, ChevronLeft, Database, Sparkles, Workflow, BarChart3 } from 'lucide-react';
import { api, type Algorithm, type Dataset, type FlowTemplate, type TemplateRunResult } from '@/lib/api';
import { ALGO_ZH, coerceParam, cellStr } from '@/lib/algoMeta';
import ParamField from '@/components/ParamField';
import DatasetChart from '@/components/DatasetChart';

/**
 * "Mini-program" run mode for a flow template (Pillar 4): a non-expert opens a
 * crystallized flow, picks a dataset, fills only the runtime params the author
 * exposed, hits run — and gets the result PLUS the visible provenance (each
 * step's algorithm + status + the derived-dataset chain). No canvas, no palette.
 * Reuses the same backend replay (with param_overrides) the editor uses.
 */
export default function RunApp({ tpl, datasets, algos, onBack }: {
  tpl: FlowTemplate; datasets: Dataset[]; algos: Algorithm[]; onBack: () => void;
}) {
  const bySlug = useMemo(() => new Map(algos.map((a) => [a.slug, a])), [algos]);
  const runtime = useMemo(() => (tpl.graph?.runtime ?? []).filter((r) => typeof r.stepIndex === 'number' && r.stepIndex >= 0), [tpl]);

  const [datasetId, setDatasetId] = useState<number | null>(datasets[0]?.id ?? null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<TemplateRunResult | null>(null);
  const [err, setErr] = useState('');
  // Which stage's data to show in the table (null = the final output). Lets you
  // click any node in the provenance chain to inspect that stage's data.
  const [stage, setStage] = useState<{ id: number; label: string; total: number; columns: string[]; rows: Record<string, unknown>[]; loading: boolean } | null>(null);

  async function openStage(id: number, label: string) {
    setStage({ id, label, total: 0, columns: [], rows: [], loading: true });
    try { const p = await api.datasetPreview(id, 50); setStage({ id, label, total: p.total, columns: p.columns, rows: p.rows, loading: false }); }
    catch { setStage(null); }
  }

  useEffect(() => { if (datasetId == null && datasets[0]) setDatasetId(datasets[0].id); }, [datasets, datasetId]);
  // Seed the form with each runtime param's saved default.
  useEffect(() => {
    const init: Record<string, string> = {};
    for (const r of runtime) {
      const d = r.default;
      init[`${r.stepIndex}::${r.param}`] = d == null ? '' : Array.isArray(d) ? d.join(', ') : String(d);
    }
    setValues(init);
  }, [runtime]);

  const runDs = datasets.find((d) => d.id === datasetId) ?? null;
  const cols = (runDs?.schema?.columns ?? []).map((c) => c.name);
  const stepCols = res?.final?.preview?.[0] ? Object.keys(res.final.preview[0]) : [];
  const [showChart, setShowChart] = useState(false);
  // The dataset id behind the final output (last non-report stage).
  const finalDsId = useMemo(() => {
    if (!res) return null;
    const last = [...(res.derived_chain ?? [])].reverse().find((d) => !d.report);
    return last?.id ?? res.new_dataset?.id ?? null;
  }, [res]);
  const chartDsId = stage ? stage.id : finalDsId;
  const chartName = stage ? stage.label : '最终输出';

  async function run() {
    if (datasetId == null) return;
    setBusy(true); setErr(''); setRes(null);
    const overrides: Record<string, Record<string, unknown>> = {};
    for (const r of runtime) {
      const spec = bySlug.get(r.slug ?? '')?.params_schema?.[r.param];
      const raw = values[`${r.stepIndex}::${r.param}`] ?? '';
      const v = spec ? coerceParam(spec, raw) : (raw || undefined);
      (overrides[String(r.stepIndex)] ??= {})[r.param] = v;
    }
    setStage(null);
    try { setRes(await api.runTemplate(tpl.id, datasetId, true, overrides)); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  }

  return (
    <div className="h-full overflow-y-auto scroll-hide bg-ink-50/40">
      <div className="max-w-2xl mx-auto p-6 space-y-4">
        <button onClick={onBack} className="text-xs text-ink-500 hover:text-ink-800 flex items-center gap-1"><ChevronLeft className="w-3.5 h-3.5" /> 返回画布编辑</button>

        <div className="bg-white rounded-2xl ring-1 ring-ink-200 p-5">
          <div className="flex items-center gap-2.5">
            <span className="grid place-items-center w-9 h-9 rounded-xl bg-brand-50 text-brand-600 shrink-0"><Workflow className="w-4.5 h-4.5" /></span>
            <div className="min-w-0">
              <h2 className="text-lg font-semibold truncate">{tpl.name}</h2>
              <p className="text-xs text-ink-500">{tpl.description || `${tpl.n_steps} 步分析流程`}</p>
            </div>
          </div>
        </div>

        {/* 1. data */}
        <div className="bg-white rounded-2xl ring-1 ring-ink-200 p-5 space-y-2">
          <div className="text-sm font-medium flex items-center gap-1.5"><Database className="w-4 h-4 text-emerald-500" /> 1. 选择数据</div>
          <select value={datasetId ?? ''} onChange={(e) => setDatasetId(e.target.value ? Number(e.target.value) : null)}
            className="w-full border border-ink-200 rounded-lg px-2.5 py-2 bg-white text-sm focus:outline-none focus:border-brand-400">
            <option value="">（选择数据集）</option>
            {datasets.map((d) => <option key={d.id} value={d.id}>{d.name}（{d.rows.toLocaleString()} × {d.columns}）</option>)}
          </select>
        </div>

        {/* 2. params (only the ones the author exposed) */}
        {runtime.length > 0 && (
          <div className="bg-white rounded-2xl ring-1 ring-ink-200 p-5 space-y-3">
            <div className="text-sm font-medium flex items-center gap-1.5"><Sparkles className="w-4 h-4 text-amber-500" /> 2. 填写参数</div>
            {runtime.map((r) => {
              const spec = bySlug.get(r.slug ?? '')?.params_schema?.[r.param];
              const key = `${r.stepIndex}::${r.param}`;
              return (
                <div key={key} className="rounded-lg ring-1 ring-ink-100 bg-ink-50/40 p-2.5">
                  <div className="text-[11px] text-ink-500 mb-1.5">{ALGO_ZH[r.slug ?? '']?.name ?? r.label ?? r.slug} · <span className="font-mono text-ink-400">{r.param}</span></div>
                  {spec ? (
                    <ParamField name={r.param} spec={spec} cols={cols} value={values[key] ?? ''}
                      onChange={(v) => setValues((s) => ({ ...s, [key]: v }))} />
                  ) : (
                    <input value={values[key] ?? ''} onChange={(e) => setValues((s) => ({ ...s, [key]: e.target.value }))}
                      className="w-full border border-ink-200 rounded-lg px-2 py-1.5 bg-white text-sm font-mono" />
                  )}
                </div>
              );
            })}
          </div>
        )}

        <button onClick={run} disabled={busy || datasetId == null}
          className="w-full px-4 py-3 rounded-xl bg-brand-600 text-white font-medium hover:bg-brand-700 transition-colors flex items-center justify-center gap-2 disabled:opacity-50">
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />} 运行
        </button>

        {err && <div className="text-sm text-red-700 bg-red-50 ring-1 ring-red-100 rounded-lg px-3 py-2 flex items-start gap-2"><AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" /><span className="whitespace-pre-wrap">{err}</span></div>}

        {res && (
          <div className="bg-white rounded-2xl ring-1 ring-ink-200 p-5 space-y-3">
            <div className="flex items-center gap-2">
              <div className="text-sm font-medium">结果</div>
              {chartDsId != null && (
                <button onClick={() => setShowChart((v) => !v)}
                  className={`ml-auto inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-lg ring-1 ${showChart ? 'bg-brand-600 text-white ring-transparent' : 'ring-brand-200 text-brand-700 hover:bg-brand-50'}`}>
                  <BarChart3 className="w-3.5 h-3.5" /> {showChart ? '收起图表' : '可视化'}
                </button>
              )}
            </div>
            {showChart && chartDsId != null && (
              <div className="rounded-lg ring-1 ring-ink-200 p-2">
                <DatasetChart datasetId={chartDsId} name={chartName} />
              </div>
            )}
            {/* provenance: each step's algorithm + status — the verifiable trail */}
            <div className="rounded-lg ring-1 ring-ink-200 divide-y divide-ink-100 overflow-hidden">
              {res.steps.map((s) => (
                <div key={s.i} className="px-2.5 py-1.5 flex items-center gap-2 text-xs">
                  {s.status === 'ok' ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
                    : s.status === 'skipped' ? <span className="w-3.5 h-3.5 grid place-items-center text-ink-300 shrink-0">·</span>
                    : <AlertTriangle className="w-3.5 h-3.5 text-red-500 shrink-0" />}
                  <span className="font-medium text-ink-700 truncate">{s.label}</span>
                  {s.report && <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-sky-50 text-sky-600 ring-1 ring-sky-100 shrink-0">报告</span>}
                  {typeof s.rows === 'number' && s.rows > 0 && <span className="text-ink-400 shrink-0 ml-auto">{s.rows.toLocaleString()} 行</span>}
                  {s.error && <span className="text-red-600 truncate ml-auto">{s.error}</span>}
                </div>
              ))}
            </div>
            {res.derived_chain && res.derived_chain.length > 0 && (
              <div className="text-xs bg-violet-50/70 ring-1 ring-violet-100 rounded-lg px-3 py-2.5">
                <div className="text-violet-700 font-medium mb-2 flex items-center gap-1.5"><GitBranch className="w-3.5 h-3.5" /> 处理过程(可追溯)<span className="text-violet-400 font-normal">—— 点任意阶段查看那一步的数据</span></div>
                <div className="flex flex-wrap items-center gap-1.5">
                  {runDs && (
                    <button onClick={() => openStage(runDs.id, '原始')}
                      className={`px-2 py-0.5 rounded-md bg-white ring-1 hover:bg-ink-50 ${stage?.id === runDs.id ? 'ring-ink-400 text-ink-800' : 'ring-ink-200 text-ink-600'}`}>原始</button>
                  )}
                  {res.derived_chain.map((d) => (
                    <span key={d.id} className="inline-flex items-center gap-1.5">
                      <ArrowRight className="w-3 h-3 text-violet-300" />
                      <button onClick={() => openStage(d.id, d.label)}
                        className={`px-2 py-0.5 rounded-md bg-white ring-1 font-mono hover:brightness-95 ${stage?.id === d.id ? (d.report ? 'ring-sky-400 text-sky-700' : 'ring-violet-400 text-violet-800') : d.report ? 'ring-sky-200 text-sky-600' : 'ring-violet-200 text-violet-700'}`}>{d.label}</button>
                    </span>
                  ))}
                </div>
              </div>
            )}
            {/* Table: a clicked stage, else the final output */}
            {stage ? (
              <div>
                <div className="flex items-center gap-2 mb-1.5">
                  <div className="text-[11px] font-medium text-ink-600">查看「{stage.label}」· {stage.total.toLocaleString()} 行{stage.columns.length ? ` × ${stage.columns.length} 列` : ''}</div>
                  <button onClick={() => setStage(null)} className="ml-auto text-[11px] text-brand-600 hover:text-brand-700">← 回到最终输出</button>
                </div>
                <div className="rounded-lg ring-1 ring-violet-200 overflow-auto max-h-72">
                  {stage.loading ? (
                    <div className="p-5 text-center text-xs text-ink-400"><Loader2 className="w-4 h-4 animate-spin inline-block" /> 加载中…</div>
                  ) : (
                    <table className="text-xs min-w-full">
                      <thead className="bg-ink-50 text-ink-500 sticky top-0"><tr>{stage.columns.map((c) => <th key={c} className="text-left py-2 px-3 font-medium whitespace-nowrap">{c}</th>)}</tr></thead>
                      <tbody>
                        {stage.rows.map((row, i) => (
                          <tr key={i} className="border-t border-ink-100">{stage.columns.map((c) => <td key={c} className="py-1.5 px-3 font-mono whitespace-nowrap">{cellStr(row[c])}</td>)}</tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              </div>
            ) : res.final.preview.length > 0 && (
              <div>
                <div className="text-[11px] font-medium text-ink-600 mb-1.5">最终输出 · {res.final.rows.toLocaleString()} 行 × {res.final.columns.length} 列</div>
                <div className="rounded-lg ring-1 ring-ink-200 overflow-auto max-h-72">
                  <table className="text-xs min-w-full">
                    <thead className="bg-ink-50 text-ink-500 sticky top-0"><tr>{stepCols.map((c) => <th key={c} className="text-left py-2 px-3 font-medium whitespace-nowrap">{c}</th>)}</tr></thead>
                    <tbody>
                      {res.final.preview.map((row, i) => (
                        <tr key={i} className="border-t border-ink-100">{stepCols.map((c) => <td key={c} className="py-1.5 px-3 font-mono whitespace-nowrap">{cellStr(row[c])}</td>)}</tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

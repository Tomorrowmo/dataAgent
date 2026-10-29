'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Sparkles, CheckCircle2, AlertTriangle, Loader2, Play, Save, Workflow, Trash2, ArrowRight, Database, GitBranch, Table2, ChevronDown, ChevronRight, Plus, BarChart3, Upload, Search, Code2, Copy } from 'lucide-react';
import { api, type Algorithm, type Dataset, type RunResult, type ParamSpec, type FlowTemplate } from '@/lib/api';
import { useT } from '@/lib/i18n';
import ParamField from '@/components/ParamField';
import dynamic from 'next/dynamic';
// @xyflow/react is browser-only — client-only load to keep it out of SSR.
const FlowCanvas = dynamic(() => import('@/components/FlowCanvas'), { ssr: false });
import AlgoStudio from '@/components/AlgoStudio';
import AlgoEditor, { type EditorTarget } from '@/components/AlgoEditor';
import RunApp from '@/components/RunApp';
import DatasetChart from '@/components/DatasetChart';
import { SOURCE_ZH, RETURNS_ZH, dispName, dispDesc, dispExample, catZh, cellStr, groupByIntent, matchAlgo, intentZh, algoIntent, intentIcon } from '@/lib/algoMeta';

// The 算法库 view: a single left list (two pinned entries 上传/AI + the
// intent-grouped algorithms) and a right area that shows the selected thing.
// 流程模板 is now its own top-level view (see TemplatesView, used by page.tsx).
export default function AlgorithmsView({ focusAlgo, active = true }: { focusAlgo?: { slug: string; nonce: number } | null; active?: boolean }) {
  const t = useT();
  return <LibraryView t={t} focusAlgo={focusAlgo ?? null} active={active} />;
}

export function TemplatesView() {
  const [tpls, setTpls] = useState<FlowTemplate[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [algos, setAlgos] = useState<Algorithm[]>([]);
  const [selId, setSelId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [mode, setMode] = useState<'edit' | 'run'>('edit');

  function refresh(selectId?: number) {
    api.listTemplates().then((ts) => {
      setTpls(ts);
      setSelId((cur) => selectId ?? (cur && ts.some((t) => t.id === cur) ? cur : ts[0]?.id ?? null));
    }).catch(() => {});
  }
  useEffect(() => {
    refresh();
    api.listDatasets().then(setDatasets).catch(() => {});
    api.listAlgorithms().then(setAlgos).catch(() => {});
  }, []);

  async function createBlank() {
    const name = window.prompt('新流程名称:', '新流程');
    if (!name) return;
    setCreating(true);
    try { const t = await api.createTemplate(name, [], '在画布上自由编排的流程'); refresh(t.id); }
    catch { /* ignore */ } finally { setCreating(false); }
  }

  const selected = tpls.find((t) => t.id === selId) ?? null;

  return (
    <div className="flex h-full">
      {/* master list — full-width on mobile (hidden once a template is picked) */}
      <div className={`w-full md:w-[240px] shrink-0 border-r border-ink-200 bg-ink-50/40 flex flex-col ${selId ? 'max-md:hidden' : ''}`}>
        <div className="p-3 border-b border-ink-200">
          <button onClick={createBlank} disabled={creating}
            className="w-full flex items-center justify-center gap-1.5 bg-brand-600 text-white text-sm px-3 py-2 rounded-lg hover:bg-brand-700 disabled:opacity-50">
            <Plus className="w-4 h-4" /> 新建流程
          </button>
        </div>
        <div className="flex-1 overflow-y-auto scroll-hide p-2 space-y-1.5">
          {tpls.length === 0 && (
            <div className="text-xs text-ink-400 text-center px-3 py-6">还没有流程模板。<br />「新建流程」开始拖拽编排,或在对话「流程图」里保存。</div>
          )}
          {tpls.map((tp) => (
            <button key={tp.id} onClick={() => setSelId(tp.id)}
              className={`w-full text-left rounded-lg p-2.5 ring-1 transition ${selId === tp.id ? 'bg-brand-50 ring-brand-300' : 'bg-white ring-ink-200 hover:ring-brand-200'}`}>
              <div className="flex items-center gap-1.5"><Workflow className="w-3.5 h-3.5 text-brand-600 shrink-0" /><span className="font-medium text-sm truncate">{tp.name}</span></div>
              <div className="text-[11px] text-ink-400 mt-0.5">{tp.n_steps} 步</div>
            </button>
          ))}
        </div>
      </div>
      {/* detail: free-form canvas (edit) or mini-program (run). On mobile hidden
          until a template is picked, then full-screen with a back button. */}
      <div className={`flex-1 min-w-0 flex flex-col ${selId ? '' : 'max-md:hidden'}`}>
        {selected ? (
          <>
            {/* mobile back to list */}
            <button onClick={() => setSelId(null)}
              className="md:hidden w-full text-left px-4 py-2.5 bg-white border-b border-ink-200 text-sm text-brand-600 font-medium">
              ← 返回流程列表
            </button>
            <div className="border-b border-ink-200 bg-white px-3 py-1.5 flex items-center gap-2">
              <div className="inline-flex rounded-lg ring-1 ring-ink-200 overflow-hidden text-xs">
                <button onClick={() => setMode('edit')} className={mode === 'edit' ? 'bg-brand-600 text-white px-2.5 py-1' : 'px-2.5 py-1 text-ink-600 hover:bg-ink-50'}>编辑画布</button>
                <button onClick={() => setMode('run')} className={mode === 'run' ? 'bg-brand-600 text-white px-2.5 py-1' : 'px-2.5 py-1 text-ink-600 hover:bg-ink-50'}>运行 · 小程序</button>
              </div>
              <span className="text-[11px] text-ink-400">运行模式 = 给非专家用:选数据 + 填参数 + 跑,并看到可信的处理过程</span>
            </div>
            <div className="flex-1 min-h-0">
              {mode === 'edit' ? (
                <FlowCanvas key={selected.id} tpl={selected} datasets={datasets} algos={algos}
                  onChanged={() => refresh(selected.id)} onDeleted={() => refresh()} />
              ) : (
                <RunApp key={'run-' + selected.id} tpl={selected} datasets={datasets} algos={algos} onBack={() => setMode('edit')} />
              )}
            </div>
          </>
        ) : (
          <div className="h-full grid place-items-center text-sm text-ink-400 p-6 text-center">
            选择左侧的流程在<b className="mx-1">自由画布</b>上编辑,或「新建流程」开始拖拽编排。
          </div>
        )}
      </div>
    </div>
  );
}

type Sel = Algorithm | 'upload' | 'ai' | null;
const isAlgoSel = (s: Sel): s is Algorithm => !!s && typeof s === 'object';

/** Editor target for an algorithm: built-ins open read-only (source + "复制为我的
 *  算法"), user / AI algorithms open editable. */
const editorFor = (a: Algorithm): EditorTarget =>
  a.source === 'builtin' || a.id == null ? { mode: 'builtin', slug: a.slug } : { mode: 'edit', algoId: a.id };

/** Wide enough (Tailwind xl) for run panel + editor side by side. */
const sideBySide = () => typeof window !== 'undefined' && window.matchMedia('(min-width: 1280px)').matches;

function LibraryView({ t, focusAlgo, active }: { t: (k: string) => string; focusAlgo: { slug: string; nonce: number } | null; active: boolean }) {
  const [algos, setAlgos] = useState<Algorithm[]>([]);
  const [q, setQ] = useState('');
  const [selected, setSelected] = useState<Sel>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());   // collapsed intent groups
  const toggleGroup = (k: string) => setCollapsed((s) => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n; });

  // 代码编辑器弹窗 + a revision counter so the run panel remounts (fresh params
  // schema) after its algorithm was edited.
  const [editor, setEditor] = useState<EditorTarget | null>(null);
  const [rev, setRev] = useState(0);
  const editorDirty = useRef(false);
  // Picking something else in the list closes the inline editor — ask first if
  // it holds unsaved edits.
  const pick = (s: Sel) => {
    if (editor && editorDirty.current && !window.confirm('编辑器里有未保存的改动，确定离开？')) return;
    editorDirty.current = false;
    // The code sits open beside the run panel by default. Below xl the editor
    // would cover the run panel entirely, so there it stays one click away.
    setEditor(isAlgoSel(s) && sideBySide() ? editorFor(s) : null);
    setSelected(s);
  };

  const reload = (selectId?: number) => api.listAlgorithms().then((as) => {
    setAlgos(as);
    if (selectId != null) { const hit = as.find((a) => a.id === selectId); if (hit) setSelected(hit); }
    setRev((r) => r + 1);
  }).catch(() => {});
  useEffect(() => { reload(); }, []);
  // Kept mounted while hidden: refresh the list each time the tab comes back
  // (the chat may have created tools meanwhile) — selection and any studio work stay.
  const wasActive = useRef(active);
  useEffect(() => {
    if (active && !wasActive.current) api.listAlgorithms().then(setAlgos).catch(() => {});
    wasActive.current = active;
  }, [active]);

  // Jump-in from chat (an AI-built tool's "在编辑器中打开"): select that algorithm
  // and open its code editor once the list is loaded.
  const handledFocus = useRef<number | null>(null);
  useEffect(() => {
    if (!focusAlgo || handledFocus.current === focusAlgo.nonce || algos.length === 0) return;
    const hit = algos.find((a) => a.slug === focusAlgo.slug && a.id != null);
    if (!hit) return;
    handledFocus.current = focusAlgo.nonce;
    setSelected(hit);
    setEditor({ mode: 'edit', algoId: hit.id! });
  }, [focusAlgo, algos]);
  const isSel = (a: Algorithm) => isAlgoSel(selected) && selected.slug === a.slug && selected.id === a.id;

  const searching = q.trim().length > 0;
  const hits = searching ? algos.filter((a) => matchAlgo(a, q)) : [];
  const groups = searching ? [] : groupByIntent(algos);   // 改法 A + D

  const showDetail = selected !== null || editor !== null;
  return (
    <div className="flex h-full">
      {/* Left list: full-width on mobile (hidden once something is picked);
          fixed column on desktop. */}
      <div className={`w-full md:w-[300px] shrink-0 border-r border-ink-200 flex flex-col bg-ink-50/40 ${showDetail ? 'max-md:hidden' : ''}`}>
        <div className="p-3 border-b border-ink-200 space-y-2">
          {/* two prominent capability cards, side by side — extend the library */}
          <div className="grid grid-cols-2 gap-2">
            <EntryCard icon={<Upload className="w-4 h-4" />} label="上传自由算法" hint="贴代码即用" tone="emerald" sel={selected === 'upload'} onClick={() => pick('upload')} />
            <EntryCard icon={<Sparkles className="w-4 h-4" />} label="用 AI 生成" hint="描述就生成" tone="violet" sel={selected === 'ai'} onClick={() => pick('ai')} />
          </div>
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-ink-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="想做什么？例：去掉温度尖峰…"
              className="w-full border border-ink-200 rounded-lg pl-8 pr-2 py-1.5 bg-white text-xs focus:outline-none focus:border-brand-400" />
          </div>
        </div>
        <div className="flex-1 overflow-y-auto scroll-hide p-2">
          {searching ? (
            <div className="space-y-1.5">
              {hits.map((a) => <AlgoRow key={a.slug + (a.id ?? '')} a={a} sel={isSel(a)} onClick={() => pick(a)} />)}
              {hits.length === 0 && <div className="text-xs text-ink-400 text-center py-6">没有匹配的算法</div>}
            </div>
          ) : (
            groups.map((g) => {
              const open = !collapsed.has(g.key);
              return (
                <div key={g.key} className="mb-1.5">
                  <button onClick={() => toggleGroup(g.key)}
                    className="w-full flex items-center gap-1 px-1 py-1 text-[11px] font-medium text-ink-500 hover:text-ink-700">
                    {open ? <ChevronDown className="w-3 h-3 shrink-0" /> : <ChevronRight className="w-3 h-3 shrink-0" />}
                    <span>{g.label}</span>
                    <span className="text-ink-300">({g.items.length})</span>
                  </button>
                  {open && (
                    <div className="space-y-1 mt-0.5">
                      {g.items.map((a) => <AlgoRow key={a.slug + (a.id ?? '')} a={a} sel={isSel(a)} onClick={() => pick(a)} />)}
                    </div>
                  )}
                </div>
              );
            })
          )}
          {!searching && groups.length === 0 && <div className="text-xs text-ink-400 text-center py-6">暂无算法</div>}
        </div>
      </div>

      {/* Right: upload & AI forms stay MOUNTED (just hidden) so switching between
          them doesn't lose typed code / the AI description. Algo run panel and
          the empty hint render conditionally. On mobile this is hidden until
          something is picked (then full-screen with a back button). */}
      <div className={`flex-1 min-w-0 flex ${showDetail ? '' : 'max-md:hidden'}`}>
        {/* Detail / run column. With the editor open it narrows to the run panel's
            width and the 代码编辑器 fills the space beside it — edit on the right,
            run the saved version on the left. Below xl the editor takes the pane. */}
        <div className={`overflow-y-auto scroll-hide ${editor ? 'w-[44rem] max-w-[50%] shrink-0 max-xl:hidden' : 'flex-1 min-w-0'}`}>
          {showDetail && (
            <button onClick={() => pick(null)}
              className="md:hidden sticky top-0 z-10 w-full text-left px-4 py-2.5 bg-white border-b border-ink-200 text-sm text-brand-600 font-medium">
              ← 返回列表
            </button>
          )}
          <div className={selected === 'upload' ? 'h-full' : 'hidden'}><AlgoStudio start="upload" onSaved={() => reload()} /></div>
          <div className={selected === 'ai' ? 'h-full' : 'hidden'}><AlgoStudio start="ai" onSaved={() => reload()} /></div>
          {isAlgoSel(selected) && <RunPanel key={selected.slug + (selected.id ?? '') + ':' + rev} algo={selected} t={t} onOpenEditor={setEditor} />}
          {selected === null && !editor && (
            <div className="h-full grid place-items-center text-sm text-ink-400 px-6 text-center">
              ← 从左侧选一个算法（或上面的「上传自由算法 / 用 AI 生成」）;在这里填参数、选数据、直接运行
            </div>
          )}
        </div>
        {editor && (
          <div className="flex-1 min-w-0 border-l border-ink-200">
            <AlgoEditor key={JSON.stringify(editor).slice(0, 200)} target={editor}
              onClose={() => { setEditor(null); editorDirty.current = false; }}
              onDirtyChange={(d) => { editorDirty.current = d; }}
              onSaved={(a) => reload(a.id)}
              onDeleted={() => { setEditor(null); editorDirty.current = false; setSelected(null); reload(); }} />
          </div>
        )}
      </div>
    </div>
  );
}

/** A prominent capability card above the algorithm list (上传自由算法 / 用 AI 生成)
 *  — these EXTEND the library, so they get emphasis (colored chip + gradient +
 *  hover-lift) to stand out from the plain algorithm rows. Selected like an
 *  algorithm; the right area then shows its form. */
function EntryCard({ icon, label, hint, tone, sel, onClick }: {
  icon: React.ReactNode; label: string; hint: string; tone: 'emerald' | 'violet'; sel: boolean; onClick: () => void;
}) {
  const a = tone === 'emerald'
    ? { grad: 'from-emerald-50', chip: 'bg-emerald-100 text-emerald-700', ring: 'ring-emerald-200', selRing: 'ring-emerald-400' }
    : { grad: 'from-violet-50', chip: 'bg-violet-100 text-violet-700', ring: 'ring-violet-200', selRing: 'ring-violet-400' };
  return (
    <button onClick={onClick}
      className={`rounded-xl p-2.5 transition text-left flex flex-col gap-1.5 hover:-translate-y-0.5 hover:shadow-sm bg-gradient-to-br ${a.grad} to-white ${
        sel ? `ring-2 ${a.selRing}` : `ring-1 ${a.ring} hover:ring-2`
      }`}>
      <span className={`w-8 h-8 rounded-lg grid place-items-center ${a.chip}`}>{icon}</span>
      <span className="font-semibold text-[13px] leading-tight text-ink-800">{label}</span>
      <span className="text-[10.5px] text-ink-400 leading-tight">{hint}</span>
    </button>
  );
}

/** One algorithm row — compact (name + source badge only). The explanation
 *  (description + example) appears in a hover card to the row's right, portaled
 *  to <body> so the narrow scrollable sidebar doesn't clip it. */
function AlgoRow({ a, sel, onClick }: { a: Algorithm; sel: boolean; onClick: () => void }) {
  const ref = useRef<HTMLButtonElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const show = () => {
    const r = ref.current?.getBoundingClientRect();
    if (r) setPos({ top: Math.min(r.top, window.innerHeight - 170), left: r.right + 8 });
  };
  return (
    <>
      <button
        ref={ref}
        onClick={onClick}
        onMouseEnter={show}
        onMouseLeave={() => setPos(null)}
        className={`w-full text-left rounded-lg px-2.5 py-1.5 ring-1 transition flex items-center gap-2 ${sel ? 'bg-brand-50 ring-brand-300' : 'bg-white ring-ink-200 hover:ring-brand-300'}`}
      >
        <span className="shrink-0 text-[15px] leading-none">{intentIcon(algoIntent(a))}</span>
        <span className="font-medium text-sm truncate flex-1">{dispName(a)}</span>
        <span className={`shrink-0 text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${
          a.source === 'builtin' ? 'bg-ink-100 text-ink-600' : a.source === 'ai' ? 'bg-purple-100 text-purple-700' : 'bg-emerald-100 text-emerald-700'
        }`}>{SOURCE_ZH[a.source] ?? a.source}</span>
      </button>
      {pos && createPortal(
        <div
          style={{ position: 'fixed', top: pos.top, left: pos.left, zIndex: 60 }}
          className="w-64 rounded-xl bg-white ring-1 ring-ink-200 shadow-xl p-3 pointer-events-none"
        >
          <div className="font-medium text-sm mb-1">{dispName(a)}</div>
          <div className="text-[12px] text-ink-600 leading-relaxed">{dispDesc(a)}</div>
          {dispExample(a).startsWith('例') && <div className="text-[11px] text-ink-400 mt-1.5">{dispExample(a)}</div>}
          <div className="text-[10px] text-ink-300 font-mono mt-1.5">{a.slug} · {intentZh(algoIntent(a))}</div>
        </div>,
        document.body,
      )}
    </>
  );
}

/** Manual tool runner (inline, no modal) — pick a dataset + fill params
 *  (auto-generated from the schema) + execute. Pure compute, NO AI involved. */
function RunPanel({ algo, t, onOpenEditor }: { algo: Algorithm; t: (k: string) => string; onOpenEditor: (target: EditorTarget) => void }) {
  const schema = algo.params_schema || {};
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [datasetId, setDatasetId] = useState<number | null>(null);
  const [params, setParams] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    for (const [k, sp] of Object.entries(schema)) {
      const d = (sp as ParamSpec).default;
      init[k] = d === undefined || d === null ? '' : Array.isArray(d) ? d.join(', ') : String(d);
    }
    return init;
  });
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<RunResult | null>(null);
  const [error, setError] = useState('');
  // Natural-language assist: fills the form (you still review + run).
  const [intent, setIntent] = useState('');
  const [suggesting, setSuggesting] = useState(false);
  const [explanations, setExplanations] = useState<Record<string, string>>({});
  const [aiNote, setAiNote] = useState('');
  const [explaining, setExplaining] = useState(false);
  const [errorExplain, setErrorExplain] = useState('');
  const [savingDs, setSavingDs] = useState(false);
  const [savedDs, setSavedDs] = useState<{ name: string } | null>(null);
  const [showInput, setShowInput] = useState(true);
  const [preview, setPreview] = useState<{ columns: string[]; rows: Record<string, unknown>[]; total: number; shown: number } | null>(null);
  const [previewLimit, setPreviewLimit] = useState(50);
  const [explainingRes, setExplainingRes] = useState(false);
  const [resultExplain, setResultExplain] = useState('');
  const [showChart, setShowChart] = useState(false);

  useEffect(() => {
    api.listDatasets().then((d) => { setDatasets(d); if (d[0]) setDatasetId(d[0].id); }).catch(() => {});
  }, []);

  // Fetch original-data rows on demand (more than the stored 10-row head).
  useEffect(() => {
    if (datasetId == null) { setPreview(null); return; }
    api.datasetPreview(datasetId, previewLimit).then(setPreview).catch(() => setPreview(null));
  }, [datasetId, previewLimit]);

  async function explainResultFn() {
    if (!result) return;
    setExplainingRes(true); setResultExplain('');
    try {
      const r = await api.explainResult(algo.slug, buildParams(), (result.summary || {}) as Record<string, unknown>, datasetId ?? undefined);
      setResultExplain(r.explanation || '（没有得到解读）');
    } catch (e) { setResultExplain('（解读失败:' + (e as Error).message + '）'); }
    finally { setExplainingRes(false); }
  }

  async function suggest() {
    setSuggesting(true); setError('');
    try {
      const s = await api.suggestParams(algo.slug, datasetId ?? undefined, intent.trim() || undefined);
      setParams((prev) => {
        const next = { ...prev };
        for (const [k, v] of Object.entries(s.params)) {
          if (k in schema) next[k] = Array.isArray(v) ? v.join(', ') : v === null || v === undefined ? '' : String(v);
        }
        return next;
      });
      setExplanations(s.explanations || {});
      setAiNote(s.note || '');
    } catch (e) { setError((e as Error).message); }
    finally { setSuggesting(false); }
  }

  function coerce(key: string, raw: string): unknown {
    const sp = schema[key] as ParamSpec;
    const v = raw.trim();
    if (v === '') return undefined;
    if (sp.type === 'array') return v.split(',').map((s) => s.trim()).filter(Boolean);
    if (sp.type === 'integer') return parseInt(v, 10);
    if (sp.type === 'number') return Number(v);
    if (sp.type === 'boolean') return v === 'true' || v === '1';
    return v;
  }

  function buildParams(): Record<string, unknown> {
    const p: Record<string, unknown> = {};
    for (const k of Object.keys(schema)) {
      const c = coerce(k, params[k] ?? '');
      if (c !== undefined) p[k] = c;
    }
    return p;
  }

  async function execute() {
    setBusy(true); setError(''); setErrorExplain(''); setResult(null); setSavedDs(null); setResultExplain('');
    try {
      const r = await api.runAlgorithm(algo.slug, buildParams(), datasetId ?? undefined);
      setResult(r);
      if (r.status !== 'ok') setError(r.error || '执行失败');
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function saveAsDataset() {
    if (datasetId == null) return;
    setSavingDs(true);
    try {
      const d = await api.runToDataset(algo.slug, buildParams(), datasetId);
      setSavedDs({ name: d.name });
    } catch (e) { setError((e as Error).message); }
    finally { setSavingDs(false); }
  }

  async function explainErr() {
    setExplaining(true); setErrorExplain('');
    try {
      const r = await api.explainError(algo.slug, error, buildParams(), datasetId ?? undefined);
      setErrorExplain(r.explanation || '（没有得到解释）');
    } catch (e) { setErrorExplain('（解释失败:' + (e as Error).message + '）'); }
    finally { setExplaining(false); }
  }

  const keys = Object.keys(schema);
  const activeDs = datasets.find((d) => d.id === datasetId) ?? null;
  const cols = (activeDs?.schema?.columns ?? []).map((c) => c.name);
  const inHead = activeDs?.schema?.head ?? [];

  return (
    <div className="max-w-2xl p-6 space-y-4">
      <div>
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold">{dispName(algo)}</h2>
          <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-ink-100 text-ink-600">{SOURCE_ZH[algo.source] ?? algo.source}</span>
        </div>
        <div className="text-xs text-ink-500 mt-0.5 font-mono">{algo.slug} · {catZh(algo.category)} · 返回 {RETURNS_ZH[algo.returns] ?? algo.returns}</div>
        <p className="text-sm text-ink-700 mt-2">{dispDesc(algo)}</p>
        <div className="flex flex-wrap gap-2 mt-3">
          {algo.source === 'builtin' ? (
            <>
              <button onClick={() => onOpenEditor({ mode: 'builtin', slug: algo.slug })}
                className="text-xs px-2.5 py-1.5 rounded-lg ring-1 ring-ink-200 text-ink-700 hover:bg-ink-50 flex items-center gap-1.5">
                <Code2 className="w-3.5 h-3.5" /> 查看源码
              </button>
              <button onClick={async () => { try { const r = await api.forkBuiltin(algo.slug); onOpenEditor({ mode: 'new', code: r.code, source: 'user', title: `${dispName(algo)}（副本）` }); } catch (e) { setError((e as Error).message); } }}
                className="text-xs px-2.5 py-1.5 rounded-lg ring-1 ring-brand-200 text-brand-700 hover:bg-brand-50 flex items-center gap-1.5">
                <Copy className="w-3.5 h-3.5" /> 复制为我的算法（可改）
              </button>
            </>
          ) : algo.id != null && (
            <button onClick={() => onOpenEditor({ mode: 'edit', algoId: algo.id! })}
              className="text-xs px-2.5 py-1.5 rounded-lg bg-brand-600 text-white hover:bg-brand-700 flex items-center gap-1.5">
              <Code2 className="w-3.5 h-3.5" /> 代码 · 编辑 / 调试 / 历史版本
            </button>
          )}
          {algo.source !== 'builtin' && !algo.verified && (
            <span className="text-[11px] px-2 py-1 rounded-lg bg-amber-50 text-amber-700 ring-1 ring-amber-100">草稿 · 未验证（在编辑器里调试通过并保存即为已验证）</span>
          )}
        </div>
      </div>

      <div className="bg-white rounded-xl ring-1 ring-ink-200 p-4 space-y-3">
        <div>
          <label className="block text-xs text-ink-500 mb-1">数据集</label>
          <select value={datasetId ?? ''} onChange={(e) => setDatasetId(e.target.value ? Number(e.target.value) : null)}
            className="w-full border border-ink-200 rounded-lg px-2 py-1.5 bg-white text-sm">
            <option value="">（无 / 不需要数据集）</option>
            {datasets.map((d) => <option key={d.id} value={d.id}>{d.name} ({d.rows} × {d.columns})</option>)}
          </select>
        </div>

        {/* Original input data preview — so you see what you're operating on. */}
        {activeDs && (cols.length > 0) && (() => {
          const rows = preview?.rows ?? inHead;
          const total = preview?.total ?? activeDs.rows;
          const shown = preview?.shown ?? rows.length;
          return (
            <div className="rounded-lg ring-1 ring-ink-200 overflow-hidden">
              <button onClick={() => setShowInput((v) => !v)}
                className="w-full flex items-center justify-between px-2.5 py-1.5 text-xs text-ink-600 hover:bg-ink-50">
                <span className="flex items-center gap-1.5"><Table2 className="w-3.5 h-3.5" /> 原始数据预览 · 显示前 {shown} 行（共 {total.toLocaleString()} 行 × {activeDs.columns} 列）</span>
                <ChevronDown className={`w-3.5 h-3.5 transition-transform ${showInput ? '' : '-rotate-90'}`} />
              </button>
              {showInput && (
                <>
                  <div className="overflow-auto max-h-64 border-t border-ink-200">
                    <table className="text-xs min-w-full">
                      <thead className="bg-ink-50 text-ink-500 sticky top-0">
                        <tr>{cols.map((c) => <th key={c} className="text-left py-1.5 px-2 font-medium whitespace-nowrap">{c}</th>)}</tr>
                      </thead>
                      <tbody>
                        {rows.map((row, i) => (
                          <tr key={i} className="border-t border-ink-100">
                            {cols.map((c) => <td key={c} className="py-1 px-2 font-mono whitespace-nowrap text-ink-700">{cellStr((row as Record<string, unknown>)[c])}</td>)}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {shown < total && (
                    <button onClick={() => setPreviewLimit((l) => Math.min(500, l + 200))}
                      className="w-full text-xs text-brand-600 hover:bg-brand-50 py-1.5 border-t border-ink-100">
                      多看 200 行（最多 500 行）
                    </button>
                  )}
                </>
              )}
            </div>
          );
        })()}

        {/* Natural-language assist — fills the params below; you still review + run. */}
        {keys.length > 0 && (
          <div className="rounded-lg bg-brand-50/60 ring-1 ring-brand-100 p-2.5">
            <div className="flex items-center gap-1.5 text-xs text-brand-700 font-medium mb-1.5">
              <Sparkles className="w-3.5 h-3.5" /> 不会设参数?用一句话说,AI 帮你填(可留空)
            </div>
            <div className="flex gap-2">
              <input value={intent} onChange={(e) => setIntent(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') suggest(); }}
                placeholder={dispExample(algo)}
                className="flex-1 border border-ink-200 rounded-lg px-2 py-1.5 bg-white text-sm" />
              <button onClick={suggest} disabled={suggesting}
                className="px-3 py-1.5 rounded-lg bg-brand-600 text-white text-sm font-medium hover:bg-brand-700 disabled:opacity-50 flex items-center gap-1.5 shrink-0">
                {suggesting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />} 推荐参数
              </button>
            </div>
            {aiNote && <div className="text-xs text-ink-600 mt-2">💡 {aiNote}</div>}
          </div>
        )}

        {keys.length > 0 && (
          <div className="space-y-3 pt-1">
            <div className="text-xs font-medium text-ink-600">参数</div>
            {keys.map((k) => (
              <ParamField key={k} name={k} spec={schema[k] as ParamSpec} value={params[k] ?? ''} cols={cols} aiHint={explanations[k]} onChange={(v) => setParams((p) => ({ ...p, [k]: v }))} />
            ))}
          </div>
        )}

        <button onClick={execute} disabled={busy} className="px-4 py-2 rounded-xl bg-brand-600 text-white font-medium hover:bg-brand-700 flex items-center gap-2 disabled:opacity-50">
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />} 执行
        </button>
      </div>

      {error && (
        <div className="rounded-lg bg-red-50 ring-1 ring-red-100 p-3 space-y-2">
          <div className="text-sm text-red-700 flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
            <span className="whitespace-pre-wrap font-mono text-xs">{error}</span>
          </div>
          <button onClick={explainErr} disabled={explaining}
            className="text-xs px-2.5 py-1 rounded-lg bg-white ring-1 ring-red-200 text-red-700 hover:bg-red-50 flex items-center gap-1.5 disabled:opacity-50">
            {explaining ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />} 用人话解释这个错误
          </button>
          {errorExplain && (
            <div className="text-sm text-ink-700 bg-white rounded-lg ring-1 ring-ink-200 p-2.5 whitespace-pre-wrap">
              💡 {errorExplain}
            </div>
          )}
        </div>
      )}
      {result && result.status === 'ok' && (
        <div className="space-y-2">
          <RunOutput result={result} t={t} />
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <button onClick={explainResultFn} disabled={explainingRes}
                className="text-xs px-2.5 py-1.5 rounded-lg ring-1 ring-brand-200 text-brand-700 hover:bg-brand-50 flex items-center gap-1.5 disabled:opacity-50">
                {explainingRes ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />} 解读这个结果
              </button>
              {(result.result_rows ?? 0) > 0 && result.result_path && (
                <button onClick={() => setShowChart((v) => !v)}
                  className={`text-xs px-2.5 py-1.5 rounded-lg ring-1 flex items-center gap-1.5 ${showChart ? 'bg-brand-600 text-white ring-transparent' : 'ring-brand-200 text-brand-700 hover:bg-brand-50'}`}>
                  <BarChart3 className="w-3.5 h-3.5" /> {showChart ? '收起图表' : '可视化'}
                </button>
              )}
            </div>
            {resultExplain && (
              <div className="text-sm text-ink-700 bg-brand-50/60 rounded-lg ring-1 ring-brand-100 p-2.5 whitespace-pre-wrap">
                💡 {resultExplain}
              </div>
            )}
            {showChart && result.result_path && (result.result_rows ?? 0) > 0 && (
              <div className="rounded-lg ring-1 ring-ink-200 p-2">
                <DatasetChart resultPath={result.result_path} name={dispName(algo)} />
              </div>
            )}
          </div>
          {(result.result_rows ?? 0) > 0 && datasetId != null && (
            savedDs ? (
              <div className="text-xs text-violet-700 bg-violet-50 ring-1 ring-violet-100 rounded-lg px-3 py-2">
                ✓ 已存为派生数据集「{savedDs.name}」—— 在「数据集 → 中间结果」里可继续分析 / 对比
              </div>
            ) : (
              <button onClick={saveAsDataset} disabled={savingDs}
                className="text-xs px-2.5 py-1.5 rounded-lg ring-1 ring-violet-200 text-violet-700 hover:bg-violet-50 flex items-center gap-1.5 disabled:opacity-50">
                {savingDs ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />} 把结果存为派生数据集
              </button>
            )
          )}
        </div>
      )}
    </div>
  );
}

function RunOutput({ result, t }: { result: RunResult; t: (k: string) => string }) {
  const s = (result.summary || {}) as { type?: string; rows?: number; columns?: string[]; head?: Record<string, unknown>[]; value?: unknown; length?: number };
  const exp = (fmt: string) => `/api/datasets/export?path=${encodeURIComponent(result.result_path || '')}&format=${fmt}`;

  return (
    <div className="space-y-2">
      <div className="text-sm text-emerald-700 bg-emerald-50 ring-1 ring-emerald-100 rounded-lg px-3 py-2 flex items-center gap-2 flex-wrap">
        <CheckCircle2 className="w-4 h-4" /> 执行成功 · {result.duration_ms} ms
        {typeof result.result_rows === 'number' && result.result_rows > 0 && <span>· {result.result_rows} 行</span>}
        {result.result_path && (
          <span className="ml-auto flex items-center gap-2 text-xs">
            下载:<a href={exp('csv')} className="text-brand-600 underline">CSV</a>
            <a href={exp('xlsx')} className="text-brand-600 underline">Excel</a>
          </span>
        )}
      </div>

      {s.type === 'dataframe' && s.head && s.head.length > 0 ? (
        <div className="rounded-lg ring-1 ring-ink-200 overflow-auto max-h-80">
          <table className="text-xs min-w-full">
            <thead className="bg-ink-50 text-ink-500 sticky top-0">
              <tr>{(s.columns ?? Object.keys(s.head[0])).map((c) => <th key={c} className="text-left py-2 px-3 font-medium whitespace-nowrap">{c}</th>)}</tr>
            </thead>
            <tbody>
              {s.head.map((row, i) => (
                <tr key={i} className="border-t border-ink-100">
                  {(s.columns ?? Object.keys(s.head![0])).map((c) => <td key={c} className="py-1.5 px-3 font-mono whitespace-nowrap">{cellStr(row[c])}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <pre className="bg-ink-50 ring-1 ring-ink-200 rounded-lg p-3 text-xs overflow-auto max-h-80">{JSON.stringify(s.value ?? s, null, 2).slice(0, 4000)}</pre>
      )}
    </div>
  );
}

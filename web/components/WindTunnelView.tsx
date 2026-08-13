'use client';

/**
 * 风洞试验过程质量检查 — the domain application built on the DataAgent platform.
 *
 * Five steps, matching the customer's specification one-to-one:
 *   ① 数据导入   upload ca/pa/da, pick which checks to run, start
 *   ② 运算结果   per-item verdict with 原因分析 / 影响评估 / 处理建议
 *   ③ 气动曲线   custom X, multi-select Y, plus an AI-narrated conclusion
 *   ④ 报告       selectable sections, editable preview, export as 车次号_跟班记录
 *   ⑤ 知识库     rules / features / custom algorithms / balance library
 *
 * The layout deliberately keeps the run list on the left across steps ②③④ so a
 * reviewer can walk a batch run by run without losing their place — the single
 * most common action during a wind-tunnel entry.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle, BarChart3, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight,
  ChevronRight as ChevronRightIcon, ChevronUp, CircleSlash, Download,
  FileText, FolderTree, FolderUp, Info, Layers, Loader2, MessageSquare, Play, RefreshCw, Sparkles,
  Trash2, TrendingUp, Wind, XCircle,
} from 'lucide-react';
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import Markdown from '@/components/Markdown';
import WindTunnelCompare from '@/components/WindTunnelCompare';
import WindTunnelKnowledge, { LevelChip } from '@/components/WindTunnelKnowledge';
import {
  api, type WtBatch, type WtBatchResult, type WtCurve, type WtFinding,
  type WtLevel, type WtRule, type WtRunResult,
} from '@/lib/api';

type Step = 'import' | 'result' | 'curve' | 'compare' | 'report' | 'kb';

const STEPS: { id: Step; n: string; label: string; icon: React.ReactNode }[] = [
  { id: 'import', n: '①', label: '数据导入', icon: <FolderUp className="w-4 h-4" /> },
  { id: 'result', n: '②', label: '运算结果查看', icon: <CheckCircle2 className="w-4 h-4" /> },
  { id: 'curve', n: '③', label: '气动曲线绘制', icon: <BarChart3 className="w-4 h-4" /> },
  // 20260225《车次及马赫数绘图》— comparison is the mode the work actually
  // lives in, so it gets a step of its own rather than a tab inside ③.
  { id: 'compare', n: '③b', label: '多车次对比', icon: <Layers className="w-4 h-4" /> },
  { id: 'report', n: '④', label: '质量检查报告', icon: <FileText className="w-4 h-4" /> },
  { id: 'kb', n: '⑤', label: '知识库管理', icon: <Sparkles className="w-4 h-4" /> },
];

const SERIES_COLORS = ['#2563eb', '#dc2626', '#059669', '#d97706',
  '#7c3aed', '#0891b2', '#db2777', '#65a30d'];

const gradeStyle = (g: string) =>
  g === '不合格' ? 'bg-red-100 text-red-700 ring-red-200'
    : g === '有条件合格' ? 'bg-amber-100 text-amber-700 ring-amber-200'
      : g.includes('关注') ? 'bg-sky-100 text-sky-700 ring-sky-200'
        : 'bg-emerald-100 text-emerald-700 ring-emerald-200';

const fmt = (v: number | null, unit: string) =>
  v == null ? '—' : `${Number(v.toPrecision(6))}${unit ? ` ${unit}` : ''}`;

// ══════════════════════════════════════════════════════════════════════════
export default function WindTunnelView() {
  const [step, setStep] = useState<Step>('import');
  const [batches, setBatches] = useState<WtBatch[]>([]);
  const [batchId, setBatchId] = useState<number | null>(null);
  const [result, setResult] = useState<WtBatchResult | null>(null);
  const [rules, setRules] = useState<WtRule[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [tailContracted, setTailContracted] = useState(false);
  const [activeRun, setActiveRun] = useState<string>('');
  const [busy, setBusy] = useState('');
  const [progress, setProgress] = useState<string[]>([]);
  const [err, setErr] = useState('');
  const [llmOn, setLlmOn] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const dirRef = useRef<HTMLInputElement>(null);

  const batch = useMemo(() => batches.find((b) => b.id === batchId) ?? null, [batches, batchId]);
  const run = useMemo<WtRunResult | null>(
    () => result?.runs.find((r) => r.run_no === activeRun) ?? result?.runs[0] ?? null,
    [result, activeRun]);

  const loadBatches = useCallback(async () => {
    const bs = await api.wtListBatches();
    setBatches(bs);
    if (bs.length && batchId == null) setBatchId(bs[0].id);
  }, [batchId]);

  const loadRules = useCallback(async () => {
    const r = await api.wtRules();
    setRules(r.rules);
    setSelected(new Set(r.rules.filter((x) => x.enabled).map((x) => x.rule_id)));
  }, []);

  useEffect(() => {
    api.wtHealth().then((h) => setLlmOn(!!h.llm_configured)).catch(() => {});
    loadRules().catch((e) => setErr(String(e)));
    loadBatches().catch((e) => setErr(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (batchId == null) { setResult(null); return; }
    api.wtGetBatch(batchId)
      .then((d) => { setResult(d.result); setActiveRun(d.result?.runs[0]?.run_no ?? ''); })
      .catch(() => setResult(null));
  }, [batchId]);

  /** Walk a dropped directory tree. `dataTransfer.files` is EMPTY for a folder
   *  drop — only `items[].webkitGetAsEntry()` sees it — so without this, dragging
   *  a folder did nothing at all and said nothing either. The tunnel's data is
   *  organised as ca/ da/ temp/, so folder drops are the normal case, not an
   *  edge case. */
  async function filesFromDataTransfer(dt: DataTransfer): Promise<File[]> {
    const entries: FileSystemEntry[] = [];
    for (const item of Array.from(dt.items ?? [])) {
      const e = item.webkitGetAsEntry?.();
      if (e) entries.push(e);
    }
    if (!entries.some((e) => e.isDirectory)) return Array.from(dt.files ?? []);

    const out: File[] = [];
    const readDir = (dir: FileSystemDirectoryEntry): Promise<FileSystemEntry[]> =>
      new Promise((resolve) => {
        const reader = dir.createReader();
        const acc: FileSystemEntry[] = [];
        const step = () => reader.readEntries((batch) => {
          if (!batch.length) { resolve(acc); return; }
          acc.push(...batch);
          step();               // readEntries returns at most 100 per call
        }, () => resolve(acc));
        step();
      });
    const walk = async (entry: FileSystemEntry): Promise<void> => {
      if (entry.isFile) {
        const f = await new Promise<File | null>((resolve) =>
          (entry as FileSystemFileEntry).file(resolve, () => resolve(null)));
        if (f) out.push(f);
      } else if (entry.isDirectory) {
        for (const child of await readDir(entry as FileSystemDirectoryEntry)) {
          await walk(child);
        }
      }
    };
    for (const e of entries) await walk(e);
    return out;
  }

  /** ``ca246490`` / ``pa91837模板(公开)`` / a zip / the 车次表 spreadsheet —
   *  same rule the backend uses. The plan table is not run data but it IS
   *  meaningful: it is the only thing that can show a MISSING run. */
  const looksLikeRunFile = (name: string) =>
    /^(ca|pa|da)\d{3,}/i.test(name)
    || /\.(zip|xlsx|xls)$/i.test(name);

  async function upload(files: FileList | File[] | null) {
    const all = files ? Array.from(files) : [];
    if (!all.length) {
      // Never fail silently. An import that quietly does nothing is worse than
      // an error, because the user has no idea whether it worked.
      setErr('没有读到任何文件。如果你拖的是文件夹，请用「选择文件夹」按钮，'
           + '或把文件夹里的文件一起拖进来。');
      return;
    }
    // Pre-filter on the client: a picked directory usually carries plenty of
    // unrelated files, and shipping them all just to have the server reject
    // them wastes the upload. Say how many were skipped rather than dropping
    // them quietly.
    const list = all.filter((f) => looksLikeRunFile(f.name));
    const skipped = all.length - list.length;
    if (!list.length) {
      setErr(`选中的 ${all.length} 个文件里没有识别到车次文件。`
           + '车次文件应形如 ca246490 / pa246490 / da246490（无扩展名），或是一个 .zip 包。');
      return;
    }
    setBusy('upload'); setErr('');
    setProgress([`正在上传 ${list.length} 个车次文件`
                 + (skipped ? `（已跳过 ${skipped} 个无关文件）` : '') + '…']);
    try {
      const b = await api.wtCreateBatch(list);
      // Switch to the new batch FIRST. Listing is a second round-trip; doing it
      // before the switch left the view (and 开始检查) pointing at the previous
      // batch for the duration of that request.
      setBatchId(b.id);
      setResult(null);
      if (b.error) setErr(b.error);
      setProgress([`已导入 ${b.runs.length} 个车次`
                   + (skipped ? `（跳过 ${skipped} 个无关文件）` : '')
                   + '，请在下方勾选检查项后点「开始检查」。']);
      await loadBatches();
    } catch (e) { setErr(String(e)); setProgress([]); } finally { setBusy(''); }
  }

  async function startCheck() {
    if (batchId == null) return;
    setBusy('check'); setErr(''); setProgress([]);
    const names = batch?.runs.map((r) => r.run_no) ?? [];
    setProgress([`准备检查 ${names.length} 个车次：${names.join('、')}`,
      `已勾选 ${selected.size} / ${rules.length} 项检查规则`]);
    try {
      const r = await api.wtCheck(batchId, {
        rule_ids: Array.from(selected), tail_contracted: tailContracted,
      });
      setResult(r);
      setActiveRun(r.runs[0]?.run_no ?? '');
      setProgress((p) => [...p,
        `检查完成：严重 ${r.summary.totals.critical} 项，警告 ${r.summary.totals.warning} 项，` +
        `关注 ${r.summary.totals.notice} 项，未评定 ${r.summary.totals.unavailable} 项`,
        `批次总体评级：${r.summary.grade}`]);
      await loadBatches();
      setStep('result');
    } catch (e) { setErr(String(e)); setProgress((p) => [...p, `失败：${e}`]); }
    finally { setBusy(''); }
  }

  return (
    <div className="h-full flex flex-col bg-ink-50/40">
      {/* header */}
      <div className="shrink-0 bg-white border-b border-ink-200 px-5 py-3">
        <div className="flex items-center gap-2">
          <Wind className="w-5 h-5 text-brand-600" />
          <h1 className="text-base font-semibold text-ink-900">风洞试验过程质量检查</h1>
          <span className="text-[11px] text-ink-400">单车次数据质量检查 · 多车次综合分析</span>
          {batch && (
            <span className="ml-3 text-xs text-ink-500">
              当前批次：<span className="text-ink-800">{batch.name || `#${batch.id}`}</span>
              <span className="ml-2">{batch.runs.length} 个车次</span>
            </span>
          )}
          <button onClick={() => { loadBatches(); loadRules(); }}
            className="ml-auto p-1.5 text-ink-400 hover:text-brand-600" title="刷新">
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
        <div className="flex flex-wrap gap-1 mt-2">
          {STEPS.map((s) => (
            <button key={s.id} onClick={() => setStep(s.id)}
              className={`px-3 py-1.5 rounded-lg text-sm inline-flex items-center gap-1.5 transition ${
                step === s.id ? 'bg-brand-50 text-brand-700 ring-1 ring-brand-200'
                  : 'text-ink-500 hover:bg-ink-100'}`}>
              <span className="text-xs opacity-70">{s.n}</span>{s.icon}{s.label}
            </button>
          ))}
        </div>
      </div>

      {err && (
        <div className="shrink-0 mx-5 mt-3 text-sm px-3 py-2 rounded-lg bg-red-50 text-red-800 ring-1 ring-red-200 flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <span className="flex-1">{err}</span>
          <button onClick={() => setErr('')} className="text-red-400 hover:text-red-700">×</button>
        </div>
      )}

      <div className="flex-1 min-h-0 overflow-y-auto p-5">
        {step === 'import' && (
          <ImportStep
            batches={batches} batchId={batchId} setBatchId={setBatchId} batch={batch}
            rules={rules} selected={selected} setSelected={setSelected}
            tailContracted={tailContracted} setTailContracted={setTailContracted}
            busy={busy} progress={progress}
            onUploadClick={() => fileRef.current?.click()}
            onPickFolder={() => dirRef.current?.click()}
            onDropTransfer={async (dt) => upload(await filesFromDataTransfer(dt))}
            onStart={startCheck}
            onDelete={async (id) => {
              if (!confirm('删除该批次及其上传的原始文件？')) return;
              await api.wtDeleteBatch(id);
              if (batchId === id) { setBatchId(null); setResult(null); }
              await loadBatches();
            }}
            onGoKb={() => setStep('kb')}
          />
        )}
        {step === 'result' && (
          <ResultStep result={result} run={run} activeRun={activeRun}
            setActiveRun={setActiveRun} batchId={batchId} llmOn={llmOn} />
        )}
        {step === 'curve' && (
          <CurveStep batchId={batchId} result={result} activeRun={activeRun}
            setActiveRun={setActiveRun} llmOn={llmOn} />
        )}
        {step === 'compare' && <WindTunnelCompare batchId={batchId} />}
        {step === 'report' && (
          <ReportStep batchId={batchId} result={result} activeRun={activeRun}
            setActiveRun={setActiveRun} llmOn={llmOn} />
        )}
        {step === 'kb' && (
          <WindTunnelKnowledge batches={batches} llmOn={llmOn} onRulesChanged={loadRules} />
        )}
      </div>

      <input ref={fileRef} data-testid="wt-file-input" type="file" multiple className="hidden"
        onChange={(e) => { upload(e.target.files); e.target.value = ''; }} />
      {/* Directory picker. `webkitdirectory` is non-standard but is what every
          Chromium/WebKit browser implements; React needs it spelled this way. */}
      <input ref={dirRef} data-testid="wt-dir-input" type="file" multiple className="hidden"
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        {...({ webkitdirectory: '', directory: '' } as any)}
        onChange={(e) => { upload(e.target.files); e.target.value = ''; }} />
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
//  ① 数据导入
// ══════════════════════════════════════════════════════════════════════════
function ImportStep(props: {
  batches: WtBatch[]; batchId: number | null; setBatchId: (n: number) => void;
  batch: WtBatch | null; rules: WtRule[];
  selected: Set<string>; setSelected: (s: Set<string>) => void;
  tailContracted: boolean; setTailContracted: (b: boolean) => void;
  busy: string; progress: string[];
  onUploadClick: () => void; onPickFolder: () => void;
  onDropTransfer: (dt: DataTransfer) => void;
  onStart: () => void; onDelete: (id: number) => void; onGoKb: () => void;
}) {
  const { batches, batchId, setBatchId, batch, rules, selected, setSelected,
    tailContracted, setTailContracted, busy, progress, onUploadClick, onPickFolder,
    onDropTransfer, onStart, onDelete, onGoKb } = props;
  const [dragging, setDragging] = useState(false);

  const toggle = (id: string) => {
    const s = new Set(selected);
    if (s.has(id)) s.delete(id); else s.add(id);
    setSelected(s);
  };

  return (
    <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
      <div className="xl:col-span-2 space-y-4">
        <div
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => { e.preventDefault(); setDragging(false); onDropTransfer(e.dataTransfer); }}
          className={`rounded-xl border-2 border-dashed p-8 text-center transition ${
            dragging ? 'border-brand-400 bg-brand-50' : 'border-ink-200 bg-white'}`}>
          <FolderUp className="w-8 h-8 mx-auto text-ink-300 mb-2" />
          <div className="text-sm text-ink-700">把车次文件或整个文件夹拖进来，或</div>
          <div className="mt-2 flex items-center justify-center gap-2">
            <button onClick={onUploadClick} disabled={busy === 'upload'}
              className="px-4 py-1.5 rounded-lg bg-brand-600 text-white text-sm inline-flex items-center gap-1.5 disabled:opacity-50">
              {busy === 'upload' ? <Loader2 className="w-4 h-4 animate-spin" /> : <FolderUp className="w-4 h-4" />}
              选择文件
            </button>
            <button onClick={onPickFolder} disabled={busy === 'upload'}
              className="px-4 py-1.5 rounded-lg border border-brand-300 text-brand-700 text-sm inline-flex items-center gap-1.5 disabled:opacity-50"
              title="选一个目录，其下所有子目录里的车次文件都会被导入">
              <FolderTree className="w-4 h-4" /> 选择文件夹
            </button>
          </div>
          <div className="text-[11px] text-ink-400 mt-2 leading-relaxed">
            文件无扩展名，按 <code className="font-mono">ca/pa/da + 车次号</code> 前缀自动识别并分组；
            GBK 编码自动处理；也支持整包 .zip 一次导入。<br />
            <span className="text-ink-500">数据按 ca/ da/ temp/ 分目录存放时，直接选最外层目录即可</span>
            —— 会递归读取全部子目录，不匹配前缀的文件自动忽略并列出。<br />
            <span className="text-ink-500">目录里如果有「车次表.xlsx」会一并读入</span>
            ，用于核对计划与实到、找出缺失车次。<br />
            多个连续车次一起导入时，天平零飘会自动按车次链逐次比对。
          </div>
        </div>

        {batch && batch.runs.length > 0 && (
          <div className="rounded-xl border border-ink-200 bg-white p-4">
            <div className="text-sm font-medium text-ink-800 mb-2">已识别车次</div>
            <table className="w-full text-xs">
              <thead className="text-ink-500 border-b border-ink-100">
                <tr><th className="text-left py-1">车次</th><th className="text-left">文件</th>
                  <th className="text-left">马赫数</th><th className="text-left">天平</th>
                  <th className="text-left">吹风点</th><th className="text-left">模型</th></tr>
              </thead>
              <tbody>
                {batch.runs.map((r) => {
                  const m = r.meta as Record<string, unknown>;
                  const files = Object.keys(r.files);
                  return (
                    <tr key={r.run_no} className="border-b border-ink-50">
                      <td className="py-1.5 font-mono text-ink-800">{r.run_no}</td>
                      <td>
                        {(['ca', 'pa', 'da'] as const).map((k) => (
                          <span key={k} className={`inline-block mr-1 px-1.5 rounded text-[10px] ${
                            files.includes(k) ? 'bg-emerald-50 text-emerald-700'
                              : 'bg-ink-100 text-ink-400 line-through'}`}>{k}</span>
                        ))}
                      </td>
                      <td className="text-ink-600">{String(m.mach ?? '—')}</td>
                      <td className="text-ink-600 font-mono text-[11px]">{String(m.balance_formula || m.balance_type || '—')}</td>
                      <td className="text-ink-600">{String(m.n_blow_points ?? 0)}</td>
                      <td className="text-ink-500 truncate max-w-48">{String(m.model || '—')}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        <div className="rounded-xl border border-ink-200 bg-white p-4">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-sm font-medium text-ink-800">选择质量检查项</span>
            <span className="text-[11px] text-ink-400">已选 {selected.size} / {rules.length}</span>
            <button onClick={() => setSelected(new Set(rules.map((r) => r.rule_id)))}
              className="ml-auto text-xs text-brand-600 hover:underline">全选</button>
            <button onClick={() => setSelected(new Set())}
              className="text-xs text-ink-400 hover:underline">全不选</button>
            <button onClick={onGoKb}
              className="text-xs text-brand-600 hover:underline inline-flex items-center gap-1">
              <Sparkles className="w-3 h-3" /> AI 自定义生成
            </button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-1">
            {rules.map((r) => (
              <label key={r.rule_id}
                className="flex items-start gap-2 px-2 py-1.5 rounded-lg hover:bg-ink-50 cursor-pointer">
                <input type="checkbox" checked={selected.has(r.rule_id)}
                  onChange={() => toggle(r.rule_id)} className="mt-0.5 accent-brand-600" />
                <span className="text-xs text-ink-700 flex-1">
                  {r.name}
                  {r.source !== 'builtin' && (
                    <span className={`ml-1.5 text-[10px] px-1 rounded ${
                      r.source === 'ai' ? 'bg-violet-100 text-violet-700' : 'bg-sky-100 text-sky-700'}`}>
                      {r.source === 'ai' ? 'AI' : '自定义'}
                    </span>
                  )}
                </span>
              </label>
            ))}
          </div>
          <label className="flex items-center gap-2 mt-3 pt-3 border-t border-ink-100 text-xs text-ink-600">
            <input type="checkbox" checked={tailContracted}
              onChange={(e) => setTailContracted(e.target.checked)} className="accent-brand-600" />
            模型尾部为收缩外形（勾选后按规程跳过「底压与来流静压比较」一项）
          </label>
        </div>

        <div className="flex items-center gap-3">
          <button onClick={onStart} disabled={!!busy || batchId == null || selected.size === 0}
            className="px-5 py-2 rounded-lg bg-brand-600 text-white text-sm font-medium inline-flex items-center gap-2 disabled:opacity-40">
            {busy === 'check' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
            开始检查
          </button>
          {batchId == null && <span className="text-xs text-ink-400">请先导入或选择一个批次</span>}
        </div>

        {progress.length > 0 && (
          <div className="rounded-xl border border-ink-200 bg-white p-3">
            <div className="text-xs font-medium text-ink-700 mb-1.5">检查进度</div>
            {progress.map((p, i) => (
              <div key={i} className="text-xs text-ink-600 flex items-start gap-1.5 py-0.5">
                <ChevronRight className="w-3 h-3 mt-0.5 text-ink-300 shrink-0" />{p}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="space-y-2">
        <div className="text-sm font-medium text-ink-800">历史批次</div>
        {batches.length === 0 && <div className="text-xs text-ink-400 py-4">还没有导入过数据。</div>}
        {batches.map((b) => (
          <div key={b.id}
            className={`rounded-lg border p-3 cursor-pointer transition ${
              b.id === batchId ? 'border-brand-300 bg-brand-50/40' : 'border-ink-200 bg-white hover:border-ink-300'}`}
            onClick={() => setBatchId(b.id)}>
            <div className="flex items-center gap-2">
              <span className="text-sm text-ink-800 truncate flex-1">{b.name || `批次 ${b.id}`}</span>
              <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                b.status === 'checked' ? 'bg-emerald-100 text-emerald-700'
                  : b.status === 'error' ? 'bg-red-100 text-red-700' : 'bg-ink-100 text-ink-500'}`}>
                {b.status === 'checked' ? '已检查' : b.status === 'error' ? '异常' : '待检查'}
              </span>
              <button onClick={(e) => { e.stopPropagation(); onDelete(b.id); }}
                className="p-1 text-ink-300 hover:text-red-600"><Trash2 className="w-3.5 h-3.5" /></button>
            </div>
            <div className="text-[11px] text-ink-400 mt-1">
              {b.runs.length} 个车次 · {new Date(b.created_at).toLocaleString('zh-CN')}
            </div>
            {b.error && <div className="text-[11px] text-amber-700 mt-1">{b.error}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
//  run picker shared by ②③④
// ══════════════════════════════════════════════════════════════════════════
/**
 * Run picker for steps ②③④.
 *
 * It used to render every run as a card in the left column. That is fine for
 * five runs and unusable for the customer's real entry of 130: the list alone
 * ran several screens tall and pushed every control below it out of sight —
 * the axis pickers, the report options, the buttons. Nothing was broken, but
 * the panel could not be operated.
 *
 * So the run is a COMPACT BAR by default — previous / current / next, plus the
 * current run's verdict — and the full list is opened only when the user wants
 * to browse. Everything below stays where it is. The expanded list is bounded
 * and scrolls inside itself, carries a search box and severity filters, and
 * offers "jump to next problem run", which is what a reviewer actually does on
 * a long entry.
 */
function RunPicker({ result, activeRun, setActiveRun }: {
  result: WtBatchResult | null; activeRun: string; setActiveRun: (s: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const [only, setOnly] = useState<'all' | 'problem' | 'unavailable'>('all');

  const runs = result?.runs ?? [];
  const idx = Math.max(0, runs.findIndex((r) => r.run_no === activeRun));
  const cur = runs[idx];

  const filtered = useMemo(() => runs.filter((r) => {
    if (q && !r.run_no.includes(q)) return false;
    if (only === 'problem') return r.counts.critical > 0 || r.counts.warning > 0;
    if (only === 'unavailable') return r.counts.unavailable > 0;
    return true;
  }), [runs, q, only]);

  // Open on the current run so a 130-row list does not start at the top.
  const listRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    listRef.current?.querySelector('[data-active="1"]')
      ?.scrollIntoView({ block: 'center' });
  }, [open]);

  if (!result || !cur) return null;
  const step = (d: number) => {
    const n = runs[Math.min(runs.length - 1, Math.max(0, idx + d))];
    if (n) setActiveRun(n.run_no);
  };
  const nextProblem = () => {
    const bad = (r: WtRunResult) => r.counts.critical > 0 || r.counts.warning > 0;
    const after = runs.slice(idx + 1).find(bad) ?? runs.find(bad);
    if (after) setActiveRun(after.run_no);
  };
  const problemCount = runs.filter((r) => r.counts.critical > 0 || r.counts.warning > 0).length;

  return (
    <div className="rounded-xl border border-ink-200 bg-white">
      <div className="px-2.5 py-2 flex items-center gap-1.5">
        <span className="text-xs text-ink-500 shrink-0">车次</span>
        <button onClick={() => step(-1)} disabled={idx <= 0}
          title="上一个车次" className="p-1 rounded text-ink-400 hover:bg-ink-100 disabled:opacity-30">
          <ChevronLeft className="w-4 h-4" />
        </button>
        <select value={activeRun} onChange={(e) => setActiveRun(e.target.value)}
          className="flex-1 min-w-0 text-sm font-mono px-1.5 py-1 rounded border border-ink-200 bg-white">
          {runs.map((r) => (
            <option key={r.run_no} value={r.run_no}>
              {r.run_no}　{r.grade}
            </option>
          ))}
        </select>
        <button onClick={() => step(1)} disabled={idx >= runs.length - 1}
          title="下一个车次" className="p-1 rounded text-ink-400 hover:bg-ink-100 disabled:opacity-30">
          <ChevronRightIcon className="w-4 h-4" />
        </button>
        <span className="text-[10px] text-ink-400 shrink-0 tabular-nums">{idx + 1}/{runs.length}</span>
      </div>

      <div className="px-2.5 pb-2 flex items-center gap-1.5 flex-wrap">
        <span className={`text-[10px] px-1.5 py-0.5 rounded ring-1 ${gradeStyle(cur.grade)}`}>
          {cur.grade}
        </span>
        {cur.counts.critical > 0 && <span className="text-[10px] text-red-600">严重 {cur.counts.critical}</span>}
        {cur.counts.warning > 0 && <span className="text-[10px] text-amber-600">警告 {cur.counts.warning}</span>}
        {cur.counts.notice > 0 && <span className="text-[10px] text-sky-600">关注 {cur.counts.notice}</span>}
        {cur.counts.unavailable > 0 && <span className="text-[10px] text-ink-500">未评定 {cur.counts.unavailable}</span>}
        <span className="text-[10px] text-emerald-600">正常 {cur.counts.ok}</span>
        {problemCount > 0 && (
          <button onClick={nextProblem}
            className="ml-auto text-[10px] text-brand-600 hover:underline shrink-0"
            title={`本批次 ${problemCount} 个车次有警告及以上`}>
            跳到下一个异常 ({problemCount})
          </button>
        )}
      </div>

      <button onClick={() => setOpen(!open)}
        className="w-full px-2.5 py-1.5 border-t border-ink-100 text-[11px] text-ink-500 hover:bg-ink-50 flex items-center justify-center gap-1">
        {open ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
        {open ? '收起车次列表' : `展开车次列表（${runs.length}）`}
      </button>

      {open && (
        <div className="border-t border-ink-100">
          <div className="p-2 flex items-center gap-1.5">
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜索车次号"
              className="flex-1 min-w-0 text-xs px-2 py-1 rounded border border-ink-200" />
            {([['all', '全部'], ['problem', '异常'], ['unavailable', '未评定']] as const).map(([k, label]) => (
              <button key={k} onClick={() => setOnly(k)}
                className={`px-1.5 py-1 rounded text-[11px] shrink-0 ${only === k
                  ? 'bg-brand-50 text-brand-700 ring-1 ring-brand-200' : 'text-ink-500 border border-ink-200'}`}>
                {label}
              </button>
            ))}
          </div>
          {/* Bounded so the panel can never push the controls off screen again. */}
          <div ref={listRef} className="max-h-[34vh] overflow-y-auto">
            {filtered.map((r) => (
              <button key={r.run_no} data-active={r.run_no === activeRun ? '1' : '0'}
                onClick={() => setActiveRun(r.run_no)}
                className={`w-full text-left px-2.5 py-1.5 border-b border-ink-50 flex items-center gap-2 ${
                  r.run_no === activeRun ? 'bg-brand-50/60' : 'hover:bg-ink-50'}`}>
                <span className="font-mono text-xs text-ink-800">{r.run_no}</span>
                <span className="ml-auto flex items-center gap-1.5 text-[10px]">
                  {r.counts.critical > 0 && <span className="text-red-600">严{r.counts.critical}</span>}
                  {r.counts.warning > 0 && <span className="text-amber-600">警{r.counts.warning}</span>}
                  {r.counts.unavailable > 0 && <span className="text-ink-400">未{r.counts.unavailable}</span>}
                  <span className={`px-1 py-0.5 rounded ring-1 ${gradeStyle(r.grade)}`}>{r.grade}</span>
                </span>
              </button>
            ))}
            {filtered.length === 0 && (
              <div className="text-xs text-ink-400 p-4 text-center">没有符合条件的车次</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
//  ② 运算结果查看
// ══════════════════════════════════════════════════════════════════════════
function FindingCard({ f }: { f: WtFinding }) {
  const [open, setOpen] = useState(f.level === 'critical' || f.level === 'warning');
  const icon = f.status !== 'evaluated'
    ? <CircleSlash className="w-4 h-4 text-ink-400" />
    : f.level === 'critical' ? <XCircle className="w-4 h-4 text-red-600" />
      : f.level === 'warning' ? <AlertTriangle className="w-4 h-4 text-amber-600" />
        : f.level === 'notice' ? <Info className="w-4 h-4 text-sky-600" />
          : <CheckCircle2 className="w-4 h-4 text-emerald-600" />;
  return (
    <div className="rounded-lg border border-ink-200 bg-white">
      <button onClick={() => setOpen(!open)} className="w-full flex items-center gap-2 px-3 py-2 text-left">
        {icon}
        <span className="text-sm text-ink-800">{f.rule_name}</span>
        <span className="text-xs text-ink-500 font-mono">{fmt(f.value, f.unit)}</span>
        <span className="ml-auto text-xs text-ink-600 truncate max-w-96">{f.verdict}</span>
        {f.status === 'evaluated'
          ? <LevelChip level={f.level} text={f.level_label} />
          : <span className="text-[11px] text-ink-400 shrink-0">
              {f.status === 'unavailable' ? '未评定' : '不适用'}</span>}
      </button>
      {open && (
        <div className="px-3 pb-3 pt-1 border-t border-ink-100 text-xs space-y-1.5">
          <div><span className="text-ink-500">监测特征：</span>{f.feature_name}
            <code className="ml-1.5 text-[10px] text-ink-400">{f.feature}</code></div>
          {f.detail && <div><span className="text-ink-500">测量说明：</span>{f.detail}</div>}
          {f.cause && <div><span className="text-ink-500">原因分析：</span>{f.cause}</div>}
          {f.impact && <div><span className="text-ink-500">影响评估：</span>{f.impact}</div>}
          {f.action && <div className="text-ink-800"><span className="text-ink-500">处理建议：</span>{f.action}</div>}
          {f.method && (
            <div className="text-ink-400">
              <span className="text-ink-500">计算方法：</span>
              <code className="font-mono text-[10px]">{f.method}</code>
            </div>
          )}
          {!!(f.extras?.per_unit || f.extras?.per_sensor) && (
            <div className="text-ink-500">
              分量明细：
              <span className="font-mono text-[11px] text-ink-700">
                {Object.entries((f.extras.per_unit ?? f.extras.per_sensor) as Record<string, number>)
                  .map(([k, v]) => `${k}=${v}`).join('  ')}
              </span>
            </div>
          )}
          {f.refs.length > 0 && (
            <details className="text-ink-500">
              <summary className="cursor-pointer text-[11px]">判据依据（{f.refs.length}）</summary>
              <ul className="list-disc pl-4 mt-1 space-y-0.5 text-[11px]">
                {f.refs.map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

function ResultStep({ result, run, activeRun, setActiveRun, batchId, llmOn }: {
  result: WtBatchResult | null; run: WtRunResult | null; activeRun: string;
  setActiveRun: (s: string) => void; batchId: number | null; llmOn: boolean;
}) {
  const [summary, setSummary] = useState('');
  const [asking, setAsking] = useState(false);
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState('');
  const [filter, setFilter] = useState<'all' | 'problem'>('all');

  useEffect(() => { setSummary(''); setAnswer(''); }, [activeRun]);

  if (!result) return <Empty text="请先在「① 数据导入」中导入数据并执行检查。" />;

  const findings = run?.findings ?? [];
  const shown = filter === 'problem'
    ? findings.filter((f) => f.status !== 'evaluated' || f.level !== 'ok')
    : findings;

  return (
    <div className="grid grid-cols-1 xl:grid-cols-4 gap-5">
      <div className="xl:col-span-1 space-y-3">
        <RunPicker result={result} activeRun={activeRun} setActiveRun={setActiveRun} />
        <div className="rounded-lg border border-ink-200 bg-white p-3">
          <div className="text-xs font-medium text-ink-700 mb-1.5">批次汇总</div>
          <div className={`text-sm px-2 py-1 rounded ring-1 inline-block ${gradeStyle(result.summary.grade)}`}>
            {result.summary.grade}
          </div>
          <div className="text-[11px] text-ink-500 mt-2 space-y-0.5">
            <div>车次数 {result.summary.run_count}</div>
            <div>严重 {result.summary.totals.critical} · 警告 {result.summary.totals.warning}
              {' '}· 关注 {result.summary.totals.notice} · 未评定 {result.summary.totals.unavailable}</div>
            {result.summary.failed_runs.length > 0 &&
              <div className="text-red-600">不合格车次：{result.summary.failed_runs.join('、')}</div>}
          </div>
          {result.notes.length > 0 && (
            <div className="mt-2 pt-2 border-t border-ink-100 text-[11px] text-ink-500 space-y-1">
              {result.notes.map((n, i) => <div key={i}>· {n}</div>)}
            </div>
          )}
        </div>
      </div>

      <div className="xl:col-span-3 space-y-4">
        {run && (
          <>
            <div className="rounded-xl border border-ink-200 bg-white p-4">
              <div className="flex items-center gap-3 flex-wrap">
                <span className="font-mono text-lg text-ink-900">车次 {run.run_no}</span>
                <span className={`text-sm px-2 py-0.5 rounded ring-1 ${gradeStyle(run.grade)}`}>{run.grade}</span>
                <span className="text-xs text-ink-500">Ma {String((run.meta as Record<string, unknown>).mach ?? '—')}</span>
                <span className="text-xs text-ink-500">天平 {String((run.meta as Record<string, unknown>).balance_formula || '—')}</span>
                <span className="text-xs text-ink-500">
                  零飘比对 {run.compared_with ?? '无（首车次）'}
                </span>
                {llmOn && (
                  <button onClick={async () => {
                    if (batchId == null) return;
                    setSummary('生成中…');
                    const r = await api.wtSummarize(batchId, run.run_no);
                    setSummary(r.text ?? r.error ?? '');
                  }} className="ml-auto text-xs text-brand-600 hover:underline inline-flex items-center gap-1">
                    <Sparkles className="w-3 h-3" /> AI 质量小结
                  </button>
                )}
              </div>
              {summary && (
                <div className="mt-3 text-xs text-ink-700 bg-brand-50/50 rounded-lg p-3 leading-relaxed whitespace-pre-wrap">
                  {summary}
                </div>
              )}
            </div>

            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-ink-800">检查结果明细</span>
              <div className="ml-auto flex gap-1 text-xs">
                <button onClick={() => setFilter('all')}
                  className={`px-2 py-1 rounded ${filter === 'all' ? 'bg-brand-50 text-brand-700' : 'text-ink-500'}`}>
                  全部 {findings.length}
                </button>
                <button onClick={() => setFilter('problem')}
                  className={`px-2 py-1 rounded ${filter === 'problem' ? 'bg-brand-50 text-brand-700' : 'text-ink-500'}`}>
                  仅异常与未评定
                </button>
              </div>
            </div>
            {/* Key on the run too: a card's open/closed state is derived from
                its severity at mount, so reusing the component across runs
                would leave a critical finding collapsed just because the
                previously viewed run was clean. */}
            <div className="space-y-1.5">
              {shown.map((f) => <FindingCard key={`${run.run_no}-${f.rule_id}`} f={f} />)}
            </div>

            {llmOn && batchId != null && (
              <div className="rounded-xl border border-ink-200 bg-white p-3">
                <div className="flex items-center gap-2 mb-2">
                  <MessageSquare className="w-4 h-4 text-ink-400" />
                  <span className="text-sm font-medium text-ink-800">就本车次结果提问</span>
                  <span className="text-[11px] text-ink-400">只基于已算出的结果回答，不猜数</span>
                </div>
                <div className="flex gap-2">
                  <input value={question} onChange={(e) => setQuestion(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); (async () => {
                      if (!question.trim()) return;
                      setAsking(true);
                      const r = await api.wtAsk(batchId, run.run_no, question);
                      setAnswer(r.text ?? r.error ?? ''); setAsking(false);
                    })(); } }}
                    placeholder="例如：哪些项目没能评定？为什么？"
                    className="flex-1 text-sm px-3 py-1.5 rounded-lg border border-ink-200" />
                  <button disabled={asking || !question.trim()} onClick={async () => {
                    setAsking(true);
                    const r = await api.wtAsk(batchId, run.run_no, question);
                    setAnswer(r.text ?? r.error ?? ''); setAsking(false);
                  }} className="px-3 py-1.5 rounded-lg bg-brand-600 text-white text-sm disabled:opacity-50">
                    {asking ? <Loader2 className="w-4 h-4 animate-spin" /> : '提问'}
                  </button>
                </div>
                {answer && (
                  <div className="mt-2 text-xs text-ink-700 bg-ink-50 rounded-lg p-3 whitespace-pre-wrap leading-relaxed">
                    {answer}
                  </div>
                )}
              </div>
            )}
          </>
        )}

        {result.trends.length > 0 && result.runs.length > 1 && <TrendPanel result={result} />}
      </div>
    </div>
  );
}

function TrendPanel({ result }: { result: WtBatchResult }) {
  const flagged = result.trends.filter((t) => t.flagged);
  const [sel, setSel] = useState<string>(
    flagged[0]?.feature ?? result.trends[0]?.feature ?? '');
  const t = result.trends.find((x) => x.feature === sel);
  const data = t ? t.runs.map((rn, i) => ({ run: rn, v: t.values[i] })) : [];
  return (
    <div className="rounded-xl border border-ink-200 bg-white p-4">
      <div className="flex items-center gap-2 mb-2">
        <TrendingUp className="w-4 h-4 text-ink-400" />
        <span className="text-sm font-medium text-ink-800">多车次趋势</span>
        <select value={sel} onChange={(e) => setSel(e.target.value)}
          className="ml-auto text-xs px-2 py-1 rounded border border-ink-200 bg-white">
          {result.trends.map((x) => (
            <option key={x.feature} value={x.feature}>
              {x.flagged ? '⚠ ' : ''}{x.name}{x.unit ? ` (${x.unit})` : ''}
            </option>
          ))}
        </select>
      </div>
      {t && (
        <>
          <div style={{ height: 180 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="run" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} width={70} />
                <Tooltip contentStyle={{ fontSize: 12 }} />
                <Line type="monotone" dataKey="v" name={t.name}
                  stroke={t.flagged ? '#dc2626' : '#2563eb'} strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          {t.flagged ? (
            <div className="text-xs text-amber-800 bg-amber-50 rounded-lg p-2 mt-1">
              <div className="font-medium">趋势告警：{t.note}</div>
              <div className="text-[11px] text-amber-700 mt-1">判据依据：{t.reference}</div>
            </div>
          ) : (
            <div className="text-[11px] text-ink-400 mt-1">
              连续单调 {t.monotone_run} 个车次，未达趋势判据窗口。
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
//  ③ 气动曲线
// ══════════════════════════════════════════════════════════════════════════
const DEFAULT_YS = ['CAF', 'CN', 'CZ', 'CAB', 'MX', 'MY', 'MZ'];

function CurveStep({ batchId, result, activeRun, setActiveRun, llmOn }: {
  batchId: number | null; result: WtBatchResult | null;
  activeRun: string; setActiveRun: (s: string) => void; llmOn: boolean;
}) {
  const [x, setX] = useState('ALPHA');
  const [ys, setYs] = useState<string[]>(DEFAULT_YS);
  const [curve, setCurve] = useState<WtCurve | null>(null);
  const [busy, setBusy] = useState(false);
  const [narr, setNarr] = useState('');
  const [err, setErr] = useState('');
  // Shared axes vs small multiples — see the note at the chart below.
  const [split, setSplit] = useState(true);

  const draw = useCallback(async () => {
    if (batchId == null || !activeRun) return;
    setBusy(true); setErr('');
    try {
      setCurve(await api.wtCurve(batchId, activeRun, x, ys));
    } catch (e) { setErr(String(e)); setCurve(null); } finally { setBusy(false); }
  }, [batchId, activeRun, x, ys]);

  useEffect(() => { setNarr(''); draw().catch(() => {}); // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batchId, activeRun]);

  if (!result) return <Empty text="请先在「① 数据导入」中导入数据并执行检查。" />;

  // Recharts wants one row per x with a column per series.
  const rows = useMemo(() => {
    if (!curve) return [];
    const map = new Map<number, Record<string, number>>();
    curve.series.forEach((s) => s.x.forEach((xv, i) => {
      const row = map.get(xv) ?? { x: xv };
      row[s.key] = s.y[i];
      map.set(xv, row);
    }));
    return Array.from(map.values()).sort((a, b) => a.x - b.x);
  }, [curve]);

  return (
    <div className="grid grid-cols-1 xl:grid-cols-4 gap-5">
      <div className="xl:col-span-1 space-y-3">
        <RunPicker result={result} activeRun={activeRun} setActiveRun={setActiveRun} />
        <div className="rounded-lg border border-ink-200 bg-white p-3 space-y-3">
          <label className="block text-xs text-ink-600">
            横轴参数
            <select value={x} onChange={(e) => setX(e.target.value)}
              className="mt-1 w-full text-sm px-2 py-1.5 rounded-lg border border-ink-200 bg-white">
              {(curve?.available_columns ?? [{ key: 'ALPHA', label: '攻角 α (°)' }]).map((c) => (
                <option key={c.key} value={c.key}>{c.label}</option>
              ))}
            </select>
          </label>
          <div className="text-xs text-ink-600">
            <div className="flex items-center mb-1">
              纵轴参数（可多选）
              <button onClick={() => setYs(DEFAULT_YS)} className="ml-auto text-[11px] text-brand-600 hover:underline">
                恢复默认 CAF~MZ
              </button>
            </div>
            <div className="max-h-72 overflow-y-auto space-y-0.5 pr-1">
              {(curve?.available_columns ?? []).filter((c) => c.key !== x).map((c) => (
                <label key={c.key} className="flex items-center gap-1.5 px-1.5 py-0.5 rounded hover:bg-ink-50 cursor-pointer">
                  <input type="checkbox" checked={ys.includes(c.key)} className="accent-brand-600"
                    onChange={() => setYs(ys.includes(c.key) ? ys.filter((k) => k !== c.key) : [...ys, c.key])} />
                  <span className="text-[11px]">{c.label}</span>
                </label>
              ))}
            </div>
          </div>
          <button onClick={draw} disabled={busy}
            className="w-full px-3 py-1.5 rounded-lg bg-brand-600 text-white text-sm inline-flex items-center justify-center gap-1.5 disabled:opacity-50">
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <BarChart3 className="w-4 h-4" />} 绘制曲线
          </button>
        </div>
      </div>

      <div className="xl:col-span-3 space-y-4">
        {err && <div className="text-sm px-3 py-2 rounded-lg bg-amber-50 text-amber-800 ring-1 ring-amber-200">{err}</div>}
        {curve && (
          <>
            <div className="rounded-xl border border-ink-200 bg-white p-4">
              <div className="flex items-center gap-2 mb-2 text-xs text-ink-500 flex-wrap">
                <span className="text-sm font-medium text-ink-800">车次 {curve.run_no}</span>
                <span>Ma {curve.mach ?? '—'}</span>
                <span className="truncate">{curve.model}</span>
                {Object.entries(curve.flow).map(([k, v]) => (
                  <span key={k} className="font-mono text-[11px]">{k}={Number(v.toPrecision(6))}</span>
                ))}
                <div className="ml-auto flex gap-1">
                  <button onClick={() => setSplit(true)}
                    className={`px-2 py-0.5 rounded ${split ? 'bg-brand-50 text-brand-700' : 'text-ink-500'}`}>分图</button>
                  <button onClick={() => setSplit(false)}
                    className={`px-2 py-0.5 rounded ${!split ? 'bg-brand-50 text-brand-700' : 'text-ink-500'}`}>合图</button>
                </div>
              </div>
              {/* Split view matters here: CN spans ~1.2 while MX spans ~2e-4,
                  so on shared axes every moment coefficient collapses onto the
                  zero line. Engineers read these as separate panels anyway. */}
              {split ? (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                  {curve.series.map((s, i) => (
                    <div key={s.key} className="rounded-lg border border-ink-100 p-2">
                      <div className="text-[11px] text-ink-600 mb-1">{s.label}</div>
                      <div style={{ height: 150 }}>
                        <ResponsiveContainer width="100%" height="100%">
                          <LineChart data={rows} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#eef1f5" />
                            <XAxis dataKey="x" type="number" domain={['dataMin', 'dataMax']}
                              tick={{ fontSize: 10 }} />
                            <YAxis tick={{ fontSize: 10 }} width={60}
                              domain={['auto', 'auto']} tickFormatter={(v: number) => Number(v.toPrecision(3)).toString()} />
                            <Tooltip contentStyle={{ fontSize: 11 }} />
                            <Line type="monotone" dataKey={s.key} name={s.label}
                              stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
                              strokeWidth={1.8} dot={{ r: 2 }} />
                          </LineChart>
                        </ResponsiveContainer>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ height: 380 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={rows} margin={{ top: 8, right: 20, bottom: 34, left: 8 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                      <XAxis dataKey="x" type="number" domain={['dataMin', 'dataMax']}
                        tick={{ fontSize: 11 }}
                        label={{ value: curve.x_label, position: 'insideBottom', offset: -22, fontSize: 12 }} />
                      <YAxis tick={{ fontSize: 11 }} width={70} />
                      <Tooltip contentStyle={{ fontSize: 12 }} />
                      <Legend wrapperStyle={{ fontSize: 11, paddingTop: 8 }} />
                      {curve.series.map((s, i) => (
                        <Line key={s.key} type="monotone" dataKey={s.key} name={s.label}
                          stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
                          strokeWidth={1.8} dot={{ r: 2.5 }} />
                      ))}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>

            <div className="rounded-xl border border-ink-200 bg-white p-4">
              <div className="text-sm font-medium text-ink-800 mb-2">曲线特征量（确定性计算，非模型估计）</div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="text-ink-500 border-b border-ink-200">
                    <tr><th className="text-left py-1">系数</th><th className="text-left">线性斜率/度</th>
                      <th className="text-left">线性度 R²</th><th className="text-left">最小值</th>
                      <th className="text-left">最大值</th><th className="text-left">单调</th>
                      <th className="text-left">最大偏离线性处</th></tr>
                  </thead>
                  <tbody>
                    {curve.statistics.map((s) => (
                      <tr key={s.key} className="border-b border-ink-50">
                        <td className="py-1 text-ink-800">{s.label}</td>
                        <td className="font-mono">{s.slope_per_deg}</td>
                        <td className={`font-mono ${s.r2 > 0.99 ? 'text-emerald-700' : s.r2 < 0.5 ? 'text-ink-400' : ''}`}>
                          {s.r2.toFixed(4)}
                        </td>
                        <td className="font-mono text-[11px]">{s.min.y} @ {s.min.x}°</td>
                        <td className="font-mono text-[11px]">{s.max.y} @ {s.max.x}°</td>
                        <td>{s.monotone ? '是' : '否'}</td>
                        <td className="font-mono text-[11px]">{s.max_nonlinearity.x}° / {s.max_nonlinearity.deviation}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {llmOn && (
                <div className="mt-3">
                  <button disabled={busy} onClick={async () => {
                    if (batchId == null) return;
                    setNarr('生成中…');
                    const r = await api.wtCurveConclusion(batchId, curve.run_no, curve.statistics,
                      { mach: curve.mach, model: curve.model, flow: curve.flow });
                    setNarr(r.text ?? r.error ?? '');
                  }} className="text-xs text-brand-600 hover:underline inline-flex items-center gap-1">
                    <Sparkles className="w-3 h-3" /> 生成气动规律结论
                  </button>
                  {narr && (
                    <div className="mt-2 text-xs text-ink-700 bg-brand-50/50 rounded-lg p-3 leading-relaxed whitespace-pre-wrap">
                      {narr}
                    </div>
                  )}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
//  ④ 报告
// ══════════════════════════════════════════════════════════════════════════
function ReportStep({ batchId, result, activeRun, setActiveRun, llmOn }: {
  batchId: number | null; result: WtBatchResult | null;
  activeRun: string; setActiveRun: (s: string) => void; llmOn: boolean;
}) {
  const [sections, setSections] = useState<{ key: string; name: string; desc: string }[]>([]);
  const [picked, setPicked] = useState<Set<string>>(new Set(
    ['overview', 'verdict', 'problems', 'unavailable', 'curves', 'shift_record', 'basis']));
  const [kind, setKind] = useState<'report' | 'shift' | 'summary'>('report');
  const [title, setTitle] = useState('风洞试验过程质量检查报告');
  const [author, setAuthor] = useState('');
  const [content, setContent] = useState('');
  const [reportId, setReportId] = useState<number | null>(null);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState('');
  const [saved, setSaved] = useState('');

  useEffect(() => { api.wtReportSections().then((r) => setSections(r.sections)).catch(() => {}); }, []);

  if (!result) return <Empty text="请先在「① 数据导入」中导入数据并执行检查。" />;

  async function generate() {
    if (batchId == null) return;
    setBusy('gen'); setSaved('');
    try {
      let narratives: Record<string, string> = {};
      if (kind === 'report' && picked.has('curves') && llmOn) {
        try {
          const c = await api.wtCurve(batchId, activeRun, 'ALPHA', DEFAULT_YS);
          const n = await api.wtCurveConclusion(batchId, activeRun, c.statistics,
            { mach: c.mach, model: c.model, flow: c.flow });
          if (n.ok && n.text) narratives = { curves: n.text };
        } catch { /* 曲线不可用时报告照出 */ }
      }
      const r = await api.wtMakeReport(batchId, {
        run_no: activeRun, kind, sections: Array.from(picked),
        title, author, narratives, include_curve: picked.has('curves'),
      });
      setContent(r.content); setReportId(r.id); setEditing(false);
    } catch (e) { setSaved(String(e)); } finally { setBusy(''); }
  }

  async function save() {
    if (reportId == null) return;
    setBusy('save');
    try { await api.wtSaveReport(reportId, content); setSaved('已保存编辑内容。'); }
    catch (e) { setSaved(String(e)); } finally { setBusy(''); }
  }

  return (
    <div className="grid grid-cols-1 xl:grid-cols-4 gap-5">
      <div className="xl:col-span-1 space-y-3">
        <RunPicker result={result} activeRun={activeRun} setActiveRun={setActiveRun} />
        <div className="rounded-lg border border-ink-200 bg-white p-3 space-y-3">
          <div className="text-xs text-ink-600">
            报告类型
            <div className="mt-1 space-y-1">
              {([['report', '质量检查报告'], ['shift', '跟班记录（现行格式）'],
                ['summary', '多车次汇总报告']] as const).map(([k, label]) => (
                <label key={k} className="flex items-center gap-1.5 text-xs cursor-pointer">
                  <input type="radio" checked={kind === k} onChange={() => setKind(k)}
                    className="accent-brand-600" />{label}
                </label>
              ))}
            </div>
          </div>
          {kind === 'report' && (
            <div className="text-xs text-ink-600">
              自定义报告内容
              <div className="mt-1 space-y-0.5 max-h-64 overflow-y-auto">
                {sections.map((s) => (
                  <label key={s.key} title={s.desc}
                    className="flex items-start gap-1.5 px-1 py-0.5 rounded hover:bg-ink-50 cursor-pointer">
                    <input type="checkbox" checked={picked.has(s.key)} className="mt-0.5 accent-brand-600"
                      onChange={() => {
                        const n = new Set(picked);
                        if (n.has(s.key)) n.delete(s.key); else n.add(s.key);
                        setPicked(n);
                      }} />
                    <span className="text-[11px]">{s.name}</span>
                  </label>
                ))}
              </div>
            </div>
          )}
          <label className="block text-xs text-ink-600">
            标题
            <input value={title} onChange={(e) => setTitle(e.target.value)}
              className="mt-1 w-full text-sm px-2 py-1 rounded-lg border border-ink-200" />
          </label>
          <label className="block text-xs text-ink-600">
            编制人
            <input value={author} onChange={(e) => setAuthor(e.target.value)}
              className="mt-1 w-full text-sm px-2 py-1 rounded-lg border border-ink-200" />
          </label>
          <button onClick={generate} disabled={busy === 'gen'}
            className="w-full px-3 py-1.5 rounded-lg bg-brand-600 text-white text-sm inline-flex items-center justify-center gap-1.5 disabled:opacity-50">
            {busy === 'gen' ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileText className="w-4 h-4" />}
            生成报告
          </button>
        </div>
      </div>

      <div className="xl:col-span-3 space-y-3">
        {!content && <Empty text="在左侧选择报告类型与章节，点「生成报告」。" />}
        {content && (
          <>
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-ink-800">报告预览</span>
              <span className="text-[11px] text-ink-400">
                {editing ? '编辑模式 — 内容可直接修改' : '渲染模式'}
              </span>
              <button onClick={() => setEditing(!editing)}
                className="ml-auto text-xs text-brand-600 hover:underline">
                {editing ? '预览渲染效果' : '编辑内容'}
              </button>
              <button onClick={save} disabled={busy === 'save' || reportId == null}
                className="text-xs px-2.5 py-1 rounded-lg border border-ink-200 text-ink-600 disabled:opacity-50">
                保存编辑
              </button>
              {reportId != null && (
                <button onClick={async () => {
                  setBusy('dl');
                  try {
                    const { blob, filename } = await api.wtDownloadReport(reportId, 'txt');
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url; a.download = filename;
                    document.body.appendChild(a); a.click(); a.remove();
                    URL.revokeObjectURL(url);
                    setSaved(`已导出 ${filename}`);
                  } catch (e) { setSaved(String(e)); } finally { setBusy(''); }
                }} disabled={busy === 'dl'}
                  className="text-xs px-2.5 py-1 rounded-lg bg-emerald-600 text-white inline-flex items-center gap-1 disabled:opacity-50">
                  {busy === 'dl' ? <Loader2 className="w-3 h-3 animate-spin" /> : <Download className="w-3 h-3" />}
                  导出报告
                </button>
              )}
            </div>
            {saved && <div className="text-xs text-ink-500">{saved}</div>}
            {editing ? (
              <textarea value={content} onChange={(e) => setContent(e.target.value)}
                className="w-full h-[70vh] text-xs font-mono px-3 py-2 rounded-xl border border-ink-200 bg-white" />
            ) : (
              <div className="rounded-xl border border-ink-200 bg-white p-6 max-h-[75vh] overflow-y-auto text-sm text-ink-800 prose-tight wt-report">
                <Markdown>{content}</Markdown>
              </div>
            )}
            <div className="text-[11px] text-ink-400">
              导出文件名遵循「车次号_跟班记录」的既有命名约定；编辑后的内容会随导出一并保存。
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="text-center py-20 text-sm text-ink-400">
      <Wind className="w-8 h-8 mx-auto mb-2 text-ink-200" />
      {text}
    </div>
  );
}

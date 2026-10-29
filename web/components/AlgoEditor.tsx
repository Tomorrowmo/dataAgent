'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Loader2, Play, Save, Sparkles, Download, Trash2, X, Copy, ShieldCheck } from 'lucide-react';
import { api, type Algorithm, type Dataset, type TestResult, type GenerationResult, type AlgoVersion, type ParamSpec, type RunResult } from '@/lib/api';
import { cellStr } from '@/lib/algoMeta';

// 代码编辑器（弹窗里的小 IDE）—— 参考 SFBYDataLab 能力库的做法:
// 行号 / 校验 / 调试运行（沙箱 + 选测试数据）/ 问题跳转到行 / AI 校正（先预览再应用）/
// 版本历史 / 保存为新版本（服务端沙箱复跑通过才落库）/ 导出 / 删除。
// 内置算法只读（它们在进程内运行、不走沙箱）,可「复制为我的算法」后再改。

export type EditorTarget =
  | { mode: 'edit'; algoId: number }
  | { mode: 'builtin'; slug: string }
  | { mode: 'new'; code: string; source: 'user' | 'ai'; title?: string };

type Problem = { level: 'bad' | 'warn'; msg: string; line: number };
type Tab = 'out' | 'prob' | 'data' | 'ai' | 'hist';

const LH = 20; // editor line height (px) — gutter and textarea must agree

/** Pick the most useful line number out of an error message: the innermost frame
 *  in the user's code (`File "<algorithm>", line N`), else "(line N)" / "line N". */
export function errLine(msg: string | undefined | null): number {
  const s = String(msg || '');
  const frames = [...s.matchAll(/File "<algorithm>", line (\d+)/g)];
  if (frames.length) return Number(frames[frames.length - 1][1]);
  const m = /\(line (\d+)\)|line (\d+)/i.exec(s);
  return m ? Number(m[1] || m[2]) : 0;
}

function lastLine(s: string): string {
  const ls = s.trim().split('\n').filter(Boolean);
  return ls[ls.length - 1] || s;
}

function problemsFrom(validation?: TestResult['validation'], execution?: RunResult, extra?: string): Problem[] {
  const out: Problem[] = [];
  for (const e of validation?.errors ?? []) out.push({ level: 'bad', msg: e, line: errLine(e) });
  if (execution && execution.status !== 'ok' && execution.error && !execution.error.startsWith('validation failed')) {
    out.push({ level: 'bad', msg: lastLine(execution.error), line: errLine(execution.error) });
  }
  if (extra) out.push({ level: 'bad', msg: extra, line: errLine(extra) });
  return out;
}

function defaultsFrom(schema?: Record<string, ParamSpec> | null): string {
  const p: Record<string, unknown> = {};
  for (const [k, sp] of Object.entries(schema || {})) if (sp && sp.default !== undefined && sp.default !== null) p[k] = sp.default;
  return JSON.stringify(p, null, 2);
}

function CodeView({ code, mark }: { code: string; mark?: Set<number> }) {
  const lines = code.replace(/\r/g, '').split('\n');
  return (
    <pre className="bg-ink-900 text-ink-50 rounded-lg p-2 text-[12px] leading-[18px] overflow-auto max-h-[50vh] font-mono">
      {lines.map((l, i) => (
        <div key={i} className={mark?.has(i) ? 'bg-emerald-900/60' : ''}>
          <span className="inline-block w-8 pr-2 text-right text-ink-500 select-none">{i + 1}</span>{l || ' '}
        </div>
      ))}
    </pre>
  );
}

export default function AlgoEditor({ target: initial, onClose, onSaved, onDeleted, onDirtyChange }: {
  target: EditorTarget;
  onClose: () => void;
  onSaved?: (a: Algorithm) => void;
  onDeleted?: () => void;
  /** Lets the host (算法库右侧) ask before navigating away from unsaved edits. */
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const [target, setTarget] = useState<EditorTarget>(initial);
  const [code, setCode] = useState(initial.mode === 'new' ? initial.code : '');
  const [saved, setSaved] = useState(initial.mode === 'new' ? '' : '');   // last persisted code (dirty check)
  const [head, setHead] = useState<{ name: string; slug: string; version?: number; source: string; verified?: boolean; file?: string; line?: number }>(
    { name: initial.mode === 'new' ? (initial.title || '新算法') : '', slug: '', source: initial.mode === 'new' ? initial.source : '' });
  const [editable, setEditable] = useState(initial.mode === 'new');
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [datasetId, setDatasetId] = useState<number | null>(null);
  const [paramsText, setParamsText] = useState('{}');
  const [out, setOut] = useState<TestResult | null>(null);
  const [problems, setProblems] = useState<Problem[]>([]);
  const [tab, setTab] = useState<Tab>('out');
  const [busy, setBusy] = useState<'' | 'load' | 'run' | 'save' | 'fix' | 'del'>(initial.mode === 'new' ? '' : 'load');
  const [status, setStatus] = useState('');
  const [note, setNote] = useState('');
  const [fixAsk, setFixAsk] = useState('');
  const [fix, setFix] = useState<GenerationResult | null>(null);
  const [fixErr, setFixErr] = useState('');
  const [versions, setVersions] = useState<AlgoVersion[]>([]);
  const [pos, setPos] = useState({ line: 1, col: 1 });
  const taRef = useRef<HTMLTextAreaElement>(null);
  const gutRef = useRef<HTMLDivElement>(null);

  const dirty = editable && code !== saved;
  const isCustom = target.mode === 'edit';
  useEffect(() => { onDirtyChange?.(dirty); }, [dirty, onDirtyChange]);

  useEffect(() => { api.listDatasets().then((d) => { setDatasets(d); if (d[0]) setDatasetId((cur) => cur ?? d[0].id); }).catch(() => {}); }, []);

  // Load source for edit / builtin targets.
  useEffect(() => {
    let alive = true;
    if (target.mode === 'edit') {
      setBusy('load');
      Promise.all([api.algorithmSource(target.algoId), api.algorithmVersions(target.algoId).catch(() => [])]).then(([s, vs]) => {
        if (!alive) return;
        setCode(s.code); setSaved(s.code); setEditable(s.editable);
        setHead({ name: s.name, slug: s.slug, version: s.version, source: s.source, verified: s.verified });
        setParamsText(defaultsFrom(s.params_schema));
        const dsid = (s.test_report as { dataset_id?: number })?.dataset_id;
        if (typeof dsid === 'number') setDatasetId(dsid);
        setVersions(vs); setStatus(s.editable ? '就绪' : '只读（不是你的算法）');
      }).catch((e) => setStatus('载入失败:' + (e as Error).message)).finally(() => alive && setBusy(''));
    } else if (target.mode === 'builtin') {
      setBusy('load');
      api.builtinSource(target.slug).then((s) => {
        if (!alive) return;
        setCode(s.code); setSaved(s.code); setEditable(false);
        setHead({ name: s.name, slug: s.slug, source: 'builtin', file: s.file, line: s.line });
        setStatus('内置算法只读 —「复制为我的算法」后可修改');
        setTab('prob');
      }).catch((e) => setStatus('载入失败:' + (e as Error).message)).finally(() => alive && setBusy(''));
    } else {
      setCode(target.code); setSaved(''); setEditable(true);
      setHead({ name: target.title || '新算法', slug: '', source: target.source });
      setStatus('新算法（未保存）');
    }
    return () => { alive = false; };
  }, [target]);

  function parseParams(): Record<string, unknown> | null {
    try { const v = JSON.parse(paramsText || '{}'); return v && typeof v === 'object' ? v : {}; }
    catch { setProblems([{ level: 'bad', msg: '测试参数不是合法 JSON', line: 0 }]); setTab('data'); return null; }
  }

  function gotoLine(line: number) {
    const ta = taRef.current; if (!ta || !line) return;
    const ls = ta.value.split('\n'); let p = 0;
    for (let i = 0; i < line - 1 && i < ls.length; i++) p += ls[i].length + 1;
    ta.focus(); ta.selectionStart = p; ta.selectionEnd = p + (ls[line - 1] || '').length;
    ta.scrollTop = Math.max(0, (line - 4) * LH);
    syncPos();
  }

  function syncPos() {
    const ta = taRef.current; if (!ta) return;
    const before = ta.value.slice(0, ta.selectionStart).split('\n');
    setPos({ line: before.length, col: before[before.length - 1].length + 1 });
  }

  async function validate() {
    const r = await api.testAlgorithm(code, {}, undefined).catch(() => null);
    // /test always runs too; for a pure static check we only read `validation`.
    if (!r) return;
    const probs = problemsFrom(r.validation);
    setProblems(probs); setTab('prob');
    setStatus(r.validation.ok ? '静态校验通过' : `校验未通过:${probs.length} 处`);
    if (probs[0]?.line) gotoLine(probs[0].line);
  }

  async function run() {
    const params = parseParams(); if (params === null) return;
    setBusy('run'); setStatus('沙箱运行中…');
    try {
      const r = await api.testAlgorithm(code, params, datasetId ?? undefined);
      setOut(r);
      const probs = problemsFrom(r.validation, r.execution);
      setProblems(probs); setTab('out');
      const ok = r.validation.ok && r.execution.status === 'ok';
      setStatus(ok ? `沙箱通过 · ${r.execution.duration_ms} ms` : '沙箱未通过');
      if (!ok && probs[0]?.line) gotoLine(probs[0].line);
      // First run on new code: fill test params from META defaults if still empty.
      if (paramsText.trim() === '{}' && r.meta && (r.meta as { params_schema?: Record<string, ParamSpec> }).params_schema) {
        setParamsText(defaultsFrom((r.meta as { params_schema?: Record<string, ParamSpec> }).params_schema));
      }
    } catch (e) {
      setProblems([{ level: 'bad', msg: (e as Error).message, line: 0 }]); setTab('prob'); setStatus('运行失败');
    } finally { setBusy(''); }
  }

  async function save() {
    if (!editable) return;
    const params = parseParams(); if (params === null) return;
    setBusy('save'); setStatus('保存中:服务端沙箱复跑…');
    try {
      if (target.mode === 'edit') {
        const r = await api.updateAlgorithm(target.algoId, { code, note, dataset_id: datasetId ?? undefined, params });
        if (!r.ok) {
          const probs = problemsFrom(r.validation, r.execution, r.stage === 'meta' ? r.error : undefined);
          setProblems(probs);
          if (r.execution) setOut({ validation: r.validation!, execution: r.execution });
          setTab(r.stage === 'sandbox' ? 'out' : 'prob');
          setStatus('未保存:' + ({ validation: '静态校验未通过', meta: 'META 解析失败', sandbox: '沙箱运行未通过' } as Record<string, string>)[r.stage || ''] );
          if (probs[0]?.line) gotoLine(probs[0].line);
          return;
        }
        setSaved(code); setNote('');
        setHead((h) => ({ ...h, version: r.version, verified: true, name: r.algorithm?.name ?? h.name }));
        setStatus(`已保存为 v${r.version}${r.note ? ' · ' + r.note : ''}`);
        api.algorithmVersions(target.algoId).then(setVersions).catch(() => {});
        if (r.algorithm) onSaved?.(r.algorithm);
      } else {
        const a = await api.saveAlgorithm({
          code, source: target.mode === 'new' ? target.source : 'user',
          verify: true, dataset_id: datasetId ?? undefined, params, note: note || '新建',
        });
        setSaved(code); setNote('');
        setStatus(`已入库 ${a.slug}`);
        onSaved?.(a);
        if (a.id != null) setTarget({ mode: 'edit', algoId: a.id });
      }
    } catch (e) {
      const msg = (e as Error).message;
      setProblems(problemsFrom(undefined, undefined, msg)); setTab('prob'); setStatus('未保存');
      const l = errLine(msg); if (l) gotoLine(l);
    } finally { setBusy(''); }
  }

  async function aiFix() {
    setBusy('fix'); setFix(null); setFixErr('');
    const lastErr = out && out.execution.status !== 'ok' ? out.execution.error : problems.map((p) => p.msg).join('\n');
    try { setFix(await api.autofixAlgorithm(code, datasetId ?? undefined, fixAsk, lastErr || '')); }
    catch (e) { setFixErr((e as Error).message); }
    finally { setBusy(''); }
  }

  async function forkBuiltin() {
    if (target.mode !== 'builtin') return;
    try {
      const r = await api.forkBuiltin(target.slug);
      setTarget({ mode: 'new', code: r.code, source: 'user', title: `${head.name}（副本）` });
      setTab('out'); setOut(null); setProblems([]);
    } catch (e) { setStatus('复制失败:' + (e as Error).message); }
  }

  async function remove() {
    if (target.mode !== 'edit') return;
    if (!window.confirm(`删除算法「${head.name}」（含全部历史版本）？在用它的流程会找不到这个工具。`)) return;
    setBusy('del');
    try { await api.deleteAlgorithm(target.algoId); onDeleted?.(); onClose(); }
    catch (e) { setStatus('删除失败:' + (e as Error).message); setBusy(''); }
  }

  function exportPy() {
    const blob = new Blob([code], { type: 'text/x-python' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = `${head.slug || 'algorithm'}.py`; a.click();
    URL.revokeObjectURL(a.href);
  }

  function close() {
    if (dirty && !window.confirm('有未保存的改动，确定关闭？')) return;
    onClose();
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    const ta = e.currentTarget;
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); if (busy === '') run(); return; }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); if (busy === '') save(); return; }
    if (!editable) return;
    const s = ta.selectionStart, en = ta.selectionEnd, v = ta.value;
    const put = (next: string, caret: number) => { setCode(next); requestAnimationFrame(() => { ta.selectionStart = ta.selectionEnd = caret; syncPos(); }); };
    if (e.key === 'Tab') {
      e.preventDefault();
      const ls = v.lastIndexOf('\n', s - 1) + 1;
      if (e.shiftKey) { if (v.slice(ls, ls + 4) === '    ') put(v.slice(0, ls) + v.slice(ls + 4), Math.max(ls, s - 4)); }
      else put(v.slice(0, s) + '    ' + v.slice(en), s + 4);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const ls = v.lastIndexOf('\n', s - 1) + 1;
      const line = v.slice(ls, s);
      const ind = (line.match(/^\s*/) || [''])[0] + (/[:([{]\s*$/.test(line) ? '    ' : '');
      put(v.slice(0, s) + '\n' + ind + v.slice(en), s + 1 + ind.length);
    }
  }

  const nLines = code.split('\n').length;
  const errLines = useMemo(() => new Set(problems.map((p) => p.line).filter(Boolean)), [problems]);
  const fixMark = useMemo(() => {
    if (!fix) return undefined;
    const cur = new Set(code.split('\n').map((l) => l.trim()));
    return new Set(fix.code.split('\n').map((l, i) => (cur.has(l.trim()) ? -1 : i)).filter((i) => i >= 0));
  }, [fix, code]);

  const btn = 'text-xs px-2.5 py-1.5 rounded-lg flex items-center gap-1.5 disabled:opacity-50 shrink-0';
  const ghost = `${btn} ring-1 ring-ink-200 text-ink-700 hover:bg-ink-50`;
  const tabs: [Tab, string][] = target.mode === 'builtin'
    ? [['prob', '说明']]
    : [['out', '输出'], ['prob', `问题${problems.length ? ' · ' + problems.length : ''}`], ['data', '测试数据'], ['ai', 'AI 校正'], ...(isCustom ? [['hist', `历史${versions.length ? ' · ' + versions.length : ''}`] as [Tab, string]] : [])];

  const ex = out?.execution;
  const sum = (ex?.summary || {}) as { type?: string; columns?: string[]; head?: Record<string, unknown>[]; value?: unknown };

  return (
    <div className="h-full flex">
      <div className="bg-white w-full h-full flex flex-col overflow-hidden">
        {/* header */}
        <div className="flex flex-wrap items-center gap-2 px-3 py-2 border-b border-ink-200">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <b className="text-sm truncate">{target.mode === 'builtin' ? '查看内置算法' : target.mode === 'new' ? '新建算法' : editable ? '编辑算法' : '查看算法'} · {head.name}</b>
              {head.version != null && <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-ink-100 text-ink-600">v{head.version}</span>}
              {head.source === 'builtin'
                ? <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-ink-100 text-ink-600">内置 · 只读</span>
                : head.verified === false && <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700">草稿 · 未验证</span>}
            </div>
            <div className="text-[11px] text-ink-400 font-mono truncate">
              {head.source === 'builtin' ? `${head.file}:${head.line} · 进程内运行（不走沙箱）` : `${head.slug || '（保存时取 META.slug）'} · 入口 run(df, **params) · 沙箱运行`}
            </div>
          </div>
          {target.mode === 'builtin' ? (
            <button onClick={forkBuiltin} className={`${btn} bg-brand-600 text-white hover:bg-brand-700`}><Copy className="w-3.5 h-3.5" /> 复制为我的算法</button>
          ) : editable && (
            <>
              <button onClick={validate} disabled={!!busy} className={ghost}><ShieldCheck className="w-3.5 h-3.5" /> 校验</button>
              <button onClick={run} disabled={!!busy} className={ghost} title="Ctrl+Enter">
                {busy === 'run' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />} 调试运行
              </button>
              <button onClick={() => setTab('ai')} disabled={!!busy} className={ghost}><Sparkles className="w-3.5 h-3.5" /> AI 校正</button>
              <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="这版改了什么（可空）"
                className="text-xs border border-ink-200 rounded-lg px-2 py-1.5 w-40" />
              <button onClick={save} disabled={!!busy || (isCustom && !dirty)} className={`${btn} bg-brand-600 text-white hover:bg-brand-700`} title="Ctrl+S">
                {busy === 'save' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />} {isCustom ? '保存为新版本' : '沙箱通过后入库'}
              </button>
            </>
          )}
          <button onClick={exportPy} className={ghost}><Download className="w-3.5 h-3.5" /> 导出 .py</button>
          {isCustom && editable && <button onClick={remove} disabled={!!busy} className={`${btn} ring-1 ring-red-200 text-red-600 hover:bg-red-50`}><Trash2 className="w-3.5 h-3.5" /> 删除</button>}
          <button onClick={close} className={ghost} title="关闭编辑器，回到算法详情"><X className="w-3.5 h-3.5" /> 关闭编辑器</button>
        </div>

        {/* body */}
        {/* The editor sits beside the run panel (about half the pane), so code is
            on top and the tool panel below it. */}
        <div className="flex-1 min-h-0 flex flex-col">
          <div className="flex-1 min-h-[40vh] flex bg-ink-900 relative">
            {busy === 'load' && <div className="absolute inset-0 grid place-items-center text-ink-300 text-sm"><Loader2 className="w-5 h-5 animate-spin" /></div>}
            <div ref={gutRef} className="w-12 shrink-0 overflow-hidden text-right pr-2 pt-3 font-mono text-[12px] text-ink-500 select-none" style={{ lineHeight: `${LH}px` }}>
              {Array.from({ length: nLines }, (_, i) => (
                <div key={i} className={errLines.has(i + 1) ? 'text-red-400 font-bold' : ''}>{i + 1}</div>
              ))}
            </div>
            <textarea
              ref={taRef}
              value={code}
              readOnly={!editable}
              onChange={(e) => setCode(e.target.value)}
              onKeyDown={onKeyDown}
              onKeyUp={syncPos}
              onClick={syncPos}
              onScroll={(e) => { if (gutRef.current) gutRef.current.scrollTop = e.currentTarget.scrollTop; }}
              spellCheck={false}
              wrap="off"
              className="flex-1 bg-transparent text-ink-50 font-mono text-[13px] pt-3 pr-3 resize-none outline-none overflow-auto"
              style={{ lineHeight: `${LH}px`, tabSize: 4 }}
            />
          </div>

          <div className="h-[42%] shrink-0 border-t border-ink-200 flex flex-col min-h-0">
            <div className="flex gap-1 px-2 pt-2 border-b border-ink-200 overflow-x-auto">
              {tabs.map(([k, label]) => (
                <button key={k} onClick={() => setTab(k)}
                  className={`text-xs px-2.5 py-1.5 rounded-t-lg whitespace-nowrap ${tab === k ? 'bg-brand-50 text-brand-700 font-medium' : 'text-ink-500 hover:text-ink-700'}`}>{label}</button>
              ))}
            </div>
            <div className="flex-1 overflow-y-auto p-3 text-sm space-y-2">
              {target.mode === 'builtin' && (
                <div className="text-xs text-ink-600 space-y-2">
                  <p>内置算法在后端进程内直接运行（不经过沙箱），所以这里只读。</p>
                  <p>点右上角<b>「复制为我的算法」</b>：会把它的函数（改名为 <code>run</code>）连同用到的辅助函数、import 和 META 一起生成一份<b>自定义算法</b>，在沙箱里运行，可以随意修改、调试、保存版本。</p>
                </div>
              )}

              {tab === 'out' && target.mode !== 'builtin' && (!out ? (
                <div className="text-xs text-ink-400">点「调试运行」（Ctrl+Enter）：静态校验 → 沙箱子进程用「测试数据」里选的数据集和参数跑一遍。print 的输出也会显示在这里。</div>
              ) : (
                <>
                  <div className={`rounded-lg px-2.5 py-1.5 text-xs ${ex?.status === 'ok' && out.validation.ok ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'}`}>
                    {ex?.status === 'ok' && out.validation.ok ? `沙箱通过 · ${ex.duration_ms} ms` : '未通过'}
                    {datasetId != null && <> · 数据:{datasets.find((d) => d.id === datasetId)?.name}</>}
                  </div>
                  {ex?.status !== 'ok' && ex?.error && <pre className="text-[11px] bg-red-50/50 ring-1 ring-red-100 rounded p-2 whitespace-pre-wrap font-mono">{ex.error.slice(0, 4000)}</pre>}
                  {ex?.status === 'ok' && (sum.type === 'dataframe' && sum.head?.length ? (
                    <div className="overflow-auto max-h-64 ring-1 ring-ink-200 rounded">
                      <table className="text-[11px] min-w-full">
                        <thead className="bg-ink-50 sticky top-0"><tr>{(sum.columns ?? Object.keys(sum.head[0])).map((c) => <th key={c} className="px-2 py-1 text-left font-medium whitespace-nowrap">{c}</th>)}</tr></thead>
                        <tbody>{sum.head.map((r, i) => <tr key={i} className="border-t border-ink-100">{(sum.columns ?? Object.keys(sum.head![0])).map((c) => <td key={c} className="px-2 py-0.5 font-mono whitespace-nowrap">{cellStr(r[c])}</td>)}</tr>)}</tbody>
                      </table>
                    </div>
                  ) : <pre className="text-[11px] bg-ink-50 rounded p-2 overflow-auto max-h-64">{JSON.stringify(sum.value ?? sum, null, 2).slice(0, 4000)}</pre>)}
                  {ex?.logs && <><div className="text-[11px] text-ink-400">输出（print / 警告）</div><pre className="text-[11px] bg-ink-50 rounded p-2 whitespace-pre-wrap max-h-48 overflow-auto">{ex.logs.slice(-4000)}</pre></>}
                </>
              ))}

              {tab === 'prob' && target.mode !== 'builtin' && (problems.length ? (
                <ul className="space-y-1">
                  {problems.map((p, i) => (
                    <li key={i} onClick={() => gotoLine(p.line)}
                      className={`text-xs rounded px-2 py-1.5 ring-1 ${p.line ? 'cursor-pointer hover:bg-red-50' : ''} ${p.level === 'warn' ? 'ring-amber-200 text-amber-800' : 'ring-red-200 text-red-700'}`}>
                      <span className="font-semibold mr-1">{p.line ? `行 ${p.line}` : '错误'}</span>{p.msg}
                    </li>
                  ))}
                </ul>
              ) : <div className="text-xs text-ink-400">没有问题。「校验」做静态检查：只允许 numpy / pandas / scipy / sklearn / 标准库；禁止 os、文件、网络、eval 等；必须有顶级 META 字典和 run(df, **params)。</div>)}

              {tab === 'data' && (
                <div className="space-y-2">
                  <label className="block text-xs text-ink-500">测试数据集（调试运行和保存时的沙箱复跑都用它）</label>
                  <select value={datasetId ?? ''} onChange={(e) => setDatasetId(e.target.value ? Number(e.target.value) : null)}
                    className="w-full border border-ink-200 rounded-lg px-2 py-1.5 bg-white text-sm">
                    <option value="">（无 —— run 收到的 df 为 None）</option>
                    {datasets.map((d) => <option key={d.id} value={d.id}>{d.name} ({d.rows} × {d.columns})</option>)}
                  </select>
                  {datasetId != null && <div className="text-[11px] text-ink-400 break-all">列:{(datasets.find((d) => d.id === datasetId)?.schema?.columns ?? []).map((c) => c.name).join(', ')}</div>}
                  <label className="block text-xs text-ink-500">测试参数（JSON，传给 run 的 **params）</label>
                  <textarea value={paramsText} onChange={(e) => setParamsText(e.target.value)} rows={8} spellCheck={false}
                    className="w-full font-mono text-xs border border-ink-200 rounded-lg p-2" />
                </div>
              )}

              {tab === 'ai' && (
                <div className="space-y-2">
                  <div className="text-xs text-ink-500">把当前代码、你的要求和最近一次报错交给 AI 改写（会在沙箱自测）。改写稿<b>不会直接覆盖</b>，先看再「应用到编辑器」。</div>
                  <textarea value={fixAsk} onChange={(e) => setFixAsk(e.target.value)} rows={3}
                    placeholder="例如：加一个 window 参数；缺失值先插值再计算；修正下面的报错"
                    className="w-full text-sm border border-ink-200 rounded-lg p-2" />
                  <button onClick={aiFix} disabled={!!busy} className={`${btn} bg-violet-600 text-white hover:bg-violet-700`}>
                    {busy === 'fix' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />} 让 AI 改
                  </button>
                  {fixErr && <div className="text-xs text-red-600">{fixErr}</div>}
                  {fix && (
                    <>
                      <div className={`text-xs rounded px-2 py-1.5 ${fix.all_tests_passed ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
                        沙箱自测 {fix.tests.filter((t) => t.status === 'ok').length}/{fix.tests.length} {fix.all_tests_passed ? '全部通过' : '未全通过'} · 绿色为改动行
                      </div>
                      <button onClick={() => { setCode(fix.code); setFix(null); setStatus('已应用 AI 修改稿（未保存）'); }}
                        className={`${btn} bg-brand-600 text-white hover:bg-brand-700`}>应用到编辑器</button>
                      <CodeView code={fix.code} mark={fixMark} />
                    </>
                  )}
                </div>
              )}

              {tab === 'hist' && (versions.length ? (
                <ul className="space-y-1.5">
                  {versions.map((v) => (
                    <li key={v.version + (v.created_at || '')} className={`rounded-lg ring-1 p-2 text-xs ${v.current ? 'ring-brand-300 bg-brand-50/50' : 'ring-ink-200'}`}>
                      <div className="flex items-center gap-2">
                        <b>v{v.version}</b>{v.current && <span className="text-brand-600">当前</span>}
                        {!v.verified && <span className="text-amber-600">未验证</span>}
                        <span className="text-ink-400 ml-auto">{v.created_at ? new Date(v.created_at).toLocaleString() : ''}</span>
                      </div>
                      <div className="text-ink-600 mt-0.5">{v.note || '—'}</div>
                      {editable && !v.current && (
                        <button onClick={() => { setCode(v.code); setStatus(`已载入 v${v.version} 的代码（未保存，保存后成为新版本）`); }}
                          className="mt-1 text-brand-600 hover:underline">载入到编辑器</button>
                      )}
                    </li>
                  ))}
                </ul>
              ) : <div className="text-xs text-ink-400">还没有历史版本。</div>)}
            </div>
          </div>
        </div>

        {/* status bar */}
        <div className="flex items-center gap-3 px-3 py-1 border-t border-ink-200 text-[11px] text-ink-500 bg-ink-50">
          <span className="truncate">{dirty ? '● 已修改，未保存 · ' : ''}{status}</span>
          <span className="ml-auto whitespace-nowrap">行 {pos.line}，列 {pos.col}</span>
          <span className="whitespace-nowrap">{code.length} 字符</span>
          {editable && <span className="whitespace-nowrap max-md:hidden">Ctrl+Enter 运行 · Ctrl+S 保存</span>}
        </div>
      </div>
    </div>
  );
}

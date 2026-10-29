'use client';

import { useEffect, useRef, useState } from 'react';
import { Send, Loader2, Sparkles, Upload, Undo2, Wrench, Square, CheckCircle2, AlertTriangle, Bot, User, ShieldCheck, XCircle, Circle, Settings2 } from 'lucide-react';
import { api, streamStudio, type Algorithm, type Dataset, type StudioEvent, type TestResult, type AdmissionItem } from '@/lib/api';
import AlgoEditor from '@/components/AlgoEditor';

// 算法共创: chat on the left, the live code editor on the right. Each turn the AI
// either asks one clarifying question (clickable options), writes / modifies the
// code (build stages streamed live, changed lines tinted, undoable), or answers a
// question. Modifications start from whatever is in the editor — hand edits too.

type Stage = Extract<StudioEvent, { kind: 'progress' }>;
type Msg = {
  id: number;
  role: 'user' | 'ai';
  text: string;
  kind?: 'pending' | 'ask' | 'answer' | 'result' | 'error' | 'info' | 'check';
  /** Admission checklist (kind 'check'); `checking` while it runs. */
  items?: AdmissionItem[];
  checkOk?: boolean;
  checking?: boolean;
  /** Show "go to run settings" (next step once the code can join). */
  nextStep?: boolean;
  options?: string[];
  stages?: Stage[];
  result?: { name: string; passed: boolean; ok: number; total: number; repairs: number; changed: number; reason: string };
  prevCode?: string;   // editor code before this AI change → undo
  undone?: boolean;
};

const STARTERS: Record<'ai' | 'upload', string[]> = {
  ai: ['对选定列做移动中位数滤波，窗口可调', '按 x、y 两列拟合 y = ax² + bx + c，输出系数和 R²', '统计每列缺失值和异常值比例'],
  upload: ['补齐平台规范（META + run）', '这段代码在做什么？', '把写死的数字改成可调参数'],
};

export default function AlgoStudio({ start, onSaved }: { start: 'ai' | 'upload'; onSaved?: (a: Algorithm) => void }) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [code, setCode] = useState('');
  const [external, setExternal] = useState<{ code: string; nonce: number } | undefined>();
  const [highlight, setHighlight] = useState<Set<number>>(new Set());
  const [lastRun, setLastRun] = useState<TestResult | null>(null);
  const [openTab, setOpenTab] = useState<{ tab: 'out' | 'data'; nonce: number } | undefined>();
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [datasetId, setDatasetId] = useState<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const nextId = useRef(1);

  useEffect(() => {
    api.listDatasets().then((d) => {
      setDatasets(d);
      // One dataset serves both the AI (real column names) and debug runs.
      setDatasetId((cur) => cur ?? d.find((x) => x.kind !== 'derived')?.id ?? null);
    }).catch(() => {});
  }, []);
  useEffect(() => { listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' }); }, [msgs]);

  const push = (m: Omit<Msg, 'id'>) => { const id = nextId.current++; setMsgs((x) => [...x, { ...m, id }]); return id; };
  const patch = (id: number, f: (m: Msg) => Msg) => setMsgs((x) => x.map((m) => (m.id === id ? f(m) : m)));

  function loadCode(c: string) {
    setExternal({ code: c, nonce: Date.now() });
    setHighlight(new Set());
  }

  const runError = lastRun && (!lastRun.validation.ok || lastRun.execution.status !== 'ok')
    ? (lastRun.execution.error || lastRun.validation.errors.join('\n')) : '';

  async function send(text: string, fixError = '', opts: { mode?: 'fix'; silent?: boolean; code?: string } = {}): Promise<string | null> {
    const t = text.trim();
    if (!t || busy) return null;
    let newCode: string | null = null;
    setInput('');
    // The AI sees the conversation so far (its own replies as plain text).
    const history = msgs
      .filter((m) => m.role === 'user' || (m.kind && m.kind !== 'pending' && m.kind !== 'info'))
      .map((m) => ({ role: m.role === 'user' ? 'user' as const : 'assistant' as const, content: m.text }));
    if (!opts.silent) push({ role: 'user', text: t });
    const aid = push({ role: 'ai', text: '', kind: 'pending', stages: [] });
    const before = opts.code ?? code;
    setBusy(true);
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      await streamStudio({
        messages: [...history, { role: 'user', content: t }], code: before,
        dataset_id: datasetId ?? undefined, last_error: fixError, mode: opts.mode,
      }, (ev) => {
        if (ev.kind === 'plan') patch(aid, (m) => ({ ...m, text: ev.reply }));
        else if (ev.kind === 'progress') patch(aid, (m) => ({ ...m, stages: [...(m.stages ?? []), ev] }));
        else if (ev.kind === 'ask') patch(aid, (m) => ({ ...m, kind: 'ask', text: ev.question, options: ev.options }));
        else if (ev.kind === 'answer') patch(aid, (m) => ({ ...m, kind: 'answer', text: ev.reply }));
        else if (ev.kind === 'error') patch(aid, (m) => ({ ...m, kind: 'error', text: ev.message }));
        else if (ev.kind === 'result') {
          const oldLines = new Set(before.split('\n').map((l) => l.trim()));
          const changed = new Set<number>();
          ev.code.split('\n').forEach((l, i) => { if (l.trim() && !oldLines.has(l.trim())) changed.add(i); });
          loadCode(ev.code);
          newCode = ev.code;
          setHighlight(before.trim() ? changed : new Set());
          setLastRun(null);
          const ok = ev.tests.filter((x) => x.status === 'ok').length;
          patch(aid, (m) => ({
            ...m, kind: 'result', prevCode: before,
            text: m.text || (before.trim() ? '已按要求修改代码。' : '已生成代码。'),
            result: {
              name: String(ev.meta?.name ?? ''), passed: ev.all_tests_passed, ok, total: ev.tests.length,
              repairs: Math.max(0, ev.attempts - 1), changed: changed.size,
              reason: (ev.final_error || '').trim().split('\n').pop()?.slice(0, 200) ?? '',
            },
          }));
        }
      }, ac.signal);
    } catch (e) {
      patch(aid, (m) => ({ ...m, kind: 'error', text: (e as Error).name === 'AbortError' ? '已停止。' : (e as Error).message }));
    } finally {
      // A stream that ended without a terminal event (aborted mid-build) shouldn't spin forever.
      patch(aid, (m) => (m.kind === 'pending' ? { ...m, kind: 'error', text: m.text || '没有得到结果，请重试。' } : m));
      setBusy(false);
      abortRef.current = null;
    }
    return newCode;
  }

  /** Step 1 for uploaded code: can it join the platform? A checklist in the
   *  chat; when something required fails and `autoFix`, AI fixes it right away
   *  (stages in the chat, result on the right) and the code is checked again. */
  async function admission(c: string, autoFix: boolean) {
    if (!c.trim()) return;
    const id = push({ role: 'ai', kind: 'check', text: '正在检查能否接入平台…', checking: true });
    let r: { ok: boolean; items: AdmissionItem[] };
    try { r = await api.checkAlgorithm(c); }
    catch (e) { patch(id, (m) => ({ ...m, kind: 'error', checking: false, text: '检查失败：' + (e as Error).message })); return; }
    const failed = r.items.filter((i) => !i.ok && i.level === 'required');
    patch(id, (m) => ({
      ...m, checking: false, items: r.items, checkOk: r.ok, nextStep: r.ok,
      text: r.ok ? '接入检查通过，这段代码可以加入平台。' : `接入检查：有 ${failed.length} 项不符合平台规范${autoFix ? '，我来自动修复。' : '。'}`,
    }));
    if (!r.ok && autoFix) {
      const desc = failed.map((i) => `${i.label}${i.detail ? `（${i.detail}）` : ''}`).join('；');
      const fixed = await send(`按平台接入规范修复：${desc}`, '', { mode: 'fix', silent: true, code: c });
      if (fixed) await admission(fixed, false);
    }
  }

  function fixFailed(items: AdmissionItem[]) {
    const desc = items.filter((i) => !i.ok && i.level === 'required').map((i) => `${i.label}${i.detail ? `（${i.detail}）` : ''}`).join('；');
    send(`按平台接入规范修复：${desc}`, '', { mode: 'fix', silent: true }).then((c) => { if (c) admission(c, false); });
  }

  function undo(m: Msg) {
    if (m.prevCode === undefined) return;
    loadCode(m.prevCode);
    patch(m.id, (x) => ({ ...x, undone: true }));
  }

  function onPickFile(f?: File) {
    if (!f) return;
    const r = new FileReader();
    r.onload = () => {
      const c = String(r.result ?? '');
      loadCode(c);
      push({ role: 'ai', kind: 'info', text: `已把 ${f.name} 载入右侧编辑器。` });
      admission(c, true);
    };
    r.readAsText(f);
  }

  return (
    <div className="h-full flex max-xl:flex-col">
      {/* ── chat ── */}
      <div className="xl:w-[400px] shrink-0 max-xl:h-[46%] flex flex-col border-r border-ink-200 bg-white min-h-0">
        <div className="px-3 py-2 border-b border-ink-200 flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-violet-600 shrink-0" />
          <div className="text-sm font-medium flex-1">{start === 'ai' ? '和 AI 一起写算法' : '上传代码，和 AI 一起改'}</div>
          <button onClick={() => fileRef.current?.click()} className="text-xs px-2 py-1 rounded-lg ring-1 ring-ink-200 text-ink-600 hover:bg-ink-50 flex items-center gap-1">
            <Upload className="w-3.5 h-3.5" /> 上传 .py
          </button>
          <button onClick={() => admission(code, true)} disabled={busy || !code.trim()} title="检查右侧代码能否接入平台，不符合的自动修复"
            className="text-xs px-2 py-1 rounded-lg ring-1 ring-ink-200 text-ink-600 hover:bg-ink-50 flex items-center gap-1 disabled:opacity-40">
            <ShieldCheck className="w-3.5 h-3.5" /> 检查接入
          </button>
          <input ref={fileRef} type="file" accept=".py,.txt,text/x-python,text/plain" className="hidden"
            onChange={(e) => { onPickFile(e.target.files?.[0]); e.target.value = ''; }} />
        </div>
        <div className="px-3 py-1.5 border-b border-ink-100 flex items-center gap-2 text-xs text-ink-500">
          数据集 <span className="text-ink-400">（AI 参考 + 调试运行）</span>
          <select value={datasetId ?? ''} onChange={(e) => setDatasetId(e.target.value ? Number(e.target.value) : null)}
            className="flex-1 min-w-0 border border-ink-200 rounded-md px-1.5 py-0.5 bg-white text-xs">
            <option value="">（不选 —— AI 不知道列名，调试运行时 df 为空）</option>
            {datasets.filter((d) => d.kind !== 'derived').map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </div>

        <div ref={listRef} className="flex-1 min-h-0 overflow-y-auto scroll-hide px-3 py-3 space-y-3">
          {msgs.length === 0 && (
            <div className="text-xs text-ink-500 space-y-2">
              <p>{start === 'ai'
                ? '用一句话描述你想要的算法。不清楚的地方我会先问你；写好后代码出现在右侧，可以继续说怎么改，也可以直接手改。'
                : '点上面的「上传 .py」，或把代码粘贴到右侧后点「检查接入」。我会先检查它能不能加入平台，不符合的地方自动修好；修的过程在这里显示，结果在右侧。'}</p>
              <div className="flex flex-wrap gap-1.5">
                {STARTERS[start].map((s) => (
                  <button key={s} onClick={() => send(s)} className="px-2 py-1 rounded-full ring-1 ring-violet-200 text-violet-700 hover:bg-violet-50">{s}</button>
                ))}
              </div>
            </div>
          )}
          {msgs.map((m) => m.role === 'user' ? (
            <div key={m.id} className="flex gap-2 justify-end">
              <div className="max-w-[85%] bg-brand-600 text-white text-sm rounded-2xl rounded-tr-sm px-3 py-2 whitespace-pre-wrap">{m.text}</div>
              <User className="w-5 h-5 text-ink-400 shrink-0 mt-1" />
            </div>
          ) : (
            <div key={m.id} className="flex gap-2">
              <Bot className="w-5 h-5 text-violet-600 shrink-0 mt-1" />
              <div className={`max-w-[88%] text-sm rounded-2xl rounded-tl-sm px-3 py-2 ring-1 space-y-1.5 ${
                m.kind === 'error' ? 'bg-red-50 ring-red-100 text-red-700' : m.kind === 'info' ? 'bg-ink-50 ring-ink-200 text-ink-600' : 'bg-violet-50/60 ring-violet-100 text-ink-800'}`}>
                {m.text && <div className="whitespace-pre-wrap">{m.text}</div>}
                {m.kind === 'pending' && (
                  <ol className="text-xs space-y-0.5">
                    {(m.stages ?? []).length === 0 && <li className="flex items-center gap-1.5 text-ink-500"><Loader2 className="w-3 h-3 animate-spin" />思考中…</li>}
                    {(m.stages ?? []).map((s, i, all) => {
                      const last = i === all.length - 1;
                      const label = s.stage === 'write' ? ((s.attempt ?? 1) > 1 ? `按问题重写代码（第 ${s.attempt} 次）` : '编写代码')
                        : s.stage === 'test' ? '沙箱自测' : s.stage === 'repair' ? `自测未通过，自动修正${s.reason ? `：${s.reason}` : ''}` : '完成';
                      return (
                        <li key={i} className={`flex items-start gap-1.5 ${s.stage === 'repair' ? 'text-amber-700' : last ? 'text-ink-700' : 'text-ink-400'}`}>
                          {last ? <Loader2 className="w-3 h-3 mt-0.5 animate-spin shrink-0" /> : <span className="w-3 text-center shrink-0">{s.stage === 'repair' ? '↻' : '✓'}</span>}
                          <span className="break-all">{label}</span>
                        </li>
                      );
                    })}
                  </ol>
                )}
                {m.kind === 'check' && (
                  <div className="space-y-1">
                    {m.checking && <div className="flex items-center gap-1.5 text-xs text-ink-500"><Loader2 className="w-3 h-3 animate-spin" />检查语法、入口、META、依赖库…</div>}
                    {(m.items ?? []).map((it) => (
                      <div key={it.key} className="flex items-start gap-1.5 text-xs">
                        {it.ok ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 shrink-0 mt-px" />
                          : it.level === 'required' ? <XCircle className="w-3.5 h-3.5 text-red-500 shrink-0 mt-px" />
                            : <Circle className="w-3.5 h-3.5 text-ink-300 shrink-0 mt-px" />}
                        <div className="min-w-0">
                          <span className={it.ok ? 'text-ink-700' : it.level === 'required' ? 'text-red-700' : 'text-ink-500'}>{it.label}</span>
                          {it.level !== 'required' && !it.ok && <span className="text-ink-400">（{it.level === 'optional' ? '可选' : '建议'}）</span>}
                          {it.detail && !it.ok && <div className="text-ink-500 break-all">{it.detail}</div>}
                        </div>
                      </div>
                    ))}
                    {m.checkOk === false && !busy && m.id === msgs.filter((x) => x.kind === 'check').at(-1)?.id && (
                      <button onClick={() => fixFailed(m.items ?? [])} className="mt-1 text-xs px-2 py-1 rounded-md bg-violet-600 text-white hover:bg-violet-700 inline-flex items-center gap-1">
                        <Wrench className="w-3 h-3" /> 让 AI 修复这些问题
                      </button>
                    )}
                    {m.nextStep && (
                      <div className="mt-1 text-xs text-ink-600 bg-white rounded-lg ring-1 ring-emerald-100 p-2 space-y-1">
                        <div><b>下一步：</b>在右侧「运行设置」里选数据、填参数 → 点「调试运行」验证 → 没问题就「沙箱通过后入库」。</div>
                        <button onClick={() => setOpenTab({ tab: 'data', nonce: Date.now() })} className="inline-flex items-center gap-1 text-violet-700 underline hover:no-underline">
                          <Settings2 className="w-3 h-3" /> 打开运行设置
                        </button>
                      </div>
                    )}
                  </div>
                )}
                {m.kind === 'ask' && (
                  <div className="flex flex-wrap gap-1.5 pt-0.5">
                    {(m.options ?? []).map((o) => (
                      <button key={o} disabled={busy} onClick={() => send(o)}
                        className="text-xs px-2.5 py-1 rounded-full bg-white ring-1 ring-violet-300 text-violet-700 hover:bg-violet-100 disabled:opacity-50">{o}</button>
                    ))}
                    <span className="text-[11px] text-ink-400 self-center">或直接在下面回答</span>
                  </div>
                )}
                {m.kind === 'result' && m.result && (
                  <div className={`text-xs rounded-lg px-2 py-1.5 ${m.result.passed ? 'bg-emerald-50 text-emerald-800' : 'bg-amber-50 text-amber-800'}`}>
                    <div className="flex items-center gap-1">
                      {m.result.passed ? <CheckCircle2 className="w-3.5 h-3.5" /> : <AlertTriangle className="w-3.5 h-3.5" />}
                      {m.result.name && <b>「{m.result.name}」</b>}
                      沙箱自测 {m.result.ok}/{m.result.total} {m.result.passed ? '通过' : '未全通过'}
                      {m.result.repairs > 0 && ` · 自动修复 ${m.result.repairs} 次`}
                    </div>
                    {m.prevCode?.trim() ? <div className="mt-0.5">改动 {m.result.changed} 行，右侧行号绿色标出。</div> : <div className="mt-0.5">代码已放到右侧编辑器。</div>}
                    {!m.result.passed && m.result.reason && <div className="mt-0.5 break-all">原因：{m.result.reason}</div>}
                    {m.prevCode !== undefined && (
                      m.undone
                        ? <div className="mt-1 text-ink-500">已撤销这次修改。</div>
                        : <button onClick={() => undo(m)} className="mt-1 inline-flex items-center gap-1 underline hover:no-underline"><Undo2 className="w-3 h-3" />撤销这次修改</button>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>

        {runError && !busy && (() => {
          const d = lastRun?.diagnosis;
          const tag = d ? ({ param: '参数问题', data: '数据问题', code: '代码问题', rule: '不符合规范', timeout: '运行超时' } as const)[d.category] : '调试运行报错';
          const settingsFix = d && (d.category === 'param' || d.category === 'data');
          return (
            <div className="mx-3 mb-2 text-xs bg-red-50 ring-1 ring-red-100 text-red-700 rounded-lg px-2.5 py-1.5 flex items-start gap-2">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <div className="font-medium">{tag}{d ? `：${d.title.replace(/^.+?问题：/, '')}` : ''}</div>
                <div className="text-red-600/80 break-all line-clamp-2">{d ? d.action : runError.trim().split('\n').pop()}</div>
              </div>
              {settingsFix ? (
                <button onClick={() => setOpenTab({ tab: 'data', nonce: Date.now() })} className="shrink-0 inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-white ring-1 ring-red-200 text-red-700 hover:bg-red-100">
                  <Settings2 className="w-3 h-3" /> 去运行设置
                </button>
              ) : (
                <button onClick={() => send('修复调试运行的报错', runError)} className="shrink-0 inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-red-600 text-white hover:bg-red-700">
                  <Wrench className="w-3 h-3" /> 让 AI 修
                </button>
              )}
            </div>
          );
        })()}
        <div className="border-t border-ink-200 p-2.5 flex gap-2 items-end">
          <textarea value={input} onChange={(e) => setInput(e.target.value)} rows={2}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input); } }}
            placeholder={msgs.length ? '继续说要怎么改…（Enter 发送，Shift+Enter 换行）' : start === 'ai' ? '描述你想要的算法…' : '告诉我要怎么改这段代码…'}
            className="flex-1 resize-none border border-ink-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-violet-400" />
          {busy
            ? <button onClick={() => abortRef.current?.abort()} title="停止" className="p-2.5 rounded-xl bg-ink-200 text-ink-700 hover:bg-ink-300"><Square className="w-4 h-4" /></button>
            : <button onClick={() => send(input)} disabled={!input.trim()} title="发送" className="p-2.5 rounded-xl bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-40"><Send className="w-4 h-4" /></button>}
        </div>
      </div>

      {/* ── live code ── */}
      <div className="flex-1 min-w-0 min-h-0">
        <AlgoEditor
          target={{ mode: 'new', code: '', source: start === 'ai' ? 'ai' : 'user', title: start === 'ai' ? 'AI 共创算法' : '上传的算法' }}
          studio
          externalCode={external}
          onCodeChange={(c) => { setCode(c); }}
          onRunResult={setLastRun}
          datasetId={datasetId}
          onDatasetChange={setDatasetId}
          openTab={openTab}
          highlight={highlight}
          onSaved={(a) => {
            push({ role: 'ai', kind: 'info', text: `已保存到算法库「${a.name}」。可以继续对话修改，之后再保存会成为新版本。` });
            onSaved?.(a);
          }}
        />
      </div>
    </div>
  );
}

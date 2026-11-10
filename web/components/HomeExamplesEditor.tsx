'use client';

// Settings → 主页示例问题 (admins). 改进清单-4 · 第 3 步.
// Tabs and questions can be added, renamed, reordered and hidden; built-in ones
// keep their prepared result card. A new question can take its example result
// from one of the admin's own runs — the server copies what the card needs.

import { Hint } from '@/components/ui';
import { useEffect, useState } from 'react';
import { ArrowDown, ArrowUp, Eye, EyeOff, Loader2, Plus, Trash2, X } from 'lucide-react';
import { api } from '@/lib/api';
import { BUILTIN_RESULTS, DEFAULT_EXAMPLES, snapshotChart, type ExampleKpi, type ExampleQuestion, type ExampleTab } from '@/lib/homeExamples';

const uid = (p: string) => `${p}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 5)}`;
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
function move<T>(arr: T[], i: number, d: -1 | 1): T[] {
  const j = i + d;
  if (j < 0 || j >= arr.length) return arr;
  const a = arr.slice(); [a[i], a[j]] = [a[j], a[i]]; return a;
}

const iconBtn = 'w-7 h-7 grid place-items-center rounded text-ink-500 hover:bg-ink-100 hover:text-ink-900 disabled:opacity-30 disabled:hover:bg-transparent';
const input = 'h-8 px-2 rounded border border-ink-300 text-sm bg-white focus:outline-none focus:border-brand-600 min-w-0';

export default function HomeExamplesEditor() {
  const [tabs, setTabs] = useState<ExampleTab[] | null>(null);
  const [isDefault, setIsDefault] = useState(false);
  const [cur, setCur] = useState(0);
  const [open, setOpen] = useState<string | null>(null);
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [picking, setPicking] = useState<string | null>(null);   // question id choosing a run

  useEffect(() => {
    api.getHomeExamples().then((r) => {
      if (r.tabs) { setTabs(r.tabs); setIsDefault(false); } else { setTabs(clone(DEFAULT_EXAMPLES.tabs)); setIsDefault(true); }
    }).catch((e) => setMsg((e as Error).message));
  }, []);
  if (!tabs) return null;
  const tab = tabs[Math.min(cur, tabs.length - 1)];

  const setTab = (patch: Partial<ExampleTab>) => setTabs(tabs.map((t, i) => (i === cur ? { ...t, ...patch } : t)));
  const setQ = (id: string, patch: Partial<ExampleQuestion>) => setTab({ questions: tab.questions.map((q) => (q.id === id ? { ...q, ...patch } : q)) });

  async function save() {
    setBusy(true); setMsg('');
    try { const r = await api.putHomeExamples(tabs); if (r.tabs) setTabs(r.tabs); setIsDefault(false); setMsg('已保存，用户刷新主页后生效'); }
    catch (e) { setMsg((e as Error).message); }
    finally { setBusy(false); }
  }
  async function restore() {
    if (!confirm('恢复为内置的示例问题？当前的修改会丢失。')) return;
    setBusy(true); setMsg('');
    try { await api.putHomeExamples(null); setTabs(clone(DEFAULT_EXAMPLES.tabs)); setIsDefault(true); setCur(0); setMsg('已恢复默认'); }
    catch (e) { setMsg((e as Error).message); }
    finally { setBusy(false); }
  }

  return (
    <div className="bg-white rounded-md border border-ink-200 p-5 mt-5">
      <div className="flex items-baseline gap-3">
        <h3 className="font-medium">主页示例问题（管理员）</h3>
        {isDefault && <span className="text-xs text-hint">当前为内置默认内容</span>}
      </div>
      <p className="mt-1 text-xs text-ink-600 leading-relaxed">所有用户在主页看到同一套示例问题。内置问题带有预先做好的示例结果；新加的问题可以从你自己的运行记录里选一条作为示例结果。</p>

      {/* tabs */}
      <div className="mt-4 flex flex-wrap items-center gap-1.5">
        {tabs.map((t, i) => (
          <button key={t.id} type="button" onClick={() => { setCur(i); setOpen(null); }}
            className={`h-7 px-2.5 rounded text-[13px] inline-flex items-center gap-1 ${i === cur ? 'bg-brand-50 text-brand-700 ring-1 ring-brand-100' : 'text-ink-700 hover:bg-ink-100'} ${t.hidden ? 'opacity-60' : ''}`}>
            {t.hidden && <EyeOff className="w-3 h-3" />}{t.name || '（未命名）'}
          </button>
        ))}
        <button type="button" disabled={tabs.length >= 8}
          onClick={() => { setTabs([...tabs, { id: uid('t'), name: '新页签', questions: [] }]); setCur(tabs.length); }}
          className="h-7 px-2 rounded text-[13px] text-brand-700 hover:bg-ink-100 inline-flex items-center gap-1 disabled:opacity-40"><Plus className="w-3.5 h-3.5" />页签</button>
      </div>

      {tab && (
        <div className="mt-3 border-t border-ink-150 pt-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-ink-500">页签名称</span>
            <input value={tab.name} maxLength={20} onChange={(e) => setTab({ name: e.target.value })} className={`${input} w-40`} />
            <button type="button" className={iconBtn} title="左移" disabled={cur === 0} onClick={() => { setTabs(move(tabs, cur, -1)); setCur(cur - 1); }}><ArrowUp className="w-3.5 h-3.5 -rotate-90" /></button>
            <button type="button" className={iconBtn} title="右移" disabled={cur === tabs.length - 1} onClick={() => { setTabs(move(tabs, cur, 1)); setCur(cur + 1); }}><ArrowDown className="w-3.5 h-3.5 -rotate-90" /></button>
            <button type="button" className={iconBtn} title={tab.hidden ? '显示' : '隐藏'} onClick={() => setTab({ hidden: !tab.hidden })}>{tab.hidden ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}</button>
            <button type="button" className={`${iconBtn} hover:text-danger-700`} title="删除页签"
              onClick={() => { if (confirm(`删除页签「${tab.name}」及其中的问题？`)) { setTabs(tabs.filter((_, i) => i !== cur)); setCur(Math.max(0, cur - 1)); } }}><Trash2 className="w-3.5 h-3.5" /></button>
          </div>

          <ul className="mt-3 divide-y divide-ink-150 border-y border-ink-150">
            {tab.questions.length === 0 && <li className="py-3 text-xs text-hint">这个页签还没有问题。</li>}
            {tab.questions.map((q, i) => (
              <li key={q.id} className={`py-2 ${q.hidden ? 'opacity-60' : ''}`}>
                <div className="flex items-center gap-1">
                  <input value={q.text} maxLength={120} onChange={(e) => setQ(q.id, { text: e.target.value })} className={`${input} flex-1`} placeholder="问题" />
                  <button type="button" className={iconBtn} title="上移" disabled={i === 0} onClick={() => setTab({ questions: move(tab.questions, i, -1) })}><ArrowUp className="w-3.5 h-3.5" /></button>
                  <button type="button" className={iconBtn} title="下移" disabled={i === tab.questions.length - 1} onClick={() => setTab({ questions: move(tab.questions, i, 1) })}><ArrowDown className="w-3.5 h-3.5" /></button>
                  <button type="button" className={iconBtn} title={q.hidden ? '显示' : '隐藏'} onClick={() => setQ(q.id, { hidden: !q.hidden })}>{q.hidden ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}</button>
                  <button type="button" onClick={() => setOpen(open === q.id ? null : q.id)} className="h-7 px-2 rounded text-xs text-brand-700 hover:bg-ink-100">{open === q.id ? '收起' : '详情'}</button>
                  <button type="button" className={`${iconBtn} hover:text-danger-700`} title="删除" onClick={() => setTab({ questions: tab.questions.filter((x) => x.id !== q.id) })}><Trash2 className="w-3.5 h-3.5" /></button>
                </div>
                {open === q.id && <QuestionDetail q={q} onChange={(p) => setQ(q.id, p)} onPick={() => setPicking(q.id)} />}
              </li>
            ))}
          </ul>
          <button type="button" disabled={tab.questions.length >= 12}
            onClick={() => { const id = uid('q'); setTab({ questions: [...tab.questions, { id, text: '' }] }); setOpen(id); }}
            className="mt-2 h-7 px-2 rounded text-[13px] text-brand-700 hover:bg-ink-100 inline-flex items-center gap-1 disabled:opacity-40"><Plus className="w-3.5 h-3.5" />添加问题</button>
        </div>
      )}

      <div className="mt-4 flex items-center gap-3">
        <button type="button" onClick={save} disabled={busy} className="h-8 px-3 rounded border border-brand-600 bg-brand-600 text-white text-sm hover:bg-brand-700 disabled:opacity-60 inline-flex items-center gap-1.5">
          {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}保存</button>
        <button type="button" onClick={restore} disabled={busy} className="h-8 px-3 rounded border border-ink-300 bg-white text-sm text-ink-800 hover:bg-ink-50">恢复默认</button>
        {msg && <span className="text-xs text-ink-600">{msg}</span>}
      </div>

      {picking && (
        <RunPicker onClose={() => setPicking(null)}
          onPicked={(snap) => { setQ(picking, { snapshot: snap, builtin_key: undefined }); setPicking(null); }} />
      )}
    </div>
  );
}

function QuestionDetail({ q, onChange, onPick }: { q: ExampleQuestion; onChange: (p: Partial<ExampleQuestion>) => void; onPick: () => void }) {
  const builtin = q.builtin_key ? BUILTIN_RESULTS[q.builtin_key] : undefined;
  const kpis = q.kpis ?? [];
  const setKpi = (i: number, p: Partial<ExampleKpi>) => onChange({ kpis: kpis.map((k, j) => (j === i ? { ...k, ...p } : k)) });
  return (
    <div className="mt-2 ml-1 pl-3 border-l-2 border-ink-150 space-y-2.5 text-sm">
      <label className="flex items-center gap-2"><span className="w-20 shrink-0 text-xs text-ink-500">需要的数据</span>
        <input value={q.needs ?? ''} maxLength={120} onChange={(e) => onChange({ needs: e.target.value })} className={`${input} flex-1`} placeholder="未选数据时提示，例如：一组攻角扫描数据" /></label>
      <label className="flex items-center gap-2"><span className="w-20 shrink-0 text-xs text-ink-500">会用到的方法</span>
        <input value={q.methods ?? ''} maxLength={120} onChange={(e) => onChange({ methods: e.target.value })} className={`${input} flex-1`} placeholder="没有示例结果时显示，例如：find_peaks" /></label>
      <div className="flex items-start gap-2">
        <span className="w-20 shrink-0 text-xs text-ink-500 pt-1.5">示例结果</span>
        <div className="flex-1 min-w-0">
          {builtin ? (
            <div className="flex items-center gap-2 text-xs text-ink-600 pt-1.5">内置：{builtin.title}
              <button type="button" onClick={onPick} className="text-brand-700 hover:underline">改用运行记录</button></div>
          ) : q.snapshot ? (
            <div>
              <div className="flex items-center gap-2 text-xs text-ink-600">
                <span className="font-mono text-ink-400">{q.snapshot.code}</span><span className="text-ink-800">{q.snapshot.title}</span>
                <button type="button" onClick={onPick} className="text-brand-700 hover:underline">更换</button>
                <button type="button" onClick={() => onChange({ snapshot: null })} className="text-ink-500 hover:text-danger-700">移除</button>
              </div>
              <div className="mt-1.5 max-w-md rounded border border-ink-150 p-1" dangerouslySetInnerHTML={{ __html: snapshotChart(q.snapshot) }} />
              <div className="mt-2 text-xs text-ink-500">关键数值（0–4 个，显示在图下方）</div>
              {kpis.map((k, i) => (
                <div key={i} className="mt-1 flex items-center gap-1">
                  <input value={k.label} maxLength={40} onChange={(e) => setKpi(i, { label: e.target.value })} className={`${input} w-28`} placeholder="名称" />
                  <input value={k.value} maxLength={40} onChange={(e) => setKpi(i, { value: e.target.value })} className={`${input} w-24 font-mono`} placeholder="数值" />
                  <input value={k.unit ?? ''} maxLength={16} onChange={(e) => setKpi(i, { unit: e.target.value })} className={`${input} w-16`} placeholder="单位" />
                  <input value={k.note ?? ''} maxLength={60} onChange={(e) => setKpi(i, { note: e.target.value })} className={`${input} flex-1`} placeholder="备注" />
                  <button type="button" className={iconBtn} onClick={() => onChange({ kpis: kpis.filter((_, j) => j !== i) })}><X className="w-3.5 h-3.5" /></button>
                </div>
              ))}
              {kpis.length < 4 && <button type="button" onClick={() => onChange({ kpis: [...kpis, { label: '', value: '' }] })} className="mt-1 text-xs text-brand-700 hover:underline">+ 关键数值</button>}
            </div>
          ) : (
            <div className="flex items-center gap-2 text-xs text-ink-600 pt-1.5">无（主页显示文字说明）
              <button type="button" onClick={onPick} className="text-brand-700 hover:underline">从运行记录选择</button></div>
          )}
        </div>
      </div>
    </div>
  );
}

type RunRow = { id: number; code: string; slug: string; label: string; created_at: string | null; rows: number; columns: string[] };

function RunPicker({ onClose, onPicked }: { onClose: () => void; onPicked: (s: import('@/lib/homeExamples').ExampleSnapshot) => void }) {
  const [runs, setRuns] = useState<RunRow[] | null>(null);
  const [run, setRun] = useState<RunRow | null>(null);
  const [x, setX] = useState('');
  const [ys, setYs] = useState<string[]>([]);
  const [title, setTitle] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.homeExampleRuns().then(setRuns).catch((e) => setErr((e as Error).message)); }, []);
  function choose(r: RunRow) { setRun(r); setX(r.columns[0]); setYs(r.columns.slice(1, 2)); setTitle(r.label || r.slug); }
  async function make() {
    if (!run || !x || ys.length === 0) return;
    setBusy(true); setErr('');
    try { onPicked(await api.homeExampleSnapshot(run.id, x, ys, title.trim() || undefined)); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  }
  return (
    <div className="fixed inset-0 z-50 bg-ink-900/30 grid place-items-center p-4" onClick={onClose}>
      <div className="w-full max-w-xl max-h-[80vh] overflow-hidden flex flex-col bg-white rounded-lg shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center px-4 py-3 border-b border-ink-150">
          <span className="font-medium text-sm">选择示例结果</span>
          <span className="ml-2 text-xs text-hint">你自己的、产生了表格的运行记录</span>
          <button type="button" onClick={onClose} className="ml-auto p-1 text-ink-500 hover:text-ink-900"><X className="w-4 h-4" /></button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {!runs && !err && <div className="p-6 text-center text-sm text-ink-500"><Loader2 className="w-4 h-4 animate-spin inline-block" /></div>}
          {runs && runs.length === 0 && <Hint className="p-6">还没有可用的运行记录。先在对话或算法库里跑一次分析。</Hint>}
          <ul className="divide-y divide-ink-150">
            {runs?.map((r) => (
              <li key={r.id}>
                <button type="button" onClick={() => choose(r)} className={`w-full text-left px-4 py-2 flex items-center gap-3 text-sm ${run?.id === r.id ? 'bg-brand-50' : 'hover:bg-ink-50'}`}>
                  <span className="font-mono text-xs text-ink-500 w-20 shrink-0">{r.code}</span>
                  <span className="flex-1 min-w-0 truncate">{r.label || r.slug}</span>
                  <span className="text-xs text-ink-500 shrink-0">{r.rows} 行 · {r.created_at?.slice(5, 16).replace('T', ' ')}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
        {run && (
          <div className="border-t border-ink-150 p-4 space-y-2 text-sm">
            <label className="flex items-center gap-2"><span className="w-14 text-xs text-ink-500">标题</span>
              <input value={title} maxLength={80} onChange={(e) => setTitle(e.target.value)} className={`${input} flex-1`} /></label>
            <label className="flex items-center gap-2"><span className="w-14 text-xs text-ink-500">横轴</span>
              <select value={x} onChange={(e) => { setX(e.target.value); setYs(ys.filter((c) => c !== e.target.value)); }} className={`${input} flex-1`}>
                {run.columns.map((c) => <option key={c} value={c}>{c}</option>)}
              </select></label>
            <div className="flex items-start gap-2"><span className="w-14 text-xs text-ink-500 pt-1">纵轴</span>
              <div className="flex-1 flex flex-wrap gap-x-3 gap-y-1">
                {run.columns.filter((c) => c !== x).map((c) => (
                  <label key={c} className="inline-flex items-center gap-1 text-xs">
                    <input type="checkbox" checked={ys.includes(c)} disabled={!ys.includes(c) && ys.length >= 3}
                      onChange={(e) => setYs(e.target.checked ? [...ys, c] : ys.filter((v) => v !== c))} />{c}
                  </label>
                ))}
              </div></div>
            <div className="flex items-center gap-3 pt-1">
              <button type="button" onClick={make} disabled={busy || ys.length === 0} className="h-8 px-3 rounded bg-brand-600 text-white text-sm hover:bg-brand-700 disabled:opacity-50 inline-flex items-center gap-1.5">
                {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}使用这个结果</button>
              <span className="text-xs text-hint">最多 3 条纵轴；数据会复制一份保存，之后与原记录无关</span>
            </div>
          </div>
        )}
        {err && <div className="px-4 pb-3 text-xs text-danger-700">{err}</div>}
      </div>
    </div>
  );
}

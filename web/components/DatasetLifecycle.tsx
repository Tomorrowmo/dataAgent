'use client';

// Datasets page pieces for 改进清单-3 · 第 3 步: the 「即将清理」 reminder,
// list filters, origin captions, and the 「产生于」 card (re-run / reproduce).
import { useEffect, useState } from 'react';
import { Loader2, RotateCcw, History, ArrowRight, Clock } from 'lucide-react';
import { api, type Dataset, type DatasetProvenance, type RetentionItem } from '@/lib/api';

/** Local-time "MM-DD HH:mm" (the server works in UTC). */
export function fmtLocal(iso?: string | null): string {
  if (!iso) return '';
  const d = new Date(iso.endsWith('Z') || /[+-]\d\d:\d\d$/.test(iso) ? iso : iso + 'Z');
  if (Number.isNaN(d.getTime())) return '';
  const p = (n: number) => String(n).padStart(2, '0');
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function daysLeft(iso?: string | null): number | null {
  if (!iso) return null;
  const d = new Date(iso.endsWith('Z') || /[+-]\d\d:\d\d$/.test(iso) ? iso : iso + 'Z');
  return Number.isNaN(d.getTime()) ? null : (d.getTime() - Date.now()) / 86_400_000;
}

/** "对话「A12 容量衰减」" / "流程「…」" / "算法库" / "上传" */
export function originLabel(d: Dataset): string {
  const o = d.origin;
  if (!o || !o.entry) return d.kind === 'derived' ? '中间结果' : '上传';
  if (o.template && o.entry !== 'chat') return `流程「${o.template.name ?? '已删除'}」`;
  if (o.conversation) return `对话「${o.conversation.title ?? '已删除'}」`;
  if (o.entry === 'library') return '算法库';
  if (o.entry === 'flow') return '流程';
  return '对话';
}

export type DsFilter = {
  range: 'all' | 'today' | '7d' | '30d';
  source: 'all' | 'upload' | 'chat' | 'flow' | 'library';
  algo: string;
  keptOnly: boolean;
  expiring: boolean;
  cleaned: boolean;
};
export const EMPTY_FILTER: DsFilter = { range: 'all', source: 'all', algo: '', keptOnly: false, expiring: false, cleaned: false };
export const filterActive = (f: DsFilter) =>
  f.range !== 'all' || f.source !== 'all' || f.algo.trim() !== '' || f.keptOnly || f.expiring || f.cleaned;

export function matchFilter(d: Dataset, f: DsFilter, noticeDays: number): boolean {
  if (f.range !== 'all' && d.created_at) {
    const age = -(daysLeft(d.created_at) ?? 0);
    const lim = f.range === 'today' ? 1 : f.range === '7d' ? 7 : 30;
    if (age > lim) return false;
  }
  if (f.source !== 'all') {
    const entry = d.kind === 'derived' ? (d.origin?.template && d.origin.entry !== 'chat' ? 'flow' : d.origin?.entry ?? 'chat') : 'upload';
    if (entry !== f.source) return false;
  }
  if (f.algo.trim()) {
    const q = f.algo.trim().toLowerCase();
    const hay = `${d.origin?.algorithm?.label ?? ''} ${d.origin?.algorithm?.slug ?? ''} ${d.lineage?.op?.label ?? ''} ${d.lineage?.op?.slug ?? ''}`.toLowerCase();
    if (!hay.includes(q)) return false;
  }
  if (f.keptOnly && !d.kept) return false;
  if (f.expiring) {
    const left = daysLeft(d.expires_at);
    if (d.kept || d.state === 'cleaned' || left == null || left > noticeDays) return false;
  }
  if (f.cleaned && d.state !== 'cleaned') return false;
  return true;
}

export function DatasetFilters({ f, onChange }: { f: DsFilter; onChange: (f: DsFilter) => void }) {
  const sel = 'h-7 border border-ink-300 rounded px-1.5 bg-white text-xs';
  const chk = (key: 'keptOnly' | 'expiring' | 'cleaned', label: string) => (
    <label className="inline-flex items-center gap-1 text-xs text-ink-700 cursor-pointer">
      <input type="checkbox" checked={f[key]} onChange={(e) => onChange({ ...f, [key]: e.target.checked })} /> {label}
    </label>
  );
  return (
    <div className="px-2 pt-2 space-y-1.5">
      <div className="flex gap-1.5">
        <select aria-label="时间" className={sel} value={f.range} onChange={(e) => onChange({ ...f, range: e.target.value as DsFilter['range'] })}>
          <option value="all">全部时间</option><option value="today">今天</option><option value="7d">近 7 天</option><option value="30d">近 30 天</option>
        </select>
        <select aria-label="来源" className={sel} value={f.source} onChange={(e) => onChange({ ...f, source: e.target.value as DsFilter['source'] })}>
          <option value="all">全部来源</option><option value="upload">上传</option><option value="chat">对话</option><option value="flow">流程</option><option value="library">算法库</option>
        </select>
        <input aria-label="按算法筛选" placeholder="算法" value={f.algo} onChange={(e) => onChange({ ...f, algo: e.target.value })}
          className="h-7 min-w-0 flex-1 border border-ink-300 rounded px-2 bg-white text-xs" />
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1">
        {chk('keptOnly', '只看已保留')}{chk('expiring', '即将清理')}{chk('cleaned', '已清理')}
        {filterActive(f) && <button type="button" onClick={() => onChange(EMPTY_FILTER)} className="text-xs text-brand-700 hover:underline">清除筛选</button>}
      </div>
    </div>
  );
}

/** 「有 N 份中间结果将在 3 天内清理」 — acting on an item records that its
 *  reminder was seen (required before it can be deleted). */
export function RetentionBanner({ refreshKey, onChanged }: { refreshKey: number; onChanged: () => void }) {
  const [items, setItems] = useState<RetentionItem[]>([]);
  const [noticeDays, setNoticeDays] = useState(3);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const load = () => api.retentionList().then((r) => { setItems(r.items); setNoticeDays(r.policy.notice_days); }).catch(() => {});
  useEffect(() => { load(); }, [refreshKey]);
  if (items.length === 0) return null;
  async function act(ids: number[], action: 'keep' | 'extend' | 'clean' | 'ack') {
    if (action === 'clean' && !window.confirm(`立即清理 ${ids.length} 份中间结果的数据？运行记录会保留。`)) return;
    setBusy(true);
    try { await api.retentionAct(ids, action); await load(); onChanged(); } finally { setBusy(false); }
  }
  const all = items.map((i) => i.id);
  const btn = 'h-6 px-2 rounded border border-ink-300 bg-white text-xs text-ink-800 hover:bg-ink-50 disabled:opacity-50';
  return (
    <div className="m-4 mb-0 rounded border border-warning-200 bg-warning-50 text-sm">
      <div className="flex flex-wrap items-center gap-2 px-3 py-2">
        <Clock className="w-4 h-4 text-warning-700" />
        <span className="text-warning-800">有 {items.length} 份中间结果将在 {noticeDays} 天内清理。保留需要的，其余到期后删除数据（运行记录保留）。</span>
        <button type="button" onClick={() => setOpen((v) => !v)} className="ml-auto text-xs text-brand-700 hover:underline">{open ? '收起' : '查看清单'}</button>
      </div>
      {open && (
        <div className="border-t border-warning-200 bg-white">
          <div className="flex flex-wrap gap-1.5 px-3 py-2 border-b border-ink-150">
            <button className={btn} disabled={busy} onClick={() => act(all, 'keep')}>全部保留</button>
            <button className={btn} disabled={busy} onClick={() => act(all, 'extend')}>全部延期 20 天</button>
            <button className={btn} disabled={busy} onClick={() => act(all, 'ack')}>我知道了</button>
            <button className={btn} disabled={busy} onClick={() => act(all, 'clean')}>全部立即清理</button>
            {busy && <Loader2 className="w-4 h-4 animate-spin text-ink-500" />}
          </div>
          <ul className="max-h-64 overflow-y-auto divide-y divide-ink-150">
            {items.map((it) => (
              <li key={it.id} className="flex flex-wrap items-center gap-2 px-3 py-1.5 text-xs">
                <span className="text-ink-900 truncate max-w-[18rem]" title={it.name}>{it.name}</span>
                <span className={`font-mono ${it.days_left <= 0 ? 'text-danger-700' : 'text-warning-700'}`}>
                  {it.days_left <= 0 ? '已到期' : `剩 ${Math.max(0, Math.ceil(it.days_left))} 天`}
                </span>
                {it.acked && <span className="text-ink-500">已确认</span>}
                <span className="ml-auto flex gap-1">
                  <button className={btn} disabled={busy} onClick={() => act([it.id], 'keep')}>保留</button>
                  <button className={btn} disabled={busy} onClick={() => act([it.id], 'extend')}>延期</button>
                  <button className={btn} disabled={busy} onClick={() => act([it.id], 'clean')}>立即清理</button>
                  {!it.acked && <button className={btn} disabled={busy} onClick={() => act([it.id], 'ack')}>知道了</button>}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** 「产生于」: which run made this dataset, jump back to its conversation /
 *  flow, and 重跑 (current version) / 复现 (the version used then). */
export function ProvenanceCard({ ds, onOpenConversation, onOpenTemplate, onNewDataset }: {
  ds: Dataset;
  onOpenConversation?: (id: number) => void;
  onOpenTemplate?: (id: number) => void;
  onNewDataset?: (id: number, message: string) => void;
}) {
  const [p, setP] = useState<DatasetProvenance | null>(null);
  const [busy, setBusy] = useState<'' | 'rerun' | 'reproduce'>('');
  const [msg, setMsg] = useState('');
  useEffect(() => {
    setP(null); setMsg('');
    if (!ds.run_id) return;
    let alive = true;
    api.datasetProvenance(ds.id).then((r) => { if (alive) setP(r); }).catch(() => {});
    return () => { alive = false; };
  }, [ds.id, ds.run_id]);
  if (!ds.run_id || !p?.run) return null;
  const r = p.run, o = p.origin, a = p.actions;
  async function again(kind: 'rerun' | 'reproduce') {
    setBusy(kind); setMsg('');
    try {
      const res = kind === 'rerun' ? await api.datasetRerun(ds.id) : await api.datasetReproduce(ds.id);
      const m = res.status === 'ok'
        ? `${kind === 'rerun' ? '重跑（当前版本）' : '复现（当时的版本）'}完成：${res.code}，下面是新生成的中间结果。${res.warning ? ' ' + res.warning : ''}`
        : `运行失败：${res.error ?? ''}`;
      setMsg(m);
      if (res.dataset_id) onNewDataset?.(res.dataset_id, m);
    } catch (e) { setMsg((e as Error).message); }
    finally { setBusy(''); }
  }
  const entry = o?.entry === 'chat' ? '对话' : o?.entry === 'flow' ? '流程' : '算法库';
  const params = Object.entries(r.params ?? {}).map(([k, v]) => `${k}=${Array.isArray(v) ? v.join(',') : typeof v === 'object' ? JSON.stringify(v) : String(v)}`).join('  ');
  const btn = 'h-7 px-2.5 rounded border border-ink-300 bg-white text-xs text-ink-800 hover:bg-ink-50 disabled:opacity-50 inline-flex items-center gap-1.5';
  return (
    <div className="mb-5 rounded-md border border-ink-200 bg-white overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 px-4 py-2 border-b border-ink-150 bg-ink-50 text-[13px]">
        <span className="font-semibold text-ink-800">产生于</span>
        {o?.code && <span className="font-mono text-xs text-ink-600">{o.code}</span>}
        <span className="text-xs text-ink-500">{entry} · {fmtLocal(r.created_at)}</span>
        {o?.conversation && (o.conversation.exists && onOpenConversation
          ? <button type="button" onClick={() => onOpenConversation(o.conversation!.id!)} className="ml-auto text-xs text-brand-700 hover:underline inline-flex items-center gap-1">回到对话「{o.conversation.title}」<ArrowRight className="w-3 h-3" /></button>
          : <span className="ml-auto text-xs text-ink-500">对话「{o.conversation.title}」</span>)}
        {o?.template && !o.conversation && (o.template.exists && onOpenTemplate
          ? <button type="button" onClick={() => onOpenTemplate(o.template!.id)} className="ml-auto text-xs text-brand-700 hover:underline inline-flex items-center gap-1">打开流程「{o.template.name}」<ArrowRight className="w-3 h-3" /></button>
          : <span className="ml-auto text-xs text-ink-500">流程「{o.template.name}」</span>)}
      </div>
      <div className="px-4 py-2.5 text-xs text-ink-700 space-y-1">
        <div><span className="text-ink-500">算法：</span>{r.label}<span className="font-mono text-ink-500 ml-1.5">{r.slug}{r.version != null ? ` v${r.version}` : r.source === 'builtin' && r.app_version ? ` · 软件 ${r.app_version}` : ''}</span></div>
        {params && <div className="font-mono text-ink-600 break-all"><span className="text-ink-500 font-sans">参数：</span>{params}</div>}
        <div><span className="text-ink-500">输入：</span>{r.input ? `${r.input.name}${r.input.state === 'cleaned' ? '（数据已清理）' : ''}` : '已删除'}</div>
        {ds.state === 'cleaned' && <div className="text-warning-700">这份数据已清理，运行记录保留；可以重跑或复现得到新的结果。</div>}
      </div>
      <div className="px-4 py-2 border-t border-ink-150 flex flex-wrap items-center gap-2">
        <button className={btn} disabled={!!busy || !a?.rerun} onClick={() => again('rerun')} title="用算法当前版本，在同一份输入上重新运行">
          {busy === 'rerun' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RotateCcw className="w-3.5 h-3.5" />} 重跑
        </button>
        <button className={btn} disabled={!!busy || !a?.reproduce} onClick={() => again('reproduce')} title="用当时的算法版本、参数和输入重新计算">
          {busy === 'reproduce' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <History className="w-3.5 h-3.5" />} 复现
        </button>
        {a && !a.rerun && a.rerun_reason && <span className="text-xs text-ink-500">重跑不可用：{a.rerun_reason}</span>}
        {a && !a.reproduce && a.reproduce_reason && a.reproduce_reason !== a.rerun_reason && <span className="text-xs text-ink-500">复现不可用：{a.reproduce_reason}</span>}
        {a?.warning && <span className="text-xs text-warning-700">{a.warning}</span>}
      </div>
      {msg && <div className="px-4 py-2 border-t border-ink-150 text-xs text-ink-700">{msg}</div>}
    </div>
  );
}

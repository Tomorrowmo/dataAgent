'use client';

import { useEffect, useRef, useState } from 'react';
import { Upload, Trash2, Database, Loader2, AlertTriangle, Bookmark, Pin, PinOff, BarChart3, Box, Play, Download, ArrowRight, Clock, MessageSquare, Workflow, Code2, MessageSquareOff, CircleHelp } from 'lucide-react';
import { AiMark, Hint } from '@/components/ui';
import AnalysisIcon from '@/components/AnalysisIcon';
import Markdown from '@/components/Markdown';
import { api, downloadFile, type Dataset, type DatasetProfile, type UploadResp } from '@/lib/api';
import { useT, useLangStore } from '@/lib/i18n';
import { buildPrompt, type RecipeId } from '@/lib/recipes';
import ParserModal from '@/components/ParserModal';
import DatasetChart from '@/components/DatasetChart';
import DataTable from '@/components/DataTable';
import { ProvenanceCard, RetentionBanner, daysLeft, fmtLocal } from '@/components/DatasetLifecycle';
import { Overview, Entries, EntryTile, Section, Rows, Row, Counts, ListHead, BackBar } from '@/components/LibraryOverview';
import { useAlgoLookup } from '@/lib/useAlgoNames';
import { SAMPLES } from '@/lib/homeExamples';
import dynamic from 'next/dynamic';
// three / @react-three are browser-only (reference window/self) — client-only load.
const MeshViewer3D = dynamic(() => import('@/components/MeshViewer3D'), { ssr: false });

// 数据页 (改进清单-6 · 3): left list split into 源数据 / 中间结果, right side an
// overview until a dataset is picked, then its detail in four tabs
// (预览 · 字段 · 来源 · 用在哪些分析).

type NeedsParser = NonNullable<UploadResp['needs_parser']>;
type Tab = 'source' | 'derived';
type Status = 'all' | 'expiring' | 'kept' | 'cleaned';

const NOTICE_DAYS = 3;
const WIND = '示例·风洞攻角扫描';
export const isDerivedDs = (d: Dataset) => d.kind === 'derived' || d.derived_from != null;
const expiring = (d: Dataset) => { const l = daysLeft(d.expires_at); return !d.kept && d.state !== 'cleaned' && l != null && l <= NOTICE_DAYS; };
const statusOf = (d: Dataset): Status | null => d.state === 'cleaned' ? 'cleaned' : d.kept ? 'kept' : expiring(d) ? 'expiring' : null;

/** The analysis a derived dataset came from — the grouping key of the 中间结果 list. */
function analysisOf(d: Dataset): { key: string; title: string; convId: number | null; tplId: number | null } {
  const o = d.origin;
  if (o?.conversation) {
    // A deleted conversation has no id any more — keep its runs apart by run group (R-0002…).
    if (o.conversation.exists === false || o.conversation.id == null) {
      const grp = (o.code ?? '').split('.')[0];
      return { key: 'gone' + grp, title: `（已删除的对话）${grp ? ' · ' + grp : ''}`, convId: null, tplId: null };
    }
    return { key: 'c' + o.conversation.id, title: o.conversation.title ?? '对话', convId: o.conversation.id, tplId: null };
  }
  if (o?.template) return { key: 't' + o.template.id, title: `流程「${o.template.name ?? '已删除'}」`, convId: null, tplId: o.template.exists ? o.template.id : null };
  if (o?.entry === 'library') return { key: 'lib', title: '算法库里直接运行', convId: null, tplId: null };
  return { key: 'other', title: '其他（没有运行记录）', convId: null, tplId: null };
}

/** Walk derived_from up to the source dataset. */
function rootOf(d: Dataset, byId: Map<number, Dataset>): Dataset {
  let cur = d; const seen = new Set<number>();
  while (cur.derived_from != null && byId.has(cur.derived_from) && !seen.has(cur.id)) { seen.add(cur.id); cur = byId.get(cur.derived_from)!; }
  return cur;
}

export default function DatasetsView({ onAsk, onUseInChat, onGoSettings, focusDataset, onBackToChat, onActiveDataset, onDatasetsChanged, onOpenConversation, onOpenTemplate }: { onAsk?: (prompt: string, datasetId: number) => void; onUseInChat?: (datasetId: number) => void; onGoSettings?: () => void; focusDataset?: { id: number; nonce: number } | null; onBackToChat?: () => void; onActiveDataset?: (id: number | null) => void; onDatasetsChanged?: () => void; onOpenConversation?: (id: number) => void; onOpenTemplate?: (id: number) => void }) {
  const [retentionKey, setRetentionKey] = useState(0);
  const [flash, setFlash] = useState<{ id: number; text: string } | null>(null);
  const t = useT();
  const algoName = useAlgoLookup();
  // True after arriving here via "查看完整表格" from a conversation → show a 返回 link.
  const [cameFromChat, setCameFromChat] = useState(false);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [selected, setSelected] = useState<Dataset | null>(null);
  const [tab, setTab] = useState<Tab>('source');
  const [status, setStatus] = useState<Status>('all');
  const [q, setQ] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{ done: number; total: number } | null>(null);
  const [error, setError] = useState('');
  // Files whose format isn't natively known queue up here; the parser modal
  // processes them one at a time (a batch with 3 unknown-format files asks 3×).
  const [parserQueue, setParserQueue] = useState<NeedsParser[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const pendingParser = parserQueue[0] ?? null;
  const shiftQueue = () => setParserQueue((q) => q.slice(1));

  async function refresh() {
    try {
      const d = await api.listDatasets();
      setDatasets(d);
      if (selected) setSelected(d.find((x) => x.id === selected.id) ?? null);
      // Every mutation here ends in a refresh — tell the parent from one place so
      // the chat view's dataset picker stays in sync.
      onDatasetsChanged?.();
      return d;
    } catch (e) {
      setError((e as Error).message);
      return [];
    }
  }
  useEffect(() => { refresh(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  /** Open a dataset: the list switches to its tab so the row is visible. */
  const open = (d: Dataset | null) => { setSelected(d); if (d) setTab(isDerivedDs(d) ? 'derived' : 'source'); };

  // Arrived via "查看完整表格" from a conversation → open that dataset.
  const lastFocusRef = useRef<number | null>(null);
  useEffect(() => {
    if (!focusDataset || lastFocusRef.current === focusDataset.nonce) return;
    const d = datasets.find((x) => x.id === focusDataset.id);
    if (d) { open(d); setCameFromChat(true); lastFocusRef.current = focusDataset.nonce; }
  }, [focusDataset, datasets]); // eslint-disable-line react-hooks/exhaustive-deps

  // Report the open dataset up (feedback notes record WHICH dataset).
  useEffect(() => { onActiveDataset?.(selected?.id ?? null); }, [selected, onActiveDataset]);

  // Upload a batch sequentially. Natively-parseable files ingest straight away;
  // unknown formats queue for the generate-parser modal. Failures are reported together.
  async function handleUploadMany(files: File[]) {
    if (files.length === 0) return;
    setError('');
    setUploading(true);
    setUploadProgress({ done: 0, total: files.length });
    const queue: NeedsParser[] = [];
    const failures: string[] = [];
    let lastOk: Dataset | null = null;
    for (let i = 0; i < files.length; i++) {
      try {
        const r = await api.uploadDataset(files[i]);
        if (r.status === 'needs_parser' && r.needs_parser) queue.push(r.needs_parser);
        else if (r.status === 'ok' && r.dataset) lastOk = r.dataset;
      } catch (e) {
        failures.push(`${files[i].name}：${(e as Error).message}`);
      }
      setUploadProgress({ done: i + 1, total: files.length });
    }
    setUploading(false);
    setUploadProgress(null);
    await refresh();
    if (lastOk) open(lastOk);
    if (failures.length) setError(`${failures.length} 个文件上传失败：\n` + failures.join('\n'));
    if (queue.length) setParserQueue(queue);
  }

  async function onParserIngested(ds: Dataset) {
    await refresh();
    open(ds);
    shiftQueue();
  }

  function onFilesPicked(list: FileList | null | undefined) {
    if (list && list.length) handleUploadMany(Array.from(list));
  }

  async function openWindSample() {
    setError('');
    let ds = datasets.find((d) => d.name === WIND);
    if (!ds) {
      try {
        const r = await api.uploadDataset(new File([SAMPLES[WIND]()], `${WIND}.csv`, { type: 'text/csv' }));
        ds = r.dataset ?? r.datasets?.[0];
        await refresh();
      } catch (e) { setError((e as Error).message); return; }
    }
    if (ds) open(ds);
  }

  async function handleDelete(id: number) {
    try {
      // Ask the server what the delete would take out BEFORE destroying anything —
      // a source dataset drags its whole 中间结果 subtree with it.
      const preview = await api.deleteDataset(id, true);
      if (preview.descendants > 0) {
        const mb = (preview.freed_bytes / 1024 / 1024).toFixed(1);
        const keptWarn = preview.kept_hit > 0 ? `\n其中 ${preview.kept_hit} 份是你「保留」过的。` : '';
        const names = preview.deleted.slice(1, 6).map((d) => `  · ${d.name}`).join('\n');
        const more = preview.descendants > 5 ? `\n  … 另有 ${preview.descendants - 5} 份` : '';
        if (!confirm(
          `删除「${preview.deleted[0].name}」会连同它衍生出的 ${preview.descendants} 份中间结果一起删除，` +
          `共 ${preview.count} 份，释放约 ${mb} MB。${keptWarn}\n\n${names}${more}\n\n此操作不可撤销。继续？`,
        )) return;
      } else if (!confirm(t('ds.confirmDelete'))) {
        return;
      }
      const res = await api.deleteDataset(id);
      const goneIds = new Set(res.deleted.map((d) => d.id));
      if (selected && goneIds.has(selected.id)) setSelected(null);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handlePromote(id: number) {
    try { await api.promoteDataset(id); await refresh(); }
    catch (e) { setError((e as Error).message); }
  }

  async function handleKeep(id: number, kept: boolean) {
    try { await api.keepDataset(id, kept); await refresh(); setRetentionKey((k) => k + 1); }
    catch (e) { setError((e as Error).message); }
  }

  const [gcing, setGcing] = useState(false);
  async function handleGc() {
    setError('');
    setGcing(true);
    try {
      const preview = await api.gcDatasets(true);
      if (preview.count === 0) { setError('没有可清理的中间结果（已保留的、正在使用的、以及它们的上游都会保留）。'); return; }
      if (!confirm(`立即清理 ${preview.count} 份未保留的中间结果的数据？\n运行记录和血缘会保留，之后可以重跑或复现。\n（已保留的、源数据、正在用于分析的不受影响。）`)) return;
      await api.gcDatasets(false);
      await refresh();
      setRetentionKey((k) => k + 1);
    } catch (e) { setError((e as Error).message); }
    finally { setGcing(false); }
  }

  // ── list data ──
  const byId = new Map(datasets.map((d) => [d.id, d]));
  const sources = datasets.filter((d) => !isDerivedDs(d));
  const derived = datasets.filter(isDerivedDs);
  const resultsOf = new Map<number, number>();
  for (const d of derived) { const r = rootOf(d, byId); if (r.id !== d.id) resultsOf.set(r.id, (resultsOf.get(r.id) ?? 0) + 1); }
  const count = (s: Status) => derived.filter((d) => statusOf(d) === s).length;
  const kw = q.trim().toLowerCase();
  const algoOf = (d: Dataset) => algoName(d.origin?.algorithm?.slug || d.lineage?.op?.slug || d.lineage?.op?.label || d.name).name;
  const hay = (d: Dataset) => `${d.name} ${d.origin?.code ?? ''} ${algoOf(d)} ${(d.schema.columns ?? []).map((c) => c.name).join(' ')}`.toLowerCase();
  const shownSources = sources.filter((d) => !kw || hay(d).includes(kw)).sort((a, b) => b.id - a.id);
  const shownDerived = derived.filter((d) => (!kw || hay(d).includes(kw)) && (status === 'all' || statusOf(d) === status));
  const groups: { key: string; title: string; items: Dataset[] }[] = [];
  for (const d of [...shownDerived].sort((a, b) => b.id - a.id)) {
    const a = analysisOf(d);
    let g = groups.find((x) => x.key === a.key);
    if (!g) { g = { key: a.key, title: a.title, items: [] }; groups.push(g); }
    g.items.push(d);
  }
  for (const g of groups) g.items.sort((a, b) => (a.origin?.code ?? '').localeCompare(b.origin?.code ?? '', undefined, { numeric: true }) || a.id - b.id);

  const switchTab = (k: Tab) => { setTab(k); setStatus('all'); };
  const jumpStatus = (s: Status) => { setSelected(null); setTab('derived'); setStatus(s); };

  return (
    <div className="flex h-full"
      onDragOver={(e) => { if (e.dataTransfer.types.includes('Files')) { e.preventDefault(); if (!dragOver) setDragOver(true); } }}
      onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragOver(false); }}
      onDrop={(e) => { e.preventDefault(); setDragOver(false); onFilesPicked(e.dataTransfer.files); }}>
      {pendingParser && (
        <ParserModal pending={pendingParser} onClose={shiftQueue} onIngested={onParserIngested} onGoSettings={onGoSettings} />
      )}
      <input ref={inputRef} type="file" multiple className="hidden"
        onChange={(e) => { onFilesPicked(e.target.files); e.target.value = ''; }} />

      {/* ── left list ── */}
      <div className={`w-full md:w-[300px] shrink-0 border-r flex flex-col bg-white transition-colors ${selected ? 'max-md:hidden' : ''} ${dragOver ? 'border-brand-400 bg-brand-50' : 'border-ink-200'}`}>
        <ListHead title="数据" q={q} onQ={setQ} placeholder="搜索名称、列名、运行编号"
          extra={<button onClick={() => inputRef.current?.click()} disabled={uploading}
            className="h-7 px-2 rounded-md ring-1 ring-ink-300 text-xs text-ink-700 hover:bg-ink-50 inline-flex items-center gap-1 disabled:opacity-60">
            {uploading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
            {uploading ? (uploadProgress ? `${uploadProgress.done}/${uploadProgress.total}` : '上传中') : '导入'}
          </button>} />
        <div className="px-3.5 pt-2.5 pb-2 border-b border-ink-150">
          <div className="grid grid-cols-2 p-0.5 rounded-md bg-ink-100">
            {([['source', '源数据', sources.length], ['derived', '中间结果', derived.length]] as const).map(([k, label, n]) => (
              <button key={k} onClick={() => switchTab(k)}
                className={`h-7 rounded text-[12.5px] ${tab === k ? 'bg-white text-ink-900 font-medium shadow-sm' : 'text-ink-600 hover:text-ink-900'}`}>
                {label}<span className="ml-1 font-mono text-[11px] text-ink-400">{n}</span>
              </button>
            ))}
          </div>
          {tab === 'derived' && (
            <div className="flex flex-wrap gap-1 mt-2">
              {([['all', '全部'], ['expiring', '即将清理'], ['kept', '已保留'], ['cleaned', '已清理']] as const).map(([k, label]) => (
                <button key={k} onClick={() => setStatus(k)}
                  className={`h-[22px] px-2 rounded-full text-[11.5px] ${status === k ? 'bg-ink-900 text-white' : 'text-ink-600 ring-1 ring-inset ring-ink-200 hover:bg-ink-50'}`}>
                  {label}{k !== 'all' && <span className="ml-1 font-mono">{count(k)}</span>}
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="flex-1 overflow-y-auto scroll-hide p-2">
          {tab === 'source' ? (
            <>
              {shownSources.length === 0 && <Hint center className="mt-6 px-3">{kw ? '没有匹配的源数据' : t('ds.empty')}</Hint>}
              <div className="space-y-0.5">
                {shownSources.map((d) => (
                  <ListRow key={d.id} sel={selected?.id === d.id} onClick={() => open(d)} onDelete={() => handleDelete(d.id)}>
                    <Database className="w-3.5 h-3.5 text-ink-500 shrink-0" strokeWidth={1.6} />
                    <span className="flex-1 min-w-0 truncate text-[13px] text-ink-800">{d.name}</span>
                    <span className="font-mono text-[11px] text-ink-500 shrink-0">{d.rows.toLocaleString()}×{d.columns}</span>
                    {(resultsOf.get(d.id) ?? 0) > 0 && <span className="text-[10.5px] px-1.5 rounded-sm bg-ink-100 text-ink-500 shrink-0">{resultsOf.get(d.id)} 份结果</span>}
                  </ListRow>
                ))}
              </div>
            </>
          ) : (
            <>
              {groups.length === 0 && <Hint center className="mt-6 px-3">{kw || status !== 'all' ? '没有符合条件的中间结果' : '还没有中间结果。对话或流程里每运行一步，结果会出现在这里。'}</Hint>}
              {groups.map((g) => (
                <div key={g.key} className="mb-2">
                  {/* group = one analysis: a sticky band with the source type's icon */}
                  {(() => {
                    const k = g.key.startsWith('gone') ? 'gone' : g.key[0] === 'c' ? 'chat' : g.key[0] === 't' ? 'flow' : g.key === 'lib' ? 'lib' : 'other';
                    const Icon = { chat: MessageSquare, gone: MessageSquareOff, flow: Workflow, lib: Code2, other: CircleHelp }[k];
                    const dim = k === 'gone' || k === 'other';
                    // Line 1: what kind of analysis + its name (a chat is titled by its first question).
                    const label = { chat: '对话', gone: '对话', flow: '流程', lib: '算法库', other: '其他' }[k];
                    const name = k === 'flow' ? g.title.replace(/^流程「|」$/g, '')
                      : k === 'gone' ? `已删除${g.title.includes('·') ? ' · ' + g.title.split('·').pop()!.trim() : ''}`
                      : k === 'lib' ? '直接运行' : k === 'other' ? '没有运行记录' : g.title;
                    // Line 2: which source data it worked on, and how many results.
                    const srcs = [...new Set(g.items.map((d) => rootOf(d, byId)).filter((r) => !isDerivedDs(r)).map((r) => r.name))];
                    const unit = k === 'chat' || k === 'gone' || k === 'flow' ? '步' : '份';
                    const full = `${label}：${name}
源数据：${srcs.join('、') || '—'}
${g.items.length} ${unit}结果`;
                    return (
                      <div title={full} className="sticky top-0 z-[1] px-2 py-1.5 rounded bg-ink-100">
                        <div className={`flex items-center gap-1.5 text-[12px] ${dim ? 'text-ink-400' : 'text-ink-800'}`}>
                          <Icon className="w-3.5 h-3.5 shrink-0" strokeWidth={1.75} />
                          <span className={`shrink-0 text-[11px] px-1 rounded-sm ${dim ? 'bg-ink-150 text-ink-400' : 'bg-white text-ink-600 ring-1 ring-ink-200'}`}>{label}</span>
                          <span className={`truncate ${dim ? '' : 'font-medium'}`}>{name}</span>
                        </div>
                        <div className="mt-0.5 pl-5 flex gap-1.5 text-[11px] text-ink-500">
                          <span className="truncate">{srcs.length ? srcs.join('、') : '源数据已删除'}</span>
                          <span className="ml-auto shrink-0 font-mono text-ink-400">{g.items.length} {unit}</span>
                        </div>
                      </div>
                    );
                  })()}
                  <div className="ml-[15px] mt-1 pl-1.5 border-l border-ink-200 space-y-0.5">
                    {g.items.map((d) => {
                      const st = statusOf(d);
                      const left = daysLeft(d.expires_at);
                      return (
                        <ListRow key={d.id} sel={selected?.id === d.id} onClick={() => open(d)} onDelete={() => handleDelete(d.id)}
                          onKeep={() => handleKeep(d.id, !d.kept)} kept={!!d.kept} dim={st === 'cleaned'}>
                          <span className="font-mono text-[11px] text-ink-400 w-[52px] shrink-0">{(d.origin?.code ?? '').replace(/^R-/, '') || '—'}</span>
                          <span className="flex-1 min-w-0 truncate text-[13px]" title={d.name}>{algoOf(d)}</span>
                          <span className="font-mono text-[11px] text-ink-500 shrink-0">{d.rows.toLocaleString()}×{d.columns}</span>
                          {st === 'expiring' && <span className="text-[10.5px] px-1.5 rounded-sm bg-warning-50 text-warning-700 shrink-0">{left != null && left <= 0 ? '已到期' : `${Math.ceil(left ?? 0)}天`}</span>}
                          {st === 'kept' && <span className="text-[10.5px] px-1.5 rounded-sm bg-success-50 text-success-700 shrink-0">已保留</span>}
                          {st === 'cleaned' && <span className="text-[10.5px] px-1.5 rounded-sm bg-ink-100 text-ink-500 shrink-0">已清理</span>}
                        </ListRow>
                      );
                    })}
                  </div>
                </div>
              ))}
            </>
          )}
        </div>
      </div>

      {/* ── right: overview / detail ── */}
      <div className={`flex-1 min-w-0 flex flex-col ${selected ? '' : 'max-md:hidden'}`}>
        {cameFromChat && onBackToChat && (
          <button onClick={onBackToChat}
            className="shrink-0 w-full text-left px-4 py-2 bg-brand-50 border-b border-brand-100 text-sm text-brand-700 font-medium hover:bg-brand-100">
            ← 返回对话
          </button>
        )}
        {selected && <BackBar onBack={() => setSelected(null)}>
          <span className="text-xs text-ink-500 truncate">{isDerivedDs(selected) ? '中间结果' : '源数据'} / {isDerivedDs(selected) ? `${selected.origin?.code ? selected.origin.code + ' ' : ''}${algoOf(selected)}` : selected.name}</span>
        </BackBar>}
        <div className="flex-1 min-h-0 overflow-y-auto scroll-hide">
          {error && (
            <div className="mx-6 mt-4 px-3 py-2 rounded bg-danger-50 text-danger-700 text-sm flex items-start gap-2 whitespace-pre-line">
              <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" /> <span className="flex-1">{error}</span>
              <button onClick={() => setError('')} className="text-xs hover:underline shrink-0">关闭</button>
            </div>
          )}
          {flash && selected?.id === flash.id && (
            <div className="mx-6 mt-4 rounded border border-success-200 bg-success-50 px-3 py-2 text-xs text-success-800 flex items-center gap-2">
              {flash.text}
              <button type="button" onClick={() => setFlash(null)} className="ml-auto text-success-700 hover:underline">知道了</button>
            </div>
          )}
          {selected ? (
            <DatasetDetail key={selected.id} ds={selected} t={t} datasets={datasets} algoOf={algoOf}
              onPromote={() => handlePromote(selected.id)} onKeep={(k) => handleKeep(selected.id, k)} onDelete={() => handleDelete(selected.id)}
              onOpen={open} onSubsetSaved={(d) => { refresh(); open(d); }} onAsk={onAsk} onUseInChat={onUseInChat}
              onOpenConversation={onOpenConversation} onOpenTemplate={onOpenTemplate}
              onNewDataset={async (id, m) => { const all = await refresh(); const d = all.find((x) => x.id === id); if (d) { open(d); setFlash({ id, text: m }); } }} />
          ) : (
            <Overview title="数据"
              lead="源数据是你导入的文件，长期保存；中间结果是分析中每一步的输出，带运行编号，默认保留 20 天。左侧切换两类，选中一份查看内容、字段和来源。">
              <div className={`rounded-lg transition ${dragOver ? 'ring-2 ring-brand-600 ring-offset-4 ring-offset-ink-50' : ''}`}>
                <Entries>
                  <EntryTile primary icon={<Upload className="w-4 h-4" strokeWidth={1.75} />} title={uploading ? `正在导入${uploadProgress ? ` ${uploadProgress.done}/${uploadProgress.total}` : '…'}` : '导入数据'}
                    desc="表格文件、Tecplot 导出、CGNS / VTK 仿真结果和表格截图都能直接导入；可以一次选多个，或把文件夹拖进来"
                    onClick={() => inputRef.current?.click()} disabled={uploading} />
                  <EntryTile icon={<Play className="w-4 h-4" strokeWidth={1.75} />} title="打开风洞示例数据"
                    desc="一份攻角扫描数据（攻角、升力系数、阻力系数），可以直接拿来提问试用" onClick={openWindSample} />
                </Entries>
              </div>
              <Hint className="mt-2">其他格式会先生成读取程序，确认后保存，之后同类文件直接使用。单个文件最大 200 MiB。</Hint>

              {tab === 'derived' ? (
                <>
                  <RetentionBanner refreshKey={retentionKey} onChanged={() => refresh()} className="mt-5" />
                  {groups.length > 0 && (
                    <Section title="按分析看" note="中间结果按产生它的对话分组">
                      <Rows>
                        {groups.map((g) => {
                          const a = analysisOf(g.items[0]);
                          const from = rootOf(g.items[0], byId);
                          return (
                            <Row key={g.key} name={g.title} meta={`${from.id !== g.items[0].id ? `来自 ${from.name} · ` : ''}${g.items.length} 份`}
                              action={a.convId != null && onOpenConversation ? '回到对话' : a.tplId != null && onOpenTemplate ? '打开流程' : undefined}
                              onAction={() => { if (a.convId != null) onOpenConversation?.(a.convId); else if (a.tplId != null) onOpenTemplate?.(a.tplId); }} />
                          );
                        })}
                      </Rows>
                    </Section>
                  )}
                  <section className="mt-7">
                    <div className="flex items-center gap-2">
                      <h2 className="text-sm font-semibold text-ink-900">保留规则</h2>
                      <button onClick={handleGc} disabled={gcing || derived.length === 0}
                        className="ml-auto h-7 px-2.5 rounded-md bg-white ring-1 ring-ink-300 text-[12.5px] text-ink-800 hover:bg-ink-50 disabled:opacity-50 inline-flex items-center gap-1.5">
                        {gcing && <Loader2 className="w-3.5 h-3.5 animate-spin" />}清理中间结果
                      </button>
                    </div>
                    <div className="mt-2 px-3.5 py-3 rounded-lg bg-white ring-1 ring-ink-150 text-[13px] leading-relaxed text-ink-700">
                      中间结果从产生起保留 20 天；点过「保留」或「升为正式数据集」的不会清理。清理只删数据文件，运行编号、算法和参数都留着，需要时可以重跑。
                      <Hint inline className="ml-2">保留天数可以在设置里改（管理员）</Hint>
                    </div>
                  </section>
                </>
              ) : (
                shownSources.length > 0 && (
                  <Section title="最近导入">
                    <Rows>
                      {[...sources].sort((a, b) => b.id - a.id).slice(0, 5).map((d) => (
                        <div key={d.id} className="flex items-center gap-2.5 px-3.5 py-2.5 text-[13px] min-w-0">
                          <button onClick={() => open(d)} className="font-medium text-ink-900 truncate hover:text-brand-700">{d.name}</button>
                          <span className="font-mono text-xs text-ink-500 shrink-0">{d.rows.toLocaleString()}×{d.columns}</span>
                          <span className="ml-auto text-xs text-ink-500 shrink-0 max-sm:hidden">{fmtLocal(d.created_at).slice(0, 5)} 导入{(resultsOf.get(d.id) ?? 0) > 0 ? ` · ${resultsOf.get(d.id)} 份中间结果` : ''}</span>
                          {onUseInChat && <button onClick={() => onUseInChat(d.id)}
                            className="shrink-0 h-7 px-2.5 rounded-md bg-white ring-1 ring-ink-300 text-[12.5px] text-ink-800 hover:bg-ink-50">在对话中分析</button>}
                        </div>
                      ))}
                    </Rows>
                  </Section>
                )
              )}

              <Counts items={[
                { label: '源数据', n: sources.length, onClick: () => switchTab('source') },
                { label: '中间结果', n: derived.length, onClick: () => switchTab('derived') },
                { label: '即将清理', n: count('expiring'), onClick: () => jumpStatus('expiring') },
                { label: '已保留', n: count('kept'), onClick: () => jumpStatus('kept') },
                { label: '已清理', n: count('cleaned'), onClick: () => jumpStatus('cleaned') },
              ]} />
            </Overview>
          )}
        </div>
      </div>
    </div>
  );
}

/** One row of the left list, with hover actions (保留 for 中间结果, 删除). */
function ListRow({ sel, onClick, onDelete, onKeep, kept, dim, children }: {
  sel: boolean; onClick: () => void; onDelete: () => void; onKeep?: () => void; kept?: boolean; dim?: boolean; children: React.ReactNode;
}) {
  return (
    <div className={`group flex items-center rounded transition-colors ${sel ? 'bg-brand-50' : 'hover:bg-ink-50'}`}>
      <button onClick={onClick} className={`flex-1 min-w-0 flex items-center gap-2 px-2 py-1.5 text-left ${dim ? 'text-ink-400' : 'text-ink-800'}`}>{children}</button>
      <span className="hidden group-hover:flex items-center gap-1 pr-1.5 shrink-0">
        {onKeep && (
          <button onClick={onKeep} title={kept ? '取消保留（到期后可被清理）' : '保留（不被自动清理）'} className="p-0.5 text-ink-400 hover:text-ink-800">
            {kept ? <PinOff className="w-3.5 h-3.5" /> : <Pin className="w-3.5 h-3.5" />}
          </button>
        )}
        <button onClick={onDelete} title="删除" className="p-0.5 text-ink-400 hover:text-danger-600"><Trash2 className="w-3.5 h-3.5" /></button>
      </span>
    </div>
  );
}

// A suggestion slug → its chip label (zh/en); icon via AnalysisIcon. Slugs come from the
// backend profile; recipe slugs also exist in lib/recipes (→ chat prompt).
const SUGG_META: Record<string, { zh: string; en: string }> = {
  chart:    { zh: '可视化', en: 'Visualize' },
  mesh3d:   { zh: '3D 网格', en: '3D mesh' },
  smooth:   { zh: '平滑降噪', en: 'Smooth' },
  drivers:  { zh: '找主因', en: 'Key drivers' },
  fit:      { zh: '拟合关系', en: 'Fit a relation' },
  outliers: { zh: '找异常点', en: 'Outliers' },
  corr:     { zh: '相关性', en: 'Correlations' },
  pca:      { zh: '降维看结构', en: 'Reduce dims' },
  clean:    { zh: '清洗数据', en: 'Clean' },
  explain:  { zh: '解释', en: 'Explain' },
};
const RECIPE_SLUGS = new Set<string>(['smooth', 'drivers', 'fit', 'outliers', 'corr', 'pca']);

type DetailTab = 'preview' | 'fields' | 'origin' | 'used';

function DatasetDetail({ ds, t, datasets, algoOf, onPromote, onKeep, onDelete, onOpen, onSubsetSaved, onAsk, onUseInChat, onOpenConversation, onOpenTemplate, onNewDataset }: {
  ds: Dataset; t: (k: string) => string; datasets: Dataset[]; algoOf: (d: Dataset) => string;
  onPromote: () => void; onKeep: (kept: boolean) => void; onDelete: () => void; onOpen: (d: Dataset) => void;
  onSubsetSaved?: (d: Dataset) => void; onAsk?: (prompt: string, datasetId: number) => void; onUseInChat?: (datasetId: number) => void;
  onOpenConversation?: (id: number) => void; onOpenTemplate?: (id: number) => void; onNewDataset?: (id: number, message: string) => void;
}) {
  const cols = ds.schema.columns ?? [];
  const lang = useLangStore((s) => s.lang);
  const isDerived = isDerivedDs(ds);
  const cleaned = ds.state === 'cleaned';
  const [tab, setTab] = useState<DetailTab>(cleaned ? 'origin' : 'preview');
  const [showChart, setShowChart] = useState(false);
  const [showMesh, setShowMesh] = useState(false);
  const [explaining, setExplaining] = useState(false);
  const [explanation, setExplanation] = useState('');
  // Instant deterministic first-read (free; auto-loaded per dataset).
  const [profile, setProfile] = useState<DatasetProfile | null>(null);
  useEffect(() => {
    let alive = true;
    if (!cleaned) api.profileDataset(ds.id).then((p) => { if (alive) setProfile(p); }).catch(() => {});
    return () => { alive = false; };
  }, [ds.id, cleaned]);
  async function explain() {
    setTab('preview'); setExplaining(true); setExplanation('');
    try { const r = await api.explainDataset(ds.id); setExplanation(r.explanation || '（没有得到解释）'); }
    catch (e) { setExplanation('（解释失败：' + (e as Error).message + '）'); }
    finally { setExplaining(false); }
  }
  // Suggestion chips: in-view actions run here; analysis recipes go to chat as a question.
  function onSuggest(slug: string) {
    if (slug === 'chart') { setShowChart(true); return; }
    if (slug === 'mesh3d') { setShowMesh(true); return; }
    if (slug === 'explain') { explain(); return; }
    if (slug === 'clean') {
      onAsk?.(
        lang === 'zh'
          ? `帮我清洗这份数据「${ds.name}」：处理缺失值、去掉明显异常的点，整理成一张干净的表，并说明你做了哪些处理。`
          : `Clean this dataset "${ds.name}": handle missing values, drop obvious bad points, produce a tidy table, and tell me what you changed.`,
        ds.id,
      );
      return;
    }
    if (RECIPE_SLUGS.has(slug)) {
      const prompt = buildPrompt(slug as RecipeId, ds, lang);
      if (prompt) onAsk?.(prompt, ds.id);
    }
  }
  const isMesh = ['x', 'y', 'z'].every((a) => cols.some((c) => c.name.toLowerCase() === a));

  // Lineage: walk derived_from up to the source.
  const byId = new Map(datasets.map((d) => [d.id, d]));
  const chain: Dataset[] = [];
  { let cur: Dataset | undefined = ds; const seen = new Set<number>();
    while (cur && !seen.has(cur.id)) { seen.add(cur.id); chain.unshift(cur); cur = cur.derived_from != null ? byId.get(cur.derived_from) : undefined; } }

  // 用在哪些分析: the analyses that produced results from this dataset (its
  // descendants, plus — for a 中间结果 — the analysis that produced it).
  const descendants: Dataset[] = [];
  { const stack = [ds.id]; const seen = new Set<number>([ds.id]);
    while (stack.length) { const id = stack.pop()!; for (const d of datasets) if (d.derived_from === id && !seen.has(d.id)) { seen.add(d.id); descendants.push(d); stack.push(d.id); } } }
  const used = new Map<string, { title: string; convId: number | null; tplId: number | null; n: number }>();
  for (const d of isDerived ? [ds, ...descendants] : descendants) {
    const a = analysisOf(d);
    const u = used.get(a.key) ?? { title: a.title, convId: a.convId, tplId: a.tplId, n: 0 };
    u.n += 1; used.set(a.key, u);
  }

  const left = daysLeft(ds.expires_at);
  const btn = 'inline-flex items-center gap-1.5 text-[13px] h-8 px-3 rounded border border-ink-300 bg-white text-ink-800 hover:bg-ink-50 disabled:opacity-50';
  const primary = 'inline-flex items-center gap-1.5 text-[13px] h-8 px-3 rounded bg-brand-600 text-white hover:bg-brand-700';
  const title = isDerived ? algoOf(ds) : ds.name;
  const tabs: [DetailTab, string, number?][] = [
    ['preview', '预览'], ['fields', '字段', cols.length], ['origin', isDerived ? '来源与血缘' : '来源'], ['used', '用在哪些分析', used.size],
  ];

  return (
    <div className="max-w-[1100px] mx-auto px-6 md:px-10 pt-6 pb-12">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-semibold text-ink-900 truncate" title={ds.name}>{title}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-ink-500">
            <span className="px-1.5 py-px rounded-sm bg-ink-100 text-ink-600">{isDerived ? '中间结果' : '源数据'}</span>
            {isDerived && ds.origin?.code && <span className="font-mono">{ds.origin.code}</span>}
            <span className="font-mono">{ds.rows.toLocaleString()} 行 × {ds.columns} 列</span>
            <span>· {fmtLocal(ds.created_at)} {isDerived ? '产生' : '导入'}</span>
            {!isDerived && ds.filename && <span className="font-mono">· {ds.filename}</span>}
            {isDerived && !cleaned && !ds.kept && left != null && (
              <span className={`px-1.5 py-px rounded-sm ${left <= NOTICE_DAYS ? 'bg-warning-50 text-warning-700' : 'bg-ink-100 text-ink-600'}`}>{left <= 0 ? '已到期' : `${Math.ceil(left)} 天后清理`}</span>
            )}
            {isDerived && ds.kept && <span className="px-1.5 py-px rounded-sm bg-success-50 text-success-700">已保留</span>}
            {cleaned && <span className="px-1.5 py-px rounded-sm bg-ink-100 text-ink-600">数据已清理</span>}
          </div>
        </div>
        <div className="shrink-0 flex flex-wrap items-center gap-2">
          {!cleaned && <>
            <button onClick={explain} disabled={explaining} className={btn}>{explaining ? <Loader2 className="w-4 h-4 animate-spin" /> : <AiMark />} 解释</button>
            {isMesh && <button onClick={() => { setTab('preview'); setShowMesh((v) => !v); }} className={btn}><Box className="w-4 h-4" /> {showMesh ? '收起 3D' : '3D 网格'}</button>}
            <button onClick={() => { setTab('preview'); setShowChart((v) => !v); }} className={btn}><BarChart3 className="w-4 h-4" /> {showChart ? '收起图表' : '可视化'}</button>
            <button onClick={() => downloadFile(`/datasets/${ds.id}/export?format=csv`, `${ds.name}.csv`)} className={btn} title="导出为 CSV"><Download className="w-4 h-4" /> 导出</button>
          </>}
          {isDerived ? <>
            <button onClick={() => onKeep(!ds.kept)} className={btn} title={ds.kept ? '取消保留后，到期可被自动清理' : '保留，不被自动清理'}>
              {ds.kept ? <PinOff className="w-4 h-4" /> : <Pin className="w-4 h-4" />} {ds.kept ? '取消保留' : '保留'}
            </button>
            {!cleaned && <button onClick={onPromote} className={primary}><Bookmark className="w-4 h-4" /> 升为正式数据集</button>}
          </> : (
            onUseInChat && <button onClick={() => onUseInChat(ds.id)} className={primary}><MessageSquare className="w-4 h-4" /> 在对话中分析</button>
          )}
          <button onClick={onDelete} title="删除" className="h-8 w-8 grid place-items-center rounded border border-ink-300 bg-white text-ink-500 hover:text-danger-600 hover:border-danger-300"><Trash2 className="w-4 h-4" /></button>
        </div>
      </div>

      <div className="mt-5 flex gap-5 border-b border-ink-200 overflow-x-auto">
        {tabs.map(([k, label, n]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`py-2 -mb-px border-b-2 text-[13px] whitespace-nowrap ${tab === k ? 'border-brand-600 text-ink-900 font-medium' : 'border-transparent text-ink-500 hover:text-ink-800'}`}>
            {label}{n != null && <span className="ml-1 font-mono text-[11px] text-ink-400">{n}</span>}
          </button>
        ))}
      </div>

      {tab === 'preview' && (cleaned ? (
        <div className="mt-4 rounded-md border border-ink-200 bg-ink-50 px-4 py-6 text-sm text-ink-600 text-center">
          这份中间结果的数据已于 {fmtLocal(ds.cleaned_at ?? null) || '之前'} 清理，名称和血缘仍保留。
          {ds.run_id ? '需要时可以在「来源与血缘」里重跑或复现。' : '它产生于升级之前，没有运行记录，无法自动重跑；可以回到原对话或流程重新运行。'}
        </div>
      ) : <div className="mt-4 space-y-4">
        {profile && (
          <div className="rounded-md bg-white border border-ink-200 p-4">
            <div className="flex items-center gap-2 text-ink-800 font-semibold text-[13px] mb-1.5">
              {lang === 'zh' ? '数据概况' : 'Data profile'}<span className="text-xs font-normal text-ink-500">{lang === 'zh' ? '自动生成' : 'auto-generated'}</span>
            </div>
            <p className="text-sm text-ink-900 leading-relaxed">{profile.headline}</p>
            {profile.facts.length > 0 && (
              <div className="mt-2.5 flex flex-wrap gap-2">
                {profile.facts.map((f, i) => <span key={i} className="inline-flex items-center text-xs text-ink-700 bg-ink-50 border border-ink-200 rounded-sm px-2 py-0.5">{f}</span>)}
              </div>
            )}
            {profile.semantic && profile.semantic.length > 0 && (
              <div className="mt-3 rounded border border-ink-200 bg-ink-50 px-3 py-2">
                <div className="text-xs text-ink-600 font-medium mb-1.5">{lang === 'zh' ? '已套用专家规则（列含义）' : 'Applied expert rules (column meanings)'}</div>
                <div className="flex flex-wrap gap-2">
                  {profile.semantic.map((m) => (
                    <span key={m.rule_id + m.column} className="inline-flex items-center gap-1 text-xs text-ink-800 bg-white border border-ink-200 rounded-sm px-2 py-0.5">
                      <code className="font-mono text-ink-900">{m.column}</code><span className="text-ink-400">→</span><span className="font-medium">{m.label}</span>
                    </span>
                  ))}
                </div>
              </div>
            )}
            {profile.suggestions.length > 0 && (
              <div className="mt-3.5 pt-3 border-t border-ink-100">
                <div className="text-xs text-ink-500 mb-2">{lang === 'zh' ? '可以这样做' : 'You could'}</div>
                <div className="flex flex-wrap gap-2">
                  {profile.suggestions.map((s) => {
                    const m = SUGG_META[s.slug];
                    return (
                      <button key={s.slug} onClick={() => onSuggest(s.slug)} title={s.why}
                        className="inline-flex items-center gap-1.5 text-xs h-7 px-2.5 rounded border border-ink-300 bg-white text-ink-800 hover:border-brand-400 hover:bg-brand-50 hover:text-brand-700 transition-colors">
                        <span className="text-ink-500"><AnalysisIcon id={s.slug} className="w-3.5 h-3.5" /></span>{m ? (lang === 'zh' ? m.zh : m.en) : s.slug}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        )}
        {(explaining || explanation) && (
          <div className="rounded-md bg-white border border-dashed border-ink-500 p-4 text-sm text-ink-700">
            <div className="flex items-center gap-1.5 text-ink-800 font-medium mb-1.5"><AiMark /> 解释 <span className="text-xs font-normal text-ink-500">AI 生成，仅供参考</span></div>
            {explaining ? <div className="text-ink-400 flex items-center gap-1.5"><Loader2 className="w-3.5 h-3.5 animate-spin" /> 正在解读…</div>
              : <div className="prose-tight leading-relaxed"><Markdown>{explanation}</Markdown></div>}
          </div>
        )}
        {showMesh && isMesh && <div className="bg-white rounded-md border border-ink-200 p-4"><MeshViewer3D datasetId={ds.id} name={ds.name} /></div>}
        {showChart && <div className="bg-white rounded-md border border-ink-200 p-4"><DatasetChart datasetId={ds.id} name={ds.name} /></div>}
        <div className="bg-white rounded-md border border-ink-200 p-5">
          <h3 className="text-[13px] font-semibold text-ink-800 mb-3">数据表 · 排序 / 筛选 / 选择另存</h3>
          <DataTable ds={ds} onSaved={onSubsetSaved} />
        </div>
      </div>)}

      {tab === 'fields' && (
        <div className="mt-4 bg-white rounded-md border border-ink-200 p-5">
          <table className="w-full text-sm">
            <thead className="text-ink-500 text-xs">
              <tr className="border-b border-ink-200"><th className="text-left py-2 font-medium">{t('ds.column')}</th><th className="text-left font-medium">{t('ds.dtype')}</th><th className="text-right font-medium">{t('ds.unique')}</th><th className="text-right font-medium">{t('ds.missing')}</th></tr>
            </thead>
            <tbody>
              {cols.map((c) => (
                <tr key={c.name} className="border-b border-ink-100">
                  <td className="py-1.5 font-mono">{c.name}</td>
                  <td className="text-ink-700">{c.dtype}</td>
                  <td className="text-right text-ink-700">{c.n_unique?.toLocaleString()}</td>
                  <td className="text-right text-ink-700">{c.n_missing?.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'origin' && (
        <div className="mt-4 space-y-4">
          {isDerived ? <>
            <ProvenanceCard ds={ds} onOpenConversation={onOpenConversation} onOpenTemplate={onOpenTemplate} onNewDataset={onNewDataset} />
            {!ds.run_id && <Hint>这份中间结果产生于运行记录功能之前，没有记录算法版本和参数，不能重跑或复现。</Hint>}
            <div className="rounded-md bg-white border border-ink-200 p-4">
              <div className="flex items-baseline gap-2 mb-2.5"><h3 className="text-[13px] font-semibold text-ink-800">血缘</h3><span className="text-xs text-ink-500">从源数据到这一份</span></div>
              <div className="flex flex-wrap items-center gap-1.5">
                {chain.map((c, i) => (
                  <span key={c.id} className="inline-flex items-center gap-1.5">
                    {i > 0 && <ArrowRight className="w-3.5 h-3.5 text-ink-300" />}
                    <button onClick={() => c.id !== ds.id && onOpen(c)} disabled={c.id === ds.id}
                      className={`text-left px-2.5 py-1 rounded text-[12.5px] ring-1 ${c.id === ds.id ? 'ring-brand-600 bg-brand-50' : 'ring-ink-200 bg-white hover:ring-ink-400'}`}>
                      {isDerivedDs(c) ? algoOf(c) : c.name}
                      <span className="block font-mono text-[10.5px] text-ink-400">{isDerivedDs(c) ? c.origin?.code ?? '中间结果' : '源数据'}</span>
                    </button>
                  </span>
                ))}
              </div>
              {chain.length > 1 && <Hint className="mt-2">点任一节点打开那一份数据。</Hint>}
            </div>
            <div className="rounded-md bg-white border border-ink-200 p-4">
              <h3 className="text-[13px] font-semibold text-ink-800 mb-1.5 flex items-center gap-1.5"><Clock className="w-3.5 h-3.5 text-ink-500" />保留</h3>
              <p className="text-[13px] text-ink-700 leading-relaxed">
                {cleaned ? `数据已于 ${fmtLocal(ds.cleaned_at ?? null) || '之前'} 清理，运行记录保留。`
                  : ds.kept ? '已保留，自动清理不会删除它。'
                    : `从产生起保留 20 天${ds.expires_at ? `，${fmtLocal(ds.expires_at).slice(0, 5)} 到期` : ''}。点「保留」后不再清理；「升为正式数据集」会把它放进源数据，长期保存。`}
              </p>
            </div>
          </> : (
            <div className="rounded-md bg-white border border-ink-200 p-4">
              <dl className="grid grid-cols-[88px_1fr] gap-x-3 gap-y-1.5 text-[13px]">
                <dt className="text-ink-500">文件名</dt><dd className="font-mono text-xs text-ink-800 break-all">{ds.filename || '—'}</dd>
                <dt className="text-ink-500">格式</dt><dd className="text-ink-800">{ds.file_format || '—'}</dd>
                <dt className="text-ink-500">大小</dt><dd className="text-ink-800">{ds.size_bytes ? `${(ds.size_bytes / 1024).toFixed(1)} KB` : '—'}</dd>
                <dt className="text-ink-500">导入时间</dt><dd className="text-ink-800">{fmtLocal(ds.created_at) || '—'}</dd>
                {ds.description && <><dt className="text-ink-500">说明</dt><dd className="text-ink-800">{ds.description}</dd></>}
              </dl>
              <Hint className="mt-3">源数据长期保存，不会被自动清理。</Hint>
            </div>
          )}
        </div>
      )}

      {tab === 'used' && (
        <div className="mt-4">
          {used.size === 0 ? (
            <Hint>还没有分析用这份数据产生过结果。{!isDerived && onUseInChat ? '点右上角「在对话中分析」开始。' : ''}</Hint>
          ) : (
            <>
              <Rows>
                {[...used.entries()].map(([k, u]) => (
                  <Row key={k} name={u.title} meta={`${u.n} 份中间结果`}
                    action={u.convId != null && onOpenConversation ? '回到对话' : u.tplId != null && onOpenTemplate ? '打开流程' : undefined}
                    onAction={() => { if (u.convId != null) onOpenConversation?.(u.convId); else if (u.tplId != null) onOpenTemplate?.(u.tplId); }} />
                ))}
              </Rows>
              <Hint className="mt-2">按这份数据产生的中间结果反推；只用来提问、没有产生结果的对话不会列出。</Hint>
            </>
          )}
        </div>
      )}
    </div>
  );
}

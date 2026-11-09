'use client';

import { useEffect, useRef, useState } from 'react';
import { Upload, Trash2, Database, Loader2, AlertTriangle, GitBranch, Bookmark, ChevronRight, Pin, PinOff, Recycle, BarChart3, Box } from 'lucide-react';
import { AiMark, SourceTag } from '@/components/ui';
import AnalysisIcon from '@/components/AnalysisIcon';
import type { ReactNode } from 'react';
import Markdown from '@/components/Markdown';
import { api, type Dataset, type DatasetProfile, type UploadResp } from '@/lib/api';
import { useT, useLangStore } from '@/lib/i18n';
import { buildPrompt, type RecipeId } from '@/lib/recipes';
import ParserModal from '@/components/ParserModal';
import DatasetChart from '@/components/DatasetChart';
import DataTable from '@/components/DataTable';
import { DatasetFilters, EMPTY_FILTER, ProvenanceCard, RetentionBanner, daysLeft, filterActive, fmtLocal, matchFilter, originLabel, type DsFilter } from '@/components/DatasetLifecycle';
import dynamic from 'next/dynamic';
// three / @react-three are browser-only (reference window/self) — client-only load.
const MeshViewer3D = dynamic(() => import('@/components/MeshViewer3D'), { ssr: false });

type NeedsParser = NonNullable<UploadResp['needs_parser']>;

export default function DatasetsView({ onAsk, onGoSettings, focusDataset, onBackToChat, onActiveDataset, onDatasetsChanged, onOpenConversation, onOpenTemplate }: { onAsk?: (prompt: string, datasetId: number) => void; onGoSettings?: () => void; focusDataset?: { id: number; nonce: number } | null; onBackToChat?: () => void; onActiveDataset?: (id: number | null) => void; onDatasetsChanged?: () => void; onOpenConversation?: (id: number) => void; onOpenTemplate?: (id: number) => void }) {
  const [filter, setFilter] = useState<DsFilter>(EMPTY_FILTER);
  const [retentionKey, setRetentionKey] = useState(0);
  const [flash, setFlash] = useState<{ id: number; text: string } | null>(null);
  const t = useT();
  // True after arriving here via "查看完整表格" from a conversation → show a 返回 link.
  const [cameFromChat, setCameFromChat] = useState(false);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [selected, setSelected] = useState<Dataset | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{ done: number; total: number } | null>(null);
  const [error, setError] = useState('');
  // Files whose format isn't natively known queue up here; the parser modal
  // processes them one at a time. pendingParser is always the head of the queue,
  // so a batch drop that includes 3 unknown-format files asks for a parser 3×.
  const [parserQueue, setParserQueue] = useState<NeedsParser[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const pendingParser = parserQueue[0] ?? null;
  const shiftQueue = () => setParserQueue((q) => q.slice(1));

  async function refresh() {
    try {
      const d = await api.listDatasets();
      setDatasets(d);
      if (selected) {
        const fresh = d.find((x) => x.id === selected.id);
        setSelected(fresh ?? null);
      }
      // Every mutation here (upload / delete / promote / keep / GC) ends in a
      // refresh, so telling the parent from this one place keeps the chat view's
      // dataset picker in sync without wiring each handler separately.
      onDatasetsChanged?.();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  // Arrived via "查看完整表格" from a conversation → select that dataset (once the
  // list is loaded) and flag it so the "← 返回对话" link shows.
  const lastFocusRef = useRef<number | null>(null);
  useEffect(() => {
    if (!focusDataset || lastFocusRef.current === focusDataset.nonce) return;
    const d = datasets.find((x) => x.id === focusDataset.id);
    if (d) { setSelected(d); setCameFromChat(true); lastFocusRef.current = focusDataset.nonce; }
  }, [focusDataset, datasets]);

  // Report the currently-open dataset up so a feedback note dropped on this view
  // records WHICH dataset, enabling "回到现场" to land on it exactly.
  useEffect(() => { onActiveDataset?.(selected?.id ?? null); }, [selected, onActiveDataset]);

  // Auto-select the newest dataset on first load so entering this page shows a
  // real preview + data table on the right immediately, instead of an empty
  // "请选择数据集" placeholder. One-shot (a ref guard) so it never fights the
  // user re-deselecting (e.g. tapping ← 返回 on a narrow screen).
  const autoSelectedRef = useRef(false);
  useEffect(() => {
    if (!autoSelectedRef.current && !selected && datasets.length > 0) {
      setSelected(datasets[0]);
      autoSelectedRef.current = true;
    }
  }, [datasets, selected]);

  // Upload a batch of files sequentially (one dropped folder / multi-select).
  // Natively-parseable files ingest straight away; unknown formats accumulate in
  // parserQueue and get the generate-parser modal one after another. Per-file
  // failures are collected and reported together — nothing is dropped silently.
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
        if (r.status === 'needs_parser' && r.needs_parser) {
          queue.push(r.needs_parser);
        } else if (r.status === 'ok' && r.dataset) {
          lastOk = r.dataset;
        }
      } catch (e) {
        failures.push(`${files[i].name}：${(e as Error).message}`);
      }
      setUploadProgress({ done: i + 1, total: files.length });
    }
    setUploading(false);
    setUploadProgress(null);
    await refresh();
    if (lastOk) setSelected(lastOk);
    if (failures.length) setError(`${failures.length} 个文件上传失败：\n` + failures.join('\n'));
    if (queue.length) setParserQueue(queue);
  }

  async function onParserIngested(ds: Dataset) {
    await refresh();
    setSelected(ds);
    shiftQueue(); // advance to the next unknown-format file, if any
  }

  function onFilesPicked(list: FileList | null | undefined) {
    if (list && list.length) handleUploadMany(Array.from(list));
  }
  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    onFilesPicked(e.dataTransfer.files);
  }

  async function handleDelete(id: number) {
    try {
      // Ask the server what the delete would take out BEFORE destroying anything —
      // a source dataset drags its whole 中间结果 subtree with it.
      const preview = await api.deleteDataset(id, true);
      if (preview.descendants > 0) {
        const mb = (preview.freed_bytes / 1024 / 1024).toFixed(1);
        const keptWarn = preview.kept_hit > 0
          ? `\n其中 ${preview.kept_hit} 份是你「保留」过的。`
          : '';
        const names = preview.deleted.slice(1, 6).map((d) => `  · ${d.name}`).join('\n');
        const more = preview.descendants > 5 ? `\n  … 另有 ${preview.descendants - 5} 份` : '';
        if (!confirm(
          `删除「${preview.deleted[0].name}」会连同它衍生出的 ${preview.descendants} 份中间结果一起删除,` +
          `共 ${preview.count} 份,释放约 ${mb} MB。${keptWarn}\n\n${names}${more}\n\n此操作不可撤销。继续?`,
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
    try { await api.keepDataset(id, kept); await refresh(); }
    catch (e) { setError((e as Error).message); }
  }

  const [gcing, setGcing] = useState(false);
  async function handleGc() {
    setError('');
    setGcing(true);
    try {
      const preview = await api.gcDatasets(true);
      if (preview.count === 0) { setError('没有可清理的中间结果（已保留的、正在使用的、以及它们的上游都会保留）。'); return; }
      if (!confirm(`立即清理 ${preview.count} 份未保留的中间结果的数据？\n运行记录和血缘会保留，之后可以重跑或复现。\n（已保留的、原始数据、正在用于分析的不受影响。）`)) return;
      await api.gcDatasets(false);
      await refresh();
      setRetentionKey((k) => k + 1);
    } catch (e) { setError((e as Error).message); }
    finally { setGcing(false); }
  }

  const derivedCount = datasets.filter((d) => (d.kind === 'derived' || d.derived_from != null) && !d.kept && d.state !== 'cleaned').length;

  return (
    <div className="flex h-full">
      {pendingParser && (
        <ParserModal
          pending={pendingParser}
          onClose={shiftQueue}
          onIngested={onParserIngested}
          onGoSettings={onGoSettings}
        />
      )}
      <div
        className={`w-full md:w-80 border-r flex flex-col transition-colors ${selected ? 'max-md:hidden' : ''} ${dragOver ? 'border-brand-400 bg-brand-50' : 'border-ink-200 bg-ink-50'}`}
        onDragOver={(e) => { e.preventDefault(); if (!dragOver) setDragOver(true); }}
        onDragLeave={(e) => { if (e.currentTarget === e.target) setDragOver(false); }}
        onDrop={onDrop}
      >
        <div className="p-4 border-b border-ink-200">
          <button
            onClick={() => inputRef.current?.click()}
            className="w-full flex items-center justify-center gap-2 bg-brand-600 text-white px-3 py-2 rounded-lg hover:bg-brand-700 font-medium disabled:opacity-60"
            disabled={uploading}
          >
            {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
            {uploading
              ? (uploadProgress ? `上传中 ${uploadProgress.done}/${uploadProgress.total}…` : t('ds.uploading'))
              : t('ds.upload')}
          </button>
          <input
            ref={inputRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => { onFilesPicked(e.target.files); e.target.value = ''; }}
          />
          <div className="text-xs text-ink-500 mt-2">{t('ds.uploadHint')}<span className="text-ink-400"> · 可一次选多个,或把多个文件 / 文件夹拖到这里</span></div>
          {derivedCount > 0 && (
            <button
              onClick={handleGc}
              disabled={gcing}
              title="清理未保留、且非近期 / 非在用的中间结果数据集"
              className="mt-2 w-full flex items-center justify-center gap-1.5 text-xs px-3 py-1.5 rounded-lg ring-1 ring-ink-200 text-ink-600 hover:bg-ink-50 disabled:opacity-50"
            >
              {gcing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Recycle className="w-3.5 h-3.5" />}
              清理中间结果（{derivedCount}）
            </button>
          )}
        </div>
        <DatasetFilters f={filter} onChange={setFilter} />
        <div className="flex-1 overflow-y-auto scroll-hide p-2">
          {datasets.length === 0 && <div className="text-sm text-ink-500 text-center mt-8 px-4">{t('ds.empty')}</div>}
          <DatasetTree datasets={datasets} selectedId={selected?.id ?? null}
            onSelect={setSelected} onDelete={handleDelete} onKeep={handleKeep} filter={filter} />
        </div>
      </div>

      <div className={`flex-1 overflow-y-auto scroll-hide ${selected ? '' : 'max-md:hidden'}`}>
        {cameFromChat && onBackToChat && (
          <button onClick={onBackToChat}
            className="sticky top-0 z-10 w-full text-left px-4 py-2.5 bg-brand-50 border-b border-brand-100 text-sm text-brand-700 font-medium hover:bg-brand-100">
            ← 返回对话
          </button>
        )}
        {selected && (
          <button onClick={() => setSelected(null)}
            className="md:hidden sticky top-0 z-10 w-full text-left px-4 py-2.5 bg-white border-b border-ink-200 text-sm text-brand-600 font-medium">
            ← 返回数据集列表
          </button>
        )}
        {error && (
          <div className="m-5 px-3 py-2 rounded-lg bg-red-50 text-red-700 text-sm flex items-center gap-2">
            <AlertTriangle className="w-4 h-4" /> {error}
          </div>
        )}
        <RetentionBanner refreshKey={retentionKey} onChanged={() => refresh()} />
        {!selected && <div className="grid place-items-center h-full text-ink-500">{t('ds.select')}</div>}
        {flash && selected?.id === flash.id && (
          <div className="mx-6 mt-4 rounded border border-success-200 bg-success-50 px-3 py-2 text-xs text-success-800 flex items-center gap-2">
            {flash.text}
            <button type="button" onClick={() => setFlash(null)} className="ml-auto text-success-700 hover:underline">知道了</button>
          </div>
        )}
        {selected && <DatasetPreview ds={selected} t={t} datasets={datasets} onPromote={() => handlePromote(selected.id)} onKeep={(k) => handleKeep(selected.id, k)} onSubsetSaved={(d) => { refresh(); setSelected(d); }} onAsk={onAsk}
          onOpenConversation={onOpenConversation} onOpenTemplate={onOpenTemplate}
          onNewDataset={async (id, m) => { await refresh(); const d = (await api.listDatasets()).find((x) => x.id === id); if (d) { setSelected(d); setFlash({ id, text: m }); } }} />}
      </div>
    </div>
  );
}

/** Lineage tree: source datasets are roots; each derived dataset nests under
 *  the step that produced it (原始 → 去噪 → 检测 → …), collapsible. This is the
 *  methodology made visible — datasets are a DAG, not a flat list. */
function DatasetTree({ datasets: all, selectedId, onSelect, onDelete, onKeep, filter }: {
  datasets: Dataset[]; selectedId: number | null; onSelect: (d: Dataset) => void; onDelete: (id: number) => void; onKeep: (id: number, kept: boolean) => void;
  filter: DsFilter;
}) {
  const [expandedState, setExpanded] = useState<Set<number>>(() => new Set());
  // Filtering keeps the lineage tree: a match is shown with its ancestors.
  const active = filterActive(filter);
  const allById = new Map(all.map((d) => [d.id, d]));
  const visible = new Set<number>();
  if (active) {
    for (const d of all) {
      if (!matchFilter(d, filter, 3)) continue;
      let cur: Dataset | undefined = d; let guard = 0;
      while (cur && !visible.has(cur.id) && guard++ < 1000) { visible.add(cur.id); cur = cur.derived_from != null ? allById.get(cur.derived_from) : undefined; }
    }
  }
  const datasets = active ? all.filter((d) => visible.has(d.id)) : all;
  const expanded = active ? new Set(datasets.map((d) => d.id)) : expandedState;
  const byId = new Map(datasets.map((d) => [d.id, d]));
  const childrenOf = (id: number) => datasets.filter((d) => d.derived_from === id).sort((a, b) => a.id - b.id);
  const roots = datasets.filter((d) => d.derived_from == null || !byId.has(d.derived_from)).sort((a, b) => b.id - a.id);
  const toggle = (id: number) => setExpanded((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  const renderNode = (d: Dataset, depth: number): ReactNode => {
    const kids = childrenOf(d.id);
    const open = expanded.has(d.id);
    const isDerived = d.kind === 'derived' || d.derived_from != null;
    const label = isDerived ? (d.lineage?.op?.label || d.name) : d.name;
    return (
      <div key={d.id}>
        <div
          className={`group flex items-center gap-1 rounded pr-1 ${selectedId === d.id ? 'bg-white ring-1 ring-ink-200' : 'hover:bg-ink-150'}`}
          style={{ paddingLeft: 4 + depth * 14 }}
        >
          {kids.length > 0 ? (
            <button onClick={() => toggle(d.id)} className="p-0.5 text-ink-400 hover:text-ink-700 shrink-0">
              <ChevronRight className={`w-3.5 h-3.5 transition-transform ${open ? 'rotate-90' : ''}`} />
            </button>
          ) : <span className="w-4 shrink-0" />}
          <button onClick={() => onSelect(d)} className={`flex-1 min-w-0 text-left py-1 flex flex-col ${d.state === 'cleaned' ? 'opacity-60' : ''}`}
            title={isDerived ? `${originLabel(d)} · ${fmtLocal(d.created_at)}${d.origin?.code ? ' · ' + d.origin.code : ''}` : d.name}>
            <span className="flex items-center gap-1.5 min-w-0">
              {isDerived ? <span className="font-mono text-xs text-ink-500 shrink-0 w-3.5 text-center">↳</span> : <Database className="w-3.5 h-3.5 text-brand-600 shrink-0" strokeWidth={1.5} />}
              <span className={`truncate text-[13px] ${isDerived ? 'font-mono text-xs' : ''} ${d.state === 'cleaned' ? 'line-through decoration-ink-400' : ''}`}>{label}</span>
              <span className="text-[11px] font-mono text-ink-500 shrink-0">{d.rows.toLocaleString()}×{d.columns}</span>
              {kids.length > 0 && <span className="text-[10px] text-ink-400 shrink-0">· {kids.length} 步</span>}
              {isDerived && d.kept && <Pin className="w-3 h-3 text-ink-500 shrink-0" />}
              {d.state === 'cleaned' && <span className="text-[10px] px-1 rounded-sm bg-ink-150 text-ink-600 shrink-0">已清理</span>}
              {d.state !== 'cleaned' && !d.kept && (() => { const left = daysLeft(d.expires_at); return left != null && left <= 3
                ? <span className="text-[10px] px-1 rounded-sm bg-warning-50 text-warning-700 border border-warning-200 shrink-0">{left <= 0 ? '已到期' : `剩 ${Math.ceil(left)} 天`}</span> : null; })()}
            </span>
            {isDerived && (
              <span className="pl-5 text-[10px] text-ink-500 truncate">{originLabel(d)} · {fmtLocal(d.created_at)}{d.origin?.code ? ` · ${d.origin.code}` : ''}</span>
            )}
          </button>
          {isDerived && (
            <button
              onClick={(e) => { e.stopPropagation(); onKeep(d.id, !d.kept); }}
              title={d.kept ? '取消保留(可被自动清理)' : '保留这个中间结果(不被自动清理)'}
              className={`shrink-0 ${d.kept ? 'text-amber-500 hover:text-amber-600' : 'opacity-0 group-hover:opacity-100 text-ink-400 hover:text-amber-500'}`}
            >
              {d.kept ? <PinOff className="w-3.5 h-3.5" /> : <Pin className="w-3.5 h-3.5" />}
            </button>
          )}
          <button onClick={() => onDelete(d.id)} className="opacity-0 group-hover:opacity-100 text-ink-400 hover:text-red-600 shrink-0"><Trash2 className="w-3.5 h-3.5" /></button>
        </div>
        {open && kids.map((k) => renderNode(k, depth + 1))}
      </div>
    );
  };

  return <div className="space-y-0.5">{roots.map((r) => renderNode(r, 0))}</div>;
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

function DatasetPreview({ ds, t, datasets, onPromote, onKeep, onSubsetSaved, onAsk, onOpenConversation, onOpenTemplate, onNewDataset }: { ds: Dataset; t: (k: string) => string; datasets: Dataset[]; onPromote: () => void; onKeep: (kept: boolean) => void; onSubsetSaved?: (d: Dataset) => void; onAsk?: (prompt: string, datasetId: number) => void; onOpenConversation?: (id: number) => void; onOpenTemplate?: (id: number) => void; onNewDataset?: (id: number, message: string) => void }) {
  const cols = ds.schema.columns ?? [];
  const lang = useLangStore((s) => s.lang);
  const isDerived = ds.kind === 'derived' || ds.derived_from != null;
  const [showChart, setShowChart] = useState(false);
  const [showMesh, setShowMesh] = useState(false);
  const [explaining, setExplaining] = useState(false);
  const [explanation, setExplanation] = useState('');
  // Instant deterministic first-read (free; auto-loaded on every dataset switch).
  const [profile, setProfile] = useState<DatasetProfile | null>(null);
  // Re-explain / re-profile when switching datasets.
  useEffect(() => { setExplanation(''); setExplaining(false); }, [ds.id]);
  useEffect(() => {
    setProfile(null);
    let alive = true;
    if (ds.state !== 'cleaned') api.profileDataset(ds.id).then((p) => { if (alive) setProfile(p); }).catch(() => {});
    return () => { alive = false; };
  }, [ds.id]);
  async function explain() {
    setExplaining(true); setExplanation('');
    try { const r = await api.explainDataset(ds.id); setExplanation(r.explanation || '(没有得到解释)'); }
    catch (e) { setExplanation('(解释失败:' + (e as Error).message + ')'); }
    finally { setExplaining(false); }
  }
  // Dispatch a suggestion chip: in-view actions run here; analysis recipes are
  // forwarded to chat as a ready-made question on this dataset.
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
  // Mesh / CGNS dataset = has X/Y/Z coordinate columns → offer the 3D viewer.
  const isMesh = ['x', 'y', 'z'].every((a) => cols.some((c) => c.name.toLowerCase() === a));

  // Full lineage breadcrumb: walk derived_from up to the source root.
  const byId = new Map(datasets.map((d) => [d.id, d]));
  const chain: Dataset[] = [];
  { let cur: Dataset | undefined = ds; const seen = new Set<number>();
    while (cur && !seen.has(cur.id)) { seen.add(cur.id); chain.unshift(cur); cur = cur.derived_from != null ? byId.get(cur.derived_from) : undefined; } }

  return (
    <div className="p-6">
      <div className="mb-5 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h2 className="text-xl font-semibold truncate text-ink-900">{ds.name}</h2>
            {isDerived && <SourceTag kind="derived" className="shrink-0">中间结果</SourceTag>}
          </div>
          <p className="mt-0.5 text-xs font-mono text-ink-600">{ds.filename} · {ds.file_format} · {ds.rows.toLocaleString()} {t('side.rows')} × {ds.columns} {t('side.cols')}</p>
        </div>
        <div className={`shrink-0 flex items-center gap-2 ${ds.state === 'cleaned' ? 'hidden' : ''}`}>
          <button onClick={explain} disabled={explaining}
            className="inline-flex items-center gap-1.5 text-[13px] h-8 px-3 rounded border border-ink-300 bg-white text-ink-800 hover:bg-ink-50 disabled:opacity-50">
            {explaining ? <Loader2 className="w-4 h-4 animate-spin" /> : <AiMark />} 解释
          </button>
          {isMesh && (
            <button onClick={() => { setShowMesh((v) => !v); }}
              className={`inline-flex items-center gap-1.5 text-[13px] h-8 px-3 rounded border ${showMesh ? 'bg-ink-900 text-white border-ink-900 hover:bg-ink-800' : 'bg-white text-ink-800 border-ink-300 hover:bg-ink-50'}`}>
              <Box className="w-4 h-4" /> {showMesh ? '收起 3D' : '3D 网格'}
            </button>
          )}
          <button onClick={() => setShowChart((v) => !v)}
            className={`inline-flex items-center gap-1.5 text-[13px] h-8 px-3 rounded border ${showChart ? 'bg-ink-900 text-white border-ink-900 hover:bg-ink-800' : 'bg-white text-ink-800 border-ink-300 hover:bg-ink-50'}`}>
            <BarChart3 className="w-4 h-4" /> {showChart ? '收起图表' : '可视化'}
          </button>
        </div>
      </div>
      <ProvenanceCard ds={ds} onOpenConversation={onOpenConversation} onOpenTemplate={onOpenTemplate} onNewDataset={onNewDataset} />
      {ds.state === 'cleaned' ? (
        <div className="rounded-md border border-ink-200 bg-ink-50 px-4 py-6 text-sm text-ink-600 text-center">
          这份中间结果的数据已于 {fmtLocal(ds.cleaned_at ?? null) || '之前'} 清理，名称和血缘仍保留。
          {ds.run_id ? '需要时可以在上方「重跑」或「复现」。' : '它产生于升级之前，没有运行记录，无法自动重跑；可以回到原对话或流程重新运行。'}
        </div>
      ) : <>
      {profile && (
        <div className="mb-5 rounded-md bg-white border border-ink-200 overflow-hidden flex items-stretch">
          <div className="flex-1 p-4">
            <div className="flex items-center gap-2 text-ink-800 font-semibold text-[13px] mb-1.5">
              {lang === 'zh' ? '数据概况' : 'Data profile'}<span className="text-xs font-normal text-ink-500">{lang === 'zh' ? '自动生成' : 'auto-generated'}</span>
            </div>
            <p className="text-sm text-ink-900 leading-relaxed">{profile.headline}</p>
            {profile.facts.length > 0 && (
              <div className="mt-2.5 flex flex-wrap gap-2">
                {profile.facts.map((f, i) => (
                  <span key={i} className="inline-flex items-center text-xs text-ink-700 bg-ink-50 border border-ink-200 rounded-sm px-2 py-0.5">{f}</span>
                ))}
              </div>
            )}
            {profile.semantic && profile.semantic.length > 0 && (
              <div className="mt-3 rounded border border-ink-200 bg-ink-50 px-3 py-2">
                <div className="text-xs text-ink-600 font-medium mb-1.5">
                  {lang === 'zh' ? '已套用专家规则（列含义）' : 'Applied expert rules (column meanings)'}
                </div>
                <div className="flex flex-wrap gap-2">
                  {profile.semantic.map((m) => (
                    <span key={m.rule_id + m.column} className="inline-flex items-center gap-1 text-xs text-ink-800 bg-white border border-ink-200 rounded-sm px-2 py-0.5">
                      <code className="font-mono text-ink-900">{m.column}</code>
                      <span className="text-ink-400">→</span>
                      <span className="font-medium">{m.label}</span>
                    </span>
                  ))}
                </div>
              </div>
            )}
            {profile.suggestions.length > 0 && (
              <div className="mt-3.5 pt-3 border-t border-ink-100">
                <div className="text-xs text-ink-500 mb-2">{lang === 'zh' ? '可以这样做：' : 'You could:'}</div>
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
        </div>
      )}
      {(explaining || explanation) && (
        <div className="mb-5 rounded-md bg-white border border-dashed border-ink-500 p-4 text-sm text-ink-700">
          <div className="flex items-center gap-1.5 text-ink-800 font-medium mb-1.5"><AiMark /> 解释 <span className="text-xs font-normal text-ink-500">AI 生成，仅供参考</span></div>
          {explaining ? <div className="text-ink-400 flex items-center gap-1.5"><Loader2 className="w-3.5 h-3.5 animate-spin" /> 正在解读…</div>
            : <div className="prose-tight leading-relaxed"><Markdown>{explanation}</Markdown></div>}
        </div>
      )}
      {showMesh && isMesh && (
        <div className="bg-white rounded-2xl ring-1 ring-ink-200 p-4 mb-5">
          <MeshViewer3D datasetId={ds.id} name={ds.name} />
        </div>
      )}
      {showChart && (
        <div className="bg-white rounded-2xl ring-1 ring-ink-200 p-4 mb-5">
          <DatasetChart datasetId={ds.id} name={ds.name} />
        </div>
      )}

      {isDerived && (
        <div className="mb-5 rounded-md bg-white border border-ink-200 px-4 py-3 text-sm">
          <div className="flex items-center gap-1.5 flex-wrap">
            <GitBranch className="w-4 h-4 text-ink-500 shrink-0" strokeWidth={1.5} />
            <span className="text-ink-500 mr-1">血缘:</span>
            {chain.map((c, i) => (
              <span key={c.id} className="inline-flex items-center gap-1.5">
                {i > 0 && <span className="text-ink-300">▸</span>}
                {i === 0
                  ? <span className="font-medium text-ink-700">{c.name}</span>
                  : <span className={`font-mono text-xs px-1.5 py-0.5 rounded-sm ${c.id === ds.id ? 'bg-brand-600 text-white' : 'bg-white border border-ink-300'}`}>{c.lineage?.op?.label || '处理'}</span>}
              </span>
            ))}
            <div className="ml-auto flex items-center gap-1.5">
              <button onClick={() => onKeep(!ds.kept)}
                title={ds.kept ? '取消保留后,可被自动清理' : '保留在中间结果树里,不被自动清理'}
                className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-lg ring-1 ${ds.kept ? 'bg-ink-150 text-ink-800 ring-ink-300 hover:bg-ink-200' : 'bg-white text-ink-600 ring-ink-200 hover:bg-ink-50'}`}>
                {ds.kept ? <PinOff className="w-3.5 h-3.5" /> : <Pin className="w-3.5 h-3.5" />} {ds.kept ? '已保留' : '保留'}
              </button>
              <button onClick={onPromote} className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-lg bg-brand-600 text-white hover:bg-brand-700">
                <Bookmark className="w-3.5 h-3.5" /> 升为正式数据集
              </button>
            </div>
          </div>
          {ds.kept && (
            <div className="mt-2 text-[11px] text-amber-700 flex items-center gap-1.5">
              <Pin className="w-3 h-3" /> 已保留 —— 自动清理不会删除它。
            </div>
          )}
        </div>
      )}

      <div className="bg-white rounded-2xl ring-1 ring-ink-200 p-5 mb-5">
        <h3 className="font-medium mb-3">{t('ds.schema')}</h3>
        <table className="w-full text-sm">
          <thead className="text-ink-500 text-xs uppercase tracking-wide">
            <tr className="border-b border-ink-200"><th className="text-left py-2">{t('ds.column')}</th><th className="text-left">{t('ds.dtype')}</th><th className="text-right">{t('ds.unique')}</th><th className="text-right">{t('ds.missing')}</th></tr>
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

      <div className="bg-white rounded-2xl ring-1 ring-ink-200 p-5">
        <h3 className="font-medium mb-3">数据表 · 排序 / 筛选 / 选择另存</h3>
        <DataTable ds={ds} onSaved={onSubsetSaved} />
      </div>
      </>}
    </div>
  );
}

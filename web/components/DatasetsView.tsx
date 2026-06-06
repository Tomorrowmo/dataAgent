'use client';

import { useEffect, useRef, useState } from 'react';
import { Upload, Trash2, Database, Loader2, AlertTriangle, GitBranch, Bookmark, ChevronRight, Pin, PinOff, Recycle, BarChart3, Box, Sparkles } from 'lucide-react';
import type { ReactNode } from 'react';
import Markdown from '@/components/Markdown';
import { api, type Dataset, type UploadResp } from '@/lib/api';
import { useT } from '@/lib/i18n';
import ParserModal from '@/components/ParserModal';
import DatasetChart from '@/components/DatasetChart';
import DataTable from '@/components/DataTable';
import dynamic from 'next/dynamic';
// three / @react-three are browser-only (reference window/self) — client-only load.
const MeshViewer3D = dynamic(() => import('@/components/MeshViewer3D'), { ssr: false });

type NeedsParser = NonNullable<UploadResp['needs_parser']>;

export default function DatasetsView() {
  const t = useT();
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
    } catch (e) {
      setError((e as Error).message);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

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
    if (!confirm(t('ds.confirmDelete'))) return;
    try {
      await api.deleteDataset(id);
      if (selected?.id === id) setSelected(null);
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
      if (preview.count === 0) { setError('没有可清理的中间结果(近 2 小时内的、已保留的、以及正在使用的都会保留)。'); return; }
      const mb = (preview.freed_bytes / 1_000_000).toFixed(1);
      if (!confirm(`将清理 ${preview.count} 个未保留的中间结果数据集,释放约 ${mb} MB。\n(已「保留」的、源数据、正在用于流水线的不受影响。)\n继续?`)) return;
      await api.gcDatasets(false);
      if (selected && preview.deleted.some((d) => d.id === selected.id)) setSelected(null);
      await refresh();
    } catch (e) { setError((e as Error).message); }
    finally { setGcing(false); }
  }

  const derivedCount = datasets.filter((d) => (d.kind === 'derived' || d.derived_from != null) && !d.kept).length;

  return (
    <div className="flex h-full">
      {pendingParser && (
        <ParserModal
          pending={pendingParser}
          onClose={shiftQueue}
          onIngested={onParserIngested}
        />
      )}
      <div
        className={`w-full md:w-80 border-r bg-white flex flex-col transition-colors ${selected ? 'max-md:hidden' : ''} ${dragOver ? 'border-brand-400 bg-brand-50/40' : 'border-ink-200'}`}
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
        <div className="flex-1 overflow-y-auto scroll-hide p-2">
          {datasets.length === 0 && <div className="text-sm text-ink-500 text-center mt-8 px-4">{t('ds.empty')}</div>}
          <DatasetTree datasets={datasets} selectedId={selected?.id ?? null}
            onSelect={setSelected} onDelete={handleDelete} onKeep={handleKeep} />
        </div>
      </div>

      <div className={`flex-1 overflow-y-auto scroll-hide ${selected ? '' : 'max-md:hidden'}`}>
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
        {!selected && <div className="grid place-items-center h-full text-ink-500">{t('ds.select')}</div>}
        {selected && <DatasetPreview ds={selected} t={t} datasets={datasets} onPromote={() => handlePromote(selected.id)} onKeep={(k) => handleKeep(selected.id, k)} onSubsetSaved={(d) => { refresh(); setSelected(d); }} />}
      </div>
    </div>
  );
}

/** Lineage tree: source datasets are roots; each derived dataset nests under
 *  the step that produced it (原始 → 去噪 → 检测 → …), collapsible. This is the
 *  methodology made visible — datasets are a DAG, not a flat list. */
function DatasetTree({ datasets, selectedId, onSelect, onDelete, onKeep }: {
  datasets: Dataset[]; selectedId: number | null; onSelect: (d: Dataset) => void; onDelete: (id: number) => void; onKeep: (id: number, kept: boolean) => void;
}) {
  const [expanded, setExpanded] = useState<Set<number>>(() => new Set());
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
          className={`group flex items-center gap-1 rounded-lg pr-1 ${selectedId === d.id ? 'bg-brand-50 ring-1 ring-brand-200' : 'hover:bg-ink-100'}`}
          style={{ paddingLeft: 4 + depth * 14 }}
        >
          {kids.length > 0 ? (
            <button onClick={() => toggle(d.id)} className="p-0.5 text-ink-400 hover:text-ink-700 shrink-0">
              <ChevronRight className={`w-3.5 h-3.5 transition-transform ${open ? 'rotate-90' : ''}`} />
            </button>
          ) : <span className="w-4 shrink-0" />}
          <button onClick={() => onSelect(d)} className="flex-1 min-w-0 text-left py-1.5 flex items-center gap-1.5">
            {isDerived ? <GitBranch className="w-3.5 h-3.5 text-violet-500 shrink-0" /> : <Database className="w-3.5 h-3.5 text-brand-500 shrink-0" />}
            <span className="truncate text-sm">{label}</span>
            <span className="text-[11px] text-ink-400 shrink-0">{d.rows.toLocaleString()}×{d.columns}</span>
            {kids.length > 0 && <span className="text-[10px] text-ink-400 shrink-0">· {kids.length} 步</span>}
            {isDerived && d.kept && <Pin className="w-3 h-3 text-amber-500 shrink-0" />}
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

function DatasetPreview({ ds, t, datasets, onPromote, onKeep, onSubsetSaved }: { ds: Dataset; t: (k: string) => string; datasets: Dataset[]; onPromote: () => void; onKeep: (kept: boolean) => void; onSubsetSaved?: (d: Dataset) => void }) {
  const cols = ds.schema.columns ?? [];
  const isDerived = ds.kind === 'derived' || ds.derived_from != null;
  const [showChart, setShowChart] = useState(false);
  const [showMesh, setShowMesh] = useState(false);
  const [explaining, setExplaining] = useState(false);
  const [explanation, setExplanation] = useState('');
  // Re-explain when switching datasets.
  useEffect(() => { setExplanation(''); setExplaining(false); }, [ds.id]);
  async function explain() {
    setExplaining(true); setExplanation('');
    try { const r = await api.explainDataset(ds.id); setExplanation(r.explanation || '(没有得到解释)'); }
    catch (e) { setExplanation('(解释失败:' + (e as Error).message + ')'); }
    finally { setExplaining(false); }
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
            <h2 className="text-xl font-semibold truncate">{ds.name}</h2>
            {isDerived && <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-violet-100 text-violet-700 shrink-0">中间结果</span>}
          </div>
          <p className="text-sm text-ink-500">{ds.filename} · {ds.file_format} · {ds.rows.toLocaleString()} {t('side.rows')} × {ds.columns} {t('side.cols')}</p>
        </div>
        <div className="shrink-0 flex items-center gap-2">
          <button onClick={explain} disabled={explaining}
            className="inline-flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg ring-1 ring-violet-200 text-violet-700 hover:bg-violet-50 disabled:opacity-50">
            {explaining ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />} AI 解释
          </button>
          {isMesh && (
            <button onClick={() => { setShowMesh((v) => !v); }}
              className={`inline-flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg ring-1 ${showMesh ? 'bg-indigo-600 text-white ring-transparent hover:bg-indigo-700' : 'ring-indigo-200 text-indigo-700 hover:bg-indigo-50'}`}>
              <Box className="w-4 h-4" /> {showMesh ? '收起 3D' : '3D 网格'}
            </button>
          )}
          <button onClick={() => setShowChart((v) => !v)}
            className={`inline-flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg ring-1 ${showChart ? 'bg-brand-600 text-white ring-transparent hover:bg-brand-700' : 'ring-brand-200 text-brand-700 hover:bg-brand-50'}`}>
            <BarChart3 className="w-4 h-4" /> {showChart ? '收起图表' : '可视化'}
          </button>
        </div>
      </div>
      {(explaining || explanation) && (
        <div className="mb-5 rounded-2xl bg-violet-50/60 ring-1 ring-violet-100 p-4 text-sm text-ink-700">
          <div className="flex items-center gap-1.5 text-violet-700 font-medium mb-1.5"><Sparkles className="w-4 h-4" /> AI 解释</div>
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
        <div className="mb-5 rounded-xl bg-violet-50/60 ring-1 ring-violet-100 px-4 py-3 text-sm">
          <div className="flex items-center gap-1.5 flex-wrap">
            <GitBranch className="w-4 h-4 text-violet-500 shrink-0" />
            <span className="text-ink-500 mr-1">血缘:</span>
            {chain.map((c, i) => (
              <span key={c.id} className="inline-flex items-center gap-1.5">
                {i > 0 && <span className="text-ink-300">▸</span>}
                {i === 0
                  ? <span className="font-medium text-ink-700">{c.name}</span>
                  : <span className={`font-mono px-1.5 py-0.5 rounded ${c.id === ds.id ? 'bg-violet-600 text-white' : 'bg-white ring-1 ring-violet-200'}`}>{c.lineage?.op?.label || '处理'}</span>}
              </span>
            ))}
            <div className="ml-auto flex items-center gap-1.5">
              <button onClick={() => onKeep(!ds.kept)}
                title={ds.kept ? '取消保留后,可被自动清理' : '保留在中间结果树里,不被自动清理'}
                className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-lg ring-1 ${ds.kept ? 'bg-amber-50 text-amber-700 ring-amber-200 hover:bg-amber-100' : 'bg-white text-ink-600 ring-ink-200 hover:bg-ink-50'}`}>
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
    </div>
  );
}

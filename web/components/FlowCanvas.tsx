'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type DragEvent } from 'react';
import { createPortal } from 'react-dom';
import {
  ReactFlow, ReactFlowProvider, Background, Controls, MiniMap,
  Handle, Position, addEdge, useNodesState, useEdgesState, useReactFlow,
  type Node, type Edge, type Connection, type NodeProps, MarkerType,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  Database, Wrench, Play, Save, Loader2, Trash2, Sparkles, Layers, Table2,
  CheckCircle2, AlertTriangle, GitBranch, ArrowRight, X, Search, BarChart3, ChevronDown, ChevronRight,
} from 'lucide-react';
import { api, type Algorithm, type Dataset, type FlowTemplate, type TemplateStep, type TemplateRunResult, type FlowGraph, type ParamSpec } from '@/lib/api';
import { ALGO_ZH, paramToStr, coerceParam, dispName, dispDesc, dispExample, catZh, RETURNS_ZH, SOURCE_ZH, COL_MULTI, COL_SINGLE, paramKind, matchAlgo, groupByIntent, intentIcon, intentZh, algoIntent } from '@/lib/algoMeta';
import ParamField from '@/components/ParamField';
import DatasetChart from '@/components/DatasetChart';

/**
 * Free-form React-Flow canvas for editing a flow template. Unlike the old
 * vertical list editor, nodes can be dragged, connected, and laid out freely;
 * the layout (positions + edges) persists in template.graph. Replay still runs
 * the LINEAR topological order of the graph (each node on its predecessor's
 * output), so the existing backend pipeline replay is unchanged.
 *
 * Templates created before the canvas have no graph — we synthesize a linear
 * layout from their `steps` on first open.
 */

type StepData = { kind: 'input' | 'step'; slug?: string; params: Record<string, unknown>; label: string; category?: string; status?: 'ok' | 'error' | 'skipped'; stale?: boolean; needsParams?: boolean };

/** A param value counts as "unset" (so a required one flags the node). */
function isEmptyVal(v: unknown): boolean {
  return v === undefined || v === null || v === '' || (Array.isArray(v) && v.length === 0);
}
type FlowNode = Node<StepData>;

const NODE_W = 248;
const NODE_GAP = 96; // horizontal spacing between a node and the next
const HANDLE = '!w-2.5 !h-2.5 !border-2 !border-white !bg-brand-400 !rounded-full';

/** Lets the custom input node reach the run-time dataset selection without
 *  stuffing callbacks into (serialized) node data. The first node IS the
 *  template's input: the user picks which dataset to run on right there. */
const InputCtx = createContext<{
  datasets: Dataset[];
  datasetIds: number[];
  toggleDataset: (id: number) => void;
  onPreview: (ds: Dataset) => void;
} | null>(null);

/** Soft, low-saturation icon tone per algorithm category (kept restrained).
 *  Keys are the real backend categories (see CAT_ZH): filter / preprocess /
 *  reduce / regression / structure / custom. */
function catTone(cat?: string): string {
  switch (cat) {
    case 'filter': return 'bg-indigo-50 text-indigo-600';
    case 'preprocess': return 'bg-sky-50 text-sky-600';
    case 'reduce': return 'bg-violet-50 text-violet-600';
    case 'regression': return 'bg-amber-50 text-amber-600';
    case 'structure': return 'bg-rose-50 text-rose-600';
    case 'custom': return 'bg-ink-100 text-ink-600';
    default: return 'bg-brand-50 text-brand-600';
  }
}

/** Algorithm params rendered as compact key·value chips (Coze-style). */
function ParamPills({ params }: { params: Record<string, unknown> }) {
  const entries = Object.entries(params || {}).filter(([, v]) => v !== undefined && v !== null && v !== '');
  if (entries.length === 0) return <span className="text-[10.5px] text-ink-400">默认参数</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {entries.slice(0, 4).map(([k, v]) => {
        const val = paramToStr(v);
        const short = val.length > 12 ? val.slice(0, 11) + '…' : val;
        return (
          <span key={k} className="inline-flex items-center gap-1 text-[10px] rounded-md bg-ink-50 ring-1 ring-ink-200 px-1.5 py-0.5 max-w-full">
            <span className="text-ink-400 font-mono shrink-0">{k}</span>
            <span className="text-ink-700 font-mono truncate">{short}</span>
          </span>
        );
      })}
      {entries.length > 4 && <span className="text-[10px] text-ink-400 self-center">+{entries.length - 4}</span>}
    </div>
  );
}

function InputNode({ selected }: NodeProps) {
  const ctx = useContext(InputCtx);
  const ids = ctx?.datasetIds ?? [];
  const chosen = ids.map((id) => ctx!.datasets.find((d) => d.id === id)).filter(Boolean) as Dataset[];
  const primary = chosen[0] ?? null;
  const ncols = primary?.columns ?? (primary?.schema?.columns?.length ?? 0);
  const addable = (ctx?.datasets ?? []).filter((d) => !ids.includes(d.id));
  const stop = (e: { stopPropagation: () => void }) => e.stopPropagation();
  return (
    <div className={`rounded-2xl bg-white shadow-sm transition-shadow hover:shadow-md ${selected ? 'ring-2 ring-emerald-500' : 'ring-1 ring-emerald-200 hover:ring-emerald-300'}`} style={{ width: NODE_W }}>
      <div className="px-3 py-2.5 flex items-center gap-2.5 border-b border-ink-100">
        <span className="grid place-items-center w-7 h-7 rounded-lg bg-emerald-50 text-emerald-600 shrink-0"><Database className="w-3.5 h-3.5" /></span>
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-semibold text-ink-900 truncate leading-tight">输入数据</div>
          <div className="text-[10px] text-ink-400">模版入口 · 可多选,批量逐个执行</div>
        </div>
      </div>
      <div className="px-3 py-2 space-y-1.5">
        {chosen.length > 0 ? (
          <div className="flex flex-wrap gap-1">
            {chosen.map((d, i) => (
              <span key={d.id} className="nodrag inline-flex items-center gap-1 text-[10.5px] rounded-md bg-emerald-50 ring-1 ring-emerald-200 text-emerald-700 px-1.5 py-0.5 max-w-full">
                {i === 0 && <span title="主数据集:列以它为准">★</span>}
                <span className="truncate">{d.name}</span>
                <button className="nodrag font-bold leading-none" title="移除" onMouseDown={stop} onClick={(e) => { stop(e); ctx?.toggleDataset(d.id); }}>×</button>
              </span>
            ))}
          </div>
        ) : (
          <div className="text-[10.5px] text-amber-600">未选数据集,无法执行</div>
        )}
        {addable.length > 0 && (
          <select className="nodrag w-full border border-ink-200 rounded-lg px-2 py-1 bg-white text-xs focus:outline-none focus:border-emerald-400"
            value="" onMouseDown={stop} onClick={stop}
            onChange={(e) => { if (e.target.value) ctx?.toggleDataset(Number(e.target.value)); }}>
            <option value="">+ 添加数据集…</option>
            {addable.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        )}
        {primary && (
          <div className="flex items-center justify-between text-[10.5px] text-ink-500">
            <span className="font-mono">{ids.length > 1 ? `${ids.length} 个数据集 · 批量执行` : `输出 ${primary.rows.toLocaleString()} 行 × ${ncols} 列`}</span>
            <button className="nodrag text-violet-600 hover:text-violet-700 font-medium"
              onMouseDown={stop} onClick={(e) => { stop(e); ctx?.onPreview(primary); }}>预览</button>
          </div>
        )}
      </div>
      <Handle type="source" position={Position.Right} className={HANDLE} />
    </div>
  );
}

function StepNode({ data, selected }: NodeProps) {
  const d = data as StepData;
  const desc = ALGO_ZH[d.slug ?? '']?.desc;
  // Ring reflects last replay status (ok/error); selection still wins visually.
  const statusRing = d.status === 'error' ? 'ring-1 ring-red-300' : d.status === 'ok' ? 'ring-1 ring-emerald-300' : 'ring-1 ring-ink-200 hover:ring-brand-300';
  return (
    <div
      className={`relative rounded-2xl bg-white shadow-sm transition-shadow hover:shadow-md ${selected ? 'ring-2 ring-brand-500 shadow-md' : statusRing}`}
      style={{ width: NODE_W }}
    >
      {d.status === 'ok' && !d.stale && !d.needsParams && <CheckCircle2 className="absolute -top-1.5 -right-1.5 w-4 h-4 text-emerald-500 bg-white rounded-full" />}
      {d.status === 'error' && <AlertTriangle className="absolute -top-1.5 -right-1.5 w-4 h-4 text-red-500 bg-white rounded-full" />}
      {(d.stale || d.needsParams) && d.status !== 'error' && (
        <span title={d.needsParams ? '缺必填参数,点开节点设置' : '有列参数不在该步的输入数据中'}
          className="absolute -top-1.5 -right-1.5 w-4 h-4 grid place-items-center text-[10px] bg-amber-400 text-white rounded-full font-bold">!</span>
      )}
      <Handle type="target" position={Position.Left} className={HANDLE} />
      <div className="px-3 py-2.5 flex items-center gap-2.5 border-b border-ink-100">
        <span className={`grid place-items-center w-7 h-7 rounded-lg shrink-0 ${catTone(d.category)}`}><Wrench className="w-3.5 h-3.5" /></span>
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-semibold text-ink-900 truncate leading-tight">{d.label}</div>
          {d.slug && <div className="text-[10px] text-ink-400 font-mono truncate">{d.slug}</div>}
        </div>
      </div>
      <div className="px-3 py-2 space-y-1.5">
        {desc && <div className="text-[10.5px] text-ink-500 leading-snug line-clamp-1">{desc}</div>}
        <ParamPills params={d.params} />
      </div>
      <Handle type="source" position={Position.Right} className={HANDLE} />
    </div>
  );
}

// NB: don't name a type 'input'/'default'/'output' — those are React Flow
// built-ins and their default CSS (border, fixed width, centered text) would
// wrap our custom node. Use a bespoke name.
const nodeTypes = { dataInput: InputNode, step: StepNode };

const INPUT_ID = 'input';
const algoLabel = (slug?: string, algos?: Map<string, Algorithm>) =>
  ALGO_ZH[slug ?? '']?.name ?? algos?.get(slug ?? '')?.name ?? slug ?? '步骤';

/** Build initial RF nodes/edges from a template's graph, or synthesize a linear
 *  layout from its steps when there's no graph yet. */
function buildInitial(tpl: FlowTemplate, algos: Map<string, Algorithm>): { nodes: FlowNode[]; edges: Edge[] } {
  const g = tpl.graph;
  if (g?.nodes && g.nodes.length) {
    const nodes: FlowNode[] = g.nodes.map((n) => ({
      id: n.id,
      type: n.kind === 'input' ? 'dataInput' : 'step',
      position: n.position ?? { x: 60, y: 120 },
      data: { kind: n.kind ?? 'step', slug: n.slug, params: n.params ?? {}, label: n.label ?? algoLabel(n.slug, algos), category: algos.get(n.slug ?? '')?.category },
    }));
    const edges: Edge[] = (g.edges ?? []).map((e, i) => ({
      id: `e${i}_${e.source}_${e.target}`, source: e.source, target: e.target,
      markerEnd: { type: MarkerType.ArrowClosed }, animated: false,
    }));
    // Legacy templates were laid out vertically (single column). With the new
    // left→right ports those look like big C-curves, so re-flow them once.
    const xs = nodes.map((n) => n.position.x);
    if (nodes.length > 1 && Math.max(...xs) - Math.min(...xs) < NODE_W) {
      const inputId = nodes.find((n) => n.data.kind === 'input')?.id;
      const seq = [inputId, ...topoOrderIds(nodes, edges)].filter(Boolean) as string[];
      seq.forEach((id, i) => {
        const nd = nodes.find((n) => n.id === id);
        if (nd) nd.position = { x: 40 + i * (NODE_W + NODE_GAP), y: 120 };
      });
    }
    return { nodes, edges };
  }
  // Synthesize a left → right pipeline: input → step1 → step2 → …
  const tool = (tpl.steps || []).filter((s) => s.action === 'run_tool' && s.slug);
  const nodes: FlowNode[] = [{ id: INPUT_ID, type: 'dataInput', position: { x: 40, y: 120 }, data: { kind: 'input', params: {}, label: '原始数据' } }];
  const edges: Edge[] = [];
  let prev = INPUT_ID;
  tool.forEach((s, i) => {
    const id = `n${i}`;
    nodes.push({ id, type: 'step', position: { x: 40 + (i + 1) * (NODE_W + NODE_GAP), y: 120 }, data: { kind: 'step', slug: s.slug, params: { ...(s.params || {}) }, label: s.label || algoLabel(s.slug, algos), category: algos.get(s.slug ?? '')?.category } });
    edges.push({ id: `e${i}`, source: prev, target: id, markerEnd: { type: MarkerType.ArrowClosed } });
    prev = id;
  });
  return { nodes, edges };
}

/** Step-node IDs in execution (topological) order, following edges from the
 *  input node. Replay runs each step on its predecessor's output, and the
 *  i-th entry here lines up with the backend's `steps[i]` run result. */
function topoOrderIds(nodes: FlowNode[], edges: Edge[]): string[] {
  const adj = new Map<string, string[]>();
  for (const e of edges) { (adj.get(e.source) ?? adj.set(e.source, []).get(e.source)!).push(e.target); }
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const order: string[] = [];
  const seen = new Set<string>();
  const start = byId.has(INPUT_ID) ? INPUT_ID : nodes.find((n) => n.data.kind === 'input')?.id;
  const stack = start ? [start] : nodes.filter((n) => !edges.some((e) => e.target === n.id)).map((n) => n.id);
  // BFS in insertion order; guards against cycles via `seen`.
  const queue = [...stack];
  while (queue.length) {
    const id = queue.shift()!;
    if (seen.has(id)) continue;
    seen.add(id);
    if (byId.get(id)?.data.kind === 'step') order.push(id);
    for (const nxt of adj.get(id) ?? []) if (!seen.has(nxt)) queue.push(nxt);
  }
  // Append any disconnected step nodes so they aren't silently lost.
  for (const n of nodes) if (n.data.kind === 'step' && !seen.has(n.id)) order.push(n.id);
  return order;
}

function topoSteps(nodes: FlowNode[], edges: Edge[]): TemplateStep[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  return topoOrderIds(nodes, edges).map((id) => {
    const n = byId.get(id)!;
    return { action: 'run_tool', slug: n.data.slug, params: n.data.params || {}, label: n.data.label };
  }).filter((s) => s.slug);
}

/** Column names referenced by a step's column-type params (columns/cols/x/y/…). */
function colRefs(params: Record<string, unknown>): string[] {
  const out: string[] = [];
  for (const [k, v] of Object.entries(params || {})) {
    const n = k.toLowerCase();
    if (!COL_MULTI.has(n) && !COL_SINGLE.has(n)) continue;
    if (Array.isArray(v)) out.push(...v.map(String));
    else if (typeof v === 'string' && v) out.push(v);
  }
  return out;
}

/** Stable key for a runtime-param (node + param name). */
const rtKey = (nodeId: string, param: string) => `${nodeId}::${param}`;

/** dataTransfer key for dragging an algorithm slug from the palette → canvas. */
const DND_MIME = 'application/x-algo-slug';

function Canvas({ tpl, datasets, algos, onChanged, onDeleted }: {
  tpl: FlowTemplate; datasets: Dataset[]; algos: Algorithm[]; onChanged: () => void; onDeleted: () => void;
}) {
  const bySlug = useMemo(() => new Map(algos.map((a) => [a.slug, a])), [algos]);
  const init = useMemo(() => buildInitial(tpl, bySlug), [tpl.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>(init.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(init.edges);
  const [name, setName] = useState(tpl.name);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [selId, setSelId] = useState<string | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(true);
  const rf = useReactFlow();

  // Input is multi-select: the flow batch-runs on EACH chosen dataset; the first
  // is the PRIMARY (its columns drive the param pickers). `activeIdx` is which
  // batch result is currently shown.
  const [datasetIds, setDatasetIds] = useState<number[]>(datasets[0] ? [datasets[0].id] : []);
  const [activeIdx, setActiveIdx] = useState(0);
  const [busy, setBusy] = useState(false);
  const [multiRes, setMultiRes] = useState<{ dsId: number; name: string; res: TemplateRunResult }[]>([]);
  // Batch results view: '逐个' (tab per dataset) or '全部出图' (a chart grid, one
  // figure per file — the 批量出图 the user asked for).
  const [batchView, setBatchView] = useState<'tabs' | 'grid'>('tabs');
  const [err, setErr] = useState('');
  // Draggable inspector width (persisted across nodes + sessions).
  const [inspectorWidth, setInspectorWidth] = useState<number>(() => {
    if (typeof window === 'undefined') return 360;
    const v = Number(localStorage.getItem('flow.inspectorWidth'));
    return v >= 280 && v <= 720 ? v : 360;
  });
  function persistInspectorWidth(w: number) {
    setInspectorWidth(w);
    try { localStorage.setItem('flow.inspectorWidth', String(w)); } catch { /* ignore */ }
  }
  // Draggable results-panel height (vertical resize of the bottom panel).
  const [resultsHeight, setResultsHeight] = useState<number>(() => {
    if (typeof window === 'undefined') return 300;
    const v = Number(localStorage.getItem('flow.resultsHeight'));
    return v >= 120 && v <= 700 ? v : 300;
  });
  function startResizeResults(e: React.MouseEvent) {
    e.preventDefault();
    const startY = e.clientY;
    const startH = resultsHeight;
    const onMove = (ev: MouseEvent) => {
      const h = Math.min(700, Math.max(120, startH + (startY - ev.clientY)));
      setResultsHeight(h);
      try { localStorage.setItem('flow.resultsHeight', String(h)); } catch { /* ignore */ }
    };
    const onUp = () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      document.body.style.cursor = ''; document.body.style.userSelect = '';
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    document.body.style.cursor = 'row-resize'; document.body.style.userSelect = 'none';
  }
  // Params promoted to "fill at replay time" — keys are `${nodeId}::${param}`.
  const [runtime, setRuntime] = useState<Set<string>>(() => new Set((tpl.graph?.runtime ?? []).map((r) => rtKey(r.nodeId, r.param))));
  // When a replay needs runtime inputs, we collect them in this form first.
  const [runForm, setRunForm] = useState<Record<string, string> | null>(null);
  // Preview of the data flowing on a clicked edge (the output of its source node).
  const [linePreview, setLinePreview] = useState<
    { dsId: number; label: string; total: number; columns: string[]; rows: Record<string, unknown>[]; loading: boolean } | null
  >(null);
  const [previewMode, setPreviewMode] = useState<'table' | 'chart'>('table');
  // Columns available at the SELECTED node's INPUT (= its upstream step's output
  // after a replay). null → fall back to the original dataset's columns. This is
  // what lets you pick e.g. `voltage_v_gauss` on the step AFTER gaussian_filter
  // instead of the original `voltage_v` that won't exist there.
  const [inputCols, setInputCols] = useState<string[] | null>(null);
  // datasetId → its columns, fetched after a replay; used to flag step nodes
  // whose column params reference columns not in their actual input.
  const [outCols, setOutCols] = useState<Map<number, string[]>>(new Map());

  useEffect(() => { if (datasetIds.length === 0 && datasets[0]) setDatasetIds([datasets[0].id]); }, [datasets, datasetIds]);
  // Reset everything when switching to a different template.
  useEffect(() => {
    setNodes(init.nodes); setEdges(init.edges); setName(tpl.name);
    setDirty(false); setSelId(null); setMultiRes([]); setActiveIdx(0); setBatchView('tabs'); setErr(''); setLinePreview(null);
    setRuntime(new Set((tpl.graph?.runtime ?? []).map((r) => rtKey(r.nodeId, r.param)))); setRunForm(null);
  }, [tpl.id]); // eslint-disable-line react-hooks/exhaustive-deps

  function toggleRuntime(nodeId: string, param: string) {
    setRuntime((s) => { const n = new Set(s); const k = rtKey(nodeId, param); if (n.has(k)) n.delete(k); else n.add(k); return n; });
    markDirty();
  }
  // Runtime params that still point at a live node+param (prunes deleted ones).
  const runtimeList = useMemo(() => {
    const byId = new Map(nodes.map((n) => [n.id, n] as const));
    return [...runtime].map((k) => { const [nodeId, param] = k.split('::'); return { key: k, nodeId, param, node: byId.get(nodeId) }; })
      .filter((r) => r.node && r.node.data.kind === 'step');
  }, [runtime, nodes]);

  const markDirty = () => setDirty(true);

  // Replay is a linear pipeline (each step on its predecessor's output), so the
  // canvas is constrained to a single chain: one out-edge per source, one
  // in-edge per target. A new connection replaces any conflicting edge — this
  // keeps canvas == execution (no silently-flattened branches).
  const onConnect = useCallback((c: Connection) => {
    setEdges((eds) => addEdge(
      { ...c, markerEnd: { type: MarkerType.ArrowClosed } },
      eds.filter((e) => e.source !== c.source && e.target !== c.target),
    ));
    markDirty();
  }, [setEdges]);

  const selNode = nodes.find((n) => n.id === selId) ?? null;
  // The currently-viewed batch result + its dataset drive the result panel,
  // edge labels and stale-column checks.
  const res = multiRes[activeIdx]?.res ?? null;
  const activeDsId = datasetIds[activeIdx] ?? datasetIds[0] ?? null;
  const runDs = datasets.find((d) => d.id === activeDsId) ?? null;
  const cols = (runDs?.schema?.columns ?? []).map((c) => c.name);

  /** Add an algorithm as a step node. `position` (canvas coords) is set when
   *  dropped from the palette; otherwise it's placed below the lowest node.
   *  Either way it auto-connects from the current topo tail so it joins the
   *  pipeline immediately (re-wire freely afterward). */
  function addStep(slug: string, position?: { x: number; y: number }, fromId?: string) {
    const a = bySlug.get(slug);
    const id = `n_${Date.now().toString(36)}`;
    const tailId = topoOrderIds(nodes, edges).slice(-1)[0];
    const srcId = fromId ?? tailId ?? (nodes.find((n) => n.data.kind === 'input')?.id ?? INPUT_ID);
    const fromNode = nodes.find((n) => n.id === srcId);
    const pos = position ?? (fromNode ? { x: fromNode.position.x + NODE_W + NODE_GAP, y: fromNode.position.y } : { x: 40, y: 120 });
    const newNode: FlowNode = {
      id, type: 'step', position: pos,
      data: { kind: 'step', slug, params: {}, label: ALGO_ZH[slug]?.name ?? a?.name ?? slug, category: a?.category },
    };
    setNodes((ns) => [...ns, newNode]);
    // Splice in right after srcId: srcId → new → (srcId's old successor). For the
    // tail this is a plain append; either way the chain stays linear & unbroken.
    setEdges((es) => {
      const succ = es.filter((e) => e.source === srcId).map((e) => e.target);
      const kept = es.filter((e) => e.source !== srcId);
      kept.push({ id: `e_${srcId}_${id}`, source: srcId, target: id, markerEnd: { type: MarkerType.ArrowClosed } });
      for (const t of succ) kept.push({ id: `e_${id}_${t}`, source: id, target: t, markerEnd: { type: MarkerType.ArrowClosed } });
      return kept;
    });
    setSelId(id);
    markDirty();
  }

  function onDragOver(e: DragEvent) { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; }
  function onDrop(e: DragEvent) {
    e.preventDefault();
    const slug = e.dataTransfer.getData(DND_MIME);
    if (!slug) return;
    addStep(slug, rf.screenToFlowPosition({ x: e.clientX, y: e.clientY }));
  }

  // Coze-style: drag a connection out of a node's port and release it on empty
  // canvas → pop an algorithm menu and splice the chosen step in after it.
  const connectFrom = useRef<string | null>(null);
  const [quickAdd, setQuickAdd] = useState<{ x: number; y: number; flowPos: { x: number; y: number }; fromId: string } | null>(null);
  const onConnectStart = useCallback((_: unknown, p: { nodeId: string | null }) => { connectFrom.current = p.nodeId; }, []);
  const onConnectEnd = useCallback((event: MouseEvent | TouchEvent) => {
    const from = connectFrom.current; connectFrom.current = null;
    const tgt = event.target as HTMLElement | null;
    if (!from || !tgt?.classList?.contains('react-flow__pane')) return; // released on a node/handle → normal connect
    if (!('clientX' in event)) return;
    setQuickAdd({ x: event.clientX, y: event.clientY, flowPos: rf.screenToFlowPosition({ x: event.clientX, y: event.clientY }), fromId: from });
  }, [rf]);

  // After a replay, the data that LEAVES each node (what flows on its outgoing
  // edges): the input node emits the chosen dataset; step i emits its derived
  // dataset. Only meaningful for the current, unedited graph — hidden once dirty.
  const nodeOutput = useMemo(() => {
    const m = new Map<string, { datasetId?: number; rows?: number; label: string }>();
    if (!res || dirty) return m;
    const inputId = nodes.find((n) => n.data.kind === 'input')?.id;
    if (inputId && runDs) m.set(inputId, { datasetId: runDs.id, rows: runDs.rows, label: runDs.name });
    const orderIds = topoOrderIds(nodes, edges);
    for (const s of res.steps) {
      const id = orderIds[s.i];
      if (id) m.set(id, { datasetId: s.dataset_id, rows: s.rows, label: s.label });
    }
    return m;
  }, [res, dirty, nodes, edges, runDs]);

  // Decorate edges that carry data with a row-count label + flow animation.
  const displayEdges = useMemo(() => edges.map((e) => {
    const out = nodeOutput.get(e.source);
    if (out && typeof out.rows === 'number') {
      return {
        ...e, animated: true, label: `${out.rows.toLocaleString()} 行`,
        labelStyle: { fontSize: 10, fill: '#7c3aed', fontWeight: 600 },
        labelBgStyle: { fill: '#f5f3ff' }, labelBgPadding: [4, 2] as [number, number], labelBgBorderRadius: 4,
        style: { stroke: '#a78bfa', strokeWidth: 1.5 },
      };
    }
    return e;
  }), [edges, nodeOutput]);

  // Resolve a step node's INPUT columns (its predecessor's output): original
  // dataset columns if fed by the input node, else the upstream stage's columns.
  const inputColsOf = useCallback((nodeId: string): string[] | null => {
    const predId = edges.find((e) => e.target === nodeId)?.source;
    if (!predId) return null;
    const pred = nodes.find((n) => n.id === predId);
    if (pred?.data.kind === 'input') return cols;
    const dsId = nodeOutput.get(predId)?.datasetId;
    return dsId ? (outCols.get(dsId) ?? null) : null;
  }, [edges, nodes, nodeOutput, outCols, cols]);

  // Decorate step nodes: always flag missing REQUIRED params (so you see it
  // before running); add last-replay status + a "stale columns" flag for the
  // current, unedited graph.
  const displayNodes = useMemo(() => {
    const haveRun = Boolean(res) && !dirty;
    const orderIds = haveRun ? topoOrderIds(nodes, edges) : [];
    const statusById = new Map<string, StepData['status']>();
    if (haveRun) res!.steps.forEach((s) => { const id = orderIds[s.i]; if (id) statusById.set(id, s.status as StepData['status']); });
    return nodes.map((n) => {
      if (n.data.kind !== 'step') return n;
      const schema = bySlug.get(n.data.slug ?? '')?.params_schema || {};
      const p = n.data.params || {};
      const needsParams = Object.entries(schema).some(([k, spec]) => (spec as ParamSpec).required && isEmptyVal(p[k]));
      const inCols = haveRun ? inputColsOf(n.id) : null;
      const stale = inCols != null && inCols.length > 0 && colRefs(p).some((r) => !inCols.includes(r));
      const status = haveRun ? statusById.get(n.id) : n.data.status;
      if (status === n.data.status && stale === Boolean(n.data.stale) && needsParams === Boolean(n.data.needsParams)) return n;
      return { ...n, data: { ...n.data, status, stale, needsParams } };
    });
  }, [nodes, edges, res, dirty, inputColsOf, bySlug]);

  // After a replay, fetch the column list of every stage's output dataset so we
  // can flag any step whose column params don't match its actual input.
  useEffect(() => {
    if (!res || dirty) { setOutCols(new Map()); return; }
    const ids = new Set<number>();
    if (runDs) ids.add(runDs.id);
    res.steps.forEach((s) => { if (s.dataset_id) ids.add(s.dataset_id); });
    let cancelled = false;
    Promise.all([...ids].map((id) =>
      api.datasetPreview(id, 1).then((p) => [id, p.columns] as const).catch(() => [id, [] as string[]] as const))
    ).then((pairs) => { if (!cancelled) setOutCols(new Map(pairs)); });
    return () => { cancelled = true; };
  }, [res, dirty, runDs]);

  // When a step is selected, resolve the columns at ITS input: the upstream
  // step's output dataset (known after a replay) — else the original columns.
  useEffect(() => {
    if (!selNode || selNode.data.kind !== 'step') { setInputCols(null); return; }
    const predId = edges.find((e) => e.target === selNode.id)?.source;
    const predNode = predId ? nodes.find((n) => n.id === predId) : undefined;
    if (!predNode || predNode.data.kind === 'input') { setInputCols(null); return; } // input → original cols
    const predDsId = nodeOutput.get(predNode.id)?.datasetId;
    if (!predDsId) { setInputCols(null); return; } // not run yet → original cols (best effort)
    let cancelled = false;
    api.datasetPreview(predDsId, 1)
      .then((p) => { if (!cancelled) setInputCols(p.columns); })
      .catch(() => { if (!cancelled) setInputCols(null); });
    return () => { cancelled = true; };
  }, [selId, nodeOutput, edges, nodes]); // eslint-disable-line react-hooks/exhaustive-deps

  // step.i (backend's index into the saved steps) → that step's params, via the
  // current topo order. Lets the result panel pass params to explain-error/result.
  const paramsByIndex = useMemo(() => {
    const byId = new Map(nodes.map((n) => [n.id, n] as const));
    return topoOrderIds(nodes, edges).map((id) => (byId.get(id)?.data.params ?? {}) as Record<string, unknown>);
  }, [nodes, edges]);

  async function openPreview(dsId: number, label: string, rows?: number) {
    setPreviewMode('table');
    setLinePreview({ dsId, label, total: rows ?? 0, columns: [], rows: [], loading: true });
    try {
      const p = await api.datasetPreview(dsId, 50);
      setLinePreview({ dsId, label, total: p.total, columns: p.columns, rows: p.rows, loading: false });
    } catch { setLinePreview(null); }
  }
  function previewEdge(_: unknown, edge: Edge) {
    const out = nodeOutput.get(edge.source);
    if (out?.datasetId) openPreview(out.datasetId, out.label, out.rows); // no data on this line until a replay
  }

  function deleteNode(id: string) {
    if (id === INPUT_ID) return; // never delete the data entry
    // Bridge predecessors → successors so the pipeline stays connected (the
    // linear replay would thread through them anyway — keep canvas == execution).
    setEdges((es) => {
      const preds = es.filter((e) => e.target === id).map((e) => e.source);
      const succs = es.filter((e) => e.source === id).map((e) => e.target);
      const kept = es.filter((e) => e.source !== id && e.target !== id);
      for (const s of preds) for (const t of succs) {
        if (s !== t && !kept.some((e) => e.source === s && e.target === t)) {
          kept.push({ id: `e_${s}_${t}_b`, source: s, target: t, markerEnd: { type: MarkerType.ArrowClosed } });
        }
      }
      return kept;
    });
    setNodes((ns) => ns.filter((n) => n.id !== id));
    if (selId === id) setSelId(null);
    markDirty();
  }

  // Snap nodes into a clean left→right row in execution order (fixes the messy
  // swooping edges you get after dragging / quick-adding).
  function autoLayout() {
    const inputId = nodes.find((n) => n.data.kind === 'input')?.id;
    const order = [inputId, ...topoOrderIds(nodes, edges)].filter(Boolean) as string[];
    const posById = new Map(order.map((id, i) => [id, { x: 40 + i * (NODE_W + NODE_GAP), y: 140 }]));
    setNodes((ns) => ns.map((n) => posById.has(n.id) ? { ...n, position: posById.get(n.id)! } : n));
    markDirty();
    setTimeout(() => { try { rf.fitView({ maxZoom: 1, padding: 0.2 }); } catch { /* ignore */ } }, 60);
  }

  // Align EVERY step's column params to its current input (skip steps whose
  // input columns aren't known yet, so a not-yet-run downstream step isn't
  // wrongly stripped). Used after switching the input dataset.
  function alignAllToInput() {
    setNodes((ns) => ns.map((n) => {
      if (n.data.kind !== 'step') return n;
      const inCols = inputColsOf(n.id);
      if (inCols == null) return n;
      const schema = bySlug.get(n.data.slug ?? '')?.params_schema || {};
      const p: Record<string, unknown> = { ...(n.data.params || {}) };
      let xVal = '';
      for (const k of Object.keys(schema)) {
        const spec = schema[k] as ParamSpec;
        const kind = paramKind(k, spec);
        if (kind === 'colsingle') {
          let v = p[k] != null && inCols.includes(String(p[k])) ? String(p[k]) : '';
          if (!v && spec.required && inCols.length) v = inCols[0];
          if (k.toLowerCase() === 'x') xVal = v;
          if (v) p[k] = v; else delete p[k];
        } else if (kind === 'colmulti') {
          const arr = (Array.isArray(p[k]) ? (p[k] as unknown[]).map(String) : String(p[k] ?? '').split(',').map((s) => s.trim())).filter(Boolean);
          let kept = arr.filter((c) => inCols.includes(c));
          if (kept.length === 0 && spec.required && inCols.length) kept = inCols.filter((c) => c !== xVal).slice(0, 1);
          if (kept.length) p[k] = kept; else delete p[k];
        }
      }
      return { ...n, data: { ...n.data, params: p } };
    }));
    markDirty();
  }

  function setNodeParam(id: string, key: string, value: unknown) {
    setNodes((ns) => ns.map((n) => {
      if (n.id !== id) return n;
      const params = { ...(n.data.params || {}) };
      if (value === undefined) delete params[key]; else params[key] = value;
      return { ...n, data: { ...n.data, params } };
    }));
    markDirty();
  }

  function applyAISuggested(id: string, p: Record<string, unknown>) {
    setNodes((ns) => ns.map((n) => n.id === id ? { ...n, data: { ...n.data, params: { ...(n.data.params || {}), ...p } } } : n));
    markDirty();
  }

  function buildGraph(): FlowGraph {
    const order = topoOrderIds(nodes, edges);
    return {
      nodes: nodes.map((n) => ({ id: n.id, kind: n.data.kind, slug: n.data.slug, params: n.data.params || {}, label: n.data.label, position: n.position })),
      edges: edges.map((e) => ({ source: e.source, target: e.target })),
      // Stamp stepIndex/slug/label/default so the standalone run page can build the
      // form + per-step overrides without re-deriving the topo order.
      runtime: runtimeList.map((r) => ({
        nodeId: r.nodeId, param: r.param, stepIndex: order.indexOf(r.nodeId),
        slug: r.node!.data.slug, label: r.node!.data.label,
        default: (r.node!.data.params || {})[r.param],
      })),
    };
  }

  async function save() {
    setSaving(true); setErr('');
    try {
      const steps = topoSteps(nodes, edges);
      await api.updateTemplate(tpl.id, { name, steps, graph: buildGraph() });
      setDirty(false); onChanged();
    } catch (e) { setErr((e as Error).message); }
    finally { setSaving(false); }
  }

  // Replay. With runtime params declared, collect them in a form first, then run
  // with per-step overrides; otherwise run straight away.
  async function run() {
    if (datasetIds.length === 0) return;
    if (runtimeList.length > 0) {
      const init: Record<string, string> = {};
      for (const r of runtimeList) init[r.key] = paramToStr((r.node!.data.params || {})[r.param]);
      setRunForm(init);
      return;
    }
    await doRun({});
  }

  // Batch replay: run the flow on EACH selected dataset (same overrides), then
  // show the first; a tab bar lets the user flip between datasets' results.
  async function doRun(overrides: Record<string, Record<string, unknown>>) {
    if (datasetIds.length === 0) return;
    setRunForm(null);
    if (dirty) await save();
    setBusy(true); setErr(''); setMultiRes([]); setActiveIdx(0); setLinePreview(null);
    try {
      const out: { dsId: number; name: string; res: TemplateRunResult }[] = [];
      for (const id of datasetIds) {
        const r = await api.runTemplate(tpl.id, id, true, overrides);
        out.push({ dsId: id, name: datasets.find((d) => d.id === id)?.name ?? String(id), res: r });
        setMultiRes([...out]); // progressive: show each as it finishes
      }
    } catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  }

  // Map the filled runtime form → per-step-index param overrides, then run.
  async function submitRunForm(values: Record<string, string>) {
    const orderIds = topoOrderIds(nodes, edges);
    const overrides: Record<string, Record<string, unknown>> = {};
    for (const r of runtimeList) {
      const stepIdx = orderIds.indexOf(r.nodeId);
      if (stepIdx < 0) continue;
      const spec = bySlug.get(r.node!.data.slug ?? '')?.params_schema?.[r.param];
      const coerced = spec ? coerceParam(spec, values[r.key] ?? '') : (values[r.key] || undefined);
      (overrides[String(stepIdx)] ??= {})[r.param] = coerced;
    }
    await doRun(overrides);
  }

  async function del() {
    if (!confirm(`删除流程模板「${tpl.name}」?`)) return;
    try { await api.deleteTemplate(tpl.id); onDeleted(); } catch (e) { setErr((e as Error).message); }
  }

  const stepCount = nodes.filter((n) => n.data.kind === 'step').length;
  const stepCols = res?.final?.preview?.[0] ? Object.keys(res.final.preview[0]) : [];

  const inputCtxVal = useMemo(() => ({
    datasets, datasetIds,
    toggleDataset: (id: number) => setDatasetIds((arr) => arr.includes(id) ? arr.filter((x) => x !== id) : [...arr, id]),
    onPreview: (ds: Dataset) => openPreview(ds.id, ds.name, ds.rows),
  }), [datasets, datasetIds]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <InputCtx.Provider value={inputCtxVal}>
    <div className="flex h-full relative">
      {/* Left: draggable algorithm palette */}
      {paletteOpen && <AlgoPalette algos={algos} onPick={(slug) => addStep(slug)} onClose={() => setPaletteOpen(false)} />}

      <div className="flex-1 min-w-0 flex flex-col">
        {/* Toolbar */}
        <div className="border-b border-ink-200 bg-white px-3 py-2 flex items-center gap-2 flex-wrap">
          {!paletteOpen && (
            <button onClick={() => setPaletteOpen(true)} title="打开算法库" className="text-xs px-2 py-1 rounded-lg ring-1 ring-dashed ring-brand-300 text-brand-600 hover:bg-brand-50 flex items-center gap-1 shrink-0"><Layers className="w-3.5 h-3.5" /> 算法库</button>
          )}
          <input value={name} onChange={(e) => { setName(e.target.value); markDirty(); }}
            className="font-medium bg-transparent border-b border-transparent hover:border-ink-200 focus:border-brand-400 focus:outline-none py-0.5 min-w-[120px] flex-1" />
          <span className="text-xs text-ink-400 shrink-0">{stepCount} 步</span>
          {nodes.length > 1 && <button onClick={autoLayout} title="按执行顺序左→右排好" className="text-xs px-2 py-1 rounded-lg ring-1 ring-ink-200 text-ink-600 hover:bg-ink-50 flex items-center gap-1 shrink-0"><Layers className="w-3.5 h-3.5" /> 整理布局</button>}
          {stepCount > 0 && <button onClick={alignAllToInput} title="把各步骤的列参数对齐到当前输入(换数据后用)" className="text-xs px-2 py-1 rounded-lg ring-1 ring-amber-200 text-amber-700 hover:bg-amber-50 flex items-center gap-1 shrink-0"><Sparkles className="w-3.5 h-3.5" /> 对齐列参数</button>}
          {dirty && <button onClick={save} disabled={saving} className="text-xs px-2.5 py-1 rounded-lg bg-brand-600 text-white hover:bg-brand-700 flex items-center gap-1 shrink-0">{saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}保存</button>}
          <button onClick={del} title="删除模板" className="text-ink-400 hover:text-red-600 p-1 shrink-0"><Trash2 className="w-4 h-4" /></button>
        </div>

        {/* Canvas */}
        <div className="flex-1 min-h-[320px] bg-ink-50/40 relative" onDrop={onDrop} onDragOver={onDragOver}>
          <ReactFlow
            nodes={displayNodes}
            edges={displayEdges}
            onNodesChange={(c) => { onNodesChange(c); if (c.some((x) => x.type === 'position' && x.dragging === false)) markDirty(); }}
            onEdgesChange={(c) => { onEdgesChange(c); if (c.some((x) => x.type === 'remove')) markDirty(); }}
            onConnect={onConnect}
            onConnectStart={onConnectStart}
            onConnectEnd={onConnectEnd}
            onNodeClick={(_, n) => {
              if ((n.data as StepData).kind === 'input') { if (runDs) openPreview(runDs.id, runDs.name, runDs.rows); }
              else setSelId(n.id);
            }}
            onEdgeClick={previewEdge}
            onPaneClick={() => { setSelId(null); setLinePreview(null); }}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ maxZoom: 1, padding: 0.22 }}
            minZoom={0.2}
            defaultEdgeOptions={{ type: 'default', markerEnd: { type: MarkerType.ArrowClosed, color: '#94a3b8' }, style: { stroke: '#cbd5e1', strokeWidth: 1.5 } }}
            proOptions={{ hideAttribution: true }}
          >
            <Background gap={22} size={1} color="#e4e4e7" className="!bg-transparent" />
            <Controls showInteractive={false} className="!shadow-sm !ring-1 !ring-ink-200 !rounded-lg overflow-hidden" />
            {nodes.length > 6 && <MiniMap pannable zoomable className="!bg-white !ring-1 !ring-ink-200 !rounded-lg" />}
          </ReactFlow>

          {res && !dirty && !linePreview && (
            <div className="absolute bottom-2 left-1/2 -translate-x-1/2 z-10 text-[11px] text-violet-700 bg-violet-50/90 ring-1 ring-violet-200 rounded-full px-3 py-1 pointer-events-none">
              点连线看流过的数据 · 点「数据入口」看原始数据
            </div>
          )}

          {/* Quick-add menu: pick the step to splice after the dragged-from node */}
          {quickAdd && (
            <>
              <div className="fixed inset-0 z-20" onClick={() => setQuickAdd(null)} />
              <div className="fixed z-30 w-52 max-h-72 overflow-y-auto scroll-hide bg-white rounded-xl ring-1 ring-ink-200 shadow-lg p-1"
                style={{ left: Math.min(quickAdd.x, window.innerWidth - 220), top: Math.min(quickAdd.y, window.innerHeight - 300) }}>
                <div className="px-2 py-1.5 text-[10px] font-medium text-ink-400 uppercase tracking-wide">接一步</div>
                {algos.filter((a) => a.returns === 'dataframe').map((a) => (
                  <button key={a.slug + (a.id ?? '')} onClick={() => { addStep(a.slug, quickAdd.flowPos, quickAdd.fromId); setQuickAdd(null); }}
                    className="w-full text-left flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-brand-50/60">
                    <span className={`grid place-items-center w-5 h-5 rounded-md shrink-0 ${catTone(a.category)}`}><Wrench className="w-3 h-3" /></span>
                    <span className="text-xs font-medium text-ink-800 truncate">{ALGO_ZH[a.slug]?.name ?? a.name}</span>
                  </button>
                ))}
              </div>
            </>
          )}

          {/* Data flowing on the clicked edge */}
          {linePreview && (
            <div className="absolute top-2 right-2 z-10 w-[min(460px,72%)] max-h-[82%] bg-white rounded-xl ring-1 ring-violet-200 shadow-lg flex flex-col">
              <div className="flex items-center gap-2 px-3 py-2 border-b border-ink-200">
                <Table2 className="w-3.5 h-3.5 text-violet-600 shrink-0" />
                <span className="text-xs font-medium truncate flex-1">{linePreview.label}</span>
                <span className="text-[11px] text-ink-400 shrink-0">{linePreview.total.toLocaleString()} 行</span>
                <div className="inline-flex rounded-md ring-1 ring-ink-200 overflow-hidden text-[11px] shrink-0">
                  <button onClick={() => setPreviewMode('table')} className={`px-1.5 py-0.5 flex items-center gap-1 ${previewMode === 'table' ? 'bg-brand-600 text-white' : 'text-ink-500 hover:bg-ink-50'}`}><Table2 className="w-3 h-3" /> 表</button>
                  <button onClick={() => setPreviewMode('chart')} className={`px-1.5 py-0.5 flex items-center gap-1 ${previewMode === 'chart' ? 'bg-brand-600 text-white' : 'text-ink-500 hover:bg-ink-50'}`}><BarChart3 className="w-3 h-3" /> 图</button>
                </div>
                <button onClick={() => setLinePreview(null)} className="text-ink-400 hover:text-ink-700 shrink-0"><X className="w-3.5 h-3.5" /></button>
              </div>
              <div className="overflow-auto scroll-hide">
                {previewMode === 'chart' ? (
                  <div className="p-2"><DatasetChart datasetId={linePreview.dsId} name={linePreview.label} height={300} /></div>
                ) : linePreview.loading ? (
                  <div className="p-5 text-center text-xs text-ink-400"><Loader2 className="w-4 h-4 animate-spin inline-block" /> 加载中…</div>
                ) : (
                  <table className="text-xs min-w-full">
                    <thead className="bg-ink-50 text-ink-500 sticky top-0">
                      <tr>{linePreview.columns.map((c) => <th key={c} className="text-left py-1.5 px-2 font-medium whitespace-nowrap">{c}</th>)}</tr>
                    </thead>
                    <tbody>
                      {linePreview.rows.map((row, i) => (
                        <tr key={i} className="border-t border-ink-100">
                          {linePreview.columns.map((c) => <td key={c} className="py-1 px-2 font-mono whitespace-nowrap">{cellOf(row[c])}</td>)}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Run bar — the dataset is chosen on the 「输入」 node now. */}
        <div className="border-t border-ink-200 bg-white px-3 py-2.5 flex items-center gap-2.5 flex-wrap">
          <div className="flex-1 min-w-[160px] text-[11px] text-ink-500 flex items-center gap-1.5">
            <Database className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
            {datasetIds.length > 1 ? (
              <span>输入:<b className="text-ink-700 font-medium">{datasetIds.length} 个数据集</b> —— 逐个批量执行(主:{runDs?.name}）</span>
            ) : runDs ? (
              <span>输入:<b className="text-ink-700 font-medium">{runDs.name}</b>（{runDs.rows.toLocaleString()} × {runDs.columns}）—— 在「输入」节点可改/加</span>
            ) : (
              <span className="text-amber-600">请在画布左侧的「输入」节点选择数据集</span>
            )}
          </div>
          {runtimeList.length > 0 && (
            <span className="text-[10.5px] text-amber-700 bg-amber-50 ring-1 ring-amber-100 rounded-full px-2 py-0.5 shrink-0" title="执行时会让你填这些参数">🖊 {runtimeList.length} 个执行参数</span>
          )}
          <button onClick={run} disabled={busy || datasetIds.length === 0 || stepCount === 0}
            className="px-4 py-2 rounded-xl bg-brand-600 text-white font-medium hover:bg-brand-700 transition-colors flex items-center gap-2 disabled:opacity-50 shrink-0">
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />} {runtimeList.length > 0 ? '填参数并执行' : dirty ? '保存并执行' : datasetIds.length > 1 ? `执行 ×${datasetIds.length}` : '执行'}
          </button>
        </div>

        {(err || res) && (
          <div className="border-t border-ink-200 bg-white flex flex-col" style={{ height: resultsHeight }}>
            {/* visible drag handle — up/down to resize the results panel height */}
            <div onMouseDown={startResizeResults} title="上下拖动调整结果区高度"
              className="group h-3 shrink-0 cursor-row-resize flex items-center justify-center hover:bg-brand-50/70">
              <div className="w-12 h-1 rounded-full bg-ink-300 group-hover:bg-brand-400 transition-colors" />
            </div>
            <div className="px-3 pb-2.5 overflow-y-auto scroll-hide space-y-2.5 flex-1 min-h-0">
            {err && (
              <div className="text-sm text-red-700 bg-red-50 ring-1 ring-red-100 rounded-lg px-3 py-2 flex items-start gap-2">
                <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" /><span className="whitespace-pre-wrap">{err}</span>
              </div>
            )}
            {/* Batch: switch between 逐个 (a tab per dataset) and 全部出图 (a chart
                grid — one figure per file, all visible at once). */}
            {multiRes.length > 1 && (
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-[11px] text-ink-500 shrink-0">批量结果 · {multiRes.length} 个文件</span>
                <div className="inline-flex rounded-md ring-1 ring-ink-200 overflow-hidden text-[11px] shrink-0">
                  <button onClick={() => setBatchView('tabs')}
                    className={`px-2 py-0.5 flex items-center gap-1 ${batchView === 'tabs' ? 'bg-brand-600 text-white' : 'text-ink-500 hover:bg-ink-50'}`}>
                    <Layers className="w-3 h-3" /> 逐个
                  </button>
                  <button onClick={() => setBatchView('grid')}
                    className={`px-2 py-0.5 flex items-center gap-1 ${batchView === 'grid' ? 'bg-brand-600 text-white' : 'text-ink-500 hover:bg-ink-50'}`}>
                    <BarChart3 className="w-3 h-3" /> 全部出图
                  </button>
                </div>
                {busy && <span className="text-[10.5px] text-ink-400 flex items-center gap-1 shrink-0"><Loader2 className="w-3 h-3 animate-spin" /> 跑批中…</span>}
              </div>
            )}

            {/* 全部出图: a responsive grid, one chart per file's final output. */}
            {multiRes.length > 1 && batchView === 'grid' ? (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                {multiRes.map((m) => {
                  const dsId = finalDatasetId(m.res);
                  const bad = m.res.steps.some((s) => s.status === 'error');
                  return (
                    <div key={m.dsId} className="rounded-lg ring-1 ring-ink-200 bg-white p-2">
                      <div className="text-[11px] font-medium text-ink-700 mb-1.5 flex items-center gap-1.5">
                        {bad ? <AlertTriangle className="w-3 h-3 text-red-400 shrink-0" /> : <CheckCircle2 className="w-3 h-3 text-emerald-400 shrink-0" />}
                        <span className="truncate">{m.name}</span>
                      </div>
                      {dsId != null ? (
                        <DatasetChart datasetId={dsId} name={m.name} height={240} maxPoints={1000} />
                      ) : (
                        <div className="py-8 text-center text-[11px] text-ink-400 flex items-center justify-center gap-1.5">
                          <BarChart3 className="w-4 h-4" /> 这个流程没产出可画的表格
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : (
              <>
                {multiRes.length > 1 && (
                  <div className="flex flex-wrap gap-1">
                    {multiRes.map((m, i) => {
                      const bad = m.res.steps.some((s) => s.status === 'error');
                      return (
                        <button key={m.dsId} onClick={() => setActiveIdx(i)}
                          className={`text-[11px] px-2 py-0.5 rounded-md ring-1 flex items-center gap-1 ${i === activeIdx ? 'bg-brand-600 text-white ring-transparent' : 'bg-white text-ink-600 ring-ink-200 hover:bg-ink-50'}`}>
                          {bad ? <AlertTriangle className="w-3 h-3 text-red-400" /> : <CheckCircle2 className="w-3 h-3 text-emerald-400" />}
                          <span className="truncate max-w-[120px]">{m.name}</span>
                        </button>
                      );
                    })}
                  </div>
                )}
                {res && <RunResults res={res} datasetId={activeDsId} paramsByIndex={paramsByIndex} stepCols={stepCols}
                  runDs={runDs} onPreview={(id, label, rows) => openPreview(id, label, rows)} />}
              </>
            )}
            </div>
          </div>
        )}
      </div>

      {/* Inspector — mirrors the algorithm-library config experience */}
      {selNode && selNode.data.kind === 'step' && (
        <NodeInspector
          key={selNode.id}
          node={selNode}
          algo={bySlug.get(selNode.data.slug ?? '')}
          cols={inputCols ?? cols}
          colsFromUpstream={inputCols != null}
          datasetId={activeDsId}
          width={inspectorWidth}
          onWidthChange={persistInspectorWidth}
          runtimeParams={runtimeList.filter((r) => r.nodeId === selNode.id).map((r) => r.param)}
          onToggleRuntime={(param) => toggleRuntime(selNode.id, param)}
          onParam={(k, v) => setNodeParam(selNode.id, k, v)}
          onApply={(p) => applyAISuggested(selNode.id, p)}
          onClose={() => setSelId(null)}
          onDelete={() => deleteNode(selNode.id)}
        />
      )}

      {/* Replay-time parameter form (the template's "fill these to run" inputs) */}
      {runForm && (
        <div className="fixed inset-0 z-40 bg-black/30 grid place-items-center p-4" onClick={() => setRunForm(null)}>
          <div className="w-[440px] max-w-full bg-white rounded-xl ring-1 ring-ink-200 shadow-xl flex flex-col max-h-[86vh]" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-2 px-4 py-3 border-b border-ink-200">
              <Play className="w-4 h-4 text-brand-600" />
              <div className="font-semibold text-sm flex-1">本次运行参数</div>
              <button onClick={() => setRunForm(null)} className="text-ink-400 hover:text-ink-700"><X className="w-4 h-4" /></button>
            </div>
            <div className="px-4 py-3 text-[11px] text-ink-500">填好这几个参数即可在 <b>{runDs?.name ?? '所选数据集'}</b> 上运行这套流程(默认值已填,可改)。</div>
            <div className="px-4 pb-2 space-y-2.5 overflow-y-auto scroll-hide">
              {runtimeList.map((r) => {
                const spec = bySlug.get(r.node!.data.slug ?? '')?.params_schema?.[r.param];
                return (
                  <div key={r.key} className="rounded-lg ring-1 ring-ink-100 bg-ink-50/40 p-2.5">
                    <div className="text-[11px] text-ink-500 mb-1.5">{ALGO_ZH[r.node!.data.slug ?? '']?.name ?? r.node!.data.label} · <span className="font-mono text-ink-400">{r.param}</span></div>
                    {spec ? (
                      <ParamField name={r.param} spec={spec} cols={cols} value={runForm[r.key] ?? ''}
                        onChange={(v) => setRunForm((f) => ({ ...(f || {}), [r.key]: v }))} />
                    ) : (
                      <input value={runForm[r.key] ?? ''} onChange={(e) => setRunForm((f) => ({ ...(f || {}), [r.key]: e.target.value }))}
                        className="w-full border border-ink-200 rounded-lg px-2 py-1.5 bg-white text-sm font-mono" />
                    )}
                  </div>
                );
              })}
            </div>
            <div className="flex justify-end gap-2 px-4 py-3 border-t border-ink-200">
              <button onClick={() => setRunForm(null)} className="text-xs px-3 py-1.5 rounded-lg ring-1 ring-ink-200 text-ink-600 hover:bg-ink-50">取消</button>
              <button onClick={() => submitRunForm(runForm)} className="text-xs px-3 py-1.5 rounded-lg bg-brand-600 text-white hover:bg-brand-700 flex items-center gap-1.5"><Play className="w-3.5 h-3.5" /> 运行</button>
            </div>
          </div>
        </div>
      )}
    </div>
    </InputCtx.Provider>
  );
}

/** Selected-node settings panel. Mirrors the algorithm-library RunPanel: shows
 *  the algorithm's metadata + description, the same natural-language param
 *  assist (with its note + per-param explanations surfaced as hints), and the
 *  same schema-driven ParamField inputs — so configuring a step in the flow
 *  feels identical to configuring that algorithm standalone. */
function NodeInspector({ node, algo, cols, colsFromUpstream, datasetId, width, onWidthChange, runtimeParams, onToggleRuntime, onParam, onApply, onClose, onDelete }: {
  node: FlowNode; algo?: Algorithm; cols: string[]; colsFromUpstream?: boolean; datasetId: number | null;
  width: number; onWidthChange: (w: number) => void;
  runtimeParams: string[]; onToggleRuntime: (param: string) => void;
  onParam: (k: string, v: unknown) => void; onApply: (p: Record<string, unknown>) => void;
  onClose: () => void; onDelete: () => void;
}) {
  // Drag the left edge to resize. Panel is on the right, so dragging left widens.
  function startResize(e: React.MouseEvent) {
    e.preventDefault();
    const startX = e.clientX;
    const startW = width;
    const onMove = (ev: MouseEvent) => onWidthChange(Math.min(720, Math.max(280, startW + (startX - ev.clientX))));
    const onUp = () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      document.body.style.cursor = ''; document.body.style.userSelect = '';
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    document.body.style.cursor = 'col-resize'; document.body.style.userSelect = 'none';
  }
  const schema = algo?.params_schema || {};
  const keys = Object.keys(schema);
  const slug = node.data.slug ?? '';
  const missingRequired = keys.filter((k) => (schema[k] as ParamSpec).required && isEmptyVal((node.data.params || {})[k]));
  const colVals = (k: string): string[] => {
    const raw = (node.data.params || {})[k];
    return (Array.isArray(raw) ? raw.map(String) : String(raw ?? '').split(',')).map((s) => s.trim()).filter(Boolean);
  };
  const hasStaleCols = keys.some((k) => {
    const kind = paramKind(k, schema[k]);
    if (kind === 'colmulti') return colVals(k).some((c) => !cols.includes(c));
    if (kind === 'colsingle') { const v = (node.data.params || {})[k]; return v != null && v !== '' && !cols.includes(String(v)); }
    return false;
  });
  // One-click: drop column refs not in the current input, and fill required ones
  // with sensible defaults from the current data (after switching datasets).
  function alignToInput() {
    let xVal = '';
    for (const k of keys) {
      const spec = schema[k] as ParamSpec;
      const kind = paramKind(k, spec);
      if (kind === 'colsingle') {
        const cur = (node.data.params || {})[k];
        let v = cur != null && cols.includes(String(cur)) ? String(cur) : '';
        if (!v && spec.required && cols.length) v = cols[0];
        if (k.toLowerCase() === 'x') xVal = v;
        onParam(k, v || undefined);
      } else if (kind === 'colmulti') {
        let kept = colVals(k).filter((c) => cols.includes(c));
        if (kept.length === 0 && spec.required && cols.length) kept = cols.filter((c) => c !== xVal).slice(0, 1);
        onParam(k, kept.length ? kept : undefined);
      }
    }
  }
  const [intent, setIntent] = useState('');
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  const [explanations, setExplanations] = useState<Record<string, string>>({});

  async function suggest() {
    if (busy) return;
    setBusy(true);
    try {
      const s = await api.suggestParams(slug, datasetId ?? undefined, intent.trim() || undefined);
      const applied: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(s.params || {})) if (k in schema) applied[k] = v;
      onApply(applied);
      setExplanations(s.explanations || {});
      setNote(s.note || '');
      setIntent('');
    } catch { /* ignore */ }
    finally { setBusy(false); }
  }

  return (
    <>
    {/* mobile-only: dim backdrop so the inspector reads as an overlay (tap to close) */}
    <div className="md:hidden absolute inset-0 z-20 bg-black/20" onClick={onClose} />
    <div className="shrink-0 border-l border-ink-200 bg-white flex flex-col md:relative max-md:absolute max-md:inset-y-0 max-md:right-0 max-md:z-30 max-md:!w-[90%] max-md:max-w-[360px] max-md:shadow-2xl" style={{ width }}>
      {/* drag handle on the left edge */}
      <div onMouseDown={startResize} title="拖动调整宽度"
        className="absolute left-0 top-0 bottom-0 w-1.5 -ml-0.5 cursor-col-resize hover:bg-brand-300/60 active:bg-brand-400/70 z-10" />
      <div className="px-3 py-2.5 border-b border-ink-200 flex items-center gap-2.5">
        <span className="grid place-items-center w-8 h-8 rounded-lg bg-brand-50 text-brand-600 shrink-0"><Wrench className="w-4 h-4" /></span>
        <div className="min-w-0 flex-1">
          <div className="font-semibold text-sm text-ink-900 truncate leading-tight">{algo ? dispName(algo) : node.data.label}</div>
          <div className="text-[10.5px] text-ink-400 font-mono truncate">{slug || '—'}</div>
        </div>
        <button onClick={onClose} className="text-ink-400 hover:text-ink-700 shrink-0"><X className="w-4 h-4" /></button>
      </div>

      <div className="flex-1 overflow-y-auto scroll-hide p-3 space-y-3">
        {algo ? (
          <div className="space-y-2">
            <div className="flex flex-wrap gap-1">
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-ink-100 text-ink-600">{catZh(algo.category)}</span>
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-ink-100 text-ink-600">返回 {RETURNS_ZH[algo.returns] ?? algo.returns}</span>
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-ink-100 text-ink-600">{SOURCE_ZH[algo.source] ?? algo.source}</span>
            </div>
            <p className="text-xs text-ink-500 leading-relaxed">{dispDesc(algo)}</p>
          </div>
        ) : (
          <div className="text-xs text-amber-700 bg-amber-50 ring-1 ring-amber-100 rounded-lg px-2.5 py-2">
            算法「{slug}」不在当前库中(可能已删除)。仍可调整已保存的参数。
          </div>
        )}

        {/* Natural-language param assist — identical to the library panel. */}
        <div className="rounded-lg bg-brand-50/60 ring-1 ring-brand-100 p-2.5">
          <div className="flex items-center gap-1.5 text-[11px] text-brand-700 font-medium mb-1.5">
            <Sparkles className="w-3.5 h-3.5" /> 用一句话调这步,AI 帮你填参数
          </div>
          <div className="flex gap-1.5">
            <input value={intent} onChange={(e) => setIntent(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') suggest(); }}
              placeholder={algo ? dispExample(algo) : '如:窗口大一点'}
              className="flex-1 border border-ink-200 rounded-lg px-2 py-1.5 bg-white text-xs min-w-0 focus:outline-none focus:border-brand-400" />
            <button onClick={suggest} disabled={busy} className="text-xs px-2.5 py-1.5 rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50 flex items-center gap-1 shrink-0">
              {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />} 推荐
            </button>
          </div>
          {note && <div className="text-[11px] text-ink-600 mt-2 leading-snug">{note}</div>}
        </div>

        <div className="space-y-2.5">
          <div className="flex items-center gap-1.5">
            <div className="text-[11px] font-medium text-ink-600">参数</div>
            {colsFromUpstream && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-violet-50 text-violet-600 ring-1 ring-violet-100" title="列选项来自上一步的输出,而不是原始数据集">列=上一步输出</span>
            )}
          </div>
          {(missingRequired.length > 0 || hasStaleCols) && (
            <div className="rounded-lg ring-1 ring-amber-200 bg-amber-50 px-2 py-1.5 space-y-1.5">
              <div className="text-[11px] text-amber-700">
                {hasStaleCols && <span>有列参数不在当前输入数据中(红色)。</span>}
                {missingRequired.length > 0 && <span> 缺必填:<span className="font-mono">{missingRequired.join(', ')}</span>。</span>}
              </div>
              <button onClick={alignToInput}
                className="text-[11px] px-2 py-1 rounded-md bg-amber-500 text-white hover:bg-amber-600 flex items-center gap-1">
                <Sparkles className="w-3 h-3" /> 一键对齐到当前输入列
              </button>
            </div>
          )}
          {keys.length === 0 ? (
            <div className="text-xs text-ink-400">该算法无可调参数。</div>
          ) : keys.map((k) => {
            const isRt = runtimeParams.includes(k);
            return (
              <div key={k} className={isRt ? 'rounded-lg ring-1 ring-amber-200 bg-amber-50/40 p-2 -mx-0.5' : ''}>
                <ParamField name={k} spec={schema[k]} cols={cols}
                  value={paramToStr((node.data.params || {})[k])} aiHint={explanations[k]}
                  onChange={(v) => onParam(k, coerceParam(schema[k], v))} />
                <button type="button" onClick={() => onToggleRuntime(k)}
                  title="勾选后,执行时会让用户填这个参数(模版可复用,不必每次进来改)"
                  className={`mt-1 text-[10.5px] inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md ring-1 ${isRt ? 'bg-amber-100 text-amber-700 ring-amber-200' : 'text-ink-400 ring-ink-200 hover:text-amber-600 hover:ring-amber-200'}`}>
                  {isRt ? '✓ 执行时填(此值作默认)' : '🖊 设为执行时填'}
                </button>
              </div>
            );
          })}
        </div>

        <button onClick={onDelete} className="w-full mt-1 text-xs px-2 py-1.5 rounded-lg ring-1 ring-red-200 text-red-600 hover:bg-red-50 flex items-center justify-center gap-1.5">
          <Trash2 className="w-3.5 h-3.5" /> 删除这个步骤
        </button>
      </div>
    </div>
    </>
  );
}

/** Left rail listing pipeline-compatible algorithms (returns a dataframe).
 *  Drag a chip onto the canvas to drop a step at that spot, or click to append
 *  it to the end of the pipeline. */
function AlgoPalette({ algos, onPick, onClose }: {
  algos: Algorithm[]; onPick: (slug: string) => void; onClose: () => void;
}) {
  const [q, setQ] = useState('');
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const toggleGroup = (k: string) => setCollapsed((s) => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n; });
  const searching = q.trim().length > 0;
  const pool = algos.filter((a) => a.returns === 'dataframe');
  const list = pool.filter((a) => matchAlgo(a, q));        // 改法 B (broadened match)
  const groups = searching ? [] : groupByIntent(pool);      // 改法 A + D
  return (
    <>
    {/* mobile-only: dim backdrop so the palette reads as an overlay (tap to close) */}
    <div className="md:hidden absolute inset-0 z-20 bg-black/20" onClick={onClose} />
    <div className="w-[184px] shrink-0 border-r border-ink-200 bg-white flex flex-col max-md:absolute max-md:inset-y-0 max-md:left-0 max-md:z-30 max-md:w-[80%] max-md:max-w-[300px] max-md:shadow-2xl">
      <div className="px-2.5 py-2 border-b border-ink-200">
        <div className="flex items-center gap-1.5 mb-1.5">
          <Layers className="w-3.5 h-3.5 text-brand-600" />
          <span className="text-[11px] font-medium text-ink-600 flex-1">算法库</span>
          <button onClick={onClose} title="收起" className="text-ink-400 hover:text-ink-700"><X className="w-3.5 h-3.5" /></button>
        </div>
        <div className="relative">
          <Search className="w-3 h-3 text-ink-400 absolute left-2 top-1/2 -translate-y-1/2" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜索算法…"
            className="w-full border border-ink-200 rounded-lg pl-6 pr-2 py-1 bg-white text-xs focus:outline-none focus:border-brand-400" />
        </div>
      </div>
      <div className="flex-1 overflow-y-auto scroll-hide p-2 space-y-1">
        {searching ? (
          <>
            {list.map((a) => <PaletteChip key={a.slug + (a.id ?? '')} a={a} onPick={onPick} />)}
            {list.length === 0 && <div className="text-[11px] text-ink-400 text-center py-5">没有匹配的算法</div>}
          </>
        ) : (
          groups.map((g) => {
            const open = !collapsed.has(g.key);
            return (
              <div key={g.key} className="mb-1">
                <button onClick={() => toggleGroup(g.key)}
                  className="w-full flex items-center gap-1 px-1 py-0.5 text-[10px] font-medium text-ink-400 hover:text-ink-600">
                  {open ? <ChevronDown className="w-3 h-3 shrink-0" /> : <ChevronRight className="w-3 h-3 shrink-0" />}
                  <span className="truncate">{g.label}</span>
                  <span className="text-ink-300">({g.items.length})</span>
                </button>
                {open && <div className="space-y-1 mt-0.5">{g.items.map((a) => <PaletteChip key={a.slug + (a.id ?? '')} a={a} onPick={onPick} />)}</div>}
              </div>
            );
          })
        )}
      </div>
      <div className="px-2.5 py-1.5 border-t border-ink-200 text-[10px] text-ink-400 leading-snug">
        拖到画布放置,或点击加到末尾
      </div>
    </div>
    </>
  );
}

/** One draggable algorithm chip in the flow-canvas palette — colored intent icon
 *  + name (single line); the explanation appears in a hover card to the right
 *  (portaled to <body> so the narrow rail doesn't clip it). Matches the library. */
function PaletteChip({ a, onPick }: { a: Algorithm; onPick: (slug: string) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const show = () => {
    const r = ref.current?.getBoundingClientRect();
    if (r) setPos({ top: Math.min(r.top, window.innerHeight - 170), left: r.right + 8 });
  };
  return (
    <>
      <div
        ref={ref}
        draggable
        onDragStart={(e) => { e.dataTransfer.setData(DND_MIME, a.slug); e.dataTransfer.effectAllowed = 'move'; setPos(null); }}
        onClick={() => onPick(a.slug)}
        onMouseEnter={show}
        onMouseLeave={() => setPos(null)}
        className="cursor-grab active:cursor-grabbing rounded-lg ring-1 ring-ink-200 bg-white px-2 py-1.5 hover:ring-brand-300 hover:bg-brand-50/60 transition flex items-center gap-2"
      >
        <span className="shrink-0 text-[14px] leading-none">{intentIcon(algoIntent(a))}</span>
        <span className="text-xs font-medium text-ink-800 truncate flex-1">{dispName(a)}</span>
      </div>
      {pos && createPortal(
        <div
          style={{ position: 'fixed', top: pos.top, left: pos.left, zIndex: 60 }}
          className="w-60 rounded-xl bg-white ring-1 ring-ink-200 shadow-xl p-3 pointer-events-none"
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

/** Replay result panel: per-step status (with a per-failure "explain in plain
 *  language" button), the derived-dataset lineage chain, and the final preview
 *  (with a "interpret result" button). Mirrors the algorithm-library diagnostics
 *  so a flow replay gives the same help as running a step standalone. */
function RunResults({ res, datasetId, paramsByIndex, stepCols, runDs, onPreview }: {
  res: TemplateRunResult; datasetId: number | null;
  paramsByIndex: Record<string, unknown>[]; stepCols: string[];
  runDs?: Dataset | null; onPreview: (id: number, label: string, rows?: number) => void;
}) {
  type Step = TemplateRunResult['steps'][number];
  const [errExplain, setErrExplain] = useState<Record<number, string>>({});
  const [errBusy, setErrBusy] = useState<number | null>(null);
  const [resultExplain, setResultExplain] = useState('');
  const [resBusy, setResBusy] = useState(false);
  const [showChart, setShowChart] = useState(false);
  // Fresh replay → drop last run's explanations.
  useEffect(() => { setErrExplain({}); setResultExplain(''); setShowChart(false); }, [res]);
  // The dataset behind the final output (last non-report stage).
  const finalDsId = finalDatasetId(res);

  async function explainStepErr(s: Step) {
    if (!s.slug) return;
    setErrBusy(s.i);
    try {
      const r = await api.explainError(s.slug, s.error || '', paramsByIndex[s.i] || {}, datasetId ?? undefined);
      setErrExplain((m) => ({ ...m, [s.i]: r.explanation || '(没有得到解释)' }));
    } catch (e) { setErrExplain((m) => ({ ...m, [s.i]: '(解释失败: ' + (e as Error).message + ')' })); }
    finally { setErrBusy(null); }
  }

  const lastOk = [...res.steps].reverse().find((s) => s.status === 'ok' && s.slug);
  async function explainResultFn() {
    if (!lastOk?.slug) return;
    setResBusy(true); setResultExplain('');
    try {
      const r = await api.explainResult(lastOk.slug, paramsByIndex[lastOk.i] || {}, (lastOk.summary || {}) as Record<string, unknown>, datasetId ?? undefined);
      setResultExplain(r.explanation || '(没有得到解读)');
    } catch (e) { setResultExplain('(解读失败: ' + (e as Error).message + ')'); }
    finally { setResBusy(false); }
  }

  return (
    <>
      <div className="rounded-lg ring-1 ring-ink-200 divide-y divide-ink-100 overflow-hidden">
        {res.steps.map((s) => (
          <div key={s.i} className="px-2.5 py-1.5">
            <div className="flex items-center gap-2 text-xs">
              {s.status === 'ok' ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
                : s.status === 'skipped' ? <span className="w-3.5 h-3.5 grid place-items-center text-ink-300 shrink-0">·</span>
                : <AlertTriangle className="w-3.5 h-3.5 text-red-500 shrink-0" />}
              <span className="font-medium text-ink-700 truncate">{s.label}</span>
              {s.report && <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-sky-50 text-sky-600 ring-1 ring-sky-100 shrink-0" title="分析报告 —— 不参与后续数据流">报告</span>}
              {typeof s.rows === 'number' && s.rows > 0 && <span className="text-ink-400 shrink-0 ml-auto">{s.rows.toLocaleString()} 行</span>}
              {s.status === 'error' && (
                <button onClick={() => explainStepErr(s)} disabled={errBusy === s.i}
                  className="ml-auto text-[11px] px-1.5 py-0.5 rounded-md ring-1 ring-red-200 text-red-600 hover:bg-red-50 flex items-center gap-1 disabled:opacity-50 shrink-0">
                  {errBusy === s.i ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />} 用人话解释
                </button>
              )}
            </div>
            {s.error && <div className="mt-1 text-[11px] font-mono text-red-600 break-all">{s.error}</div>}
            {errExplain[s.i] && (
              <div className="mt-1 text-[11px] text-ink-700 bg-red-50/60 ring-1 ring-red-100 rounded-md px-2 py-1.5 whitespace-pre-wrap">💡 {errExplain[s.i]}</div>
            )}
          </div>
        ))}
      </div>

      {res.derived_chain && res.derived_chain.length > 0 && (
        <div className="text-xs bg-violet-50/70 ring-1 ring-violet-100 rounded-lg px-3 py-2.5">
          <div className="text-violet-700 font-medium mb-2 flex items-center gap-1.5"><GitBranch className="w-3.5 h-3.5" /> 每步已存为派生数据集(带血缘)<span className="text-violet-400 font-normal">—— 点任意阶段查看数据</span></div>
          <div className="flex flex-wrap items-center gap-1.5">
            {runDs && <button onClick={() => onPreview(runDs.id, '原始', runDs.rows)} className="px-2 py-0.5 rounded-md bg-white ring-1 ring-ink-200 text-ink-600 hover:bg-ink-50">原始</button>}
            {res.derived_chain.map((d) => (
              <span key={d.id} className="inline-flex items-center gap-1.5">
                <ArrowRight className="w-3 h-3 text-violet-300" />
                <button onClick={() => onPreview(d.id, d.label, d.rows)}
                  className={`px-2 py-0.5 rounded-md bg-white ring-1 font-mono hover:brightness-95 ${d.report ? 'ring-sky-200 text-sky-600' : 'ring-violet-200 text-violet-700'}`}>{d.label}</button>
              </span>
            ))}
          </div>
        </div>
      )}

      {res.final.preview.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-1.5">
            <div className="text-[11px] font-medium text-ink-600">最终输出 · {res.final.rows.toLocaleString()} 行 × {res.final.columns.length} 列</div>
            <div className="ml-auto flex items-center gap-1.5">
              {finalDsId != null && (
                <button onClick={() => setShowChart((v) => !v)}
                  className={`text-[11px] px-1.5 py-0.5 rounded-md ring-1 flex items-center gap-1 ${showChart ? 'bg-brand-600 text-white ring-transparent' : 'ring-brand-200 text-brand-700 hover:bg-brand-50'}`}>
                  <BarChart3 className="w-3 h-3" /> {showChart ? '收起图表' : '可视化'}
                </button>
              )}
              {lastOk && (
                <button onClick={explainResultFn} disabled={resBusy}
                  className="text-[11px] px-1.5 py-0.5 rounded-md ring-1 ring-brand-200 text-brand-700 hover:bg-brand-50 flex items-center gap-1 disabled:opacity-50">
                  {resBusy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />} 解读结果
                </button>
              )}
            </div>
          </div>
          {showChart && finalDsId != null && (
            <div className="mb-2 rounded-lg ring-1 ring-ink-200 p-2"><DatasetChart datasetId={finalDsId} name="最终输出" /></div>
          )}
          {resultExplain && <div className="mb-1.5 text-[11px] text-ink-700 bg-brand-50/60 ring-1 ring-brand-100 rounded-md px-2 py-1.5 whitespace-pre-wrap">💡 {resultExplain}</div>}
          <div className="rounded-lg ring-1 ring-ink-200 overflow-auto max-h-56">
            <table className="text-xs min-w-full">
              <thead className="bg-ink-50 text-ink-500 sticky top-0">
                <tr>{stepCols.map((c) => <th key={c} className="text-left py-2 px-3 font-medium whitespace-nowrap">{c}</th>)}</tr>
              </thead>
              <tbody>
                {res.final.preview.map((row, i) => (
                  <tr key={i} className="border-t border-ink-100 hover:bg-ink-50/60">
                    {stepCols.map((c) => <td key={c} className="py-1.5 px-3 font-mono whitespace-nowrap">{cellOf(row[c])}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}

/** The dataset behind a run's final output: the last non-report derived stage
 *  (a report collapses rows and isn't the real result), else the new_dataset. */
function finalDatasetId(res: TemplateRunResult): number | null {
  return [...(res.derived_chain ?? [])].reverse().find((d) => !d.report)?.id ?? res.new_dataset?.id ?? null;
}

function cellOf(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(4);
  const s = String(v);
  return s.length > 60 ? s.slice(0, 57) + '…' : s;
}

export default function FlowCanvas(props: {
  tpl: FlowTemplate; datasets: Dataset[]; algos: Algorithm[]; onChanged: () => void; onDeleted: () => void;
}) {
  return (
    <ReactFlowProvider>
      <Canvas {...props} />
    </ReactFlowProvider>
  );
}

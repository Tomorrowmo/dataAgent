'use client';

import { useEffect, useState } from 'react';
import { Database, Wrench, BarChart3, Sparkles, List, Info, MessageSquare, CheckCircle2, AlertTriangle, ChevronDown, Save, Loader2, Pencil, X } from 'lucide-react';
import { api, type Algorithm, type Dataset, type FlowTemplate } from '@/lib/api';
import type { Event } from '@/components/WorkbenchPanel';
import dynamic from 'next/dynamic';
const FlowCanvas = dynamic(() => import('@/components/FlowCanvas'), { ssr: false });

/**
 * Dify/Coze-style flow view of a single conversation's tool-call chain.
 *
 * Unlike Dify/Coze — where the user hand-builds a DAG on a canvas — here the
 * graph is *derived from a real agent run*: every tool_call becomes a node
 * (algorithm slug + params + result), bracketed by an input (dataset) node and
 * an answer node. The user's job is to keep the good ones: "保存为模板"
 * serializes the chain into a replayable template.
 *
 * The chain is linear, so a CSS node-chain is a faithful (and dependency-free)
 * rendering. Swap in React Flow later if free-form editing / branching is needed.
 */

type FlowNode = {
  type: 'input' | 'tool' | 'answer';
  action?: string;
  slug?: string;
  params?: Record<string, unknown>;
  title: string;
  subtitle?: string;
  status?: 'ok' | 'error' | 'pending';
  result?: { status?: string; error?: string; kind?: string; summary?: Record<string, unknown> };
};

const ACTION_LABEL: Record<string, string> = {
  run_tool: '运行算法',
  visualize: '可视化',
  visualize_batch: '批量出图',
  generate_viz: '生成图表',
  generate_tool: '生成新算法',
  list_tools: '列出工具',
  describe_tool: '查看工具',
};

function actionIcon(node: FlowNode) {
  if (node.type === 'input') return Database;
  if (node.type === 'answer') return MessageSquare;
  switch (node.action) {
    case 'visualize': return BarChart3;
    case 'visualize_batch': return BarChart3;
    case 'generate_viz': return BarChart3;
    case 'generate_tool': return Sparkles;
    case 'list_tools': return List;
    case 'describe_tool': return Info;
    default: return Wrench;
  }
}

export function deriveFlow(events: Event[], datasetName?: string): FlowNode[] {
  const nodes: FlowNode[] = [{
    type: 'input',
    title: datasetName || '输入数据',
    subtitle: '数据集',
  }];

  events.forEach((e, i) => {
    if (e.kind !== 'tool_call') return;
    const action = String(e.payload.action ?? '');
    const args = (e.payload.args as Record<string, unknown>) ?? {};
    // Pair with the next tool_result (stop at the next tool_call so chains
    // don't cross-attach results).
    let result: FlowNode['result'];
    for (let j = i + 1; j < events.length; j++) {
      if (events[j].kind === 'tool_call') break;
      if (events[j].kind === 'tool_result') {
        result = events[j].payload.result as FlowNode['result'];
        break;
      }
    }
    const slug = args.slug ? String(args.slug) : undefined;
    nodes.push({
      type: 'tool',
      action,
      slug,
      params: (args.params as Record<string, unknown>) ?? args,
      title: slug || ACTION_LABEL[action] || action,
      subtitle: ACTION_LABEL[action] || action,
      status: result?.error || result?.status === 'error' ? 'error' : result ? 'ok' : 'pending',
      result,
    });
  });

  const final = [...events].reverse().find((e) => e.kind === 'final');
  if (final) {
    const errored = Boolean(final.payload.error);
    const cancelled = Boolean(final.payload.cancelled);
    nodes.push({
      type: 'answer',
      title: errored ? '出错' : cancelled ? '已取消' : '回答',
      subtitle: '最终输出',
      status: errored ? 'error' : 'ok',
    });
  }
  return nodes;
}

/** Extract the replayable step chain (what a template needs to re-run).
 * Only `ok` nodes survive — failed/pending steps would just re-fail on replay,
 * and dropping them means a "errored → fixed & re-ran" pair keeps the good version. */
export function toSteps(events: Event[], datasetName?: string) {
  return deriveFlow(events, datasetName)
    .filter((n) => n.type === 'tool' && n.action === 'run_tool' && n.slug && n.status === 'ok')
    .map((n) => ({ action: n.action!, slug: n.slug, params: n.params ?? {}, label: n.title }));
}

export default function FlowGraph({
  events,
  datasetName,
}: {
  events: Event[];
  datasetName?: string;
}) {
  const nodes = deriveFlow(events, datasetName);
  const toolCount = nodes.filter((n) => n.type === 'tool').length;
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  // When the user opts to edit, we create the template then open it in the full
  // FlowCanvas editor (delete / add steps, edit params, run) — no need to
  // re-implement editing here.
  const [editTpl, setEditTpl] = useState<FlowTemplate | null>(null);
  const [opening, setOpening] = useState(false);

  async function saveTemplate() {
    const steps = toSteps(events, datasetName);
    if (steps.length === 0) return;
    const name = window.prompt('给这个流程模板起个名字:', `${datasetName || '分析'}流程`);
    if (!name) return;
    setSaveState('saving');
    try {
      await api.createTemplate(name, steps, `从对话保存的 ${steps.length} 步流程`);
      setSaveState('saved');
    } catch {
      setSaveState('error');
    }
  }

  // Save as a template, then open it in the editor canvas so the user can
  // delete/add steps and tweak params on the flow derived from this chat.
  async function editTemplate() {
    const steps = toSteps(events, datasetName);
    if (steps.length === 0) return;
    const name = window.prompt('给这个流程起个名字（之后可在画布里编辑）:', `${datasetName || '分析'}流程`);
    if (!name) return;
    setOpening(true);
    try {
      const tpl = await api.createTemplate(name, steps, `从对话保存的 ${steps.length} 步流程`);
      setEditTpl(tpl);
      setSaveState('saved');
    } catch {
      setSaveState('error');
    } finally {
      setOpening(false);
    }
  }

  if (toolCount === 0) {
    return (
      <div className="text-[12px] text-ink-400 italic py-6 text-center">
        这次对话还没有调用任何算法/工具 —— 跑一次分析后,这里会画出流程图。
      </div>
    );
  }

  return (
    <div className="py-1">
      <div className="flex flex-col items-stretch">
        {nodes.map((node, i) => (
          <div key={i}>
            <FlowCard node={node} />
            {i < nodes.length - 1 && <Connector />}
          </div>
        ))}
      </div>

      <div className="mt-3 flex items-center gap-1.5">
        <button
          onClick={editTemplate}
          disabled={opening}
          className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-70"
        >
          {opening ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Pencil className="w-3.5 h-3.5" />}
          编辑流程（删/加步骤 · 改参数）
        </button>
        <button
          onClick={saveTemplate}
          disabled={saveState === 'saving' || saveState === 'saved'}
          title="不编辑,直接存入流程库"
          className={`shrink-0 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium ring-1 disabled:opacity-70 ${
            saveState === 'saved' ? 'ring-emerald-200 text-emerald-700 bg-emerald-50' : 'ring-ink-200 text-ink-600 hover:bg-ink-50'
          }`}
        >
          {saveState === 'saving' ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
            : saveState === 'saved' ? <CheckCircle2 className="w-3.5 h-3.5" />
            : <Save className="w-3.5 h-3.5" />}
          {saveState === 'saved' ? '已保存' : '直接保存'}
        </button>
      </div>
      <div className="mt-1.5 text-[10.5px] text-ink-400 text-center leading-snug">
        {saveState === 'error' ? '保存失败,请重试。'
          : '「编辑流程」会先存为模板再打开画布;保存后到「算法库 → 流程模板」可一键在新数据上执行。'}
      </div>

      {editTpl && <EditFlowModal tpl={editTpl} onClose={() => setEditTpl(null)} />}
    </div>
  );
}

/** Full-screen editor overlay: loads the just-saved template into the same
 *  FlowCanvas used in the 流程模板 tab, so the chat-derived flow becomes fully
 *  editable (drag/add/delete steps, edit params, batch-run + 批量出图). Datasets
 *  and the algorithm library are fetched on open (FlowCanvas needs both). */
function EditFlowModal({ tpl, onClose }: { tpl: FlowTemplate; onClose: () => void }) {
  const [datasets, setDatasets] = useState<Dataset[] | null>(null);
  const [algos, setAlgos] = useState<Algorithm[] | null>(null);
  const [cur, setCur] = useState<FlowTemplate>(tpl);

  useEffect(() => {
    api.listDatasets().then(setDatasets).catch(() => setDatasets([]));
    api.listAlgorithms().then(setAlgos).catch(() => setAlgos([]));
  }, []);

  // Re-fetch the template after a save inside the canvas so the title/steps stay
  // in sync if the modal is reopened.
  async function refreshTpl() {
    try {
      const all = await api.listTemplates();
      const fresh = all.find((x) => x.id === tpl.id);
      if (fresh) setCur(fresh);
    } catch { /* ignore */ }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-stretch p-3 sm:p-6" onClick={onClose}>
      <div className="flex-1 bg-white rounded-2xl ring-1 ring-ink-200 shadow-xl flex flex-col overflow-hidden" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-ink-200 shrink-0">
          <Pencil className="w-4 h-4 text-brand-600" />
          <div className="font-semibold text-sm flex-1 truncate">编辑流程 · {cur.name}</div>
          <span className="text-[11px] text-ink-400 hidden sm:inline">已存入流程库,改动会自动保存</span>
          <button onClick={onClose} className="text-ink-400 hover:text-ink-700 p-1"><X className="w-4 h-4" /></button>
        </div>
        <div className="flex-1 min-h-0">
          {datasets && algos ? (
            <FlowCanvas key={cur.id} tpl={cur} datasets={datasets} algos={algos}
              onChanged={refreshTpl} onDeleted={onClose} />
          ) : (
            <div className="h-full grid place-items-center text-sm text-ink-400">
              <span className="flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> 正在加载画布…</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function FlowCard({ node }: { node: FlowNode }) {
  const Icon = actionIcon(node);
  const border =
    node.type === 'input' ? 'border-l-ink-400'
      : node.type === 'answer' ? (node.status === 'error' ? 'border-l-red-400' : 'border-l-emerald-400')
        : node.status === 'error' ? 'border-l-red-400' : 'border-l-brand-500';

  const resultLine = describeResult(node);

  return (
    <div className={`rounded-lg ring-1 ring-ink-200 bg-white border-l-[3px] ${border} px-2.5 py-2`}>
      <div className="flex items-center gap-2">
        <Icon className="w-3.5 h-3.5 text-ink-500 shrink-0" />
        <span className="text-[12px] font-medium font-mono truncate">{node.title}</span>
        {node.status === 'error' && <AlertTriangle className="w-3 h-3 text-red-500 ml-auto shrink-0" />}
        {node.status === 'ok' && node.type !== 'input' && <CheckCircle2 className="w-3 h-3 text-emerald-500 ml-auto shrink-0" />}
      </div>
      {node.subtitle && <div className="text-[10.5px] text-ink-400 mt-0.5 ml-5.5">{node.subtitle}</div>}
      {node.params && Object.keys(node.params).length > 0 && node.type === 'tool' && (
        <div className="text-[10.5px] text-ink-500 mt-1 ml-5.5 font-mono break-all line-clamp-2">
          {formatParams(node.params)}
        </div>
      )}
      {resultLine && <div className="text-[10.5px] text-ink-500 mt-0.5 ml-5.5">{resultLine}</div>}
    </div>
  );
}

function Connector() {
  return (
    <div className="flex justify-center py-0.5">
      <ChevronDown className="w-3.5 h-3.5 text-ink-300" />
    </div>
  );
}

function formatParams(params: Record<string, unknown>): string {
  const parts = Object.entries(params)
    .filter(([k]) => k !== 'params')
    .slice(0, 4)
    .map(([k, v]) => `${k}=${Array.isArray(v) ? `[${v.join(',')}]` : String(v)}`);
  return parts.join('  ');
}

function describeResult(node: FlowNode): string | null {
  const r = node.result;
  if (!r) return null;
  if (r.error) return `⚠ ${String(r.error).slice(0, 60)}`;
  if (r.kind === 'chart') return `→ 图表 (${(r.summary?.points as number) ?? '?'} 点)`;
  const s = r.summary as { type?: string; rows?: number } | undefined;
  if (s?.type === 'dataframe') return `→ ${s.rows} 行`;
  if (s?.type) return `→ ${s.type}`;
  return null;
}

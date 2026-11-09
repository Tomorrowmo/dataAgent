// Steps a chat answer ran (from the per-step provenance the backend records)
// and whether they can be saved as a flow that replays faithfully.
// 改进清单-3 · E1 / L2a. Shared by the answer footer and the workbench flow graph.
import type { TemplateStep } from '@/lib/api';

type Ev = { kind: string; payload: Record<string, unknown> };


export type Prov = {
  step: number;
  input: { kind: 'dataset'; dataset_id: number; prior_turn?: boolean } | { kind: 'step'; step: number } | null;
  dataset_id?: number;
  algorithm: { slug: string; source?: string; id?: number; version?: number; verified?: boolean };
  label?: string;
  params?: Record<string, unknown>;
  output_role?: 'data' | 'report' | null;
};
export type RunStep = { prov: Prov; ok: boolean; derived?: { id: number; name: string } };

export function runStepsOf(events: Ev[]): RunStep[] {
  const out: RunStep[] = [];
  for (const e of events) {
    if (e.kind !== 'tool_result') continue;
    const p = e.payload as { action?: string; result?: { status?: string; provenance?: Prov; derived_dataset?: { id: number; name: string } } };
    const r = p.result;
    if (p.action !== 'run_tool' || !r?.provenance) continue;
    out.push({ prov: r.provenance, ok: r.status === 'ok', derived: r.derived_dataset });
  }
  return out;
}

/** Whether these steps can become a flow that replays faithfully — and if
 *  not, why (L2a). Returns template steps when allowed. */
export function flowFromSteps(steps: RunStep[]): { steps?: TemplateStep[]; reason?: string; startId?: number } {
  const ok = steps.filter((s) => s.ok);
  const idx = new Map(ok.map((s, i) => [s.prov.step, i]));
  const starts = new Set<number>();
  for (const [i, s] of ok.entries()) {
    const inp = s.prov.input;
    const n = i + 1;
    if (!inp) return { reason: `第 ${n} 步的输入无法确定，不能保存为流程。` };
    if (inp.kind === 'dataset') {
      if (inp.prior_turn) return { reason: `第 ${n} 步接着上一轮的中间结果继续算，依赖链外的数据，不能直接保存为流程。` };
      starts.add(inp.dataset_id);
    } else if (!idx.has(inp.step)) {
      return { reason: `第 ${n} 步依赖的步骤没有成功，不能保存为流程。` };
    }
    if (s.prov.algorithm.source && s.prov.algorithm.source !== 'builtin' && s.prov.algorithm.verified === false) {
      return { reason: `第 ${n} 步用的「${s.prov.label ?? s.prov.algorithm.slug}」是尚未确认保留的 AI 草稿算法，请先到算法库确认保留。` };
    }
  }
  if (starts.size > 1) return { reason: '这次分析用到了不止一个数据集，流程只能保存单一数据源的链。' };
  return {
    startId: [...starts][0],
    steps: ok.map((s) => ({
      action: 'run_tool', slug: s.prov.algorithm.slug, params: s.prov.params ?? {}, label: s.prov.label ?? s.prov.algorithm.slug,
      algorithm_id: s.prov.algorithm.id ?? null, version: s.prov.algorithm.version ?? null,
      input: s.prov.input?.kind === 'step' ? (idx.get(s.prov.input.step) as number) : 'start',
      output_role: s.prov.output_role ?? null,
    })),
  };
}


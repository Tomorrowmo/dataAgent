'use client';

import { useEffect, useRef, useState } from 'react';
import {
  Loader2, Wrench, AlertTriangle, CheckCircle2, MessageSquare,
  Cpu, X, PanelRightClose, ChevronDown, ChevronRight, ListTree, Workflow, Table2,
} from 'lucide-react';
import FlowGraph from '@/components/FlowGraph';
import DataPanel from '@/components/DataPanel';
import type { Dataset } from '@/lib/api';

/**
 * Workbench-style activity log for the agent loop.
 *
 * Mirrors the Claude-Code-in-terminal aesthetic: a vertical timeline of
 * structured events with timestamps, durations, and one-click expand of
 * the underlying payload. Always visible during a turn so the user can see
 * exactly what the agent is doing (calling LLM, listing tools, running a
 * specific algorithm, hitting an error). Eliminates the "spinner only"
 * dead zone where the user has no idea whether the system is alive.
 *
 * Backed by the streaming events the chat API already emits:
 *   progress  — heartbeat from chat_agent (llm_call / llm_done / tool_*)
 *   thought   — agent's one-sentence reasoning per step
 *   tool_call — which action + args
 *   tool_result — what came back
 *   final     — final answer / error
 *
 * Persists open/closed in localStorage so the user's preference sticks.
 */

export type Event = { kind: string; payload: Record<string, unknown> };
export type EventTrace = {
  events: Event[];
  busy: boolean;              // currently streaming?
  turnStartedAt?: number;     // performance.now() when send fired
};

/**
 * Pair each completion (llm_done / tool_done) with the most recent unmatched
 * start (llm_call / tool_start) and return the indices of starts that have
 * since completed. A spinner must only keep animating for start events NOT in
 * this set — otherwise a historical "calling qwen-plus…" / "running run_tool…"
 * row spins forever after its completion has already streamed in (the bug where
 * a finished turn still shows perpetual spinners).
 */
export function resolvedStarts(events: Event[]): Set<number> {
  const resolved = new Set<number>();
  const openLlm: number[] = [];
  const openTool: number[] = [];
  events.forEach((ev, i) => {
    if (ev.kind !== 'progress') return;
    const phase = String(ev.payload.phase ?? '');
    if (phase === 'llm_call') openLlm.push(i);
    else if (phase === 'tool_start') openTool.push(i);
    else if (phase === 'llm_done') { const s = openLlm.pop(); if (s !== undefined) resolved.add(s); }
    else if (phase === 'tool_done') { const s = openTool.pop(); if (s !== undefined) resolved.add(s); }
  });
  return resolved;
}

const LS_KEY = 'numetrix.workbench.open';

export function useWorkbenchOpen(defaultValue = true): [boolean, (v: boolean) => void] {
  const [open, setOpen] = useState<boolean>(defaultValue);
  useEffect(() => {
    try {
      const stored = localStorage.getItem(LS_KEY);
      if (stored !== null) { setOpen(stored === '1'); return; }
    } catch { /* SSR */ }
    // No saved preference → open on desktop, but CLOSED on a phone so the
    // full-screen workbench overlay doesn't cover the chat on load.
    if (typeof window !== 'undefined' && window.innerWidth < 768) setOpen(false);
  }, []);
  const set = (v: boolean) => {
    setOpen(v);
    try { localStorage.setItem(LS_KEY, v ? '1' : '0'); } catch { /* SSR */ }
  };
  return [open, set];
}

export default function WorkbenchPanel({
  trace,
  onClose,
  datasetName,
  datasets = [],
  onClean,
  onViewDataset,
}: {
  trace: EventTrace;
  onClose: () => void;
  datasetName?: string;
  datasets?: Dataset[];
  onClean?: (ds: Dataset) => void;
  onViewDataset?: (id: number) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  // "timeline" = chronological event log; "flow" = Dify/Coze-style node graph
  // of the tool-call chain; "data" = preview of the loaded dataset(s).
  const [view, setView] = useState<'timeline' | 'flow' | 'data'>('timeline');
  // Drag-to-resize width, persisted across sessions. The panel is flush to the
  // right edge, so width = (viewport width − cursor X) while dragging the left
  // handle — no need to track drag-start offsets.
  const [width, setWidth] = useState(340);
  const widthRef = useRef(340);
  const draggingRef = useRef(false);
  useEffect(() => {
    try {
      const s = localStorage.getItem('numetrix.workbench.width');
      if (s) { const w = Math.min(720, Math.max(280, parseInt(s, 10) || 340)); setWidth(w); widthRef.current = w; }
    } catch { /* SSR */ }
  }, []);
  useEffect(() => {
    function onMove(e: MouseEvent) {
      if (!draggingRef.current) return;
      const w = Math.min(720, Math.max(280, window.innerWidth - e.clientX));
      widthRef.current = w;
      setWidth(w);
    }
    function onUp() {
      if (!draggingRef.current) return;
      draggingRef.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      try { localStorage.setItem('numetrix.workbench.width', String(Math.round(widthRef.current))); } catch { /* SSR */ }
    }
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp); };
  }, []);
  // Auto-scroll to bottom on new events while busy (timeline only)
  useEffect(() => {
    if (view === 'timeline' && trace.busy && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [trace.events.length, trace.busy, view]);

  // When a dataset first appears and nothing has run yet, surface its preview
  // automatically — so importing/selecting data shows the table on the right
  // instead of an empty timeline. Only fires on the 0→data transition, so it
  // never fights a user who deliberately switched tabs mid-session.
  const prevDsCount = useRef(0);
  useEffect(() => {
    if (prevDsCount.current === 0 && datasets.length > 0 && trace.events.length === 0 && !trace.busy) {
      setView('data');
    }
    prevDsCount.current = datasets.length;
  }, [datasets.length, trace.events.length, trace.busy]);

  return (
    <aside style={{ width }} className="relative shrink-0 border-l border-ink-200 bg-ink-50/50 flex flex-col h-full max-md:!fixed max-md:!inset-0 max-md:!z-50 max-md:!w-full max-md:!border-l-0">
      {/* Drag handle on the left edge — desktop only (mobile is full-screen) */}
      <div
        onMouseDown={() => {
          draggingRef.current = true;
          document.body.style.cursor = 'col-resize';
          document.body.style.userSelect = 'none';
        }}
        className="absolute left-0 top-0 h-full w-1.5 -ml-0.5 cursor-col-resize hover:bg-brand-400/50 active:bg-brand-500/60 z-20 max-md:hidden"
        title="拖拽调整宽度"
      />
      <div className="px-3 py-2.5 border-b border-ink-200 bg-white flex items-center gap-2">
        <Cpu className="w-4 h-4 text-brand-600" />
        <div className="text-sm font-medium">工作台</div>
        {trace.busy && (
          <div className="ml-1 flex items-center gap-1 text-[11px] text-brand-600 font-mono">
            <Loader2 className="w-3 h-3 animate-spin" />
            <span>running</span>
          </div>
        )}
        <button
          onClick={onClose}
          className="ml-auto p-1 rounded hover:bg-ink-100 text-ink-500"
          title="收起工作台"
        >
          <PanelRightClose className="w-4 h-4" />
        </button>
      </div>

      {/* View toggle: timeline ↔ flow graph */}
      <div className="px-3 pt-2 bg-white flex items-center gap-1">
        {([['timeline', '时间线', ListTree], ['flow', '流程图', Workflow], ['data', '数据', Table2]] as const).map(([v, label, Icon]) => (
          <button
            key={v}
            onClick={() => setView(v)}
            className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-lg transition ${
              view === v ? 'bg-brand-50 text-brand-700 ring-1 ring-brand-200' : 'text-ink-500 hover:bg-ink-50'
            }`}
          >
            <Icon className="w-3.5 h-3.5" />
            {label}
          </button>
        ))}
      </div>

      {view === 'flow' ? (
        <div className="flex-1 overflow-y-auto scroll-hide px-3 py-3">
          <FlowGraph events={trace.events} datasetName={datasetName} />
        </div>
      ) : view === 'data' ? (
        <div className="flex-1 overflow-y-auto scroll-hide px-3 py-3">
          <DataPanel datasets={datasets} onClean={onClean} onViewFull={onViewDataset} />
        </div>
      ) : (
      <div ref={scrollRef} className="flex-1 overflow-y-auto scroll-hide px-3 py-3 space-y-1.5">
        {trace.events.length === 0 && !trace.busy && (
          <div className="text-[12px] text-ink-400 italic py-6 text-center">
            空闲中 · 发送一条消息后这里会实时显示 agent 的每一步
          </div>
        )}
        {trace.events.length === 0 && trace.busy && (
          <TimelineRow
            icon={<Loader2 className="w-3.5 h-3.5 animate-spin text-brand-600" />}
            label="initializing"
            detail="等待第一个事件..."
            tone="muted"
          />
        )}
        {(() => {
          const resolved = resolvedStarts(trace.events);
          return trace.events.map((ev, i) => (
            <EventRow key={i} ev={ev} idx={i} resolved={resolved.has(i)} />
          ));
        })()}
      </div>
      )}

      <div className="px-3 py-2 border-t border-ink-200 bg-white text-[11px] text-ink-400 flex items-center justify-between">
        <span>{trace.events.length} 事件</span>
        {trace.turnStartedAt && trace.busy && (
          <LiveDuration startedAt={trace.turnStartedAt} />
        )}
      </div>
    </aside>
  );
}

function LiveDuration({ startedAt }: { startedAt: number }) {
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => {
    const id = setInterval(() => setNow(performance.now()), 100);
    return () => clearInterval(id);
  }, []);
  const dt = ((now - startedAt) / 1000).toFixed(1);
  return <span className="font-mono">耗时 {dt}s</span>;
}

function EventRow({ ev, idx, resolved = false }: { ev: Event; idx: number; resolved?: boolean }) {
  const [expanded, setExpanded] = useState(false);

  // Divider between turns — the timeline accumulates across the whole conversation.
  if (ev.kind === 'turn') {
    const text = String(ev.payload.text ?? '');
    return (
      <div className="flex items-center gap-2 pt-3 pb-0.5 first:pt-0">
        <div className="h-px flex-1 bg-ink-200" />
        <span className="text-[10px] text-ink-400 font-medium shrink-0 max-w-[70%] truncate" title={text}>▶ {text}</span>
        <div className="h-px flex-1 bg-ink-200" />
      </div>
    );
  }

  if (ev.kind === 'progress') {
    const phase = String(ev.payload.phase ?? '');
    const msg = String(ev.payload.msg ?? '');
    const ok = ev.payload.ok;
    const dt = ev.payload.duration_s as number | undefined;
    const isError = ok === false;
    // Only spin a start row that is still genuinely in-flight; once its
    // matching completion has streamed in (`resolved`), show a neutral dot so
    // the timeline keeps the entry without an orphaned, never-ending spinner.
    const inflight = (phase === 'llm_call' || phase === 'tool_start') && !resolved;
    const done = phase === 'llm_done' || phase === 'tool_done';
    return (
      <TimelineRow
        icon={
          isError
            ? <AlertTriangle className="w-3.5 h-3.5 text-red-500" />
            : done
              ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
              : inflight
                ? <Loader2 className="w-3.5 h-3.5 animate-spin text-brand-600" />
                : <Cpu className="w-3.5 h-3.5 text-ink-400" />
        }
        label={phase || 'progress'}
        detail={msg}
        duration={dt}
        tone={isError ? 'error' : done ? 'success' : 'muted'}
      />
    );
  }

  if (ev.kind === 'thought') {
    const text = String(ev.payload.text ?? '');
    return (
      <TimelineRow
        icon={<MessageSquare className="w-3.5 h-3.5 text-violet-500" />}
        label="thought"
        detail={text}
        tone="thought"
      />
    );
  }

  if (ev.kind === 'tool_call') {
    const action = String(ev.payload.action ?? '');
    const args = ev.payload.args as Record<string, unknown> | undefined;
    const slug = args?.slug ? ` → ${String(args.slug)}` : '';
    return (
      <TimelineRow
        icon={<Wrench className="w-3.5 h-3.5 text-brand-600" />}
        label="tool_call"
        detail={`${action}${slug}`}
        tone="tool"
        expandable={args && Object.keys(args).length > 0 ? () => (
          <pre className="text-[10.5px] font-mono whitespace-pre-wrap break-all text-ink-600">
            {JSON.stringify(args, null, 2)}
          </pre>
        ) : undefined}
        expanded={expanded}
        onToggle={() => setExpanded((x) => !x)}
      />
    );
  }

  if (ev.kind === 'tool_result') {
    const result = ev.payload.result as { status?: string; error?: string; summary?: Record<string, unknown>; tools?: unknown[]; meta?: Record<string, unknown> } | undefined;
    if (!result) return null;
    const ok = result.status === 'ok';
    const err = !!result.error;
    let detail = 'completed';
    if (result.tools) detail = `found ${(result.tools as unknown[]).length} tools`;
    else if (err) detail = String(result.error).slice(0, 120);
    else if (result.meta) detail = `generated "${String((result.meta as Record<string, unknown>).name ?? '')}"`;
    else if (ok && result.summary) {
      const summary = result.summary as { rows?: number; type?: string };
      detail = summary.type === 'dataframe' ? `dataframe (${summary.rows} rows)` : (summary.type || 'ok');
    }
    return (
      <TimelineRow
        icon={
          err
            ? <AlertTriangle className="w-3.5 h-3.5 text-red-500" />
            : <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
        }
        label="tool_result"
        detail={detail}
        tone={err ? 'error' : 'success'}
        expandable={() => (
          <pre className="text-[10.5px] font-mono whitespace-pre-wrap break-all text-ink-600 max-h-64 overflow-auto">
            {JSON.stringify(result, null, 2)}
          </pre>
        )}
        expanded={expanded}
        onToggle={() => setExpanded((x) => !x)}
      />
    );
  }

  if (ev.kind === 'final') {
    const text = String(ev.payload.text ?? '');
    const isError = ev.payload.error === true;
    const isCancelled = ev.payload.cancelled === true;
    return (
      <TimelineRow
        icon={
          isError
            ? <AlertTriangle className="w-3.5 h-3.5 text-red-500" />
            : isCancelled
              ? <X className="w-3.5 h-3.5 text-amber-500" />
              : <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
        }
        label={isError ? 'final · error' : isCancelled ? 'final · cancelled' : 'final'}
        detail={text.length > 140 ? text.slice(0, 140) + '…' : text}
        tone={isError ? 'error' : isCancelled ? 'warn' : 'success'}
        expandable={text.length > 140 ? () => (
          <div className="text-[12px] whitespace-pre-wrap break-words text-ink-700">{text}</div>
        ) : undefined}
        expanded={expanded}
        onToggle={() => setExpanded((x) => !x)}
      />
    );
  }

  // Unknown kind — show raw so we never silently swallow anything
  return (
    <TimelineRow
      icon={<Cpu className="w-3.5 h-3.5 text-ink-400" />}
      label={ev.kind || `event_${idx}`}
      detail={JSON.stringify(ev.payload).slice(0, 120)}
      tone="muted"
    />
  );
}

function TimelineRow({
  icon, label, detail, duration, tone, expandable, expanded, onToggle,
}: {
  icon: React.ReactNode;
  label: string;
  detail?: string;
  duration?: number;
  tone: 'muted' | 'success' | 'error' | 'warn' | 'thought' | 'tool';
  expandable?: () => React.ReactNode;
  expanded?: boolean;
  onToggle?: () => void;
}) {
  const labelClass = {
    muted:   'text-ink-500',
    success: 'text-emerald-700',
    error:   'text-red-700',
    warn:    'text-amber-700',
    thought: 'text-violet-700',
    tool:    'text-brand-700',
  }[tone];
  const detailClass = {
    muted:   'text-ink-500',
    success: 'text-ink-600',
    error:   'text-red-600',
    warn:    'text-amber-700',
    thought: 'text-ink-600 italic',
    tool:    'text-ink-700',
  }[tone];
  return (
    <div className="text-[12px] leading-relaxed">
      <button
        type="button"
        onClick={onToggle}
        disabled={!expandable}
        className={`w-full text-left flex items-start gap-2 px-1.5 py-1 rounded ${expandable ? 'hover:bg-white cursor-pointer' : 'cursor-default'}`}
      >
        <div className="pt-0.5 shrink-0">{icon}</div>
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-1.5">
            <span className={`font-mono text-[10.5px] ${labelClass}`}>{label}</span>
            {typeof duration === 'number' && (
              <span className="font-mono text-[10.5px] text-ink-400">· {duration}s</span>
            )}
          </div>
          {detail && (
            <div className={`mt-0.5 break-words ${detailClass}`}>{detail}</div>
          )}
        </div>
        {expandable && (
          <div className="pt-0.5 shrink-0 text-ink-400">
            {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          </div>
        )}
      </button>
      {expandable && expanded && (
        <div className="ml-7 mt-1 mb-1 p-2 rounded bg-white ring-1 ring-ink-200">
          {expandable()}
        </div>
      )}
    </div>
  );
}

'use client';

import { useEffect, useRef, useState } from 'react';
import { Send, Sparkles, Wrench, Bot, User, Loader2, AlertTriangle, Upload, Database, PanelRightOpen, ChevronDown, ChevronRight, GitBranch, RotateCcw, Square } from 'lucide-react';
import Markdown from '@/components/Markdown';
import { api, streamChat, type ChatMessage, type Dataset, type UploadResp } from '@/lib/api';
import { useT, useLangStore } from '@/lib/i18n';
import { RECIPES, STARTERS, buildPrompt, type RecipeId, type Starter } from '@/lib/recipes';
import ParserModal from '@/components/ParserModal';
import CleanModal from '@/components/CleanModal';
import ChartPanel, { type ChartSpec } from '@/components/ChartPanel';
import SaveToolModal from '@/components/SaveToolModal';
import WorkbenchPanel, { useWorkbenchOpen, resolvedStarts, type Event as WbEvent } from '@/components/WorkbenchPanel';

type Event = { kind: string; payload: Record<string, unknown> };

type DisplayMsg = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  events?: Event[];
  pending?: boolean;
  datasetLabel?: string;  // which dataset(s) this turn actually ran on
};

export default function ChatView({
  conversationId,
  onConversationCreated,
}: {
  conversationId: number | null;
  onConversationCreated: (id: number) => void;
}) {
  const t = useT();
  const lang = useLangStore((s) => s.lang);
  const [messages, setMessages] = useState<DisplayMsg[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  // Multi-dataset: the set of datasets active in this conversation. The first
  // is the PRIMARY (default target); additional ones are loaded for comparison.
  const [activeDatasets, setActiveDatasets] = useState<number[]>([]);
  const [input, setInput] = useState('');
  // Dataset @-mention: typing "@" suggests datasets; picking one makes it the input.
  const [mention, setMention] = useState<{ query: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [pendingParser, setPendingParser] = useState<UploadResp['needs_parser'] | null>(null);
  const [cleaningDataset, setCleaningDataset] = useState<Dataset | null>(null);
  // Live event trace for the workbench panel. Mirrors the events of the
  // current/most-recent assistant turn so the right-side timeline shows what
  // the agent is doing in real time, even before the first chat bubble fills.
  const [liveEvents, setLiveEvents] = useState<WbEvent[]>([]);
  // The agent's reasoning as it streams in, shown live in the pending bubble so
  // "思考中" has content instead of being a blank spinner. Transient — not
  // persisted as an event; superseded by the final parsed `thought` chip.
  const [liveThought, setLiveThought] = useState('');
  const [turnStartedAt, setTurnStartedAt] = useState<number | undefined>(undefined);
  // Cross-turn pipeline head per dataset (so the user can SEE that "再插值" will
  // continue on the prior result, and reset to the original if they want).
  const [pipeline, setPipeline] = useState<Record<string, { head_id: number; head_name: string; steps: number }>>({});
  const [workbenchOpen, setWorkbenchOpen] = useWorkbenchOpen(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputAreaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // Tracks which conversation's messages are already represented in `messages`
  // state — either because we just loaded them from the DB, or because we
  // created the conversation locally in send(). The reload effect skips a
  // (destructive) refetch when this matches, so a freshly created conversation
  // whose assistant turn is still streaming doesn't get its in-flight bubble
  // wiped by a DB read that hasn't seen the persisted assistant row yet.
  const loadedConvRef = useRef<number | null>(null);
  // Aborts the in-flight streaming turn (the 停止 button / terminating a session).
  const abortRef = useRef<AbortController | null>(null);

  function stop() {
    abortRef.current?.abort();
  }

  useEffect(() => {
    refreshDatasets();
  }, []);

  async function refreshDatasets() {
    try {
      const list = await api.listDatasets();
      setDatasets(list);
      // Auto-select the newest dataset if nothing chosen yet
      if (activeDatasets.length === 0 && list.length > 0) {
        setActiveDatasets([list[0].id]);
      }
    } catch { /* ignore */ }
  }

  // Keep the pipeline-continuation chip in sync with the active conversation.
  function refreshPipeline(convId: number | null) {
    if (!convId) { setPipeline({}); return; }
    api.getPipeline(convId).then((r) => setPipeline(r.pipeline_state || {})).catch(() => {});
  }
  async function resetPipeline() {
    if (!conversationId) { setPipeline({}); return; }
    try { await api.resetPipeline(conversationId); } catch { /* ignore */ }
    setPipeline({});
  }

  useEffect(() => {
    // A GENUINE switch (to a different conversation, or to a blank new one) must
    // end any in-flight turn from the previous conversation and clear its busy
    // state — otherwise the new conversation inherits a stuck "发送中" spinner.
    // The `!== loadedConvRef.current` guard skips the conversation we just
    // created locally in send() (whose stream we must NOT abort).
    if (conversationId !== loadedConvRef.current) {
      abortRef.current?.abort();
      abortRef.current = null;
      setBusy(false);
      setLiveThought('');
      setError('');
    }
    if (!conversationId) {
      setMessages([]);
      setLiveEvents([]);
      setTurnStartedAt(undefined);
      setPipeline({});
      return;
    }
    refreshPipeline(conversationId);
    // Skip the destructive reload for a conversation already in state (just
    // created locally, or previously loaded). Switching to a *different*
    // conversation still differs from the ref, so it reloads normally.
    if (conversationId === loadedConvRef.current) return;
    api.listMessages(conversationId).then((msgs: ChatMessage[]) => {
      loadedConvRef.current = conversationId;
      const mapped: DisplayMsg[] = msgs.map((m) => ({
        id: `m_${m.id}`,
        role: m.role as 'user' | 'assistant',
        content: m.content,
        events: (m.meta?.events as Event[] | undefined) ?? undefined,
      }));
      setMessages(mapped);
      // Seed the workbench with the WHOLE conversation's timeline (every turn,
      // not just the last), a 'turn' divider before each user message — so the
      // right-side trace persists across the entire conversation.
      const tl: WbEvent[] = [];
      for (const m of mapped) {
        if (m.role === 'user') tl.push({ kind: 'turn', payload: { text: m.content.slice(0, 60) } });
        else if (m.events?.length) tl.push(...(m.events as WbEvent[]));
      }
      setLiveEvents(tl);
      setTurnStartedAt(undefined);
    });
  }, [conversationId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  async function handleFileUpload(file: File) {
    setError('');
    setUploading(true);
    try {
      const r = await api.uploadDataset(file);
      if (r.status === 'needs_parser' && r.needs_parser) {
        setPendingParser(r.needs_parser);
      } else if (r.status === 'ok' && r.dataset) {
        // A multi-sheet Excel returns one dataset per sheet — add & select all.
        const added = r.datasets && r.datasets.length ? r.datasets : [r.dataset];
        const addedIds = new Set(added.map((x) => x.id));
        setDatasets((d) => [...added, ...d.filter((x) => !addedIds.has(x.id))]);
        setActiveDatasets(added.map((x) => x.id));
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
    }
  }

  async function onParserIngested(ds: Dataset) {
    setPendingParser(null);
    setDatasets((d) => [ds, ...d.filter((x) => x.id !== ds.id)]);
    setActiveDatasets([ds.id]);
  }

  // Add/remove a dataset from the active set; order is preserved so the first
  // stays PRIMARY. Toggling is how the user builds a comparison set.
  function toggleDataset(id: number) {
    setActiveDatasets((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  }

  function onRecipeClick(id: RecipeId) {
    const ds = datasets.find((d) => d.id === (activeDatasets[0] ?? -1)) ?? null;
    if (id === 'custom' || !ds) {
      inputAreaRef.current?.focus();
      return;
    }
    const prompt = buildPrompt(id, ds, lang);
    setInput(prompt);
    inputAreaRef.current?.focus();
  }

  // One-click starter: ensure its bundled sample dataset exists (create it from
  // the embedded CSV the first time), then ask its question — so even an empty
  // account can try it instantly. Falls back to filling the box on any failure.
  async function onStarter(s: Starter) {
    const q = lang === 'zh' ? s.zh.q : s.en.q;
    let ds = datasets.find((d) => d.name === s.datasetName);
    if (!ds) {
      try {
        const file = new File([s.makeCsv()], `${s.datasetName}.csv`, { type: 'text/csv' });
        const r = await api.uploadDataset(file);
        const created = r.dataset ?? r.datasets?.[0];
        if (created) { ds = created; setDatasets((d) => [created, ...d.filter((x) => x.id !== created.id)]); }
      } catch { /* fall through to just filling the box */ }
    }
    if (ds) { setActiveDatasets([ds.id]); send(q, [ds.id]); }
    else { setInput(q); inputAreaRef.current?.focus(); }
  }

  // Pick a dataset from the @-mention dropdown: replace the @token with @name and
  // make this the (sole) input dataset for the next message.
  function pickMention(d: Dataset) {
    setInput((v) => v.replace(/@([^\s@]*)$/, `@${d.name} `));
    setActiveDatasets([d.id]);
    setMention(null);
    inputAreaRef.current?.focus();
  }

  async function send(maybeText?: string, dsOverride?: number[]) {
    const userText = (maybeText ?? input).trim();
    if (!userText || busy) return;
    const dsIds = dsOverride ?? activeDatasets;
    setError('');
    setBusy(true);
    setInput('');
    setMention(null);
    // Keep the workbench trace ACCUMULATING across the conversation (don't reset
    // per turn) — just push a 'turn' divider so each turn is distinguishable.
    // Record the start moment so the panel can show a live "elapsed Xs" counter.
    setLiveEvents((es) => [...es, { kind: 'turn', payload: { text: userText.slice(0, 60) } }]);
    setLiveThought('');
    setTurnStartedAt(performance.now());

    let convId = conversationId;
    if (!convId) {
      try {
        const conv = await api.createConversation(userText.slice(0, 50), dsIds[0] ?? undefined);
        convId = conv.id;
        // Claim this conversation as locally-loaded BEFORE bubbling the id up,
        // so the prop change it triggers doesn't make the reload effect refetch
        // (and wipe) the assistant turn we're about to stream into state.
        loadedConvRef.current = convId;
        onConversationCreated(conv.id);
      } catch (e) {
        setError((e as Error).message);
        setBusy(false);
        return;
      }
    }

    const primary = datasets.find((d) => d.id === dsIds[0]);
    const dsLabel = primary ? primary.name + (dsIds.length > 1 ? ` +${dsIds.length - 1}` : '') : undefined;
    const userMsg: DisplayMsg = { id: `u_${Date.now()}`, role: 'user', content: userText, datasetLabel: dsLabel };
    const pendingMsg: DisplayMsg = {
      id: `a_${Date.now()}`, role: 'assistant', content: '', events: [], pending: true,
    };
    setMessages((m) => [...m, userMsg, pendingMsg]);

    const ac = new AbortController();
    abortRef.current = ac;
    try {
      await streamChat(convId, userText, dsIds[0] ?? null, (ev) => {
        // Streaming reasoning: update the transient live-thought, don't persist
        // it as an event chip (the final parsed `thought` event does that).
        if (ev.kind === 'thought_delta') {
          setLiveThought(String(ev.payload.text ?? ''));
          return;
        }
        if (ev.kind === 'answer_delta') {
          // Stream the final answer into the bubble token-by-token (Claude-Code style).
          const text = String(ev.payload.text ?? '');
          setLiveThought('');
          setMessages((m) => {
            const last = m[m.length - 1];
            if (!last || last.role !== 'assistant') return m;
            return [...m.slice(0, -1), { ...last, content: text }];
          });
          return;
        }
        if (ev.kind === 'thought' || ev.kind === 'tool_call' || ev.kind === 'final') {
          setLiveThought('');
        }
        // Mirror every event into the workbench trace immediately. The
        // workbench is the user's only signal that the system is alive
        // before the first chat-bubble content lands, so this MUST happen
        // before the (heavier) message-state update below.
        setLiveEvents((es) => [...es, ev]);
        setMessages((m) => {
          const last = m[m.length - 1];
          if (!last || last.role !== 'assistant') return m;
          const next = [...m];
          const updated: DisplayMsg = { ...last, events: [...(last.events ?? []), ev] };
          if (ev.kind === 'final') {
            updated.content = String(ev.payload.text ?? '');
            updated.pending = false;
          }
          next[next.length - 1] = updated;
          return next;
        });
      }, dsIds, ac.signal);
      // The turn may have advanced the cross-turn pipeline head — refresh the chip.
      refreshPipeline(convId);
    } catch (e) {
      // User-initiated stop (终止会话): finalize the pending bubble as "已停止"
      // rather than an error. The backend persists the partial trace on disconnect.
      if ((e as Error).name === 'AbortError') {
        setLiveEvents((es) => [...es, { kind: 'final', payload: { text: '已停止生成', cancelled: true } }]);
        setMessages((m) => {
          const last = m[m.length - 1];
          if (last && last.pending) {
            const partial = (last.content || '').trim();
            return [...m.slice(0, -1), { ...last, pending: false, content: partial || '_（已停止生成）_' }];
          }
          return m;
        });
        refreshPipeline(convId);
      } else {
        const errMsg = (e as Error).message;
        setError(errMsg);
        // Mirror the failure into the workbench so it's visible there too,
        // even when the chat bubble itself ends up empty.
        setLiveEvents((es) => [
          ...es,
          { kind: 'final', payload: { text: errMsg, error: true, source: 'transport' } },
        ]);
        setMessages((m) => {
          const last = m[m.length - 1];
          if (last && last.pending) {
            return [...m.slice(0, -1), { ...last, pending: false, content: `**${t('common.error')}** ${errMsg}` }];
          }
          return m;
        });
      }
    } finally {
      abortRef.current = null;
      setBusy(false);
    }
  }

  const hasData = datasets.length > 0;
  const primaryId = activeDatasets[0] ?? null;
  const activeDs = datasets.find((d) => d.id === primaryId) ?? null;
  // Top picker shows SOURCE datasets only (+ any currently-selected derived so
  // you can still deselect it). Intermediates live in the 数据集 lineage tree.
  const pickerDatasets = datasets.filter((d) => d.kind !== 'derived' || activeDatasets.includes(d.id));
  const activeDsList = activeDatasets
    .map((id) => datasets.find((d) => d.id === id))
    .filter((d): d is Dataset => Boolean(d));
  const isFreshSession = messages.length === 0;

  return (
    <div className="flex h-full">
      {pendingParser && (
        <ParserModal
          pending={pendingParser}
          onClose={() => setPendingParser(null)}
          onIngested={onParserIngested}
        />
      )}
      {cleaningDataset && (
        <CleanModal
          dataset={cleaningDataset}
          onClose={() => setCleaningDataset(null)}
          onCreated={(ds) => {
            setDatasets((d) => [ds, ...d.filter((x) => x.id !== ds.id)]);
            setActiveDatasets([ds.id]);
            setCleaningDataset(null);
          }}
        />
      )}
      <div className="flex-1 min-w-0 flex flex-col h-full">
      <div className="border-b border-ink-200 px-3 md:px-5 py-3 bg-white flex items-center gap-3">
        <Bot className="w-5 h-5 text-brand-600 shrink-0" />
        <div className="font-medium max-md:hidden">{t('chat.title')}</div>
        <div className="ml-auto flex items-center gap-2 text-sm min-w-0">
          <span className="text-ink-500 max-md:hidden">{t('chat.dataset')}</span>
          <DatasetPicker datasets={pickerDatasets} activeIds={activeDatasets} primaryId={primaryId} onToggle={toggleDataset} />
          {!workbenchOpen && (
            <button
              onClick={() => setWorkbenchOpen(true)}
              title="打开工作台"
              className="ml-1 p-1.5 rounded-lg border border-ink-200 bg-white hover:bg-ink-50 text-ink-600 flex items-center gap-1.5"
            >
              <PanelRightOpen className="w-4 h-4" />
              <span className="text-xs">工作台</span>
            </button>
          )}
        </div>
      </div>

      <PipelineBar pipeline={pipeline} datasets={datasets} onReset={resetPipeline} />

      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto scroll-hide px-3 md:px-5 py-4 md:py-6 space-y-5 relative"
        onDragOver={(e) => { if (isFreshSession) { e.preventDefault(); setDragOver(true); } }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          if (!isFreshSession) return;
          e.preventDefault();
          setDragOver(false);
          const f = e.dataTransfer.files?.[0];
          if (f) handleFileUpload(f);
        }}
      >
        {isFreshSession ? (
          <Welcome
            t={t}
            hasData={hasData}
            datasets={datasets}
            activeDs={activeDs}
            activeIds={activeDatasets}
            uploading={uploading}
            dragOver={dragOver}
            onToggleDataset={toggleDataset}
            onClickUpload={() => fileInputRef.current?.click()}
            onRecipeClick={onRecipeClick}
            onStarter={onStarter}
            lang={lang}
          />
        ) : (
          messages.map((m) => <MessageBubble key={m.id} msg={m} t={t} liveThought={m.pending ? liveThought : ''} turnStartedAt={m.pending ? turnStartedAt : undefined} />)
        )}
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFileUpload(f); e.target.value = ''; }}
        />
      </div>

      {error && (
        <div className="mx-5 mb-2 px-3 py-2 rounded-lg bg-red-50 text-red-700 text-sm flex items-center gap-2">
          <AlertTriangle className="w-4 h-4" /> {error}
        </div>
      )}

      <div className="border-t border-ink-200 bg-white p-4 relative">
        {mention && (() => {
          const matches = datasets
            .filter((d) => d.kind !== 'derived')  // source datasets only — hide the pile of intermediate results
            .filter((d) => !mention.query || d.name.toLowerCase().includes(mention.query.toLowerCase()))
            .slice(0, 12);
          return (
            <div className="absolute bottom-full mb-2 left-4 w-80 max-h-56 overflow-y-auto scroll-hide bg-white rounded-xl ring-1 ring-ink-200 shadow-lg z-30 p-1">
              <div className="px-2 py-1 text-[10.5px] text-ink-400">选一个数据集作为这条消息的输入</div>
              {matches.map((d) => (
                <button key={d.id} onMouseDown={(e) => { e.preventDefault(); pickMention(d); }}
                  className="w-full text-left px-2 py-1.5 rounded-lg hover:bg-brand-50 flex items-center gap-2">
                  <Database className="w-3.5 h-3.5 text-brand-500 shrink-0" />
                  <span className="text-sm truncate flex-1">{d.name}</span>
                  <span className="text-[10px] text-ink-400 shrink-0">{d.rows.toLocaleString()}×{d.columns}</span>
                </button>
              ))}
              {matches.length === 0 && <div className="px-2 py-2 text-xs text-ink-400">无匹配数据集</div>}
            </div>
          );
        })()}
        <div className="flex gap-2 items-end">
          <textarea
            ref={inputAreaRef}
            value={input}
            onChange={(e) => {
              const v = e.target.value;
              setInput(v);
              const m = v.slice(0, e.target.selectionStart ?? v.length).match(/@([^\s@]*)$/);
              setMention(m ? { query: m[1] } : null);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Escape' && mention) { setMention(null); return; }
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            rows={2}
            placeholder={t('chat.placeholder')}
            className="flex-1 border border-ink-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-50 resize-none"
          />
          {busy ? (
            <button
              onClick={stop}
              title="终止本次生成"
              className="px-4 py-2 rounded-xl bg-red-600 text-white font-medium hover:bg-red-700 flex items-center gap-2"
            >
              <Square className="w-4 h-4 fill-current" /> 停止
            </button>
          ) : (
            <button
              onClick={() => send()}
              disabled={!input.trim()}
              className="px-4 py-2 rounded-xl bg-brand-600 text-white font-medium hover:bg-brand-700 disabled:opacity-50 flex items-center gap-2"
            >
              <Send className="w-4 h-4" />
              {t('chat.send')}
            </button>
          )}
        </div>
      </div>
      </div>
      {workbenchOpen && (
        <WorkbenchPanel
          trace={{ events: liveEvents, busy, turnStartedAt }}
          onClose={() => setWorkbenchOpen(false)}
          datasetName={activeDs?.name}
          datasets={activeDsList}
          onClean={(ds) => setCleaningDataset(ds)}
        />
      )}
    </div>
  );
}

/** Cross-turn pipeline banner: shows that the NEXT message will continue on a
 *  prior turn's processed result (not the original data), with a one-click
 *  reset back to source. Hidden when no pipeline is active. */
function PipelineBar({ pipeline, datasets, onReset }: {
  pipeline: Record<string, { head_id: number; head_name: string; steps: number }>;
  datasets: Dataset[];
  onReset: () => void;
}) {
  const entries = Object.entries(pipeline).filter(([, v]) => v && v.head_id);
  if (entries.length === 0) return null;
  return (
    <div className="mx-5 mt-2 px-3 py-1.5 rounded-lg bg-violet-50 ring-1 ring-violet-100 text-[12px] text-violet-800 flex items-center gap-2 flex-wrap">
      <GitBranch className="w-3.5 h-3.5 shrink-0 text-violet-500" />
      <span className="font-medium">流水线进行中</span>
      <span className="text-violet-600">
        {entries.map(([dsId, v]) => {
          const src = datasets.find((d) => String(d.id) === dsId)?.name ?? `#${dsId}`;
          return `${src} → ${v.head_name}(第 ${v.steps} 步)`;
        }).join(' · ')}
      </span>
      <span className="text-violet-500/80">—— 下一条消息会在这个结果上继续。</span>
      <button onClick={onReset}
        className="ml-auto inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-white ring-1 ring-violet-200 hover:bg-violet-100 text-violet-700 shrink-0">
        <RotateCcw className="w-3 h-3" /> 重置流水线
      </button>
    </div>
  );
}

/** Compact dataset picker — a dropdown with search + multi-select, so it stays
 *  tidy no matter how many datasets there are (chips don't scale). */
function DatasetPicker({ datasets, activeIds, primaryId, onToggle }: {
  datasets: Dataset[]; activeIds: number[]; primaryId: number | null; onToggle: (id: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    function onDoc(e: MouseEvent) { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); }
    if (open) document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  const primary = datasets.find((d) => d.id === primaryId) ?? null;
  const filtered = q ? datasets.filter((d) => d.name.toLowerCase().includes(q.toLowerCase())) : datasets;
  const label = activeIds.length === 0 ? '选择数据集'
    : activeIds.length === 1 ? (primary?.name ?? '1 个数据集')
    : `${primary?.name ?? ''} +${activeIds.length - 1}`;

  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen((o) => !o)}
        className="border border-ink-200 rounded-lg px-2.5 py-1.5 bg-white text-sm flex items-center gap-1.5 max-w-[260px] hover:border-brand-400">
        <Database className="w-3.5 h-3.5 text-brand-500 shrink-0" />
        <span className="truncate">{label}</span>
        <ChevronDown className="w-3.5 h-3.5 text-ink-400 shrink-0" />
      </button>
      {open && (
        <div className="absolute right-0 mt-1 w-72 bg-white rounded-xl ring-1 ring-ink-200 shadow-lg z-30 p-2">
          <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜索数据集…"
            className="w-full border border-ink-200 rounded-lg px-2 py-1.5 text-sm mb-1.5 focus:outline-none focus:border-brand-400" />
          <div className="max-h-72 overflow-y-auto scroll-hide space-y-0.5">
            {filtered.length === 0 && <div className="text-xs text-ink-400 px-2 py-3 text-center">无匹配的数据集</div>}
            {filtered.map((d) => {
              const sel = activeIds.includes(d.id);
              const isPrimary = primaryId === d.id;
              return (
                <button key={d.id} onClick={() => onToggle(d.id)}
                  className={`w-full text-left px-2 py-1.5 rounded-lg flex items-center gap-2 ${sel ? 'bg-brand-50' : 'hover:bg-ink-50'}`}>
                  <span className={`w-3.5 h-3.5 rounded border shrink-0 grid place-items-center ${sel ? 'bg-brand-600 border-brand-600' : 'border-ink-300'}`}>
                    {sel && <span className="text-white text-[9px] leading-none">✓</span>}
                  </span>
                  <span className="truncate text-sm flex-1">{isPrimary ? '★ ' : ''}{d.name}</span>
                  <span className="text-[10px] text-ink-400 shrink-0">{d.rows.toLocaleString()}×{d.columns}</span>
                </button>
              );
            })}
          </div>
          {activeIds.length > 1 && <div className="text-[11px] text-ink-400 px-2 pt-1.5 border-t border-ink-100 mt-1">已选 {activeIds.length} 个 · 第一个(★)为主数据集,其余用于对比</div>}
        </div>
      )}
    </div>
  );
}

function Welcome({
  t, hasData, datasets, activeDs, activeIds, uploading, dragOver, onToggleDataset, onClickUpload, onRecipeClick, onStarter, lang,
}: {
  t: (k: string) => string;
  hasData: boolean;
  datasets: Dataset[];
  activeDs: Dataset | null;
  activeIds: number[];
  uploading: boolean;
  dragOver: boolean;
  onToggleDataset: (id: number) => void;
  onClickUpload: () => void;
  onRecipeClick: (id: RecipeId) => void;
  onStarter: (s: Starter) => void;
  lang: 'en' | 'zh';
}) {
  return (
    <div className="max-w-3xl mx-auto pt-4">
      <h2 className="text-2xl font-semibold mb-1">👋 {t('welcome.hi')}</h2>

      <p className="text-sm text-ink-500 mb-4">{lang === 'zh' ? '把你要分析的数据放进来 —— 连没见过的格式，AI 也能帮你自动读懂。' : 'Bring in the data you want to analyze — even formats it has never seen, AI reads them for you.'}</p>

      {/* Drop zone — always here; the primary "get your data in" action */}
      <button
        onClick={onClickUpload}
        className={`w-full rounded-2xl border-2 border-dashed transition flex flex-col items-center gap-2 py-10 ${
          dragOver ? 'border-brand-500 bg-brand-50' : 'border-ink-200 bg-white hover:border-brand-400 hover:bg-brand-50/40'
        }`}
      >
        {uploading ? <Loader2 className="w-8 h-8 text-brand-600 animate-spin" /> : <Upload className="text-brand-600 w-8 h-8" />}
        <div className="font-medium text-base">{uploading ? t('welcome.uploading') : (lang === 'zh' ? '把你要分析的数据拖进来' : 'Drop in the data you want to analyze')}</div>
        <div className="text-xs text-ink-500">{lang === 'zh' ? 'CSV、Excel，甚至没见过的格式 —— AI 都能自动读出来' : 'CSV, Excel, even unknown formats — AI parses them automatically'}</div>
      </button>

      {!hasData ? (
        /* No data yet → offer one-click samples below the drop zone */
        <div className="mt-6">
          <h3 className="text-sm font-semibold mb-2 text-ink-600">{lang === 'zh' ? '或点一个示例直接试（自带数据）' : 'Or tap a sample (data included)'}</h3>
          <div className="grid grid-cols-2 gap-3">
            {STARTERS.map((s) => {
              const x = lang === 'zh' ? s.zh : s.en;
              return (
                <button key={s.datasetName} onClick={() => onStarter(s)}
                  className="text-left rounded-xl p-3.5 ring-1 ring-ink-200 bg-white hover:ring-brand-300 hover:bg-brand-50/40 hover:-translate-y-0.5 transition">
                  <div className="text-xl mb-1">{s.emoji}</div>
                  <div className="font-medium text-sm">{x.t}</div>
                  <div className="text-xs text-ink-500 mt-1 leading-snug line-clamp-2">{x.q}</div>
                </button>
              );
            })}
          </div>
        </div>
      ) : (
        /* Has data → what to do with the current dataset */
        <div className="mt-6">
          <p className="text-sm text-ink-500 mb-3">
            {lang === 'zh' ? '已有数据集 ' : 'Dataset '}
            <span className="font-medium text-ink-700">{activeDs?.name}</span>
            {activeIds.length > 1 && `  +${activeIds.length - 1}${lang === 'zh' ? '（可对比）' : ''}`}
            {lang === 'zh' ? ' —— 点一个分析，或在下面直接问。' : ' — tap one, or just ask below.'}
          </p>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {RECIPES.map((r) => (
              <button
                key={r.id}
                onClick={() => onRecipeClick(r.id)}
                className="text-left rounded-xl p-4 ring-1 bg-white ring-ink-200 hover:ring-brand-300 hover:bg-brand-50/40 hover:-translate-y-0.5 transition"
              >
                <div className="text-2xl mb-1.5">{r.emoji}</div>
                <div className="font-medium text-sm">{t(r.titleKey)}</div>
                <div className="text-xs text-ink-500 mt-1 leading-snug">{t(r.bodyKey)}</div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/** Live "alive" heartbeat for the pending turn: a ticking elapsed-seconds
 *  counter (proof it's not frozen) + a friendly description of the CURRENT step
 *  (which tool is running / thinking), so the user isn't left staring at a bare
 *  "思考中" while the agent works through multiple steps. */
function ThinkingIndicator({ startedAt, events, t }: { startedAt?: number; events: Event[]; t: (k: string) => string }) {
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => {
    const id = setInterval(() => setNow(performance.now()), 500);
    return () => clearInterval(id);
  }, []);
  const secs = startedAt ? Math.max(0, Math.round((now - startedAt) / 1000)) : 0;

  const rev = [...events].reverse();
  const lastProg = rev.find((e) => e.kind === 'progress');
  const lastTool = rev.find((e) => e.kind === 'tool_call');
  const step = (lastProg?.payload?.step as number) || undefined;
  const toolName = lastTool
    ? String((lastTool.payload.args as Record<string, unknown> | undefined)?.slug || lastTool.payload.action || '')
    : '';
  const ph = String(lastProg?.payload?.phase ?? '');
  let label = t('chat.thinking');
  if (ph === 'llm_call') label = '正在思考…';
  else if (ph === 'llm_done') label = '想好了，准备下一步…';
  else if (ph === 'tool_start') label = toolName ? `正在运行 ${toolName}…` : '正在运行…';
  else if (ph === 'tool_done') label = `${toolName || '工具'} 完成，继续…`;
  else if (typeof lastProg?.payload?.msg === 'string') label = String(lastProg.payload.msg);

  return (
    <div className="text-ink-500 text-xs flex items-center gap-2 mb-2">
      <Loader2 className="w-3 h-3 animate-spin shrink-0 text-brand-500" />
      {step ? <span className="shrink-0 text-ink-400 tabular-nums">第 {step} 步</span> : null}
      <span className="truncate font-medium">{label}</span>
      <span className="tabular-nums text-ink-400 shrink-0">· {secs}s</span>
    </div>
  );
}

/** Token-by-token reveal of streamed text, decoupled from arrival speed: a fast
 *  model whose deltas land in one batch still types out smoothly, because this
 *  ticks the visible length forward on its own 16ms clock until it catches the
 *  (still-growing) target. */
function Typewriter({ text }: { text: string }) {
  const [shown, setShown] = useState(0);
  useEffect(() => {
    if (shown >= text.length) return;
    const id = setTimeout(() => setShown((s) => Math.min(text.length, s + 2)), 16);
    return () => clearTimeout(id);
  });
  return <Markdown>{text.slice(0, shown)}</Markdown>;
}

function MessageBubble({ msg, t, liveThought = '', turnStartedAt }: { msg: DisplayMsg; t: (k: string) => string; liveThought?: string; turnStartedAt?: number }) {
  if (msg.role === 'user') {
    return (
      <div className="flex gap-3 max-w-3xl mx-auto">
        <div className="w-8 h-8 rounded-full bg-ink-200 grid place-items-center"><User className="w-4 h-4" /></div>
        <div className="flex-1 bg-white rounded-2xl ring-1 ring-ink-200 p-4 prose-tight text-sm">
          {msg.datasetLabel && (
            <div className="inline-flex items-center gap-1 text-[10.5px] text-brand-700 bg-brand-50 ring-1 ring-brand-100 rounded-md px-1.5 py-0.5 mb-2">
              <Database className="w-3 h-3" /> {msg.datasetLabel}
            </div>
          )}
          <Markdown>{msg.content}</Markdown>
        </div>
      </div>
    );
  }
  const events = msg.events ?? [];
  // Drop start chips (llm_call / tool_start) whose completion already arrived —
  // their done chip carries the duration and supersedes them; left in, their
  // spinner would never stop once the turn finished.
  const resolved = resolvedStarts(events);
  const visibleEvents = events.filter((e, i) => {
    if (e.kind !== 'progress') return true;
    const phase = String(e.payload.phase ?? '');
    return !((phase === 'llm_call' || phase === 'tool_start') && resolved.has(i));
  });
  const finalEvent = [...events].reverse().find((e) => e.kind === 'final');
  const errored = Boolean(finalEvent?.payload?.error);
  const cancelled = Boolean(finalEvent?.payload?.cancelled);
  const bubbleClass = errored
    ? 'bg-red-50/50 ring-red-200'
    : cancelled
      ? 'bg-amber-50/50 ring-amber-200'
      : 'bg-brand-50/50 ring-brand-100';
  // Split into OUTPUTS the user reads (charts, generated-tool cards, errors) —
  // always shown — and PROCESS chips (thinking / tool calls / progress), which
  // are collapsed by default since the full step detail lives in the 工作台.
  const outputs = visibleEvents.filter(isOutputEvent);
  const procEvents = visibleEvents.filter((e) => !isOutputEvent(e));
  return (
    <div className="flex gap-3 max-w-3xl mx-auto">
      <div className="w-8 h-8 rounded-full bg-brand-600 text-white grid place-items-center"><Bot className="w-4 h-4" /></div>
      <div className={`flex-1 rounded-2xl ring-1 p-4 prose-tight text-sm ${bubbleClass}`}>
        {procEvents.length > 0 && <ProcessTrace events={procEvents} active={Boolean(msg.pending)} t={t} />}
        {outputs.map((e, i) => <EventChip key={`o${i}`} ev={e} active={Boolean(msg.pending)} t={t} />)}
        {msg.pending && liveThought && (
          <div className="text-xs text-ink-500 italic mb-2 leading-relaxed">
            💭 {liveThought}<span className="animate-pulse">▍</span>
          </div>
        )}
        {msg.pending && <ThinkingIndicator startedAt={turnStartedAt} events={events} t={t} />}
        {msg.content && (msg.pending
          ? <Typewriter text={msg.content} />
          : <Markdown>{msg.content}</Markdown>)}
      </div>
    </div>
  );
}

/** Is this event an OUTPUT the user reads (chart / generated-tool card / error)
 *  vs a PROCESS chip (thinking, tool call, progress)? Outputs stay visible in
 *  the bubble; process is collapsed — full detail is in the 工作台. */
function isOutputEvent(e: Event): boolean {
  if (e.kind !== 'tool_result') return false;
  const r = (e.payload as { result?: { kind?: string; chart?: unknown; meta?: unknown; error?: unknown; derived_dataset?: unknown } }).result;
  if (!r) return false;
  // A new derived dataset (a new column the user may want) is an OUTPUT, not
  // process noise — keep its "已存为「X」, 数据集→中间结果可看" hint visible.
  return (r.kind === 'chart' && !!r.chart) || r.kind === 'chart_batch' || !!r.meta || !!r.error || !!r.derived_dataset;
}

/** Collapsed process trace inside the chat bubble — keeps the conversation
 *  focused on the answer; the full step-by-step lives in the right-side 工作台. */
function ProcessTrace({ events, active, t }: { events: Event[]; active: boolean; t: (k: string) => string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mb-2">
      <button onClick={() => setOpen((o) => !o)}
        className="text-[11px] text-ink-400 hover:text-ink-600 inline-flex items-center gap-1">
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        过程 · {events.length} 步{open ? '' : '（在工作台看详情）'}
      </button>
      {open && <div className="mt-1.5">{events.map((e, i) => <EventChip key={i} ev={e} active={active} t={t} />)}</div>}
    </div>
  );
}

function GeneratedToolCard({ slug, name, meta }: { slug: string; name: string; meta?: Record<string, unknown> }) {
  const [state, setState] = useState<'idle' | 'busy' | 'kept' | 'discarded' | 'reused' | 'error'>('idle');
  const [savedName, setSavedName] = useState(name);
  const [reusedName, setReusedName] = useState('');
  const [showSave, setShowSave] = useState(false);

  async function act(keep: boolean) {
    setState('busy');
    try {
      await api.confirmGeneratedTool(slug, keep);
      setState(keep ? 'kept' : 'discarded');
    } catch {
      setState('error');
    }
  }

  if (state === 'kept') {
    return <div className="text-xs text-emerald-700 bg-emerald-50 ring-1 ring-emerald-100 rounded-lg px-2.5 py-1.5 mb-2">✓ 已保存到工具库:<b>{savedName}</b>(下次可直接调用)</div>;
  }
  if (state === 'discarded') {
    return <div className="text-xs text-ink-500 bg-ink-50 ring-1 ring-ink-200 rounded-lg px-2.5 py-1.5 mb-2">已丢弃临时工具「{name}」。</div>;
  }
  if (state === 'reused') {
    return <div className="text-xs text-emerald-700 bg-emerald-50 ring-1 ring-emerald-100 rounded-lg px-2.5 py-1.5 mb-2">✓ 已改用现有工具「<b>{reusedName}</b>」,新工具已丢弃 —— 下次直接用它即可。</div>;
  }

  return (
    <div className="text-xs bg-white ring-1 ring-brand-200 rounded-lg px-3 py-2.5 mb-2">
      <div className="text-ink-700 mb-2">
        🔧 新工具 <b>{name}</b> 已临时生成并用于本次分析。要保存进工具库供以后复用吗?
      </div>
      <div className="flex items-center gap-2">
        <button
          onClick={() => setShowSave(true)}
          disabled={state === 'busy'}
          className="px-2.5 py-1 rounded-lg bg-brand-600 text-white font-medium hover:bg-brand-700 disabled:opacity-50"
        >
          保存到工具库…
        </button>
        <button
          onClick={() => act(false)}
          disabled={state === 'busy'}
          className="px-2.5 py-1 rounded-lg ring-1 ring-ink-200 text-ink-600 hover:bg-ink-50 disabled:opacity-50"
        >
          丢弃
        </button>
        {state === 'busy' && <Loader2 className="w-3.5 h-3.5 animate-spin text-ink-400" />}
        {state === 'error' && <span className="text-red-600">操作失败,请重试</span>}
      </div>
      {showSave && (
        <SaveToolModal
          slug={slug}
          meta={meta ?? { name }}
          onSaved={(n) => { setSavedName(n); setState('kept'); setShowSave(false); }}
          onReused={(n) => { setReusedName(n); setState('reused'); setShowSave(false); }}
          onCancel={() => setShowSave(false)}
        />
      )}
    </div>
  );
}

function EventChip({ ev, active = true, t }: { ev: Event; active?: boolean; t: (k: string) => string }) {
  if (ev.kind === 'progress') {
    const phase = String(ev.payload.phase ?? '');
    const msg = String(ev.payload.msg ?? '');
    const ok = ev.payload.ok;
    const dt = ev.payload.duration_s;
    const isError = ok === false;
    const inflight = (phase === 'llm_call' || phase === 'tool_start') && active;
    const done = phase === 'llm_done' || phase === 'tool_done';
    const cls = isError
      ? 'text-red-600'
      : done
        ? 'text-ink-400'
        : 'text-ink-500';
    return (
      <div className={`text-[11px] mb-1 font-mono flex items-center gap-1.5 ${cls}`}>
        {inflight && <Loader2 className="w-3 h-3 animate-spin shrink-0" />}
        {done && !isError && <span className="text-emerald-600 shrink-0">✓</span>}
        {isError && <AlertTriangle className="w-3 h-3 shrink-0" />}
        <span className="truncate">{msg}</span>
        {typeof dt === 'number' && done && (
          <span className="text-ink-300 shrink-0">· {dt}s</span>
        )}
      </div>
    );
  }
  if (ev.kind === 'thought') {
    return (
      <div className="text-xs text-ink-500 mb-2 italic">
        💭 {String(ev.payload.text ?? '')}
      </div>
    );
  }
  if (ev.kind === 'tool_call') {
    const action = String(ev.payload.action ?? '');
    const args = ev.payload.args as Record<string, unknown>;
    return (
      <div className="text-xs bg-white rounded-lg ring-1 ring-ink-200 px-2 py-1.5 mb-2 inline-flex items-center gap-2">
        <Wrench className="w-3.5 h-3.5 text-brand-600" />
        <span className="font-mono">{action}</span>
        {args?.slug ? <span className="text-ink-500">→ {String(args.slug)}</span> : null}
      </div>
    );
  }
  if (ev.kind === 'tool_result') {
    const result = ev.payload.result as { status?: string; kind?: string; chart?: ChartSpec; charts?: ChartSpec[]; summary?: Record<string, unknown>; error?: string; tools?: unknown[]; meta?: Record<string, unknown>; registered_slug?: string; derived_dataset?: { id: number; name: string } } | undefined;
    if (!result) return null;
    // An interactive chart the agent generated for this dataset.
    if (result.kind === 'chart' && result.chart) {
      return <ChartPanel spec={result.chart} />;
    }
    // Batch plotting (批量出图): one chart per file / per column, shown in a grid.
    if (result.kind === 'chart_batch' && Array.isArray(result.charts) && result.charts.length > 0) {
      return (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 my-1">
          {result.charts.map((c, i) => (
            <div key={i} className="rounded-xl ring-1 ring-ink-200 bg-white p-2">
              <ChartPanel spec={c} height={260} />
            </div>
          ))}
        </div>
      );
    }
    if (result.tools) {
      return <div className="text-xs text-ink-500 mb-2">📚 {t('chat.found')} {(result.tools as unknown[]).length} {t('chat.tools')}</div>;
    }
    if (result.error) {
      return <div className="text-xs text-red-600 mb-2 bg-red-50 rounded-lg px-2 py-1.5">⚠ {String(result.error).slice(0, 200)}</div>;
    }
    if (result.meta) {
      const toolName = String((result.meta as Record<string, unknown>).name ?? '');
      // Auto-registered draft tool → let the user keep or discard it.
      if (result.registered_slug) {
        return <GeneratedToolCard slug={result.registered_slug} name={toolName} meta={result.meta} />;
      }
      return <div className="text-xs text-ink-500 mb-2">✨ {t('chat.generated')} &quot;{toolName}&quot;{t('chat.awaiting')}</div>;
    }
    if (result.status === 'ok') {
      const summary = result.summary as { rows?: number; type?: string; value?: unknown } | undefined;
      return (
        <div className="text-xs text-ink-500 mb-2">
          ✓ {t('chat.executed')} — {summary?.type === 'dataframe' ? `${summary.rows} ${t('side.rows')}` : summary?.type ?? t('chat.done')}.
          {result.derived_dataset && (
            <span className="text-violet-600"> → 已存为「{result.derived_dataset.name}」(数据集→中间结果可看)</span>
          )}
        </div>
      );
    }
    return null;
  }
  return null;
}

'use client';

import { useEffect, useRef, useState } from 'react';
import { Send, Wrench, MessagesSquare, User, Play, Loader2, AlertTriangle, Upload, Database, PanelRightOpen, ChevronDown, ChevronRight, GitBranch, RotateCcw, Square, ImageIcon, FileText, X, Puzzle, Check } from 'lucide-react';
import Markdown from '@/components/Markdown';
import { AiMark, SourceTag } from '@/components/ui';
import DatasetChart from '@/components/DatasetChart';
import AnalysisIcon from '@/components/AnalysisIcon';
import RecipeThumb, { SampleResultChart } from '@/components/RecipeThumb';
import type { FocusAlgo } from '@/components/AlgorithmsView';
import { runStepsOf, flowFromSteps, type RunStep } from '@/lib/flowSteps';
import { api, streamChat, type ChatMessage, type TemplateStep, type FlowTemplate, type Conversation, type Dataset, type DatasetProfile, type UploadResp, type Skill } from '@/lib/api';
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
  rerunOf?: number;       // server id of the answer this one re-ran (S5)
};

export default function ChatView({
  conversationId,
  onConversationCreated,
  pendingAsk,
  onGoSettings,
  onViewDataset,
  onOpenAlgorithm,
  onOpenInLibrary,
  pendingFill,
  active = true,
  datasetsVersion = 0,
}: {
  conversationId: number | null;
  onConversationCreated: (id: number) => void;
  // Bumped by the datasets view whenever it adds/deletes datasets. ChatView
  // stays mounted while hidden, so without this its picker keeps offering
  // datasets that no longer exist.
  datasetsVersion?: number;
  // A prompt forwarded from the datasets view (a clicked suggestion). When its
  // nonce changes we run it on the given dataset.
  pendingAsk?: { prompt: string; datasetId: number; nonce: number } | null;
  // Shortcut to the Settings tab (e.g. when a "no LLM key" error is shown).
  onGoSettings?: () => void;
  // Open a dataset's full page in the datasets tab ("查看完整表格").
  onViewDataset?: (id: number) => void;
  // Open an algorithm's code editor in 算法库 (an AI-built tool's "在编辑器中打开").
  onOpenAlgorithm?: (slug: string) => void;
  // Open an algorithm in 算法库 with a chat step's params + input prefilled (L1).
  onOpenInLibrary?: (f: Omit<FocusAlgo, 'nonce'>) => void;
  // 「在对话中使用」 from the library: fill the input box (not send).
  pendingFill?: { text: string; datasetId: number | null; nonce: number } | null;
  // Whether the chat tab is the visible one (it stays mounted while hidden).
  active?: boolean;
}) {
  const t = useT();
  const lang = useLangStore((s) => s.lang);
  const [messages, setMessages] = useState<DisplayMsg[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  // Multi-dataset: the set of datasets active in this conversation. The first
  // is the PRIMARY (default target); additional ones are loaded for comparison.
  const [activeDatasets, setActiveDatasets] = useState<number[]>([]);
  // A recipe card clicked while no dataset is selected: the welcome screen asks
  // which data to use, then applies the recipe (see the effect below).
  const [pendingRecipe, setPendingRecipe] = useState<RecipeId | null>(null);
  // Selection is never guessed: the first dataset load restores the user's last
  // EXPLICIT choice (per browser), otherwise nothing is selected.
  const restoredSelRef = useRef(false);
  // Slugs of the user's algorithms that are reviewed (verified). A result from an
  // algorithm NOT in here is flagged as coming from an unreviewed draft. Re-read
  // whenever the chat tab comes back — the user may have saved it in 算法库.
  const [reviewedSlugs, setReviewedSlugs] = useState<Set<string>>(new Set());
  // Skills: the user's ACTIVE skills, and the ones enabled for the next message.
  const [skills, setSkills] = useState<Skill[]>([]);
  const [activeSkills, setActiveSkills] = useState<number[]>([]);
  // Restored after mount (not in the initializer) so server and first client
  // render agree; only persisted once restored, so the restore isn't clobbered.
  const skillsRestored = useRef(false);
  useEffect(() => { setActiveSkills(readIds(SKILLS_KEY)); skillsRestored.current = true; }, []);
  useEffect(() => { if (skillsRestored.current) writeIds(SKILLS_KEY, activeSkills); }, [activeSkills]);
  const toggleSkill = (id: number) => setActiveSkills((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  const [input, setInput] = useState('');
  // Dataset @-mention: typing "@" suggests datasets; picking one makes it the input.
  const [mention, setMention] = useState<{ query: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [pendingParser, setPendingParser] = useState<UploadResp['needs_parser'] | null>(null);
  // Claude-style attachment chip above the input: shows a file the user just
  // pasted / dragged in, with live upload status. Once the upload lands, the
  // dataset is added to the conversation's active-set automatically — the chip
  // is a visual confirmation, NOT a stage-before-send buffer (our uploads
  // create Datasets immediately). ✕ only clears the chip; the Dataset itself
  // stays in the header dropdown until GC'd.
  type StagedAttachment = {
    name: string;
    isImage: boolean;
    previewUrl?: string;   // object URL for image thumb, revoked when cleared
    uploading: boolean;
    dataset?: Dataset;
    error?: string;
  };
  const [stagedAttachment, setStagedAttachment] = useState<StagedAttachment | null>(null);
  function clearStaged() {
    setStagedAttachment((prev) => {
      if (prev?.previewUrl) URL.revokeObjectURL(prev.previewUrl);
      return null;
    });
  }
  // An image attached to the NEXT message for the agent to ANALYZE (chart, plot,
  // diagram) — distinct from stagedAttachment, which uploads a file as a dataset.
  const [chatImage, setChatImage] = useState<{ ref?: string; name: string; previewUrl: string; uploading: boolean; error?: string } | null>(null);
  const chatImageInputRef = useRef<HTMLInputElement>(null);
  function clearChatImage() {
    setChatImage((prev) => { if (prev?.previewUrl) URL.revokeObjectURL(prev.previewUrl); return null; });
  }
  async function attachChatImage(file: File) {
    setError('');
    const previewUrl = URL.createObjectURL(file);
    setChatImage((prev) => { if (prev?.previewUrl) URL.revokeObjectURL(prev.previewUrl); return { name: file.name, previewUrl, uploading: true }; });
    try {
      const r = await api.uploadChatImage(file);
      setChatImage((prev) => prev ? { ...prev, ref: r.ref, uploading: false } : null);
    } catch (e) {
      const msg = (e as Error).message;
      setChatImage((prev) => prev ? { ...prev, uploading: false, error: msg } : null);
      setError(msg);
    }
  }
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
  const wb = useWorkbenchOpen();
  const workbenchOpen = wb.open;
  const setWorkbenchOpen = wb.set;
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
  // Last pendingAsk nonce we've already fired, so re-renders don't resend it.
  const lastAskRef = useRef<number | null>(null);

  function stop() {
    abortRef.current?.abort();
  }

  useEffect(() => {
    refreshDatasets();
  }, []);

  useEffect(() => {
    if (!active) return;
    api.listSkills().then((ss) => {
      const act = ss.filter((x) => x.status === 'active');
      setSkills(act);
      // Drop selections of skills that were deleted / disabled meanwhile.
      setActiveSkills((p) => p.filter((id) => act.some((x) => x.id === id)));
    }).catch(() => {});
    api.listAlgorithms({ source: undefined }).then((as) => {
      setReviewedSlugs(new Set(as.filter((a) => a.source !== 'builtin' && a.verified).map((a) => a.slug)));
    }).catch(() => {});
  }, [active]);

  // A suggestion was clicked in the datasets view → run it here on that dataset.
  useEffect(() => {
    if (!pendingAsk || lastAskRef.current === pendingAsk.nonce) return;
    lastAskRef.current = pendingAsk.nonce;
    const { prompt, datasetId } = pendingAsk;
    refreshDatasets();
    setActiveDatasets([datasetId]);
    send(prompt, [datasetId]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingAsk?.nonce]);

  useEffect(() => {
    if (!pendingFill) return;
    setInput(pendingFill.text);
    if (pendingFill.datasetId != null) setActiveDatasets([pendingFill.datasetId]);
    setTimeout(() => inputAreaRef.current?.focus(), 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingFill?.nonce]);

  async function refreshDatasets() {
    try {
      const list = await api.listDatasets();
      setDatasets(list);
      // Drop selections whose dataset is gone (deleted from the datasets view —
      // possibly as a cascade that took a whole derived subtree). Leaving a dead
      // id selected would also send it as the target of the next message.
      const alive = new Set(list.map((d) => d.id));
      // Never auto-select list[0]: it is often a pipeline intermediate the user
      // didn't pick, and analyzing the wrong data silently is the worst failure.
      setActiveDatasets((prev) => {
        if (!restoredSelRef.current) {
          restoredSelRef.current = true;
          if (prev.length === 0) return readLastSelection().filter((id) => alive.has(id));
        }
        const kept = prev.filter((id) => alive.has(id));
        return kept.length === prev.length ? prev : kept;
      });
    } catch { /* ignore */ }
  }

  // Re-sync when the datasets view reports a change.
  useEffect(() => {
    if (datasetsVersion > 0) refreshDatasets();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetsVersion]);

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
    // Results in this conversation may have been produced elsewhere (a flow run
    // from the 流程 page, a re-run) — refresh the dataset list first so cards
    // don't wrongly show their data as cleaned up.
    refreshDatasets().finally(() => api.listMessages(conversationId).then((msgs: ChatMessage[]) => {
      loadedConvRef.current = conversationId;
      const mapped: DisplayMsg[] = msgs.map((m) => ({
        id: `m_${m.id}`,
        role: m.role as 'user' | 'assistant',
        content: m.content,
        events: (m.meta?.events as Event[] | undefined) ?? undefined,
        rerunOf: typeof m.meta?.rerun_of === 'number' ? (m.meta.rerun_of as number) : undefined,
      }));
      setMessages(mapped);
      if (mapped.length) wb.auto();
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
    }));
  }, [conversationId]);

  useEffect(() => {
    // The home page reads top-down; only a conversation follows its tail.
    if (messages.length === 0) { scrollRef.current?.scrollTo({ top: 0 }); return; }
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  async function handleFileUpload(file: File) {
    setError('');
    setUploading(true);

    // Mount the chip immediately so the user sees feedback within one frame,
    // not after the round-trip. Image files get an inline thumbnail via a
    // local object URL (released when the chip is cleared).
    const isImage = /^image\//.test(file.type) || /\.(png|jpe?g|webp|gif|bmp)$/i.test(file.name);
    const previewUrl = isImage ? URL.createObjectURL(file) : undefined;
    // Revoke any previous preview before overwriting.
    setStagedAttachment((prev) => {
      if (prev?.previewUrl) URL.revokeObjectURL(prev.previewUrl);
      return { name: file.name, isImage, previewUrl, uploading: true };
    });

    try {
      const r = await api.uploadDataset(file);
      if (r.status === 'needs_parser' && r.needs_parser) {
        setPendingParser(r.needs_parser);
        // Parser modal takes over; stagedAttachment can retire.
        clearStaged();
      } else if (r.status === 'ok' && r.dataset) {
        // A multi-sheet Excel returns one dataset per sheet — add & select all.
        const added = r.datasets && r.datasets.length ? r.datasets : [r.dataset];
        const addedIds = new Set(added.map((x) => x.id));
        setDatasets((d) => [...added, ...d.filter((x) => !addedIds.has(x.id))]);
        setActiveDatasets(added.map((x) => x.id));
        // Update chip to "attached" — show rows/cols so the user knows the AI
        // reads the image / file successfully, not just "uploaded".
        setStagedAttachment((prev) => prev
          ? { ...prev, uploading: false, dataset: added[0], name: added[0].name }
          : null);
      }
    } catch (e) {
      const msg = (e as Error).message;
      setError(msg);
      setStagedAttachment((prev) => prev ? { ...prev, uploading: false, error: msg } : null);
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
    if (id === 'custom') {
      setPendingRecipe(null);
      inputAreaRef.current?.focus();
      return;
    }
    if (!ds) {
      // Needs data but none is selected — ask which (Welcome renders the picker).
      setPendingRecipe(id);
      return;
    }
    applyRecipe(id, ds);
  }

  function applyRecipe(id: RecipeId, ds: Dataset) {
    setInput(buildPrompt(id, ds, lang));
    inputAreaRef.current?.focus();
  }

  // Remember the user's explicit selection so the next visit restores it.
  useEffect(() => {
    if (restoredSelRef.current) writeLastSelection(activeDatasets);
  }, [activeDatasets]);

  // A recipe waiting for data runs as soon as a dataset gets selected — from the
  // welcome picker, the top-bar picker, or a fresh upload alike.
  useEffect(() => {
    if (!pendingRecipe) return;
    const ds = datasets.find((d) => d.id === activeDatasets[0]);
    if (!ds) return;
    setPendingRecipe(null);
    applyRecipe(pendingRecipe, ds);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingRecipe, activeDatasets, datasets]);

  // One-click starter: ensure its bundled sample dataset exists (create it from
  // the embedded CSV the first time), then ask its question — so even an empty
  // account can try it instantly. Falls back to filling the box on any failure.
  async function ensureStarterDataset(s: Starter): Promise<Dataset | undefined> {
    let ds = datasets.find((d) => d.name === s.datasetName);
    if (!ds) {
      try {
        const file = new File([s.makeCsv()], `${s.datasetName}.csv`, { type: 'text/csv' });
        const r = await api.uploadDataset(file);
        const created = r.dataset ?? r.datasets?.[0];
        if (created) { ds = created; setDatasets((d) => [created, ...d.filter((x) => x.id !== created.id)]); }
      } catch { /* caller falls back */ }
    }
    return ds;
  }

  async function onStarter(s: Starter) {
    const q = lang === 'zh' ? s.zh.q : s.en.q;
    const ds = await ensureStarterDataset(s);
    if (ds) { setActiveDatasets([ds.id]); send(q, [ds.id]); }
    else { setInput(q); inputAreaRef.current?.focus(); }
  }

  // ── O2: "用示例数据体验一次" ──
  // With a usable model → the full AI flow on the periodic-signal sample. With
  // none (or when the AI fails / takes > 60 s) → a deterministic built-in demo:
  // FFT of the same signal, no AI involved.
  const [llmAvailable, setLlmAvailable] = useState<boolean | null>(null);
  useEffect(() => { api.me().then((u) => setLlmAvailable(!!u.llm_available)).catch(() => setLlmAvailable(false)); }, []);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  useEffect(() => {
    if (conversationId == null) api.listConversations().then(setConversations).catch(() => {});
  }, [conversationId]);
  const [demo, setDemo] = useState<DemoResult | null>(null);
  const [demoBusy, setDemoBusy] = useState(false);
  const [demoErr, setDemoErr] = useState('');
  const [aiDemoAt, setAiDemoAt] = useState<number | null>(null);
  const [nowTick, setNowTick] = useState(0);
  useEffect(() => {
    if (aiDemoAt == null) return;
    const id = setInterval(() => setNowTick(Date.now()), 2000);
    return () => clearInterval(id);
  }, [aiDemoAt]);
  const signalStarter = STARTERS.find((s) => s.datasetName === '示例·周期信号') ?? STARTERS[0];

  async function runBuiltinDemo() {
    setDemoBusy(true); setDemoErr('');
    try {
      const ds = await ensureStarterDataset(signalStarter);
      if (!ds) throw new Error(lang === 'zh' ? '示例数据创建失败' : 'Could not create the sample data');
      const time = ds.schema?.columns?.find((c) => /time/i.test(c.name))?.name;
      const sig = ds.schema?.columns?.find((c) => c.name !== time && /float|int/.test(c.dtype))?.name ?? 'signal';
      // 400 samples over 20 s in the bundled signal → fs ≈ 19.95 Hz
      const fs = 19.95;
      const r = await api.runAlgorithm('fft_frequency_analysis', { columns: [sig], fs_hz: fs, window: 'hann' }, ds.id);
      if (r.status !== 'ok' || r.artifact_id == null) throw new Error(r.error || 'FFT failed');
      const pv = await api.previewArtifact(r.artifact_id, 2000);
      const ampCol = pv.columns.find((c) => c.endsWith('_amplitude')) ?? pv.columns[1];
      const pts = pv.rows.map((row) => ({ f: Number(row.frequency_hz), a: Number(row[ampCol]) })).filter((p) => p.f > 0 && Number.isFinite(p.a));
      const peaks = pts.filter((p, i) => i > 0 && i < pts.length - 1 && p.a >= pts[i - 1].a && p.a >= pts[i + 1].a)
        .sort((x, y) => y.a - x.a).slice(0, 2);
      setDemo({ datasetName: ds.name, artifactId: r.artifact_id, fs, peaks, durationMs: r.duration_ms });
      setAiDemoAt(null);
    } catch (e) { setDemoErr((e as Error).message); }
    finally { setDemoBusy(false); }
  }

  async function runDemo() {
    if (llmAvailable) { setAiDemoAt(Date.now()); await onStarter(signalStarter); }
    else await runBuiltinDemo();
  }
  // Offer the deterministic demo when the AI demo errors or takes too long.
  const lastMsg = messages[messages.length - 1];
  const aiDemoFailed = aiDemoAt != null && !!lastMsg && !lastMsg.pending &&
    !!(lastMsg.events ?? []).find((e) => e.kind === 'final' && (e.payload as { error?: unknown }).error);
  const aiDemoSlow = aiDemoAt != null && busy && (nowTick || Date.now()) - aiDemoAt > 60_000;

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
    // Snapshot & clear the attached image up front: it belongs to THIS message.
    const imgRef = chatImage?.ref ?? null;
    const imgName = chatImage?.name;
    clearChatImage();
    const dsIds = dsOverride ?? activeDatasets;
    setError('');
    setBusy(true);
    wb.auto();   // something to show now — open the workbench unless the user chose otherwise
    setInput('');
    setMention(null);
    // The message is going out — retire the chip. The dataset stays selected
    // in the header dropdown, so the user still sees what's attached to the
    // conversation, but the transient "just added" chip clears out.
    clearStaged();
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
    const userMsg: DisplayMsg = { id: `u_${Date.now()}`, role: 'user', content: userText, datasetLabel: imgName ? `图片 · ${imgName}` : dsLabel };
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
      }, dsIds, ac.signal, imgRef, activeSkills.filter((id) => skills.some((x) => x.id === id)));
      // The turn may have advanced the cross-turn pipeline head — refresh the chip.
      refreshPipeline(convId);
      // Digitizing an image can create a new dataset — refresh so it appears.
      if (imgRef) refreshDatasets();
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
            // Record the failure on the message itself too, so anything that
            // inspects the turn (e.g. the demo fallback) sees it as failed.
            return [...m.slice(0, -1), { ...last, pending: false, content: `**${t('common.error')}** ${errMsg}`,
              events: [...(last.events ?? []), { kind: 'final', payload: { text: errMsg, error: true, source: 'transport' } } as Event] }];
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
  const pickerDatasets = datasets.filter((d) => d.state !== 'cleaned' && (d.kind !== 'derived' || activeDatasets.includes(d.id)));
  // Which datasets still exist — a result card whose derived dataset is gone
  // offers a re-run on the original data (改进清单-3 · S5).
  // Only datasets whose data still exists — a cleaned one makes its card "expired".
  const datasetIds = new Set(datasets.filter((d) => d.state !== 'cleaned').map((d) => d.id));
  const dsById = new Map(datasets.map((d) => [d.id, d] as [number, Dataset]));
  const rerunTargets = new Set(messages.filter((m) => m.rerunOf != null).map((m) => `m_${m.rerunOf}`));
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
          onGoSettings={onGoSettings}
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
        <MessagesSquare className="w-5 h-5 text-brand-600 shrink-0" strokeWidth={1.5} />
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
            onClickUpload={() => fileInputRef.current?.click()}
            onRecipeClick={onRecipeClick}
            onStarter={onStarter}
            pendingRecipe={pendingRecipe}
            onPickDataset={(id) => setActiveDatasets([id])}
            onCancelRecipe={() => setPendingRecipe(null)}
            lang={lang}
            onDemo={runDemo}
            demoBusy={demoBusy}
            demo={demo}
            demoErr={demoErr}
            onGoSettings={onGoSettings}
            onFlowRan={(cid) => onConversationCreated(cid)}
            conversations={conversations}
            onOpenConversation={(cid) => onConversationCreated(cid)}
            onViewDataset={onViewDataset}
          />
        ) : (
          messages.map((m) => (
            <MessageBubble
              key={m.id}
              msg={m}
              t={t}
              liveThought={m.pending ? liveThought : ''}
              turnStartedAt={m.pending ? turnStartedAt : undefined}
              onSuggest={busy ? undefined : (p) => send(p)}
              reviewedSlugs={reviewedSlugs}
              onToolKept={(slug) => setReviewedSlugs((prev) => new Set(prev).add(slug))}
              onOpenAlgorithm={onOpenAlgorithm}
              activeSkills={activeSkills}
              onEnableSkill={(id) => setActiveSkills((p) => (p.includes(id) ? p : [...p, id]))}
              conversationId={conversationId}
              datasetIds={datasetIds}
              dsById={dsById}
              onOpenInLibrary={onOpenInLibrary}
              reran={rerunTargets.has(m.id)}
              onReran={(nm) => {
                setMessages((prev) => [...prev, {
                  id: `m_${nm.id}`, role: 'assistant', content: nm.content,
                  events: (nm.meta?.events as Event[] | undefined) ?? undefined,
                  rerunOf: typeof nm.meta?.rerun_of === 'number' ? (nm.meta.rerun_of as number) : undefined,
                }]);
                refreshDatasets();
              }}
            />
          ))
        )}
        {!isFreshSession && !demo && (aiDemoFailed || aiDemoSlow) && (
          <div className="max-w-3xl mx-auto text-xs text-ink-700 bg-white border border-ink-200 rounded px-3 py-2 flex flex-wrap items-center gap-2">
            {aiDemoSlow && !aiDemoFailed
              ? (lang === 'zh' ? 'AI 响应较慢（超过 60 秒）。' : 'The AI is slow (> 60 s).')
              : (lang === 'zh' ? 'AI 这次没能给出结果。' : 'The AI could not produce a result.')}
            <button type="button" onClick={runBuiltinDemo} disabled={demoBusy}
              className="h-7 px-2.5 rounded border border-ink-300 bg-white hover:bg-ink-50 disabled:opacity-50 inline-flex items-center gap-1.5">
              {demoBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
              {lang === 'zh' ? '先看内置算法演示' : 'See the built-in demo'}
            </button>
            {demoErr && <span className="text-danger-700">{demoErr}</span>}
          </div>
        )}
        {!isFreshSession && demo && <div className="max-w-3xl mx-auto"><DemoResultCard demo={demo} onGoSettings={onGoSettings} lang={lang} /></div>}
        <input
          ref={fileInputRef}
          type="file"
          // Explicit accept hints the OS picker (esp. mobile) and makes it
          // clear images are a first-class source, not just data files.
          // Empty accept-string bug on some Android → list the common ones AND
          // fall back to */* by not restricting further.
          accept=".csv,.tsv,.xlsx,.xls,.parquet,.json,.dat,.tec,.txt,image/png,image/jpeg,image/webp,image/gif,image/bmp"
          className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFileUpload(f); e.target.value = ''; }}
        />
      </div>

      {error && (
        <div className="mx-5 mb-2 px-3 py-2 rounded-lg bg-red-50 text-red-700 text-sm flex items-center gap-2">
          <AlertTriangle className="w-4 h-4" /> {error}
        </div>
      )}

      <div
        className={`border-t bg-white p-4 relative transition [&>*]:max-w-[1600px] [&>*]:mx-auto ${
          dragOver ? 'border-brand-400 ring-2 ring-brand-100 bg-brand-50/40' : 'border-ink-200'
        }`}
        // Drop anywhere in the input area (not just on textarea) so a big
        // drag-target is available for datasets AND screenshots.
        onDragOver={(e) => {
          if (!e.dataTransfer.types.includes('Files')) return;
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={(e) => {
          // Only clear when leaving the actual container, not its children.
          if (e.currentTarget.contains(e.relatedTarget as Node)) return;
          setDragOver(false);
        }}
        onDrop={(e) => {
          if (!e.dataTransfer.files?.length) return;
          e.preventDefault();
          setDragOver(false);
          handleFileUpload(e.dataTransfer.files[0]);
        }}
      >
        {/* Sits right above the input: it says what the NEXT message will run on,
            which is exactly where the user is looking when they type. */}
        <PipelineBar pipeline={pipeline} datasets={datasets} onReset={resetPipeline} />
        {stagedAttachment && (
          <StagedChip
            att={stagedAttachment}
            onRemove={clearStaged}
            onViewDataset={onViewDataset}
          />
        )}
        {chatImage && (
          <div className="mb-2 inline-flex items-center gap-2 rounded-xl ring-1 ring-brand-200 bg-brand-50/40 pl-1.5 pr-2 py-1.5">
            <img src={chatImage.previewUrl} alt={chatImage.name} className="w-9 h-9 rounded object-cover" />
            <div className="text-xs">
              <div className="text-ink-700 max-w-[180px] truncate">{chatImage.name}</div>
              <div className="text-[10.5px] text-ink-400">
                {chatImage.uploading ? '上传中…' : chatImage.error ? '上传失败' : '附图待分析 — 直接提问'}
              </div>
            </div>
            <button onClick={clearChatImage} title="移除图片" className="text-ink-400 hover:text-ink-700 p-0.5">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
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
        <SkillBar skills={skills} active={activeSkills} onToggle={toggleSkill} />
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
            // Paste a screenshot / any file directly from the clipboard.
            // We do NOT preventDefault when the clipboard has text — that lets
            // normal text-paste continue as usual.
            onPaste={(e) => {
              const items = Array.from(e.clipboardData?.items || []);
              const fileItem = items.find((it) => it.kind === 'file');
              if (!fileItem) return;
              const f = fileItem.getAsFile();
              if (!f) return;
              e.preventDefault();
              // An image pasted into CHAT means "analyze this" — stage it for the
              // agent. Non-image files (csv/xlsx) still upload as a dataset.
              if (/^image\//.test(f.type)) attachChatImage(f);
              else handleFileUpload(f);
            }}
            rows={2}
            placeholder={t('chat.placeholder')}
            className="flex-1 border border-ink-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-50 resize-none"
          />
          <input
            ref={chatImageInputRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) attachChatImage(f); e.target.value = ''; }}
          />
          <button
            onClick={() => chatImageInputRef.current?.click()}
            title="附一张图让 AI 分析(曲线图/示意图/照片)"
            disabled={busy}
            className="px-3 py-2 rounded-xl ring-1 ring-ink-200 text-ink-500 hover:bg-ink-50 disabled:opacity-50 self-stretch flex items-center"
          >
            <ImageIcon className="w-4 h-4" />
          </button>
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
          onViewDataset={onViewDataset}
        />
      )}
    </div>
  );
}

/** Claude-style attachment chip above the textarea. Live status while uploading,
 *  row×col preview once the vision/parser flow lands, red error state if the
 *  upload failed. Click ✕ to dismiss (does not delete the persisted dataset). */
function StagedChip({ att, onRemove, onViewDataset }: {
  att: {
    name: string;
    isImage: boolean;
    previewUrl?: string;
    uploading: boolean;
    dataset?: import('@/lib/api').Dataset;
    error?: string;
  };
  onRemove: () => void;
  onViewDataset?: (id: number) => void;
}) {
  const status = att.error
    ? { label: att.error, color: 'text-red-600' }
    : att.uploading
      ? { label: att.isImage ? '视觉模型识别中…' : '正在解析…', color: 'text-ink-500' }
      : att.dataset
        ? { label: `${att.dataset.rows.toLocaleString()} 行 × ${att.dataset.columns} 列 · 已作为当前数据集`, color: 'text-emerald-600' }
        : { label: '已附加', color: 'text-ink-500' };
  const clickable = !!att.dataset && !!onViewDataset;
  return (
    <div className="mb-2 flex items-start gap-2">
      <div
        className={`flex items-center gap-2 max-w-full pr-1 pl-1.5 py-1.5 rounded-xl ring-1 ring-ink-200 bg-white ${
          clickable ? 'hover:ring-brand-300 cursor-pointer' : ''
        } ${att.error ? 'ring-red-200 bg-red-50/50' : ''}`}
        onClick={() => { if (clickable && att.dataset) onViewDataset!(att.dataset.id); }}
        title={clickable ? '打开数据集' : undefined}
      >
        {/* Thumbnail (image preview) or file-type icon */}
        {att.isImage && att.previewUrl ? (
          <img
            src={att.previewUrl}
            alt=""
            className="w-9 h-9 rounded-lg object-cover ring-1 ring-ink-200 shrink-0"
          />
        ) : (
          <div className="w-9 h-9 rounded-lg bg-ink-50 grid place-items-center shrink-0">
            {att.isImage ? <ImageIcon className="w-4 h-4 text-brand-600" /> : <FileText className="w-4 h-4 text-brand-600" />}
          </div>
        )}
        <div className="min-w-0 pr-2">
          <div className="text-xs font-medium text-ink-700 truncate max-w-[240px]">{att.name}</div>
          <div className={`text-[11px] flex items-center gap-1.5 ${status.color}`}>
            {att.uploading && <Loader2 className="w-3 h-3 animate-spin" />}
            <span className="truncate">{status.label}</span>
          </div>
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); onRemove(); }}
          className="ml-1 w-6 h-6 rounded-md grid place-items-center text-ink-400 hover:text-ink-700 hover:bg-ink-50 shrink-0"
          title="从输入框移除(不影响数据集)"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
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
    <div className="mb-2 px-3 py-2 rounded-lg bg-violet-50 ring-1 ring-violet-200 text-[12.5px] text-violet-900 flex items-center gap-2 flex-wrap">
      <GitBranch className="w-4 h-4 shrink-0 text-violet-600" />
      <span className="min-w-0">
        <span className="font-medium">下一条消息将接着上一步的结果继续：</span>
        {entries.map(([dsId, v], i) => {
          const src = datasets.find((d) => String(d.id) === dsId)?.name ?? `#${dsId}`;
          // head_name is "<source> · <step>" — show the step, the source separately.
          const step = v.head_name.startsWith(src + ' · ') ? v.head_name.slice(src.length + 3) : v.head_name;
          return (
            <span key={dsId}>
              {i > 0 && '；'}
              「<b>{step}</b>」<span className="text-violet-600">（基于 {src}，第 {v.steps} 步）</span>
            </span>
          );
        })}
      </span>
      <button onClick={onReset} title="清掉这条处理链，下一条消息改为在原始数据上分析"
        className="ml-auto inline-flex items-center gap-1 px-2 py-1 rounded-md bg-white ring-1 ring-violet-300 hover:bg-violet-100 text-violet-700 shrink-0">
        <RotateCcw className="w-3 h-3" /> 改用原始数据
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

/** Instant, free "认识这份数据" card for the active dataset — the same
 *  deterministic first-read shown in the datasets view, surfaced right here at
 *  the chat's upload entry point so dropping a file gives immediate context. */
function ChatProfileCard({ ds, lang }: { ds: Dataset; lang: 'en' | 'zh' }) {
  const [p, setP] = useState<DatasetProfile | null>(null);
  useEffect(() => {
    setP(null);
    let alive = true;
    api.profileDataset(ds.id).then((r) => { if (alive) setP(r); }).catch(() => {});
    return () => { alive = false; };
  }, [ds.id]);
  if (!p) return null;
  return (
    <div className="mb-4 rounded-md bg-white border border-ink-200 overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2 border-b border-ink-150 bg-ink-50 text-[13px] font-semibold text-ink-800">
        {lang === 'zh' ? '数据概况' : 'Data profile'}
        <span className="text-xs font-normal text-ink-500">{lang === 'zh' ? '自动生成' : 'auto-generated'}</span>
      </div>
      <div className="px-4 py-3">
        <p className="text-sm text-ink-900 leading-relaxed">{p.headline}</p>
        {p.facts.length > 0 && (
          <div className="mt-2.5 flex flex-wrap gap-2">
            {p.facts.map((f, i) => (
              <span key={i} className="inline-flex items-center text-xs text-ink-700 bg-ink-50 border border-ink-200 rounded-sm px-2 py-0.5">{f}</span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/** What each recipe card gives you — shown under its question (O3). */
const RECIPE_OUTCOME: Record<string, { zh: string; en: string }> = {
  smooth: { zh: '得到：平滑后的曲线 + 前后对比', en: 'You get: a smoothed curve + before/after' },
  drivers: { zh: '得到：各因素的影响排序', en: 'You get: factors ranked by influence' },
  fit: { zh: '得到：拟合公式、R² 和预测曲线', en: 'You get: fitted formula, R², prediction curve' },
  outliers: { zh: '得到：异常点清单和位置', en: 'You get: list and location of outliers' },
  corr: { zh: '得到：相关系数矩阵', en: 'You get: a correlation matrix' },
  pca: { zh: '得到：2–3 个主成分及解释度', en: 'You get: 2–3 components + variance explained' },
  custom: { zh: '得到：按你的问题选方法', en: 'You get: a method picked for your question' },
};

export type DemoResult = {
  datasetName: string;
  artifactId: number;
  fs: number;
  peaks: { f: number; a: number }[];
  durationMs: number;
};

/** The deterministic demo (no AI): FFT of the sample periodic signal, with the
 *  dominant frequencies spelled out and the full provenance underneath. */
function DemoResultCard({ demo, onGoSettings, lang }: { demo: DemoResult; onGoSettings?: () => void; lang: 'en' | 'zh' }) {
  const zh = lang === 'zh';
  const [p1, p2] = demo.peaks;
  return (
    <div className="rounded-md bg-white border border-ink-200 border-l-[3px] border-l-brand-600 overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 px-4 py-2.5 border-b border-ink-150">
        <span className="text-sm font-semibold text-ink-900">{zh ? '示例结果 · 周期信号的频谱' : 'Demo · spectrum of a periodic signal'}</span>
        <SourceTag kind="builtin" />
        <span className="text-xs text-ink-500">{zh ? '内置算法直接计算，不经过 AI' : 'computed by a built-in algorithm, no AI'}</span>
      </div>
      <div className="px-4 py-3 text-sm text-ink-800 leading-relaxed">
        {p1 ? (zh
          ? <>这段信号的主频约 <b className="font-mono">{p1.f.toFixed(2)} Hz</b>{p2 ? <>，另有一个 <b className="font-mono">{p2.f.toFixed(2)} Hz</b> 的次要分量</> : null}。</>
          : <>Dominant frequency ≈ <b className="font-mono">{p1.f.toFixed(2)} Hz</b>{p2 ? <>, with a secondary component at <b className="font-mono">{p2.f.toFixed(2)} Hz</b></> : null}.</>)
          : (zh ? '已算出频谱。' : 'Spectrum computed.')}
      </div>
      <div className="px-2 pb-2"><DatasetChart artifactId={demo.artifactId} name={zh ? '幅值谱' : 'Amplitude spectrum'} height={260} /></div>
      <div className="px-4 py-2 border-t border-ink-150 bg-ink-50 font-mono text-[11px] text-ink-600 flex flex-wrap gap-x-4 gap-y-1">
        <span>fft_frequency_analysis</span><span>fs_hz={demo.fs}</span><span>window=hann</span>
        <span>{zh ? '输入' : 'input'} {demo.datasetName}</span><span>{demo.durationMs} ms</span>
      </div>
      <div className="px-4 py-2.5 border-t border-ink-150 text-xs text-ink-600 flex flex-wrap items-center gap-2">
        {zh ? '配置大模型后，可以直接用大白话提问，AI 会自己挑算法、调参数。' : 'Configure a model to ask in plain language — the AI picks the algorithm and parameters.'}
        {onGoSettings && <button type="button" onClick={onGoSettings} className="underline text-brand-700">{zh ? '去设置' : 'Settings'}</button>}
      </div>
    </div>
  );
}

function Welcome({
  t, hasData, datasets, activeDs, activeIds, uploading, onClickUpload, onRecipeClick, onStarter,
  pendingRecipe, onPickDataset, onCancelRecipe, lang, onDemo, demoBusy, demo, demoErr, onGoSettings,
  onFlowRan, conversations, onOpenConversation, onViewDataset,
}: {
  t: (k: string) => string;
  hasData: boolean;
  datasets: Dataset[];
  activeDs: Dataset | null;
  activeIds: number[];
  uploading: boolean;
  dragOver: boolean;
  onClickUpload: () => void;
  onRecipeClick: (id: RecipeId) => void;
  onStarter: (s: Starter) => void;
  pendingRecipe: RecipeId | null;
  onPickDataset: (id: number) => void;
  onCancelRecipe: () => void;
  lang: 'en' | 'zh';
  onDemo: () => void;
  demoBusy: boolean;
  demo: DemoResult | null;
  demoErr: string;
  onGoSettings?: () => void;
  onFlowRan: (conversationId: number) => void;
  conversations: Conversation[];
  onOpenConversation: (id: number) => void;
  onViewDataset?: (id: number) => void;
}) {
  const zh = lang === 'zh';
  const sources = datasets.filter((d) => d.kind !== 'derived')
    .sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? '') || b.id - a.id);
  const pendingTitle = pendingRecipe ? t(RECIPES.find((r) => r.id === pendingRecipe)?.titleKey ?? '') : '';
  const recipes = RECIPES.filter((r) => r.id !== 'custom');
  // The user's most recent result (a derived dataset produced by a recorded run).
  const recent = datasets
    .filter((d) => d.kind === 'derived' && d.state !== 'cleaned' && d.origin?.code)
    .sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? '') || b.id - a.id)[0] ?? null;
  return (
    <div className="mx-auto max-w-[1600px] grid grid-cols-1 min-[1100px]:grid-cols-[minmax(0,1fr)_320px] min-[1700px]:grid-cols-[minmax(0,1fr)_380px] gap-5 items-start">
      {/* ── left: start an analysis ── */}
      <div className="min-w-0">
        <div className="rounded-md border border-ink-200 bg-white px-5 py-4 flex flex-wrap items-center gap-x-6 gap-y-3">
          <div className="min-w-0 flex-1">
            <h2 className="text-xl font-semibold text-ink-900">{zh ? '工程试验数据的分析助手' : 'An analysis assistant for engineering test data'}</h2>
            <p className="mt-1 text-sm text-ink-600">{zh ? '清洗、平滑、频谱、拟合、找主因、找异常——不用先学算法，每个结果都写明用了什么方法和参数。' : 'Clean, smooth, spectra, fits, key drivers, outliers — no need to know the algorithms; every result states its method and parameters.'}</p>
            <div className="mt-2.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-600">
              {(zh ? ['放入数据', '用大白话提问，或点下面一个分析', '得到带来源、可复现、可导出的结果'] : ['Bring in data', 'Ask in plain words, or pick an analysis below', 'Get reproducible results with provenance']).map((s, i) => (
                <span key={i} className="inline-flex items-center gap-1.5">
                  {i > 0 && <span className="text-ink-400">→</span>}
                  <span className="w-[18px] h-[18px] rounded-sm bg-ink-150 text-ink-700 grid place-items-center font-mono text-[11px]">{i + 1}</span>{s}
                </span>
              ))}
            </div>
          </div>
          <div className="flex flex-col gap-2 shrink-0">
            <button type="button" onClick={onDemo} disabled={demoBusy}
              className="h-9 px-4 rounded border border-brand-600 bg-brand-600 text-white text-sm font-medium hover:bg-brand-700 disabled:opacity-60 inline-flex items-center justify-center gap-2">
              {demoBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" strokeWidth={1.75} />}
              {zh ? '用示例数据体验一次' : 'Try it with sample data'}
            </button>
            <button type="button" onClick={onClickUpload}
              className="h-9 px-4 rounded border border-ink-300 bg-white text-ink-800 text-sm hover:bg-ink-50 inline-flex items-center justify-center gap-2">
              {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" strokeWidth={1.5} />}
              {zh ? '上传我的数据' : 'Upload my data'}
            </button>
          </div>
        </div>
        {demoErr && <div className="mt-2 text-xs text-danger-700">{demoErr}</div>}

        {/* analyses, each with a schematic of what you get */}
        <section className="mt-5">
          <div className="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h3 className="text-sm font-semibold text-ink-900">{zh ? '从一个问题开始' : 'Start from a question'}</h3>
            <span className="text-xs text-ink-500">
              {pendingRecipe
                ? <span className="text-brand-700">{zh ? `「${pendingTitle}」需要一份数据 —— 在右侧「我的数据」里点一份。` : `"${pendingTitle}" needs data — pick one under My data.`}
                    <button type="button" onClick={onCancelRecipe} className="ml-2 text-ink-500 hover:text-ink-800">{zh ? '取消' : 'Cancel'}</button></span>
                : activeDs
                  ? <>{zh ? '点一下就在当前数据上分析 · 当前数据：' : 'Runs on the current data · '}<span className="font-mono text-ink-700">{activeDs.name}</span>{activeIds.length > 1 ? (zh ? ` 等 ${activeIds.length} 份` : ` +${activeIds.length - 1}`) : ''}</>
                  : (zh ? '先在右侧选一份数据，或直接点一个分析' : 'Pick data on the right, or just tap an analysis')}
            </span>
          </div>
          <div className="grid grid-cols-2 min-[1300px]:grid-cols-3 gap-3">
            {recipes.map((r) => {
              const out = RECIPE_OUTCOME[r.id];
              return (
                <button key={r.id} type="button" onClick={() => onRecipeClick(r.id)}
                  className={`text-left rounded-md overflow-hidden bg-white transition-colors border ${pendingRecipe === r.id ? 'border-brand-600 ring-1 ring-brand-600' : 'border-ink-200 hover:border-brand-400'}`}>
                  <RecipeThumb id={r.id} />
                  <div className="px-3 pt-2.5 pb-3">
                    <div className="text-sm font-medium text-ink-900">{t(r.titleKey)}</div>
                    <div className="text-xs text-ink-500 mt-0.5 leading-snug">{t(r.bodyKey)}</div>
                    {out && <div className="text-xs text-ink-700 mt-1.5">{zh ? out.zh : out.en}</div>}
                  </div>
                </button>
              );
            })}
          </div>
        </section>

        {/* what a result looks like: the demo, the user's latest result, or a sample */}
        <section className="mt-5">
          <div className="mb-2 flex flex-wrap items-baseline gap-x-3">
            <h3 className="text-sm font-semibold text-ink-900">{demo ? (zh ? '示例结果' : 'Demo result') : recent ? (zh ? '最近的结果' : 'Latest result') : (zh ? '你会得到这样的结果' : 'You get results like this')}</h3>
            {!demo && !recent && <span className="text-xs text-ink-500">{zh ? '示例 · 跑过分析后这里换成你最近的一个结果' : 'Sample · replaced by your latest result once you run an analysis'}</span>}
          </div>
          {demo ? <DemoResultCard demo={demo} onGoSettings={onGoSettings} lang={lang} />
            : recent ? <RecentResultCard ds={recent} onOpenConversation={onOpenConversation} onViewDataset={onViewDataset} lang={lang} />
            : <SampleResultCard lang={lang} />}
        </section>

        {!hasData && (
          <section className="mt-5">
            <h3 className="mb-2 text-sm font-semibold text-ink-900">{zh ? '更多示例（自带数据）' : 'More samples (data included)'}</h3>
            <div className="grid grid-cols-2 gap-3">
              {STARTERS.map((s) => {
                const x = zh ? s.zh : s.en;
                return (
                  <button key={s.datasetName} onClick={() => onStarter(s)}
                    className="text-left rounded-md p-3 border border-ink-200 bg-white hover:border-brand-400 hover:bg-ink-50 transition-colors">
                    <div className="font-medium text-sm">{x.t}</div>
                    <div className="text-xs text-ink-500 mt-1 leading-snug line-clamp-2">{x.q}</div>
                  </button>
                );
              })}
            </div>
          </section>
        )}
      </div>

      {/* ── right: my work ── */}
      <aside className="flex flex-col gap-3 min-w-0">
        <div className={`rounded-md border bg-white ${pendingRecipe ? 'border-brand-600 ring-1 ring-brand-600' : 'border-ink-200'}`}>
          <div className="flex items-center gap-2 px-3.5 py-2.5 border-b border-ink-150">
            <span className="text-sm font-semibold text-ink-900">{zh ? '我的数据' : 'My data'}</span>
            <button type="button" onClick={onClickUpload} className="ml-auto h-7 px-2.5 rounded border border-ink-300 bg-white text-xs text-ink-800 hover:bg-ink-50 inline-flex items-center gap-1.5">
              <Upload className="w-3.5 h-3.5" strokeWidth={1.5} /> {zh ? '上传' : 'Upload'}
            </button>
          </div>
          <ul className="p-1.5 space-y-0.5 max-h-[260px] overflow-y-auto scroll-hide">
            {sources.length === 0 && <li className="px-2 py-3 text-xs text-ink-500">{zh ? '还没有数据。上传一份，或点「用示例数据体验一次」。' : 'No data yet — upload one, or try the sample.'}</li>}
            {sources.slice(0, 8).map((d) => {
              const cur = activeIds.includes(d.id);
              return (
                <li key={d.id}>
                  <button type="button" onClick={() => onPickDataset(d.id)} title={zh ? '选为当前分析的数据' : 'Use for the next analysis'}
                    className={`w-full text-left flex items-center gap-2 px-2 py-1.5 rounded ${cur ? 'bg-brand-50 ring-1 ring-brand-100' : 'hover:bg-ink-50'}`}>
                    <Database className="w-3.5 h-3.5 text-brand-600 shrink-0" strokeWidth={1.5} />
                    <span className="min-w-0 flex flex-col">
                      <span className="truncate text-[13px] text-ink-900">{d.name}</span>
                      <span className="font-mono text-[11px] text-ink-500">{d.rows.toLocaleString()} × {d.columns}{cur ? (zh ? ' · 当前' : ' · current') : ''}</span>
                    </span>
                    <span className="ml-auto text-[11px] text-ink-500 shrink-0">{shortDate(d.created_at)}</span>
                  </button>
                </li>
              );
            })}
          </ul>
          <div className="mx-2 mb-2 rounded border border-dashed border-ink-300 px-2 py-1.5 text-center text-[11px] text-ink-500">
            {zh ? '把文件拖到页面任意位置即可上传 · CSV / Excel / 表格截图' : 'Drop files anywhere on the page · CSV / Excel / table screenshots'}
          </div>
        </div>

        <div className="rounded-md border border-ink-200 bg-white">
          <div className="px-3.5 py-2.5 border-b border-ink-150 text-sm font-semibold text-ink-900">{zh ? '最近的分析' : 'Recent analyses'}</div>
          <ul className="p-1.5 space-y-0.5">
            {conversations.length === 0 && <li className="px-2 py-3 text-xs text-ink-500">{zh ? '还没有分析记录。点左侧一个问题，或在下面直接提问。' : 'No analyses yet — tap a question or just ask below.'}</li>}
            {conversations.slice(0, 5).map((c) => {
              const results = datasets.filter((d) => d.origin?.conversation?.id === c.id && d.state !== 'cleaned');
              const expiring = results.filter((d) => !d.kept && d.expires_at && (new Date(d.expires_at.endsWith('Z') || /[+-]\d\d:\d\d$/.test(d.expires_at) ? d.expires_at : d.expires_at + 'Z').getTime() - Date.now()) / 86_400_000 <= 3).length;
              return (
                <li key={c.id}>
                  <button type="button" onClick={() => onOpenConversation(c.id)} className="w-full text-left flex items-center gap-2 px-2 py-1.5 rounded hover:bg-ink-50">
                    <span className="min-w-0 flex flex-col">
                      <span className="truncate text-[13px] text-ink-900">{c.title}</span>
                      <span className="text-[11px] text-ink-500">
                        {results.length > 0 ? (zh ? `${results.length} 个结果` : `${results.length} results`) : (zh ? '对话' : 'chat')}
                        {expiring > 0 && <span className="ml-1.5 px-1 rounded-sm border border-warning-200 bg-warning-50 text-warning-700">{zh ? `${expiring} 份将清理` : `${expiring} expiring`}</span>}
                      </span>
                    </span>
                    <span className="ml-auto text-[11px] text-ink-500 shrink-0">{shortDate(c.created_at)}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>

        <HomeFlows activeDs={activeDs} onRan={onFlowRan} lang={lang} />
      </aside>
    </div>
  );
}

/** "今天 14:32" / "11-08" in the viewer's time zone. */
function shortDate(iso?: string | null): string {
  if (!iso) return '';
  const d = new Date(iso.endsWith('Z') || /[+-]\d\d:\d\d$/.test(iso) ? iso : iso + 'Z');
  if (Number.isNaN(d.getTime())) return '';
  const p = (n: number) => String(n).padStart(2, '0');
  const today = new Date();
  return d.toDateString() === today.toDateString() ? `今天 ${p(d.getHours())}:${p(d.getMinutes())}` : `${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** Static sample of what a finished analysis looks like (until the user has one). */
function SampleResultCard({ lang }: { lang: 'en' | 'zh' }) {
  const zh = lang === 'zh';
  return (
    <div className="rounded-md border border-ink-200 bg-white overflow-hidden">
      <div className="flex items-center gap-2.5 px-3.5 py-2 border-b border-ink-150 text-[13px]">
        <span className="font-mono text-xs text-ink-500">R-0012.2</span>
        <span className="font-semibold text-ink-900">{zh ? '放电曲线平滑与容量衰减' : 'Discharge curves: smoothing & capacity fade'}</span>
        <SourceTag kind="builtin" />
        <span className="ml-auto text-xs text-ink-500">{zh ? '示例' : 'sample'}</span>
      </div>
      <div className="grid grid-cols-1 min-[1300px]:grid-cols-[1.3fr_1fr]">
        <div className="px-2 py-1.5"><SampleResultChart /></div>
        <div className="border-t min-[1300px]:border-t-0 min-[1300px]:border-l border-ink-150">
          <table className="w-full text-xs">
            <thead><tr className="bg-ink-50 text-ink-600"><th className="text-left font-medium px-3.5 py-1.5">{zh ? '指标' : 'Metric'}</th><th className="text-right font-medium px-3.5">{zh ? '第 1 圈' : 'Cycle 1'}</th><th className="text-right font-medium px-3.5">{zh ? '第 50 圈' : 'Cycle 50'}</th><th className="text-right font-medium px-3.5">{zh ? '变化' : 'Δ'}</th></tr></thead>
            <tbody className="font-mono">
              {[['放电容量 (Ah)', '2.310', '2.190', '−5.2 %'], ['平台电压 (V)', '3.652', '3.648', '−4 mV'], ['内阻 (mΩ)', '18.4', '21.0', '+14 %']].map((r) => (
                <tr key={r[0]} className="border-t border-ink-150"><td className="px-3.5 py-1.5 font-sans">{r[0]}</td><td className="text-right px-3.5">{r[1]}</td><td className="text-right px-3.5">{r[2]}</td><td className="text-right px-3.5">{r[3]}</td></tr>
              ))}
            </tbody>
          </table>
          <div className="px-3.5 py-2 border-t border-ink-150 text-xs text-ink-700 leading-relaxed">{zh ? '结论：容量衰减 5.2 %，平台电压基本不变，内阻上升是主要原因。' : 'Capacity fades 5.2 %; plateau voltage is stable; rising resistance is the main cause.'}</div>
        </div>
      </div>
      <div className="px-3.5 py-1.5 border-t border-ink-150 bg-ink-50 font-mono text-[11px] text-ink-600 flex flex-wrap gap-x-4 gap-y-1">
        <span>savgol_filter v1.2</span><span>window=11 order=3</span><span>{zh ? '输入' : 'input'} cell_A12_cycles.csv</span><span>0.82 s</span>
      </div>
    </div>
  );
}

/** The user's most recent result: chart of the data + where it came from. */
function RecentResultCard({ ds, onOpenConversation, onViewDataset, lang }: {
  ds: Dataset; onOpenConversation: (id: number) => void; onViewDataset?: (id: number) => void; lang: 'en' | 'zh';
}) {
  const zh = lang === 'zh';
  const o = ds.origin;
  return (
    <div className="rounded-md border border-ink-200 bg-white overflow-hidden">
      <div className="flex flex-wrap items-center gap-2.5 px-3.5 py-2 border-b border-ink-150 text-[13px]">
        {o?.code && <span className="font-mono text-xs text-ink-500">{o.code}</span>}
        <span className="font-semibold text-ink-900 truncate">{ds.name}</span>
        <span className="ml-auto text-xs text-ink-500">{shortDate(ds.created_at)}</span>
      </div>
      <div className="px-2 py-1"><DatasetChart datasetId={ds.id} name={ds.name} height={220} /></div>
      <div className="px-3.5 py-1.5 border-t border-ink-150 bg-ink-50 text-[11px] text-ink-600 flex flex-wrap items-center gap-x-4 gap-y-1">
        {o?.algorithm && <span className="font-mono">{o.algorithm.slug}{o.algorithm.version != null ? ` v${o.algorithm.version}` : ''}</span>}
        <span className="font-mono">{ds.rows.toLocaleString()} × {ds.columns}</span>
        <span className="ml-auto flex gap-3">
          {o?.conversation?.exists && <button type="button" onClick={() => onOpenConversation(o.conversation!.id)} className="text-brand-700 hover:underline">{zh ? '回到对话' : 'Open chat'}</button>}
          {onViewDataset && <button type="button" onClick={() => onViewDataset(ds.id)} className="text-brand-700 hover:underline">{zh ? '查看数据' : 'View data'}</button>}
        </span>
      </div>
    </div>
  );
}

/** My flows — run one on the current data without the AI (L4). */
function HomeFlows({ activeDs, onRan, lang }: { activeDs: Dataset | null; onRan: (conversationId: number) => void; lang: 'en' | 'zh' }) {
  const zh = lang === 'zh';
  const [tpls, setTpls] = useState<FlowTemplate[]>([]);
  const [busy, setBusy] = useState<number | null>(null);
  const [err, setErr] = useState('');
  useEffect(() => { api.listTemplates().then((t) => setTpls(t.filter((x) => x.n_steps > 0))).catch(() => {}); }, []);
  async function run(id: number) {
    if (!activeDs) { setErr(zh ? '先在「我的数据」里选一份数据' : 'Pick the data first'); return; }
    setBusy(id); setErr('');
    try { const r = await api.runTemplateInChat(id, activeDs.id); onRan(r.conversation_id); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(null); }
  }
  return (
    <div className="rounded-md border border-ink-200 bg-white">
      <div className="flex items-baseline gap-2 px-3.5 py-2.5 border-b border-ink-150">
        <span className="text-sm font-semibold text-ink-900">{zh ? '我的流程' : 'My flows'}</span>
        <span className="ml-auto text-[11px] text-ink-500">{zh ? '不经过 AI，在当前数据上重跑' : 'Re-run on the current data, no AI'}</span>
      </div>
      <ul className="p-1.5 space-y-0.5">
        {tpls.length === 0 && <li className="px-2 py-3 text-xs text-ink-500">{zh ? '还没有流程。在对话回答末尾点「存为流程」即可保存。' : 'No flows yet — use 「存为流程」 under an answer.'}</li>}
        {tpls.slice(0, 5).map((t) => (
          <li key={t.id} className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-ink-50">
            <span className="min-w-0 flex flex-col">
              <span className="truncate text-[13px] text-ink-900">{t.name}</span>
              <span className="text-[11px] text-ink-500">{t.n_steps} {zh ? '步' : 'steps'}</span>
            </span>
            <button type="button" onClick={() => run(t.id)} disabled={busy != null}
              className="ml-auto h-7 px-2.5 rounded border border-ink-300 bg-white text-xs text-ink-800 hover:bg-ink-100 disabled:opacity-50 inline-flex items-center gap-1.5 shrink-0">
              {busy === t.id && <Loader2 className="w-3.5 h-3.5 animate-spin" />}{zh ? '运行' : 'Run'}
            </button>
          </li>
        ))}
      </ul>
      {err && <div className="px-3.5 pb-2 text-xs text-danger-700">{err}</div>}
    </div>
  );
}


function inputLabel(s: RunStep, steps: RunStep[], dsById?: Map<number, Dataset>): string {
  const inp = s.prov.input;
  if (!inp) return '输入未知';
  if (inp.kind === 'dataset') {
    const name = dsById?.get(inp.dataset_id)?.name ?? `数据集 #${inp.dataset_id}`;
    return inp.prior_turn ? `上一轮的结果「${name}」` : `原始数据「${name}」`;
  }
  const k = steps.findIndex((x) => x.prov.step === inp.step);
  return k >= 0 ? `第 ${k + 1} 步的结果` : '更早一步的结果';
}

function AnswerSteps({ steps, excluded, dsById, onOpenInLibrary }: {
  steps: RunStep[]; excluded: number; dsById?: Map<number, Dataset>;
  onOpenInLibrary?: (f: Omit<FocusAlgo, 'nonce'>) => void;
}) {
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [err, setErr] = useState('');
  const flow = flowFromSteps(steps);
  const okCount = steps.filter((s) => s.ok).length;
  const [name, setName] = useState('');

  function openStep(s: RunStep) {
    if (!onOpenInLibrary) return;
    const notes: string[] = [];
    let datasetId: number | null = null;
    const inp = s.prov.input;
    if (inp?.kind === 'dataset') {
      if (dsById?.has(inp.dataset_id)) datasetId = inp.dataset_id;
      else notes.push('这一步的输入数据已删除，只预填了参数。');
    } else if (inp?.kind === 'step') {
      const src = steps.find((x) => x.prov.step === inp.step);
      if (src?.derived && dsById?.has(src.derived.id)) datasetId = src.derived.id;
      else notes.push('这一步的输入（前一步的结果）已清理，只预填了参数。');
    }
    if (s.prov.algorithm.source && s.prov.algorithm.source !== 'builtin') notes.push('自定义算法如果含随机性，结果可能与对话略有不同。');
    onOpenInLibrary({ slug: s.prov.algorithm.slug, params: s.prov.params, datasetId, notes, expectVersion: s.prov.algorithm.version ?? null });
  }

  async function save() {
    if (!flow.steps) return;
    setSaving(true); setErr('');
    try {
      const start = flow.startId != null ? dsById?.get(flow.startId)?.name : undefined;
      const nm = name.trim() || `${start ?? '对话'} 分析流程`;
      await api.createTemplate(nm, flow.steps, '从对话保存');
      setSaved(nm); setOpen(false);
    } catch (e) { setErr((e as Error).message); }
    finally { setSaving(false); }
  }

  return (
    <div className="mt-3 pt-3 border-t border-ink-150 text-xs">
      <div className="text-ink-600 font-medium mb-1">本次分析步骤</div>
      <ol className="space-y-0.5">
        {steps.map((s, i) => (
          <li key={i} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <span className="font-mono text-ink-500 w-4 text-right">{i + 1}</span>
            {onOpenInLibrary
              ? <button type="button" onClick={() => openStep(s)} className="text-brand-700 hover:underline" title="在算法库打开，带上这一步的参数和输入">{s.prov.label ?? s.prov.algorithm.slug}</button>
              : <span className="text-ink-800">{s.prov.label ?? s.prov.algorithm.slug}</span>}
            {s.prov.algorithm.version != null && <span className="font-mono text-ink-500">v{s.prov.algorithm.version}</span>}
            <span className="text-ink-500">输入：{inputLabel(s, steps, dsById)}</span>
            {s.prov.output_role === 'report' && <span className="text-ink-500">· 报告</span>}
            {!s.ok && <span className="text-danger-700">· 失败</span>}
          </li>
        ))}
      </ol>
      {okCount >= 2 && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {saved
            ? <span className="text-success-700">已保存为流程「{saved}」，可在「流程」页换数据重跑。</span>
            : <>
                <span className="text-ink-600">本次共 {okCount} 步</span>
                <button type="button" onClick={() => setOpen((v) => !v)}
                  className="h-7 px-2.5 rounded border border-ink-300 bg-white text-ink-800 hover:bg-ink-50">存为流程，下次换数据一键重跑</button>
              </>}
        </div>
      )}
      {open && (
        <div className="mt-2 rounded border border-ink-200 bg-ink-50 p-3 space-y-2">
          {flow.reason ? (
            <div className="text-ink-700">{flow.reason}</div>
          ) : (
            <>
              <div className="text-ink-700">将保存以下 {flow.steps!.length} 步，每步的输入按这次实际的依赖记录：</div>
              <ol className="space-y-0.5">
                {flow.steps!.map((st, i) => (
                  <li key={i} className="flex gap-2"><span className="font-mono text-ink-500 w-4 text-right">{i + 1}</span>
                    <span className="text-ink-800">{st.label}</span>
                    <span className="text-ink-500">输入：{st.input === 'start' ? '起始数据' : `第 ${(st.input as number) + 1} 步的结果`}{st.output_role === 'report' ? ' · 报告' : ''}</span>
                  </li>
                ))}
              </ol>
              {excluded > 0 && <div className="text-ink-500">画图、生成算法等 {excluded} 个步骤不会保存进流程。</div>}
              <div className="flex flex-wrap items-center gap-2">
                <input value={name} onChange={(e) => setName(e.target.value)} placeholder="流程名称（可空）"
                  className="h-7 border border-ink-300 rounded px-2 bg-white text-xs w-56" />
                <button type="button" onClick={save} disabled={saving}
                  className="h-7 px-2.5 rounded border border-brand-600 bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50">
                  {saving ? '保存中…' : '保存'}
                </button>
                <button type="button" onClick={() => setOpen(false)} className="h-7 px-2 text-ink-600 hover:text-ink-900">取消</button>
              </div>
            </>
          )}
          {err && <div className="text-danger-700">{err}</div>}
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

function MessageBubble({ msg, t, liveThought = '', turnStartedAt, onSuggest, reviewedSlugs, onToolKept, onOpenAlgorithm, activeSkills, onEnableSkill, conversationId, datasetIds, onReran, reran = false, dsById, onOpenInLibrary }: {
  msg: DisplayMsg; t: (k: string) => string; liveThought?: string; turnStartedAt?: number; onSuggest?: (prompt: string) => void;
  reviewedSlugs?: Set<string>; onToolKept?: (slug: string) => void; onOpenAlgorithm?: (slug: string) => void;
  activeSkills?: number[]; onEnableSkill?: (id: number) => void;
  conversationId?: number | null; datasetIds?: Set<number>; onReran?: (m: ChatMessage) => void; reran?: boolean;
  dsById?: Map<number, Dataset>; onOpenInLibrary?: (f: Omit<FocusAlgo, 'nonce'>) => void;
}) {
  if (msg.role === 'user') {
    return (
      <div className="flex gap-3 max-w-3xl mx-auto">
        <div className="w-7 h-7 shrink-0 rounded bg-ink-150 text-ink-600 grid place-items-center"><User className="w-4 h-4" strokeWidth={1.5} /></div>
        <div className="flex-1 min-w-0 bg-white rounded-md border border-ink-200 px-4 py-3 prose-tight text-sm">
          {msg.datasetLabel && (
            <div className="inline-flex items-center gap-1 text-[11px] font-mono text-brand-700 bg-brand-50 border border-brand-100 rounded-sm px-1.5 py-px mb-2">
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
    if (e.kind === 'skills') return false;  // rendered as the "使用了 skill" label below
    if (e.kind !== 'progress') return true;
    const phase = String(e.payload.phase ?? '');
    if (phase === 'codegen') return false;  // rendered as one live build card below
    return !((phase === 'llm_call' || phase === 'tool_start') && resolved.has(i));
  });
  // An AI tool build still in flight: its stage events after the last finished build.
  const lastBuildDone = events.map((e) => isGenerateResult(e)).lastIndexOf(true);
  const liveBuild = events.filter((e, i) => i > lastBuildDone && e.kind === 'progress' && e.payload.phase === 'codegen');
  // Results computed by algorithms nobody has reviewed yet (not saved/verified).
  const drafts = new Map<string, string>();
  for (const e of events) {
    const d = e.kind === 'tool_result' ? (e.payload.result as { draft_tool?: { slug: string; name: string } } | undefined)?.draft_tool : undefined;
    if (d && !reviewedSlugs?.has(d.slug)) drafts.set(d.slug, d.name);
  }
  const finalEvent = [...events].reverse().find((e) => e.kind === 'final');
  // Grounded follow-ups the agent proposed for this turn — one click sends one.
  const rawSug = (finalEvent?.payload as { suggestions?: unknown } | undefined)?.suggestions;
  const suggestions: string[] = Array.isArray(rawSug)
    ? rawSug.filter((s): s is string => typeof s === 'string' && s.trim().length > 0).slice(0, 3)
    : [];
  const usedSkills = ((events.find((e) => e.kind === 'skills')?.payload as { used?: { id: number; name: string }[] } | undefined)?.used) ?? [];
  const suggestedSkills = ((finalEvent?.payload as { suggest_skills?: { id: number; name: string; summary: string }[] } | undefined)?.suggest_skills) ?? [];
  const errored = Boolean(finalEvent?.payload?.error);
  const cancelled = Boolean(finalEvent?.payload?.cancelled);
  // Answer bubble: white sheet whose left rule carries the turn's STATE
  // (brand = normal, red = error, amber = cancelled).
  const bubbleClass = errored
    ? 'border-l-danger-600'
    : cancelled
      ? 'border-l-warning-500'
      : 'border-l-brand-600';
  // Split into OUTPUTS the user reads (charts, generated-tool cards, errors) —
  // always shown — and PROCESS chips (thinking / tool calls / progress), which
  // are collapsed by default since the full step detail lives in the 工作台.
  const outputs = visibleEvents.filter(isOutputEvent);
  // Derived datasets this answer produced that no longer exist → "expired".
  const serverId = msg.id.startsWith('m_') ? Number(msg.id.slice(2)) : null;
  const runSteps = runStepsOf(events);
  const excludedSteps = events.filter((e) => e.kind === 'tool_result' && (e.payload as { action?: string }).action !== 'run_tool'
    && ['visualize', 'visualize_batch', 'generate_viz', 'generate_tool'].includes(String((e.payload as { action?: string }).action))).length;
  const expired = datasetIds && datasetIds.size > 0
    ? events.flatMap((e) => {
        const dd = e.kind === 'tool_result' ? (e.payload.result as { derived_dataset?: { id: number; name: string } } | undefined)?.derived_dataset : undefined;
        return dd && !datasetIds.has(dd.id) ? [dd.name] : [];
      })
    : [];
  const procEvents = visibleEvents.filter((e) => !isOutputEvent(e));
  return (
    <div className="flex gap-3 max-w-3xl mx-auto">
      <div className="w-7 h-7 shrink-0 rounded bg-brand-600 text-white grid place-items-center font-mono text-xs font-medium">R</div>
      <div className={`flex-1 min-w-0 rounded-md bg-white border border-ink-200 border-l-[3px] px-4 py-3 prose-tight text-sm ${bubbleClass}`}>
        {usedSkills.length > 0 && (
          <div className="inline-flex items-center gap-1 text-[11px] text-violet-700 bg-violet-50 ring-1 ring-violet-100 rounded-md px-1.5 py-0.5 mb-2">
            <Puzzle className="w-3 h-3" /> 使用了 skill：{usedSkills.map((x) => `「${x.name}」`).join('')}
          </div>
        )}
        {procEvents.length > 0 && <ProcessTrace events={procEvents} active={Boolean(msg.pending)} t={t} />}
        {outputs.map((e, i) => isGenerateResult(e)
          ? <GeneratedToolCard key={`o${i}`} result={e.payload.result as GenResult}
              reviewed={reviewedSlugs?.has(String((e.payload.result as GenResult).registered_slug ?? '')) ?? false}
              onKept={onToolKept} onOpenAlgorithm={onOpenAlgorithm} />
          : <EventChip key={`o${i}`} ev={e} active={Boolean(msg.pending)} t={t} />)}
        {liveBuild.length > 0 && msg.pending && <ToolBuildCard events={liveBuild} />}
        {drafts.size > 0 && !msg.pending && (
          <div className="text-xs text-ink-700 bg-white border border-dashed border-ink-500 rounded px-2.5 py-1.5 mb-2 flex flex-wrap items-center gap-x-2 gap-y-1">
            <AiMark />
            <span>本回答中的部分结果来自 AI 新建、<b>尚未经你审核</b>的算法{[...drafts.values()].map((n) => `「${n}」`).join('')}。审核并保存后，这个提示会消失。</span>
            {onOpenAlgorithm && [...drafts.keys()].slice(0, 1).map((slug) => (
              <button key={slug} onClick={() => onOpenAlgorithm(slug)} className="underline text-brand-700 hover:text-brand-800">去审核代码</button>
            ))}
          </div>
        )}
        {msg.pending && liveThought && (
          <div className="text-xs text-ink-500 mb-2 leading-relaxed border-l-2 border-ink-200 pl-2">
            {liveThought}<span className="animate-pulse">▍</span>
          </div>
        )}
        {msg.pending && <ThinkingIndicator startedAt={turnStartedAt} events={events} t={t} />}
        {msg.content && (msg.pending
          ? <Typewriter text={msg.content} />
          : <Markdown>{msg.content}</Markdown>)}
        {!msg.pending && suggestedSkills.length > 0 && onEnableSkill && (
          <div className="mt-3 space-y-1.5">
            {suggestedSkills.map((sk) => {
              const on = activeSkills?.includes(sk.id);
              return (
                <div key={sk.id} className="flex flex-wrap items-center gap-2 text-xs bg-ink-50 border border-ink-200 rounded px-2.5 py-1.5">
                  <Puzzle className="w-3.5 h-3.5 text-violet-600 shrink-0" />
                  <span className="text-ink-700 flex-1 min-w-0">你的 skill「<b>{sk.name}</b>」可能更适合这个问题{sk.summary ? `：${sk.summary}` : ''}</span>
                  {on
                    ? <span className="text-violet-700 inline-flex items-center gap-1"><Check className="w-3.5 h-3.5" /> 已启用，下一条消息生效</span>
                    : <button onClick={() => onEnableSkill(sk.id)} className="px-2 py-0.5 rounded border border-brand-600 bg-brand-600 text-white hover:bg-brand-700">启用</button>}
                </div>
              );
            })}
          </div>
        )}
        {!msg.pending && suggestions.length > 0 && onSuggest && (
          <div className="mt-3 pt-3 border-t border-ink-100/70">
            <div className="text-[11px] text-ink-400 mb-1.5">接下来可以</div>
            <div className="flex flex-wrap gap-1.5">
              {suggestions.map((s, i) => (
                <button
                  key={i}
                  onClick={() => onSuggest(s)}
                  className="text-xs px-2.5 py-1 rounded border border-dashed border-ink-300 text-ink-700
                             bg-white hover:bg-ink-50 hover:border-brand-400 hover:text-brand-700 transition-colors"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {!msg.pending && runSteps.length > 0 && (
          <AnswerSteps steps={runSteps} excluded={excludedSteps} dsById={dsById} onOpenInLibrary={onOpenInLibrary} />
        )}
        {!msg.pending && expired.length > 0 && serverId != null && conversationId != null && onReran && (
          reran
            ? <div className="mt-3 pt-3 border-t border-ink-150 text-xs text-ink-600">该结果的数据已清理，已在原始数据上重新运行，见下方。</div>
            : <RerunBar convId={conversationId} msgId={serverId} names={expired} onReran={onReran} />
        )}
      </div>
    </div>
  );
}

/** Shown on a past answer whose result data no longer exists (cleaned up, or
 *  produced before the storage rework): re-run the turn's algorithm steps on
 *  the original data. Disabled — with the reason — when that isn't possible. */
function RerunBar({ convId, msgId, names, onReran }: {
  convId: number; msgId: number; names: string[]; onReran: (m: ChatMessage) => void;
}) {
  const [check, setCheck] = useState<{ ok: boolean; reason: string | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  useEffect(() => {
    let alive = true;
    api.chatRerunCheck(convId, msgId).then((c) => { if (alive) setCheck(c); }).catch((e) => { if (alive) setCheck({ ok: false, reason: (e as Error).message }); });
    return () => { alive = false; };
  }, [convId, msgId]);
  async function go() {
    setBusy(true); setErr('');
    try { onReran(await api.chatRerun(convId, msgId)); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  }
  return (
    <div className="mt-3 pt-3 border-t border-ink-150 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs">
      <span className="text-ink-600">该结果已过期：{names.slice(0, 2).map((n) => `「${n}」`).join('')}{names.length > 2 ? ` 等 ${names.length} 份` : ''}的数据已清理。</span>
      <button type="button" onClick={go} disabled={busy || !check?.ok}
        className="h-7 px-2.5 rounded border border-ink-300 bg-white text-ink-800 hover:bg-ink-50 disabled:opacity-50 inline-flex items-center gap-1.5">
        {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RotateCcw className="w-3.5 h-3.5" />} 重新运行
      </button>
      {check && !check.ok && check.reason && <span className="text-ink-500">{check.reason}</span>}
      {err && <span className="text-danger-700">{err}</span>}
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

type GenResult = {
  code?: string; meta?: Record<string, unknown>; registered_slug?: string; all_tests_passed?: boolean;
  attempts?: number; final_error?: string;
  tests?: { case: number; status: string; error?: string; duration_ms?: number }[];
};

function isGenerateResult(e: Event): boolean {
  return e.kind === 'tool_result' && e.payload.action === 'generate_tool' && !!(e.payload.result as GenResult | undefined)?.meta;
}

/** Live view of an AI tool being built: one line per stage (write → sandbox
 *  test → auto-repair → done) instead of a frozen spinner — compact on purpose,
 *  the code itself only shows up in the summary card once it's built. */
function ToolBuildCard({ events }: { events: Event[] }) {
  const p = (e: Event) => e.payload as { stage?: string; attempt?: number; reason?: string; name?: string; description?: string };
  const name = [...events].reverse().map((e) => p(e).name).find(Boolean) || p(events[0]).description || '新算法';
  const lines = events.map((e) => {
    const { stage, attempt = 1, reason } = p(e);
    if (stage === 'write') return attempt > 1 ? `按问题重写代码（第 ${attempt} 次）` : '理解需求，编写代码';
    if (stage === 'test') return '沙箱自测（用合成数据真实运行）';
    if (stage === 'repair') return `自测未通过，自动修正${reason ? `：${reason}` : ''}`;
    if (stage === 'done') return '完成';
    return String(stage ?? '');
  });
  return (
    <div className="text-xs bg-white ring-1 ring-brand-200 rounded-lg px-3 py-2.5 mb-2">
      <div className="text-ink-700 mb-1.5 flex items-center gap-1.5"><AiMark /> 正在为你新建算法「<b>{name}</b>」</div>
      <ol className="space-y-0.5">
        {lines.map((l, i) => {
          const last = i === lines.length - 1;
          const repair = p(events[i]).stage === 'repair';
          return (
            <li key={i} className={`flex items-start gap-1.5 ${repair ? 'text-amber-700' : last ? 'text-ink-700' : 'text-ink-400'}`}>
              {last ? <Loader2 className="w-3 h-3 mt-0.5 animate-spin shrink-0" /> : <span className="w-3 shrink-0 text-center">{repair ? '↻' : '✓'}</span>}
              <span className="break-all">{l}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/** Summary of an AI-built tool, collapsed by default: what it does, its params,
 *  how it fared in the sandbox; code + test detail one click away. Also the
 *  keep / edit / discard decision. A failed build says so instead of vanishing. */
function GeneratedToolCard({ result, reviewed, onKept, onOpenAlgorithm }: {
  result: GenResult; reviewed: boolean; onKept?: (slug: string) => void; onOpenAlgorithm?: (slug: string) => void;
}) {
  const meta = result.meta ?? {};
  const name = String(meta.name ?? '新算法');
  const slug = result.registered_slug ?? '';
  const [state, setState] = useState<'idle' | 'busy' | 'kept' | 'discarded' | 'reused' | 'error'>(reviewed ? 'kept' : 'idle');
  const [savedName, setSavedName] = useState(name);
  const [reusedName, setReusedName] = useState('');
  const [showSave, setShowSave] = useState(false);
  useEffect(() => { if (reviewed) setState((s) => (s === 'idle' ? 'kept' : s)); }, [reviewed]);

  const tests = result.tests ?? [];
  const okTests = tests.filter((x) => x.status === 'ok').length;
  const repairs = Math.max(0, (result.attempts ?? 1) - 1);
  const params = Object.keys((meta.params_schema as Record<string, unknown> | undefined) ?? {});
  const failed = !slug || !result.all_tests_passed;

  async function discard() {
    setState('busy');
    try { await api.confirmGeneratedTool(slug, false); setState('discarded'); }
    catch { setState('error'); }
  }

  const details = (
    <>
      {result.code && (
        <details className="mt-1.5">
          <summary className="cursor-pointer text-ink-500 hover:text-ink-700 select-none">查看代码（{result.code.split('\n').length} 行）</summary>
          <pre className="mt-1 bg-ink-900 text-ink-50 rounded-lg p-2 text-[11px] leading-[16px] overflow-auto max-h-72">{result.code}</pre>
        </details>
      )}
      {tests.length > 0 && (
        <details className="mt-1">
          <summary className="cursor-pointer text-ink-500 hover:text-ink-700 select-none">测试明细</summary>
          <ul className="mt-1 space-y-0.5">
            {tests.map((x) => (
              <li key={x.case} className={x.status === 'ok' ? 'text-emerald-700' : 'text-red-600'}>
                用例 {x.case}：{x.status === 'ok' ? '通过' : '失败'}{x.duration_ms != null ? ` · ${x.duration_ms} ms` : ''}
                {x.error && <div className="font-mono text-[10.5px] whitespace-pre-wrap break-all">{x.error.slice(0, 400)}</div>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );

  if (failed) {
    return (
      <div className="text-xs bg-amber-50/60 ring-1 ring-amber-200 rounded-lg px-3 py-2.5 mb-2">
        <div className="text-amber-800">AI 尝试新建算法「<b>{name}</b>」，沙箱自测没有通过（尝试 {result.attempts ?? 1} 次），<b>没有被使用</b>。</div>
        {result.final_error && <div className="text-amber-700 mt-1 break-all">原因：{result.final_error.trim().split('\n').pop()?.slice(0, 200)}</div>}
        {details}
      </div>
    );
  }

  const head = (
    <>
      <div className="text-ink-700">
        AI 新建了算法「<b>{state === 'kept' ? savedName : name}</b>」
        {state === 'kept'
          ? <span className="ml-1.5 text-emerald-700">✓ 已审核保存到工具库</span>
          : <span className="ml-1.5 px-1.5 py-0.5 rounded bg-amber-100 text-amber-800">草稿 · 未经你审核</span>}
      </div>
      {meta.description ? <div className="text-ink-500 mt-1">作用：{String(meta.description)}</div> : null}
      <div className="text-ink-500 mt-0.5">
        {params.length > 0 && <>参数：<span className="font-mono">{params.join(', ')}</span> · </>}
        沙箱自测 {okTests}/{tests.length} 通过{repairs > 0 ? ` · 自动修复 ${repairs} 次` : ''}
      </div>
      {details}
    </>
  );

  if (state === 'discarded') {
    return <div className="text-xs text-ink-500 bg-ink-50 ring-1 ring-ink-200 rounded-lg px-2.5 py-1.5 mb-2">已丢弃临时工具「{name}」（本次回答里用它算出的结果仍保留，但未经审核）。</div>;
  }
  if (state === 'reused') {
    return <div className="text-xs text-emerald-700 bg-emerald-50 ring-1 ring-emerald-100 rounded-lg px-2.5 py-1.5 mb-2">✓ 已改用现有工具「<b>{reusedName}</b>」,新工具已丢弃 —— 下次直接用它即可。</div>;
  }

  return (
    <div className={`text-xs bg-white ring-1 rounded-lg px-3 py-2.5 mb-2 ${state === 'kept' ? 'ring-emerald-200' : 'ring-brand-200'}`}>
      {head}
      {state !== 'kept' && (
        <div className="flex flex-wrap items-center gap-2 mt-2">
          <button onClick={() => setShowSave(true)} disabled={state === 'busy'}
            className="px-2.5 py-1 rounded-lg bg-brand-600 text-white font-medium hover:bg-brand-700 disabled:opacity-50">
            保存到工具库…
          </button>
          {onOpenAlgorithm && (
            <button onClick={() => onOpenAlgorithm(slug)} disabled={state === 'busy'}
              className="px-2.5 py-1 rounded-lg ring-1 ring-brand-200 text-brand-700 hover:bg-brand-50 disabled:opacity-50">
              在编辑器中打开
            </button>
          )}
          <button onClick={discard} disabled={state === 'busy'}
            className="px-2.5 py-1 rounded-lg ring-1 ring-ink-200 text-ink-600 hover:bg-ink-50 disabled:opacity-50">
            丢弃
          </button>
          {state === 'busy' && <Loader2 className="w-3.5 h-3.5 animate-spin text-ink-400" />}
          {state === 'error' && <span className="text-red-600">操作失败,请重试</span>}
        </div>
      )}
      {showSave && (
        <SaveToolModal
          slug={slug}
          meta={meta}
          onSaved={(n) => { setSavedName(n); setState('kept'); setShowSave(false); onKept?.(slug); }}
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
      <div className="text-xs text-ink-500 mb-2 border-l-2 border-ink-200 pl-2">
        {String(ev.payload.text ?? '')}
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
      return <div className="text-xs text-ink-500 mb-2">{t('chat.found')} {(result.tools as unknown[]).length} {t('chat.tools')}</div>;
    }
    if (result.error) {
      return <div className="text-xs text-red-600 mb-2 bg-red-50 rounded-lg px-2 py-1.5">⚠ {String(result.error).slice(0, 200)}</div>;
    }
    if (result.meta) {
      const toolName = String((result.meta as Record<string, unknown>).name ?? '');
      // Auto-registered draft tool → let the user keep or discard it.
      if (result.registered_slug) {
        return <GeneratedToolCard result={result as GenResult} reviewed={false} />;
      }
      return <div className="text-xs text-ink-500 mb-2 inline-flex items-center gap-1.5"><AiMark /> {t('chat.generated')} &quot;{toolName}&quot;{t('chat.awaiting')}</div>;
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


// Last explicit dataset selection in the chat, per browser. localStorage can be
// unavailable (private mode, blocked site data) — then we simply don't restore.
const LAST_SEL_KEY = 'numetrix.chat.lastDatasets';

function readLastSelection(): number[] {
  try {
    const v = JSON.parse(localStorage.getItem(LAST_SEL_KEY) || '[]');
    return Array.isArray(v) ? v.filter((x): x is number => typeof x === 'number') : [];
  } catch { return []; }
}

function writeLastSelection(ids: number[]) {
  try { localStorage.setItem(LAST_SEL_KEY, JSON.stringify(ids)); } catch { /* ignore */ }
}


/** Skills selector above the chat input: which of the user's skills the agent
 *  should follow for the next message. Selected ones show as removable chips. */
function SkillBar({ skills, active, onToggle }: { skills: Skill[]; active: number[]; onToggle: (id: number) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    function onDoc(e: MouseEvent) { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); }
    if (open) document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);
  const on = skills.filter((x) => active.includes(x.id));
  return (
    <div className="flex flex-wrap items-center gap-1.5 mb-2">
      <div ref={ref} className="relative">
        <button onClick={() => setOpen((o) => !o)}
          className={`inline-flex items-center gap-1 text-xs px-2 py-1 rounded-lg ring-1 ${on.length ? 'ring-violet-300 bg-violet-50 text-violet-700' : 'ring-ink-200 text-ink-500 hover:bg-ink-50'}`}>
          <Puzzle className="w-3.5 h-3.5" /> Skills{on.length ? ` · ${on.length}` : ''} <ChevronDown className="w-3 h-3" />
        </button>
        {open && (
          <div className="absolute bottom-full mb-2 left-0 w-80 max-h-72 overflow-y-auto scroll-hide bg-white rounded-xl ring-1 ring-ink-200 shadow-lg z-30 p-1">
            <div className="px-2 py-1 text-[10.5px] text-ink-400">勾选后，智能体会按这些 skill 的方法来分析</div>
            {skills.length === 0 && (
              <div className="px-2 py-3 text-xs text-ink-400">还没有可用的 skill —— 在左侧「技能 Skills」里添加并确认后会出现在这里。</div>
            )}
            {skills.map((x) => {
              const sel = active.includes(x.id);
              return (
                <button key={x.id} onClick={() => onToggle(x.id)}
                  className={`w-full text-left px-2 py-1.5 rounded-lg flex items-start gap-2 ${sel ? 'bg-violet-50' : 'hover:bg-ink-50'}`}>
                  <span className={`mt-0.5 w-3.5 h-3.5 rounded border shrink-0 grid place-items-center ${sel ? 'bg-violet-600 border-violet-600' : 'border-ink-300'}`}>
                    {sel && <Check className="w-2.5 h-2.5 text-white" />}
                  </span>
                  <span className="min-w-0">
                    <span className="block text-sm text-ink-800 truncate">{x.config?.name || x.name}</span>
                    <span className="block text-[11px] text-ink-400 line-clamp-2">{x.config?.summary || x.description}</span>
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>
      {on.map((x) => (
        <span key={x.id} className="inline-flex items-center gap-1 text-[11px] text-violet-700 bg-violet-50 ring-1 ring-violet-100 rounded-md pl-1.5 pr-1 py-0.5">
          {x.config?.name || x.name}
          <button onClick={() => onToggle(x.id)} title="不再使用这个 skill" className="hover:text-violet-900"><X className="w-3 h-3" /></button>
        </span>
      ))}
    </div>
  );
}

const SKILLS_KEY = 'numetrix.chat.activeSkills';

function readIds(key: string): number[] {
  try {
    const v = JSON.parse(localStorage.getItem(key) || '[]');
    return Array.isArray(v) ? v.filter((x): x is number => typeof x === 'number') : [];
  } catch { return []; }
}

function writeIds(key: string, ids: number[]) {
  try { localStorage.setItem(key, JSON.stringify(ids)); } catch { /* ignore */ }
}

'use client';

import { useEffect, useMemo, useState } from 'react';
import { api, fetchFeedbackScreenshot, type Feedback, type FeedbackKind, type MappingRule } from '@/lib/api';
import { useLangStore } from '@/lib/i18n';

/** Lazily fetches a note's screenshot (authenticated) and shows a thumbnail;
 *  click opens it full-size in a new tab. */
function ScreenshotThumb({ id }: { id: number }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let u: string | null = null;
    fetchFeedbackScreenshot(id).then((x) => { u = x; setUrl(x); }).catch(() => {});
    return () => { if (u) URL.revokeObjectURL(u); };
  }, [id]);
  if (!url) return <div className="mt-2 h-20 w-32 animate-pulse rounded-lg bg-ink-100" />;
  return (
    <img
      src={url}
      alt="screenshot"
      onClick={() => window.open(url, '_blank')}
      className="mt-2 max-h-40 cursor-zoom-in rounded-lg border border-ink-200 object-contain"
    />
  );
}

/**
 * Triage inbox for the in-the-moment notes users drop via FeedbackButton.
 * Admins see everyone's; a regular user sees their own. Filter by bucket and
 * status, then move each note new → triaged → done. This is the human end of
 * the candidate → review → promote loop.
 */

const KIND_META: Record<FeedbackKind, { zh: string; en: string; cls: string }> = {
  cannot:   { zh: '想做但做不到', en: 'Couldn’t do it',  cls: 'bg-amber-50 text-amber-700 ring-amber-200' },
  wrong:    { zh: '它做错了',     en: 'Got it wrong',    cls: 'bg-rose-50 text-rose-700 ring-rose-200' },
  distrust: { zh: '不敢信结果',   en: 'Don’t trust it',  cls: 'bg-violet-50 text-violet-700 ring-violet-200' },
  idea:     { zh: '想法 / 其它',  en: 'Idea / other',    cls: 'bg-sky-50 text-sky-700 ring-sky-200' },
};

const STATUS_META: Record<string, { zh: string; en: string; cls: string }> = {
  new:     { zh: '待处理', en: 'New',     cls: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
  triaged: { zh: '已查看', en: 'Triaged', cls: 'bg-ink-100 text-ink-600 ring-ink-200' },
  done:    { zh: '已完成', en: 'Done',    cls: 'bg-ink-100 text-ink-400 ring-ink-200' },
};

const KIND_ORDER: (FeedbackKind | 'all')[] = ['all', 'cannot', 'wrong', 'distrust', 'idea'];
const STATUS_ORDER = ['all', 'new', 'triaged', 'done'];

type JumpTarget = { view?: string; datasetId?: number | null; conversationId?: number | null };
type Props = { onJump?: (t: JumpTarget) => void };

export default function FeedbackInbox({ onJump }: Props) {
  const lang = useLangStore((s) => s.lang);
  const zh = lang === 'zh';
  const [items, setItems] = useState<Feedback[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [kindFilter, setKindFilter] = useState<FeedbackKind | 'all'>('all');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  // Sedimented mapping rules + the inline "promote" form state.
  const [rules, setRules] = useState<MappingRule[]>([]);
  const [showRules, setShowRules] = useState(false);
  const [promoteId, setPromoteId] = useState<number | null>(null);
  const [mPattern, setMPattern] = useState('');
  const [mRole, setMRole] = useState('');
  const [saving, setSaving] = useState(false);

  async function load() {
    setLoading(true); setError('');
    try {
      const [fb, rl] = await Promise.all([api.listFeedback(), api.listMappings().catch(() => [])]);
      setItems(fb);
      setRules(rl as MappingRule[]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { load(); }, []);

  async function setStatus(f: Feedback, status: string) {
    // optimistic
    setItems((xs) => xs.map((x) => (x.id === f.id ? { ...x, status } : x)));
    try { await api.updateFeedback(f.id, { status }); }
    catch { load(); }
  }

  function openPromote(f: Feedback) {
    setPromoteId(f.id); setMPattern(''); setMRole('');
  }
  async function promote(f: Feedback) {
    const pattern = mPattern.trim(); const role = mRole.trim();
    if (!pattern || !role || saving) return;
    setSaving(true);
    try {
      const rule = await api.createMapping({ pattern, role, label: role, feedback_id: f.id });
      setRules((rs) => [rule, ...rs]);
      setItems((xs) => xs.map((x) => (x.id === f.id ? { ...x, status: 'done' } : x)));  // server marks it done
      setPromoteId(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }
  async function removeRule(id: number) {
    setRules((rs) => rs.filter((r) => r.id !== id));
    try { await api.deleteMapping(id); } catch { load(); }
  }

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: items.length, new: 0, triaged: 0, done: 0 };
    for (const it of items) c[it.status] = (c[it.status] ?? 0) + 1;
    return c;
  }, [items]);

  const filtered = useMemo(
    () => items.filter((it) =>
      (kindFilter === 'all' || it.kind === kindFilter) &&
      (statusFilter === 'all' || it.status === statusFilter)),
    [items, kindFilter, statusFilter],
  );

  const fmtTime = (iso: string) => {
    if (!iso) return '';
    try { return new Date(iso).toLocaleString(zh ? 'zh-CN' : 'en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }); }
    catch { return iso; }
  };

  return (
    <div className="h-full overflow-y-auto bg-ink-50/30">
      <div className="mx-auto max-w-3xl px-6 py-8">
        <div className="mb-1 flex items-center justify-between">
          <h1 className="text-xl font-semibold text-ink-800">{zh ? '反馈收件箱' : 'Feedback inbox'}</h1>
          <button onClick={load} className="text-sm text-brand-600 hover:text-brand-700">{zh ? '刷新' : 'Refresh'}</button>
        </div>
        <p className="mb-4 text-sm text-ink-500">
          {zh ? '用户随手丢来的想法,带着当时的上下文。按类型 / 状态筛,逐条处理。'
              : 'In-the-moment notes with the context they happened in. Filter and triage.'}
        </p>

        {/* Sedimented expert knowledge: the column-meaning rules promoted from notes */}
        <div className="mb-5 rounded-xl border border-brand-200 bg-brand-50/50 p-3">
          <button onClick={() => setShowRules((v) => !v)} className="flex w-full items-center justify-between text-left">
            <span className="text-sm font-medium text-brand-800">
              {zh ? '已沉淀的列映射规则' : 'Sedimented column-meaning rules'}
              <span className="ml-2 rounded-full bg-brand-600 px-2 py-0.5 text-xs text-white">{rules.length}</span>
            </span>
            <span className="text-xs text-brand-600">{showRules ? (zh ? '收起' : 'hide') : (zh ? '展开' : 'show')}</span>
          </button>
          {showRules && (
            <div className="mt-2 space-y-1">
              {rules.length === 0 && (
                <p className="text-xs text-ink-400">
                  {zh ? '还没有规则。把「它做错了」类的列纠正晋升成规则后,下次打开数据会自动套用。'
                      : 'No rules yet. Promote a column correction and it auto-applies next time.'}
                </p>
              )}
              {rules.map((r) => (
                <div key={r.id} className="flex items-center gap-2 rounded-lg bg-white px-2.5 py-1.5 text-xs ring-1 ring-ink-200">
                  <code className="rounded bg-ink-100 px-1.5 py-0.5">{r.pattern}</code>
                  <span className="text-ink-400">→</span>
                  <span className="font-medium text-ink-700">{r.label || r.role}</span>
                  <span className="text-ink-300">·{r.match_type}</span>
                  {r.hit_count > 0 && <span className="text-emerald-600">{zh ? `命中 ${r.hit_count} 次` : `${r.hit_count} hits`}</span>}
                  <button onClick={() => removeRule(r.id)} className="ml-auto text-ink-300 hover:text-rose-600">{zh ? '删除' : 'delete'}</button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* status tabs */}
        <div className="mb-3 flex flex-wrap gap-1.5">
          {STATUS_ORDER.map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`rounded-full px-3 py-1 text-sm transition ${
                statusFilter === s ? 'bg-brand-600 text-white' : 'bg-white text-ink-600 ring-1 ring-ink-200 hover:bg-ink-50'
              }`}
            >
              {s === 'all' ? (zh ? '全部' : 'All') : (zh ? STATUS_META[s].zh : STATUS_META[s].en)}
              <span className="ml-1.5 opacity-60">{counts[s] ?? 0}</span>
            </button>
          ))}
        </div>

        {/* kind filter */}
        <div className="mb-5 flex flex-wrap gap-1.5">
          {KIND_ORDER.map((k) => (
            <button
              key={k}
              onClick={() => setKindFilter(k)}
              className={`rounded-full px-3 py-1 text-xs transition ${
                kindFilter === k ? 'bg-ink-800 text-white' : 'bg-white text-ink-500 ring-1 ring-ink-200 hover:bg-ink-50'
              }`}
            >
              {k === 'all' ? (zh ? '全部类型' : 'All kinds') : (zh ? KIND_META[k].zh : KIND_META[k].en)}
            </button>
          ))}
        </div>

        {loading && <div className="py-12 text-center text-sm text-ink-400">{zh ? '加载中…' : 'Loading…'}</div>}
        {error && <div className="rounded-lg bg-rose-50 p-3 text-sm text-rose-700">{error}</div>}
        {!loading && !error && filtered.length === 0 && (
          <div className="py-16 text-center text-sm text-ink-400">{zh ? '还没有反馈。' : 'No feedback yet.'}</div>
        )}

        <div className="space-y-3">
          {filtered.map((f) => {
            const km = KIND_META[f.kind] ?? KIND_META.idea;
            const sm = STATUS_META[f.status] ?? STATUS_META.new;
            const canJump = !!(f.view || f.dataset_id != null || f.conversation_id != null);
            return (
              <div key={f.id} className={`rounded-xl border border-ink-200 bg-white p-4 shadow-sm ${f.status === 'done' ? 'opacity-70' : ''}`}>
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${km.cls}`}>{zh ? km.zh : km.en}</span>
                  <span className={`rounded-full px-2 py-0.5 text-xs ring-1 ${sm.cls}`}>{zh ? sm.zh : sm.en}</span>
                  <span className="ml-auto text-xs text-ink-400">{fmtTime(f.created_at)}</span>
                </div>

                <p className="whitespace-pre-wrap text-sm text-ink-800">{f.text}</p>

                {f.has_screenshot && <ScreenshotThumb id={f.id} />}

                {/* context chips */}
                <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[11px] text-ink-500">
                  {f.view && <span className="rounded bg-ink-100 px-1.5 py-0.5 font-mono">view: {f.view}</span>}
                  {f.conversation_id != null && <span className="rounded bg-ink-100 px-1.5 py-0.5 font-mono">conv #{f.conversation_id}</span>}
                  {f.dataset_id != null && <span className="rounded bg-ink-100 px-1.5 py-0.5 font-mono">dataset #{f.dataset_id}</span>}
                  {f.run_id != null && <span className="rounded bg-ink-100 px-1.5 py-0.5 font-mono">run #{f.run_id}</span>}
                  {canJump && onJump && (
                    <button
                      onClick={() => onJump({ view: f.view, datasetId: f.dataset_id, conversationId: f.conversation_id })}
                      className="rounded bg-brand-50 px-1.5 py-0.5 font-mono text-brand-600 ring-1 ring-brand-200 hover:bg-brand-100"
                    >
                      {zh ? '回到现场 ↗' : 'go to context ↗'}
                    </button>
                  )}
                </div>

                {/* triage actions + promote */}
                <div className="mt-3 flex flex-wrap items-center gap-1.5">
                  {['new', 'triaged', 'done'].map((s) => (
                    <button
                      key={s}
                      onClick={() => setStatus(f, s)}
                      disabled={f.status === s}
                      className={`rounded-md px-2.5 py-1 text-xs transition ${
                        f.status === s
                          ? 'cursor-default bg-brand-50 text-brand-700 ring-1 ring-brand-200'
                          : 'text-ink-500 hover:bg-ink-100'
                      }`}
                    >
                      {zh ? STATUS_META[s].zh : STATUS_META[s].en}
                    </button>
                  ))}
                  <button
                    onClick={() => (promoteId === f.id ? setPromoteId(null) : openPromote(f))}
                    className="ml-auto rounded-md bg-brand-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-brand-700"
                  >
                    {zh ? '晋升为映射规则 →' : 'Promote to rule →'}
                  </button>
                </div>

                {/* inline promote form: turn a column correction into a reusable rule */}
                {promoteId === f.id && (
                  <div className="mt-3 rounded-lg border border-brand-200 bg-brand-50/40 p-3">
                    <p className="mb-2 text-xs text-ink-500">
                      {zh ? '把这条纠正变成下次自动生效的规则:列名(匹配)→ 它的真实含义。'
                          : 'Turn this correction into a rule: column (match) → its real meaning.'}
                    </p>
                    <div className="flex flex-wrap items-center gap-2">
                      <input
                        value={mPattern}
                        onChange={(e) => setMPattern(e.target.value)}
                        placeholder={zh ? '列名,如 U(V)' : 'column, e.g. U(V)'}
                        className="w-36 rounded-md border border-ink-200 px-2 py-1 text-sm outline-none focus:border-brand-400"
                      />
                      <span className="text-ink-400">→</span>
                      <input
                        value={mRole}
                        onChange={(e) => setMRole(e.target.value)}
                        placeholder={zh ? '含义,如 电压' : 'meaning, e.g. voltage'}
                        className="w-36 rounded-md border border-ink-200 px-2 py-1 text-sm outline-none focus:border-brand-400"
                        onKeyDown={(e) => { if (e.key === 'Enter') promote(f); }}
                      />
                      <button
                        onClick={() => promote(f)}
                        disabled={!mPattern.trim() || !mRole.trim() || saving}
                        className="rounded-md bg-brand-600 px-3 py-1 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
                      >
                        {saving ? (zh ? '保存中…' : 'Saving…') : (zh ? '沉淀' : 'Sediment')}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

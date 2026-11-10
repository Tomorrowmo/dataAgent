'use client';

import { Database, Braces, Workflow, Settings, LogOut, Plus, Trash2, Pencil, Check, Inbox, Puzzle, Search, Menu, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { api, type Conversation, setToken, OIDC_LOGOUT_URL } from '@/lib/api';
import LanguageToggle from '@/components/LanguageToggle';
import ResizeHandle, { useResizableWidth } from '@/components/ResizeHandle';
import { useT } from '@/lib/i18n';

type View = 'chat' | 'datasets' | 'algorithms' | 'templates' | 'skills' | 'feedback' | 'settings' | 'about';

/** "今天" / "昨天" / "11-07" in the viewer's time zone. */
function dayLabel(iso: string | null | undefined, zh: boolean): string {
  if (!iso) return '';
  const d = new Date(iso.endsWith('Z') || /[+-]\d\d:\d\d$/.test(iso) ? iso : iso + 'Z');
  if (Number.isNaN(d.getTime())) return '';
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const day = new Date(d); day.setHours(0, 0, 0, 0);
  const diff = Math.round((today.getTime() - day.getTime()) / 86_400_000);
  if (diff === 0) return zh ? '今天' : 'Today';
  if (diff === 1) return zh ? '昨天' : 'Yday';
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export default function Sidebar({
  activeView,
  onChangeView,
  activeConv,
  onSelectConv,
  onNewConv,
  onConvDeleted,
}: {
  activeView: View;
  onChangeView: (v: View) => void;
  activeConv: number | null;
  onSelectConv: (id: number) => void;
  onNewConv: () => void;
  onConvDeleted?: (id: number) => void;
}) {
  const router = useRouter();
  const t = useT();
  const zh = t('side.chat') === '对话';
  const [convs, setConvs] = useState<Conversation[]>([]);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [me, setMe] = useState<{ name: string; email: string; is_admin: boolean } | null>(null);
  const [version, setVersion] = useState('');
  const [counts, setCounts] = useState<{ datasets: number | null; flows: number | null }>({ datasets: null, flows: null });
  const [filter, setFilter] = useState('');
  const [mobileOpen, setMobileOpen] = useState(false);
  const sw = useResizableWidth('numetrix.sidebar.width', 220, 180, 320);

  useEffect(() => {
    api.listConversations().then(setConvs).catch(() => {});
    api.me().then((m) => setMe({ name: m.name, email: m.email, is_admin: !!m.is_admin })).catch(() => {});
    api.about().then((a) => setVersion(a.version)).catch(() => {});
  }, []);
  // Counts next to 数据 / 流程 — refreshed whenever the user moves between views.
  useEffect(() => {
    api.listDatasets().then((ds) => setCounts((c) => ({ ...c, datasets: ds.filter((d) => d.kind !== 'derived').length }))).catch(() => {});
    api.listTemplates().then((ts) => setCounts((c) => ({ ...c, flows: ts.length }))).catch(() => {});
  }, [activeView]);
  // Ctrl/⌘ K — new analysis from anywhere.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === 'k') { e.preventDefault(); onNewConv(); setMobileOpen(false); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onNewConv]);

  function startRename(c: Conversation) { setEditingId(c.id); setEditTitle(c.title); }
  async function saveRename(c: Conversation) {
    const title = editTitle.trim();
    setEditingId(null);
    if (!title || title === c.title) return;
    try {
      await api.renameConversation(c.id, title);
      setConvs((cs) => cs.map((x) => (x.id === c.id ? { ...x, title } : x)));
    } catch { /* ignore */ }
  }
  async function del(c: Conversation) {
    if (!confirm(zh ? `删除会话「${c.title}」？此操作不可撤销。` : `Delete "${c.title}"? This cannot be undone.`)) return;
    try {
      await api.deleteConversation(c.id);
      setConvs((cs) => cs.filter((x) => x.id !== c.id));
      onConvDeleted?.(c.id);
    } catch { /* ignore */ }
  }

  async function logout() {
    // Under OIDC, clear the local token AND bounce through the auth center for a
    // true single logout; otherwise just drop the local token.
    let oidc = false;
    try { oidc = (await api.oidcConfig()).enabled; } catch { /* keep local logout */ }
    setToken(null);
    if (oidc) window.location.href = OIDC_LOGOUT_URL;
    else router.push('/login');
  }

  const onHome = activeView === 'chat' && activeConv == null;
  const go = (v: View) => { onChangeView(v); setMobileOpen(false); };
  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return (q ? convs.filter((c) => c.title.toLowerCase().includes(q)) : convs).slice(0, q ? 100 : 30);
  }, [convs, filter]);

  const ico = 'w-4 h-4 shrink-0';
  const MAIN: { id: View; label: string; icon: React.ReactNode; count?: number | null }[] = [
    { id: 'datasets', label: zh ? '数据' : 'Data', icon: <Database className={ico} strokeWidth={1.6} />, count: counts.datasets },
    { id: 'templates', label: zh ? '流程' : 'Flows', icon: <Workflow className={ico} strokeWidth={1.6} />, count: counts.flows },
  ];
  const TOOLS: { id: View; label: string; icon: React.ReactNode }[] = [
    { id: 'algorithms', label: zh ? '算法' : 'Algorithms', icon: <Braces className={ico} strokeWidth={1.6} /> },
    { id: 'skills', label: zh ? '技能' : 'Skills', icon: <Puzzle className={ico} strokeWidth={1.6} /> },
    // Feedback inbox is admin-only — it's the triage queue.
    ...(me?.is_admin ? [{ id: 'feedback' as View, label: zh ? '反馈收件箱' : 'Feedback inbox', icon: <Inbox className={ico} strokeWidth={1.6} /> }] : []),
  ];
  const item = (n: { id: View; label: string; icon: React.ReactNode; count?: number | null }) => {
    const on = activeView === n.id;
    return (
      <button key={n.id} type="button" onClick={() => go(n.id)}
        aria-current={on ? 'page' : undefined}
        className={`w-full h-8 px-2.5 rounded-md flex items-center gap-2.5 text-[13px] transition-colors ${
          on ? 'bg-white text-ink-900 font-medium shadow-[0_1px_2px_rgba(22,25,29,0.07)] [&>svg]:text-brand-600' : 'text-ink-600 hover:bg-ink-900/5 hover:text-ink-900'}`}>
        {n.icon}<span className="truncate">{n.label}</span>
        {n.count != null && <span className="ml-auto text-[11px] text-ink-400 tabular-nums">{n.count}</span>}
      </button>
    );
  };

  return (
    <>
      {/* phone: a slim bar with the menu button; the full sidebar opens as a drawer */}
      <div className="md:hidden w-11 shrink-0 bg-ink-100 border-r border-ink-200 flex flex-col items-center py-3 gap-2">
        <button type="button" onClick={() => setMobileOpen(true)} title={zh ? '菜单' : 'Menu'} className="w-8 h-8 grid place-items-center rounded-md text-ink-600 hover:bg-ink-900/5"><Menu className="w-[18px] h-[18px]" /></button>
        <button type="button" onClick={onNewConv} title={zh ? '新建分析' : 'New analysis'} className="w-8 h-8 grid place-items-center rounded-md text-brand-600 hover:bg-ink-900/5"><Plus className="w-[18px] h-[18px]" /></button>
      </div>
      {mobileOpen && <div className="md:hidden fixed inset-0 z-40 bg-ink-900/30" onClick={() => setMobileOpen(false)} />}

      <aside style={{ width: sw.width }} className={`relative shrink-0 bg-ink-100 border-r border-ink-200 flex flex-col px-2.5 pt-3.5 pb-2.5 min-h-0 h-full max-md:!w-[220px]
        max-md:fixed max-md:inset-y-0 max-md:left-0 max-md:z-50 max-md:shadow-2xl max-md:transition-transform ${mobileOpen ? '' : 'max-md:-translate-x-full'}`}>
        <ResizeHandle side="right" widthAt={(x) => x} onResize={(w) => sw.set(w)}
          onDone={() => sw.set(sw.current.current, true)} onReset={sw.reset} />
        <div className="flex items-center gap-2.5 px-2 pb-3.5">
          <Link href="/" title="RLab Cortex" className="w-6 h-6 rounded-[5px] bg-brand-600 text-white grid place-items-center font-mono text-[12px] font-semibold shrink-0">R</Link>
          <div className="min-w-0 leading-tight">
            <div className="text-sm font-semibold text-ink-900">RLab Cortex</div>
            {version && (
              <button type="button" onClick={() => go('about')} title={zh ? '版本与更新日志' : 'Version & changelog'}
                className={`font-mono text-[11px] hover:text-brand-600 ${activeView === 'about' ? 'text-brand-600' : 'text-ink-500'}`}>v{version}</button>
            )}
          </div>
          <button type="button" onClick={() => setMobileOpen(false)} className="md:hidden ml-auto p-1 text-ink-500"><X className="w-4 h-4" /></button>
        </div>

        <button type="button" onClick={() => { onNewConv(); setMobileOpen(false); }}
          aria-current={onHome ? 'page' : undefined}
          className={`mx-0.5 mb-3.5 h-[34px] px-2.5 rounded-md bg-white flex items-center gap-2 text-[13px] text-ink-900 shadow-[0_1px_2px_rgba(22,25,29,0.05)] ${onHome ? 'ring-1 ring-brand-600/40 font-medium' : 'ring-1 ring-ink-200 hover:ring-ink-300'}`}>
          <Plus className={`w-[15px] h-[15px] ${onHome ? 'text-brand-600' : ''}`} strokeWidth={1.75} />{zh ? '新建分析' : 'New analysis'}
          <kbd className="ml-auto font-mono text-[11px] text-ink-400">Ctrl K</kbd>
        </button>

        <nav className="space-y-px">{MAIN.map(item)}</nav>
        <div className="mt-4 mb-1 px-2.5 text-[11px] text-ink-400">{zh ? '工具库' : 'Library'}</div>
        <nav className="space-y-px">{TOOLS.map(item)}</nav>

        <div className="mt-4 mb-1 px-2.5 flex items-center gap-2 text-[11px] text-ink-400">
          <span>{zh ? '最近' : 'Recent'}</span>
        </div>
        {convs.length > 8 && (
          <label className="mx-0.5 mb-1 h-7 px-2 rounded-md flex items-center gap-1.5 text-ink-400 focus-within:bg-white focus-within:shadow-[0_0_0_1px_#c6cbd1]">
            <Search className="w-3.5 h-3.5 shrink-0" />
            <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder={zh ? '按标题查找' : 'Find by title'}
              className="flex-1 min-w-0 bg-transparent text-xs text-ink-800 placeholder:text-ink-400 outline-none" />
          </label>
        )}
        <div className="flex-1 min-h-0 overflow-y-auto scroll-hide -mx-0.5 px-0.5">
          {convs.length === 0 && <div className="px-2.5 py-2 text-xs text-ink-400">{t('side.noSessions')}</div>}
          {convs.length > 0 && shown.length === 0 && <div className="px-2.5 py-2 text-xs text-ink-400">{zh ? '没有匹配的会话' : 'No match'}</div>}
          {shown.map((c) => {
            const active = activeView === 'chat' && activeConv === c.id;
            return (
              <div key={c.id} className={`group flex items-center gap-1 rounded-md pl-2.5 pr-1 ${active ? 'bg-white shadow-[0_1px_2px_rgba(22,25,29,0.07)]' : 'hover:bg-ink-900/5'}`}>
                {editingId === c.id ? (
                  <>
                    <input autoFocus value={editTitle} onChange={(e) => setEditTitle(e.target.value)}
                      onKeyDown={(e) => { if (e.key === 'Enter') saveRename(c); else if (e.key === 'Escape') setEditingId(null); }}
                      onBlur={() => saveRename(c)}
                      className="flex-1 min-w-0 my-0.5 text-[12.5px] px-1.5 py-1 rounded border border-brand-300 focus:outline-none bg-white" />
                    <button onMouseDown={(e) => e.preventDefault()} onClick={() => saveRename(c)} title={zh ? '保存' : 'Save'} className="shrink-0 p-1 text-ink-400 hover:text-success-700"><Check className="w-3.5 h-3.5" /></button>
                  </>
                ) : (
                  <>
                    <button type="button" onClick={() => { onSelectConv(c.id); setMobileOpen(false); }} title={c.title}
                      className={`flex-1 min-w-0 py-1.5 text-left text-[12.5px] truncate ${active ? 'text-ink-900 font-medium' : 'text-ink-700'}`}>
                      <span className="text-[11px] text-ink-400 mr-1.5 font-normal">{dayLabel(c.created_at, zh)}</span>{c.title}
                    </button>
                    <div className="shrink-0 hidden group-hover:flex items-center">
                      <button onClick={() => startRename(c)} title={zh ? '重命名' : 'Rename'} className="p-1 text-ink-400 hover:text-brand-600"><Pencil className="w-3.5 h-3.5" /></button>
                      <button onClick={() => del(c)} title={zh ? '删除会话' : 'Delete'} className="p-1 text-ink-400 hover:text-danger-700"><Trash2 className="w-3.5 h-3.5" /></button>
                    </div>
                  </>
                )}
              </div>
            );
          })}
        </div>

        <div className="pt-2.5 pl-1.5 flex items-center gap-2">
          <span className="w-[26px] h-[26px] rounded-full bg-ink-200 text-ink-700 grid place-items-center text-[11px] shrink-0">{(me?.name || me?.email || '·').trim()[0]?.toUpperCase()}</span>
          <div className="min-w-0 flex-1 leading-tight">
            <div className="text-[12.5px] text-ink-900 truncate">{me?.name || me?.email || ''}</div>
            {me?.is_admin && <div className="text-[11px] text-ink-500">{zh ? '管理员' : 'Admin'}</div>}
          </div>
          <LanguageToggle compact />
          <button type="button" onClick={() => go('settings')} title={t('side.settings')}
            className={`w-7 h-7 grid place-items-center rounded-md hover:bg-ink-900/5 ${activeView === 'settings' ? 'text-brand-600 bg-white shadow-[0_1px_2px_rgba(22,25,29,0.07)]' : 'text-ink-500'}`}>
            <Settings className="w-[15px] h-[15px]" strokeWidth={1.6} />
          </button>
          <button type="button" onClick={logout} title={t('side.signout')} className="w-7 h-7 grid place-items-center rounded-md text-ink-500 hover:bg-ink-900/5 hover:text-danger-700">
            <LogOut className="w-[15px] h-[15px]" strokeWidth={1.6} />
          </button>
        </div>
      </aside>
    </>
  );
}

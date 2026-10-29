'use client';

import { Bot, Database, FunctionSquare, Workflow, Settings, LogOut, Plus, Trash2, Pencil, Check, Inbox, Info, Puzzle } from 'lucide-react';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { api, type Conversation, setToken, OIDC_LOGOUT_URL } from '@/lib/api';
import LanguageToggle from '@/components/LanguageToggle';
import { useT } from '@/lib/i18n';

type View = 'chat' | 'datasets' | 'algorithms' | 'templates' | 'skills' | 'feedback' | 'settings' | 'about';

// Per-conversation avatar colour, hashed from the id so each conversation keeps
// a stable, distinct tint (Notion/Linear style) — makes the list scannable.
const AVATAR_COLORS = [
  'bg-blue-100 text-blue-700', 'bg-violet-100 text-violet-700', 'bg-emerald-100 text-emerald-700',
  'bg-amber-100 text-amber-700', 'bg-rose-100 text-rose-700', 'bg-cyan-100 text-cyan-700',
  'bg-indigo-100 text-indigo-700', 'bg-fuchsia-100 text-fuchsia-700',
];
const avatarColor = (id: number) => AVATAR_COLORS[((id % AVATAR_COLORS.length) + AVATAR_COLORS.length) % AVATAR_COLORS.length];
const avatarChar = (title: string) => (title?.trim()?.[0] ?? '·').toUpperCase();

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
  const [convs, setConvs] = useState<Conversation[]>([]);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [isAdmin, setIsAdmin] = useState(false);
  const [version, setVersion] = useState('');

  useEffect(() => {
    api.listConversations().then(setConvs).catch(() => {});
    api.me().then((m) => setIsAdmin(!!m.is_admin)).catch(() => {});
    api.about().then((a) => setVersion(a.version)).catch(() => {});
  }, []);

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
    if (!confirm(`删除会话「${c.title}」?此操作不可撤销。`)) return;
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
    if (oidc) {
      window.location.href = OIDC_LOGOUT_URL;
    } else {
      router.push('/login');
    }
  }

  // The conversation list toggles (VSCode-style) and is HIDDEN by default:
  // clicking the chat icon opens it; clicking it again collapses it.
  const [convPanelOpen, setConvPanelOpen] = useState(false);

  const NAV: { id: View; label: string; icon: React.ReactNode }[] = [
    { id: 'chat', label: t('side.chat'), icon: <Bot className="w-5 h-5" /> },
    { id: 'datasets', label: t('side.datasets'), icon: <Database className="w-5 h-5" /> },
    { id: 'algorithms', label: t('side.algorithms'), icon: <FunctionSquare className="w-5 h-5" /> },
    { id: 'templates', label: '流程模板', icon: <Workflow className="w-5 h-5" /> },
    { id: 'skills', label: '技能 Skills', icon: <Puzzle className="w-5 h-5" /> },
    // Feedback inbox is admin-only — it's the boss's triage queue.
    ...(isAdmin ? [{ id: 'feedback' as View, label: '反馈收件箱', icon: <Inbox className="w-5 h-5" /> }] : []),
    { id: 'settings', label: t('side.settings'), icon: <Settings className="w-5 h-5" /> },
    { id: 'about', label: t('side.about'), icon: <Info className="w-5 h-5" /> },
  ];

  return (
    <div className="flex h-full shrink-0">
      {/* Tier 1 — icon rail (primary navigation) */}
      <aside className="w-14 shrink-0 border-r border-ink-200 bg-white flex flex-col items-center py-3 gap-1">
        <Link href="/" title="RLab Cortex" className="w-9 h-9 rounded-lg bg-brand-600 text-white grid place-items-center text-sm font-semibold mb-1">R</Link>
        {/* New conversation — prominent, always reachable from the rail */}
        <button
          onClick={onNewConv}
          title="新建对话"
          className="w-10 h-10 grid place-items-center rounded-xl text-brand-500 hover:bg-brand-50 mb-1"
        >
          <Plus className="w-5 h-5" />
        </button>
        {NAV.map((n) => (
          <button
            key={n.id}
            onClick={() => {
              // The chat icon toggles the conversation list: open it (or, if
              // already on chat with it open, collapse it).
              if (n.id === 'chat' && activeView === 'chat') { setConvPanelOpen((o) => !o); return; }
              if (n.id === 'chat') setConvPanelOpen(true);
              onChangeView(n.id);
            }}
            title={n.label}
            className={`w-10 h-10 grid place-items-center rounded-xl transition ${
              activeView === n.id ? 'bg-brand-50 text-brand-700 ring-1 ring-brand-200' : 'text-ink-400 hover:bg-ink-100 hover:text-ink-700'
            }`}
          >
            {n.icon}
          </button>
        ))}
        <div className="mt-auto flex flex-col items-center gap-1">
          <LanguageToggle compact />
          <button onClick={logout} title={t('side.signout')} className="w-10 h-10 grid place-items-center rounded-xl text-ink-400 hover:bg-ink-100 hover:text-red-600">
            <LogOut className="w-5 h-5" />
          </button>
          {version && (
            <button
              onClick={() => onChangeView('about')}
              title={`版本 v${version} · 点击查看更新日志`}
              className="text-[9px] leading-none font-mono text-ink-300 hover:text-brand-600 pb-0.5"
            >
              v{version}
            </button>
          )}
        </div>
      </aside>

      {/* Tier 2 — contextual panel: conversation list (only on the chat view) */}
      {activeView === 'chat' && convPanelOpen && (
        <aside className="w-60 shrink-0 border-r border-ink-200 bg-ink-50/40 flex flex-col max-md:fixed max-md:left-14 max-md:top-0 max-md:bottom-0 max-md:z-40 max-md:shadow-2xl">
          <div className="px-3 pt-3 pb-1.5">
            <span className="text-[11px] font-medium text-ink-500 uppercase tracking-wide">{t('side.conversations')}</span>
          </div>
          <div className="flex-1 overflow-y-auto scroll-hide px-2 pb-2 space-y-0.5">
            {convs.length === 0 && <div className="px-2 py-3 text-xs text-ink-400">{t('side.noSessions')}</div>}
            {convs.map((c) => {
              const active = activeConv === c.id;
              return (
                <div
                  key={c.id}
                  className={`group flex items-center gap-2 rounded-lg px-1.5 py-1.5 ${active ? 'bg-brand-50 ring-1 ring-brand-200' : 'hover:bg-white'}`}
                >
                  <span className={`shrink-0 w-7 h-7 rounded-lg grid place-items-center text-xs font-semibold ${avatarColor(c.id)}`}>
                    {avatarChar(c.title)}
                  </span>
                  {editingId === c.id ? (
                    <input
                      autoFocus
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      onKeyDown={(e) => { if (e.key === 'Enter') saveRename(c); else if (e.key === 'Escape') setEditingId(null); }}
                      onBlur={() => saveRename(c)}
                      className="flex-1 min-w-0 text-sm px-1.5 py-1 rounded border border-brand-300 focus:outline-none bg-white"
                    />
                  ) : (
                    <button
                      onClick={() => { onSelectConv(c.id); if (typeof window !== 'undefined' && window.innerWidth < 768) setConvPanelOpen(false); }}
                      className={`flex-1 min-w-0 text-left text-sm truncate ${active ? 'text-brand-700 font-medium' : 'text-ink-700'}`}
                    >
                      {c.title}
                    </button>
                  )}
                  {editingId === c.id ? (
                    <button onMouseDown={(e) => e.preventDefault()} onClick={() => saveRename(c)} title="保存" className="shrink-0 p-1 text-ink-400 hover:text-emerald-600"><Check className="w-3.5 h-3.5" /></button>
                  ) : (
                    <div className="shrink-0 flex items-center opacity-0 group-hover:opacity-100">
                      <button onClick={() => startRename(c)} title="重命名" className="p-1 text-ink-400 hover:text-brand-600"><Pencil className="w-3.5 h-3.5" /></button>
                      <button onClick={() => del(c)} title="删除会话" className="p-1 text-ink-400 hover:text-red-600"><Trash2 className="w-3.5 h-3.5" /></button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </aside>
      )}
    </div>
  );
}

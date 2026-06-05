'use client';

import { MessageSquarePlus, BookOpen, Database, Settings, LogOut, Trash2, Pencil, Check } from 'lucide-react';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { api, type Conversation, setToken } from '@/lib/api';
import LanguageToggle from '@/components/LanguageToggle';
import { useT } from '@/lib/i18n';

type View = 'chat' | 'datasets' | 'algorithms' | 'settings';

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

  useEffect(() => {
    api.listConversations().then(setConvs).catch(() => {});
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

  function logout() {
    setToken(null);
    router.push('/login');
  }

  const NavBtn = ({ id, label, icon }: { id: View; label: string; icon: React.ReactNode }) => (
    <button
      onClick={() => onChangeView(id)}
      className={`flex items-center gap-2 w-full px-3 py-2 rounded-lg text-sm ${
        activeView === id ? 'bg-brand-50 text-brand-700 font-medium' : 'text-ink-700 hover:bg-ink-100'
      }`}
    >
      {icon}
      {label}
    </button>
  );

  return (
    <aside className="w-64 shrink-0 border-r border-ink-200 bg-white flex flex-col">
      <div className="p-4 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2 font-semibold">
          <div className="w-7 h-7 rounded-lg bg-brand-600 text-white grid place-items-center text-sm">N</div>
          Numetrix
        </Link>
        <LanguageToggle />
      </div>

      <div className="px-3 space-y-1">
        <NavBtn id="chat" label={t('side.chat')} icon={<MessageSquarePlus className="w-4 h-4" />} />
        <NavBtn id="datasets" label={t('side.datasets')} icon={<Database className="w-4 h-4" />} />
        <NavBtn id="algorithms" label={t('side.algorithms')} icon={<BookOpen className="w-4 h-4" />} />
        <NavBtn id="settings" label={t('side.settings')} icon={<Settings className="w-4 h-4" />} />
      </div>

      {activeView === 'chat' && (
        <div className="mt-4 flex-1 overflow-y-auto scroll-hide px-3">
          <div className="flex items-center justify-between px-1 py-2 text-xs uppercase tracking-wide text-ink-500">
            <span>{t('side.conversations')}</span>
            <button onClick={onNewConv} className="text-brand-600 hover:underline">{t('side.new')}</button>
          </div>
          <div className="space-y-1">
            {convs.length === 0 && <div className="px-2 text-xs text-ink-500">{t('side.noSessions')}</div>}
            {convs.map((c) => (
              <div
                key={c.id}
                className={`group flex items-center gap-0.5 rounded ${
                  activeConv === c.id ? 'bg-brand-50' : 'hover:bg-ink-100'
                }`}
              >
                {editingId === c.id ? (
                  <input
                    autoFocus
                    value={editTitle}
                    onChange={(e) => setEditTitle(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') saveRename(c); else if (e.key === 'Escape') setEditingId(null); }}
                    onBlur={() => saveRename(c)}
                    className="flex-1 min-w-0 text-sm px-2 py-1.5 rounded border border-brand-300 focus:outline-none bg-white"
                  />
                ) : (
                  <button
                    onClick={() => onSelectConv(c.id)}
                    className={`flex-1 min-w-0 text-left text-sm px-2 py-1.5 truncate ${activeConv === c.id ? 'text-brand-700' : ''}`}
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
            ))}
          </div>
        </div>
      )}

      <div className="mt-auto border-t border-ink-200 p-3">
        <button onClick={logout} className="flex items-center gap-2 text-sm text-ink-500 hover:text-ink-900">
          <LogOut className="w-4 h-4" /> {t('side.signout')}
        </button>
      </div>
    </aside>
  );
}

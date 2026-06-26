'use client';

import { Languages } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useLangStore, type Lang } from '@/lib/i18n';

export default function LanguageToggle({ size = 'sm', compact = false }: { size?: 'sm' | 'md'; compact?: boolean }) {
  const lang = useLangStore((s) => s.lang);
  const setLang = useLangStore((s) => s.setLang);
  // useState to defeat SSR/CSR hydration mismatch — render nothing on the first paint.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted) {
    return <div className={compact ? 'w-10 h-10' : size === 'sm' ? 'w-14 h-7' : 'w-20 h-9'} />;
  }

  function pick(next: Lang) {
    setLang(next);
    if (typeof document !== 'undefined') {
      document.documentElement.setAttribute('lang', next === 'zh' ? 'zh-CN' : 'en');
    }
  }

  // Compact single-button variant for the narrow icon rail: shows the current
  // language, clicking switches to the other (no room for a horizontal pill).
  if (compact) {
    return (
      <button
        onClick={() => pick(lang === 'zh' ? 'en' : 'zh')}
        title="Language / 语言"
        className="w-10 h-10 grid place-items-center rounded-xl text-[11px] font-semibold text-ink-400 hover:bg-ink-100 hover:text-ink-700"
      >
        {lang === 'zh' ? '中' : 'EN'}
      </button>
    );
  }

  const isSmall = size === 'sm';
  const base = isSmall ? 'text-[11px] px-1.5 py-0.5' : 'text-xs px-2 py-1';
  return (
    <div className={`inline-flex items-center gap-1 rounded-full bg-ink-100 ring-1 ring-ink-200 p-0.5 ${isSmall ? '' : 'p-1'}`} title="Language / 语言">
      <Languages className={isSmall ? 'w-3 h-3 ml-1 text-ink-500' : 'w-3.5 h-3.5 ml-1.5 text-ink-500'} />
      <button
        onClick={() => pick('en')}
        className={`${base} rounded-full transition ${lang === 'en' ? 'bg-white text-ink-900 shadow-sm font-medium' : 'text-ink-500 hover:text-ink-900'}`}
      >EN</button>
      <button
        onClick={() => pick('zh')}
        className={`${base} rounded-full transition ${lang === 'zh' ? 'bg-white text-ink-900 shadow-sm font-medium' : 'text-ink-500 hover:text-ink-900'}`}
      >中文</button>
    </div>
  );
}

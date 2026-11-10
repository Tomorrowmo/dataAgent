'use client';

import type { ReactNode } from 'react';
import { Search } from 'lucide-react';
import { Hint as UiHint } from '@/components/ui';

// Shared pieces for the 算法 / 技能 / 流程 pages (改进清单-9): every page is a
// left list + a right area that shows an overview until something is picked.
// Overview = title + lead → two entry tiles → one page-specific block → counts.

export function Overview({ title, lead, children }: { title: string; lead: string; children: ReactNode }) {
  return (
    <div className="max-w-[900px] mx-auto px-6 md:px-10 pt-7 pb-12">
      <h1 className="text-[22px] font-semibold text-ink-900">{title}</h1>
      <p className="mt-1.5 text-[13.5px] leading-relaxed text-ink-600">{lead}</p>
      {children}
    </div>
  );
}

export function Entries({ children }: { children: ReactNode }) {
  return <div className="mt-5 grid grid-cols-1 sm:grid-cols-2 gap-2.5">{children}</div>;
}

/** One entry tile. `primary` = the page's main way in (filled icon). Without
 *  onClick it is an explanation tile (e.g. 「从对话保存」 happens in the chat). */
export function EntryTile({ icon, title, desc, primary, onClick, disabled }: {
  icon: ReactNode; title: string; desc: string; primary?: boolean; onClick?: () => void; disabled?: boolean;
}) {
  const body = (
    <>
      <span className={`w-8 h-8 rounded-md grid place-items-center shrink-0 ${primary ? 'bg-brand-600 text-white' : 'bg-ink-100 text-ink-700'}`}>{icon}</span>
      <span className="min-w-0">
        <span className="block text-sm font-medium text-ink-900">{title}</span>
        <span className="block mt-0.5 text-xs leading-relaxed text-ink-500">{desc}</span>
      </span>
    </>
  );
  const cls = 'flex gap-3 items-start p-3.5 rounded-lg bg-white text-left ring-1 transition-colors';
  if (!onClick) return <div className={`${cls} ring-ink-150`}>{body}</div>;
  return (
    <button onClick={onClick} disabled={disabled}
      className={`${cls} ${primary ? 'ring-brand-300 hover:ring-brand-600' : 'ring-ink-150 hover:ring-ink-300'} disabled:opacity-50`}>
      {body}
    </button>
  );
}

export function Hint({ children }: { children: ReactNode }) {
  return <UiHint className="mt-2">{children}</UiHint>;
}

export function Section({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section className="mt-7">
      <div className="flex items-baseline gap-2">
        <h2 className="text-sm font-semibold text-ink-900">{title}</h2>
        {note && <span className="text-xs text-ink-500">{note}</span>}
      </div>
      {children}
    </section>
  );
}

export function Rows({ children }: { children: ReactNode }) {
  return <div className="mt-2 bg-white rounded-lg ring-1 ring-ink-150 divide-y divide-ink-150">{children}</div>;
}

export function Row({ tag, name, meta, action, onAction }: {
  tag?: string; name: ReactNode; meta?: ReactNode; action?: string; onAction?: () => void;
}) {
  return (
    <div className="flex items-center gap-2.5 px-3.5 py-2.5 text-[13px] min-w-0">
      {tag && <span className="shrink-0 text-[11px] px-1.5 py-px rounded-sm bg-warning-50 text-warning-700">{tag}</span>}
      <span className="font-medium text-ink-900 shrink-0 max-w-[45%] truncate">{name}</span>
      {meta && <span className="text-xs text-ink-500 truncate min-w-0">{meta}</span>}
      {action && (
        <button onClick={onAction}
          className="ml-auto shrink-0 h-7 px-2.5 rounded-md bg-white ring-1 ring-ink-300 text-[12.5px] text-ink-800 hover:bg-ink-50">{action}</button>
      )}
    </div>
  );
}

/** 「库里有什么」: one chip per group with its count; clicking jumps the list there. */
export function Counts({ items }: { items: { label: string; n: number; onClick?: () => void }[] }) {
  return (
    <Section title="库里有什么">
      <div className="mt-2 flex flex-wrap gap-2">
        {items.map((c) => (
          <button key={c.label} onClick={c.onClick} disabled={!c.onClick}
            className="px-3 py-2 rounded-md bg-white ring-1 ring-ink-150 text-[12.5px] text-ink-700 enabled:hover:ring-ink-300">
            {c.label}<span className="ml-1.5 font-mono text-ink-400">{c.n}</span>
          </button>
        ))}
      </div>
    </Section>
  );
}

/** Left-list header: page name + search box. */
export function ListHead({ title, q, onQ, placeholder, extra }: {
  title: string; q: string; onQ: (v: string) => void; placeholder: string; extra?: ReactNode;
}) {
  return (
    <div className="px-3.5 pt-3.5 pb-2.5 border-b border-ink-150">
      <div className="flex items-center gap-2 h-7">
        <span className="text-[15px] font-semibold text-ink-900">{title}</span>
        {extra && <span className="ml-auto">{extra}</span>}
      </div>
      <div className="relative mt-2.5">
        <Search className="w-3.5 h-3.5 text-ink-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
        <input value={q} onChange={(e) => onQ(e.target.value)} placeholder={placeholder}
          className="w-full rounded-md pl-8 pr-2 h-8 bg-ink-50 ring-1 ring-inset ring-ink-200 text-xs focus:outline-none focus:ring-brand-600" />
      </div>
    </div>
  );
}

/** Group label inside the left list. */
export function ListGroup({ label, n, id }: { label: string; n: number; id?: string }) {
  return (
    <div id={id} className="flex justify-between mx-1.5 mt-3 mb-1 text-[11px] text-ink-500 scroll-mt-2">
      <span>{label}</span><span className="font-mono">{n}</span>
    </div>
  );
}

/** 「← 概览」 bar above a detail view. */
export function BackBar({ onBack, children }: { onBack: () => void; children?: ReactNode }) {
  return (
    <div className="shrink-0 flex items-center gap-2 px-4 h-9 bg-white border-b border-ink-200">
      <button onClick={onBack} className="text-[13px] text-brand-600 hover:text-brand-800">← 概览</button>
      {children}
    </div>
  );
}

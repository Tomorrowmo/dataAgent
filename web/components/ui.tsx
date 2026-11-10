// Small shared visual primitives for the design system
// (docs/ui-redesign-proposal.html · 02 设计规范 / 03 组件).
import type { ReactNode } from 'react';
import { Info } from 'lucide-react';

/** The "AI" mark: a tiny mono label. AI-generated content has no colour of its
 *  own — it is identified by this mark plus a dashed outline. */
export function AiMark({ className = '' }: { className?: string }) {
  return (
    <span className={`inline-flex items-center font-mono text-[10px] font-semibold leading-[14px] px-[3px] rounded-sm border border-ink-600 text-ink-700 ${className}`}>
      AI
    </span>
  );
}

/** Provenance tag. 内置 = solid brand · 自定义 = brand outline ·
 *  AI 待复核 = dashed grey + AI mark · AI 已复核 = solid grey + AI mark ·
 *  派生 = grey with ↳. Shape + text carry the meaning, not colour alone. */
export function SourceTag({ kind, children, className = '' }: {
  kind: 'builtin' | 'custom' | 'ai' | 'ai-reviewed' | 'derived';
  children?: ReactNode;
  className?: string;
}) {
  const base = 'inline-flex items-center gap-1 text-[11px] font-medium leading-4 px-1.5 py-px rounded-sm whitespace-nowrap';
  switch (kind) {
    case 'builtin':
      return <span className={`${base} bg-brand-600 text-white ${className}`}>{children ?? '内置'}</span>;
    case 'custom':
      return <span className={`${base} border border-brand-600 text-brand-700 ${className}`}>{children ?? '自定义'}</span>;
    case 'ai':
      return <span className={`${base} border border-dashed border-ink-600 text-ink-700 ${className}`}><AiMark />{children ?? '待复核'}</span>;
    case 'ai-reviewed':
      return <span className={`${base} border border-ink-600 text-ink-700 ${className}`}><AiMark />{children ?? '已复核'}</span>;
    case 'derived':
      return <span className={`${base} bg-ink-150 text-ink-700 font-mono ${className}`}>↳ {children ?? '派生'}</span>;
  }
}

/** Status = dot + text. No coloured pills. */
export function StatusDot({ tone, children, className = '' }: {
  tone: 'ok' | 'run' | 'warn' | 'error' | 'idle';
  children: ReactNode;
  className?: string;
}) {
  const map = {
    ok: ['bg-success-600', 'text-success-700'],
    run: ['bg-brand-600', 'text-brand-700'],
    warn: ['bg-warning-500', 'text-warning-700'],
    error: ['bg-danger-600', 'text-danger-700'],
    idle: ['bg-ink-400', 'text-ink-600'],
  }[tone];
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs ${map[1]} ${className}`}>
      <span className={`w-[7px] h-[7px] rounded-full shrink-0 ${map[0]}`} />
      {children}
    </span>
  );
}

/** 提示文字 (改进清单-5 · 8, 方案 A): 12px blue-grey. A standalone line gets a
 *  small ⓘ; `inline` (a short note next to a control or label) has no icon.
 *  Errors are not hints — they stay red. */
export function Hint({ children, inline = false, center = false, className = '' }: {
  children: ReactNode; inline?: boolean; center?: boolean; className?: string;
}) {
  if (inline) return <span className={`text-xs leading-relaxed font-normal text-hint ${className}`}>{children}</span>;
  return (
    <p className={`flex gap-1.5 items-start text-xs leading-relaxed font-normal text-hint ${center ? 'justify-center text-center' : ''} ${className}`}>
      <Info className="w-3.5 h-3.5 shrink-0 mt-[2px]" strokeWidth={2} /><span>{children}</span>
    </p>
  );
}

'use client';

import type { ReactNode } from 'react';
import { AlertTriangle } from 'lucide-react';
import { explainErrorText } from '@/lib/errorHints';

/** Who acts after the error: the AI keeps going, or the user has to. */
export type ErrorNext = { who: 'ai' | 'user'; text: string };

/** Ready-made 「接下来」 lines for the places errors show up. */
export const NEXT = {
  aiRunning: { who: 'ai', text: 'AI 会根据这个报错调整参数或换一个算法再试，你不用操作，等它给出回答即可。' },
  aiDone: { who: 'ai', text: 'AI 已经根据这个报错调整过做法，结果以后面的回答为准。如果回答里仍没有解决，可以换一种说法再问，或先检查数据。' },
  userRun: { who: 'user', text: '这次是你直接运行的，不会自动重试：按上面的原因改参数或换数据后，再点「执行」。看不懂可以点下面的「用人话解释这个错误」。' },
  userFlow: { who: 'user', text: '流程在这一步停下了，后面的步骤没有运行：改这一步的参数或换数据后重新运行流程。' },
} satisfies Record<string, ErrorNext>;

/** An algorithm / sandbox error: one plain sentence first (what happened and
 *  why), then who acts next, the raw message folded underneath. `who` names
 *  the step, e.g. 「第 2 步 · 峰值检测」. `children` = extra actions. */
export default function ErrorNote({ error, who, next, compact = false, children }: {
  error: string; who?: string; next?: ErrorNext; compact?: boolean; children?: ReactNode;
}) {
  const h = explainErrorText(error);
  const pad = compact ? 'pl-5' : 'pl-6';
  return (
    <div className={`rounded-md bg-danger-50 border border-danger-200 ${compact ? 'px-2.5 py-2' : 'p-3'} space-y-1.5`}>
      <div className={`flex items-start gap-2 text-danger-700 ${compact ? 'text-xs' : 'text-sm'}`}>
        <AlertTriangle className={`${compact ? 'w-3.5 h-3.5' : 'w-4 h-4'} mt-0.5 shrink-0`} />
        <div className="min-w-0">
          {who && <span className="font-medium">{who}出错：</span>}{h.summary}
        </div>
      </div>
      {next && (
        <div className={`${pad} flex items-start gap-1.5 ${compact ? 'text-[11.5px]' : 'text-xs'} text-ink-700`}>
          <span className={`shrink-0 px-1.5 py-px rounded-sm text-[11px] font-medium ${next.who === 'ai' ? 'bg-white text-ink-700 ring-1 ring-ink-200' : 'bg-warning-100 text-warning-800'}`}>
            {next.who === 'ai' ? 'AI 会继续' : '需要你处理'}
          </span>
          <span className="leading-relaxed">{next.text}</span>
        </div>
      )}
      <details className={`${pad} text-[11px] text-danger-700/80`}>
        <summary className="cursor-pointer select-none hover:text-danger-800">查看原始报错{h.type ? `（${h.type}）` : ''}</summary>
        <pre className="mt-1 max-h-60 overflow-auto whitespace-pre-wrap break-all font-mono bg-white/60 rounded p-2 text-ink-700">{error.slice(0, 4000)}</pre>
      </details>
      {children && <div className={pad}>{children}</div>}
    </div>
  );
}

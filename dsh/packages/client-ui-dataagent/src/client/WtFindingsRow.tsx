/**
 * Keyed tool view for `wt_findings`.
 *
 * The point of this view is one distinction: an item that was **assessed and
 * failed** is not the same as an item that could **not be assessed**. In a flat
 * text dump those read alike, and a 未评定 item mistaken for a pass is the exact
 * failure this module exists to prevent. So the two live in separate blocks
 * with different labels, and the unassessed block states what is missing.
 *
 * Pure function of the durable slice — no service reads, no clock — so it
 * replays identically from the session log.
 */

import { createElement as h, type ReactNode } from 'react'
import type { ToolCallViewProps } from '@deepseek-ai/dsh-client-ui-tool/client'
import { callArgs, callState, cardMeta, resultText } from './shared.ts'

/** Card payload projected by the host tool through `output.presentationMeta`. */
interface FindingsMeta {
  readonly runNo: string
  readonly grade: string
  readonly problems: readonly {
    readonly feature: string
    readonly level: string
    readonly verdict: string
    readonly cause: string
    readonly impact: string
    readonly action: string
    readonly value?: number
    readonly unit?: string
  }[]
  readonly unavailable: readonly { readonly feature: string, readonly reason: string }[]
}

/** Severity ordering used only for the accent colour; the label itself comes from the host. */
const LEVEL_TONE: Record<string, string> = {
  critical: '#9E3A38',
  严重: '#9E3A38',
  warning: '#8F6318',
  警告: '#8F6318',
  notice: '#4A6572',
  提示: '#4A6572',
}

function tone(level: string): string {
  return LEVEL_TONE[level] ?? '#4A6572'
}

function field(label: string, value: string): ReactNode {
  if (!value) return null
  return h('div', { style: { display: 'flex', gap: '0.5em', lineHeight: 1.7 } },
    h('span', { style: { opacity: 0.6, flex: 'none', minWidth: '5em' } }, label),
    h('span', null, value))
}

export function WtFindingsRow({ block }: ToolCallViewProps): ReactNode {
  const state = callState(block)
  const args = callArgs<{ run_no: string, batch_id: number }>(block)
  const meta = cardMeta<FindingsMeta>(block)

  if (state === 'running') {
    return h('div', { style: { opacity: 0.7 } },
      `正在读取车次 ${args.run_no ?? ''} 的判定…`)
  }

  // No projection (older log, or an error result): the model-facing text is
  // still the truthful record, so show it rather than an empty card.
  if (meta === null) {
    const text = resultText(block)
    return h('pre', {
      style: { whiteSpace: 'pre-wrap', margin: 0, fontFamily: 'inherit' },
    }, text ?? '（无结果）')
  }

  const problems = meta.problems ?? []
  const unavailable = meta.unavailable ?? []

  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: '0.9em' } },
    h('div', { style: { display: 'flex', alignItems: 'baseline', gap: '0.75em' } },
      h('strong', null, `车次 ${meta.runNo}`),
      h('span', {
        style: {
          border: '1px solid currentColor', padding: '0.05em 0.5em',
          fontSize: '0.85em',
          color: meta.grade.startsWith('合格') ? '#2C7A4E' : '#9E3A38',
        },
      }, meta.grade),
      h('span', { style: { opacity: 0.6, fontSize: '0.85em' } },
        `异常 ${problems.length} 项 · 未评定 ${unavailable.length} 项`)),

    problems.length > 0 && h('div', {
      style: { display: 'flex', flexDirection: 'column', gap: '0.75em' },
    },
    problems.map((p, i) => h('div', {
      key: `${p.feature}-${i}`,
      style: {
        borderLeft: `3px solid ${tone(p.level)}`,
        paddingLeft: '0.85em',
        display: 'flex', flexDirection: 'column', gap: '0.15em',
      },
    },
    h('div', { style: { display: 'flex', gap: '0.6em', alignItems: 'baseline' } },
      h('span', { style: { color: tone(p.level), fontSize: '0.85em' } }, `[${p.level}]`),
      h('strong', null, p.feature),
      p.value !== undefined && h('span', { style: { opacity: 0.7 } },
        `= ${p.value}${p.unit ?? ''}`)),
    field('判定', p.verdict),
    field('原因分析', p.cause),
    field('影响评估', p.impact),
    field('处理建议', p.action)))),

    // Kept visually distinct on purpose: this block is not a pass.
    unavailable.length > 0 && h('div', {
      style: {
        border: '1px dashed currentColor', opacity: 0.85,
        padding: '0.6em 0.85em',
        display: 'flex', flexDirection: 'column', gap: '0.25em',
      },
    },
    h('div', { style: { fontSize: '0.85em', opacity: 0.7 } },
      '未评定（输入不足，不代表合格）'),
    unavailable.map((u, i) => h('div', { key: `${u.feature}-${i}` },
      h('strong', null, u.feature), '：', u.reason))),

    problems.length === 0 && unavailable.length === 0
      && h('div', { style: { opacity: 0.7 } }, '没有异常项，也没有未评定项。'))
}

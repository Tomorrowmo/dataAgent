/**
 * The algorithm catalogue.
 *
 * Provenance is the column that matters. The product's premise is "vetted
 * classical algorithms first, sandboxed user code second, model-written code
 * last" — so where an algorithm came from, and whether it passed a test, are
 * shown next to its name rather than buried in a detail pane. An unverified
 * AI-written algorithm sitting unmarked beside a citable classical one would
 * undo the distinction the product is built on.
 */

import { createElement as h, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, type Algorithm } from '../api.ts'

const SOURCE_LABEL: Record<string, string> = {
  builtin: '内置', user: '用户上传', ai: 'AI 生成',
}

function Badge({ source, verified }: { source: string, verified: boolean }): ReactNode {
  // Built-ins carry their own vetting history; anything else is trustworthy only
  // insofar as it passed the sandbox, so an untested entry says so plainly.
  const untested = source !== 'builtin' && !verified
  const tone = source === 'builtin' ? '#2C7A4E' : untested ? '#9E3A38' : '#8F6318'
  return h('span', {
    style: {
      color: tone, border: '1px solid currentColor', borderRadius: '2px',
      padding: '0 0.4em', fontSize: '0.78em', whiteSpace: 'nowrap', flex: 'none',
    },
  }, SOURCE_LABEL[source] ?? source, untested ? ' · 未通过测试' : '')
}

export function AlgorithmsView(): ReactNode {
  const [rows, setRows] = useState<readonly Algorithm[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [category, setCategory] = useState<string>('')
  const [query, setQuery] = useState('')

  useEffect(() => {
    const ac = new AbortController()
    api.algorithms(ac.signal).then(setRows)
      .catch((e: Error) => { if (e.name !== 'AbortError') setError(e.message) })
    return () => ac.abort()
  }, [])

  const categories = useMemo(
    () => [...new Set((rows ?? []).map(a => a.category))].sort(), [rows])

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (rows ?? []).filter(a =>
      (category === '' || a.category === category)
      && (q === '' || a.slug.toLowerCase().includes(q)
        || a.name.toLowerCase().includes(q)
        || a.description.toLowerCase().includes(q)))
  }, [rows, category, query])

  if (error !== null) {
    return h('div', { style: { padding: '1.5em', color: '#b4544f' } }, `读取算法失败：${error}`)
  }
  if (rows === null) return h('div', { style: { padding: '1.5em', opacity: 0.6 } }, '读取中…')

  return h('div', { style: { display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 } },
    h('div', {
      style: {
        display: 'flex', gap: '0.6em', padding: '0.6em 0.9em', flexWrap: 'wrap',
        borderBottom: '1px solid rgba(127,127,127,0.25)', alignItems: 'center',
      },
    },
    h('input', {
      type: 'search', value: query, placeholder: '搜索算法',
      onChange: (e: { target: { value: string } }) => setQuery(e.target.value),
      style: {
        flex: '1 1 12em', minWidth: '8em', padding: '0.3em 0.6em',
        background: 'transparent', color: 'inherit', font: 'inherit',
        border: '1px solid rgba(127,127,127,0.4)', borderRadius: '3px',
      },
    }),
    h('select', {
      value: category,
      onChange: (e: { target: { value: string } }) => setCategory(e.target.value),
      style: {
        padding: '0.3em 0.5em', background: 'transparent', color: 'inherit',
        font: 'inherit', border: '1px solid rgba(127,127,127,0.4)', borderRadius: '3px',
      },
    },
    h('option', { value: '' }, `全部分类（${rows.length}）`),
    categories.map(c => h('option', { key: c, value: c }, c)))),

    h('div', { style: { overflow: 'auto', flex: 1, minHeight: 0 } },
      shown.length === 0
        ? h('div', { style: { padding: '1.5em', opacity: 0.65 } }, '没有匹配的算法。')
        : shown.map(a => h('div', {
          key: `${a.source}:${a.slug}`,
          'data-rlab-algo': a.slug,
          'data-rlab-source': a.source,
          style: {
            padding: '0.55em 0.9em', borderBottom: '1px solid rgba(127,127,127,0.15)',
            display: 'flex', flexDirection: 'column', gap: '0.15em',
          },
        },
        h('div', { style: { display: 'flex', gap: '0.6em', alignItems: 'baseline' } },
          h('code', { style: { fontSize: '0.9em' } }, a.slug),
          h('span', { style: { flex: 1, minWidth: 0 } }, a.name),
          h('span', { style: { opacity: 0.72, fontSize: '0.82em', flex: 'none' } }, a.category),
          h(Badge, { source: a.source, verified: a.verified === true })),
        a.description
          ? h('div', { style: { opacity: 0.78, fontSize: '0.86em' } }, a.description)
          : null))))
}

/**
 * The dataset view: a lineage tree, not a list.
 *
 * The methodology this product settled on is that **data is a lineage DAG**.
 * A flat list of names loses the one fact that makes a derived number
 * trustworthy — where it came from and what was done to it. So sources are
 * roots, derived datasets nest under their parent, and each edge is labelled
 * with the operation that created it.
 *
 * Read-only on purpose. Running an algorithm from here would mutate state
 * outside the session log; that belongs to a tool call.
 */

import { createElement as h, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, type Dataset, type Preview } from '../api.ts'

interface Node {
  readonly ds: Dataset
  readonly children: Node[]
}

/** Build the forest: sources are roots, derived nest under their parent. */
function buildForest(rows: readonly Dataset[]): Node[] {
  const byId = new Map<number, Node>()
  for (const ds of rows) byId.set(ds.id, { ds, children: [] })
  const roots: Node[] = []
  for (const node of byId.values()) {
    const parentId = node.ds.derived_from
    const parent = parentId === null ? undefined : byId.get(parentId)
    // A derived dataset whose parent was deleted is shown as a root rather than
    // hidden — an orphan is still real data, and silently dropping rows from a
    // provenance view is exactly the wrong failure.
    if (parent === undefined) roots.push(node)
    else parent.children.push(node)
  }
  const byIdDesc = (a: Node, b: Node) => b.ds.id - a.ds.id
  roots.sort(byIdDesc)
  for (const n of byId.values()) n.children.sort(byIdDesc)
  return roots
}

function opLabel(ds: Dataset): string | null {
  const op = ds.lineage?.op
  if (op === undefined) return null
  return op.label ?? op.slug ?? null
}

function Row({ node, depth, selected, onSelect }: {
  node: Node, depth: number, selected: number | null, onSelect: (id: number) => void,
}): ReactNode {
  const { ds } = node
  const isSel = selected === ds.id
  const op = opLabel(ds)
  return h('div', null,
    h('button', {
      type: 'button',
      onClick: () => onSelect(ds.id),
      // Test hooks: a substring search over page text passes for the wrong
      // reasons (a name containing an id, a column called `clean`). These let a
      // check count real rows and read real nesting depth.
      'data-rlab-dataset': String(ds.id),
      'data-rlab-depth': String(depth),
      style: {
        display: 'flex', alignItems: 'baseline', gap: '0.5em', width: '100%',
        textAlign: 'left', background: isSel ? 'rgba(127,127,127,0.16)' : 'transparent',
        border: 'none', borderLeft: `2px solid ${isSel ? 'currentColor' : 'transparent'}`,
        padding: '0.35em 0.6em', paddingLeft: `${0.6 + depth * 1.1}em`,
        color: 'inherit', font: 'inherit', cursor: 'pointer',
      },
    },
    h('span', { style: { opacity: 0.68, fontVariantNumeric: 'tabular-nums' } }, `#${ds.id}`),
    h('span', { style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, ds.name),
    op !== null && h('span', {
      style: { opacity: 0.78, fontSize: '0.82em', flex: 'none' },
      title: '产生这个数据集的算法',
    }, op),
    h('span', { style: { opacity: 0.62, fontSize: '0.82em', flex: 'none', fontVariantNumeric: 'tabular-nums' } },
      `${ds.rows}×${ds.columns}`)),
    node.children.map(c => h(Row, {
      key: c.ds.id, node: c, depth: depth + 1, selected, onSelect,
    })))
}

function PreviewPane({ id }: { id: number | null }): ReactNode {
  const [data, setData] = useState<Preview | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (id === null) { setData(null); setError(null); return }
    const ac = new AbortController()
    setData(null); setError(null)
    api.preview(id, 50, ac.signal)
      .then(setData)
      .catch((e: Error) => { if (e.name !== 'AbortError') setError(e.message) })
    return () => ac.abort()
  }, [id])

  if (id === null) return h('div', { style: { opacity: 0.6, padding: '1em' } }, '选择左侧的数据集查看内容。')
  if (error !== null) return h('div', { style: { padding: '1em', color: '#b4544f' } }, `读取失败：${error}`)
  if (data === null) return h('div', { style: { opacity: 0.6, padding: '1em' } }, '读取中…')
  if (data.rows.length === 0) return h('div', { style: { opacity: 0.6, padding: '1em' } }, '（无数据行）')

  return h('div', { style: { overflow: 'auto', height: '100%' } },
    h('table', { style: { borderCollapse: 'collapse', fontSize: '0.86em', width: '100%' } },
      h('thead', null, h('tr', null, data.columns.map(c =>
        h('th', {
          key: c,
          style: {
            textAlign: 'left', padding: '0.3em 0.7em', position: 'sticky', top: 0,
            background: 'var(--dsh-surface, rgba(127,127,127,0.12))',
            borderBottom: '1px solid rgba(127,127,127,0.35)', whiteSpace: 'nowrap',
          },
        }, c)))),
      h('tbody', null, data.rows.map((r, i) =>
        h('tr', { key: i },
          data.columns.map(c => h('td', {
            key: c,
            style: {
              padding: '0.25em 0.7em', borderBottom: '1px solid rgba(127,127,127,0.15)',
              fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap',
            },
          }, r[c] === null || r[c] === undefined ? '' : String(r[c]))))))))
}

export function DatasetsView(): ReactNode {
  const [rows, setRows] = useState<readonly Dataset[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<number | null>(null)

  useEffect(() => {
    const ac = new AbortController()
    api.datasets(ac.signal)
      .then((d) => { setRows(d); setSelected(s => s ?? (d[0]?.id ?? null)) })
      .catch((e: Error) => { if (e.name !== 'AbortError') setError(e.message) })
    return () => ac.abort()
  }, [])

  const forest = useMemo(() => buildForest(rows ?? []), [rows])

  if (error !== null) {
    return h('div', { style: { padding: '1.5em', color: '#b4544f' } },
      `读取数据集失败：${error}`)
  }
  if (rows === null) return h('div', { style: { padding: '1.5em', opacity: 0.6 } }, '读取中…')
  if (rows.length === 0) {
    return h('div', { style: { padding: '1.5em', opacity: 0.7 } },
      '还没有数据集。在对话里让 agent 用 dataset_ingest 导入一个文件。')
  }

  return h('div', {
    style: { display: 'grid', gridTemplateColumns: 'minmax(260px, 34%) 1fr', height: '100%', minHeight: 0 },
  },
  h('div', { style: { overflow: 'auto', borderRight: '1px solid rgba(127,127,127,0.25)', padding: '0.4em 0' } },
    forest.map(n => h(Row, { key: n.ds.id, node: n, depth: 0, selected, onSelect: setSelected }))),
  h('div', { style: { minWidth: 0, minHeight: 0 } }, h(PreviewPane, { id: selected })))
}

/**
 * Keyed tool view for `algo_run`.
 *
 * Shows the lineage edge the run created — parent dataset, operation, result —
 * because that edge is the product's claim to traceability. A line of prose
 * saying "saved as #263" makes the reader reconstruct the graph in their head;
 * the arrow shows it.
 *
 * Pure function of the durable slice, so it replays identically from the log.
 */
import { createElement as h } from 'react';
import { callArgs, callState, cardMeta, resultText } from "./shared.js";
function node(label, sub) {
    return h('div', {
        style: {
            border: '1px solid currentColor', padding: '0.4em 0.7em',
            display: 'flex', flexDirection: 'column', gap: '0.1em', minWidth: 0,
        },
    }, h('strong', { style: { whiteSpace: 'nowrap' } }, label), h('span', { style: { fontSize: '0.85em', opacity: 0.7 } }, sub));
}
export function AlgoRunRow({ block }) {
    const state = callState(block);
    const args = callArgs(block);
    const meta = cardMeta(block);
    if (state === 'running') {
        return h('div', { style: { opacity: 0.7 } }, `正在用 ${args.slug ?? '算法'} 处理数据集 #${args.dataset_id ?? '?'}…`);
    }
    if (meta === null) {
        const text = resultText(block);
        return h('pre', {
            style: { whiteSpace: 'pre-wrap', margin: 0, fontFamily: 'inherit' },
        }, text ?? '（无结果）');
    }
    return h('div', {
        style: {
            display: 'flex', alignItems: 'center', gap: '0.6em',
            flexWrap: 'wrap', lineHeight: 1.5,
        },
    }, node(`#${meta.derivedFrom}`, '源数据'), h('span', { style: { opacity: 0.6, whiteSpace: 'nowrap' } }, `── ${meta.algorithm} →`), node(`#${meta.datasetId}`, `${meta.rows} 行 × ${meta.columns} 列`), h('span', { style: { opacity: 0.7, minWidth: 0, wordBreak: 'break-word' } }, meta.name));
}

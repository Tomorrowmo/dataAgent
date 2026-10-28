/**
 * The workbench: RLab's own surface inside the harness shell.
 *
 * dsh's frame is deliberately chat-centric — `sidebar` and `conversation` are
 * single-occupancy slots, so registering into either would REPLACE the shell's
 * own column rather than add to it. `shell.overlay` is the one seat documented
 * as additive ("a frame-wide surface of your own"), so that is where a product
 * with its own views belongs.
 *
 * The layer is click-through by default; only the launcher and the open panel
 * take pointer events, so the conversation underneath stays fully usable when
 * the workbench is closed.
 */
import { createElement as h, useEffect, useState } from 'react';
import { DatasetsView } from "./views/DatasetsView.js";
import { AlgorithmsView } from "./views/AlgorithmsView.js";
const TABS = [
    { id: 'datasets', label: '数据集', render: () => h(DatasetsView) },
    { id: 'algorithms', label: '算法库', render: () => h(AlgorithmsView) },
];
/** Shared surface colour, resolved from the host theme with a readable fallback. */
const SURFACE = 'var(--dsh-color-surface, var(--dsh-surface, #17191a))';
export function Workbench() {
    const [open, setOpen] = useState(false);
    const [tab, setTab] = useState('datasets');
    // Escape closes. A full-frame panel that traps the reader with no keyboard
    // way out is a panel people learn to avoid opening.
    useEffect(() => {
        if (!open)
            return;
        const onKey = (e) => { if (e.key === 'Escape')
            setOpen(false); };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [open]);
    if (!open) {
        return h('button', {
            type: 'button',
            onClick: () => setOpen(true),
            title: 'RLab 工作台：数据集与算法库',
            style: {
                position: 'absolute', right: '1rem', bottom: '1rem', pointerEvents: 'auto',
                padding: '0.45em 0.9em', borderRadius: '999px', cursor: 'pointer',
                background: SURFACE, color: 'inherit', font: 'inherit',
                border: '1px solid rgba(127,127,127,0.45)',
                boxShadow: '0 2px 10px rgba(0,0,0,0.25)',
            },
        }, '工作台');
    }
    const active = TABS.find(t => t.id === tab) ?? TABS[0];
    return h('div', {
        style: {
            position: 'absolute', inset: 0, pointerEvents: 'auto',
            background: SURFACE, display: 'flex', flexDirection: 'column',
            borderTop: '1px solid rgba(127,127,127,0.3)',
        },
    }, h('div', {
        style: {
            display: 'flex', alignItems: 'center', gap: '0.4em',
            padding: '0.5em 0.9em', borderBottom: '1px solid rgba(127,127,127,0.25)',
        },
    }, h('strong', { style: { marginRight: '0.6em' } }, 'RLab 工作台'), TABS.map(t => h('button', {
        key: t.id,
        type: 'button',
        onClick: () => setTab(t.id),
        style: {
            padding: '0.28em 0.75em', cursor: 'pointer', font: 'inherit',
            color: 'inherit', borderRadius: '3px',
            background: t.id === tab ? 'rgba(127,127,127,0.2)' : 'transparent',
            border: `1px solid ${t.id === tab ? 'rgba(127,127,127,0.45)' : 'transparent'}`,
        },
    }, t.label)), h('span', { style: { flex: 1 } }), h('span', { style: { opacity: 0.5, fontSize: '0.8em', marginRight: '0.6em' } }, '只读视图'), h('button', {
        type: 'button',
        onClick: () => setOpen(false),
        title: '关闭（Esc）',
        style: {
            padding: '0.28em 0.7em', cursor: 'pointer', font: 'inherit', color: 'inherit',
            background: 'transparent', border: '1px solid rgba(127,127,127,0.4)', borderRadius: '3px',
        },
    }, '关闭')), h('div', { style: { flex: 1, minHeight: 0 } }, active.render()));
}

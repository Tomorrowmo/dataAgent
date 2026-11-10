'use client';

// Drag-to-resize for side panels (改进清单-5 · 4). The width is remembered per
// panel; double-clicking the edge restores the default. Desktop only.

import { useEffect, useRef, useState } from 'react';

export function useResizableWidth(key: string, def: number, min: number, max: number) {
  const [width, setWidth] = useState(def);
  const ref = useRef(def);
  useEffect(() => {
    try {
      const s = localStorage.getItem(key);
      if (s) { const w = Math.min(max, Math.max(min, parseInt(s, 10) || def)); setWidth(w); ref.current = w; }
    } catch { /* storage blocked */ }
  }, [key, def, min, max]);
  const set = (w: number, persist = false) => {
    const v = Math.min(max, Math.max(min, Math.round(w)));
    ref.current = v; setWidth(v);
    if (persist) { try { localStorage.setItem(key, String(v)); } catch { /* storage blocked */ } }
  };
  return { width, set, reset: () => set(def, true), current: ref };
}

/** An invisible strip over a panel edge; shows a thin brand line on hover / while dragging.
 *  `widthAt(clientX)` maps the pointer position to the new panel width. */
export default function ResizeHandle({ side, widthAt, onResize, onDone, onReset, title = '拖动调整宽度，双击恢复默认' }: {
  side: 'left' | 'right';
  widthAt: (clientX: number) => number;
  onResize: (w: number) => void;
  onDone: () => void;
  onReset: () => void;
  title?: string;
}) {
  const [drag, setDrag] = useState(false);
  useEffect(() => {
    if (!drag) return;
    const move = (e: PointerEvent) => onResize(widthAt(e.clientX));
    const up = () => { setDrag(false); onDone(); document.body.style.cursor = ''; document.body.style.userSelect = ''; };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    return () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
  }, [drag, widthAt, onResize, onDone]);
  return (
    <div
      role="separator" aria-orientation="vertical" title={title}
      onPointerDown={(e) => { e.preventDefault(); setDrag(true); document.body.style.cursor = 'col-resize'; document.body.style.userSelect = 'none'; }}
      onDoubleClick={onReset}
      className={`group absolute top-0 bottom-0 z-30 w-[7px] cursor-col-resize max-md:hidden ${side === 'right' ? '-right-[4px]' : '-left-[4px]'}`}
    >
      <span className={`absolute inset-y-0 left-[3px] w-[2px] transition-colors ${drag ? 'bg-brand-600' : 'bg-transparent group-hover:bg-brand-400'}`} />
    </div>
  );
}

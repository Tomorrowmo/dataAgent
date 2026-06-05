'use client';

import { useEffect, useMemo, useState } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import * as THREE from 'three';
import { Loader2, Box } from 'lucide-react';
import { api } from '@/lib/api';

/**
 * Interactive 3D point-cloud viewer for mesh / CGNS datasets: renders the mesh
 * points (X/Y/Z columns) colored by a chosen field (jet colormap), with orbit /
 * zoom / pan. Geometry comes straight from the stored table — no CGNS re-read.
 * A first-cut "see the field in space"; surface/volume rendering is a later step.
 */

const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
/** Jet colormap: t∈[0,1] → [r,g,b]∈[0,1]. */
function jet(t: number): [number, number, number] {
  t = clamp01(t);
  return [clamp01(1.5 - Math.abs(4 * t - 3)), clamp01(1.5 - Math.abs(4 * t - 2)), clamp01(1.5 - Math.abs(4 * t - 1))];
}

function Cloud({ positions, colors, size }: { positions: Float32Array; colors: Float32Array; size: number }) {
  const geom = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    g.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    g.computeBoundingSphere();
    return g;
  }, [positions, colors]);
  return (
    <points geometry={geom}>
      <pointsMaterial vertexColors size={size} sizeAttenuation={false} />
    </points>
  );
}

type ColorData = { values: (number | null)[] | null; cmin: number; cmax: number };

export default function MeshViewer3D({ datasetId }: { datasetId: number; name?: string }) {
  const [positions, setPositions] = useState<Float32Array | null>(null);
  const [fields, setFields] = useState<string[]>([]);
  const [field, setField] = useState('');
  const [colorData, setColorData] = useState<ColorData | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [size, setSize] = useState(2.5);
  const [total, setTotal] = useState(0);
  // Slicing (剖切): clip the cloud along an axis to reveal interior fields.
  const [clipAxis, setClipAxis] = useState(-1); // -1 none, 0=X 1=Y 2=Z
  const [clipVal, setClipVal] = useState(0.5);   // 0..1 along the axis range
  const [clipKeepLow, setClipKeepLow] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setErr(''); setPositions(null);
    api.datasetPoints3d(datasetId).then((d) => {
      if (cancelled) return;
      const n = d.n;
      // Normalize to a unit cube centered at the origin so the default camera +
      // OrbitControls frame it regardless of the model's real-world scale.
      let minx = Infinity, miny = Infinity, minz = Infinity, maxx = -Infinity, maxy = -Infinity, maxz = -Infinity;
      for (let i = 0; i < n; i++) {
        const x = d.x[i], y = d.y[i], z = d.z[i];
        if (x < minx) minx = x; if (x > maxx) maxx = x;
        if (y < miny) miny = y; if (y > maxy) maxy = y;
        if (z < minz) minz = z; if (z > maxz) maxz = z;
      }
      const cx = (minx + maxx) / 2, cy = (miny + maxy) / 2, cz = (minz + maxz) / 2;
      const ext = Math.max(maxx - minx, maxy - miny, maxz - minz) || 1;
      const pos = new Float32Array(n * 3);
      for (let i = 0; i < n; i++) {
        pos[i * 3] = (d.x[i] - cx) / ext;
        pos[i * 3 + 1] = (d.y[i] - cy) / ext;
        pos[i * 3 + 2] = (d.z[i] - cz) / ext;
      }
      setPositions(pos);
      setFields(d.fields);
      setField(d.color_field ?? '');
      setColorData({ values: d.color, cmin: d.cmin, cmax: d.cmax });
      setTotal(d.total);
      setLoading(false);
    }).catch((e) => { if (!cancelled) { setErr((e as Error).message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [datasetId]);

  function pickField(f: string) {
    setField(f);
    api.datasetColumn(datasetId, f).then((d) => setColorData({ values: d.values, cmin: d.cmin, cmax: d.cmax })).catch(() => {});
  }

  const colors = useMemo(() => {
    if (!positions || !colorData) return null;
    const n = positions.length / 3;
    const col = new Float32Array(n * 3);
    const { values, cmin, cmax } = colorData;
    const span = (cmax - cmin) || 1;
    for (let i = 0; i < n; i++) {
      const v = values ? values[i] : null;
      if (v == null) { col[i * 3] = 0.55; col[i * 3 + 1] = 0.55; col[i * 3 + 2] = 0.6; continue; }
      const [r, g, b] = jet((v - cmin) / span);
      col[i * 3] = r; col[i * 3 + 1] = g; col[i * 3 + 2] = b;
    }
    return col;
  }, [positions, colorData]);

  // Apply the slice: keep only points on the chosen side of the cut plane.
  const view = useMemo(() => {
    if (!positions || !colors) return null;
    if (clipAxis < 0) return { pos: positions, col: colors };
    const n = positions.length / 3;
    let mn = Infinity, mx = -Infinity;
    for (let i = 0; i < n; i++) { const v = positions[i * 3 + clipAxis]; if (v < mn) mn = v; if (v > mx) mx = v; }
    const thr = mn + clipVal * (mx - mn);
    const keep: number[] = [];
    for (let i = 0; i < n; i++) { const v = positions[i * 3 + clipAxis]; if (clipKeepLow ? v <= thr : v >= thr) keep.push(i); }
    const pos = new Float32Array(keep.length * 3), col = new Float32Array(keep.length * 3);
    for (let j = 0; j < keep.length; j++) {
      const i = keep[j];
      pos[j * 3] = positions[i * 3]; pos[j * 3 + 1] = positions[i * 3 + 1]; pos[j * 3 + 2] = positions[i * 3 + 2];
      col[j * 3] = colors[i * 3]; col[j * 3 + 1] = colors[i * 3 + 1]; col[j * 3 + 2] = colors[i * 3 + 2];
    }
    return { pos, col };
  }, [positions, colors, clipAxis, clipVal, clipKeepLow]);

  if (loading) return <div className="py-12 text-center text-sm text-ink-400"><Loader2 className="w-4 h-4 animate-spin inline-block" /> 正在读取网格点…</div>;
  if (err) return <div className="py-8 text-center text-sm text-ink-400 flex items-center justify-center gap-1.5"><Box className="w-4 h-4" /> {err}</div>;
  if (!positions) return null;
  const shown = positions.length / 3;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs">
        <span className="font-medium text-ink-600">3D 网格 · {shown.toLocaleString()} 点{total > shown ? `(共 ${total.toLocaleString()},已降采样)` : ''}</span>
        {fields.length > 0 && (
          <label className="inline-flex items-center gap-1 text-ink-500">按场上色:
            <select value={field} onChange={(e) => pickField(e.target.value)} className="border border-ink-200 rounded-md px-1.5 py-1 bg-white max-w-[180px]">
              {fields.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
          </label>
        )}
        <label className="inline-flex items-center gap-1 text-ink-500">点大小
          <input type="range" min={1} max={6} step={0.5} value={size} onChange={(e) => setSize(Number(e.target.value))} />
        </label>
        {colorData && <Legend min={colorData.cmin} max={colorData.cmax} />}
      </div>

      {/* slicing controls */}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5 text-xs">
        <span className="text-ink-500">剖切:</span>
        <div className="inline-flex rounded-lg ring-1 ring-ink-200 overflow-hidden">
          {['无', 'X', 'Y', 'Z'].map((lab, i) => (
            <button key={lab} onClick={() => setClipAxis(i - 1)}
              className={`px-2 py-1 ${clipAxis === i - 1 ? 'bg-brand-600 text-white' : 'bg-white text-ink-500 hover:bg-ink-50'}`}>{lab}</button>
          ))}
        </div>
        {clipAxis >= 0 && (
          <>
            <input type="range" min={0} max={1} step={0.01} value={clipVal} onChange={(e) => setClipVal(Number(e.target.value))} className="w-40" />
            <button onClick={() => setClipKeepLow((v) => !v)} className="px-2 py-1 rounded-md ring-1 ring-ink-200 text-ink-600 hover:bg-ink-50">
              {clipKeepLow ? '保留 ≤ 侧' : '保留 ≥ 侧'}
            </button>
            {view && <span className="text-ink-400">{(view.pos.length / 3).toLocaleString()} 点</span>}
          </>
        )}
      </div>

      <div style={{ width: '100%', height: 460 }} className="rounded-xl ring-1 ring-ink-200 overflow-hidden">
        <Canvas camera={{ position: [1.2, 1.0, 1.5], fov: 50, near: 0.001, far: 100 }} dpr={[1, 1.6]}>
          <color attach="background" args={['#0b1020']} />
          <ambientLight intensity={0.9} />
          {view && <Cloud positions={view.pos} colors={view.col} size={size} />}
          <OrbitControls enableDamping makeDefault />
        </Canvas>
      </div>
      <div className="text-[11px] text-ink-400">拖动旋转 · 滚轮缩放 · 右键平移</div>
    </div>
  );
}

function fmt(v: number): string {
  if (v == null || Number.isNaN(v)) return '';
  const a = Math.abs(v);
  return (a >= 1000 || (a > 0 && a < 0.01)) ? v.toExponential(2) : v.toFixed(2);
}

function Legend({ min, max }: { min: number; max: number }) {
  const stops = Array.from({ length: 8 }, (_, i) => {
    const [r, g, b] = jet(i / 7);
    return `rgb(${(r * 255) | 0},${(g * 255) | 0},${(b * 255) | 0})`;
  }).join(',');
  return (
    <span className="inline-flex items-center gap-1 text-[10.5px] text-ink-500">
      <span>{fmt(min)}</span>
      <span style={{ background: `linear-gradient(to right, ${stops})` }} className="inline-block w-24 h-2.5 rounded ring-1 ring-ink-200" />
      <span>{fmt(max)}</span>
    </span>
  );
}

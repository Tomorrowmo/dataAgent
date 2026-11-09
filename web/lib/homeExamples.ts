// Home-page example questions (改进清单-4 · 第 2–4 步).
//
// The admin-editable config (GET/PUT /api/home/examples) is a list of tabs, each a
// list of questions. A built-in question points at a result card defined here
// (`builtin_key`); an admin-added question may carry a `snapshot` copied from one
// of the admin's own runs. Built-in sample data is generated client-side, the
// same way as the older STARTERS, and the numbers on the built-in cards are what
// the generated data actually gives.

export type ExampleKpi = { label: string; value: string; unit?: string; note?: string };
export type ExampleSeries = { name: string; values: (number | null)[] };
export type ExampleSnapshot = {
  title: string;
  code?: string;
  x: ExampleSeries;
  ys: ExampleSeries[];
  chain: string[];
  run_id?: number;
};
export type ExampleQuestion = {
  id: string;
  text: string;
  needs?: string;              // "需要的数据" — shown when no data is selected
  builtin_key?: string;        // → BUILTIN_RESULTS
  samples?: string[];          // built-in sample datasets this question can load
  snapshot?: ExampleSnapshot | null;
  kpis?: ExampleKpi[];         // admin-entered values for a snapshot card
  methods?: string;            // shown on the text-only card
  hidden?: boolean;
};
export type ExampleTab = { id: string; name: string; hidden?: boolean; questions: ExampleQuestion[] };
export type ExamplesConfig = { tabs: ExampleTab[] };

// ── deterministic sample data ─────────────────────────────────────────────
const range = (a: number, b: number, step = 1) => { const r: number[] = []; for (let x = a; x <= b + 1e-9; x += step) r.push(+x.toFixed(6)); return r; };
const csv = (headers: string[], rows: number[][]) => {
  const f = (x: number) => (Number.isFinite(x) ? +x.toFixed(5) : '');
  return [headers.join(','), ...rows.map((r) => r.map(f).join(','))].join('\n');
};
// Repeatable "noise" (no Math.random — the cards must match the data).
const jitter = (i: number, k = 1) => Math.sin(i * 12.9898 * k + 78.233) * 43758.5453 % 1;

export const ALPHA = range(-4, 20);
const POST: Record<number, number> = { 13: 1.36, 14: 1.38, 15: 1.30, 16: 1.12, 17: 1.04, 18: 0.98, 19: 0.95, 20: 0.93 };
export const CL1 = ALPHA.map((a, i) => (a <= 12 ? 0.095 * (a + 2) + 0.008 * Math.sin(i * 2.7 + 0.3) : POST[a]));
const POST2: Record<number, number> = { 13: -0.012, 14: -0.013, 15: -0.05, 16: -0.06, 17: -0.04, 18: -0.02, 19: -0.015, 20: -0.01 };
export const CL2 = ALPHA.map((a, i) => CL1[i] + (a <= 12 ? 0.004 * Math.sin(i * 1.9) : POST2[a]));
const cd = (cl: number, a: number) => 0.01788 + 0.04043 * cl * cl + (a > 14 ? 0.025 * (a - 14) ** 1.5 : 0);
const cm = (cl: number, a: number) => -0.02 - 0.01 * cl - (a > 14 ? 0.006 * (a - 14) : 0);
const reCurve = (s: number, stall: number, mx: number) => ALPHA.map((a) => {
  if (a <= stall - 2) return s * (a + 2);
  const lo = s * stall;                                 // value at stall-2
  if (a <= stall) return lo + (mx - lo) * (1 - ((stall - a) / 2) ** 2);
  return Math.max(mx - 0.09 * (a - stall) - 0.004 * (a - stall) ** 2, 0.62 * mx);
});
export const CL_RE = { re2: reCurve(0.089, 12, 1.24), re3: CL1, re5: reCurve(0.099, 16, 1.49) };

function windSweepCsv(cl: number[]) { return csv(['alpha_deg', 'CL', 'CD', 'Cm'], ALPHA.map((a, i) => [a, cl[i], cd(cl[i], a), cm(cl[i], a)])); }
function windReCsv() { return csv(['alpha_deg', 'CL_Re2e5', 'CL_Re3e5', 'CL_Re5e5'], ALPHA.map((a, i) => [a, CL_RE.re2[i], CL_RE.re3[i], CL_RE.re5[i]])); }
function pressureCsv() {
  const fs = 2000, n = 8000, rows: number[][] = [];
  for (let i = 0; i < n; i++) {
    const t = i / fs;
    rows.push([t, 12 * Math.sin(2 * Math.PI * 62.5 * t) + 3.5 * Math.sin(2 * Math.PI * 125 * t + 0.7) + 4 * (jitter(i) - 0.5) * 2 + 2.5 * Math.sin(2 * Math.PI * 7.3 * t)]);
  }
  return csv(['time_s', 'p_Pa'], rows);
}
function channelsCsv() {
  const n = 400, rows: number[][] = [];
  for (let i = 0; i < n; i++) {
    const t = i / 100, base = -0.8 + 0.05 * Math.sin(2 * Math.PI * 0.4 * t);
    const r = [t];
    for (let c = 1; c <= 12; c++) {
      let v = base + 0.02 * c + 0.01 * (jitter(i, c) - 0.5);
      if (c === 5) v += 0.06 * (jitter(i, 99) - 0.5) * 2;   // noisy channel
      if (c === 10) v += 0.0004 * i;                        // drifting channel
      r.push(v);
    }
    rows.push(r);
  }
  return csv(['time_s', ...range(1, 12).map((c) => `P${String(c).padStart(2, '0')}`)], rows);
}
function balanceCsv() {
  const fs = 100, n = 1000, rows: number[][] = [];
  for (let i = 0; i < n; i++) {
    const t = i / fs, alpha = 4 + 0.8 * t;   // slow sweep 4° → 12°
    const lift = 612 * 0.12 * 0.095 * (alpha + 2);
    rows.push([t, alpha, lift + 9 * Math.sin(2 * Math.PI * 13.7 * t) + 6 * Math.sin(2 * Math.PI * 29.3 * t + 1) + 4 * (jitter(i) - 0.5),
      0.08 * lift + 1.5 * (jitter(i, 3) - 0.5)]);
  }
  return csv(['time_s', 'alpha_deg', 'Fz_N', 'Fx_N'], rows);
}
function batteryCsv() {
  return csv(['cycle', 'capacity_Ah', 'resistance_mOhm', 'temp_rise_K'], range(0, 50).map((c) => [
    c, 2.31 - 0.0024 * c + 0.004 * Math.sin(c * 1.3), 18.4 + 0.052 * c + 0.15 * Math.sin(c * 0.9),
    [17, 33, 41].includes(c) ? 9 + (c % 3) : 4 + 1.2 * Math.sin(c * 2.1) + 0.02 * c,
  ]));
}
function vibrationCsv() {
  const fs = 2048, n = 4096, rows: number[][] = [];
  for (let i = 0; i < n; i++) {
    const t = i / fs;
    rows.push([t, 0.8 * Math.sin(2 * Math.PI * 98 * t) + 0.35 * Math.sin(2 * Math.PI * 196 * t + 0.4) + 0.15 * Math.sin(2 * Math.PI * 294 * t + 1.1)
      + 0.5 * Math.sin(2 * Math.PI * 50 * t) + 0.2 * Math.sin(2 * Math.PI * 150 * t) + 0.12 * (jitter(i) - 0.5) * 2]);
  }
  return csv(['time_s', 'accel_g'], rows);
}

/** Built-in sample datasets, created on first use (name must stay stable). */
export const SAMPLES: Record<string, () => string> = {
  '示例·风洞攻角扫描': () => windSweepCsv(CL1),
  '示例·风洞重复吹风': () => windSweepCsv(CL2),
  '示例·风洞雷诺数对比': windReCsv,
  '示例·天平信号': balanceCsv,
  '示例·脉动压力': pressureCsv,
  '示例·测点通道': channelsCsv,
  '示例·电池循环': batteryCsv,
  '示例·振动加速度': vibrationCsv,
};
// 示例·参数优化DOE already exists in STARTERS (lib/recipes.ts).

// ── default config ───────────────────────────────────────────────────────
export const DEFAULT_EXAMPLES: ExamplesConfig = {
  tabs: [
    { id: 'wind', name: '风洞试验', questions: [
      { id: 'w1', builtin_key: 'wind_lift', samples: ['示例·风洞攻角扫描'], text: '升力线斜率、失速攻角、最大升阻比分别是多少？', needs: '一组攻角扫描数据（攻角、CL、CD）' },
      { id: 'w2', builtin_key: 'wind_repeat', samples: ['示例·风洞攻角扫描', '示例·风洞重复吹风'], text: '两次吹风的结果一致吗？偏差集中在哪个攻角段？', needs: '同一工况的两组攻角扫描数据' },
      { id: 'w3', builtin_key: 'wind_smooth', samples: ['示例·天平信号'], text: '对天平信号做平滑，再按 q∞=612 Pa、S=0.12 m² 计算升力系数', needs: '天平力的时间序列' },
      { id: 'w4', builtin_key: 'wind_re', samples: ['示例·风洞雷诺数对比'], text: '把不同雷诺数下的升力曲线叠在一起比较', needs: '多个雷诺数下的升力系数' },
      { id: 'w5', builtin_key: 'wind_psd', samples: ['示例·脉动压力'], text: '脉动压力信号的主频是多少？按 D=0.1 m、U=30 m/s 算 Strouhal 数', needs: '脉动压力时间序列（含采样率）' },
      { id: 'w6', builtin_key: 'wind_channels', samples: ['示例·测点通道'], text: '检查各测点通道，列出数据异常的测点', needs: '多个测点的同步采集数据' },
    ] },
    { id: 'battery', name: '电池充放电', questions: [
      { id: 'b1', builtin_key: 'bat_fade', samples: ['示例·电池循环'], text: '第 1 圈到第 50 圈的容量衰减和内阻变化', needs: '按循环整理的容量、内阻数据' },
      { id: 'b2', builtin_key: 'bat_temp', samples: ['示例·电池循环'], text: '列出温升异常的循环', needs: '每个循环的温升数据' },
    ] },
    { id: 'vib', name: '振动 / NVH', questions: [
      { id: 'v1', builtin_key: 'vib_peak', samples: ['示例·振动加速度'], text: '振动信号的主峰频率及其谐波', needs: '加速度时间序列（含采样率）' },
      { id: 'v2', builtin_key: 'vib_notch', samples: ['示例·振动加速度'], text: '滤除 50 Hz 工频干扰后重新计算频谱', needs: '加速度时间序列（含采样率）' },
    ] },
    { id: 'doe', name: '工艺参数 / DOE', questions: [
      { id: 'd1', builtin_key: 'doe_rank', samples: ['示例·参数优化DOE'], text: '各设计参数对阻力的影响排序', needs: '一组试验设计数据（多个输入、一个输出）' },
      { id: 'd2', builtin_key: 'doe_fit', samples: ['示例·参数优化DOE'], text: '拟合阻力与攻角的关系，给出拟合优度', needs: '输入与输出两列' },
    ] },
  ],
};

// ── charts (plain SVG strings, chart palette) ─────────────────────────────
const C1 = '#2e5f8a', C2 = '#d0702e', C3 = '#4c8c5e', C4 = '#b5474e', MU = '#a0a6ae';
const W = 520, H = 250, L = 50, R = 500, T = 26, B = 218;
type Ax = { X: (v: number) => number; Y: (v: number) => number; g: string };
const fmt = (v: number) => (Math.abs(v) >= 1000 || (Math.abs(v) < 0.01 && v !== 0) ? v.toExponential(1) : String(+v.toFixed(3)));
function axes(xr: number[], yr: number[], xt: number[], yt: number[], xl: string, yl: string): Ax {
  const X = (v: number) => L + ((v - xr[0]) / (xr[1] - xr[0])) * (R - L);
  const Y = (v: number) => B - ((v - yr[0]) / (yr[1] - yr[0])) * (B - T);
  let g = `<g stroke="#eef0f2">${yt.map((v) => `<path d="M${L} ${Y(v)}H${R}"/>`).join('')}</g>`;
  g += `<path d="M${L} ${B}H${R}M${L} ${T - 6}V${B}" stroke="#c6cbd1" fill="none"/>`;
  g += `<g font-size="10.5" fill="#69707a" font-family="IBM Plex Mono,monospace">`
    + yt.map((v) => `<text x="${L - 6}" y="${Y(v) + 4}" text-anchor="end">${fmt(v)}</text>`).join('')
    + xt.map((v) => `<text x="${X(v)}" y="${B + 15}" text-anchor="middle">${fmt(v)}</text>`).join('')
    + `<text x="${L + 4}" y="${T - 10}">${esc(yl)}</text><text x="${R}" y="${B - 6}" text-anchor="end">${esc(xl)}</text></g>`;
  return { X, Y, g };
}
const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]!));
const svg = (inner: string, legend = '') => `<svg viewBox="0 0 ${W} ${H}" role="img" style="display:block;width:100%;height:auto">${inner}${legend}</svg>`;
function poly(A: Ax, xs: number[], ys: (number | null)[], c: string, o: { w?: number; dash?: string } = {}) {
  const segs: string[][] = [[]];
  xs.forEach((x, i) => { const y = ys[i]; if (y == null || !Number.isFinite(y)) { segs.push([]); return; } segs[segs.length - 1].push(`${A.X(x).toFixed(1)},${A.Y(y).toFixed(1)}`); });
  return segs.filter((s) => s.length > 1).map((s) => `<polyline fill="none" stroke="${c}" stroke-width="${o.w ?? 2}" ${o.dash ? `stroke-dasharray="${o.dash}"` : ''} stroke-linejoin="round" points="${s.join(' ')}"/>`).join('');
}
const dots = (A: Ax, xs: number[], ys: number[], c: string, hollow = false) => xs.map((x, i) => hollow
  ? `<circle cx="${A.X(x)}" cy="${A.Y(ys[i])}" r="3" fill="#fff" stroke="${c}" stroke-width="1.4"/>`
  : `<circle cx="${A.X(x)}" cy="${A.Y(ys[i])}" r="2.6" fill="${c}"/>`).join('');
const vmark = (A: Ax, x: number, c: string, label: string) => `<path d="M${A.X(x)} ${T - 6}V${B}" stroke="${c}" stroke-dasharray="3 3"/><text x="${A.X(x) + 6}" y="${T + 8}" font-size="11" fill="${c}" font-family="IBM Plex Mono,monospace">${esc(label)}</text>`;
function leg(items: [string, string, ('o' | 'd')?][]) {
  return `<g font-size="11" fill="#363b42">${items.map(([c, t, k], i) => {
    const x = R - items.length * 104 + i * 104 + 18;
    const mark = k === 'o' ? `<circle cx="${x}" cy="${T - 12}" r="3" fill="#fff" stroke="${c}" stroke-width="1.4"/>`
      : k === 'd' ? `<path d="M${x - 7} ${T - 12}h14" stroke="${c}" stroke-dasharray="4 3" stroke-width="1.6"/>`
        : `<path d="M${x - 7} ${T - 12}h14" stroke="${c}" stroke-width="2"/>`;
    return `${mark}<text x="${x + 11}" y="${T - 8}">${esc(t)}</text>`;
  }).join('')}</g>`;
}
function curve(f: (x: number) => number, a: number, b: number, n: number): [number[], number[]] {
  const xs: number[] = [], ys: number[] = [];
  for (let i = 0; i <= n; i++) { const x = a + ((b - a) * i) / n; xs.push(x); ys.push(f(x)); }
  return [xs, ys];
}
const noise = (f: number) => 2 * Math.sin(f * 0.7) + 1.6 * Math.sin(f * 2.3 + 1) + 1.2 * Math.sin(f * 5.1 + 2) + 0.8 * Math.sin(f * 11.7);
const clAxes = () => axes([-4, 20], [-0.4, 1.6], [-4, 0, 4, 8, 12, 16, 20], [-0.4, 0.1, 0.6, 1.1, 1.6], 'α (°)', 'CL');

/** "Nice" axis ticks for an arbitrary range. */
export function niceTicks(lo: number, hi: number, n = 5): number[] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [0, 1];
  if (lo === hi) { lo -= 1; hi += 1; }
  const raw = (hi - lo) / n, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.floor(lo / step) * step; v <= hi + step * 0.5; v += step) out.push(+v.toFixed(10));
  return out;
}

/** Line chart of an admin snapshot. */
export function snapshotChart(s: ExampleSnapshot): string {
  const xs = s.x.values.map((v) => (v == null ? NaN : v));
  const all = s.ys.flatMap((y) => y.values.filter((v): v is number => v != null && Number.isFinite(v)));
  const xt = niceTicks(Math.min(...xs.filter(Number.isFinite)), Math.max(...xs.filter(Number.isFinite)));
  const yt = niceTicks(Math.min(...all), Math.max(...all), 4);
  const A = axes([xt[0], xt[xt.length - 1]], [yt[0], yt[yt.length - 1]], xt, yt, s.x.name, s.ys.length === 1 ? s.ys[0].name : '');
  const cols = [C1, C2, C3];
  return svg(A.g + s.ys.map((y, i) => poly(A, xs, y.values, cols[i % 3], { w: 1.8 })).join(''),
    s.ys.length > 1 ? leg(s.ys.map((y, i) => [cols[i % 3], y.name] as [string, string])) : '');
}

export type BuiltinResult = { code?: string; title: string; chart: () => string; kpis: ExampleKpi[]; chain: string[] };

export const BUILTIN_RESULTS: Record<string, BuiltinResult> = {
  wind_lift: {
    title: '翼型攻角扫描 · 升力特性',
    chart: () => { const A = clAxes(); return svg(A.g + `<path d="M${A.X(-4)} ${A.Y(0.095 * -2)}L${A.X(12)} ${A.Y(0.095 * 14)}" stroke="${C1}" stroke-dasharray="5 4" opacity=".5"/>` + vmark(A, 14, C4, '失速 14°') + poly(A, ALPHA, CL1, C1, { w: 2.2 }) + dots(A, ALPHA, CL1, C1), leg([[C1, 'CL'], [C1, '线性段拟合', 'd']])); },
    kpis: [{ label: '升力线斜率', value: '0.095', unit: '/°', note: 'R²=0.9998' }, { label: '失速攻角', value: '14', unit: '°', note: 'CLmax=1.38' }, { label: '最大升阻比', value: '18.6', note: 'α=5°' }],
    chain: ['CL/CD 计算', 'α≤10° 取线性段', 'linear_regression', '取最大值'],
  },
  wind_repeat: {
    title: '重复吹风对比',
    chart: () => { const A = clAxes(); const band = `<rect x="${A.X(14)}" y="${T - 6}" width="${A.X(20) - A.X(14)}" height="${B - T + 6}" fill="#fbf1f1"/>`; return svg(band + A.g + poly(A, ALPHA, CL1, C1) + dots(A, ALPHA, CL1, C1) + dots(A, ALPHA, CL2, C2, true) + `<text x="${A.X(14.3)}" y="${B - 34}" font-size="11" fill="${C4}">偏差集中</text><text x="${A.X(14.3)}" y="${B - 20}" font-size="11" fill="${C4}">在 15°–17°</text>`, leg([[C1, '第 1 次'], [C2, '第 2 次', 'o']])); },
    kpis: [{ label: '线性段最大差值', value: '0.004', note: 'α ≤ 12°' }, { label: '最大偏差', value: '0.06', note: 'α=16°' }, { label: '失速攻角', value: '14 / 14', unit: '°' }],
    chain: ['两组数据按 α 对齐', 'derived_column 差值', '逐点比较'],
  },
  wind_smooth: {
    title: '天平 Fz 平滑与升力系数',
    chart: () => { const A = axes([0, 10], [500, 1200], [0, 2, 4, 6, 8, 10], [500, 700, 900, 1100], 't (s)', 'Fz (N)');
      const lift = (t: number) => 612 * 0.12 * 0.095 * (4 + 0.8 * t + 2);
      const [xs, ys] = curve((t) => lift(t) + 9 * Math.sin(2 * Math.PI * 13.7 * t) + 6 * Math.sin(2 * Math.PI * 29.3 * t + 1), 0, 10, 400);
      const [xs2, ys2] = curve(lift, 0, 10, 40);
      return svg(A.g + poly(A, xs, ys, MU, { w: 1 }) + poly(A, xs2, ys2, C1, { w: 2.4 }), leg([[MU, '原始'], [C1, '平滑后']])); },
    kpis: [{ label: '原始噪声 RMS', value: '7.7', unit: 'N' }, { label: '窗口 / 阶数', value: '21 / 3' }, { label: 'CL 范围', value: '0.57–1.33' }],
    chain: ['savgol_filter w=21 p=3', 'derived_column CL=Fz/(612×0.12)'],
  },
  wind_re: {
    title: '雷诺数影响',
    chart: () => { const A = clAxes(); return svg(A.g + poly(A, ALPHA, CL_RE.re2, C3) + poly(A, ALPHA, CL_RE.re3, C1) + poly(A, ALPHA, CL_RE.re5, C2), leg([[C3, 'Re 2×10⁵'], [C1, 'Re 3×10⁵'], [C2, 'Re 5×10⁵']])); },
    kpis: [{ label: 'CLmax', value: '1.24 / 1.38 / 1.49' }, { label: '失速攻角', value: '12 / 14 / 16', unit: '°' }],
    chain: ['3 组 CL 列', '叠加绘图'],
  },
  wind_psd: {
    title: '脉动压力频谱',
    chart: () => { const A = axes([0, 200], [-60, 0], [0, 50, 100, 150, 200], [-60, -40, -20, 0], 'f (Hz)', 'dB');
      const [xs, ys] = curve((f) => -46 + noise(f) + 30 * Math.exp(-(((f - 62.5) / 3.2) ** 2)) + 11 * Math.exp(-(((f - 125) / 3.5) ** 2)) - f * 0.03, 0, 200, 400);
      return svg(A.g + poly(A, xs, ys, C1, { w: 1.6 }) + vmark(A, 62.5, C4, '62.5 Hz  St=0.21')); },
    kpis: [{ label: '主频', value: '62.5', unit: 'Hz', note: '2 倍频 125 Hz' }, { label: 'Strouhal 数', value: '0.21', note: 'D=0.1 m, U=30 m/s' }],
    chain: ['fft_frequency_analysis fs=2000 Hz', 'find_peaks', 'St = f·D/U'],
  },
  wind_channels: {
    title: '测点通道检查',
    chart: () => { const A = axes([0, 13], [0, 6], [], [0, 2, 4, 6], '测点', '离散度 (相对值)');
      const v = [1.1, 0.9, 1.3, 1.0, 5.2, 1.2, 0.8, 1.4, 1.0, 4.6, 1.1, 0.9];
      const bars = v.map((y, i) => `<rect x="${A.X(i + 1) - 11}" y="${A.Y(y)}" width="22" height="${B - A.Y(y)}" fill="${y > 3 ? C4 : C1}" opacity="${y > 3 ? 1 : 0.75}" rx="1"/><text x="${A.X(i + 1)}" y="${B + 15}" text-anchor="middle" font-size="10" fill="#69707a" font-family="IBM Plex Mono,monospace">P${String(i + 1).padStart(2, '0')}</text>`).join('');
      return svg(A.g + `<path d="M${L} ${A.Y(3)}H${R}" stroke="${C4}" stroke-dasharray="4 3" opacity=".6"/>` + bars); },
    kpis: [{ label: '异常测点', value: 'P05, P10' }, { label: '原因', value: '噪声大 / 漂移' }],
    chain: ['12 个测点', 'outlier_detect', '通道间对比'],
  },
  bat_fade: {
    title: '循环容量衰减',
    chart: () => { const A = axes([0, 50], [2.1, 2.35], [0, 10, 20, 30, 40, 50], [2.1, 2.2, 2.3], '循环', '容量 (Ah)');
      const [xs, ys] = curve((c) => 2.31 - 0.0024 * c + 0.004 * Math.sin(c * 1.3), 0, 50, 50);
      return svg(A.g + dots(A, xs, ys, C1) + poly(A, [0, 50], [2.31, 2.19], C2, { dash: '6 4' }), leg([[C1, '实测'], [C2, '线性趋势', 'd']])); },
    kpis: [{ label: '容量衰减', value: '5.2', unit: '%', note: '2.310 → 2.190 Ah' }, { label: '内阻变化', value: '+14', unit: '%', note: '18.4 → 21.0 mΩ' }],
    chain: ['linear_regression 容量~循环', 'linear_regression 内阻~循环'],
  },
  bat_temp: {
    title: '温升检查',
    chart: () => { const A = axes([0, 50], [0, 12], [0, 10, 20, 30, 40, 50], [0, 4, 8, 12], '循环', '温升 (K)');
      const ys = range(0, 50).map((c) => ([17, 33, 41].includes(c) ? 9 + (c % 3) : 4 + 1.2 * Math.sin(c * 2.1) + 0.02 * c));
      return svg(A.g + ys.map((y, x) => `<circle cx="${A.X(x)}" cy="${A.Y(y)}" r="${y > 8 ? 4 : 2.6}" fill="${y > 8 ? C4 : C1}" opacity="${y > 8 ? 1 : 0.7}"/>`).join('')); },
    kpis: [{ label: '异常循环', value: '17, 33, 41' }, { label: '判据', value: '> 8', unit: 'K' }],
    chain: ['outlier_detect temp_rise_K'],
  },
  vib_peak: {
    title: '振动频谱',
    chart: () => { const A = axes([0, 400], [-70, 0], [0, 100, 200, 300, 400], [-60, -40, -20, 0], 'f (Hz)', 'dB');
      const pk = (f: number, c: number, h: number) => h * Math.exp(-(((f - c) / 2.5) ** 2));
      const [xs, ys] = curve((f) => -58 + noise(f) + pk(f, 98, 50) + pk(f, 196, 42) + pk(f, 294, 34) + pk(f, 50, 44) + pk(f, 150, 36), 0, 400, 800);
      return svg(A.g + poly(A, xs, ys, C1, { w: 1.4 }) + vmark(A, 98, C4, '主峰 98 Hz')); },
    kpis: [{ label: '主峰', value: '98', unit: 'Hz' }, { label: '谐波', value: '196 / 294', unit: 'Hz' }, { label: '工频干扰', value: '50 / 150', unit: 'Hz' }],
    chain: ['fft_frequency_analysis fs=2048 Hz', 'find_peaks'],
  },
  vib_notch: {
    title: '工频滤波',
    chart: () => { const A = axes([0, 200], [-70, 0], [0, 50, 100, 150, 200], [-60, -40, -20, 0], 'f (Hz)', 'dB');
      const pk = (f: number, c: number, h: number, w = 2.5) => h * Math.exp(-(((f - c) / w) ** 2));
      const base = (f: number) => -58 + noise(f) + pk(f, 98, 50) + pk(f, 196, 42);
      const [xs, ys] = curve((f) => base(f) + pk(f, 50, 44, 1.5) + pk(f, 150, 36, 1.5), 0, 200, 400);
      const [xs2, ys2] = curve(base, 0, 200, 400);
      return svg(A.g + poly(A, xs, ys, MU, { w: 1 }) + poly(A, xs2, ys2, C1, { w: 1.6 }), leg([[MU, '滤波前'], [C1, '滤波后']])); },
    kpis: [{ label: '50 Hz', value: '已滤除' }, { label: '150 Hz', value: '已滤除' }],
    chain: ['butterworth_filter 带阻 45–55 / 145–155 Hz', 'fft_frequency_analysis'],
  },
  doe_rank: {
    title: '设计参数敏感性',
    chart: () => { const names = ['aoa', 'thickness', 'camber', 'sweep'], v = [0.71, 0.24, 0.03, 0.02];
      return svg(names.map((n, i) => `<text x="${L + 40}" y="${T + 30 + i * 44}" text-anchor="end" font-size="12" fill="#363b42" font-family="IBM Plex Mono,monospace">${n}</text><rect x="${L + 50}" y="${T + 16 + i * 44}" width="${(v[i] / 0.71) * 360}" height="20" rx="2" fill="${C1}" opacity="${1 - i * 0.18}"/><text x="${L + 58 + (v[i] / 0.71) * 360}" y="${T + 31 + i * 44}" font-size="11" fill="#525861" font-family="IBM Plex Mono,monospace">${v[i].toFixed(2)}</text>`).join('')); },
    kpis: [{ label: '影响最大', value: 'aoa', note: '攻角' }, { label: '其次', value: 'thickness', note: '厚度' }, { label: '几乎无影响', value: 'sweep' }],
    chain: ['sensitivity 输出 drag'],
  },
  doe_fit: {
    title: '阻力 ~ 攻角',
    chart: () => { const A = axes([-2, 8], [0, 45], [-2, 0, 2, 4, 6, 8], [0, 15, 30, 45], 'aoa (°)', 'drag');
      const pts = range(0, 39).map((i) => { const a = -2 + (i / 39) * 10; return [a, 0.6 * a * a + 2.9 + 3 * (jitter(i) - 0.5)]; });
      const [xs, ys] = curve((a) => 0.6 * a * a + 2.9, -2, 8, 60);
      return svg(A.g + pts.map(([x, y]) => `<circle cx="${A.X(x)}" cy="${A.Y(y)}" r="2.6" fill="${C1}" opacity=".7"/>`).join('') + poly(A, xs, ys, C2, { w: 2 }), leg([[C1, '试验点'], [C2, '二次拟合']])); },
    kpis: [{ label: '拟合形式', value: '二次' }, { label: '主要项', value: '0.6·aoa²' }],
    chain: ['polynomial_regression degree=2'],
  },
};

/** Keep the config well-formed even if the server returns something partial. */
export function normalizeExamples(c: unknown): ExamplesConfig {
  const tabs = (c as ExamplesConfig | null)?.tabs;
  if (!Array.isArray(tabs) || tabs.length === 0) return DEFAULT_EXAMPLES;
  return { tabs: tabs.filter((t) => t && typeof t.name === 'string' && Array.isArray(t.questions)) };
}

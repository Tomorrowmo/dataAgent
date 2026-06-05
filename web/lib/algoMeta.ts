// Shared algorithm/param presentation metadata + coercion helpers.
// Extracted from AlgorithmsView so the flow canvas (FlowCanvas) and the
// library/template editors render parameters identically.

import type { Algorithm, ParamSpec } from '@/lib/api';

export const CAT_ZH: Record<string, string> = {
  filter: '滤波', preprocess: '预处理', reduce: '降维', regression: '回归/拟合',
  structure: '结构', custom: '自定义',
};
export const SOURCE_ZH: Record<string, string> = { builtin: '内置', ai: 'AI 生成', user: '自建' };
export const RETURNS_ZH: Record<string, string> = { dataframe: '数据表', series: '序列', dict: '字典', scalar: '标量', artifact: '产物' };

export const ALGO_ZH: Record<string, { name: string; desc: string; example?: string }> = {
  butterworth_filter: { name: '巴特沃斯滤波', desc: '零相位低通/高通滤波 —— 适合已知采样率的传感器数据。', example: '滤掉电压的高频噪声' },
  gaussian_filter: { name: '高斯滤波', desc: '一维高斯平滑(由 σ 控制),保留慢变特征、抑制快变噪声。', example: '把信号平滑一点' },
  median_filter: { name: '中值滤波', desc: '滑动中值滤波 —— 对会拉偏均值的离群尖峰更稳健。', example: '去掉温度里的尖峰毛刺' },
  moving_average: { name: '移动平均', desc: '为每个数值列加上宽度 N 的滑动均值列。', example: '给电压加个 5 点滑动平均' },
  savgol_filter: { name: 'Savitzky-Golay 平滑', desc: '多项式最小二乘平滑,比移动平均更好地保留峰形。', example: '平滑曲线但保留峰形' },
  data_prep: { name: '数据清洗', desc: '去重复行、去含缺失值的行,并重置索引。', example: '去掉重复行和有缺失的行' },
  fill_missing: { name: '缺失值填充', desc: '缺失值插补(线性/前向/后向/均值/中位数/常数)。', example: '用线性插值补上缺失值' },
  normalize: { name: '归一化 / 标准化', desc: '对选定数值列做 Min-Max、Z-score 或 Max-Abs 缩放。', example: '把各列归一化到 0–1' },
  outlier_detect: { name: '异常值检测', desc: '按列标记离群点:Tukey IQR、Z-score 或 Dixon Q 检验(小样本)。', example: '找出温度里的异常值' },
  pca: { name: '主成分分析 PCA', desc: '把数值列投影到 N 个主成分,可选核(RBF/多项式/sigmoid/cosine)。', example: '把这些列降到 2 维看看' },
  sensitivity: { name: '敏感性分析', desc: '按对输出的影响强弱给输入变量排序(相关 / Morris / 方差)。', example: '看哪个输入对温度影响最大' },
  interpolate: { name: '一维插值', desc: '按 x 重采样 y:线性 / 三次 / 二次 / 最近邻。', example: '按时间把电压重采样平滑' },
  correlation: { name: '相关性矩阵', desc: '数值列两两 Pearson / Spearman / Kendall 相关。', example: '看看哪些变量相关性强' },
};

// Friendly Chinese label + hint per parameter name.
export const PARAM_ZH: Record<string, { label: string; hint?: string }> = {
  columns: { label: '处理哪些列', hint: '不选 = 全部数值列' },
  cols: { label: '处理哪些列', hint: '不选 = 全部数值列' },
  inputs: { label: '输入变量(自变量)', hint: '勾选作为输入的列' },
  output: { label: '输出变量(因变量)', hint: '选一列作为输出' },
  target: { label: '目标列' },
  x: { label: 'x 轴 / 自变量列' },
  y: { label: 'y 轴 / 因变量列' },
  method: { label: '方法' },
  kernel: { label: '核函数', hint: '不选 = 线性 PCA' },
  window: { label: '窗口大小(点数)', hint: '滑动窗口包含的数据点数,如 5、11' },
  cutoff_hz: { label: '截止频率 (Hz)', hint: '保留低于此频率的信号;噪声多为高频,可先试采样率的 1/10' },
  fs_hz: { label: '采样率 (Hz)', hint: '每秒采样点数;有时间列时≈1/时间间隔' },
  kind: { label: '滤波类型', hint: 'lowpass=去高频噪声(最常用),highpass=去基线漂移' },
  n_components: { label: '主成分个数' },
  iqr_k: { label: 'IQR 倍数', hint: 'Tukey 围栏系数,越大越宽松' },
  z_threshold: { label: 'Z 阈值', hint: '|z| 超过该值判为异常' },
  sigma: { label: 'σ 平滑强度', hint: '越大越平滑' },
  order: { label: '阶数' },
  polyorder: { label: '多项式阶数' },
  cutoff: { label: '截止频率' },
  fs: { label: '采样率 (Hz)' },
  value: { label: '填充常数', hint: '仅当方法=constant 时使用' },
  drop_na: { label: '删除含缺失值的行' },
  drop_dup: { label: '删除重复行' },
};

export const COL_MULTI = new Set(['columns', 'cols', 'inputs', 'features']);
export const COL_SINGLE = new Set(['x', 'y', 'output', 'target', 'column', 'col']);

export function coerceParam(spec: ParamSpec, raw: string): unknown {
  const v = raw.trim();
  if (v === '') return undefined;
  if (spec.type === 'array') return v.split(',').map((s) => s.trim()).filter(Boolean);
  if (spec.type === 'integer') return parseInt(v, 10);
  if (spec.type === 'number') return Number(v);
  if (spec.type === 'boolean') return v === 'true' || v === '1';
  return v;
}

export function paramToStr(v: unknown): string {
  if (v === undefined || v === null) return '';
  if (Array.isArray(v)) return v.join(', ');
  return String(v);
}

export function paramsSummary(p?: Record<string, unknown>): string {
  if (!p) return '';
  return Object.entries(p).slice(0, 3).map(([k, v]) => `${k}=${Array.isArray(v) ? `[${v.join(',')}]` : String(v)}`).join('  ');
}

export type ParamKind = 'colmulti' | 'colsingle' | 'enum' | 'bool' | 'num' | 'text';

export function paramKind(name: string, spec: ParamSpec): ParamKind {
  const n = name.toLowerCase();
  if (spec.enum) return 'enum';
  if (spec.type === 'boolean') return 'bool';
  if (COL_MULTI.has(n) || spec.type === 'array') return 'colmulti';
  if (COL_SINGLE.has(n)) return 'colsingle';
  if (spec.type === 'number' || spec.type === 'integer') return 'num';
  return 'text';
}

export function paramLabel(name: string): string { return PARAM_ZH[name]?.label ?? name; }

export function paramHint(name: string, spec: ParamSpec): string {
  const base = PARAM_ZH[name]?.hint ?? spec.description ?? '';
  const d = spec.default;
  const def = d !== undefined && d !== null && !(Array.isArray(d) && d.length === 0) ? `默认 ${Array.isArray(d) ? d.join(',') : d}` : '';
  return [base, def].filter(Boolean).join(' · ');
}

export const dispName = (a: Algorithm) => ALGO_ZH[a.slug]?.name ?? a.name;
export const dispDesc = (a: Algorithm) => ALGO_ZH[a.slug]?.desc ?? a.description;
export const dispExample = (a: Algorithm) => {
  const ex = ALGO_ZH[a.slug]?.example;
  return ex ? `例:${ex}` : '用一句话描述你想要的结果,或留空用默认';
};
export const catZh = (c: string) => CAT_ZH[c] ?? c;

export function cellStr(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(4);
  const str = String(v);
  return str.length > 60 ? str.slice(0, 57) + '…' : str;
}

// ── Intent grouping (改法 A) + search (改法 B) + fallback (改法 D) ──────────────
// Re-group algorithms by "what the user wants to do" instead of by algorithm
// family. The grouping is a VIEW computed from category + a few per-slug
// overrides — NO backend change. Unknowns fall to '其他 · 待归类' so nothing is
// ever lost (still searchable). Shared by the library panel AND the flow-canvas
// algorithm palette so both read identically.
export const INTENT_ZH: Record<string, string> = {
  clean: '🧹 准备 · 清洗',
  smooth: '〰️ 平滑 · 去噪',
  feature: '🎯 找特征 · 找异常',
  map: '🔀 映射 · 重采样',
  fit: '📈 拟合 · 建模',
  reduce: '🧭 降维 · 看结构',
  structure: '🔧 结构操作',
  custom: '🛠️ 自建 · AI 生成',
  other: '🆕 其他 · 待归类',
};
export const INTENT_ORDER = ['clean', 'smooth', 'feature', 'map', 'fit', 'reduce', 'structure', 'custom', 'other'];

// Per-intent icon (the leading colored glyph on each algorithm row).
export const INTENT_ICON: Record<string, string> = {
  clean: '🧹', smooth: '〰️', feature: '🎯', map: '🔀', fit: '📈',
  reduce: '🧭', structure: '🔧', custom: '🛠️', other: '🆕',
};
export const intentIcon = (k: string) => INTENT_ICON[k] ?? INTENT_ICON.other;

// backend category → default intent
const CAT_INTENT: Record<string, string> = {
  filter: 'smooth', preprocess: 'clean', reduce: 'reduce',
  regression: 'fit', structure: 'structure', custom: 'custom',
};
// per-slug overrides where the family category misplaces the user's intent
const SLUG_INTENT: Record<string, string> = {
  outlier_detect: 'feature',          // preprocess, but it's "找异常"
  interpolate: 'map',                 // regression, but it's "重采样/映射"
  correlation: 'reduce',              // regression, but it's "看结构"
  find_peaks: 'feature',
  fft_frequency_analysis: 'feature',
};

export function algoIntent(a: Algorithm): string {
  if (a.source && a.source !== 'builtin') return 'custom';
  return SLUG_INTENT[a.slug] ?? CAT_INTENT[a.category] ?? 'other';
}
export const intentZh = (k: string) => INTENT_ZH[k] ?? INTENT_ZH.other;

// 改法 B — match a query across slug, names, description, example, category, intent.
export function matchAlgo(a: Algorithm, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const hay = [
    a.slug, a.name, a.category, catZh(a.category),
    ALGO_ZH[a.slug]?.name, ALGO_ZH[a.slug]?.desc, ALGO_ZH[a.slug]?.example,
    intentZh(algoIntent(a)),
  ].filter(Boolean).join(' ').toLowerCase();
  return hay.includes(q);
}

// 改法 A + D — group into intent buckets, canonical order, drop empty groups.
export function groupByIntent(algos: Algorithm[]): { key: string; label: string; items: Algorithm[] }[] {
  const buckets: Record<string, Algorithm[]> = {};
  for (const a of algos) (buckets[algoIntent(a)] ||= []).push(a);
  return INTENT_ORDER.filter((k) => buckets[k]?.length).map((k) => ({ key: k, label: intentZh(k), items: buckets[k] }));
}

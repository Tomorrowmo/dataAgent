// Recipe definitions — these are *scenarios*, not algorithms.
// Each recipe produces a context-aware Chinese/English prompt the chat agent
// can act on directly, using the user's real column names so they don't have
// to remember anything.

import type { Dataset } from './api';

export type RecipeId =
  | 'smooth' | 'drivers' | 'fit' | 'outliers' | 'corr' | 'pca' | 'custom';

export type Recipe = {
  id: RecipeId;
  emoji: string;
  titleKey: string;
  bodyKey: string;
};

export const RECIPES: Recipe[] = [
  { id: 'smooth',   emoji: '🌊', titleKey: 'recipe.smooth.t',   bodyKey: 'recipe.smooth.b' },
  { id: 'drivers',  emoji: '🎯', titleKey: 'recipe.drivers.t',  bodyKey: 'recipe.drivers.b' },
  { id: 'fit',      emoji: '📈', titleKey: 'recipe.fit.t',      bodyKey: 'recipe.fit.b' },
  { id: 'outliers', emoji: '🚨', titleKey: 'recipe.outliers.t', bodyKey: 'recipe.outliers.b' },
  { id: 'corr',     emoji: '📊', titleKey: 'recipe.corr.t',     bodyKey: 'recipe.corr.b' },
  { id: 'pca',      emoji: '🧭', titleKey: 'recipe.pca.t',      bodyKey: 'recipe.pca.b' },
  { id: 'custom',   emoji: '✨', titleKey: 'recipe.custom.t',   bodyKey: 'recipe.custom.b' },
];

// ── sample-data generators (each starter ships its OWN data) ────────────────
function _randn(): number {
  let u = 0, v = 0;
  while (u === 0) u = Math.random();
  while (v === 0) v = Math.random();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}
function _csv(headers: string[], rows: number[][]): string {
  const round = (x: number) => (Number.isFinite(x) ? +x.toFixed(4) : 0);
  return [headers.join(','), ...rows.map((r) => r.map(round).join(','))].join('\n');
}
function _doeCsv(): string {
  const rows: number[][] = [];
  for (let i = 0; i < 60; i++) {
    const thickness = 8 + Math.random() * 8, camber = Math.random() * 4, aoa = -2 + Math.random() * 10, sweep = Math.random() * 30;
    rows.push([thickness, camber, aoa, sweep,
      0.015 * thickness ** 2 + 0.6 * aoa ** 2 + 0.05 * camber + _randn() * 1.5,  // drag (thickness/aoa drive it; sweep is noise)
      1.3 * aoa + 0.9 * camber - 0.08 * thickness + _randn() * 0.5,              // lift
      2.2 * thickness + _randn() * 0.8]);                                         // mass
  }
  return _csv(['thickness', 'camber', 'aoa', 'sweep', 'drag', 'lift', 'mass'], rows);
}
function _scatterCsv(): string {
  const xs = Array.from({ length: 40 }, () => Math.random() * 10).sort((a, b) => a - b);
  return _csv(['x', 'y'], xs.map((x) => [x, Math.sin(x) + 0.15 * _randn()]));
}
function _signalCsv(): string {
  const n = 400; const sig: number[] = [];
  for (let i = 0; i < n; i++) { const t = (i * 20) / (n - 1); sig.push(2 * Math.sin(2 * Math.PI * 0.5 * t) + 0.5 * Math.sin(2 * Math.PI * 2 * t) + 0.25 * _randn()); }
  for (let k = 0; k < 5; k++) { const i = Math.floor(Math.random() * n); sig[i] += (Math.random() < 0.5 ? -1 : 1) * (4 + Math.random() * 3); }
  return _csv(['time_s', 'signal'], sig.map((s, i) => [(i * 20) / (n - 1), s]));
}
function _blobsCsv(): string {
  const centers = [[0, 0], [6, 6], [0, 7]]; const rows: number[][] = [];
  for (const [cx, cy] of centers) for (let k = 0; k < 40; k++) rows.push([cx + 0.6 * _randn(), cy + 0.6 * _randn(), _randn()]);
  return _csv(['f1', 'f2', 'f3'], rows);
}

/** One-click starters for the empty-state home: each is a plain-language
 *  question that SHIPS ITS OWN sample data. On click we ensure the dataset
 *  exists (create it from makeCsv the first time), then ask the question — so
 *  even a brand-new empty account can try it instantly, and the agent picks the
 *  specialized method (sensitivity / radial-basis / FFT / clustering) itself. */
export type Starter = {
  emoji: string;
  datasetName: string;           // exact name; created on demand if absent
  makeCsv: () => string;         // generates the sample CSV the first time
  zh: { t: string; q: string };
  en: { t: string; q: string };
};

export const STARTERS: Starter[] = [
  {
    emoji: '🎯', datasetName: '示例·参数优化DOE', makeCsv: _doeCsv,
    zh: { t: '哪个因素影响最大？', q: '这几个设计参数里，到底哪个对阻力 drag 影响最大、哪个其实没什么用？' },
    en: { t: 'What matters most?', q: 'Which of these design parameters most affects drag, and which barely matter?' },
  },
  {
    emoji: '〰️', datasetName: '示例·散点曲线', makeCsv: _scatterCsv,
    zh: { t: '把散点插成光滑曲线', q: '我这些点采样不太均匀，帮我插值成一条光滑的曲线。' },
    en: { t: 'Smooth scattered points', q: 'My points are unevenly sampled — interpolate them into one smooth curve.' },
  },
  {
    emoji: '📡', datasetName: '示例·周期信号', makeCsv: _signalCsv,
    zh: { t: '信号里有周期吗？', q: '这个信号里有没有周期性的成分？主要的频率大概是多少？' },
    en: { t: 'Any periodicity?', q: 'Does this signal have periodic components? What is the dominant frequency?' },
  },
  {
    emoji: '🧩', datasetName: '示例·分组数据', makeCsv: _blobsCsv,
    zh: { t: '帮我自动分组', q: '帮我把这些数据自动分成几组，看看有没有自然的分类。' },
    en: { t: 'Auto-group my data', q: 'Group these rows into a few natural clusters for me.' },
  },
];

function numericColumns(ds: Dataset): string[] {
  const cols = ds.schema.columns ?? [];
  return cols
    .filter((c) => /float|int|double|long|short|num/i.test(c.dtype))
    .map((c) => c.name);
}

export function buildPrompt(id: RecipeId, ds: Dataset | null, lang: 'en' | 'zh'): string {
  const nums = ds ? numericColumns(ds) : [];
  const first = nums[0] ?? (lang === 'zh' ? '第一个数值列' : 'the first numeric column');
  const last = nums[nums.length - 1] ?? first;
  const others = nums.slice(0, -1);

  // NOTE: these are deliberately ALGORITHM-FREE. The user describes intent in
  // plain language; the agent picks the method. That's the whole pitch — so a
  // sample question must never name an algorithm (no "Savitzky-Golay", "PCA"…).
  const en: Record<RecipeId, string> = {
    smooth:
      `"${first}" looks noisy / jittery. Smooth it for me, but keep the original shape and peaks — don't flatten them. Show me before-vs-after and tell me how strong the noise was.`,
    drivers:
      `In this data, which columns most affect "${last}", and which ones barely matter? Rank them and point out the 2 most important factors.`,
    fit:
      `Is there a pattern between "${last}" and "${nums[0] ?? 'another variable'}"? Fit a relationship so I could estimate one from the other, and tell me how good (or shaky) the fit is.`,
    outliers:
      `Are there any abnormal or suspicious points in this data (sensor glitches, recording errors)? Find them, and tell me how many per column and which rows they're in.`,
    corr:
      `Are these metrics related — when one goes up, does another tend to follow? Find the strongest relationships and tell me what they suggest.`,
    pca:
      `This data has too many columns to take in at once. Collapse it into 2-3 main dimensions and show me the overall structure — how the data clusters or spreads.`,
    custom: '',
  };

  const zh: Record<RecipeId, string> = {
    smooth:
      `"${first}" 这一列看起来有不少噪声毛刺，帮我平滑一下，但要尽量保留原本的波形和峰值，别抹平了。给我看看平滑前后的对比，顺便说说噪声大不大。`,
    drivers:
      `在这份数据里，到底哪几列对 "${last}" 影响最大、哪些其实没什么用？帮我排个序，并指出最关键的 2 个因素。`,
    fit:
      `"${last}" 和 "${nums[0] ?? '另一个变量'}" 之间有没有什么规律？能不能拟合出一条关系，让我可以用一个去估另一个？顺便告诉我拟合得准不准。`,
    outliers:
      `这份数据里有没有异常的、不正常的点（比如传感器跳变、记录出错）？帮我找出来，告诉我每列有几个可疑点、分别在哪几行。`,
    corr:
      `这些指标之间有没有关联？比如一个变大，另一个是不是也跟着变？帮我找出关系最强的几对，并说说这说明了什么。`,
    pca:
      `这份数据列太多了，看不过来。能不能帮我压缩到两三个主要维度，把整体结构展示出来，看看数据大致怎么分布、分成几类？`,
    custom: '',
  };

  return lang === 'zh' ? zh[id] : en[id];
}

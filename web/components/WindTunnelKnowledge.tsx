'use client';

/**
 * ⑤ 知识库管理 — 规则库 / 特征清单 / 自定义算子 / 天平载荷库
 *
 * This is where the product's central claim lives: a quality rule is DATA a
 * test engineer edits, not code a vendor ships. Three surfaces:
 *
 *   规则库    edit a threshold, add a rule by hand, or describe one in Chinese
 *             and let the model draft it — then PREVIEW it against real runs
 *             before it is allowed to affect a report.
 *   自定义算子 when no existing feature can measure what the user wants, the
 *             model writes an extractor, the sandbox proves it runs, and only
 *             then does it join the library.
 *   天平载荷库 the rated ranges the overload check needs and no run file carries.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle, Check, ChevronDown, ChevronRight, Code2, Download, Loader2,
  Pencil, Plus, RotateCcw, Save, Scale, Sparkles, Trash2, Upload, X,
} from 'lucide-react';
import {
  api, type WtBalance, type WtBand, type WtBatch, type WtExtractor,
  type WtFeature, type WtLevel, type WtRule, type WtRuleInput,
} from '@/lib/api';

const LEVEL_META: Record<WtLevel, { label: string; cls: string }> = {
  critical: { label: '严重·停止试验', cls: 'bg-red-100 text-red-700 ring-red-200' },
  warning: { label: '警告·需检查', cls: 'bg-amber-100 text-amber-700 ring-amber-200' },
  notice: { label: '注意·跟踪', cls: 'bg-sky-100 text-sky-700 ring-sky-200' },
  ok: { label: '正常', cls: 'bg-emerald-100 text-emerald-700 ring-emerald-200' },
};

export function LevelChip({ level, text }: { level: WtLevel; text?: string }) {
  const m = LEVEL_META[level] ?? LEVEL_META.ok;
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-medium ring-1 ${m.cls}`}>
      {text ?? m.label}
    </span>
  );
}

const emptyBand = (level: WtLevel): WtBand => ({
  level, lo: null, hi: null, verdict: '', action: '', cause: '', impact: '',
});

const blankRule = (): WtRuleInput => ({
  rule_id: '', name: '', feature: '', object: '', note: '',
  refs: [], enabled: true, source: 'user', applies_when_mach: '',
  bands: [emptyBand('warning'), { ...emptyBand('ok'), verdict: '正常' }],
});

function num(v: string): number | null {
  const t = v.trim();
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

// ══════════════════════════════════════════════════════════════════════════
//  规则编辑器
// ══════════════════════════════════════════════════════════════════════════
function RuleEditor({
  value, features, onChange, onCancel, onSave, onPreview, saving, previewing,
}: {
  value: WtRuleInput;
  features: WtFeature[];
  onChange: (r: WtRuleInput) => void;
  onCancel: () => void;
  onSave: () => void;
  onPreview: () => void;
  saving: boolean;
  previewing: boolean;
}) {
  const feat = features.find((f) => f.key === value.feature);
  const set = (patch: Partial<WtRuleInput>) => onChange({ ...value, ...patch });
  const setBand = (i: number, patch: Partial<WtBand>) =>
    set({ bands: value.bands.map((b, j) => (j === i ? { ...b, ...patch } : b)) });

  return (
    <div className="border border-brand-200 bg-brand-50/30 rounded-xl p-4 space-y-3">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <label className="text-xs text-ink-600">
          规则 ID（英文，唯一）
          <input value={value.rule_id} onChange={(e) => set({ rule_id: e.target.value })}
            placeholder="rule_custom_xxx"
            className="mt-1 w-full text-sm px-2 py-1.5 rounded-lg border border-ink-200 font-mono" />
        </label>
        <label className="text-xs text-ink-600">
          规则名称
          <input value={value.name} onChange={(e) => set({ name: e.target.value })}
            placeholder="例如：来流总压稳定性诊断"
            className="mt-1 w-full text-sm px-2 py-1.5 rounded-lg border border-ink-200" />
        </label>
        <label className="text-xs text-ink-600">
          绑定的监测特征
          <select value={value.feature} onChange={(e) => set({ feature: e.target.value })}
            className="mt-1 w-full text-sm px-2 py-1.5 rounded-lg border border-ink-200 bg-white">
            <option value="">— 请选择 —</option>
            {features.map((f) => (
              <option key={f.key} value={f.key}>
                {f.name}（{f.key}{f.unit ? ` · ${f.unit}` : ''}）
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-ink-600">
          适用马赫数条件（可空，如 &lt;2.9）
          <input value={value.applies_when_mach} onChange={(e) => set({ applies_when_mach: e.target.value })}
            placeholder="留空表示始终适用"
            className="mt-1 w-full text-sm px-2 py-1.5 rounded-lg border border-ink-200 font-mono" />
        </label>
        <label className="text-xs text-ink-600 md:col-span-2">
          监测对象
          <input value={value.object} onChange={(e) => set({ object: e.target.value })}
            className="mt-1 w-full text-sm px-2 py-1.5 rounded-lg border border-ink-200" />
        </label>
        <label className="text-xs text-ink-600 md:col-span-2">
          工程说明（为什么这样判）
          <textarea value={value.note} onChange={(e) => set({ note: e.target.value })} rows={2}
            className="mt-1 w-full text-sm px-2 py-1.5 rounded-lg border border-ink-200" />
        </label>
        <label className="text-xs text-ink-600 md:col-span-2">
          判据依据（每行一条：标准号 / 规则书 / 论文；没有就写「用户自定义工程约定，待评审」）
          <textarea value={value.refs.join('\n')} rows={2}
            onChange={(e) => set({ refs: e.target.value.split('\n').filter(Boolean) })}
            className="mt-1 w-full text-sm px-2 py-1.5 rounded-lg border border-ink-200" />
        </label>
      </div>

      {feat && (
        <div className="text-[11px] text-ink-500 bg-white rounded-lg px-3 py-2 border border-ink-100">
          <span className="font-medium text-ink-700">{feat.name}</span>
          {feat.unit && <span className="ml-2">单位 {feat.unit}</span>}
          {feat.requires.length > 0 && <span className="ml-2">依赖 {feat.requires.join('/')} 文件</span>}
          {feat.needs_prev_run && <span className="ml-2 text-amber-600">需要上一车次</span>}
          <div className="mt-1">{feat.description}</div>
          {feat.method && <div className="mt-1 font-mono text-[10px] text-ink-400">{feat.method}</div>}
        </div>
      )}

      <div>
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-xs font-medium text-ink-700">
            判定区间（半开区间 [下限, 上限)，从最严重往下排，命中即止）
          </span>
          <button onClick={() => set({ bands: [...value.bands, emptyBand('notice')] })}
            className="text-xs text-brand-600 hover:underline inline-flex items-center gap-1">
            <Plus className="w-3 h-3" /> 增加区间
          </button>
        </div>
        <div className="space-y-2">
          {value.bands.map((b, i) => (
            <div key={i} className="bg-white rounded-lg border border-ink-200 p-2.5 space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <select value={b.level} onChange={(e) => setBand(i, { level: e.target.value as WtLevel })}
                  className="text-xs px-2 py-1 rounded border border-ink-200 bg-white">
                  {(['critical', 'warning', 'notice', 'ok'] as WtLevel[]).map((l) => (
                    <option key={l} value={l}>{LEVEL_META[l].label}</option>
                  ))}
                </select>
                <span className="text-[11px] text-ink-500">下限≥</span>
                <input value={b.lo ?? ''} onChange={(e) => setBand(i, { lo: num(e.target.value) })}
                  placeholder="-∞" className="w-24 text-xs px-2 py-1 rounded border border-ink-200 font-mono" />
                <span className="text-[11px] text-ink-500">上限&lt;</span>
                <input value={b.hi ?? ''} onChange={(e) => setBand(i, { hi: num(e.target.value) })}
                  placeholder="+∞" className="w-24 text-xs px-2 py-1 rounded border border-ink-200 font-mono" />
                <button onClick={() => set({ bands: value.bands.filter((_, j) => j !== i) })}
                  className="ml-auto p-1 text-ink-400 hover:text-red-600"><Trash2 className="w-3.5 h-3.5" /></button>
              </div>
              <input value={b.verdict} onChange={(e) => setBand(i, { verdict: e.target.value })}
                placeholder="判定结论（报告里直接呈现的一句话）"
                className="w-full text-xs px-2 py-1 rounded border border-ink-200" />
              {b.level !== 'ok' && (
                <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                  <input value={b.cause} onChange={(e) => setBand(i, { cause: e.target.value })}
                    placeholder="原因分析" className="text-xs px-2 py-1 rounded border border-ink-200" />
                  <input value={b.impact} onChange={(e) => setBand(i, { impact: e.target.value })}
                    placeholder="影响评估" className="text-xs px-2 py-1 rounded border border-ink-200" />
                  <input value={b.action} onChange={(e) => setBand(i, { action: e.target.value })}
                    placeholder="处理建议" className="text-xs px-2 py-1 rounded border border-ink-200" />
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-2 pt-1">
        <button onClick={onSave} disabled={saving}
          className="px-3 py-1.5 rounded-lg bg-brand-600 text-white text-sm inline-flex items-center gap-1.5 disabled:opacity-50">
          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />} 保存规则
        </button>
        <button onClick={onPreview} disabled={previewing}
          className="px-3 py-1.5 rounded-lg border border-brand-300 text-brand-700 text-sm inline-flex items-center gap-1.5 disabled:opacity-50">
          {previewing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />} 先在真实车次上试跑
        </button>
        <button onClick={onCancel} className="px-3 py-1.5 rounded-lg text-ink-500 text-sm hover:bg-ink-100">取消</button>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
//  主组件
// ══════════════════════════════════════════════════════════════════════════
type Tab = 'rules' | 'features' | 'extractors' | 'balances';

export default function WindTunnelKnowledge({
  batches, llmOn, onRulesChanged,
}: {
  batches: WtBatch[];
  llmOn: boolean;
  onRulesChanged?: () => void;
}) {
  const [tab, setTab] = useState<Tab>('rules');
  const [rules, setRules] = useState<WtRule[]>([]);
  const [features, setFeatures] = useState<WtFeature[]>([]);
  const [extractors, setExtractors] = useState<WtExtractor[]>([]);
  const [balances, setBalances] = useState<WtBalance[]>([]);
  const [units, setUnits] = useState<string[]>([]);
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const [editing, setEditing] = useState<{ rowId?: number; draft: WtRuleInput } | null>(null);
  const [preview, setPreview] = useState<{ run_no: string; findings: { level: WtLevel; status: string; value: number | null; unit: string; verdict: string }[] }[] | null>(null);
  const [previewBatch, setPreviewBatch] = useState<number | null>(null);

  const [aiText, setAiText] = useState('');
  const [aiBusy, setAiBusy] = useState(false);
  const [aiNote, setAiNote] = useState('');
  const [genResult, setGenResult] = useState<{ code: string; name: string; slug: string; description: string; tests: unknown } | null>(null);

  const reload = useCallback(async () => {
    const [r, f, e, b] = await Promise.all([
      api.wtRules(), api.wtFeatures(), api.wtListExtractors(), api.wtBalances(),
    ]);
    setRules(r.rules);
    setFeatures(f.features);
    setExtractors(e.extractors);
    setBalances(b.balances);
    setUnits(b.units);
  }, []);

  useEffect(() => { reload().catch((e) => setMsg({ kind: 'err', text: String(e) })); }, [reload]);
  useEffect(() => { if (batches.length && previewBatch == null) setPreviewBatch(batches[0].id); }, [batches, previewBatch]);

  const flash = (kind: 'ok' | 'err', text: string) => {
    setMsg({ kind, text });
    setTimeout(() => setMsg(null), 6000);
  };

  // Custom extractors show up as bindable features too.
  const bindable = useMemo<WtFeature[]>(() => [
    ...features,
    ...extractors
      .filter((x) => !features.some((f) => f.key === x.feature_key))
      .map((x) => ({
        key: x.feature_key, name: x.name, unit: '', requires: [],
        needs_prev_run: false, description: x.description || '自定义特征算子',
        method: '沙箱内执行的自定义特征算子',
      })),
  ], [features, extractors]);

  async function saveRule() {
    if (!editing) return;
    setBusy('save');
    try {
      if (editing.rowId) await api.wtUpdateRule(editing.rowId, editing.draft);
      else await api.wtCreateRule(editing.draft);
      setEditing(null);
      setPreview(null);
      await reload();
      onRulesChanged?.();
      flash('ok', '规则已保存，下次执行检查即刻生效。');
    } catch (e) { flash('err', String(e)); } finally { setBusy(''); }
  }

  async function previewRule() {
    if (!editing || previewBatch == null) { flash('err', '请先在上方选择一个用于试跑的批次'); return; }
    setBusy('preview');
    try {
      const r = await api.wtPreviewRule(editing.draft, previewBatch);
      setPreview(r.preview.map((p) => ({
        run_no: p.run_no,
        findings: p.findings.map((f) => ({
          level: f.level, status: f.status, value: f.value, unit: f.unit, verdict: f.verdict,
        })),
      })));
    } catch (e) { flash('err', String(e)); } finally { setBusy(''); }
  }

  async function aiDraft() {
    if (!aiText.trim()) return;
    setAiBusy(true); setAiNote(''); setGenResult(null);
    try {
      const t = await api.wtTriage(aiText);
      if (t.ok && t.matched === false) {
        setAiNote(`现有特征无法测量这个需求 —— ${t.why ?? ''}\n建议新增测量量：${t.new_feature_brief ?? ''}\n下面可以直接让 AI 写一个特征算子。`);
      }
      const d = await api.wtDraftRule(aiText);
      if (d.ok && d.rule) {
        setEditing({ draft: { ...(d.rule as WtRuleInput), source: 'ai' } });
        setAiNote((prev) => [prev, d.reasoning ? `AI 选择理由：${d.reasoning}` : '',
          d.threshold_source ? `阈值来源：${d.threshold_source}` : ''].filter(Boolean).join('\n'));
        setTab('rules');
      } else {
        setAiNote((prev) => [prev, d.error ?? '', d.needs_new_feature ? `需要新增测量量：${d.needs_new_feature}` : '']
          .filter(Boolean).join('\n'));
      }
    } catch (e) { flash('err', String(e)); } finally { setAiBusy(false); }
  }

  async function aiGenExtractor() {
    if (!aiText.trim()) return;
    setAiBusy(true); setAiNote('正在生成算法并在沙箱中验证…'); setGenResult(null);
    try {
      const r = await api.wtGenExtractor(aiText, previewBatch ?? undefined);
      if (r.ok && r.code && r.meta?.slug) {
        setGenResult({
          code: r.code, name: r.meta.name ?? r.meta.slug, slug: r.meta.slug,
          description: r.meta.description ?? '', tests: r.tests,
        });
        setAiNote(`沙箱测试通过（共尝试 ${r.attempts ?? 1} 次）。确认无误后点「入库」，随后即可被规则引用为 ${r.feature_key}。`);
      } else {
        setAiNote(`生成失败：${r.error ?? '未知错误'}`);
      }
    } catch (e) { flash('err', String(e)); } finally { setAiBusy(false); }
  }

  async function saveExtractor() {
    if (!genResult) return;
    setBusy('ext');
    try {
      const r = await api.wtSaveExtractor({
        code: genResult.code, name: genResult.name, slug: genResult.slug,
        description: genResult.description, test_report: { tests: genResult.tests },
      });
      setGenResult(null);
      await reload();
      flash('ok', `算子已入库，可用特征键 ${r.feature_key}。现在去规则库新建一条规则来绑定它。`);
      setTab('extractors');
    } catch (e) { flash('err', String(e)); } finally { setBusy(''); }
  }

  const TABS: { id: Tab; label: string; icon: React.ReactNode }[] = [
    { id: 'rules', label: `规则库 (${rules.length})`, icon: <Scale className="w-4 h-4" /> },
    { id: 'features', label: `监测特征 (${features.length})`, icon: <ChevronRight className="w-4 h-4" /> },
    { id: 'extractors', label: `自定义算子 (${extractors.length})`, icon: <Code2 className="w-4 h-4" /> },
    { id: 'balances', label: `天平载荷库 (${balances.length})`, icon: <Scale className="w-4 h-4" /> },
  ];

  return (
    <div className="space-y-4">
      {msg && (
        <div className={`text-sm px-3 py-2 rounded-lg ${msg.kind === 'ok'
          ? 'bg-emerald-50 text-emerald-800 ring-1 ring-emerald-200'
          : 'bg-red-50 text-red-800 ring-1 ring-red-200'}`}>{msg.text}</div>
      )}

      {/* AI 面板 —— 两条扩展路径都从这里进 */}
      <div className="rounded-xl border border-brand-200 bg-gradient-to-br from-brand-50/60 to-white p-4">
        <div className="flex items-center gap-2 mb-2">
          <Sparkles className="w-4 h-4 text-brand-600" />
          <span className="text-sm font-medium text-ink-800">用一句话新增检查能力</span>
          {!llmOn && <span className="text-[11px] text-amber-700 bg-amber-50 px-1.5 py-0.5 rounded">未配置大模型，AI 功能不可用</span>}
        </div>
        <p className="text-[11px] text-ink-500 mb-2 leading-relaxed">
          先由 AI 分诊：现有特征能测就直接起草规则；测不了就让 AI 写一个特征算子，
          沙箱验证通过、你确认后才入库。<span className="text-ink-700">任何 AI 产物都要先在真实车次上试跑，你点头才生效。</span>
        </p>
        <textarea value={aiText} onChange={(e) => setAiText(e.target.value)} rows={2}
          placeholder="例如：吹风段来流总压的波动系数超过 1% 就告警；又例如：天平回零量超过 0.008 必须停机检查"
          className="w-full text-sm px-3 py-2 rounded-lg border border-ink-200" />
        <div className="flex flex-wrap items-center gap-2 mt-2">
          <button onClick={aiDraft} disabled={!llmOn || aiBusy || !aiText.trim()}
            className="px-3 py-1.5 rounded-lg bg-brand-600 text-white text-sm inline-flex items-center gap-1.5 disabled:opacity-50">
            {aiBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />} 起草规则
          </button>
          <button onClick={aiGenExtractor} disabled={!llmOn || aiBusy || !aiText.trim()}
            className="px-3 py-1.5 rounded-lg border border-brand-300 text-brand-700 text-sm inline-flex items-center gap-1.5 disabled:opacity-50">
            <Code2 className="w-4 h-4" /> 生成特征算子
          </button>
          <select value={previewBatch ?? ''} onChange={(e) => setPreviewBatch(Number(e.target.value) || null)}
            className="text-xs px-2 py-1.5 rounded-lg border border-ink-200 bg-white">
            <option value="">试跑批次…</option>
            {batches.map((b) => <option key={b.id} value={b.id}>{b.name || `批次 ${b.id}`}</option>)}
          </select>
        </div>
        {aiNote && <pre className="mt-2 text-[11px] text-ink-600 whitespace-pre-wrap bg-white rounded-lg p-2 border border-ink-100">{aiNote}</pre>}
        {genResult && (
          <div className="mt-2 bg-white rounded-lg border border-ink-200 p-3">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-sm font-medium">{genResult.name}</span>
              <code className="text-[11px] text-ink-500">custom:{genResult.slug}</code>
              <span className="text-[11px] text-emerald-700 bg-emerald-50 px-1.5 py-0.5 rounded ring-1 ring-emerald-200">沙箱测试通过</span>
              <button onClick={saveExtractor} disabled={busy === 'ext'}
                className="ml-auto px-2.5 py-1 rounded-lg bg-emerald-600 text-white text-xs inline-flex items-center gap-1 disabled:opacity-50">
                {busy === 'ext' ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />} 入库
              </button>
            </div>
            <pre className="text-[11px] font-mono bg-ink-50 rounded p-2 overflow-x-auto max-h-72">{genResult.code}</pre>
          </div>
        )}
      </div>

      <div className="flex flex-wrap gap-1 border-b border-ink-200">
        {TABS.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`px-3 py-2 text-sm inline-flex items-center gap-1.5 border-b-2 -mb-px ${tab === t.id
              ? 'border-brand-600 text-brand-700 font-medium' : 'border-transparent text-ink-500 hover:text-ink-700'}`}>
            {t.icon}{t.label}
          </button>
        ))}
      </div>

      {/* ── 规则库 ── */}
      {tab === 'rules' && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <button onClick={() => { setEditing({ draft: blankRule() }); setPreview(null); }}
              className="px-3 py-1.5 rounded-lg bg-brand-600 text-white text-sm inline-flex items-center gap-1.5">
              <Plus className="w-4 h-4" /> 手工新增规则
            </button>
            <button onClick={async () => {
              if (!confirm('恢复全部内置规则的默认阈值？你自己新增的规则不受影响。')) return;
              await api.wtRestoreDefaultRules(); await reload(); onRulesChanged?.();
              flash('ok', '内置规则已恢复默认。');
            }} className="px-3 py-1.5 rounded-lg border border-ink-200 text-ink-600 text-sm inline-flex items-center gap-1.5">
              <RotateCcw className="w-4 h-4" /> 恢复内置默认
            </button>
          </div>

          {editing && (
            <>
              <RuleEditor value={editing.draft} features={bindable}
                onChange={(d) => setEditing({ ...editing, draft: d })}
                onCancel={() => { setEditing(null); setPreview(null); }}
                onSave={saveRule} onPreview={previewRule}
                saving={busy === 'save'} previewing={busy === 'preview'} />
              {preview && (
                <div className="rounded-xl border border-ink-200 bg-white p-3">
                  <div className="text-xs font-medium text-ink-700 mb-2">
                    试跑结果（尚未保存，仅预览这条规则会怎么判）
                  </div>
                  <table className="w-full text-xs">
                    <thead className="text-ink-500">
                      <tr><th className="text-left py-1">车次</th><th className="text-left">实测值</th>
                        <th className="text-left">判定</th><th className="text-left">等级</th></tr>
                    </thead>
                    <tbody>
                      {preview.map((p) => p.findings.map((f, i) => (
                        <tr key={`${p.run_no}-${i}`} className="border-t border-ink-100">
                          <td className="py-1 font-mono">{p.run_no}</td>
                          <td>{f.value == null ? '—' : `${f.value.toPrecision(6)} ${f.unit}`}</td>
                          <td className="text-ink-700">{f.verdict}</td>
                          <td>{f.status === 'evaluated'
                            ? <LevelChip level={f.level} />
                            : <span className="text-[11px] text-ink-400">未评定</span>}</td>
                        </tr>
                      )))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}

          <div className="space-y-1.5">
            {rules.map((r) => {
              const open = expanded === r.rule_id;
              return (
                <div key={r.rule_id} className="rounded-lg border border-ink-200 bg-white">
                  <div className="flex items-center gap-2 px-3 py-2">
                    <button onClick={() => setExpanded(open ? null : r.rule_id)} className="text-ink-400">
                      {open ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                    </button>
                    <input type="checkbox" checked={r.enabled} title="启用/停用"
                      onChange={async () => {
                        await api.wtUpdateRule(r.id!, { ...(r as WtRuleInput), enabled: !r.enabled });
                        await reload(); onRulesChanged?.();
                      }} className="accent-brand-600" />
                    <span className="text-sm text-ink-800">{r.name}</span>
                    <code className="text-[10px] text-ink-400">{r.feature}</code>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded ${r.source === 'builtin'
                      ? 'bg-ink-100 text-ink-600' : r.source === 'ai'
                        ? 'bg-violet-100 text-violet-700' : 'bg-sky-100 text-sky-700'}`}>
                      {r.source === 'builtin' ? '内置' : r.source === 'ai' ? 'AI' : '自定义'}
                    </span>
                    <div className="ml-auto flex items-center gap-1">
                      <button onClick={() => { setEditing({ rowId: r.id, draft: r as WtRuleInput }); setPreview(null); }}
                        className="p-1 text-ink-400 hover:text-brand-600"><Pencil className="w-3.5 h-3.5" /></button>
                      <button onClick={async () => {
                        if (!confirm(`删除规则「${r.name}」？`)) return;
                        await api.wtDeleteRule(r.id!); await reload(); onRulesChanged?.();
                      }} className="p-1 text-ink-400 hover:text-red-600"><Trash2 className="w-3.5 h-3.5" /></button>
                    </div>
                  </div>
                  {open && (
                    <div className="px-3 pb-3 pt-1 border-t border-ink-100 text-xs space-y-2">
                      {r.object && <div><span className="text-ink-500">监测对象：</span>{r.object}</div>}
                      {r.applies_when_mach && <div><span className="text-ink-500">适用条件：</span>马赫数 {r.applies_when_mach}</div>}
                      {r.note && <div className="text-ink-600 leading-relaxed">{r.note}</div>}
                      <table className="w-full">
                        <thead className="text-ink-500">
                          <tr><th className="text-left py-1">区间</th><th className="text-left">等级</th>
                            <th className="text-left">判定结论</th><th className="text-left">处理建议</th></tr>
                        </thead>
                        <tbody>
                          {r.bands.map((b, i) => (
                            <tr key={i} className="border-t border-ink-100">
                              <td className="py-1 font-mono text-[11px]">
                                [{b.lo ?? '-∞'}, {b.hi ?? '+∞'})
                              </td>
                              <td><LevelChip level={b.level} /></td>
                              <td className="text-ink-700">{b.verdict}</td>
                              <td className="text-ink-500">{b.action || '—'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {r.refs.length > 0 && (
                        <div className="text-[11px] text-ink-500">
                          <div className="font-medium text-ink-600 mb-0.5">判据依据</div>
                          <ul className="list-disc pl-4 space-y-0.5">
                            {r.refs.map((x, i) => <li key={i}>{x}</li>)}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── 监测特征 ── */}
      {tab === 'features' && (
        <div className="overflow-x-auto">
          <p className="text-xs text-ink-500 mb-2">
            特征只负责「测量」，规则只负责「判定」。二者显式绑定，因此一个读数不可能被错误的规则诊断。
          </p>
          <table className="w-full text-xs">
            <thead className="text-ink-500 border-b border-ink-200">
              <tr><th className="text-left py-1.5">特征键</th><th className="text-left">名称</th>
                <th className="text-left">单位</th><th className="text-left">依赖</th>
                <th className="text-left">说明 / 计算方法</th></tr>
            </thead>
            <tbody>
              {features.map((f) => (
                <tr key={f.key} className="border-b border-ink-100 align-top">
                  <td className="py-1.5 font-mono text-[11px] text-brand-700">{f.key}</td>
                  <td className="text-ink-800">{f.name}</td>
                  <td className="text-ink-500">{f.unit || '—'}</td>
                  <td className="text-ink-500">
                    {f.requires.join('/') || '—'}{f.needs_prev_run && <span className="text-amber-600"> +上一车次</span>}
                  </td>
                  <td className="text-ink-600">
                    {f.description}
                    {f.method && <div className="font-mono text-[10px] text-ink-400 mt-0.5">{f.method}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ── 自定义算子 ── */}
      {tab === 'extractors' && (
        <div className="space-y-2">
          {extractors.length === 0 && (
            <div className="text-sm text-ink-500 py-8 text-center">
              还没有自定义算子。在上方用一句话描述你想测量的量，让 AI 生成并通过沙箱验证。
            </div>
          )}
          {extractors.map((x) => (
            <details key={x.id} className="rounded-lg border border-ink-200 bg-white">
              <summary className="px-3 py-2 cursor-pointer text-sm flex items-center gap-2">
                <Code2 className="w-4 h-4 text-ink-400" />
                {x.name}
                <code className="text-[11px] text-ink-400">{x.feature_key}</code>
                {x.verified && <span className="text-[10px] text-emerald-700 bg-emerald-50 px-1.5 py-0.5 rounded">已验证</span>}
                <span className="text-[10px] text-ink-400 ml-auto">v{x.version}</span>
              </summary>
              <div className="px-3 pb-3 text-xs">
                <div className="text-ink-600 mb-2">{x.description}</div>
                <pre className="font-mono text-[11px] bg-ink-50 rounded p-2 overflow-x-auto max-h-96">{x.code}</pre>
              </div>
            </details>
          ))}
        </div>
      )}

      {/* ── 天平载荷库 ── */}
      {tab === 'balances' && (
        <BalanceLibrary units={units} balances={balances} onChanged={async () => { await reload(); }} flash={flash} />
      )}
    </div>
  );
}

function BalanceLibrary({
  units, balances, onChanged, flash,
}: {
  units: string[];
  balances: WtBalance[];
  onChanged: () => Promise<void>;
  flash: (k: 'ok' | 'err', t: string) => void;
}) {
  const [name, setName] = useState('');
  const [vals, setVals] = useState<Record<string, string>>({});
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const u = units.length ? units : ['My', 'Z', 'Mz', 'Y', 'Mx', 'Q'];

  async function add() {
    const ranges: Record<string, number> = {};
    for (const k of u) {
      const n = Number(vals[k]);
      if (!Number.isFinite(n) || n <= 0) { flash('err', `单元 ${k} 的量程必须是正数`); return; }
      ranges[k] = n;
    }
    if (!name.trim()) { flash('err', '天平名称不能为空'); return; }
    setBusy(true);
    try {
      await api.wtAddBalance({ name: name.trim(), ranges, note });
      setName(''); setVals({}); setNote('');
      await onChanged();
      flash('ok', '已保存。原本因缺量程而「未评定」的超量程检查，重跑后即可给出结论。');
    } catch (e) { flash('err', String(e)); } finally { setBusy(false); }
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-ink-500 leading-relaxed">
        天平额定量程不在任何一个车次文件里，只能来自风洞的天平载荷库。库中查不到该天平时，
        系统会如实报「未评定」并指出要补什么 —— 不会用猜测的量程给出结论。
      </p>

      <div className="rounded-xl border border-ink-200 bg-white p-3">
        <div className="text-xs font-medium text-ink-700 mb-2">新增 / 更新条目</div>
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-[11px] text-ink-500">
            天平名称
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="N628E"
              className="mt-0.5 block w-32 text-sm px-2 py-1 rounded border border-ink-200 font-mono" />
          </label>
          {u.map((k) => (
            <label key={k} className="text-[11px] text-ink-500">
              {k}
              <input value={vals[k] ?? ''} onChange={(e) => setVals({ ...vals, [k]: e.target.value })}
                className="mt-0.5 block w-20 text-sm px-2 py-1 rounded border border-ink-200 font-mono" />
            </label>
          ))}
          <label className="text-[11px] text-ink-500 flex-1 min-w-40">
            备注
            <input value={note} onChange={(e) => setNote(e.target.value)}
              className="mt-0.5 block w-full text-sm px-2 py-1 rounded border border-ink-200" />
          </label>
          <button onClick={add} disabled={busy}
            className="px-3 py-1.5 rounded-lg bg-brand-600 text-white text-sm inline-flex items-center gap-1.5 disabled:opacity-50">
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />} 保存
          </button>
          <button onClick={() => fileRef.current?.click()}
            className="px-3 py-1.5 rounded-lg border border-ink-200 text-ink-600 text-sm inline-flex items-center gap-1.5">
            <Upload className="w-4 h-4" /> 导入载荷库文件
          </button>
          <input ref={fileRef} type="file" className="hidden" onChange={async (e) => {
            const f = e.target.files?.[0]; if (!f) return;
            try {
              const r = await api.wtImportBalances(f);
              await onChanged();
              flash('ok', `导入完成：新增 ${r.added} 条，更新 ${r.updated} 条。`);
            } catch (err) { flash('err', String(err)); }
            e.target.value = '';
          }} />
        </div>
        <div className="text-[11px] text-ink-400 mt-1.5">
          导入文件格式：每行 <code className="font-mono">名称 My Z Mz Y Mx Q</code>，
          支持 <code className="font-mono">#</code> 注释，UTF-8 或 GBK 均可。
        </div>
      </div>

      <table className="w-full text-xs">
        <thead className="text-ink-500 border-b border-ink-200">
          <tr>
            <th className="text-left py-1.5">天平</th>
            {u.map((k) => <th key={k} className="text-left">{k}</th>)}
            <th className="text-left">备注</th><th></th>
          </tr>
        </thead>
        <tbody>
          {balances.map((b) => (
            <tr key={b.id} className="border-b border-ink-100">
              <td className="py-1.5 font-mono text-ink-800">{b.name}</td>
              {u.map((k) => <td key={k} className="font-mono text-ink-600">{b.ranges[k] ?? '—'}</td>)}
              <td className="text-ink-500">{b.note}</td>
              <td className="text-right">
                <button onClick={async () => {
                  if (!confirm(`删除天平「${b.name}」？`)) return;
                  await api.wtDeleteBalance(b.id); await onChanged();
                }} className="p-1 text-ink-400 hover:text-red-600"><Trash2 className="w-3.5 h-3.5" /></button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

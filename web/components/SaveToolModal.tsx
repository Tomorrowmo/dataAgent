'use client';

import { useEffect, useMemo, useState } from 'react';
import { Loader2, Save, X, Sparkles, AlertTriangle } from 'lucide-react';
import { api, type Algorithm, type ParamSpec } from '@/lib/api';
import { coerceParam, paramToStr, CAT_ZH } from '@/lib/algoMeta';

/**
 * Save-to-library dialog for an AI-generated tool. Lets the user confirm/edit the
 * tool NAME + DESCRIPTION and curate WHICH params are exposed (with labels +
 * defaults) — all AI-pre-filled, all editable — so the saved tool is general and
 * reusable. Also surfaces similar existing tools to discourage near-duplicates.
 */
type ParamRow = { key: string; spec: ParamSpec; include: boolean; label: string; defaultStr: string; isNew?: boolean };

export default function SaveToolModal({ slug, meta, onSaved, onReused, onCancel, onConfirm, showReuse = true, hint }: {
  slug: string;
  meta: Record<string, unknown>;
  onSaved: (name: string) => void;
  onReused: (existingName: string) => void;
  onCancel: () => void;
  // When provided, save() calls this with the curated edits INSTEAD of the
  // AI-draft confirmGeneratedTool path — lets the upload flow reuse this dialog
  // to save via /algorithms/save. The callback persists and resolves on success.
  onConfirm?: (edits: { name: string; description: string; category: string; params_schema: Record<string, ParamSpec> }) => Promise<void>;
  // Show the "reuse an existing similar tool" block (only meaningful for the
  // AI-draft flow, which can discard the draft). Off for direct uploads.
  showReuse?: boolean;
  hint?: string;
}) {
  const initName = String(meta.name ?? slug);
  const initDesc = String(meta.description ?? '');
  const initCat = String(meta.category ?? 'custom');
  const schema = (meta.params_schema as Record<string, ParamSpec>) || {};

  const [name, setName] = useState(initName);
  const [description, setDescription] = useState(initDesc);
  const [category, setCategory] = useState(initCat);
  const [params, setParams] = useState<ParamRow[]>(() =>
    Object.entries(schema).map(([key, spec]) => ({
      key, spec, include: true,
      label: String(spec.description ?? ''),
      defaultStr: paramToStr(spec.default),
    })),
  );
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [existing, setExisting] = useState<Algorithm[]>([]);
  // "Let AI rewrite this tool" — adds/changes a real parameter via codegen.
  const [refineIntent, setRefineIntent] = useState('');
  const [refining, setRefining] = useState(false);
  const [refineMsg, setRefineMsg] = useState('');

  useEffect(() => { api.listAlgorithms().then(setExisting).catch(() => {}); }, []);

  // Similar existing tools (same category, or name-token overlap) → discourage dupes.
  const similar = useMemo(() => {
    const toks = new Set(name.toLowerCase().split(/[^a-z0-9一-鿿]+/).filter((t) => t.length > 1));
    return existing
      .filter((a) => a.slug !== slug && (a.source === 'ai' || a.source === 'user'))
      .filter((a) => a.category === category ||
        a.name.toLowerCase().split(/[^a-z0-9一-鿿]+/).some((t) => t.length > 1 && toks.has(t)))
      .slice(0, 4);
  }, [existing, name, category, slug]);

  function setRow(i: number, patch: Partial<ParamRow>) {
    setParams((arr) => arr.map((r, idx) => idx === i ? { ...r, ...patch } : r));
  }
  function addParam() {
    setParams((arr) => [...arr, { key: '', spec: { type: 'string' } as ParamSpec, include: true, label: '', defaultStr: '', isNew: true }]);
  }
  function removeRow(i: number) {
    setParams((arr) => arr.filter((_, idx) => idx !== i));
  }

  // Known categories: built-ins + any already used by existing tools, so the
  // user picks from what exists (and can still type a brand-new one).
  const categories = useMemo(() => {
    const builtin = ['filter', 'preprocess', 'reduce', 'regression', 'structure', 'custom'];
    return Array.from(new Set([...builtin, ...existing.map((a) => a.category).filter(Boolean)]));
  }, [existing]);

  // Reuse an existing similar tool instead of saving a near-duplicate: discard
  // this draft and tell the user to use the existing one.
  async function reuse(a: Algorithm) {
    setBusy(true); setErr('');
    try { await api.confirmGeneratedTool(slug, false); onReused(a.name); }
    catch (e) { setErr((e as Error).message); setBusy(false); }
  }

  async function save() {
    if (!name.trim()) { setErr('请填写工具名称'); return; }
    setBusy(true); setErr('');
    const params_schema: Record<string, ParamSpec> = {};
    for (const r of params) {
      if (!r.include) continue;
      const key = r.key.trim();
      if (!key) continue;  // skip a half-added blank param row
      const def = coerceParam(r.spec, r.defaultStr);
      params_schema[key] = { ...r.spec, description: r.label || r.spec.description, default: def as ParamSpec['default'] };
    }
    try {
      if (onConfirm) {
        await onConfirm({ name: name.trim(), description: description.trim(), category: category.trim(), params_schema });
      } else {
        await api.confirmGeneratedTool(slug, true, { name: name.trim(), description: description.trim(), category: category.trim(), params_schema });
      }
      onSaved(name.trim());
    } catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  }

  // Ask AI to rewrite the underlying algorithm so a NEW capability/parameter is
  // real (declared AND used). On success the server updated the draft's code +
  // params; we refresh the form fields from the returned meta.
  async function refine() {
    const ins = refineIntent.trim();
    if (!ins || refining) return;
    setRefining(true); setRefineMsg(''); setErr('');
    try {
      const r = await api.refineTool(slug, ins);
      if (!r.all_tests_passed) {
        setRefineMsg('AI 改写没通过自测,已保留原版 —— 换个说法再试试。');
        return;
      }
      const m = (r.meta || {}) as Record<string, unknown>;
      if (m.name) setName(String(m.name));
      if (m.description) setDescription(String(m.description));
      if (m.category) setCategory(String(m.category));
      const ns = (m.params_schema as Record<string, ParamSpec>) || {};
      setParams(Object.entries(ns).map(([key, spec]) => ({
        key, spec, include: true, label: String(spec.description ?? ''), defaultStr: paramToStr(spec.default),
      })));
      setRefineMsg('✓ 已按你的要求重写,下面的参数已更新 —— 确认后保存即可。');
      setRefineIntent('');
    } catch (e) { setRefineMsg('改写失败:' + (e as Error).message); }
    finally { setRefining(false); }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/30 grid place-items-center p-4" onClick={onCancel}>
      <div className="w-[540px] max-w-full bg-white rounded-xl ring-1 ring-ink-200 shadow-xl flex flex-col max-h-[88vh]" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 px-4 py-3 border-b border-ink-200">
          <Save className="w-4 h-4 text-brand-600" />
          <div className="font-semibold text-sm flex-1">保存到工具库</div>
          <button onClick={onCancel} className="text-ink-400 hover:text-ink-700"><X className="w-4 h-4" /></button>
        </div>

        <div className="px-4 py-3 space-y-3 overflow-y-auto scroll-hide">
          <div className="text-[11px] text-ink-500 flex items-center gap-1.5"><Sparkles className="w-3.5 h-3.5 text-violet-500" /> {hint ?? '名称、说明、参数已由 AI 预填,确认或修改后保存 —— 这样它就是个通用工具,以后任何数据都能复用。'}</div>

          {showReuse && similar.length > 0 && (
            <div className="text-[11px] text-amber-700 bg-amber-50 ring-1 ring-amber-200 rounded-lg px-2.5 py-2">
              <div className="flex items-center gap-1.5 font-medium mb-1.5"><AlertTriangle className="w-3.5 h-3.5" /> 库里已有类似工具——复用更省事、也避免同质化。你可以<b>改用其中一个</b>(丢弃这个新工具),或仍然新建:</div>
              <div className="flex flex-wrap gap-1.5">
                {similar.map((a) => (
                  <button key={a.slug + (a.id ?? '')} onClick={() => reuse(a)} disabled={busy}
                    title="改用这个已有工具,丢弃刚生成的新工具"
                    className="px-2 py-0.5 rounded-md bg-white ring-1 ring-amber-300 text-amber-800 hover:bg-amber-100 disabled:opacity-50">
                    改用「{a.name}」
                  </button>
                ))}
              </div>
            </div>
          )}

          <div>
            <label className="block text-[11px] font-medium text-ink-600 mb-1">工具名称 *</label>
            <input value={name} onChange={(e) => setName(e.target.value)} className="w-full border border-ink-200 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:border-brand-400" />
          </div>
          <div>
            <label className="block text-[11px] font-medium text-ink-600 mb-1">工具说明</label>
            <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} placeholder="一句话说明这个工具做什么、什么时候用"
              className="w-full border border-ink-200 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:border-brand-400 resize-none" />
          </div>
          <div>
            <label className="block text-[11px] font-medium text-ink-600 mb-1">分类</label>
            <input value={category} onChange={(e) => setCategory(e.target.value)} list="savetool-cats" placeholder="选一个已有分类,或输入新分类"
              className="w-64 border border-ink-200 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:border-brand-400" />
            <datalist id="savetool-cats">
              {categories.map((c) => <option key={c} value={c}>{CAT_ZH[c] ?? c}</option>)}
            </datalist>
            <div className="text-[10.5px] text-ink-400 mt-1">下拉里是已有分类(可选),也可以直接输入一个新分类。</div>
          </div>

          <div>
            <div className="text-[11px] font-medium text-ink-600 mb-1.5">可编辑参数(勾选要暴露给用户的;不勾的用代码默认值,固定不可改)</div>
            <div className="space-y-1.5">
              {params.map((r, i) => (
                <div key={i} className="rounded-lg ring-1 ring-ink-200 p-2">
                  <div className="flex items-center gap-2">
                    <input type="checkbox" checked={r.include} onChange={(e) => setRow(i, { include: e.target.checked })} />
                    {r.isNew ? (
                      <>
                        <input value={r.key} onChange={(e) => setRow(i, { key: e.target.value.replace(/\s+/g, '_') })} placeholder="参数名(英文)"
                          className="font-mono text-xs border border-ink-200 rounded-md px-2 py-1 w-32 focus:outline-none focus:border-brand-400" />
                        <select value={String(r.spec.type ?? 'string')} onChange={(e) => setRow(i, { spec: { ...r.spec, type: e.target.value } })}
                          className="text-xs border border-ink-200 rounded-md px-1.5 py-1 bg-white focus:outline-none focus:border-brand-400">
                          <option value="string">文本</option><option value="number">数字</option><option value="integer">整数</option><option value="boolean">是否</option><option value="array">列表</option>
                        </select>
                        <button onClick={() => removeRow(i)} className="ml-auto text-ink-400 hover:text-red-600" title="删除这个参数"><X className="w-3.5 h-3.5" /></button>
                      </>
                    ) : (
                      <>
                        <span className="font-mono text-xs font-medium">{r.key}</span>
                        <span className="text-[10px] text-ink-400">{String(r.spec.type ?? 'string')}{r.spec.required ? ' · 必填' : ''}{r.spec.enum ? ` · 选项 ${r.spec.enum.join('/')}` : ''}</span>
                      </>
                    )}
                  </div>
                  {r.include && (
                    <div className="mt-1.5 grid grid-cols-2 gap-1.5">
                      <input value={r.label} onChange={(e) => setRow(i, { label: e.target.value })} placeholder="参数说明(给用户的提示)"
                        className="border border-ink-200 rounded-md px-2 py-1 text-xs focus:outline-none focus:border-brand-400" />
                      <input value={r.defaultStr} onChange={(e) => setRow(i, { defaultStr: e.target.value })} placeholder="默认值(可空)"
                        className="border border-ink-200 rounded-md px-2 py-1 text-xs font-mono focus:outline-none focus:border-brand-400" />
                    </div>
                  )}
                </div>
              ))}
              {params.length === 0 && <div className="text-xs text-ink-400">这个工具没有可调参数。</div>}
            </div>
            <button onClick={addParam} className="mt-1.5 text-[11px] px-2 py-1 rounded-md ring-1 ring-dashed ring-brand-300 text-brand-600 hover:bg-brand-50 inline-flex items-center gap-1">
              ＋ 加一个参数
            </button>
            <div className="text-[10.5px] text-ink-400 mt-1 leading-snug">新参数需要算法代码用得上它 —— AI 生成的工具大多能直接接收;若运行时报 “unexpected argument”,说明算法没用到它,用下面的「让 AI 改」最稳妥。</div>

            {showReuse && (
              <div className="mt-2.5 rounded-lg bg-violet-50/60 ring-1 ring-violet-100 p-2.5">
                <div className="flex items-center gap-1.5 text-[11px] text-violet-700 font-medium mb-1.5">
                  <Sparkles className="w-3.5 h-3.5" /> 想要别的参数 / 能力?一句话说清,让 AI 重写这个工具(代码+参数一起改,保证真能用)
                </div>
                <div className="flex gap-1.5">
                  <input value={refineIntent} onChange={(e) => setRefineIntent(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); refine(); } }}
                    placeholder="如:再加一个能选标准化方法(zscore / minmax)的参数"
                    className="flex-1 border border-ink-200 rounded-md px-2 py-1 text-xs focus:outline-none focus:border-violet-400" />
                  <button onClick={refine} disabled={refining || !refineIntent.trim()}
                    className="text-xs px-2.5 py-1 rounded-md bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-50 inline-flex items-center gap-1 shrink-0">
                    {refining ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />} 让 AI 改
                  </button>
                </div>
                {refineMsg && <div className="text-[11px] text-ink-600 mt-1.5 leading-snug">{refineMsg}</div>}
              </div>
            )}
          </div>
          {err && <div className="text-xs text-red-700 bg-red-50 rounded-lg px-2.5 py-1.5">{err}</div>}
        </div>

        <div className="flex justify-end gap-2 px-4 py-3 border-t border-ink-200">
          <button onClick={onCancel} className="text-xs px-3 py-1.5 rounded-lg ring-1 ring-ink-200 text-ink-600 hover:bg-ink-50">取消</button>
          <button onClick={save} disabled={busy} className="text-xs px-3 py-1.5 rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50 flex items-center gap-1.5">
            {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />} 保存到工具库
          </button>
        </div>
      </div>
    </div>
  );
}

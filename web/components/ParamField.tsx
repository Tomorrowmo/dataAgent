'use client';

import type { ParamSpec } from '@/lib/api';
import { paramKind, paramHint, paramLabel } from '@/lib/algoMeta';

/** A single algorithm-parameter input, rendered from its JSON-schema spec:
 *  column multi-/single-select when a dataset is chosen, enum dropdowns, bools,
 *  numbers, or free text. Shared by the library run panel, the template list
 *  editor, and the flow canvas inspector. */
export default function ParamField({ name, spec, value, cols, aiHint, onChange }: {
  name: string; spec: ParamSpec; value: string; cols: string[]; aiHint?: string; onChange: (v: string) => void;
}) {
  const kind = paramKind(name, spec);
  const hint = paramHint(name, spec);
  const friendly = paramLabel(name);
  const label = (
    <label className="block text-xs mb-1">
      <span className="text-ink-700 font-medium">{friendly}</span>
      {spec.required && <span className="text-red-500"> *</span>}
      {friendly !== name && <span className="text-ink-400 font-mono ml-1.5">{name}</span>}
      {hint && <span className="text-ink-400 font-normal"> — {hint}</span>}
      {aiHint && <span className="block text-brand-600 font-normal mt-0.5">💡 {aiHint}</span>}
    </label>
  );

  if (kind === 'colmulti') {
    const selected = value.split(',').map((s) => s.trim()).filter(Boolean);
    // Columns selected but NOT present in the current input — stale refs (e.g. a
    // template configured on another dataset). Show them red so they're visible
    // and one-click removable, instead of silently breaking the run.
    const missing = selected.filter((s) => !cols.includes(s));
    const setSel = (arr: string[]) => onChange(arr.join(', '));
    return (
      <div>{label}
        {(cols.length > 0 || missing.length > 0) ? (
          <div className="flex flex-wrap gap-1">
            {cols.map((c) => {
              const on = selected.includes(c);
              return (
                <button key={c} type="button"
                  onClick={() => setSel(on ? selected.filter((x) => x !== c) : [...selected, c])}
                  className={`text-xs px-2 py-1 rounded-md ring-1 transition ${on ? 'bg-brand-600 text-white ring-transparent' : 'bg-white text-ink-600 ring-ink-200 hover:bg-ink-50'}`}>
                  {c}
                </button>
              );
            })}
            {missing.map((c) => (
              <button key={c} type="button" title="该列不在当前输入数据中 —— 点 × 移除"
                onClick={() => setSel(selected.filter((x) => x !== c))}
                className="text-xs px-2 py-1 rounded-md ring-1 bg-red-50 text-red-600 ring-red-200 flex items-center gap-1">
                {c}<span className="font-bold leading-none">×</span>
              </button>
            ))}
          </div>
        ) : (
          <input value={value} onChange={(e) => onChange(e.target.value)} placeholder="先选数据集,或逗号分隔列名"
            className="w-full border border-ink-200 rounded-lg px-2 py-1.5 bg-white text-sm font-mono" />
        )}
        {missing.length > 0 && <div className="text-[10.5px] text-red-500 mt-1">红色列不在当前输入中,点 × 移除或改选</div>}
      </div>
    );
  }

  if (kind === 'colsingle') {
    // A selected column that no longer exists in the input → keep it visible
    // (flagged) so the user can see the mismatch and re-pick.
    const missing = value && !cols.includes(value) ? value : '';
    return (
      <div>{label}
        {(cols.length > 0 || missing) ? (
          <select value={value} onChange={(e) => onChange(e.target.value)}
            className={`w-full border rounded-lg px-2 py-1.5 bg-white text-sm ${missing ? 'border-red-300 text-red-600' : 'border-ink-200'}`}>
            <option value="">（请选择列）</option>
            {missing && <option value={missing}>{missing}(不在输入列中)</option>}
            {cols.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        ) : (
          <input value={value} onChange={(e) => onChange(e.target.value)} placeholder="先选数据集,或输入列名"
            className="w-full border border-ink-200 rounded-lg px-2 py-1.5 bg-white text-sm font-mono" />
        )}
      </div>
    );
  }

  if (kind === 'enum') {
    return (
      <div>{label}
        <select value={value} onChange={(e) => onChange(e.target.value)} className="w-full border border-ink-200 rounded-lg px-2 py-1.5 bg-white text-sm">
          {!spec.required && <option value="">（默认）</option>}
          {spec.enum!.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      </div>
    );
  }
  if (kind === 'bool') {
    return (
      <div>{label}
        <select value={value} onChange={(e) => onChange(e.target.value)} className="w-full border border-ink-200 rounded-lg px-2 py-1.5 bg-white text-sm">
          <option value="">（默认）</option>
          <option value="true">是</option>
          <option value="false">否</option>
        </select>
      </div>
    );
  }
  return (
    <div>{label}
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={kind === 'num' ? '数字' : ''}
        type={kind === 'num' ? 'number' : 'text'}
        className="w-full border border-ink-200 rounded-lg px-2 py-1.5 bg-white text-sm font-mono" />
    </div>
  );
}

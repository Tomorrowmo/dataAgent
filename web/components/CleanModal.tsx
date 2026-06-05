'use client';

import { useEffect, useRef, useState } from 'react';
import { CheckCircle2, AlertTriangle, Loader2, Sparkles, X, RefreshCw } from 'lucide-react';
import { api, streamDatasetClean, type Dataset, type ParserEvent } from '@/lib/api';

/**
 * "AI 整理脏数据" — drives the data-cleaner codegen for a messy dataset and shows
 * the cleaner being written live (same UX as the parser modal), a preview of the
 * tidy result, and an approve button that registers it as a NEW dataset.
 */
type Status =
  | { kind: 'streaming' }
  | { kind: 'success'; code: string; preview: Record<string, unknown>[]; result_rows: number; duration_ms: number }
  | { kind: 'give_up'; errors: string[] }
  | { kind: 'fatal'; error: string };

export default function CleanModal({
  dataset,
  onClose,
  onCreated,
}: {
  dataset: Dataset;
  onClose: () => void;
  onCreated: (ds: Dataset) => void;
}) {
  const [status, setStatus] = useState<Status>({ kind: 'streaming' });
  const [stage, setStage] = useState('正在准备整理…');
  const [progress, setProgress] = useState(6);
  const [liveCode, setLiveCode] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const codeRef = useRef<HTMLPreElement>(null);

  async function run() {
    setStatus({ kind: 'streaming' });
    setStage('正在准备整理…');
    setProgress(6);
    setLiveCode('');
    setSaveError('');
    try {
      await streamDatasetClean(dataset.id, (ev: ParserEvent) => {
        if (ev.event === 'attempt_start') { setLiveCode(''); setStage(`正在编写整理代码…（第 ${ev.n} 次）`); setProgress(12); }
        else if (ev.event === 'token') { setLiveCode((c) => c + ev.delta); setStage('正在编写整理代码…'); setProgress((p) => Math.min(70, p + 0.8)); }
        else if (ev.event === 'code_ready') { setStage('校验中…'); setProgress(76); }
        else if (ev.event === 'validated') { setStage('沙箱执行整理…'); setProgress(88); }
        else if (ev.event === 'attempt_failed') { setStage(''); setProgress(0); }
        else if (ev.event === 'success') {
          setProgress(100);
          setStatus({ kind: 'success', code: ev.code, preview: ev.preview, result_rows: ev.result_rows, duration_ms: ev.duration_ms });
        }
        else if (ev.event === 'give_up') setStatus({ kind: 'give_up', errors: ev.errors });
        else if (ev.event === 'fatal') setStatus({ kind: 'fatal', error: ev.error });
      });
    } catch (e) {
      setStatus({ kind: 'fatal', error: (e as Error).message });
    }
  }

  useEffect(() => { run(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);
  useEffect(() => { if (codeRef.current) codeRef.current.scrollTop = codeRef.current.scrollHeight; }, [liveCode]);

  async function approve() {
    if (status.kind !== 'success') return;
    setSaving(true);
    setSaveError('');
    try {
      const ds = await api.cleanApprove(dataset.id, status.code, `${dataset.name}（整理）`);
      onCreated(ds);
    } catch (e) {
      setSaveError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  const isStreaming = status.kind === 'streaming';
  const cols = status.kind === 'success' && status.preview[0] ? Object.keys(status.preview[0]) : [];

  return (
    <div className="fixed inset-0 z-40 bg-ink-900/50 backdrop-blur-sm grid place-items-center p-4">
      <div className="bg-white w-full max-w-3xl max-h-[90vh] overflow-y-auto rounded-2xl shadow-xl ring-1 ring-ink-200">
        <div className="sticky top-0 bg-white border-b border-ink-200 px-5 py-3 flex items-center gap-3 z-10">
          <Sparkles className="w-5 h-5 text-brand-600" />
          <div className="flex-1 min-w-0">
            <div className="font-medium truncate">AI 整理脏数据</div>
            <div className="text-xs text-ink-500 truncate">来源:{dataset.name} ({dataset.rows} × {dataset.columns})</div>
          </div>
          <button onClick={onClose} className="text-ink-500 hover:text-ink-900 p-1"><X className="w-4 h-4" /></button>
        </div>

        <div className="px-5 py-4 space-y-4">
          <p className="text-sm text-ink-700">让 AI 写一段整理代码 —— 找表头、去空行/单位行、规范列名、把数值列转成数字,产出一个规整的新数据集。原数据集保留不动。</p>

          {isStreaming && (
            <div className="rounded-xl bg-ink-50 ring-1 ring-ink-200 p-4 space-y-2">
              <div className="flex items-center gap-2 text-xs text-ink-600">
                <Loader2 className="w-3 h-3 animate-spin text-brand-600" />
                <span>{stage}</span>
                <span className="ml-auto font-mono text-ink-400">{Math.round(progress)}%</span>
              </div>
              <div className="h-1.5 w-full bg-ink-100 rounded-full overflow-hidden">
                <div className="h-full bg-brand-500 rounded-full transition-all duration-300" style={{ width: `${progress}%` }} />
              </div>
              {liveCode && (
                <pre ref={codeRef} className="bg-ink-900 text-ink-50 text-[11.5px] p-3 rounded-lg overflow-auto max-h-64 leading-snug">
                  <code>{liveCode.replace(/^```(?:python)?\s*/i, '').replace(/```\s*$/, '')}<span className="inline-block w-1.5 h-3.5 bg-emerald-400 align-middle animate-pulse ml-0.5" /></code>
                </pre>
              )}
            </div>
          )}

          {status.kind === 'success' && (
            <>
              <div className="rounded-xl bg-emerald-50 ring-1 ring-emerald-100 px-4 py-3 text-sm text-emerald-700 flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 shrink-0" /> 整理完成 —— {status.result_rows} 行 × {cols.length} 列(耗时 {status.duration_ms} ms)。预览:
              </div>
              {status.preview.length > 0 && (
                <div className="rounded-xl ring-1 ring-ink-200 overflow-auto max-h-72">
                  <table className="text-xs min-w-full">
                    <thead className="bg-ink-50 text-ink-500 sticky top-0">
                      <tr>{cols.map((c) => <th key={c} className="text-left py-2 px-3 font-medium whitespace-nowrap">{c}</th>)}</tr>
                    </thead>
                    <tbody>
                      {status.preview.map((row, i) => (
                        <tr key={i} className="border-t border-ink-100">
                          {cols.map((c) => <td key={c} className="py-1.5 px-3 font-mono whitespace-nowrap">{fmt(row[c])}</td>)}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {saveError && <div className="text-sm text-red-600 flex items-center gap-2"><AlertTriangle className="w-4 h-4" /> {saveError}</div>}
              <div className="flex items-center gap-2">
                <button onClick={approve} disabled={saving} className="px-4 py-2 rounded-xl bg-brand-600 text-white font-medium hover:bg-brand-700 disabled:opacity-50 flex items-center gap-2">
                  {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />} 保存为新数据集
                </button>
                <button onClick={run} disabled={saving} className="px-3 py-2 rounded-xl border border-ink-200 text-sm flex items-center gap-1.5 hover:bg-ink-50 disabled:opacity-50">
                  <RefreshCw className="w-3.5 h-3.5" /> 重试
                </button>
                <button onClick={onClose} disabled={saving} className="px-3 py-2 rounded-xl border border-ink-200 text-sm hover:bg-ink-50 disabled:opacity-50">取消</button>
              </div>
            </>
          )}

          {(status.kind === 'give_up' || status.kind === 'fatal') && (
            <div className="rounded-xl bg-red-50 ring-1 ring-red-100 px-4 py-3 text-sm text-red-700 space-y-2">
              <div className="font-medium flex items-center gap-2"><AlertTriangle className="w-4 h-4" /> 整理失败</div>
              <pre className="text-xs whitespace-pre-wrap font-mono bg-white/60 rounded p-2 max-h-40 overflow-y-auto">
                {status.kind === 'fatal' ? status.error : status.errors.join('\n---\n')}
              </pre>
              <div className="flex gap-2">
                <button onClick={run} className="px-3 py-1.5 rounded-lg bg-brand-600 text-white text-sm flex items-center gap-1.5 hover:bg-brand-700"><RefreshCw className="w-3.5 h-3.5" /> 重试</button>
                <button onClick={onClose} className="px-3 py-1.5 rounded-lg border border-ink-200 text-sm hover:bg-ink-50">取消</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function fmt(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(4);
  const s = String(v);
  return s.length > 60 ? s.slice(0, 57) + '…' : s;
}

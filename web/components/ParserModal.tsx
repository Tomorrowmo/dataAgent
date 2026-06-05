'use client';

import { useEffect, useRef, useState } from 'react';
import { CheckCircle2, AlertTriangle, Loader2, Sparkles, X, RefreshCw, ChevronRight } from 'lucide-react';
import { api, streamParserGenerate, type Dataset, type ParserEvent, type UploadResp } from '@/lib/api';
import { useT } from '@/lib/i18n';

type Attempt = {
  n: number;
  llm_ms?: number;
  code_size?: number;
  validation_imports?: string[];
  failed_stage?: 'llm' | 'validation' | 'sandbox';
  failed_error?: string;
  failed_duration_ms?: number;
};

type Status =
  | { kind: 'streaming' }
  | { kind: 'success'; code: string; meta: Record<string, unknown>; result_rows: number; preview: Record<string, unknown>[]; duration_ms: number; n: number }
  | { kind: 'give_up'; errors: string[] }
  | { kind: 'fatal'; error: string };

export default function ParserModal({
  pending,
  onClose,
  onIngested,
}: {
  pending: NonNullable<UploadResp['needs_parser']>;
  onClose: () => void;
  onIngested: (ds: Dataset) => void;
}) {
  const t = useT();
  const [status, setStatus] = useState<Status>({ kind: 'streaming' });
  const [attempts, setAttempts] = useState<Attempt[]>([]);
  const [currentStage, setCurrentStage] = useState<string>('');
  const [progress, setProgress] = useState(0);
  const [liveCode, setLiveCode] = useState('');
  const [showCode, setShowCode] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const logEndRef = useRef<HTMLDivElement>(null);
  const liveCodeRef = useRef<HTMLPreElement>(null);

  async function run() {
    setStatus({ kind: 'streaming' });
    setAttempts([]);
    // Show a status the instant the modal opens — never a blank box, even
    // before the first backend event lands (the boot/DB can be slow).
    setCurrentStage('正在准备解析器…');
    setProgress(6);
    setLiveCode('');
    setSaveError('');
    try {
      await streamParserGenerate(pending.staging_path, pending.extension, (ev: ParserEvent) => {
        if (ev.event === 'attempt_start') {
          setAttempts((a) => [...a, { n: ev.n }]);
          setLiveCode('');
          setCurrentStage(`正在写解析器…（第 ${ev.n} 次）`);
          setProgress(12);
        } else if (ev.event === 'token') {
          // Stream the parser code in live — the model writing in front of you.
          setLiveCode((c) => c + ev.delta);
          setCurrentStage('正在写解析器…');
          setProgress((p) => Math.min(70, p + 0.8));
        } else if (ev.event === 'code_ready') {
          setAttempts((a) => updateLast(a, ev.n, {
            llm_ms: ev.duration_ms, code_size: ev.size,
          }));
          setCurrentStage(t('adapter.validating'));
          setProgress(76);
        } else if (ev.event === 'validated') {
          setAttempts((a) => updateLast(a, ev.n, { validation_imports: ev.imports }));
          setCurrentStage(t('adapter.running'));
          setProgress(88);
        } else if (ev.event === 'attempt_failed') {
          setAttempts((a) => updateLast(a, ev.n, {
            failed_stage: ev.stage as Attempt['failed_stage'],
            failed_error: ev.error,
            failed_duration_ms: ev.duration_ms,
          }));
          setCurrentStage('');
          setProgress(0);
        } else if (ev.event === 'success') {
          setProgress(100);
          setStatus({
            kind: 'success',
            code: ev.code, meta: ev.meta,
            result_rows: ev.result_rows, preview: ev.preview,
            duration_ms: ev.duration_ms, n: ev.n,
          });
          setCurrentStage('');
        } else if (ev.event === 'give_up') {
          setStatus({ kind: 'give_up', errors: ev.errors });
          setCurrentStage('');
        } else if (ev.event === 'fatal') {
          setStatus({ kind: 'fatal', error: ev.error });
          setCurrentStage('');
        }
      });
    } catch (e) {
      setStatus({ kind: 'fatal', error: (e as Error).message });
    }
  }

  useEffect(() => { run(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);
  useEffect(() => { logEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [attempts, status]);
  // Keep the live code view pinned to the newest tokens as they stream in.
  useEffect(() => { if (liveCodeRef.current) liveCodeRef.current.scrollTop = liveCodeRef.current.scrollHeight; }, [liveCode]);

  async function approve() {
    if (status.kind !== 'success') return;
    setSaving(true);
    setSaveError('');
    try {
      const ds = await api.approveParser({
        staging_path: pending.staging_path,
        extension: pending.extension,
        code: status.code,
        meta: status.meta,
        name: pending.display_name ?? undefined,
        description: pending.description,
      });
      onIngested(ds);
    } catch (e) {
      setSaveError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  const isStreaming = status.kind === 'streaming';

  return (
    <div className="fixed inset-0 z-40 bg-ink-900/50 backdrop-blur-sm grid place-items-center p-4">
      <div className="bg-white w-full max-w-3xl max-h-[90vh] overflow-y-auto rounded-2xl shadow-xl ring-1 ring-ink-200">
        <div className="sticky top-0 bg-white border-b border-ink-200 px-5 py-3 flex items-center gap-3 z-10">
          <Sparkles className="w-5 h-5 text-brand-600" />
          <div className="flex-1 min-w-0">
            <div className="font-medium truncate">{t('adapter.unknownTitle')}</div>
            <div className="text-xs text-ink-500 truncate">{pending.filename} · {(pending.size_bytes / 1024).toFixed(1)} KB</div>
          </div>
          <button onClick={onClose} className="text-ink-500 hover:text-ink-900 p-1">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          <p className="text-sm text-ink-700">
            {t('adapter.unknownBody', { ext: pending.extension })}
          </p>

          {/* Live attempt log */}
          <div className="rounded-xl bg-ink-50 ring-1 ring-ink-200 p-4 space-y-3">
            {attempts.map((a) => (
              <AttemptRow key={a.n} attempt={a} t={t} totalAttempts={3} />
            ))}
            {isStreaming && (
              <div className="space-y-1.5">
                <div className="flex items-center gap-2 text-xs text-ink-600 pl-5">
                  <Loader2 className="w-3 h-3 animate-spin text-brand-600" />
                  <span>{currentStage || '正在写解析器…'}</span>
                  <span className="ml-auto font-mono text-ink-400">{Math.round(progress)}%</span>
                </div>
                <div className="h-1.5 w-full bg-ink-100 rounded-full overflow-hidden ml-5">
                  <div
                    className="h-full bg-brand-500 rounded-full transition-all duration-300 ease-out"
                    style={{ width: `${progress}%` }}
                  />
                </div>
              </div>
            )}
            {/* The parser code materializing live, token by token. */}
            {isStreaming && liveCode && (
              <pre
                ref={liveCodeRef}
                className="bg-ink-900 text-ink-50 text-[11.5px] p-3 rounded-lg overflow-x-auto leading-snug max-h-64 overflow-y-auto ml-5"
              >
                <code>{stripFences(liveCode)}<span className="inline-block w-1.5 h-3.5 bg-emerald-400 align-middle animate-pulse ml-0.5" /></code>
              </pre>
            )}
            <div ref={logEndRef} />
          </div>

          {/* Success result */}
          {status.kind === 'success' && (
            <>
              <div className="rounded-xl bg-emerald-50 ring-1 ring-emerald-100 px-4 py-3 text-sm text-emerald-700 flex items-start gap-2">
                <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" />
                <div className="flex-1">
                  <div className="font-medium">
                    {t('adapter.parsed', {
                      rows: status.result_rows,
                      cols: status.preview[0] ? Object.keys(status.preview[0]).length : 0,
                    })}
                  </div>
                  <div className="text-xs text-emerald-600 mt-0.5">
                    {t('adapter.success', { ms: status.duration_ms, n: status.n })}
                  </div>
                </div>
              </div>

              {status.preview.length > 0 && (
                <div className="rounded-xl ring-1 ring-ink-200 overflow-hidden">
                  <div className="overflow-x-auto max-h-72">
                    <table className="text-xs min-w-full">
                      <thead className="bg-ink-50 text-ink-500 uppercase tracking-wide sticky top-0">
                        <tr>
                          {Object.keys(status.preview[0]).map((c) => (
                            <th key={c} className="text-left py-2 px-3 font-medium whitespace-nowrap">{c}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {status.preview.map((row, i) => (
                          <tr key={i} className="border-t border-ink-100">
                            {Object.keys(status.preview[0]).map((c) => (
                              <td key={c} className="py-1.5 px-3 font-mono whitespace-nowrap">{formatCell(row[c])}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              <div className="rounded-xl ring-1 ring-ink-200">
                <button
                  onClick={() => setShowCode((v) => !v)}
                  className="w-full px-4 py-2 text-sm font-medium text-left hover:bg-ink-50 flex items-center gap-2"
                >
                  <ChevronRight className={`w-4 h-4 transition-transform ${showCode ? 'rotate-90' : ''}`} />
                  {t('adapter.proposedCode')}
                </button>
                {showCode && (
                  <pre className="bg-ink-900 text-ink-50 text-[12.5px] p-4 overflow-x-auto leading-snug max-h-80 overflow-y-auto">
                    <code>{status.code}</code>
                  </pre>
                )}
              </div>

              {saveError && (
                <div className="text-sm text-red-600 flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4" /> {saveError}
                </div>
              )}

              <div className="flex items-center gap-2">
                <button
                  onClick={approve}
                  disabled={saving}
                  className="px-4 py-2 rounded-xl bg-brand-600 text-white font-medium hover:bg-brand-700 disabled:opacity-50 flex items-center gap-2"
                >
                  {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
                  {t('adapter.approveBtn')}
                </button>
                <button onClick={run} disabled={saving} className="px-3 py-2 rounded-xl border border-ink-200 text-sm flex items-center gap-1.5 hover:bg-ink-50 disabled:opacity-50">
                  <RefreshCw className="w-3.5 h-3.5" /> {t('common.retry')}
                </button>
                <button onClick={onClose} disabled={saving} className="px-3 py-2 rounded-xl border border-ink-200 text-sm hover:bg-ink-50 disabled:opacity-50">
                  {t('common.cancel')}
                </button>
              </div>
            </>
          )}

          {/* Give up state */}
          {status.kind === 'give_up' && (
            <div className="rounded-xl bg-red-50 ring-1 ring-red-100 px-4 py-3 text-sm text-red-700 space-y-3">
              <div className="font-medium flex items-center gap-2">
                <AlertTriangle className="w-4 h-4" />
                {t('adapter.giveUp', { n: status.errors.length })}
              </div>
              <div className="flex gap-2">
                <button onClick={run} className="px-3 py-1.5 rounded-lg bg-brand-600 text-white text-sm flex items-center gap-1.5 hover:bg-brand-700">
                  <RefreshCw className="w-3.5 h-3.5" /> {t('common.retry')}
                </button>
                <button onClick={onClose} className="px-3 py-1.5 rounded-lg border border-ink-200 text-sm hover:bg-ink-50">
                  {t('common.cancel')}
                </button>
              </div>
            </div>
          )}

          {/* Fatal error */}
          {status.kind === 'fatal' && (
            <div className="rounded-xl bg-red-50 ring-1 ring-red-100 px-4 py-3 text-sm text-red-700 space-y-2">
              <div className="font-medium flex items-center gap-2">
                <AlertTriangle className="w-4 h-4" /> {t('common.error')}
              </div>
              <pre className="text-xs whitespace-pre-wrap font-mono bg-white/60 rounded p-2 max-h-40 overflow-y-auto">
                {status.error}
              </pre>
              <div className="flex gap-2">
                <button onClick={run} className="px-3 py-1.5 rounded-lg bg-brand-600 text-white text-sm flex items-center gap-1.5 hover:bg-brand-700">
                  <RefreshCw className="w-3.5 h-3.5" /> {t('common.retry')}
                </button>
                <button onClick={onClose} className="px-3 py-1.5 rounded-lg border border-ink-200 text-sm hover:bg-ink-50">
                  {t('common.cancel')}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function updateLast(list: Attempt[], n: number, patch: Partial<Attempt>): Attempt[] {
  return list.map((a) => (a.n === n ? { ...a, ...patch } : a));
}

function AttemptRow({ attempt, t, totalAttempts }: { attempt: Attempt; t: (k: string, vars?: Record<string, string | number>) => string; totalAttempts: number }) {
  const failed = !!attempt.failed_stage;
  const success = attempt.validation_imports !== undefined && !failed;
  const inProgress = !failed && !success;
  const [showError, setShowError] = useState(false);

  return (
    <div className="text-sm">
      <div className="flex items-center gap-2">
        <span className={`w-5 h-5 rounded-full grid place-items-center text-[10px] font-semibold shrink-0 ${
          failed ? 'bg-red-100 text-red-700' :
          success ? 'bg-emerald-100 text-emerald-700' :
          'bg-brand-100 text-brand-700'
        }`}>{attempt.n}</span>
        <span className="font-medium text-ink-700">{t('adapter.attempt', { n: attempt.n, max: totalAttempts })}</span>
        {inProgress && <Loader2 className="w-3 h-3 animate-spin text-ink-400" />}
      </div>
      <div className="pl-7 mt-1 space-y-0.5 text-xs text-ink-500">
        {attempt.llm_ms !== undefined && (
          <div>↳ {t('adapter.thought', { bytes: attempt.code_size ?? 0, ms: attempt.llm_ms })}</div>
        )}
        {attempt.validation_imports !== undefined && (
          <div>↳ {t('adapter.validated', { imports: attempt.validation_imports.slice(0, 4).join(', ') || '—' })}</div>
        )}
        {failed && (
          <div className="text-red-600">
            ↳ <strong>{t(`adapter.stage.${attempt.failed_stage}`)}</strong>
            {attempt.failed_duration_ms !== undefined && ` (${attempt.failed_duration_ms} ms)`}
            {' '}
            <button onClick={() => setShowError((v) => !v)} className="underline hover:text-red-700">
              {showError ? '— hide' : t('adapter.viewError')}
            </button>
            {showError && attempt.failed_error && (
              <pre className="mt-1 text-[11px] whitespace-pre-wrap font-mono bg-red-50 rounded p-2 max-h-32 overflow-y-auto text-red-700">
                {attempt.failed_error}
              </pre>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/** Strip a leading ```python fence (and trailing ```) as the code streams in,
 *  so the live view reads as clean code rather than markdown. Tolerant of the
 *  fence arriving only partially. */
function stripFences(s: string): string {
  return s.replace(/^```(?:python)?\s*/i, '').replace(/```\s*$/, '');
}

function formatCell(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(4);
  const s = String(v);
  return s.length > 60 ? s.slice(0, 57) + '…' : s;
}

'use client';

import { useState, type ClipboardEvent, type DragEvent } from 'react';
import { api, type FeedbackKind } from '@/lib/api';
import { useLangStore } from '@/lib/i18n';

/** Read an image File and re-encode it downscaled (≤1600px wide) as a JPEG data
 *  URL, so a pasted full-res screenshot doesn't bloat the payload / storage. */
function downscale(file: File, maxW = 1600, quality = 0.85): Promise<string> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      const scale = Math.min(1, maxW / img.width);
      const w = Math.round(img.width * scale);
      const h = Math.round(img.height * scale);
      const canvas = document.createElement('canvas');
      canvas.width = w; canvas.height = h;
      const ctx = canvas.getContext('2d');
      if (!ctx) { reject(new Error('no 2d context')); return; }
      ctx.drawImage(img, 0, 0, w, h);
      resolve(canvas.toDataURL('image/jpeg', quality));
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('image load failed')); };
    img.src = url;
  });
}

/**
 * A frictionless "📍 标记/反馈" affordance the expert can hit AT THE MOMENT a
 * thought happens. The note is captured WITH its context (which view /
 * conversation / dataset the user was looking at + the URL), so a vague memory
 * becomes an actionable, replayable record. Three buckets route to three fixes.
 */

type Props = {
  view: string;
  conversationId: number | null;
  datasetId?: number | null;
};

const KINDS: { key: FeedbackKind; zh: string; en: string; hint_zh: string; hint_en: string }[] = [
  { key: 'cannot',   zh: '想做但做不到', en: 'Wanted to, couldn’t', hint_zh: '能力缺口', hint_en: 'capability gap' },
  { key: 'wrong',    zh: '它做错了',     en: 'It got it wrong',     hint_zh: '我得手动改', hint_en: 'had to fix by hand' },
  { key: 'distrust', zh: '不敢信结果',   en: 'Don’t trust it',      hint_zh: '对但没把握', hint_en: 'right but unsure' },
  { key: 'idea',     zh: '想法 / 其它',  en: 'Idea / other',        hint_zh: '随手一记',   hint_en: 'just a note' },
];

export default function FeedbackButton({ view, conversationId, datasetId }: Props) {
  const lang = useLangStore((s) => s.lang);
  const zh = lang === 'zh';
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<FeedbackKind>('idea');
  const [text, setText] = useState('');
  const [shot, setShot] = useState<string | null>(null);  // downscaled JPEG data URL
  const [dragOver, setDragOver] = useState(false);
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState('');

  function reset() {
    setKind('idea'); setText(''); setShot(null); setDragOver(false); setSending(false); setDone(false); setError('');
  }
  function close() { setOpen(false); setTimeout(reset, 200); }

  async function addImage(file: File | null | undefined) {
    if (!file || !file.type.startsWith('image/')) return;
    try { setShot(await downscale(file)); }
    catch { setError(zh ? '这张图读不了,换一张试试' : 'Could not read that image'); }
  }
  function onPaste(e: ClipboardEvent) {
    const item = Array.from(e.clipboardData.items).find((i) => i.type.startsWith('image/'));
    if (item) { e.preventDefault(); addImage(item.getAsFile()); }
  }
  function onDrop(e: DragEvent) {
    e.preventDefault(); setDragOver(false);
    addImage(e.dataTransfer.files?.[0]);
  }

  async function submit() {
    const body = text.trim();
    if (!body || sending) return;
    setSending(true); setError('');
    try {
      await api.submitFeedback({
        text: body,
        kind,
        view,
        conversation_id: conversationId,
        dataset_id: datasetId ?? null,
        screenshot_b64: shot,
        context: {
          url: typeof window !== 'undefined' ? window.location.href : '',
          ua: typeof navigator !== 'undefined' ? navigator.userAgent : '',
          ts_client: new Date().toISOString(),
        },
      });
      setDone(true);
      setTimeout(close, 1100);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSending(false);
    }
  }

  return (
    <>
      {/* Floating trigger — always reachable, low-key */}
      <button
        onClick={() => setOpen(true)}
        title={zh ? '标记 / 反馈' : 'Mark / feedback'}
        className="fixed bottom-5 right-5 z-40 flex items-center gap-2 rounded-full bg-sky-600 px-4 py-2.5
                   text-sm font-medium text-white shadow-lg shadow-sky-600/30 transition
                   hover:-translate-y-0.5 hover:bg-sky-700 hover:shadow-xl focus:outline-none
                   focus-visible:ring-2 focus-visible:ring-sky-400 focus-visible:ring-offset-2"
      >
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
             strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 21V5a2 2 0 0 1 2-2h10l4 4v8a2 2 0 0 1-2 2H9l-5 4z" />
        </svg>
        {zh ? '反馈' : 'Feedback'}
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/40 p-4 sm:items-center"
          onClick={close}
        >
          <div
            className="w-full max-w-md rounded-2xl bg-white p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
            onPaste={onPaste}
          >
            {done ? (
              <div className="flex flex-col items-center gap-3 py-8 text-center">
                <div className="grid h-12 w-12 place-items-center rounded-full bg-emerald-50 text-emerald-600">
                  <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor"
                       strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M20 6L9 17l-5-5" />
                  </svg>
                </div>
                <div className="text-base font-semibold text-slate-800">{zh ? '已收到,谢谢!' : 'Got it — thanks!'}</div>
                <div className="text-sm text-slate-500">{zh ? '已带上当前页面的上下文一起记录。' : 'Saved with the current context.'}</div>
              </div>
            ) : (
              <>
                <div className="mb-1 flex items-center justify-between">
                  <h2 className="text-base font-semibold text-slate-800">{zh ? '说说当下的想法' : 'Drop a thought'}</h2>
                  <button onClick={close} className="text-slate-400 hover:text-slate-600" aria-label="close">
                    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M6 6l12 12M18 6L6 18" /></svg>
                  </button>
                </div>
                <p className="mb-3 text-xs text-slate-500">
                  {zh ? '会自动带上你当前所在的页面 / 会话上下文,方便事后定位。' : 'Your current view / conversation context is attached automatically.'}
                </p>

                {/* kind chips */}
                <div className="mb-3 grid grid-cols-2 gap-2">
                  {KINDS.map((k) => {
                    const active = kind === k.key;
                    return (
                      <button
                        key={k.key}
                        onClick={() => setKind(k.key)}
                        className={`rounded-lg border px-3 py-2 text-left text-sm transition ${
                          active
                            ? 'border-sky-500 bg-sky-50 text-sky-800 ring-1 ring-sky-300'
                            : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300'
                        }`}
                      >
                        <div className="font-medium">{zh ? k.zh : k.en}</div>
                        <div className={`text-[11px] ${active ? 'text-sky-600' : 'text-slate-400'}`}>{zh ? k.hint_zh : k.hint_en}</div>
                      </button>
                    );
                  })}
                </div>

                <textarea
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  autoFocus
                  rows={4}
                  placeholder={zh ? '当时在想什么?哪一步、期望是什么、实际怎样…' : 'What were you thinking? Which step, expected vs. actual…'}
                  className="w-full resize-none rounded-lg border border-slate-200 p-3 text-sm text-slate-800
                             outline-none focus:border-sky-400 focus:ring-1 focus:ring-sky-300"
                  onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') submit(); }}
                />

                {/* screenshot capture: paste / drop / pick */}
                {shot ? (
                  <div className="mt-3 relative">
                    <img src={shot} alt="screenshot" className="max-h-44 w-full rounded-lg border border-slate-200 object-contain bg-slate-50" />
                    <button
                      onClick={() => setShot(null)}
                      className="absolute right-2 top-2 grid h-6 w-6 place-items-center rounded-full bg-slate-900/70 text-white hover:bg-slate-900"
                      title={zh ? '移除截图' : 'remove'}
                    >
                      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M6 6l12 12M18 6L6 18" /></svg>
                    </button>
                  </div>
                ) : (
                  <label
                    onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                    onDragLeave={() => setDragOver(false)}
                    onDrop={onDrop}
                    className={`mt-3 flex cursor-pointer items-center justify-center gap-2 rounded-lg border border-dashed px-3 py-3 text-xs transition ${
                      dragOver ? 'border-sky-400 bg-sky-50 text-sky-700' : 'border-slate-300 text-slate-500 hover:border-slate-400'
                    }`}
                  >
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M14.5 4h-5L8 6H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-4l-1.5-2z" /><circle cx="12" cy="13" r="3.5" />
                    </svg>
                    {zh ? '截图后 Ctrl+V 粘贴,或拖入 / 点此选图' : 'Paste a screenshot (Ctrl+V), drop, or click to pick'}
                    <input type="file" accept="image/*" className="hidden" onChange={(e) => addImage(e.target.files?.[0])} />
                  </label>
                )}

                {error && <p className="mt-2 text-xs text-rose-600">{error}</p>}

                <div className="mt-3 flex items-center justify-between">
                  <span className="text-[11px] text-slate-400">⌘/Ctrl + Enter</span>
                  <div className="flex gap-2">
                    <button onClick={close} className="rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-slate-100">
                      {zh ? '取消' : 'Cancel'}
                    </button>
                    <button
                      onClick={submit}
                      disabled={!text.trim() || sending}
                      className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white transition
                                 hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {sending ? (zh ? '提交中…' : 'Sending…') : (zh ? '发送' : 'Send')}
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}

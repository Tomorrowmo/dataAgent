'use client';

import { useEffect, useState } from 'react';
import { Info, FileText, Download, Eye, History, ChevronDown } from 'lucide-react';
import { api, type AboutInfo } from '@/lib/api';
import { useT } from '@/lib/i18n';

export default function AboutView() {
  const t = useT();
  const [about, setAbout] = useState<AboutInfo | null>(null);
  const [showLog, setShowLog] = useState(false);

  useEffect(() => {
    api.about().then(setAbout).catch(() => {});
  }, []);

  return (
    <div className="p-6 max-w-2xl">
      <h2 className="text-xl font-semibold mb-1">{t('about.title')}</h2>
      <p className="text-sm text-ink-500 mb-6">{t('about.sub')}</p>

      {/* Version */}
      <div className="bg-white rounded-2xl ring-1 ring-ink-200 p-5 mb-5">
        <div className="flex items-center gap-2 mb-3">
          <Info className="w-4 h-4 text-brand-600" />
          <h3 className="font-medium">{t('about.versionCard')}</h3>
        </div>
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <div className="text-base font-semibold text-ink-900">
              {about?.product ?? 'RLab Cortex'}
              {about?.product_note && <span className="ml-1.5 text-xs font-normal text-ink-400">（{about.product_note}）</span>}
            </div>
            <div className="text-xs text-ink-500 mt-0.5">{t('about.version')}</div>
          </div>
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-brand-50 text-brand-700 font-mono text-sm font-semibold ring-1 ring-brand-200">
            v{about?.version ?? '—'}
            <span className="text-[10px] font-sans font-medium px-1 py-0.5 rounded bg-emerald-100 text-emerald-700">{t('about.latest')}</span>
          </span>
        </div>
      </div>

      {/* Changelog */}
      {about?.changelog?.length ? (
        <div className="bg-white rounded-2xl ring-1 ring-ink-200 p-5 mb-5">
          <div className="flex items-center justify-between gap-2 mb-1">
            <div className="flex items-center gap-2">
              <History className="w-4 h-4 text-brand-600" />
              <h3 className="font-medium">{t('about.changelog')}</h3>
            </div>
            <button
              onClick={() => setShowLog((v) => !v)}
              className="flex items-center gap-1 text-xs text-brand-600 hover:text-brand-700 font-medium"
            >
              {showLog ? t('about.hide') : t('about.viewAll')}
              <ChevronDown className={`w-3.5 h-3.5 transition-transform ${showLog ? 'rotate-180' : ''}`} />
            </button>
          </div>

          {(showLog ? about.changelog : about.changelog.slice(0, 1)).map((entry, idx) => (
            <div key={entry.version} className={idx === 0 ? 'mt-3' : 'mt-4 pt-3 border-t border-ink-100'}>
              <div className="flex items-baseline gap-2 flex-wrap">
                <span className="font-mono text-sm font-semibold text-ink-800">v{entry.version}</span>
                {idx === 0 && <span className="text-[10px] px-1 py-0.5 rounded bg-emerald-100 text-emerald-700">{t('about.latest')}</span>}
                <span className="text-xs text-ink-400">{entry.date}</span>
                {entry.title && <span className="text-xs text-ink-600">· {entry.title}</span>}
              </div>
              {entry.summary && <p className="text-xs text-ink-500 mt-1">{entry.summary}</p>}
              <div className="mt-2 space-y-2">
                {Object.entries(entry.changes).map(([bucket, items]) => (
                  <div key={bucket}>
                    <div className="text-xs font-medium text-ink-700 mb-1">{bucket}</div>
                    <ul className="space-y-1">
                      {items.map((it, i) => (
                        <li key={i} className="text-xs text-ink-600 flex gap-1.5 leading-relaxed">
                          <span className="text-brand-400 shrink-0">·</span>
                          <span>{it}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {/* Product documents — view (PDF, inline) + download (docx) */}
      {about?.documents?.length ? (
        <div className="bg-white rounded-2xl ring-1 ring-ink-200 p-5">
          <div className="flex items-center gap-2 mb-3">
            <FileText className="w-4 h-4 text-brand-600" />
            <h3 className="font-medium">{t('about.docs')}</h3>
          </div>
          <div className="space-y-2.5">
            {about.documents.map((d) => (
              <div key={d.key} className="flex items-center gap-3 rounded-xl border border-ink-200 px-3 py-3">
                <span className="w-10 h-10 shrink-0 rounded-lg bg-brand-50 text-brand-600 grid place-items-center">
                  <FileText className="w-5 h-5" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-ink-800 truncate">{d.title}</div>
                  <div className="text-xs text-ink-500 truncate">{d.subtitle}</div>
                </div>
                {d.view && (
                  <a
                    href={d.view}
                    target="_blank"
                    rel="noreferrer"
                    className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium bg-brand-600 text-white hover:bg-brand-700"
                  >
                    <Eye className="w-4 h-4" /> {t('about.view')}
                  </a>
                )}
                <a
                  href={d.download}
                  download={d.filename}
                  className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium border border-ink-200 text-ink-600 hover:bg-ink-50"
                >
                  <Download className="w-4 h-4" /> {t('about.download')}
                </a>
              </div>
            ))}
          </div>
          <p className="text-xs text-ink-400 mt-3">{t('about.docsHint')}</p>
        </div>
      ) : null}
    </div>
  );
}

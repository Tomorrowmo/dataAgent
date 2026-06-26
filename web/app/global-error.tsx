'use client';

import { useEffect } from 'react';

function hardReload() {
  try {
    const u = new URL(window.location.href);
    u.searchParams.set('_cb', String(Date.now()));
    window.location.replace(u.href);
  } catch {
    window.location.reload();
  }
}

// Root-layout-level error boundary. Same ChunkLoadError auto-recovery as
// app/error.tsx (must render its own <html>/<body>).
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const isChunk = error?.name === 'ChunkLoadError' || /Loading chunk|ChunkLoadError|importing a module script failed/i.test(error?.message || '');

  useEffect(() => {
    if (!isChunk || typeof window === 'undefined') return;
    if (new URL(window.location.href).searchParams.has('_cb')) return; // already reloaded once — don't loop
    hardReload();
  }, [isChunk]);

  return (
    <html lang="en">
      <body style={{ margin: 0 }}>
        <div style={{ padding: 24, fontFamily: 'system-ui, sans-serif', textAlign: 'center', marginTop: '18vh', color: '#3f3f46' }}>
          <div style={{ fontSize: 34, marginBottom: 12 }}>{isChunk ? '🔄' : '⚠️'}</div>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>{isChunk ? '正在更新到最新版本…' : '出错了'}</div>
          <div style={{ fontSize: 13, color: '#71717a', marginBottom: 18 }}>
            {isChunk ? '页面有更新，正在重新加载，请稍候。' : String(error?.message || '').slice(0, 200)}
          </div>
          <button
            onClick={() => { try { sessionStorage.removeItem('numetrix.chunkReloaded'); } catch { /* ignore */ } hardReload(); }}
            style={{ padding: '9px 18px', border: 'none', borderRadius: 8, background: '#5d66ab', color: '#fff', fontSize: 14 }}
          >
            刷新
          </button>
        </div>
      </body>
    </html>
  );
}

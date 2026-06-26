'use client';

import { useEffect } from 'react';

// Reload while BYPASSING the browser cache: navigate to the same URL with a
// fresh query param so Safari can't serve the stale cached document. A plain
// location.reload() can keep returning the cached HTML and get stuck.
function hardReload() {
  try {
    const u = new URL(window.location.href);
    u.searchParams.set('_cb', String(Date.now()));
    window.location.replace(u.href);
  } catch {
    window.location.reload();
  }
}

// A ChunkLoadError means the page was cached from an OLDER build whose JS chunks
// no longer exist on the server (after a redeploy). The fix is a single full
// reload to fetch the current HTML + chunks. For any other error, show a simple
// retry. (Replaces Next's generic "Application error" message.)
export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const isChunk = error?.name === 'ChunkLoadError' || /Loading chunk|ChunkLoadError|importing a module script failed/i.test(error?.message || '');

  useEffect(() => {
    if (!isChunk || typeof window === 'undefined') return;
    // Loop guard via the URL (robust even where sessionStorage throws, e.g.
    // Safari private mode): if we already cache-bust-reloaded once (_cb is
    // present), show the message instead of reloading again — never loops.
    if (new URL(window.location.href).searchParams.has('_cb')) return;
    hardReload();
  }, [isChunk]);

  return (
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
  );
}

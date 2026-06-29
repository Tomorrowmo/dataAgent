'use client';

// OIDC callback at /auth/callback — the single redirect_uri the auth center
// supports for this product. This page plays TWO roles in one round-trip:
//
//  1) BRIDGE: the auth center sends the browser here with ?code=&state=. Only
//     /api/* is proxied to the backend, so this frontend page forwards those
//     query params to the backend handler (/api/auth/oidc/callback), which holds
//     the PKCE verifier in its session and does the token exchange.
//  2) RECEIVER: the backend then redirects back here with #token=&next= in the
//     fragment (fragments never hit the server / logs). We store the JWT and go.
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { setToken } from '@/lib/api';

export default function OidcCallbackPage() {
  const router = useRouter();
  const [error, setError] = useState('');

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const search = new URLSearchParams(window.location.search);
    const hashParams = new URLSearchParams(window.location.hash.replace(/^#/, ''));

    // Role 2 — backend bounced back with the app JWT in the fragment.
    const token = hashParams.get('token');
    if (token) {
      setToken(token);
      const next = hashParams.get('next') || '/app';
      window.history.replaceState(null, '', window.location.pathname); // strip the token from the URL
      router.replace(next.startsWith('/') ? next : '/app');
      return;
    }

    // Auth center reported an error (user cancelled, etc.).
    const oidcErr = search.get('error');
    if (oidcErr) {
      router.replace('/login?error=' + encodeURIComponent(search.get('error_description') || oidcErr));
      return;
    }

    // Role 1 — auth center handed us ?code=&state=; forward to the backend, which
    // owns the session/PKCE verifier and completes the exchange.
    if (search.get('code')) {
      window.location.replace('/api/auth/oidc/callback' + window.location.search);
      return;
    }

    // Neither code nor token — nothing to do.
    setError('登录回调缺少凭证');
    const tm = setTimeout(() => router.replace('/login?error=' + encodeURIComponent('登录失败,请重试')), 1200);
    return () => clearTimeout(tm);
  }, [router]);

  return (
    <main className="min-h-screen grid place-items-center bg-ink-50 px-4">
      <div className="text-sm text-ink-500">{error || '正在登录…'}</div>
    </main>
  );
}

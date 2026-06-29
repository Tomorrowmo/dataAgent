'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { api, setToken, OIDC_LOGIN_URL } from '@/lib/api';
import LanguageToggle from '@/components/LanguageToggle';
import { useT } from '@/lib/i18n';

export default function LoginPage() {
  const router = useRouter();
  const t = useT();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [oidc, setOidc] = useState(false);
  // 'probing' until we know whether login is delegated to the auth center; then
  // 'redirecting' (OIDC on → bounce straight to the auth center, no local form
  // shown) or 'local' (OIDC off, or ?local=1 escape hatch → show the form).
  const [phase, setPhase] = useState<'probing' | 'redirecting' | 'local'>('probing');

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    // Surface an error bounced back from the OIDC callback (?error=...).
    const e = params.get('error');
    if (e) setError(e);
    // ?local=1 forces the local email/password form (admin escape hatch when the
    // auth center is down). Otherwise OIDC, when enabled, is the only entry: we
    // redirect immediately so the user never sees this intermediate page.
    const forceLocal = params.has('local') || !!e;

    api.oidcConfig()
      .then((c) => {
        setOidc(c.enabled);
        if (c.enabled && !forceLocal) {
          setPhase('redirecting');
          window.location.replace(OIDC_LOGIN_URL); // straight to the auth center (silent SSO if already signed in)
        } else {
          setPhase('local');
        }
      })
      .catch(() => setPhase('local')); // probe failed → never block login, show the form
  }, []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      const r = await api.login(email, password);
      setToken(r.access_token);
      router.push('/app');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // While probing or bouncing to the auth center, show a minimal splash (no form
  // flash). The auth center handles login; if already signed in it returns at once.
  if (phase !== 'local') {
    return (
      <main className="min-h-screen grid place-items-center bg-ink-50 px-4">
        <p className="text-sm text-ink-500">{t('auth.redirecting')}</p>
      </main>
    );
  }

  return (
    <main className="min-h-screen grid place-items-center bg-ink-50 px-4 relative">
      <div className="absolute top-4 right-4"><LanguageToggle /></div>
      <div className="w-full max-w-sm bg-white rounded-2xl shadow-sm ring-1 ring-ink-200 p-7">
        <Link href="/" className="flex items-center gap-2 font-semibold mb-6">
          <div className="w-7 h-7 rounded-lg bg-brand-600 text-white grid place-items-center text-sm">N</div>
          RLab Cortex
        </Link>
        <h1 className="text-xl font-semibold mb-1">{t('auth.signin.title')}</h1>
        <p className="text-sm text-ink-500 mb-5">{t('auth.welcomeBack')}</p>
        {oidc && (
          <>
            <a href={OIDC_LOGIN_URL} className="btn-primary w-full block text-center mb-3">
              {t('auth.ssoLogin')}
            </a>
            <div className="flex items-center gap-3 my-4 text-xs text-ink-400">
              <span className="h-px flex-1 bg-ink-200" />{t('auth.or')}<span className="h-px flex-1 bg-ink-200" />
            </div>
          </>
        )}
        <form onSubmit={onSubmit} className="space-y-3">
          <input className="input" type="email" placeholder={t('auth.email')} value={email} onChange={(e) => setEmail(e.target.value)} required />
          <input className="input" type="password" placeholder={t('auth.password')} value={password} onChange={(e) => setPassword(e.target.value)} required minLength={6} />
          {error && <div className="text-sm text-red-600">{error}</div>}
          <button className="btn-primary w-full" disabled={busy}>{busy ? t('auth.signing') : t('auth.signinBtn')}</button>
        </form>
        <p className="text-sm text-ink-500 mt-5 text-center">
          {t('auth.newHere')} <Link href="/signup" className="text-brand-600 hover:underline">{t('auth.createOne')}</Link>
        </p>
      </div>
      <style jsx global>{`
        .input { width: 100%; padding: 0.6rem 0.8rem; border: 1px solid #e4e4e7; border-radius: 0.6rem; background: #fff; }
        .input:focus { outline: none; border-color: #3e4ee0; box-shadow: 0 0 0 3px #eaeefe; }
        .btn-primary { background: #2d36c0; color: #fff; padding: 0.6rem 0.8rem; border-radius: 0.6rem; font-weight: 500; }
        .btn-primary:hover { background: #252c97; }
        .btn-primary:disabled { opacity: 0.6; }
      `}</style>
    </main>
  );
}

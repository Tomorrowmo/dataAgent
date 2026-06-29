'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { api, setToken, OIDC_LOGIN_URL } from '@/lib/api';
import LanguageToggle from '@/components/LanguageToggle';
import { useT } from '@/lib/i18n';

export default function SignupPage() {
  const router = useRouter();
  const t = useT();
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  // When OIDC is on, accounts live at the auth center — there is no local signup;
  // we bounce to the auth center (its login page links to registration). ?local=1
  // forces the local signup form.
  const [phase, setPhase] = useState<'probing' | 'redirecting' | 'local'>('probing');

  useEffect(() => {
    const forceLocal = new URLSearchParams(window.location.search).has('local');
    api.oidcConfig()
      .then((c) => {
        if (c.enabled && !forceLocal) {
          setPhase('redirecting');
          window.location.replace(OIDC_LOGIN_URL);
        } else {
          setPhase('local');
        }
      })
      .catch(() => setPhase('local'));
  }, []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      const r = await api.signup(email, password, name);
      setToken(r.access_token);
      router.push('/app');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

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
        <h1 className="text-xl font-semibold mb-1">{t('auth.signup.title')}</h1>
        <p className="text-sm text-ink-500 mb-5">{t('auth.signup.note')}</p>
        <form onSubmit={onSubmit} className="space-y-3">
          <input className="input" type="text" placeholder={t('auth.name')} value={name} onChange={(e) => setName(e.target.value)} />
          <input className="input" type="email" placeholder={t('auth.email')} value={email} onChange={(e) => setEmail(e.target.value)} required />
          <input className="input" type="password" placeholder={t('auth.passwordHint')} value={password} onChange={(e) => setPassword(e.target.value)} required minLength={6} />
          {error && <div className="text-sm text-red-600">{error}</div>}
          <button className="btn-primary w-full" disabled={busy}>{busy ? t('auth.creating') : t('auth.createBtn')}</button>
        </form>
        <p className="text-sm text-ink-500 mt-5 text-center">
          {t('auth.haveAccount')} <Link href="/login" className="text-brand-600 hover:underline">{t('auth.signinBtn')}</Link>
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

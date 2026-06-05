'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { getToken, api } from '@/lib/api';
import { useT } from '@/lib/i18n';

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const t = useT();
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    const tk = getToken();
    if (!tk) {
      router.replace('/login');
      return;
    }
    api.me().then(() => setChecked(true)).catch(() => router.replace('/login'));
  }, [router]);

  if (!checked) return <div className="min-h-screen grid place-items-center text-ink-500">{t('common.loading')}</div>;
  return <>{children}</>;
}

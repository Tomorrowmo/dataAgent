'use client';

import Link from 'next/link';
import { ArrowRight, CheckCircle2, ShieldCheck, Wrench, Sparkles, BookOpen, Activity, BatteryCharging, Cpu } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import LanguageToggle from '@/components/LanguageToggle';
import { useT } from '@/lib/i18n';
import { getToken } from '@/lib/api';

export default function LandingPage() {
  const t = useT();
  const router = useRouter();
  // Already-authenticated users skip the marketing page and go straight to
  // /app. /app's layout re-validates the token — a stale one bounces to
  // /login, which is what we want anyway.  The check runs client-side only
  // (localStorage), so SSR still renders the landing page for crawlers and
  // first-time visitors.
  const [redirecting, setRedirecting] = useState(false);
  useEffect(() => {
    if (getToken()) {
      setRedirecting(true);
      router.replace('/app');
    }
  }, [router]);

  if (redirecting) {
    return (
      <main className="min-h-screen grid place-items-center bg-white">
        <p className="text-sm text-ink-500">{t('auth.redirecting') || '正在进入…'}</p>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-white text-ink-900">
      <header className="sticky top-0 z-30 backdrop-blur bg-white/80 border-b border-ink-200">
        <div className="mx-auto max-w-6xl px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-2 font-semibold">
            <div className="w-7 h-7 rounded-lg bg-brand-600 text-white grid place-items-center text-sm">N</div>
            <span>RLab Cortex</span>
            <span className="text-xs px-2 py-0.5 rounded-full bg-ink-100 text-ink-700 ml-2">{t('nav.beta')}</span>
          </div>
          <nav className="hidden md:flex items-center gap-6 text-sm text-ink-700">
            <a href="#why" className="hover:text-ink-900">{t('nav.why')}</a>
            <a href="#how" className="hover:text-ink-900">{t('nav.how')}</a>
            <a href="#verticals" className="hover:text-ink-900">{t('nav.verticals')}</a>
            <a href="#pricing" className="hover:text-ink-900">{t('nav.pricing')}</a>
          </nav>
          <div className="flex items-center gap-3">
            <LanguageToggle />
            <Link href="/login" className="text-sm text-ink-700 hover:text-ink-900">{t('nav.signin')}</Link>
            <Link href="/signup" className="text-sm px-3 py-1.5 rounded-lg bg-brand-600 text-white hover:bg-brand-700">
              {t('nav.startFree')}
            </Link>
          </div>
        </div>
      </header>

      <section className="relative overflow-hidden mx-auto max-w-6xl px-6 pt-16 pb-20 text-center">
        <div aria-hidden className="pointer-events-none absolute inset-x-0 -top-28 -z-10 flex justify-center">
          <div className="w-[680px] h-[420px] rounded-full bg-brand-100/50 blur-3xl" />
        </div>
        <div className="inline-flex items-center gap-2 text-xs px-3 py-1 rounded-full bg-brand-50 text-brand-700 ring-1 ring-brand-100">
          <ShieldCheck className="w-3.5 h-3.5" />
          {t('brand.tagline')}
        </div>
        <h1 className="mt-5 text-4xl md:text-5xl font-semibold tracking-tight leading-[1.1]">
          {t('hero.headPart1')}<br className="hidden md:block" />
          {t('hero.headPart2')} <span className="text-brand-600">{t('hero.headHighlight')}</span>{t('hero.headPart3')}
        </h1>
        <p className="mt-5 text-lg text-ink-700 max-w-2xl mx-auto">{t('hero.sub')}</p>
        <div className="mt-8 flex items-center justify-center gap-3">
          <Link href="/signup" className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-brand-600 text-white hover:bg-brand-700 font-medium">
            {t('hero.ctaPrimary')} <ArrowRight className="w-4 h-4" />
          </Link>
          <Link href="/login" className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl border border-ink-200 hover:bg-ink-50 font-medium">
            {t('hero.ctaSecondary')}
          </Link>
        </div>
        <div className="mt-6 text-xs text-ink-500">{t('hero.note')}</div>
        <HeroDemo />
      </section>

      <section id="why" className="border-y border-ink-200 bg-ink-50">
        <div className="mx-auto max-w-6xl px-6 py-16">
          <h2 className="text-2xl font-semibold mb-8 text-center">{t('why.title')}</h2>
          <div className="grid md:grid-cols-3 gap-6">
            <Card title={t('why.bad1.t')} body={t('why.bad1.b')} negative />
            <Card title={t('why.bad2.t')} body={t('why.bad2.b')} negative />
            <Card title={t('why.bad3.t')} body={t('why.bad3.b')} negative />
          </div>
          <div className="grid md:grid-cols-3 gap-6 mt-6">
            <Card title={t('why.good1.t')} body={t('why.good1.b')} positive icon={<BookOpen className="w-5 h-5" />} />
            <Card title={t('why.good2.t')} body={t('why.good2.b')} positive icon={<Wrench className="w-5 h-5" />} />
            <Card title={t('why.good3.t')} body={t('why.good3.b')} positive icon={<Sparkles className="w-5 h-5" />} />
          </div>
        </div>
      </section>

      <section id="how" className="mx-auto max-w-6xl px-6 py-20">
        <h2 className="text-2xl font-semibold mb-10 text-center">{t('how.title')}</h2>
        <ol className="grid md:grid-cols-4 gap-6 text-sm">
          {[
            [t('how.step1.t'), t('how.step1.b')],
            [t('how.step2.t'), t('how.step2.b')],
            [t('how.step3.t'), t('how.step3.b')],
            [t('how.step4.t'), t('how.step4.b')],
          ].map(([heading, body], i) => (
            <li key={i} className="rounded-2xl bg-white ring-1 ring-ink-200 p-5">
              <div className="text-xs font-semibold text-brand-600 mb-2">{t('how.stepLabel')} {i + 1}</div>
              <div className="font-medium mb-1">{heading}</div>
              <div className="text-ink-700">{body}</div>
            </li>
          ))}
        </ol>
      </section>

      <section id="verticals" className="border-t border-ink-200 bg-white">
        <div className="mx-auto max-w-6xl px-6 py-20">
          <h2 className="text-2xl font-semibold mb-3 text-center">{t('verts.title')}</h2>
          <p className="text-center text-ink-700 mb-10">{t('verts.sub')}</p>
          <div className="grid md:grid-cols-3 gap-6">
            <VerticalCard
              title={t('verts.battery.t')}
              icon={<BatteryCharging className="w-5 h-5" />}
              chip={t('verts.battery.chip')}
              points={[t('verts.battery.p1'), t('verts.battery.p2'), t('verts.battery.p3')]}
            />
            <VerticalCard
              title={t('verts.cae.t')}
              icon={<Cpu className="w-5 h-5" />}
              chip={t('verts.cae.chip')}
              points={[t('verts.cae.p1'), t('verts.cae.p2'), t('verts.cae.p3')]}
            />
            <VerticalCard
              title={t('verts.nvh.t')}
              icon={<Activity className="w-5 h-5" />}
              chip={t('verts.nvh.chip')}
              points={[t('verts.nvh.p1'), t('verts.nvh.p2'), t('verts.nvh.p3')]}
            />
          </div>
          <p className="text-center text-ink-500 text-sm mt-8">{t('verts.also')}</p>
        </div>
      </section>

      <section id="pricing" className="border-t border-ink-200 bg-ink-50">
        <div className="mx-auto max-w-6xl px-6 py-20">
          <h2 className="text-2xl font-semibold mb-3 text-center">{t('price.title')}</h2>
          <p className="text-center text-ink-700 mb-10">{t('price.sub')}</p>
          <div className="grid md:grid-cols-4 gap-5">
            <PriceCard tier={t('price.free.tier')} price={t('price.free.price')} tagline={t('price.free.tag')}
              features={[t('price.free.f1'), t('price.free.f2'), t('price.free.f3'), t('price.free.f4')]}
              cta={t('price.free.cta')} href="/signup" />
            <PriceCard tier={t('price.pro.tier')} price={t('price.pro.price')} tagline={t('price.pro.tag')}
              features={[t('price.pro.f1'), t('price.pro.f2'), t('price.pro.f3'), t('price.pro.f4')]}
              cta={t('price.pro.cta')} href="/signup?plan=pro" highlight popLabel={t('price.pro.pop')} />
            <PriceCard tier={t('price.team.tier')} price={t('price.team.price')} tagline={t('price.team.tag')}
              features={[t('price.team.f1'), t('price.team.f2'), t('price.team.f3'), t('price.team.f4')]}
              cta={t('price.team.cta')} href="/signup?plan=team" />
            <PriceCard tier={t('price.ent.tier')} price={t('price.ent.price')} tagline={t('price.ent.tag')}
              features={[t('price.ent.f1'), t('price.ent.f2'), t('price.ent.f3'), t('price.ent.f4')]}
              cta={t('price.ent.cta')} href="mailto:sales@numetrix.app" />
          </div>
        </div>
      </section>

      <footer className="border-t border-ink-200 py-10 text-center text-xs text-ink-500">
        © {new Date().getFullYear()} RLab Cortex. {t('footer.tagline')}
      </footer>
    </main>
  );
}

/** A small faux product window in the hero — shows the one thing words can't:
 *  the user asks in plain language, the agent picks a specialized algorithm (RBF)
 *  itself, and it's auditable. This is the whole pitch, made visible. */
function HeroDemo() {
  const t = useT();
  return (
    <div className="mt-14 mx-auto max-w-lg text-left">
      <div className="rounded-2xl bg-white ring-1 ring-ink-200 shadow-xl overflow-hidden">
        <div className="flex items-center gap-1.5 px-3 py-2 border-b border-ink-100 bg-ink-50">
          <span className="w-2.5 h-2.5 rounded-full bg-red-300" />
          <span className="w-2.5 h-2.5 rounded-full bg-amber-300" />
          <span className="w-2.5 h-2.5 rounded-full bg-emerald-300" />
          <span className="ml-2 text-[11px] text-ink-400 font-medium">RLab Cortex</span>
        </div>
        <div className="p-4 space-y-3">
          <div className="flex justify-end">
            <div className="bg-brand-50 text-ink-800 text-sm rounded-2xl rounded-br-sm px-3 py-2 max-w-[82%]">{t('hero.demo.q')}</div>
          </div>
          <div className="flex gap-2">
            <div className="w-7 h-7 rounded-full bg-brand-600 text-white grid place-items-center text-xs font-semibold shrink-0">N</div>
            <div className="flex-1 bg-white ring-1 ring-ink-200 rounded-2xl rounded-bl-sm px-3 py-2.5">
              <div className="inline-flex items-center gap-1.5 text-[11px] text-emerald-700 bg-emerald-50 ring-1 ring-emerald-100 rounded-md px-1.5 py-0.5 mb-2">
                <CheckCircle2 className="w-3 h-3" /> {t('hero.demo.badge')}
              </div>
              <svg viewBox="0 0 260 64" className="w-full h-16">
                <path d="M4,46 C50,8 90,58 130,32 C170,8 210,52 256,22" fill="none" stroke="#3e4ee0" strokeWidth="2.5" strokeLinecap="round" />
                {[[18, 40], [52, 20], [88, 50], [128, 34], [166, 18], [206, 46], [244, 24]].map(([cx, cy], i) => (
                  <circle key={i} cx={cx} cy={cy} r="3" fill="#9aaaf6" />
                ))}
              </svg>
              <div className="text-xs text-ink-500 mt-1.5">{t('hero.demo.caption')}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Card({ title, body, positive, negative, icon }: { title: string; body: string; positive?: boolean; negative?: boolean; icon?: React.ReactNode }) {
  return (
    <div className={`rounded-2xl p-5 ring-1 ${positive ? 'bg-white ring-brand-100' : negative ? 'bg-white ring-ink-200' : 'bg-white ring-ink-200'}`}>
      <div className="flex items-center gap-2 mb-2">
        {icon ?? (positive ? <CheckCircle2 className="w-5 h-5 text-brand-600" /> : <span className="w-2 h-2 rounded-full bg-ink-300" />)}
        <div className="font-medium">{title}</div>
      </div>
      <div className="text-sm text-ink-700">{body}</div>
    </div>
  );
}

function VerticalCard({ title, icon, points, chip }: { title: string; icon: React.ReactNode; points: string[]; chip?: string }) {
  return (
    <div className="rounded-2xl bg-white ring-1 ring-ink-200 p-6">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-brand-50 text-brand-600 grid place-items-center">{icon}</div>
          <div className="font-medium">{title}</div>
        </div>
        {chip && <span className="text-[10px] font-semibold tracking-wide uppercase text-brand-700 bg-brand-50 px-2 py-0.5 rounded-full">{chip}</span>}
      </div>
      <ul className="space-y-1.5 text-sm text-ink-700">
        {points.map((p) => (
          <li key={p} className="flex gap-2"><CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0 text-brand-500" />{p}</li>
        ))}
      </ul>
    </div>
  );
}

function PriceCard({ tier, price, tagline, features, cta, href, highlight, popLabel }: { tier: string; price: string; tagline: string; features: string[]; cta: string; href: string; highlight?: boolean; popLabel?: string }) {
  return (
    <div className={`rounded-2xl p-6 bg-white ${highlight ? 'ring-2 ring-brand-500 shadow-sm' : 'ring-1 ring-ink-200'}`}>
      <div className="flex items-baseline justify-between">
        <div className="font-semibold">{tier}</div>
        {highlight && popLabel && <span className="text-[10px] font-semibold tracking-wide uppercase text-brand-700 bg-brand-50 px-2 py-0.5 rounded-full">{popLabel}</span>}
      </div>
      <div className="mt-3 text-3xl font-semibold">{price}</div>
      <div className="text-xs text-ink-500 mb-4">{tagline}</div>
      <ul className="space-y-1.5 text-sm text-ink-700 mb-5">
        {features.map((f) => (
          <li key={f} className="flex gap-2"><CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0 text-brand-500" />{f}</li>
        ))}
      </ul>
      <Link href={href} className={`inline-flex w-full justify-center px-3 py-2 rounded-lg text-sm font-medium ${highlight ? 'bg-brand-600 text-white hover:bg-brand-700' : 'border border-ink-200 hover:bg-ink-50'}`}>{cta}</Link>
    </div>
  );
}

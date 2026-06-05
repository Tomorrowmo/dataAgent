import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Numetrix — Verifiable data analysis agent',
  description:
    'Numetrix is a verifiable analysis agent for engineers and scientists. Curated algorithms, sandboxed custom code, and LLM-generated tools — all with auditable provenance.',
};

// Next 15's PostCSS pipeline silently no-ops in our standalone/non-standalone
// Docker builds — globals.css is imported here ordinarily but never bundled.
// As a robust workaround we precompile Tailwind into public/styles.css
// (see package.json "css:build" script that runs before `next build`)
// and link it directly. Dev server still uses globals.css via the import
// below — Next's dev server is what Tailwind actually integrates with.
import './globals.css';

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // suppressHydrationWarning: i18n adjusts <html lang> client-side after mount
    // (to the user's detected/stored language); without this, that intended
    // attribute drift would log a hydration warning.
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen antialiased">
        {/* React 19 hoists <link rel="stylesheet"> to <head> automatically,
            but ONLY if `precedence` is set — otherwise it's dropped from the
            output. This is the prebuilt Tailwind stylesheet (see
            package.json "css:build" script which runs before next build). */}
        <link rel="stylesheet" href="/styles.css" precedence="default" />
        {children}
      </body>
    </html>
  );
}

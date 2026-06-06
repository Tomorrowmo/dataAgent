import type { Metadata, Viewport } from 'next';

export const metadata: Metadata = {
  title: 'Numetrix — Verifiable data analysis agent',
  description:
    'Numetrix is a verifiable analysis agent for engineers and scientists. Curated algorithms, sandboxed custom code, and LLM-generated tools — all with auditable provenance.',
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
};

// Next 15's PostCSS pipeline silently no-ops in our standalone/non-standalone
// Docker builds — globals.css is imported here ordinarily but never bundled.
// As a robust workaround we precompile Tailwind into public/styles.css
// (see package.json "css:build" script that runs before `next build`)
// and link it directly. Dev server still uses globals.css via the import
// below — Next's dev server is what Tailwind actually integrates with.
import './globals.css';

// Polyfills for Safari < 15.4 / iOS 15.x, which lack .at() / Object.hasOwn /
// structuredClone / Array.findLast(Index) used across the app + its deps. Runs
// as a classic inline script BEFORE any app chunk so the methods exist by the
// time React code calls them. (The remark-gfm lookbehind regex — a *parse*-time
// failure that can't be polyfilled — is handled separately via Markdown.tsx.)
const OLD_SAFARI_POLYFILLS = `!function(){function d(o,n,f){if(!o[n]){try{Object.defineProperty(o,n,{value:f,writable:true,configurable:true})}catch(e){o[n]=f}}}
d(Array.prototype,'at',function(i){i=Math.trunc(i)||0;if(i<0)i+=this.length;return(i<0||i>=this.length)?undefined:this[i]});
d(String.prototype,'at',function(i){i=Math.trunc(i)||0;if(i<0)i+=this.length;return(i<0||i>=this.length)?undefined:this[i]});
d(Array.prototype,'findLast',function(c,t){for(var i=this.length-1;i>=0;i--){if(c.call(t,this[i],i,this))return this[i]}});
d(Array.prototype,'findLastIndex',function(c,t){for(var i=this.length-1;i>=0;i--){if(c.call(t,this[i],i,this))return i}return -1});
if(!Object.hasOwn){d(Object,'hasOwn',function(o,k){return Object.prototype.hasOwnProperty.call(o,k)})}
if(typeof structuredClone==='undefined'){try{window.structuredClone=function(v){return v==null?v:JSON.parse(JSON.stringify(v))}}catch(e){}}}();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // suppressHydrationWarning: i18n adjusts <html lang> client-side after mount
    // (to the user's detected/stored language); without this, that intended
    // attribute drift would log a hydration warning.
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen antialiased">
        {/* Inline + synchronous so the polyfills are installed before any app
            chunk executes (see OLD_SAFARI_POLYFILLS above). */}
        <script dangerouslySetInnerHTML={{ __html: OLD_SAFARI_POLYFILLS }} />
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

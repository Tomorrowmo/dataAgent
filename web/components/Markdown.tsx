'use client';

import React, { useEffect, useState } from 'react';
import ReactMarkdown, { type Options } from 'react-markdown';

type RemarkPlugins = NonNullable<Options['remarkPlugins']>;

// remark-gfm ships an autolink regex with a lookbehind ((?<=…)) that is a
// PARSE-time SyntaxError on Safari < 16.4 (e.g. iOS 15) — a static import would
// brick the whole bundle there. So we render with CommonMark react-markdown
// SYNCHRONOUSLY (no lookbehind → works on every engine, keeps the typewriter
// streaming AND keeps output structured: headings/bold/lists/code/links), and
// only LAZY-load remark-gfm to upgrade to GFM tables/strikethrough on engines
// that actually support the syntax. Old Safari never fetches gfm and simply
// stays on CommonMark — structured, never raw markdown text.
let gfmSupported = false;
try {
  // eslint-disable-next-line no-new
  new RegExp('(?<=a)b');
  gfmSupported = true;
} catch {
  /* Safari < 16.4 — leave gfmSupported false */
}

// Module-level cache so remark-gfm is fetched at most once per session.
let cachedGfm: RemarkPlugins | null = null;
let gfmLoad: Promise<void> | null = null;

class MarkdownBoundary extends React.Component<
  { fallback: React.ReactNode; children: React.ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

function Rendered({ children }: { children: string }) {
  const [plugins, setPlugins] = useState<RemarkPlugins>(cachedGfm ?? []);

  useEffect(() => {
    if (!gfmSupported || cachedGfm) return;
    if (!gfmLoad) {
      gfmLoad = import('remark-gfm').then((m) => {
        cachedGfm = [m.default];
      });
    }
    gfmLoad.then(() => {
      if (cachedGfm) setPlugins(cachedGfm);
    });
  }, []);

  return <ReactMarkdown remarkPlugins={plugins}>{children}</ReactMarkdown>;
}

export default function Markdown({ children }: { children: string }) {
  return (
    <MarkdownBoundary fallback={<div style={{ whiteSpace: 'pre-wrap' }}>{children}</div>}>
      <Rendered>{children}</Rendered>
    </MarkdownBoundary>
  );
}

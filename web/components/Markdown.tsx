'use client';

import React from 'react';
import dynamic from 'next/dynamic';

// react-markdown + remark-gfm bundle an autolink regex with a lookbehind
// ((?<=…)) that Safari < 16.4 (e.g. iOS 15.x) cannot parse — the SyntaxError
// fails the whole JS chunk and used to crash /app into the "正在更新到最新版本"
// error screen on old iPhones. Two layered defenses:
//   1. Load the renderer from a LAZY chunk (MarkdownInner) so that regex is not
//      in the main bundle — old Safari can then boot and use the rest of the app.
//   2. Wrap it in a boundary that falls back to plain text if that lazy chunk
//      itself fails to load/parse, so markdown degrades gracefully instead of
//      taking down the surrounding UI. Modern browsers are unaffected.
const MarkdownInner = dynamic(() => import('./MarkdownInner'), {
  ssr: false,
  loading: () => null,
});

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

export default function Markdown({ children }: { children: string }) {
  return (
    <MarkdownBoundary fallback={<div style={{ whiteSpace: 'pre-wrap' }}>{children}</div>}>
      <MarkdownInner>{children}</MarkdownInner>
    </MarkdownBoundary>
  );
}

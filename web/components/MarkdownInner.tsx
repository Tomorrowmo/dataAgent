'use client';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

// Isolated into its own module so react-markdown + remark-gfm land in a SEPARATE
// lazy chunk (loaded via Markdown.tsx), not the main /app bundle. remark-gfm
// ships an autolink regex with a lookbehind ((?<=…)) that SyntaxErrors on
// Safari < 16.4 (e.g. iOS 15); keeping it out of the initial bundle is what lets
// old Safari boot the app at all.
export default function MarkdownInner({ children }: { children: string }) {
  return <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>;
}

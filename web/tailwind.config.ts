import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          // Softened (was a vivid #3e4ee0 indigo) → a gentler, lower-chroma
          // periwinkle indigo. Same family, much calmer overall.
          50: '#f7f8fc',
          100: '#eef0f9',
          200: '#dce0f2',
          300: '#c0c6e8',
          400: '#9aa3d8',
          500: '#7780c6',
          600: '#5d66ab',
          700: '#4b5289',
          800: '#3e436e',
          900: '#363a5b',
        },
        ink: {
          50: '#fafafa',
          100: '#f4f4f5',
          200: '#e4e4e7',
          300: '#d4d4d8',
          400: '#a1a1aa',
          500: '#71717a',
          600: '#52525b',
          700: '#3f3f46',
          800: '#27272a',
          900: '#18181b',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
    },
  },
  plugins: [],
};
export default config;

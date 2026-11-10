import type { Config } from 'tailwindcss';

// ── RLab Cortex design tokens (see docs/ui-redesign-proposal.html, 02 设计规范) ──
// Engineering-tool look: cool neutral greys, one ink-blue brand colour, and
// colour reserved for STATE only (red = error, amber = warning, green = pass,
// blue = in progress). AI-generated content carries no colour of its own — it
// is marked with a dashed outline + "AI" label (components/ui.tsx <AiTag>).

// Cool neutral grey (hue ≈ 215°, very low chroma). Text steps checked on white:
// 900 17.6:1 · 700 11.3:1 · 600 7.2:1 · 500 5.0:1.
const neutral = {
  50: '#f8f9fa',   // sunken: table headers, code wells
  100: '#f3f4f6',  // base: app background, rail, side panels
  150: '#eceef1',  // hover / inner dividers
  200: '#dfe2e6',  // line
  300: '#c6cbd1',  // line-strong: inputs, control borders
  400: '#a0a6ae',  // disabled text, placeholder
  500: '#69707a',  // auxiliary text
  600: '#525861',  // secondary text
  700: '#363b42',  // body text
  800: '#262a30',
  900: '#16191d',  // primary text
  950: '#0e1013',
};

// Ink blue — primary actions, current selection, links, focus.
const brand = {
  50: '#eef2f6',
  100: '#dce4ec',
  200: '#b9c8d8',
  300: '#8ea6be',
  400: '#5f7e9d',
  500: '#3f6285',
  600: '#2b4c6f',
  700: '#213c59',
  800: '#1a3047',
  900: '#14253a',
  950: '#0d1826',
};

// State colours (muted, print-safe).
const success = {
  50: '#eef6f1', 100: '#dcede2', 200: '#bcdcc8', 300: '#93c4a5', 400: '#5fa47a',
  500: '#3d8a5c', 600: '#2f7d4f', 700: '#22603b', 800: '#1b4d30', 900: '#153d26', 950: '#0c2416',
};
const warning = {
  50: '#fbf6e8', 100: '#f7edcf', 200: '#eedc9f', 300: '#e3c566', 400: '#d6a92f',
  500: '#c8900e', 600: '#a8770a', 700: '#7a5300', 800: '#624300', 900: '#4d3500', 950: '#2e2000',
};
const danger = {
  50: '#fbefee', 100: '#f7dfdc', 200: '#edc0bb', 300: '#e0978f', 400: '#cf6a60',
  500: '#c04a40', 600: '#b4372f', 700: '#8f2a23', 800: '#73221c', 900: '#5c1b17', 950: '#360f0d',
};

const config: Config = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        brand,
        ink: neutral,
        success,
        warning,
        danger,
        // 提示文字 (改进清单-5 · 8, 方案 A): blue-grey, set apart from neutral body text.
        hint: '#5b7089',
        // Remap Tailwind's stock palettes so the existing component classes
        // follow the token rules without a 400-site rewrite:
        //   violet / purple / fuchsia (old "AI" accent) → neutral: AI gets no colour
        //   indigo / sky / blue / cyan                  → brand
        //   emerald / green                             → success
        //   amber / yellow / orange                     → warning
        //   red / rose                                  → danger
        //   slate / gray / zinc                         → neutral
        violet: neutral, purple: neutral, fuchsia: neutral,
        indigo: brand, sky: brand, blue: brand, cyan: brand,
        emerald: success, green: success,
        amber: warning, yellow: warning, orange: warning,
        red: danger, rose: danger,
        slate: neutral, gray: neutral, zinc: neutral,
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', '"PingFang SC"', '"Microsoft YaHei"', '"Noto Sans SC"', '"Source Han Sans SC"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'SFMono-Regular', 'Consolas', '"PingFang SC"', '"Microsoft YaHei"', 'monospace'],
      },
      // 2 tags · 4 controls · 6 sheets/modals. Round only for status dots / full.
      borderRadius: {
        sm: '2px',
        DEFAULT: '4px',
        md: '4px',
        lg: '4px',
        xl: '6px',
        '2xl': '6px',
        '3xl': '8px',
      },
      // Three elevation levels: page (lines only) · popover · modal.
      boxShadow: {
        sm: '0 1px 0 rgba(22, 25, 29, 0.04)',
        DEFAULT: '0 1px 2px rgba(22, 25, 29, 0.06)',
        md: '0 4px 12px rgba(22, 25, 29, 0.08)',
        lg: '0 4px 12px rgba(22, 25, 29, 0.08)',
        xl: '0 12px 32px rgba(22, 25, 29, 0.16)',
        '2xl': '0 12px 32px rgba(22, 25, 29, 0.16)',
      },
      transitionDuration: { DEFAULT: '120ms' },
      transitionTimingFunction: { DEFAULT: 'cubic-bezier(0, 0, 0.2, 1)' },
    },
  },
  plugins: [],
};
export default config;

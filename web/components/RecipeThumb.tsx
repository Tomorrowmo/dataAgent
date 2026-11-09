// Small schematic previews for the home-page analysis cards: what each kind of
// analysis gives you, at a glance. Pure SVG, chart-palette colours.
const C1 = '#2e5f8a', C2 = '#d0702e', C3 = '#4c8c5e', C4 = '#b5474e', MUTED = '#a0a6ae', AX = '#c6cbd1', TXT = '#69707a';

export default function RecipeThumb({ id }: { id: string }) {
  const common = { className: 'block w-full h-auto bg-ink-50 border-b border-ink-150', viewBox: '0 0 300 86', preserveAspectRatio: 'none' as const, 'aria-hidden': true };
  switch (id) {
    case 'smooth':
      return (
        <svg {...common}>
          <polyline fill="none" stroke={MUTED} strokeWidth="1.2"
            points="10,50 18,36 26,58 34,30 42,55 50,26 58,48 66,20 74,44 82,24 90,50 98,32 106,56 114,30 122,52 130,36 138,60 146,38 154,58 162,40 170,62 178,44 186,60 194,46 202,64 210,48 218,62 226,50 234,66 242,52 250,64 258,56 266,68 274,58 282,66 290,60" />
          <path d="M10,44 C60,30 100,28 150,46 S240,64 290,62" fill="none" stroke={C1} strokeWidth="2.2" />
        </svg>
      );
    case 'drivers':
      return (
        <svg {...common}>
          <g fill={C1}>
            <rect x="34" y="14" width="226" height="10" rx="1" /><rect x="34" y="30" width="156" height="10" rx="1" opacity=".85" />
            <rect x="34" y="46" width="88" height="10" rx="1" opacity=".7" /><rect x="34" y="62" width="40" height="10" rx="1" opacity=".55" />
          </g>
          <g fontSize="9" fill={TXT} fontFamily="IBM Plex Mono, monospace"><text x="10" y="22">x1</text><text x="10" y="38">x3</text><text x="10" y="54">x2</text><text x="10" y="70">x4</text></g>
        </svg>
      );
    case 'fit':
      return (
        <svg {...common}>
          <g fill={C1} opacity=".75">
            {[[30, 70], [55, 62], [80, 60], [105, 50], [130, 47], [155, 40], [180, 36], [205, 30], [230, 24], [255, 22], [280, 14]].map(([x, y]) => <circle key={x} cx={x} cy={y} r="3" />)}
          </g>
          <path d="M20,72 C100,56 180,34 290,14" fill="none" stroke={C2} strokeWidth="2" strokeDasharray="6 4" />
          <text x="200" y="78" fontSize="10" fill="#525861" fontFamily="IBM Plex Mono, monospace">R² = 0.97</text>
        </svg>
      );
    case 'outliers':
      return (
        <svg {...common}>
          <rect x="10" y="30" width="280" height="26" fill="#eef2f6" />
          <g fill={TXT}>{[[30, 44], [52, 40], [74, 47], [96, 42], [140, 45], [162, 39], [206, 46], [228, 41], [272, 44]].map(([x, y]) => <circle key={x} cx={x} cy={y} r="2.5" />)}</g>
          <g fill={C4}><circle cx="118" cy="12" r="4" /><circle cx="184" cy="76" r="4" /><circle cx="250" cy="14" r="4" /></g>
        </svg>
      );
    case 'corr': {
      const m = [[C1, '#5f7e9d', '#dce4ec', '#f2c9a8'], ['#5f7e9d', C1, '#b9c8d8', '#eef2f6'], ['#dce4ec', '#b9c8d8', C1, C2], ['#f2c9a8', '#eef2f6', C2, C1]];
      return (
        <svg {...common}>
          <g transform="translate(112,6)">
            {m.map((row, r) => row.map((c, k) => <rect key={`${r}-${k}`} x={k * 19} y={r * 19} width="18" height="18" fill={c} />))}
          </g>
        </svg>
      );
    }
    case 'pca':
      return (
        <svg {...common}>
          <path d="M20,76 H290 M20,76 V8" stroke={AX} strokeWidth="1" fill="none" />
          <g fill={C1} opacity=".8">{[[70, 30], [82, 24], [76, 40], [90, 34], [64, 22]].map(([x, y]) => <circle key={x} cx={x} cy={y} r="3" />)}</g>
          <g fill={C2} opacity=".85">{[[160, 58], [172, 66], [150, 64], [166, 52], [178, 58]].map(([x, y]) => <circle key={x} cx={x} cy={y} r="3" />)}</g>
          <g fill={C3} opacity=".85">{[[230, 26], [244, 32], [238, 18], [252, 24]].map(([x, y]) => <circle key={x} cx={x} cy={y} r="3" />)}</g>
          <g fontSize="9" fill={TXT} fontFamily="IBM Plex Mono, monospace"><text x="262" y="72">PC1</text><text x="24" y="16">PC2</text></g>
        </svg>
      );
    default:
      return <svg {...common} />;
  }
}

/** The "you'll get a result like this" sample — shown until the user has a result of their own. */
export function SampleResultChart() {
  return (
    <svg viewBox="0 0 520 150" className="block w-full h-auto" role="img" aria-label="示例：两条放电曲线，第 50 圈略向左收缩">
      <g stroke="#eceef1"><path d="M40 20H510M40 55H510M40 90H510" /></g>
      <path d="M40 125H510M40 15V125" stroke={AX} fill="none" />
      <path d="M40 22 C110 36 190 44 280 48 S440 60 480 86 S500 112 508 122" fill="none" stroke={C1} strokeWidth="2" />
      <path d="M40 24 C108 38 186 47 272 51 S420 64 460 90 S484 114 490 122" fill="none" stroke={C2} strokeWidth="2" strokeDasharray="6 4" />
      <g fontSize="10" fill={TXT} fontFamily="IBM Plex Mono, monospace">
        <text x="34" y="14" textAnchor="end">(V)</text><text x="34" y="26" textAnchor="end">4.2</text><text x="34" y="128" textAnchor="end">3.0</text>
        <text x="508" y="142" textAnchor="end">容量 (Ah)</text>
      </g>
      <g fontSize="11" fill="#363b42">
        <path d="M360 18h14" stroke={C1} strokeWidth="2" /><text x="378" y="22">第 1 圈</text>
        <path d="M428 18h14" stroke={C2} strokeWidth="2" strokeDasharray="4 3" /><text x="446" y="22">第 50 圈</text>
      </g>
    </svg>
  );
}

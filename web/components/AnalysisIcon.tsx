// Line icons for analysis recipes / suggestion slugs / starters — replaces the
// emoji (🌊🎯📈🚨…) that read as "AI product". 16px, stroke 1.5, one colour.
import {
  Waves, Target, TrendingUp, ScanSearch, Grid3x3, Minimize2, MessageSquareText,
  BarChart3, Box, Eraser, Activity, Boxes, Spline, Circle, Shuffle, Wrench, Code2,
} from 'lucide-react';
import { AiMark } from '@/components/ui';

const MAP: Record<string, typeof Waves> = {
  smooth: Waves,
  drivers: Target,
  fit: TrendingUp,
  outliers: ScanSearch,
  corr: Grid3x3,
  pca: Minimize2,
  custom: MessageSquareText,
  chart: BarChart3,
  mesh3d: Box,
  clean: Eraser,
  map: Shuffle,
  structure: Wrench,
  'custom-algo': Code2,
  // starters (keyed by their sample dataset)
  '示例·参数优化DOE': Target,
  '示例·散点曲线': Spline,
  '示例·周期信号': Activity,
  '示例·分组数据': Boxes,
};

/** Algorithm-family icon for the library / flow palette rows. */
export function IntentIcon({ intent, className = 'w-3.5 h-3.5' }: { intent: string; className?: string }) {
  const key = ({ clean: 'clean', smooth: 'smooth', feature: 'outliers', map: 'map', fit: 'fit', reduce: 'pca', structure: 'structure', custom: 'custom-algo' } as Record<string, string>)[intent] ?? 'other';
  const Icon = MAP[key] ?? Circle;
  return <Icon className={className} strokeWidth={1.5} aria-hidden="true" />;
}

export default function AnalysisIcon({ id, className = 'w-4 h-4' }: { id: string; className?: string }) {
  if (id === 'explain') return <AiMark />;
  const Icon = MAP[id] ?? Circle;
  return <Icon className={className} strokeWidth={1.5} aria-hidden="true" />;
}

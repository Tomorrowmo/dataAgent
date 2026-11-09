// Line icons for analysis recipes / suggestion slugs / starters — replaces the
// emoji (🌊🎯📈🚨…) that read as "AI product". 16px, stroke 1.5, one colour.
import {
  Waves, Target, TrendingUp, ScanSearch, Grid3x3, Minimize2, MessageSquareText,
  BarChart3, Box, Eraser, Activity, Boxes, Spline, Circle,
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
  // starters (keyed by their sample dataset)
  '示例·参数优化DOE': Target,
  '示例·散点曲线': Spline,
  '示例·周期信号': Activity,
  '示例·分组数据': Boxes,
};

export default function AnalysisIcon({ id, className = 'w-4 h-4' }: { id: string; className?: string }) {
  if (id === 'explain') return <AiMark />;
  const Icon = MAP[id] ?? Circle;
  return <Icon className={className} strokeWidth={1.5} aria-hidden="true" />;
}

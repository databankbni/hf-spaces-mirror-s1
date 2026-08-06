import {
  ListChecksIcon,
  TrendingUpIcon,
  BotIcon,
  FileTextIcon,
  MessageSquareIcon,
  PackageIcon,
  BarChart2Icon,
  UsersIcon,
  type LucideIcon,
} from 'lucide-react';
import type { ViewComponentProps, MetricDef } from '../types';

const iconMap: Record<string, LucideIcon> = {
  'list-checks': ListChecksIcon,
  'trending-up': TrendingUpIcon,
  'bot': BotIcon,
  'file-text': FileTextIcon,
  'message-square': MessageSquareIcon,
  'package': PackageIcon,
  'bar-chart': BarChart2Icon,
  'users': UsersIcon,
};

const colorMap: Record<string, { bg: string; text: string; icon: string }> = {
  green: { bg: 'border-foreground/10', text: 'text-foreground/80', icon: 'text-foreground/50' },
  blue: { bg: 'border-foreground/10', text: 'text-foreground/80', icon: 'text-foreground/50' },
  amber: { bg: 'border-foreground/10', text: 'text-foreground/80', icon: 'text-foreground/50' },
  red: { bg: 'border-foreground/10', text: 'text-foreground/80', icon: 'text-foreground/50' },
  violet: { bg: 'border-foreground/10', text: 'text-foreground/80', icon: 'text-foreground/50' },
  gray: { bg: 'border-foreground/10', text: 'text-foreground/60', icon: 'text-foreground/40' },
};

export default function StatView({ data, options }: ViewComponentProps) {
  const metrics = options?.metrics || inferMetrics(data);

  if (metrics.length === 0) {
    return <div className="py-8 text-center text-sm text-muted-foreground">{options?.empty_text || '暂无统计数据'}</div>;
  }

  return (
    <div className="grid gap-4" style={{ gridTemplateColumns: `repeat(${Math.min(metrics.length, 4)}, 1fr)` }}>
      {metrics.map((metric, i) => {
        const value = resolveMetricValue(metric, data);
        const colors = colorMap[metric.color || 'blue'] || colorMap.blue;
        const IconComp = metric.icon ? (iconMap[metric.icon] || BarChart2Icon) : BarChart2Icon;

        return (
          <div key={i} className="rounded-xl border border-border bg-card p-4">
            <div className="flex items-center gap-3">
              <div className={`flex h-10 w-10 items-center justify-center rounded-lg ${colors.bg}`}>
                <IconComp className={`w-5 h-5 ${colors.icon}`} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-xs text-muted-foreground">{metric.label}</div>
                <div className={`text-xl font-bold tabular-nums ${colors.text}`}>
                  {metric.prefix || ''}{String(value)}{metric.suffix || ''}
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function resolveMetricValue(metric: MetricDef, data: unknown): unknown {
  if (!data || typeof data !== 'object') return '-';
  const obj = data as Record<string, unknown>;
  return obj[metric.value_field] ?? '-';
}

function inferMetrics(data: unknown): MetricDef[] {
  if (!data || typeof data !== 'object') return [];
  const obj = data as Record<string, unknown>;

  // 如果 data 有 metrics 字段（内联格式）
  if (Array.isArray(obj.metrics)) {
    return obj.metrics.map((m: Record<string, unknown>) => ({
      label: String(m.label || ''),
      value_field: String(m.value_field ?? m.value ?? ''),
      prefix: m.prefix as string | undefined,
      suffix: m.suffix as string | undefined,
      icon: m.icon as string | undefined,
      color: m.color as string | undefined,
    }));
  }

  // 自动推断：把数字字段作为指标
  return Object.entries(obj)
    .filter(([, v]) => typeof v === 'number')
    .slice(0, 4)
    .map(([key, value]) => ({
      label: key,
      value_field: key,
      suffix: typeof value === 'number' && value < 1 ? '%' : undefined,
    }));
}

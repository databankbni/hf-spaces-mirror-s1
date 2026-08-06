import type { ViewComponentProps } from '../types';

export default function TimelineView({ data, options }: ViewComponentProps) {
  const items = Array.isArray(data) ? data : data ? [data] : [];
  const timeField = options?.time_field || 'created_at' || 'time' || 'date';
  const eventField = options?.event_field || 'title' || 'name' || 'event';

  if (items.length === 0) {
    return <div className="py-8 text-center text-sm text-muted-foreground">{options?.empty_text || '暂无数据'}</div>;
  }

  // 按时间排序
  const sorted = [...items].sort((a, b) => {
    const ta = getTimeValue(a, timeField);
    const tb = getTimeValue(b, timeField);
    return (tb ?? 0) - (ta ?? 0);
  });

  return (
    <div className="relative pl-6">
      {/* 竖线 */}
      <div className="absolute left-2.5 top-2 bottom-2 w-px bg-border" />

      <div className="flex flex-col gap-4">
        {sorted.map((item, i) => {
          const row = item as Record<string, unknown>;
          const time = row[timeField] ? formatTime(String(row[timeField])) : '';
          const event = String(row[eventField] || row.title || row.name || `Event ${i + 1}`);
          const description = row.description ? String(row.description) : '';

          return (
            <div key={i} className="relative">
              {/* 节点圆点 */}
              <div className="absolute -left-3.5 top-1.5 h-2 w-2 rounded-full bg-primary ring-4 ring-background" />

              <div className="rounded-xl border border-border bg-card p-3">
                {time && <div className="text-xs text-muted-foreground mb-1">{time}</div>}
                <div className="text-sm font-medium text-foreground">{event}</div>
                {description && <p className="mt-1 text-xs text-muted-foreground line-clamp-2">{description}</p>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function getTimeValue(item: unknown, field: string): number | null {
  const row = item as Record<string, unknown>;
  const val = row[field];
  if (!val) return null;
  const date = new Date(String(val));
  return isNaN(date.getTime()) ? null : date.getTime();
}

function formatTime(str: string): string {
  try {
    const date = new Date(str);
    if (isNaN(date.getTime())) return str;
    const pad = (n: number) => n.toString().padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  } catch {
    return str;
  }
}

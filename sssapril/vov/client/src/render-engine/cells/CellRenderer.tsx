import { useNavigate } from 'react-router-dom';
import type { CellRenderConfig } from '../types';
import { resolveTemplate } from '../DataTransform';

// ── Badge 渲染 ──

const colorClasses: Record<string, string> = {
  green: 'border-foreground/20 text-foreground/70',
  blue: 'border-foreground/20 text-foreground/70',
  red: 'border-foreground/20 text-foreground/70',
  amber: 'border-foreground/20 text-foreground/70',
  gray: 'border-foreground/15 text-foreground/50',
  violet: 'border-foreground/20 text-foreground/70',
  rose: 'border-foreground/20 text-foreground/70',
  emerald: 'border-foreground/20 text-foreground/70',
};

export function BadgeCell({ value, config }: { value: unknown; config: CellRenderConfig }) {
  const strVal = String(value ?? '');
  const mapping = config.badge_map?.[strVal];
  const colorClass = mapping ? (colorClasses[mapping.color] || colorClasses.gray) : colorClasses.gray;
  const label = mapping?.label || strVal;

  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${colorClass}`}>
      {label}
    </span>
  );
}

// ── Link 渲染 ──

export function LinkCell({ value, config, row }: { value: unknown; config: CellRenderConfig; row?: Record<string, unknown> }) {
  const navigate = useNavigate();
  const label = String(value ?? '');
  const href = config.href_template && row
    ? resolveTemplate(config.href_template, row as Record<string, string | undefined>)
    : '#';

  return (
    <button
      onClick={() => navigate(href)}
      className="text-primary underline underline-offset-4 hover:opacity-80 text-left"
    >
      {label}
    </button>
  );
}

// ── Progress 渲染 ──

export function ProgressCell({ value, config, row }: { value: unknown; config: CellRenderConfig; row?: Record<string, unknown> }) {
  const current = Number(value) || 0;
  const max = config.max_field && row ? Number(row[config.max_field]) || 100 : 100;
  const pct = Math.min(100, Math.max(0, (current / max) * 100));

  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 rounded-full bg-muted overflow-hidden">
        <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-muted-foreground tabular-nums">{Math.round(pct)}%</span>
    </div>
  );
}

// ── Date 渲染 ──

export function DateCell({ value, config }: { value: unknown; config: CellRenderConfig }) {
  const strVal = String(value ?? '');
  if (!strVal) return <span className="text-muted-foreground">-</span>;

  try {
    const date = new Date(strVal);
    if (isNaN(date.getTime())) return <span>{strVal}</span>;

    const format = config.format || 'YYYY-MM-DD';
    const pad = (n: number) => n.toString().padStart(2, '0');
    const replacements: Record<string, string> = {
      'YYYY': date.getFullYear().toString(),
      'MM': pad(date.getMonth() + 1),
      'DD': pad(date.getDate()),
      'HH': pad(date.getHours()),
      'mm': pad(date.getMinutes()),
      'ss': pad(date.getSeconds()),
    };
    let result = format;
    for (const [token, val] of Object.entries(replacements)) {
      result = result.replace(token, val);
    }
    return <span className="tabular-nums text-muted-foreground">{result}</span>;
  } catch {
    return <span>{strVal}</span>;
  }
}

// ── 通用单元格渲染分发 ──

export function CellRenderer({
  value,
  config,
  row,
}: {
  value: unknown;
  config?: CellRenderConfig;
  row?: Record<string, unknown>;
}) {
  if (!config || config.type === 'text') {
    return <span>{String(value ?? '')}</span>;
  }

  switch (config.type) {
    case 'badge':
      return <BadgeCell value={value} config={config} />;
    case 'link':
      return <LinkCell value={value} config={config} row={row} />;
    case 'progress':
      return <ProgressCell value={value} config={config} row={row} />;
    case 'date':
      return <DateCell value={value} config={config} />;
    default:
      return <span>{String(value ?? '')}</span>;
  }
}

import type { ViewComponentProps } from '../types';
import { CellRenderer } from '../cells/CellRenderer';

export default function CardView({ data, options }: ViewComponentProps) {
  const items = Array.isArray(data) ? data : data ? [data] : [];
  const gridCols = options?.grid_cols ?? 3;
  const cardFields = options?.card_fields;

  if (items.length === 0) {
    return <div className="py-8 text-center text-sm text-muted-foreground">{options?.empty_text || '暂无数据'}</div>;
  }

  return (
    <div className="grid gap-4" style={{ gridTemplateColumns: `repeat(${gridCols}, 1fr)` }}>
      {items.map((item, i) => {
        const row = item as Record<string, unknown>;

        if (cardFields && cardFields.length > 0) {
          const titleField = cardFields[0];
          const otherFields = cardFields.slice(1);

          return (
            <div key={i} className="rounded-xl border border-border bg-card p-4 hover:shadow-md transition-shadow">
              <div className="text-sm font-semibold text-foreground mb-2">
                <CellRenderer value={row[titleField.field]} config={titleField.render} row={row} />
              </div>
              <div className="flex flex-col gap-1.5">
                {otherFields.map(field => (
                  <div key={field.field} className="flex items-center justify-between gap-2">
                    {field.label && <span className="text-xs text-muted-foreground">{field.label}</span>}
                    <CellRenderer value={row[field.field]} config={field.render} row={row} />
                  </div>
                ))}
              </div>
            </div>
          );
        }

        // 自动推断：第一个字符串字段做标题，其余做内容
        const entries = Object.entries(row).filter(([, v]) => v != null);
        const titleEntry = entries.find(([, v]) => typeof v === 'string' && v.length > 0) || entries[0];
        const otherEntries = entries.filter(e => e !== titleEntry).slice(0, 4);

        return (
          <div key={i} className="rounded-xl border border-border bg-card p-4 hover:shadow-md transition-shadow">
            <div className="text-sm font-semibold text-foreground mb-2">{String(titleEntry?.[1] ?? '')}</div>
            <div className="flex flex-col gap-1">
              {otherEntries.map(([key, val]) => (
                <div key={key} className="flex items-center justify-between gap-2">
                  <span className="text-xs text-muted-foreground">{key}</span>
                  <span className="text-xs text-foreground truncate max-w-32">{String(val)}</span>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

import type { ViewComponentProps } from '../types';
import { CellRenderer } from '../cells/CellRenderer';

export default function ListView({ data, options }: ViewComponentProps) {
  const items = Array.isArray(data) ? data : data ? [data] : [];
  const layout = options?.layout || 'vertical';
  const isGrid = layout === 'grid';

  if (items.length === 0) {
    return <div className="py-8 text-center text-sm text-muted-foreground">{options?.empty_text || '暂无数据'}</div>;
  }

  return (
    <div className={isGrid ? 'grid grid-cols-2 gap-3' : 'flex flex-col gap-2'}>
      {items.map((item, i) => {
        // 处理简单字符串项（如字符串数组）
        if (typeof item === 'string') {
          return (
            <div key={i} className="rounded-xl border border-border bg-card px-4 py-3 hover:bg-accent/40 transition-colors">
              <span className="text-sm text-foreground">{item}</span>
            </div>
          );
        }

        const row = item as Record<string, unknown>;
        const cardFields = options?.card_fields;

        if (options?.item_template) {
          const text = replaceTemplate(options.item_template, row);
          return (
            <div key={i} className="rounded-xl border border-border bg-card px-4 py-3 hover:bg-accent/40 transition-colors">
              <span className="text-sm text-foreground">{text}</span>
            </div>
          );
        }

        if (cardFields && cardFields.length > 0) {
          return (
            <div key={i} className="rounded-xl border border-border bg-card px-4 py-3 hover:bg-accent/40 transition-colors">
              <div className="flex flex-col gap-1.5">
                {cardFields.map(field => (
                  <div key={field.field} className="flex items-center gap-2">
                    {field.label && <span className="text-xs text-muted-foreground min-w-16">{field.label}</span>}
                    <CellRenderer value={row[field.field]} config={field.render} row={row} />
                  </div>
                ))}
              </div>
            </div>
          );
        }

        // 默认：显示第一个字符串字段作为标题
        const mainField = Object.values(row).find(v => typeof v === 'string' && v.length > 0);
        const subFields = Object.entries(row)
          .filter(([k, v]) => v != null && k !== 'id' && v !== mainField)
          .slice(0, 3);

        return (
          <div key={i} className="rounded-xl border border-border bg-card px-4 py-3 hover:bg-accent/40 transition-colors">
            <div className="text-sm font-medium text-foreground">{String(mainField ?? `Item ${i + 1}`)}</div>
            {subFields.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-3 text-xs text-muted-foreground">
                {subFields.map(([key, val]) => (
                  <span key={key}>{String(val)}</span>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function replaceTemplate(template: string, row: Record<string, unknown>): string {
  return template.replace(/\{(\w+)\}/g, (_, key) => String(row[key] ?? ''));
}

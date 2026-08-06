import { useState, useMemo } from 'react';
import { ArrowUpDownIcon, ChevronLeftIcon, ChevronRightIcon } from 'lucide-react';
import type { ViewComponentProps, ColumnDef } from '../types';
import { CellRenderer } from '../cells/CellRenderer';

export default function TableView({ data, options }: ViewComponentProps) {
  const [sortField, setSortField] = useState<string | null>(null);
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc');
  const [page, setPage] = useState(0);

  const items = useMemo(() => {
    if (!Array.isArray(data)) return [];
    let result = [...data] as Record<string, unknown>[];
    if (sortField && options?.sortable !== false) {
      result.sort((a, b) => {
        const va = a[sortField];
        const vb = b[sortField];
        if (va == null && vb == null) return 0;
        if (va == null) return 1;
        if (vb == null) return -1;
        const cmp = va < vb ? -1 : va > vb ? 1 : 0;
        return sortOrder === 'desc' ? -cmp : cmp;
      });
    }
    return result;
  }, [data, sortField, sortOrder, options?.sortable]);

  const pageSize = options?.pagination?.page_size ?? 50;
  const totalPages = Math.ceil(items.length / pageSize);
  const pagedItems = items.slice(page * pageSize, (page + 1) * pageSize);

  const columns = options?.columns;
  const colDefs: ColumnDef[] = columns || inferColumns(pagedItems);

  const toggleSort = (field: string) => {
    if (sortField === field) {
      setSortOrder(o => (o === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortOrder('asc');
    }
  };

  if (items.length === 0) {
    return <div className="py-8 text-center text-sm text-muted-foreground">{options?.empty_text || '暂无数据'}</div>;
  }

  return (
    <div className="overflow-hidden rounded-xl border border-border">
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/40">
              {colDefs.map(col => (
                <th
                  key={col.field}
                  className="px-3 py-2.5 text-left text-xs font-semibold text-muted-foreground"
                  style={{ width: col.width }}
                >
                  {options?.sortable !== false && col.sortable !== false ? (
                    <button
                      onClick={() => toggleSort(col.field)}
                      className="flex items-center gap-1 hover:text-foreground transition-colors"
                    >
                      {col.label}
                      <ArrowUpDownIcon className={`w-3 h-3 ${sortField === col.field ? 'text-primary' : 'opacity-40'}`} />
                    </button>
                  ) : (
                    col.label
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pagedItems.map((row, i) => (
              <tr key={i} className="border-b border-border last:border-0 hover:bg-accent/40 transition-colors">
                {colDefs.map(col => (
                  <td key={col.field} className={`px-3 py-2.5 ${col.align === 'center' ? 'text-center' : col.align === 'right' ? 'text-right' : ''}`}>
                    <CellRenderer value={row[col.field]} config={col.render} row={row} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="flex items-center justify-between border-t border-border bg-muted/20 px-3 py-2">
          <span className="text-xs text-muted-foreground">
            共 {items.length} 条
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage(p => Math.max(0, p - 1))}
              disabled={page === 0}
              className="rounded-md p-1 hover:bg-accent disabled:opacity-30"
            >
              <ChevronLeftIcon className="w-4 h-4" />
            </button>
            <span className="text-xs text-muted-foreground tabular-nums">
              {page + 1} / {totalPages}
            </span>
            <button
              onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="rounded-md p-1 hover:bg-accent disabled:opacity-30"
            >
              <ChevronRightIcon className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function inferColumns(items: Record<string, unknown>[]): ColumnDef[] {
  if (items.length === 0) return [];
  const keys = Object.keys(items[0]);
  return keys.slice(0, 8).map(key => ({ field: key, label: key }));
}

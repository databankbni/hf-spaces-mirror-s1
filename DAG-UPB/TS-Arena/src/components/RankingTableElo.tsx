'use client';

import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { Popover, PopoverButton, PopoverPanel } from '@headlessui/react';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  ColumnDef,
  flexRender,
  SortDirection,
} from '@tanstack/react-table';
import { Info } from 'lucide-react';
import { ModelRanking } from '@/src/services/modelService';

interface RankingTableEloProps {
  rankings: ModelRanking[];
  compact?: boolean;
  title?: string;
  limit?: number;
  definitionId?: number;
  /**
   * Models that appear on this scope's SQL board, i.e. the ones that actually
   * submitted quantile forecasts. Everyone else gets a dash in the SQL column
   * rather than their degenerate point-forecast score, which is not comparable
   * with a real one. Omitted (undefined) means the eligibility request failed or
   * was not made, in which case the column shows nothing rather than guessing.
   */
  sqlEligibleModelIds?: Set<number>;
}

// Text search filter component
function TextSearchFilter({ column }: { column: any }) {
  const filterValue = (column.getFilterValue() as string) || '';

  return (
    <div onClick={(e) => e.stopPropagation()} className="mt-1">
      <input
        type="text"
        value={filterValue}
        onChange={(e) => column.setFilterValue(e.target.value || undefined)}
        placeholder="Search..."
        className="w-full px-2 py-1.5 text-base sm:text-xs border border-gray-300 rounded focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
      />
    </div>
  );
}

// Numeric max filter component
function NumberMaxFilter({ column }: { column: any }) {
  const filterValue = (column.getFilterValue() as number) || '';

  return (
    <div onClick={(e) => e.stopPropagation()} className="mt-1">
      <input
        type="number"
        value={filterValue}
        onChange={(e) => column.setFilterValue(e.target.value ? Number(e.target.value) : undefined)}
        placeholder="Max (M)..."
        className="w-full px-2 py-1.5 text-base sm:text-xs border border-gray-300 rounded focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
      />
    </div>
  );
}

/**
 * Column header with an info popover. Hover on a pointer, tap/keyboard on touch.
 */
function HeaderWithInfo({
  label,
  ariaLabel,
  width = 'w-48',
  children,
}: {
  label: string;
  ariaLabel: string;
  width?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-1.5 normal-case">
      <span>{label}</span>
      <Popover className="relative group" onClick={(e) => e.stopPropagation()}>
        {({ open }) => (
          <>
            <PopoverButton
              className="flex items-center justify-center w-11 h-11 -m-[14px] rounded-full text-gray-400 hover:text-gray-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
              aria-label={ariaLabel}
            >
              <Info className="w-4 h-4" aria-hidden="true" />
            </PopoverButton>
            <PopoverPanel
              static
              className={`absolute right-0 top-6 ${width} p-3 bg-gray-900 text-white text-xs rounded-lg shadow-lg transition-all duration-200 z-10 normal-case font-normal ${
                open ? 'opacity-100 visible' : 'opacity-0 invisible group-hover:opacity-100 group-hover:visible'
              }`}
            >
              {children}
            </PopoverPanel>
          </>
        )}
      </Popover>
    </div>
  );
}

/** Tooltip body for the SQL column. Kept next to the header that uses it. */
function SqlExplanation() {
  return (
    <>
      <span className="font-semibold">Scaled Quantile Loss</span> — the mean pinball loss
      over the nine deciles (0.1 … 0.9), divided by the same naive-forecast MAE that scales
      MASE. Lower is better, and the two metrics are on one scale, so they can be read side
      by side. Only models that submit quantile forecasts are scored on it.
    </>
  );
}

export default function RankingTableElo({ 
  rankings,
  compact = false,
  title,
  limit,
  definitionId,
  sqlEligibleModelIds,
}: RankingTableEloProps) {
  const router = useRouter();

  const handleRowClick = (modelId: string, modelName: string) => {
    router.push(`/models/${modelId}`);
  };

  // Apply limit if specified. Memoize so the `data` reference passed to
  // useReactTable is stable across renders — an unstable data ref each render
  // makes react-table's auto-reset loop infinitely (freezing the page).
  const displayedRankings = useMemo(
    () => (limit ? rankings.slice(0, limit) : rankings),
    [rankings, limit]
  );

  const fullColumns = useMemo<ColumnDef<ModelRanking>[]>(
    () => [
      {
        accessorKey: 'rank_position',
        header: 'Rank',
        cell: (info) => (
          <span className="font-semibold text-gray-900">{info.getValue() as number}</span>
        ),
      },
      {
        accessorKey: 'model_name',
        header: 'Model Name',
        cell: (info) => (
          <span className="font-medium text-gray-900">{info.getValue() as string}</span>
        ),
      },
      {
        accessorKey: 'elo_rating_median',
        header: 'ELO Score',
        cell: (info) => {
          const row = info.row.original;
          const upperDiff = row.elo_ci_upper - row.elo_rating_median;
          const lowerDiff = row.elo_rating_median - row.elo_ci_lower;
          return (
            <div className="text-right">
              <span className="font-semibold">{row.elo_rating_median.toFixed(1)}</span>
              <div className="text-xs text-gray-500">
                +{upperDiff.toFixed(1)}/-{lowerDiff.toFixed(1)}
              </div>
            </div>
          );
        },
      },
      {
        accessorKey: 'avg_mase',
        header: 'Avg MASE',
        cell: (info) => {
          const row = info.row.original;
          if (row.avg_mase === null || row.mase_std === null) {
            return <span className="text-gray-400">N/A</span>;
          }
          return (
            <div className="text-right">
              <span>{row.avg_mase.toFixed(3)}</span>
              <div className="text-xs text-gray-500">
                ±{row.mase_std.toFixed(3)}
              </div>
            </div>
          );
        },
      },
      {
        accessorKey: 'avg_sql',
        header: () => (
          <HeaderWithInfo label="Avg SQL" ariaLabel="About the SQL metric" width="w-72">
            <SqlExplanation />
          </HeaderWithInfo>
        ),
        // Point-only models carry an avg_sql, but it is the degenerate
        // point-forecast substitution rather than a scored distribution. Sorting
        // has to agree with the cell that hides it, so they sort as absent too.
        sortUndefined: 'last',
        accessorFn: (row) =>
          sqlEligibleModelIds?.has(row.model_id) ? row.avg_sql ?? undefined : undefined,
        cell: (info) => {
          const row = info.row.original;
          if (!sqlEligibleModelIds?.has(row.model_id)) {
            return (
              <span
                className="text-gray-400 text-right block"
                title="This model submits point forecasts only, so it is not scored on the probabilistic board."
              >
                —
              </span>
            );
          }
          if (row.avg_sql === null) {
            return <span className="text-gray-400">N/A</span>;
          }
          return (
            <div className="text-right">
              <span>{row.avg_sql.toFixed(3)}</span>
              {row.sql_std !== null && (
                <div className="text-xs text-gray-500">±{row.sql_std.toFixed(3)}</div>
              )}
            </div>
          );
        },
      },
      {
        accessorKey: 'evaluated_count',
        header: 'Evaluations',
        cell: (info) => {
          const value = info.getValue() as number | null;
          return (
            <span className="text-right">{value !== null ? value.toLocaleString() : 'N/A'}</span>
          );
        },
      },
      {
        accessorKey: 'matches_played',
        header: 'Matches',
        cell: (info) => (
          <span className="text-right">{(info.getValue() as number).toLocaleString()}</span>
        ),
      },
      {
        accessorKey: 'organization_name',
        header: 'Organization',
        cell: (info) => info.getValue() as string,
      },
      {
        accessorKey: 'architecture',
        header: 'Architecture',
        cell: (info) => (
          <span className="text-gray-700">{(info.getValue() as string) || 'N/A'}</span>
        ),
      },
      {
        accessorKey: 'model_size',
        size: 150,
        minSize: 150,
        header: () => (
          <HeaderWithInfo label="Model Size" ariaLabel="About model size">
            Model sizes are shown in million parameters
          </HeaderWithInfo>
        ),
        filterFn: (row, columnId, filterValue) => {
          const value = row.getValue(columnId) as number;
          if (!filterValue) return true;
          return value <= filterValue;
        },
        cell: (info) => {
          const size = info.getValue() as number;
          return (
            <span className="text-gray-700 text-right block">
              {size ? `${size.toLocaleString()}M` : 'N/A'}
            </span>
          );
        },
      },
    ],
    [sqlEligibleModelIds]
  );

  const compactColumns = useMemo<ColumnDef<ModelRanking>[]>(
    () => [
      {
        accessorKey: 'rank_position',
        header: 'Rank',
        cell: (info) => (
          <span className="font-semibold text-gray-900">{info.getValue() as number}</span>
        ),
      },
      {
        accessorKey: 'model_name',
        header: 'Model Name',
        cell: (info) => (
          <span className="font-medium text-gray-900">{info.getValue() as string}</span>
        ),
      },
      {
        accessorKey: 'elo_rating_median',
        header: 'ELO Score',
        cell: (info) => {
          const row = info.row.original;
          const upperDiff = row.elo_ci_upper - row.elo_rating_median;
          const lowerDiff = row.elo_rating_median - row.elo_ci_lower;
          return (
            <div className="text-right">
              <span className="font-semibold">{row.elo_rating_median.toFixed(1)}</span>
              <div className="text-xs text-gray-500">
                +{upperDiff.toFixed(1)}/-{lowerDiff.toFixed(1)}
              </div>
            </div>
          );
        },
      },
      {
        accessorKey: 'avg_mase',
        header: 'Avg MASE',
        cell: (info) => {
          const row = info.row.original;
          if (row.avg_mase === null || row.mase_std === null) {
            return <span className="text-gray-400">N/A</span>;
          }
          return (
            <div className="text-right">
              <span>{row.avg_mase.toFixed(3)}</span>
              <div className="text-xs text-gray-500">
                ±{row.mase_std.toFixed(3)}
              </div>
            </div>
          );
        },
      },
      {
        accessorKey: 'avg_sql',
        header: () => (
          <HeaderWithInfo label="Avg SQL" ariaLabel="About the SQL metric" width="w-72">
            <SqlExplanation />
          </HeaderWithInfo>
        ),
        // Point-only models carry an avg_sql, but it is the degenerate
        // point-forecast substitution rather than a scored distribution. Sorting
        // has to agree with the cell that hides it, so they sort as absent too.
        sortUndefined: 'last',
        accessorFn: (row) =>
          sqlEligibleModelIds?.has(row.model_id) ? row.avg_sql ?? undefined : undefined,
        cell: (info) => {
          const row = info.row.original;
          if (!sqlEligibleModelIds?.has(row.model_id)) {
            return (
              <span
                className="text-gray-400 text-right block"
                title="This model submits point forecasts only, so it is not scored on the probabilistic board."
              >
                —
              </span>
            );
          }
          if (row.avg_sql === null) {
            return <span className="text-gray-400">N/A</span>;
          }
          return (
            <div className="text-right">
              <span>{row.avg_sql.toFixed(3)}</span>
              {row.sql_std !== null && (
                <div className="text-xs text-gray-500">±{row.sql_std.toFixed(3)}</div>
              )}
            </div>
          );
        },
      },
    ],
    [sqlEligibleModelIds]
  );

  const columns = compact ? compactColumns : fullColumns;

  const table = useReactTable({
    data: displayedRankings ?? [],
    columns,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    initialState: {
      sorting: [
        {
          id: 'rank_position',
          desc: false,
        },
      ],
    },
  });

  const getSortIcon = (isSorted: false | SortDirection) => {
    if (!isSorted) {
      return <span className="ml-1 text-gray-400">↕</span>;
    }
    return <span className="ml-1">{isSorted === 'asc' ? '↑' : '↓'}</span>;
  };

  return (
    <div className="bg-white rounded-lg shadow-md overflow-hidden">
      {title && (
        <div className="px-6 py-4 border-b border-gray-200 bg-gray-50">
          {definitionId ? (
            <h3 
              className="text-lg font-semibold text-gray-900 cursor-pointer hover:text-blue-600 transition-colors"
              onClick={() => router.push(`/challenges/${definitionId}`)}
            >
              {title}
            </h3>
          ) : (
            <h3 className="text-lg font-semibold text-gray-900">{title}</h3>
          )}
        </div>
      )}
      {/* Card list: small screens only. The full table needs ~1200-1900px of
          horizontal room, which pushes the ELO score (the point of the page)
          off-screen on a phone. */}
      <div className="md:hidden p-3 space-y-2">
        {table.getRowModel().rows.map((row) => {
          const model = row.original;
          const eloUpperDiff = model.elo_ci_upper - model.elo_rating_median;
          const eloLowerDiff = model.elo_rating_median - model.elo_ci_lower;

          return (
            <button
              key={row.id}
              type="button"
              onClick={() => handleRowClick(String(model.model_id), model.model_name)}
              className="w-full text-left bg-white border border-gray-200 rounded-lg shadow-sm hover:shadow-md transition-shadow p-3"
            >
              <div className="flex items-start gap-3">
                <span className="inline-flex items-center justify-center shrink-0 w-7 h-7 rounded-full bg-gray-100 text-gray-700 text-xs font-bold">
                  {model.rank_position}
                </span>
                <span className="text-sm font-medium text-gray-900 break-words">
                  {model.model_name}
                </span>
              </div>

              <div className="mt-3 space-y-1 text-sm">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-gray-500">ELO Score</span>
                  <span className="text-gray-900 font-semibold">
                    {model.elo_rating_median.toFixed(1)}
                    <span className="ml-1.5 text-xs font-normal text-gray-500">
                      +{eloUpperDiff.toFixed(1)}/-{eloLowerDiff.toFixed(1)}
                    </span>
                  </span>
                </div>
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-gray-500">Avg MASE</span>
                  {model.avg_mase === null || model.mase_std === null ? (
                    <span className="text-gray-400">N/A</span>
                  ) : (
                    <span className="text-gray-900">
                      {model.avg_mase.toFixed(3)}
                      <span className="ml-1.5 text-xs text-gray-500">
                        ±{model.mase_std.toFixed(3)}
                      </span>
                    </span>
                  )}
                </div>
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-gray-500">Avg SQL</span>
                  {!sqlEligibleModelIds?.has(model.model_id) ? (
                    <span className="text-gray-400">—</span>
                  ) : model.avg_sql === null ? (
                    <span className="text-gray-400">N/A</span>
                  ) : (
                    <span className="text-gray-900">
                      {model.avg_sql.toFixed(3)}
                      {model.sql_std !== null && (
                        <span className="ml-1.5 text-xs text-gray-500">
                          ±{model.sql_std.toFixed(3)}
                        </span>
                      )}
                    </span>
                  )}
                </div>
              </div>
            </button>
          );
        })}
      </div>

      <div className="hidden md:block overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => {
                  const columnId = header.column.id;
                  const showTextFilter = !compact && (columnId === 'model_name' || columnId === 'readable_id');
                  const showNumberMaxFilter = !compact && columnId === 'model_size';
                  
                  return (
                    <th
                      key={header.id}
                      className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                    >
                      <div
                        className={`flex items-center ${
                          header.column.getCanSort() ? 'cursor-pointer hover:text-gray-700' : ''
                        }`}
                        onClick={header.column.getToggleSortingHandler()}
                      >
                        {flexRender(
                          header.column.columnDef.header,
                          header.getContext()
                        )}
                        {header.column.getCanSort() &&
                          getSortIcon(header.column.getIsSorted())}
                      </div>
                      
                      {showTextFilter && <TextSearchFilter column={header.column} />}
                      {showNumberMaxFilter && <NumberMaxFilter column={header.column} />}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {table.getRowModel().rows.map((row) => (
              <tr 
                key={row.id} 
                className="hover:bg-gray-50 cursor-pointer transition-colors"
                onClick={() => handleRowClick(String(row.original.model_id), row.original.model_name)}
              >
                {row.getVisibleCells().map((cell) => (
                  <td
                    key={cell.id}
                    className="px-6 py-4 whitespace-nowrap text-sm text-gray-500"
                  >
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {table.getRowModel().rows.length === 0 && (
        <div className="text-center py-8 text-gray-500">
          No rankings found.
        </div>
      )}
    </div>
  );
}

'use client';

import { Popover, PopoverButton, PopoverPanel } from '@headlessui/react';
import { Info } from 'lucide-react';
import { ModelRanking } from '@/src/services/modelService';

interface ModelMetricSummaryProps {
  /** This model's row on the global (MASE) board, or null if it has none yet. */
  ranking: ModelRanking | null;
  /** True when the model also appears on the global SQL board. */
  sqlEligible: boolean;
}

/**
 * The model's current global standing on all three headline metrics.
 *
 * The rest of this page plots ELO over time; this is the one place a reader can see
 * the point and probabilistic accuracy behind that ELO. SQL is shown only for models
 * scored on the probabilistic board — a point-only model does receive an SQL number
 * internally, but it comes from substituting the point forecast at every quantile and
 * is not comparable with a genuine one.
 */
export default function ModelMetricSummary({ ranking, sqlEligible }: ModelMetricSummaryProps) {
  if (!ranking) return null;

  const sqlValue =
    sqlEligible && ranking.avg_sql !== null ? ranking.avg_sql.toFixed(3) : null;

  return (
    <div className="bg-white rounded-lg shadow-md p-4 sm:p-6 mt-6">
      <div className="flex items-center gap-1.5 mb-3">
        <h2 className="text-lg font-semibold text-gray-900">Current Standing</h2>
        <span className="text-sm text-gray-500">(all challenges)</span>
      </div>
      <dl className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="rounded-md bg-gray-50 px-4 py-3">
          <dt className="text-xs font-medium uppercase tracking-wider text-gray-500">
            ELO Score
          </dt>
          <dd className="mt-1 text-xl font-semibold text-gray-900">
            {ranking.elo_rating_median.toFixed(1)}
            <span className="ml-2 text-xs font-normal text-gray-500">
              rank {ranking.rank_position}
            </span>
          </dd>
        </div>

        <div className="rounded-md bg-gray-50 px-4 py-3">
          <dt className="text-xs font-medium uppercase tracking-wider text-gray-500">
            Avg MASE
          </dt>
          <dd className="mt-1 text-xl font-semibold text-gray-900">
            {ranking.avg_mase !== null ? (
              <>
                {ranking.avg_mase.toFixed(3)}
                {ranking.mase_std !== null && (
                  <span className="ml-2 text-xs font-normal text-gray-500">
                    ±{ranking.mase_std.toFixed(3)}
                  </span>
                )}
              </>
            ) : (
              <span className="text-gray-400">N/A</span>
            )}
          </dd>
        </div>

        <div className="rounded-md bg-gray-50 px-4 py-3">
          <dt className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wider text-gray-500">
            <span>Avg SQL</span>
            <Popover className="relative group">
              {({ open }) => (
                <>
                  <PopoverButton
                    className="flex items-center justify-center w-11 h-11 -m-[14px] rounded-full text-gray-400 hover:text-gray-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
                    aria-label="About the SQL metric"
                  >
                    <Info className="w-4 h-4" aria-hidden="true" />
                  </PopoverButton>
                  <PopoverPanel
                    static
                    className={`absolute left-0 top-6 w-72 p-3 bg-gray-900 text-white text-xs rounded-lg shadow-lg transition-all duration-200 z-10 normal-case font-normal tracking-normal ${
                      open ? 'opacity-100 visible' : 'opacity-0 invisible group-hover:opacity-100 group-hover:visible'
                    }`}
                  >
                    <span className="font-semibold">Scaled Quantile Loss</span> — the mean
                    pinball loss over the nine deciles (0.1 … 0.9), divided by the same
                    naive-forecast MAE that scales MASE. Lower is better, and the two
                    metrics are on one scale, so they can be read side by side. Only models
                    that submit quantile forecasts are scored on it.
                  </PopoverPanel>
                </>
              )}
            </Popover>
          </dt>
          <dd className="mt-1 text-xl font-semibold text-gray-900">
            {sqlValue !== null ? (
              <>
                {sqlValue}
                {ranking.sql_std !== null && (
                  <span className="ml-2 text-xs font-normal text-gray-500">
                    ±{ranking.sql_std.toFixed(3)}
                  </span>
                )}
              </>
            ) : (
              <span
                className="text-base font-normal text-gray-400"
                title={
                  sqlEligible
                    ? 'No scored quantile forecasts yet.'
                    : 'This model submits point forecasts only, so it is not scored on the probabilistic board.'
                }
              >
                {sqlEligible ? 'N/A' : 'Point forecasts only'}
              </span>
            )}
          </dd>
        </div>
      </dl>
    </div>
  );
}

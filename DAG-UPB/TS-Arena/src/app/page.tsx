'use client';

import { useState, useEffect } from 'react';
import { Popover, PopoverButton, PopoverPanel } from '@headlessui/react';
import { Info } from 'lucide-react';
import Breadcrumbs from '@/src/components/Breadcrumbs';
import RankingTableElo from '@/src/components/RankingTableElo';
import TimeSeriesChart from '@/src/components/TimeSeriesChart';
import { getFilteredRankings, getRankingFilters, collectSqlEligible, ModelRanking, FilterOptions, ChallengeDefinition } from '@/src/services/modelService';
import { getDefinitionRounds } from '@/src/services/definitionService';

const DEFINITION_ID:number = parseInt(process.env.NEXT_PUBLIC_DEFINITION_ID || '225');
const SERIES_ID:number = parseInt(process.env.NEXT_PUBLIC_SERIES_ID || '1373');

interface RankingsData {
  overall: ModelRanking[];
  byDefinition: Record<number, ModelRanking[]>;
  byFrequencyHorizon: Record<string, ModelRanking[]>;
  /**
   * Who may show an SQL number, per scope. Eligibility is scope-local: a model can
   * forecast probabilistically in one challenge and point-only in another, so each
   * table gets the set for its own scope rather than a single global one.
   */
  sqlEligible: {
    overall: Set<number>;
    byDefinition: Record<number, Set<number>>;
    byFrequencyHorizon: Record<string, Set<number>>;
  };
}

/** Group a bulk (scope_type) rankings response by definition id. */
function groupByDefinition(rankings: ModelRanking[]): Record<number, ModelRanking[]> {
  const grouped: Record<number, ModelRanking[]> = {};
  rankings.forEach((r) => {
    const id = r.definition_id ?? (r.scope_id != null ? Number(r.scope_id) : undefined);
    if (id === undefined || Number.isNaN(id)) return;
    (grouped[id] ??= []).push(r);
  });
  return grouped;
}

/** Group a bulk (scope_type) rankings response by frequency/horizon scope id. */
function groupByFrequencyHorizon(rankings: ModelRanking[]): Record<string, ModelRanking[]> {
  const grouped: Record<string, ModelRanking[]> = {};
  rankings.forEach((r) => {
    if (r.scope_id == null) return;
    (grouped[r.scope_id] ??= []).push(r);
  });
  return grouped;
}

function eligibleSets<K extends string | number>(
  grouped: Record<K, ModelRanking[]>
): Record<K, Set<number>> {
  const sets = {} as Record<K, Set<number>>;
  (Object.keys(grouped) as K[]).forEach((key) => {
    sets[key] = collectSqlEligible(grouped[key]);
  });
  return sets;
}

export default function Home() {
  const [filterOptions, setFilterOptions] = useState<FilterOptions>({
    definitions: [],
    frequency_horizons: [],
    calculation_dates: [],
  });
  const [rankingsData, setRankingsData] = useState<RankingsData>({
    overall: [],
    byDefinition: {},
    byFrequencyHorizon: {},
    sqlEligible: { overall: new Set(), byDefinition: {}, byFrequencyHorizon: {} },
  });
  const [selectedCalculationDate, setSelectedCalculationDate] = useState<string>('');
  const [selectedDefinitionId, setSelectedDefinitionId] = useState<number | null>(null);
  const [selectedFrequency, setSelectedFrequency] = useState<string | null>(null);
  const [selectedHorizon, setSelectedHorizon] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [isMounted, setIsMounted] = useState(false);
  const [oldestActiveRound, setOldestActiveRound] = useState<any>(null);
  const [roundLoading, setRoundLoading] = useState(true);

  // Format calculation date for display
  const formatCalculationDateLabel = (dateStr: string, isMonthEnd: boolean) => {
    const date = new Date(dateStr);
    const monthYear = `${date.toLocaleString('en-US', { month: 'short' })}-${date.getFullYear()}`;
    return isMonthEnd ? monthYear : 'Recent';
  };

  // Generate dropdown options from API data
  const monthOptions = filterOptions.calculation_dates.map((item) => ({
    label: formatCalculationDateLabel(item.calculation_date, item.is_month_end),
    value: item.calculation_date,
  }));

  // "Rankings by Challenge" selector — default to the first available definition
  const effectiveDefinitionId = selectedDefinitionId ?? filterOptions.definitions[0]?.id ?? null;
  const selectedDefinition = filterOptions.definitions.find((d) => d.id === effectiveDefinitionId);

  // Format frequency_horizon for display (e.g., "00:15:00::1 day" -> "15min / 1 day")
  const formatFrequencyHorizon = (fh: string) => {
    const parts = fh.split('::');
    if (parts.length !== 2) return fh;
    
    const [freq, horizon] = parts;
    const freqMatch = freq.match(/(\d+):(\d+):(\d+)/);
    let freqStr = freq;
    if (freqMatch) {
      const hours = parseInt(freqMatch[1]);
      const mins = parseInt(freqMatch[2]);
      if (hours > 0) {
        freqStr = `${hours}h`;
      } else if (mins > 0) {
        freqStr = `${mins}min`;
      }
    }
    
    return `${freqStr} / ${horizon}`;
  };

  // Format a bare frequency for display (e.g. "00:15:00" -> "15min", "01:00:00" -> "1h")
  const formatFrequency = (freq: string) => {
    const m = freq.match(/(\d+):(\d+):(\d+)/);
    if (m) {
      const hours = parseInt(m[1]);
      const mins = parseInt(m[2]);
      if (hours > 0) return `${hours}h`;
      if (mins > 0) return `${mins}min`;
    }
    return freq;
  };

  // "Rankings by Frequency & Horizon" selectors — driven by the valid
  // combinations the API returns in frequency_horizons (e.g. "00:15:00::1 day").
  const fhCombos = filterOptions.frequency_horizons.map((fh) => {
    const [frequency, horizon] = fh.split('::');
    return { fh, frequency, horizon };
  });
  const frequencyOptions = [...new Set(fhCombos.map((c) => c.frequency))];
  const effectiveFrequency = selectedFrequency ?? frequencyOptions[0] ?? null;
  // Horizon options are constrained to those valid for the chosen frequency.
  const horizonOptions = fhCombos
    .filter((c) => c.frequency === effectiveFrequency)
    .map((c) => c.horizon);
  const effectiveHorizon =
    selectedHorizon && horizonOptions.includes(selectedHorizon)
      ? selectedHorizon
      : horizonOptions[0] ?? null;
  const selectedFh =
    effectiveFrequency && effectiveHorizon
      ? `${effectiveFrequency}::${effectiveHorizon}`
      : null;

  useEffect(() => {
    setIsMounted(true);
    return () => setIsMounted(false);
  }, []);

  // Fetch oldest active round
  useEffect(() => {
    const fetchOldestActiveRound = async () => {
      try {
        setRoundLoading(true);
        const response = await getDefinitionRounds(DEFINITION_ID, { status: 'active' });
        
        if (response.items && response.items.length > 0) {
          // Sort by start_time to get the oldest
          const sorted = [...response.items].sort((a, b) => 
            new Date(a.start_time).getTime() - new Date(b.start_time).getTime()
          );
          setOldestActiveRound(sorted[0]);
        }
      } catch (error) {
        console.error('Error fetching active rounds:', error);
      } finally {
        setRoundLoading(false);
      }
    };

    fetchOldestActiveRound();
  }, []);

  useEffect(() => {
    if (!isMounted) return;

    const fetchAllData = async () => {
      try {
        setLoading(true);
        
        // First fetch filter options. getRankingFilters throws on a non-OK
        // response or an unexpected shape, so nothing invalid reaches state —
        // the render path reads these arrays unguarded.
        const options = await getRankingFilters();
        setFilterOptions(options);

        // Set default calculation date to the first (most recent) one
        if (!selectedCalculationDate && options.calculation_dates.length > 0) {
          setSelectedCalculationDate(options.calculation_dates[0].calculation_date);
          return; // Will re-run when selectedCalculationDate is set
        }
        
        // Build base filters
        const baseFilters: any = { limit: 100 };
        // Only send calculation_date if it's a month-end date (not Recent)
        if (selectedCalculationDate) {
          const selectedDateInfo = options.calculation_dates.find(
            d => d.calculation_date === selectedCalculationDate
          );
          if (selectedDateInfo?.is_month_end) {
            baseFilters.calculation_date = selectedCalculationDate;
          }
        }
        
        // Six requests total: the three MASE boards this page ranks by, and the
        // matching SQL boards, which are read only for their membership — they say
        // which models actually forecast probabilistically in each scope.
        // This page used to issue one request per definition and per
        // frequency/horizon — with 16 definitions that was ~20 parallel calls,
        // each of which costs the API a full scan of the rankings view.
        const sqlFilters = { ...baseFilters, metric: 'sql' as const };
        const [
          overallResponse,
          definitionResponse,
          frequencyHorizonResponse,
          overallSql,
          definitionSql,
          frequencyHorizonSql,
        ] = await Promise.all([
          getFilteredRankings(baseFilters),
          getFilteredRankings({ ...baseFilters, scope_type: 'definition' }),
          getFilteredRankings({ ...baseFilters, scope_type: 'frequency_horizon' }),
          getFilteredRankings(sqlFilters),
          getFilteredRankings({ ...sqlFilters, scope_type: 'definition' }),
          getFilteredRankings({ ...sqlFilters, scope_type: 'frequency_horizon' }),
        ]);

        // Bulk responses arrive as one flat list; group them by scope. Seed the
        // known scopes first so a scope with no rankings still renders as empty.
        const byDefinition: Record<number, ModelRanking[]> = {};
        options.definitions.forEach((def: ChallengeDefinition) => {
          byDefinition[def.id] = [];
        });
        Object.entries(groupByDefinition(definitionResponse.rankings)).forEach(([id, rows]) => {
          (byDefinition[Number(id)] ??= []).push(...rows);
        });

        const byFrequencyHorizon: Record<string, ModelRanking[]> = {};
        options.frequency_horizons.forEach((fh: string) => {
          byFrequencyHorizon[fh] = [];
        });
        Object.entries(groupByFrequencyHorizon(frequencyHorizonResponse.rankings)).forEach(
          ([fh, rows]) => {
            (byFrequencyHorizon[fh] ??= []).push(...rows);
          }
        );

        setRankingsData({
          overall: overallResponse.rankings,
          byDefinition,
          byFrequencyHorizon,
          sqlEligible: {
            overall: collectSqlEligible(overallSql.rankings),
            byDefinition: eligibleSets(groupByDefinition(definitionSql.rankings)),
            byFrequencyHorizon: eligibleSets(
              groupByFrequencyHorizon(frequencyHorizonSql.rankings)
            ),
          },
        });
      } catch (error) {
        console.error('Error fetching rankings:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchAllData();
  }, [selectedCalculationDate, isMounted]);

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 p-4 sm:p-6 lg:p-8">
        <main className="max-w-7xl mx-auto">
          <Breadcrumbs items={[{ label: 'Rankings', href: '/' }]} />
          <h1 className="text-3xl font-bold text-gray-900 mb-8">
            TS-Arena – Live Time-Series Forecasting Benchmark
          </h1>
          <div className="text-center py-12">
            <div className="text-lg text-gray-600">Loading ranking...</div>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 p-4 sm:p-6 lg:p-8">
      <main className="max-w-7xl mx-auto">
        <Breadcrumbs items={[{ label: 'Rankings', href: '/' }]} />
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900">
            TS-Arena – Live Time-Series Forecasting Benchmark
          </h1>
          <p className="mt-2 text-gray-600">
            Forecasting models compete in multiple real-time forecasting challenges per day on live real data. Rankings update multiple times daily.
          </p>
        </div>

        {/* Time Series Chart Section */}
        {roundLoading ? (
          <div className="bg-white rounded-lg shadow-md p-4 sm:p-6 lg:p-8 mb-8">
            <div className="flex items-center justify-center">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
              <span className="ml-3 text-gray-600">Loading time series data...</span>
            </div>
          </div>
        ) : oldestActiveRound ? (
          <div className="mb-8">
            <TimeSeriesChart
              challengeId={oldestActiveRound.id}
              challengeName={oldestActiveRound.name || oldestActiveRound.round_name}
              challengeDescription={oldestActiveRound.description}
              frequency={oldestActiveRound.frequency}
              horizon={oldestActiveRound.horizon}
              seriesId={SERIES_ID}
              on_title_page={true}
              definitionId={DEFINITION_ID}
            />
          </div>
        ) : (
          <div className="bg-white rounded-lg shadow-md p-4 sm:p-6 lg:p-8 text-center text-gray-500 mb-8">
            <p>No active rounds available at the moment.</p>
          </div>
        )}

        {/* Overall Ranking (Full Table) */}
        <div className="mb-8">
          <div className="flex items-center justify-between mb-1">
            <h2 className="text-2xl font-semibold text-gray-900">Overall Ranking</h2>
            
            {/* Calculation Month Filter */}
            {/* `relative` sits here, not on the Popover: the Popover box is only as
                wide as its 16px icon, so a `right-0` panel anchored to it starts
                off the left edge of a phone screen. Anchoring to this row instead
                gives the panel the full card width to grow into. `group` stays on
                the Popover so hover still only triggers from the icon. */}
            <div className="relative flex items-center gap-2">
              <label className="text-xs text-gray-500">Period</label>
              <Popover className="group">
                {({ open }) => (
                  <>
                    <PopoverButton
                      className="flex items-center justify-center w-11 h-11 -m-[14px] rounded-full text-gray-400 hover:text-gray-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
                      aria-label="About the calculation period"
                    >
                      <Info className="w-4 h-4" aria-hidden="true" />
                    </PopoverButton>
                    <PopoverPanel
                      static
                      className={`absolute right-0 top-6 w-72 max-w-[calc(100vw-2rem)] p-3 bg-gray-900 text-white text-xs rounded-lg shadow-lg transition-all duration-200 z-10 ${
                        open ? 'opacity-100 visible' : 'opacity-0 invisible group-hover:opacity-100 group-hover:visible'
                      }`}
                    >
                      <div className="font-medium mb-1">Calculation Period</div>
                      <div className="text-gray-200 space-y-1">
                        <p>Rankings are recalculated multiple times a day as new ground truth data arrives.</p>
                        <p>Historical standings are snapshotted once per month. Select a month to view that period&apos;s snapshot.</p>
                        <p>&ldquo;Recent&rdquo; shows today&apos;s current ranking.</p>
                      </div>
                    </PopoverPanel>
                  </>
                )}
              </Popover>
              <select
                value={selectedCalculationDate}
                onChange={(e) => setSelectedCalculationDate(e.target.value)}
                className="px-3 py-1 text-base sm:text-xs bg-white border border-gray-200 rounded text-gray-600 hover:border-gray-300 focus:outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400 cursor-pointer"
              >
                {monthOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <p className="text-sm text-gray-600 mb-4">
            Aggregated scores across all challenge definitions and time series. ELO: higher is
            better. MASE and SQL: lower is better. SQL is shown only for models that submit
            quantile forecasts. Updated multiple times a day.
          </p>
          <RankingTableElo
            rankings={rankingsData.overall}
            sqlEligibleModelIds={rankingsData.sqlEligible.overall}
          />
        </div>

        {/* Rankings by Challenge Definition */}
        <div className="mb-8">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
            <h2 className="text-2xl font-semibold text-gray-900">Rankings by Challenge</h2>
            <select
              value={effectiveDefinitionId ?? ''}
              onChange={(e) => setSelectedDefinitionId(Number(e.target.value))}
              disabled={filterOptions.definitions.length === 0}
              className="px-3 py-2 text-base sm:text-sm bg-white border border-gray-200 rounded-md text-gray-700 hover:border-gray-300 focus:outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400 cursor-pointer max-w-full sm:max-w-sm disabled:opacity-50"
            >
              {filterOptions.definitions.map((def) => (
                <option key={def.id} value={def.id}>
                  {def.name}
                </option>
              ))}
            </select>
          </div>
          <p className="text-sm text-gray-600 mb-4">
            Rankings evaluated for the selected challenge definition.
          </p>
          {selectedDefinition ? (
            <RankingTableElo
              key={selectedDefinition.id}
              rankings={rankingsData.byDefinition[selectedDefinition.id] || []}
              sqlEligibleModelIds={rankingsData.sqlEligible.byDefinition[selectedDefinition.id]}
              limit={10}
              title={selectedDefinition.name}
              definitionId={selectedDefinition.id}
            />
          ) : (
            <p className="text-sm text-gray-500">No challenge definitions available.</p>
          )}
        </div>

        {/* Rankings by Frequency/Horizon */}
        <div className="mb-8">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
            <h2 className="text-2xl font-semibold text-gray-900">Rankings by Frequency & Horizon Combinations</h2>
            <div className="flex flex-wrap items-center gap-3">
              <label className="flex items-center gap-1.5 text-sm text-gray-600">
                <span>Frequency</span>
                <select
                  value={effectiveFrequency ?? ''}
                  onChange={(e) => setSelectedFrequency(e.target.value)}
                  disabled={frequencyOptions.length === 0}
                  className="px-3 py-2 text-base sm:text-sm bg-white border border-gray-200 rounded-md text-gray-700 hover:border-gray-300 focus:outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400 cursor-pointer disabled:opacity-50"
                >
                  {frequencyOptions.map((f) => (
                    <option key={f} value={f}>
                      {formatFrequency(f)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-center gap-1.5 text-sm text-gray-600">
                <span>Horizon</span>
                <select
                  value={effectiveHorizon ?? ''}
                  onChange={(e) => setSelectedHorizon(e.target.value)}
                  disabled={horizonOptions.length === 0}
                  className="px-3 py-2 text-base sm:text-sm bg-white border border-gray-200 rounded-md text-gray-700 hover:border-gray-300 focus:outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400 cursor-pointer disabled:opacity-50"
                >
                  {horizonOptions.map((h) => (
                    <option key={h} value={h}>
                      {h}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>
          <p className="text-sm text-gray-600 mb-4">
            Rankings for the selected forecast frequency / horizon combination.
          </p>
          {selectedFh ? (
            <RankingTableElo
              key={selectedFh}
              rankings={rankingsData.byFrequencyHorizon[selectedFh] || []}
              sqlEligibleModelIds={rankingsData.sqlEligible.byFrequencyHorizon[selectedFh]}
              limit={10}
              title={formatFrequencyHorizon(selectedFh)}
            />
          ) : (
            <p className="text-sm text-gray-500">No frequency / horizon combinations available.</p>
          )}
        </div>
      </main>
    </div>
  );
}

'use client';

import { useState, useEffect, useMemo, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Popover, PopoverButton, PopoverPanel } from '@headlessui/react';
import { Info } from 'lucide-react';
import Breadcrumbs from '@/src/components/Breadcrumbs';
import RankingTableElo from '@/src/components/RankingTableElo';
import Pagination from '@/src/components/Pagination';
import DetailsCard from '@/src/components/DetailsCard';
import ChallengeRoundsList from '@/src/components/ChallengeRoundsList';
import type { ChallengeDefinition, DefinitionSeries } from '@/src/types/challenge';
import { getFilteredRankings, getRankingFilters, collectSqlEligible, type RankingsResponse, type FilterOptions } from '@/src/services/modelService';
import { getDefinitionSeries } from '@/src/services/definitionService';

export default function ChallengeDefinitionDetail() {
  const params = useParams();
  const router = useRouter();
  const [definition, setDefinition] = useState<ChallengeDefinition | null>(null);
  const [rankings, setRankings] = useState<RankingsResponse | null>(null);
  // Models scored on this challenge's SQL board — the ones that submitted real
  // quantiles here. Everyone else shows a dash rather than a degenerate score.
  const [sqlEligible, setSqlEligible] = useState<Set<number> | undefined>(undefined);
  const [selectedCalculationDate, setSelectedCalculationDate] = useState<string>('');
  const [filterOptions, setFilterOptions] = useState<FilterOptions | null>(null);
  const [loading, setLoading] = useState(true);
  const [rankingsLoading, setRankingsLoading] = useState(false);
  const [rankingsPage, setRankingsPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [series, setSeries] = useState<DefinitionSeries[]>([]);
  const [seriesLoading, setSeriesLoading] = useState(false);

  // Format calculation date for display
  const formatCalculationDateLabel = (dateStr: string, isMonthEnd: boolean) => {
    const date = new Date(dateStr);
    const monthYear = `${date.toLocaleString('en-US', { month: 'short' })}-${date.getFullYear()}`;
    return isMonthEnd ? monthYear : 'Recent';
  };

  // Generate dropdown options from API data
  const monthOptions = filterOptions?.calculation_dates.map((item) => ({
    label: formatCalculationDateLabel(item.calculation_date, item.is_month_end),
    value: item.calculation_date,
  })) || [];

  useEffect(() => {
    const fetchDefinition = async () => {
      try {
        setLoading(true);
        const response = await fetch('/api/v1/definitions');
        
        if (!response.ok) {
          throw new Error('Failed to fetch challenge definitions');
        }
        
        const data: ChallengeDefinition[] = await response.json();
        const found = data.find(d => d.id === Number(params.challengeId));
        
        if (!found) {
          setError('Challenge definition not found');
        } else {
          setDefinition(found);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'An error occurred');
        console.error('Error fetching challenge definition:', err);
      } finally {
        setLoading(false);
      }
    };

    if (params.challengeId) {
      fetchDefinition();
    }
  }, [params.challengeId]);

  // Fetch filter options
  useEffect(() => {
    const fetchFilters = async () => {
      try {
        const options = await getRankingFilters();
        setFilterOptions(options);
        // Set default calculation date to the first (most recent) one
        if (!selectedCalculationDate && options.calculation_dates.length > 0) {
          setSelectedCalculationDate(options.calculation_dates[0].calculation_date);
        }
      } catch (err) {
        console.error('Error fetching filter options:', err);
      }
    };

    fetchFilters();
  }, []);

  // Fetch rankings for the definition
  useEffect(() => {
    const fetchRankings = async () => {
      if (!definition || !definition.id || !selectedCalculationDate) return;

      try {
        setRankingsLoading(true);
        const filters: any = { 
          definition_id: definition.id,
          limit: 100
        };
        // Only send calculation_date if it's a month-end date (not Recent)
        if (selectedCalculationDate && filterOptions) {
          const selectedDateInfo = filterOptions.calculation_dates.find(
            d => d.calculation_date === selectedCalculationDate
          );
          if (selectedDateInfo?.is_month_end) {
            filters.calculation_date = selectedCalculationDate;
          }
        }
        const [rankingsData, sqlRankings] = await Promise.all([
          getFilteredRankings(filters),
          getFilteredRankings({ ...filters, metric: 'sql' }),
        ]);
        setRankings(rankingsData);
        setSqlEligible(collectSqlEligible(sqlRankings.rankings));
      } catch (err) {
        console.error('Error fetching rankings:', err);
      } finally {
        setRankingsLoading(false);
      }
    };

    fetchRankings();
  }, [definition, selectedCalculationDate, filterOptions]);

  // Reset to page 1 when calculation date changes
  useEffect(() => {
    setRankingsPage(1);
  }, [selectedCalculationDate]);

  // Fetch the series that belong to this challenge definition
  useEffect(() => {
    const fetchSeries = async () => {
      if (!definition?.id) return;
      try {
        setSeriesLoading(true);
        const data = await getDefinitionSeries(definition.id);
        setSeries(data);
      } catch (err) {
        console.error('Error fetching definition series:', err);
      } finally {
        setSeriesLoading(false);
      }
    };
    fetchSeries();
  }, [definition?.id]);

  // Rankings pagination calculations
  const RANKINGS_PER_PAGE = 10;
  const totalRankings = rankings?.rankings.length || 0;
  const totalRankingsPages = Math.ceil(totalRankings / RANKINGS_PER_PAGE);
  const startRankingIndex = (rankingsPage - 1) * RANKINGS_PER_PAGE;
  const endRankingIndex = startRankingIndex + RANKINGS_PER_PAGE;
  const paginatedRankings = rankings?.rankings.slice(startRankingIndex, endRankingIndex) || [];

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex justify-center items-center h-64">
          <div className="text-gray-500">Loading challenge definition...</div>
        </div>
      </div>
    );
  }

  if (error || !definition) {
    return (
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="bg-red-50 border border-red-200 text-red-800 px-4 py-3 rounded">
          <p className="font-semibold">Error</p>
          <p className="text-sm">{error || 'Challenge definition not found'}</p>
        </div>
        <button
          onClick={() => router.back()}
          className="mt-4 text-blue-600 hover:text-blue-800 text-sm font-medium"
        >
          ← Go back
        </button>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <Breadcrumbs 
        items={[
          { label: 'Challenges', href: '/challenges' },
          { label: `Challenge #${params.challengeId}`, href: `/challenges/${params.challengeId}` }
        ]} 
      />
      
      <DetailsCard
        title={definition.name}
        id={`Challenge ID: ${definition.id}`}
        description={definition.description}
        displayText={definition.display_text}
        fields={[
          {
            label: 'Schedule ID',
            value: definition.schedule_id,
            mono: true
          },
          {
            label: 'Frequency',
            value: definition.frequency
          },
          {
            label: 'Horizon',
            value: definition.horizon
          },
          {
            label: 'Context Length',
            value: definition.context_length
          },
          ...(definition.domain ? [{
            label: 'Domain',
            value: definition.domain
          }] : []),
          ...(definition.subdomain ? [{
            label: 'Subdomain',
            value: definition.subdomain
          }] : [])
        ]}
        registrationPeriod={
          definition.next_registration_start || definition.next_registration_end
            ? {
                start: definition.next_registration_start ?? undefined,
                end: definition.next_registration_end ?? undefined
              }
            : undefined
        }
      />

      {/* Series Section */}
      <div className="mt-8">
        <h2 className="text-2xl font-semibold text-gray-900 mb-4">Series in this Challenge</h2>
        {seriesLoading ? (
          <div className="bg-white rounded-lg shadow-md p-12 text-center text-gray-500">
            Loading series...
          </div>
        ) : series.length > 0 ? (
          <div className="bg-white rounded-lg shadow-md overflow-hidden divide-y divide-gray-200">
            {series.map((s) => (
              <div key={s.series_id} className="px-4 sm:px-6 py-4">
                <div className="font-medium text-gray-900">{s.name}</div>
                {s.display_text && (
                  <div className="text-sm text-gray-600 mt-1">{s.display_text}</div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="bg-white rounded-lg shadow-md p-12 text-center text-gray-500">
            No series found for this challenge.
          </div>
        )}
      </div>

      {/* Rankings Section */}
      {definition && (
        <div className="mt-8">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-2xl font-semibold text-gray-900">Model Rankings</h2>
            
            {/* Calculation Month Filter */}
            <div className="flex items-center gap-2">
              <label className="text-xs text-gray-500">Period</label>
              <Popover className="relative group">
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
                      className={`absolute right-0 top-6 w-64 p-3 bg-gray-900 text-white text-xs rounded-lg shadow-lg transition-all duration-200 z-10 ${
                        open ? 'opacity-100 visible' : 'opacity-0 invisible group-hover:opacity-100 group-hover:visible'
                      }`}
                    >
                      <div className="font-medium mb-1">Calculation Period</div>
                      <div className="text-gray-200">
                        Select a month to view rankings calculated at the end of that period. &quot;Recent&quot; shows the most current rankings.
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
          
          {rankingsLoading ? (
            <div className="bg-white rounded-lg shadow-md p-12 text-center text-gray-500">
              Loading rankings...
            </div>
          ) : rankings && rankings.rankings.length > 0 ? (
            <>
              <RankingTableElo rankings={paginatedRankings} sqlEligibleModelIds={sqlEligible} />
              
              {/* Rankings Pagination */}
              <div className="mt-4 bg-white rounded-lg shadow-md overflow-hidden">
                <Pagination
                  currentPage={rankingsPage}
                  totalPages={totalRankingsPages}
                  totalItems={totalRankings}
                  itemsPerPage={RANKINGS_PER_PAGE}
                  onPageChange={setRankingsPage}
                  itemLabel="models"
                />
              </div>
            </>
          ) : (
            <div className="bg-white rounded-lg shadow-md p-12 text-center text-gray-500">
              No rankings available
            </div>
          )}
        </div>
      )}

      {/* Rounds Section */}
      {definition && (
        <div className="mt-8">
          <ChallengeRoundsList 
            definitionId={definition.id} 
            challengeId={params.challengeId as string}
          />
        </div>
      )}
    </div>
  );
}

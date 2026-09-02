'use client';

import { useEffect, useState, useCallback } from 'react';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import type { PlotParams } from 'react-plotly.js';
import type { ForecastsResponse, ForecastData, Model } from '@/src/types/challenge';
import { getChallengeSeries, getSeriesData, getSeriesForecasts, getRoundModels } from '@/src/services/roundService';
import { useIsMobile } from '@/src/hooks/useIsMobile';
import { MOBILE_PLOT_CONFIG, MOBILE_PLOT_HEIGHT, MOBILE_PLOT_MARGIN } from '@/src/components/plotMobile';
import humanizeDuration from 'humanize-duration';
import { parse, toSeconds } from 'iso8601-duration';
import wrap from 'word-wrap';


// Dynamically import Plotly to avoid SSR issues. `PlotlyPlot` is the app's
// single Plotly entry point — see the note there on why it is not
// `react-plotly.js` directly.
const Plot = dynamic(() => import('@/src/components/PlotlyPlot'), { ssr: false });

// One row of the mobile legend. `key` is already namespaced per series.
interface LegendEntry {
  key: string;
  label: string;
  detail?: string;
  color: string;
  dashed: boolean;
  visible: boolean;
}

/**
 * Mobile replacement for Plotly's built-in legend.
 *
 * Plotly's legend is laid out in axis fractions, which at phone widths turns
 * into a 200px-wide, 1400px-tall box sitting on top of the plot. Rendering the
 * same information as HTML below the chart lets it wrap, scroll and take a
 * proper 44px touch target per row.
 */
function MobilePlotLegend({
  entries,
  onToggle,
}: {
  entries: LegendEntry[];
  onToggle: (key: string, visible: boolean) => void;
}) {
  if (entries.length === 0) return null;

  return (
    <div className="mt-3 border border-gray-200 rounded-lg overflow-hidden bg-white">
      <div className="flex items-baseline justify-between gap-2 px-3 py-2 bg-gray-50 border-b border-gray-200">
        <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">
          Series
        </span>
        <span className="text-xs text-gray-400">Tap to show or hide</span>
      </div>
      <ul className="divide-y divide-gray-100">
        {entries.map((entry) => (
          <li key={entry.key}>
            <button
              type="button"
              aria-pressed={entry.visible}
              onClick={() => onToggle(entry.key, !entry.visible)}
              className={`flex w-full min-h-[44px] items-center gap-3 px-3 py-2 text-left transition-colors active:bg-gray-100 ${
                entry.visible ? '' : 'opacity-40'
              }`}
            >
              <svg
                width="20"
                height="8"
                viewBox="0 0 20 8"
                aria-hidden="true"
                className="shrink-0"
              >
                <line
                  x1="1"
                  y1="4"
                  x2="19"
                  y2="4"
                  stroke={entry.color}
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeDasharray={entry.dashed ? '5 3' : undefined}
                />
              </svg>
              <span className="min-w-0 flex-1 break-words text-sm text-gray-900">
                {entry.label}
              </span>
              {entry.detail && (
                <span className="shrink-0 text-xs font-medium text-gray-500 tabular-nums">
                  {entry.detail}
                </span>
              )}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

// Wrap a legend label: replace underscores with spaces and break at ~25 chars
function wrapLegendLabel(label: string | undefined, width = 25): string {
  if (!label) return '';
  const spaced = label.replace(/_/g, ' ');

  return wrap(spaced, { width, indent: '', trim: true, cut: false }).replace(/\n/g, '<br>');
}

// Convert a hex color to an rgba() string
function hexToRgba(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

// CI bands to render: wider interval → lower alpha (more transparent)
const CI_BANDS = [
  { lower: 'q_0.2', upper: 'q_0.8', alpha: 0.12 },
  { lower: 'q_0.3', upper: 'q_0.7', alpha: 0.22 },
] as const;

// Convert ISO 8601 duration to milliseconds
function durationToMs(isoStr: string | undefined): number | null {
  if (!isoStr) return null;
  try {
    return toSeconds(parse(isoStr)) * 1000;
  } catch {
    return null;
  }
}

// Convert ISO 8601 duration to human-readable format
function formatFrequency(freq: string | undefined): string {
  if (!freq) return 'N/A';
  
  try {
    // Parse ISO 8601 duration string (e.g., "PT3M" for 3 minutes)
    const duration = parse(freq);
    
    // Convert to seconds, then to milliseconds
    const seconds = toSeconds(duration);
    const milliseconds = seconds * 1000;
    
    // Use humanize-duration to format
    return humanizeDuration(milliseconds, { 
      largest: 2, 
      round: true,
      conjunction: ' and ',
      serialComma: false
    });
  } catch (error) {
    // If parsing fails, return the original string
    console.warn(`Failed to parse frequency "${freq}":`, error);
    return freq;
  }
}

interface SeriesDataItem {
  contextData: any[];
  testData: any[];
  series_id: number;
  series_name: string;
  unit?: string | null;
  forecasts?: ForecastsResponse;
  forecastsLoading?: boolean;
  forecastsError?: string;
}

interface TimeSeriesChartProps {
  challengeId: number;
  challengeName: string;
  challengeDescription?: string;
  registrationStart?: string;
  registrationEnd?: string;
  evaluationStart?: string;
  frequency?: string;
  horizon?: string;
  seriesId?: number;
  on_title_page?: boolean;
  definitionId?: number;
  status?: string;
}

export default function TimeSeriesChart({ challengeId, challengeName, challengeDescription, registrationStart, registrationEnd, evaluationStart, frequency, horizon, seriesId, on_title_page = false, definitionId, status }: TimeSeriesChartProps) {
  const [seriesData, setSeriesData] = useState<SeriesDataItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedSeries, setExpandedSeries] = useState<Set<number>>(new Set());

  const isMobile = useIsMobile();

  // Explicit show/hide overrides driven by the mobile legend, keyed by
  // `${series_id}|${traceKey}`. An absent key means "use the default", so on
  // desktop — where the mobile legend never renders and nothing writes here —
  // this map stays empty and trace visibility is exactly what it always was.
  const [traceVisibility, setTraceVisibility] = useState<Record<string, boolean>>({});

  const setTraceVisible = useCallback((key: string, visible: boolean) => {
    setTraceVisibility(prev => ({ ...prev, [key]: visible }));
  }, []);

  // Forecast filter state
  const [maxSizeFilter, setMaxSizeFilter] = useState<string>('');
  const [architectureFilter, setArchitectureFilter] = useState<string>('');
  const [modelSearchFilter, setModelSearchFilter] = useState<string>('');
  
  // Models data
  const [models, setModels] = useState<Model[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);

  // Function to load data and forecasts for a specific series
  const loadForecastsForSeries = useCallback(async (seriesId: number) => {
    // Check if data is already loaded or loading
    setSeriesData(prev => {
      const series = prev.find(s => s.series_id === seriesId);
      if (!series || (series.forecasts && series.contextData?.length > 0)) {
        return prev;
      }
      
      // Mark as loading
      return prev.map(s => 
        s.series_id === seriesId 
          ? { ...s, forecastsLoading: true, forecastsError: undefined }
          : s
      );
    });

    try {
      // Get the series metadata to fetch context and test data
      const series = await getChallengeSeries(challengeId);
      const currentSeries = series.find(s => s.series_id === seriesId);
      
      if (!currentSeries) {
        throw new Error(`Series ${seriesId} not found`);
      }

      const startTime = currentSeries.context_start_time;
      const endTimeContext = currentSeries.context_end_time;
      const endTimeTest = currentSeries.end_time;

      if (!startTime || !endTimeContext || !endTimeTest) {
        throw new Error(`Missing time range for series ${seriesId}`);
      }

      // Load context data, test data, and forecasts in parallel
      const [dataContext, dataTest, forecasts] = await Promise.all([
        getSeriesData(challengeId, seriesId, startTime, endTimeContext),
        getSeriesData(challengeId, seriesId, endTimeContext, endTimeTest),
        getSeriesForecasts(challengeId, seriesId)
      ]);

      // Update with loaded data and forecasts
      setSeriesData(prev => prev.map(s =>
        s.series_id === seriesId
          ? {
              ...s,
              contextData: dataContext.data,
              testData: dataTest.data,
              unit: currentSeries.unit,
              forecasts,
              forecastsLoading: false
            }
          : s
      ));
    } catch (err) {
      console.error(`Failed to fetch data for series ${seriesId}:`, err);
      setSeriesData(prev => prev.map(s => 
        s.series_id === seriesId 
          ? { ...s, forecastsLoading: false, forecastsError: 'Failed to load data' }
          : s
      ));
    }
  }, [challengeId]);

  const toggleSeries = (seriesId: number) => {
    setExpandedSeries(prev => {
      const newSet = new Set(prev);
      if (newSet.has(seriesId)) {
        newSet.delete(seriesId);
      } else {
        newSet.add(seriesId);
        // Load forecasts when expanding
        loadForecastsForSeries(seriesId);
      }
      return newSet;
    });
  };

  // Fetch models for the challenge
  useEffect(() => {
    async function fetchModels() {
      try {
        setModelsLoading(true);
        const modelsData = await getRoundModels(challengeId);
        
        // API returns models as a direct array
        const modelsList = Array.isArray(modelsData) ? modelsData : [];
        setModels(modelsList);
      } catch (err) {
        console.error('Failed to fetch models:', err);
        setModels([]);
      } finally {
        setModelsLoading(false);
      }
    }
    fetchModels();
  }, [challengeId]);

  useEffect(() => {
    async function fetchData() {
      try {
        setLoading(true);
        setError(null);

        // Fetch all series for this challenge
        const series = await getChallengeSeries(challengeId);

        // Filter by seriesId if provided
        const filteredSeries = seriesId 
          ? series.filter(s => s.series_id === seriesId)
          : series;
        
        if (seriesId && filteredSeries.length === 0) {
          console.warn(`Series ${seriesId} not found in challenge ${challengeId}`);
        }
        
        // Create series items with metadata only (data will be loaded on demand)
        const validData = filteredSeries.map((s) => ({
          contextData: [],
          testData: [],
          series_id: s.series_id,
          series_name: s.name,
          forecasts: undefined,
          forecastsLoading: false,
          forecastsError: undefined
        } as SeriesDataItem));
        
        setSeriesData(validData);
        
        // Expand the first series by default and load its data
        if (validData.length > 0) {
          const firstSeriesId = validData[0].series_id;
          setExpandedSeries(new Set([firstSeriesId]));
          // Load data and forecasts for the first series
          loadForecastsForSeries(firstSeriesId);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load time series data');
      } finally {
        setLoading(false);
      }
    }

    fetchData();
  }, [challengeId, loadForecastsForSeries, seriesId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 text-red-700 p-4 rounded-lg">
        <p className="font-semibold">Error loading time series data</p>
        <p className="text-sm">{error}</p>
      </div>
    );
  }

  if (seriesData.length === 0) {
    return (
      <div className="text-center py-8 text-gray-500">
        No time series data available for this challenge.
      </div>
    );
  }

  // Filter forecasts based on user input by matching with models
  const filterForecasts = (forecasts: Record<string, ForecastData>) => {
    
    const filtered = Object.entries(forecasts).filter(([modelName, forecastData]) => {
      // Find the matching model from the models list
      const model = models.find(m => {
        const match1 = m.name === modelName;
        const match2 = m.readable_id === forecastData.model_id;
        const match3 = m.readable_id === modelName;
        return match1 || match2 || match3;
      });
      
      if (!model) {
        return false;
      }
      
      // Filter by max_size - use model data if available
      if (maxSizeFilter) {
        const filterValue = parseFloat(maxSizeFilter);
        if (!isNaN(filterValue)) {
          if (model.model_size !== undefined && model.model_size > filterValue) {
            return false;
          }
        }
      }
      
      // Filter by architecture - use model data if available
      if (architectureFilter) {
        if (model.architecture) {
          if (!model.architecture.toLowerCase().includes(architectureFilter.toLowerCase())) {
            return false;
          }
        } else {
          return false;
        }
      }
      
      // Filter by model name/ID search
      if (modelSearchFilter) {
        const searchLower = modelSearchFilter.toLowerCase();
        const modelIdMatch = model.readable_id?.toLowerCase() === searchLower;
        const modelNameMatch = model.name?.toLowerCase().includes(searchLower);
        if (!modelIdMatch && !modelNameMatch) {
          return false;
        }
      }
      
      return true;
    }).reduce((acc, [key, value]) => {
      acc[key] = value;
      return acc;
    }, {} as Record<string, ForecastData>);
    return filtered;
  };

  // Get unique architectures and max sizes for filter options from models data
  const getFilterOptions = () => {
    const architectures = new Set<string>();
    const maxSizes = new Set<number>();
    
    models.forEach(model => {
      if (model.architecture) architectures.add(model.architecture);
      if (model.model_size !== undefined) maxSizes.add(model.model_size);
    });
    
    return {
      architectures: Array.from(architectures).sort(),
      maxSizes: Array.from(maxSizes).sort((a, b) => a - b)
    };
  };

  const filterOptions = getFilterOptions();

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <div className="mb-6">
        {on_title_page && definitionId ? (
          <div className="mb-4">
            <div className="flex items-center gap-3 mb-2">
              <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-green-100 text-green-800 animate-pulse">
                <span className="w-2 h-2 bg-green-500 rounded-full mr-2"></span>
                Now Live!
              </span>
            </div>
            <h2 className="text-xl font-semibold text-gray-900">
              Currently competing in challenge:{' '}
              <Link href={`/challenges/${definitionId}/${challengeId}`}>
                <span className="text-blue-600 hover:text-blue-700 underline decoration-2 underline-offset-2 transition-colors">
                  {challengeName}
                </span>
              </Link>
            </h2>
          </div>
        ) : (
          <h2 className="text-xl font-semibold mb-4">{challengeName}</h2>
        )}
        {!on_title_page && (
          <>
            {challengeDescription && (
              <p className="text-sm text-gray-600 mb-4 italic">{challengeDescription}</p>
            )}
            <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-5 2xl:grid-cols-6 gap-4 auto-rows-auto">
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wide">Status</p>
              <p className={`text-sm font-semibold uppercase ${
                status === 'active'
                  ? 'text-green-600'
                  : status === 'completed'
                  ? 'text-blue-600'
                  : status === 'registration'
                  ? 'text-yellow-600'
                  : 'text-gray-600'
              }`}>
                {status || 'N/A'}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wide">ID</p>
              <p className="text-sm font-semibold text-gray-900">{challengeId}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wide">Series</p>
              <p className="text-sm font-semibold text-gray-900">{seriesData.length}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wide">Models</p>
              <p className="text-sm font-semibold text-gray-900">
                {seriesData.length > 0 && seriesData[0].forecasts?.forecasts 
                  ? Object.keys(seriesData[0].forecasts.forecasts).length 
                  : 0}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wide">Context</p>
              <p className="text-sm font-semibold text-gray-900">
                {seriesData.length > 0 && seriesData[0].contextData?.length 
                  ? seriesData[0].contextData.length 
                  : 'N/A'}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wide">Frequency</p>
              <p className="text-sm font-semibold text-gray-900">
                {formatFrequency(frequency)}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wide">Horizon</p>
              <p className="text-sm font-semibold text-gray-900">
                {horizon || 'N/A'}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wide">Registration Start</p>
              <p className="text-sm font-semibold text-gray-900">
                {registrationStart ? new Date(registrationStart).toLocaleString('en-US', { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZoneName: 'short' }) : 'N/A'}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wide">Registration End</p>
              <p className="text-sm font-semibold text-gray-900">
                {registrationEnd ? new Date(registrationEnd).toLocaleString('en-US', { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZoneName: 'short' }) : 'N/A'}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wide">Start of Evaluation</p>
              <p className="text-sm font-semibold text-gray-900">
                {evaluationStart ? new Date(evaluationStart).toLocaleString('en-US', { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZoneName: 'short' }) : 'N/A'}
              </p>
            </div>
          </div>
        </div>
          </>
        )}
        
        {/* Forecast Filters */}
        {!on_title_page && (
        <div className="mt-6">
          <h3 className="text-sm font-semibold text-gray-700 mb-3">Filter Forecasts</h3>
          <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {/* Model Search */}
              <div>
                <label htmlFor="model-search" className="block text-xs font-medium text-gray-700 mb-1">
                  Model Name/ID Search
                </label>
                <input
                  id="model-search"
                  type="text"
                  placeholder="Search by name or ID..."
                  value={modelSearchFilter}
                  onChange={(e) => setModelSearchFilter(e.target.value)}
                  className="w-full px-3 py-2 text-base sm:text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>
              
              {/* Max Size Filter */}
              <div>
                <label htmlFor="max-size" className="block text-xs font-medium text-gray-700 mb-1">
                  Max Size (parameters)
                </label>
                <input
                  id="max-size"
                  type="number"
                  placeholder="Max parameters..."
                  value={maxSizeFilter}
                  onChange={(e) => setMaxSizeFilter(e.target.value)}
                  className="w-full px-3 py-2 text-base sm:text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
                {filterOptions.maxSizes.length > 0 && (
                  <p className="text-xs text-gray-500 mt-1">
                    Available: {filterOptions.maxSizes.join(', ')}
                  </p>
                )}
              </div>
              
              {/* Architecture Filter */}
              <div>
                <label htmlFor="architecture" className="block text-xs font-medium text-gray-700 mb-1">
                  Architecture
                </label>
                <select
                  id="architecture"
                  value={architectureFilter}
                  onChange={(e) => setArchitectureFilter(e.target.value)}
                  className="w-full px-3 py-2 text-base sm:text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white"
                >
                  <option value="">All architectures</option>
                  {filterOptions.architectures.map((arch) => (
                    <option key={arch} value={arch}>{arch}</option>
                  ))}
                </select>
              </div>
            </div>
            
            {/* Clear Filters Button */}
            {(maxSizeFilter || architectureFilter || modelSearchFilter) && (
              <div className="mt-3 flex justify-end">
                <button
                  onClick={() => {
                    setMaxSizeFilter('');
                    setArchitectureFilter('');
                    setModelSearchFilter('');
                  }}
                  className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
                >
                  Clear Filters
                </button>
              </div>
            )}
          </div>
        </div>
        )}
      </div>
      <div className="space-y-6">{seriesData.map((series: any) => {
          // Prepare traces for context and test data
          const traces: any[] = [];

          // Rows for the mobile HTML legend, collected alongside the traces so the
          // two can never drift apart.
          const legendEntries: LegendEntry[] = [];
          // Whether any forecast in this plot actually produced a shaded band. The
          // caption below the plot explains the bands, so it is only shown when
          // there is something to explain.
          let hasAnyBand = false;
          const visibilityKey = (traceKey: string) => `${series.series_id}|${traceKey}`;
          const resolveVisible = (traceKey: string, fallback: boolean) =>
            traceVisibility[visibilityKey(traceKey)] ?? fallback;

          // Ground truth trace (solid black line) — pushed first so it renders behind all other traces
          if (series.testData && series.testData.length > 0) {
            const plainName = `Live: ${series.series_name || series.series_id}`;
            const visible = resolveVisible('observed-live', true);
            traces.push({
              x: series.testData.map((d: any) => d.ts),
              y: series.testData.map((d: any) => d.value),
              type: 'scatter',
              mode: 'lines',
              name: isMobile ? plainName : wrapLegendLabel(plainName),
              line: { width: 2, color: '#000000', dash: 'solid' },
              legendgroup: 'actual',
              legendgrouptitle: { text: 'Observations' },
              visible: visible ? true : 'legendonly',
              hovertemplate: '%{x|%Y-%m-%d %H:%M} UTC<br>Value: %{y:.4g}<extra>%{fullData.name}</extra>',
            });
            legendEntries.push({
              key: visibilityKey('observed-live'),
              label: plainName,
              color: '#000000',
              dashed: false,
              visible,
            });
          }

          // Context data trace (solid blue line)
          if (series.contextData && series.contextData.length > 0) {
            const visible = resolveVisible('observed-context', true);
            traces.push({
              x: series.contextData.map((d: any) => d.ts),
              y: series.contextData.map((d: any) => d.value),
              type: 'scatter',
              mode: 'lines',
              name: 'Historical Data',
              line: { width: 2, color: '#2563eb' },
              marker: { size: 4 },
              legendgroup: 'actual',
              visible: visible ? true : 'legendonly',
              hovertemplate: '%{x|%Y-%m-%d %H:%M} UTC<br>Value: %{y:.4g}<extra>%{fullData.name}</extra>',
            });
            legendEntries.push({
              key: visibilityKey('observed-context'),
              label: 'Historical Data',
              color: '#2563eb',
              dashed: false,
              visible,
            });
          }

          // Add forecast traces for each model
          if (series.forecasts?.forecasts) {
            const colors = ['#dc2626', '#16a34a', '#9333ea', '#ea580c', '#0891b2', '#ca8a04'];
            
            // Get the last context data point to connect forecasts
            const lastActualPoint = series.contextData && series.contextData.length > 0 
              ? series.contextData[series.contextData.length - 1] 
              : null;
            
            // Apply filters to forecasts
            const filteredForecasts = filterForecasts(series.forecasts.forecasts);
            
            // Sort models by MASE (ascending - best first)
            const modelEntries = Object.entries(filteredForecasts)
              .map(([modelName, forecastData]: [string, ForecastData]) => ({
                modelName,
                forecastData,
                label: forecastData?.label,
                mase: forecastData?.current_mase
              }))
              .sort((a, b) => {
                // Handle undefined/null MASE values - put them at the end
                if (a.mase === undefined || a.mase === null) return 1;
                if (b.mase === undefined || b.mase === null) return -1;
                return a.mase - b.mase;
              });
            
            let visibleForecastCount = 0;
            
            modelEntries.forEach(({ modelName, forecastData, label, mase }, idx) => {
              const dataArray = forecastData?.data;
              if (Array.isArray(dataArray) && dataArray.length > 0 && lastActualPoint) {
                const maseText =
                  mase !== undefined && mase !== null
                    ? `MASE: ${typeof mase === 'number' ? mase.toFixed(3) : mase}`
                    : null;
                const fullLabel = maseText ? `${label} (${maseText})` : label;
                // Desktop keeps the hard wrap; on mobile the label lives in HTML,
                // so the 25-character `<br>` hack is neither needed nor wanted.
                const displayName = isMobile ? String(fullLabel ?? '') : wrapLegendLabel(fullLabel);

                // Prepend the last actual point to connect the forecast line
                const connectedX = [lastActualPoint.ts, ...dataArray.map((d: any) => d.ts)];
                const connectedY = [lastActualPoint.value, ...dataArray.map((d: any) => d.y)];

                // Show only the best 2 forecasts by default
                const traceKey = `forecast-${idx}`;
                const isVisible = resolveVisible(traceKey, visibleForecastCount < 2);
                visibleForecastCount++;

                const color = colors[idx % colors.length];

                legendEntries.push({
                  key: visibilityKey(traceKey),
                  label: String(label ?? modelName),
                  detail: maseText ?? undefined,
                  color,
                  dashed: true,
                  visible: isVisible,
                });

                // CI bands: push upper + lower (fill tonexty) pairs BEFORE the forecast
                // line so the line renders on top. Each pair must be consecutive for
                // fill: 'tonexty' to fill between them correctly.
                CI_BANDS.forEach(({ lower, upper, alpha }) => {
                  // A band is drawn only where the model actually stated a spread.
                  // Two cases produce no spread and both are rendered as a gap
                  // rather than as a flat line hugging the forecast:
                  //   - the quantile is missing at this point;
                  //   - the two bounds are equal, i.e. the model submitted identical
                  //     values for both levels. Some models do this on a large share
                  //     of their points. Drawn literally it is a zero-height band,
                  //     which looks exactly like a band-rendering bug; drawing nothing
                  //     says what the model actually said, which is "no uncertainty
                  //     here".
                  const bandAt = (d: { ci?: Record<string, number | undefined> }): [number, number] | null => {
                    const lo = d.ci?.[lower];
                    const hi = d.ci?.[upper];
                    if (lo === undefined || hi === undefined) return null;
                    if (lo === hi) return null;
                    return [lo, hi];
                  };

                  const hasCI = dataArray.some((d: any) => bandAt(d) !== null);
                  if (!hasCI) return;
                  hasAnyBand = true;

                  // `null` breaks the fill at that x, leaving a gap. The leading
                  // entry anchors the band to the last actual so it starts at the
                  // same place as the forecast line.
                  const ciUpperY = [
                    lastActualPoint.value,
                    ...dataArray.map((d: any) => bandAt(d)?.[1] ?? null),
                  ];
                  const ciLowerY = [
                    lastActualPoint.value,
                    ...dataArray.map((d: any) => bandAt(d)?.[0] ?? null),
                  ];

                  // Upper bound (invisible line, no legend entry)
                  traces.push({
                    x: connectedX,
                    y: ciUpperY,
                    type: 'scatter',
                    mode: 'lines',
                    line: { width: 0, color: 'transparent' },
                    // Explicit: the nulls above are gaps, not points to bridge.
                    connectgaps: false,
                    showlegend: false,
                    legendgroup: `forecast-${idx}`,
                    visible: isVisible ? true : 'legendonly',
                    hoverinfo: 'skip',
                  });

                  // Lower bound – fills to the upper bound trace above it
                  traces.push({
                    x: connectedX,
                    y: ciLowerY,
                    type: 'scatter',
                    mode: 'lines',
                    fill: 'tonexty',
                    fillcolor: hexToRgba(color, alpha),
                    line: { width: 0, color: 'transparent' },
                    connectgaps: false,
                    showlegend: false,
                    legendgroup: `forecast-${idx}`,
                    visible: isVisible ? true : 'legendonly',
                    hoverinfo: 'skip',
                  });
                });

                // Forecast line rendered on top of CI bands
                traces.push({
                  x: connectedX,
                  y: connectedY,
                  type: 'scatter',
                  mode: 'lines',
                  name: displayName,
                  line: { width: 2, dash: 'dash', color },
                  visible: isVisible ? true : 'legendonly',
                  legendgroup: `forecast-${idx}`,
                  legendgrouptitle: idx === 0 ? { text: 'Forecasts' } : undefined,
                  hovertemplate: '%{x|%Y-%m-%d %H:%M} UTC<br>Value: %{y:.4g}<extra>%{fullData.name}</extra>',
                });
              }
            });
          }

          const plotData: PlotParams['data'] = traces;

          // Compute default zoom: show last 3× horizon of context + full forecast window.
          const defaultXRange: [string, string] | undefined = (() => {
            const horizonMs = durationToMs(horizon);

            if (!horizonMs || !series.contextData?.length) {
              return undefined;
            }

            const contextEnd = new Date(
              series.contextData[series.contextData.length - 1].ts
            );

            const rangeStart = new Date(contextEnd.getTime() - 3 * horizonMs);
            const rangeEnd = new Date(contextEnd.getTime() + 1.1 * horizonMs);

            return [rangeStart.toISOString(), rangeEnd.toISOString()];
          })();

          // Plotly's `uirevision` deliberately lets user-made UI state win over
          // incoming props. On mobile the show/hide state comes from React, not
          // from Plotly's own legend, so the revision has to change whenever that
          // state does — otherwise a tap would be silently discarded. There is no
          // zoom/pan state to lose, because `dragmode` is off on mobile.
          const visibilityRevision = legendEntries
            .map(entry => `${entry.key}=${entry.visible ? 1 : 0}`)
            .join(',');

          const layout: PlotParams['layout'] = isMobile
            ? {
                xaxis: {
                  title: { text: '' },
                  showgrid: true,
                  type: 'date',
                  domain: [0, 1],
                  range: defaultXRange,
                  rangeslider: { visible: false },
                  automargin: true,
                  nticks: 4,
                  tickangle: 0,
                  tickfont: { size: 10 },
                },
                yaxis: {
                  title: { text: series.unit ?? '' },
                  autorange: true,
                  showgrid: true,
                  automargin: true,
                  tickfont: { size: 10 },
                },
                hovermode: 'closest',
                showlegend: false,
                dragmode: false,
                autosize: true,
                margin: MOBILE_PLOT_MARGIN,
                uirevision: `mobile:${visibilityRevision}`,
              }
            : {
                xaxis: {
                  title: { text: '' },
                  showgrid: true,
                  type: 'date',
                  domain: [0, 0.82],
                  range: defaultXRange,
                  rangeslider: { visible: true },
                },
                yaxis: {
                  title: { text: series.unit ?? '' },
                  autorange: true,
                  showgrid: true,
                },
                hovermode: 'closest',
                showlegend: true,
                legend: {
                  orientation: 'v',
                  yanchor: 'top',
                  y: 1,
                  xanchor: 'left',
                  x: 0.85,
                  font: { size: 10 },
                  bgcolor: 'rgba(255, 255, 255, 0.95)',
                  bordercolor: '#E5E7EB',
                  borderwidth: 1,
                },
                autosize: true,
                margin: { l: 60, r: 20, t: 60, b: 50 },
                uirevision: "static"
              };

          const isExpanded = expandedSeries.has(series.series_id);

          return (
            <div key={series.series_id} className="w-full border border-gray-200 rounded-lg overflow-hidden">
              <button
                onClick={() => toggleSeries(series.series_id)}
                className="w-full px-4 py-3 flex flex-wrap sm:flex-nowrap items-center justify-between gap-x-3 gap-y-1 bg-gray-50 hover:bg-gray-100 transition-colors"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <svg
                    className={`w-5 h-5 transition-transform flex-shrink-0 ${isExpanded ? 'rotate-90' : ''}`}
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                  </svg>
                  <div className="text-left min-w-0">
                    {/* Series names are long unbroken tokens (…power_plant_generation);
                        without min-w-0 the flex item refuses to shrink and the name is
                        clipped off-screen on a phone. */}
                    <h3 className="font-semibold text-gray-900 break-words">
                      {series.series_name || `Series ${series.series_id}`}
                    </h3>
                  </div>
                </div>
                <span className="text-sm text-gray-500 w-full sm:w-auto">
                  {isExpanded ? 'Click to collapse' : 'Click to expand'}
                </span>
              </button>
              {isExpanded && (
                <div className="p-4 relative">
                  {series.forecastsLoading && (
                    <div className="absolute top-0 left-0 right-0 bg-blue-50 border border-blue-200 rounded-lg p-3 mx-4 mt-4 z-10 flex items-center gap-3">
                      <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-500"></div>
                      <p className="text-sm text-blue-700">Loading forecasts...</p>
                    </div>
                  )}
                  {series.forecastsError && !series.forecastsLoading && (
                    <div className="bg-yellow-50 border border-yellow-200 text-yellow-700 p-4 rounded-lg mb-4">
                      <p className="font-semibold">Warning</p>
                      <p className="text-sm">{series.forecastsError}</p>
                      <button
                        onClick={() => loadForecastsForSeries(series.series_id)}
                        className="mt-2 text-sm underline hover:no-underline"
                      >
                        Retry loading forecasts
                      </button>
                    </div>
                  )}
                  {series.contextData.length > 0 && (
                    <>
                      <Plot
                        data={plotData}
                        layout={layout}
                        config={isMobile ? MOBILE_PLOT_CONFIG : undefined}
                        style={{
                          width: '100%',
                          height: isMobile ? MOBILE_PLOT_HEIGHT : '400px',
                        }}
                        useResizeHandler
                      />
                      {isMobile && (
                        <MobilePlotLegend
                          entries={legendEntries}
                          onToggle={setTraceVisible}
                        />
                      )}
                      {hasAnyBand && (
                        <p className="mt-2 px-1 text-xs leading-relaxed text-gray-500">
                          Shaded areas are the forecast&apos;s quantile ranges: the lighter
                          band spans the 20th to 80th percentile, the darker one the 30th to
                          70th. They appear only for models that submit quantile forecasts,
                          and only where the model stated a spread — a gap means it predicted
                          the same value at both bounds.
                        </p>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export interface RankingFilters {
  definition_id?: number;
  frequency_horizon?: string;
  calculation_date?: string;
  limit?: number;
  /**
   * Fetch every scope of this type in a single request instead of one request
   * per scope. `limit` then applies per scope. Mutually exclusive with
   * definition_id / frequency_horizon.
   */
  scope_type?: 'definition' | 'frequency_horizon';
  /**
   * Which metric drove the ELO ranking. Defaults to 'mase' server-side, which is
   * the board this UI shows. 'sql' is fetched only to learn *who is eligible* for
   * the probabilistic board — see `collectSqlEligible`.
   */
  metric?: 'mase' | 'sql';
}

export interface ModelRanking {
  model_id: number;
  model_name: string;
  readable_id?: string;
  username?: string;
  organization_name: string;
  architecture?: string;
  model_size?: number;
  elo_rating_median: number;
  elo_ci_lower: number;
  elo_ci_upper: number;
  elo_ci_lower_diff?: number;
  elo_ci_upper_diff?: number;
  matches_played: number;
  n_bootstraps: number;
  rank_position: number;
  avg_mase: number | null;
  mase_std: number | null;
  /**
   * Cumulative Scaled Quantile Loss. Written to every ranking row regardless of
   * which metric drove the ELO, so it arrives on the default mase board too.
   * It is *not* filtered by has_quantiles: for a point-only model this is the
   * degenerate point-forecast substitution, which is why the UI only shows it
   * for models on the SQL board.
   */
  avg_sql: number | null;
  sql_std: number | null;
  evaluated_count: number | null;
  calculated_at?: string;
  calculation_date: string;
  // Present so bulk (scope_type) responses can be grouped by scope.
  scope_id?: string | null;
  definition_id?: number | null;
}

export interface RankingsResponse {
  rankings: ModelRanking[];
  filters_applied: Record<string, any>;
}

export interface ChallengeDefinition {
  id: number;
  name: string;
}

export interface FilterOptions {
  definitions: ChallengeDefinition[];
  frequency_horizons: string[];
  calculation_dates: Array<{
    calculation_date: string;
    is_month_end: boolean;
  }>;
}

export interface TimeRangeRanking {
  rank: number;
  total_models: number;
  rounds_participated: number;
  avg_mase: number | null;
  stddev_mase: number | null;
  min_mase: number | null;
  max_mase: number | null;
  elo_score: number | null;
}

export interface DefinitionRanking {
  definition_id: number;
  definition_name: string;
  rankings_7d?: TimeRangeRanking;
  rankings_30d?: TimeRangeRanking;
  rankings_90d?: TimeRangeRanking;
  rankings_365d?: TimeRangeRanking;
}

export interface DailyRanking {
  calculation_date: string;
  elo_score: number;
  elo_ci_lower: number;
  elo_ci_upper: number;
  rank_position: number;
}

export interface DefinitionRankingWithHistory {
  definition_id: number;
  definition_name: string;
  scope_type: string;
  scope_id: string;
  daily_rankings: DailyRanking[];
}

export interface ModelDetails {
  readable_id: string;
  name: string;
  model_family: string;
  model_size: number;
  hosting: string;
  architecture: string;
  pretraining_data: string;
  publishing_date: string;
  // Optional discovery / provenance metadata (see backend ticket #43).
  paper_url?: string | null;
  repo_url?: string | null;
  website_url?: string | null;
  description?: string | null;
  arxiv_id?: string | null;
}

/**
 * Single row in `GET /api/v1/models` — the flat list of every registered model.
 * No page consumes it since the hard-coded Models tab was removed; the endpoint
 * stays as the service-layer mirror of the dashboard-api.
 */
export interface ModelListItem {
  id: number;
  readable_id: string | null;
  name: string;
  model_family: string | null;
  model_size: number | null;
  architecture: string | null;
  paper_url?: string | null;
  repo_url?: string | null;
  website_url?: string | null;
  arxiv_id?: string | null;
}

export interface ModelDetailRankings {
  model_id: number;
  model_name: string;
  definition_rankings: DefinitionRankingWithHistory[];
}

export interface SeriesInfo {
  series_id: number;
  series_name: string;
  series_unique_id: string;
  rounds_participated: number;
}

export interface DefinitionWithSeries {
  definition_id: number;
  definition_name: string;
  series: SeriesInfo[];
}

export interface ModelSeriesByDefinition {
  model_id: number;
  model_readable_id: string;
  model_name: string;
  definitions: DefinitionWithSeries[];
}

export async function getFilteredRankings(filters: RankingFilters = {}): Promise<RankingsResponse> {
  const params = new URLSearchParams();
  
  if (filters.scope_type) params.append('scope_type', filters.scope_type);
  if (filters.definition_id) params.append('definition_id', filters.definition_id.toString());
  if (filters.frequency_horizon) params.append('frequency_horizon', filters.frequency_horizon);
  if (filters.calculation_date) params.append('calculation_date', filters.calculation_date);
  if (filters.limit) params.append('limit', filters.limit.toString());
  if (filters.metric) params.append('metric', filters.metric);
  
  const url = `/api/v1/models/rankings${params.toString() ? '?' + params.toString() : ''}`;

  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to fetch rankings: ${response.status}`);
  }
  return response.json();
}

/**
 * The set of models entitled to show a Scaled Quantile Loss number, derived from a
 * `metric=sql` rankings response.
 *
 * The SQL board excludes point-only forecasts at *row* level (backend #64), so a model
 * reaches it only if it actually submitted distributions in this scope. Membership is
 * therefore the closest thing to a "this model forecasts probabilistically here" flag
 * the rankings API offers — there is no has_quantiles column on the aggregate rows.
 *
 * Known imprecision: for the handful of models that submit quantiles on some rounds and
 * not others, the avg_sql we then display still averages in their degenerate rounds, so
 * it reads slightly worse than their true probabilistic performance.
 */
export function collectSqlEligible(rankings: ModelRanking[]): Set<number> {
  return new Set(rankings.map((r) => r.model_id));
}

export async function getRankingFilters(): Promise<FilterOptions> {
  const url = '/api/v1/models/ranking-filters';

  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to fetch ranking filters: ${response.status}`);
  }
  const data = await response.json();
  // Callers read these three arrays straight from render, so a payload that is
  // missing them takes the whole page down with the error boundary rather than
  // failing in the fetch handler. Reject it here instead.
  if (
    !Array.isArray(data?.calculation_dates) ||
    !Array.isArray(data?.definitions) ||
    !Array.isArray(data?.frequency_horizons)
  ) {
    throw new Error('Unexpected ranking-filters payload');
  }
  return data;
}

export async function getModelDetails(modelId: string): Promise<ModelDetails> {
  const url = `/api/v1/models/${modelId}`;

  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to fetch model details: ${response.status}`);
  }
  const data = await response.json();
  return Array.isArray(data) ? data[0] : data;
}

export async function getModelRankings(modelId: string): Promise<ModelDetailRankings> {
  const url = `/api/v1/models/${modelId}/rankings`;

  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to fetch model rankings: ${response.status}`);
  }
  return response.json();
}

export interface ModelActiveRound {
  round_id: number;
  round_name: string;
  description: string | null;
  definition_id: number | null;
  definition_name: string | null;
  status: string;
  registration_start: string | null;
  registration_end: string | null;
  start_time: string | null;
  end_time: string | null;
  frequency: string | null;
  horizon: string | null;
}

export interface ModelActiveRoundsResponse {
  model_id: number;
  model_readable_id: string;
  model_name: string;
  rounds: ModelActiveRound[];
}

export async function getModelActiveRounds(modelId: string): Promise<ModelActiveRoundsResponse | null> {
  const url = `/api/v1/models/${modelId}/active-rounds`;

  try {
    const response = await fetch(url);
    if (!response.ok) {
      // 404 (endpoint not deployed yet, or unknown model) → treat as "no active rounds"
      return null;
    }
    return response.json();
  } catch (err) {
    console.error('Error fetching active rounds:', err);
    return null;
  }
}

export async function getModelSeriesByDefinition(modelId: string): Promise<ModelSeriesByDefinition> {
  const url = `/api/v1/models/${modelId}/series-by-definition`;

  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to fetch series by definition: ${response.status}`);
  }
  return response.json();
}

export async function getAllModels(): Promise<ModelListItem[]> {
  const response = await fetch('/api/v1/models');
  if (!response.ok) {
    throw new Error(`Failed to fetch models list: ${response.status}`);
  }
  return response.json();
}

export async function getModelSeriesForecasts(
  modelId: string, 
  definitionId: number, 
  seriesId: number,
  startDate?: string,
  endDate?: string
): Promise<import('@/src/types/challenge').ModelSeriesForecastsResponse> {
  const params = new URLSearchParams();
  if (startDate) params.append('start_date', startDate);
  if (endDate) params.append('end_date', endDate);
  
  const queryString = params.toString();
  const url = `/api/v1/models/${modelId}/definitions/${definitionId}/series/${seriesId}/forecasts${queryString ? '?' + queryString : ''}`;

  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to fetch series forecasts: ${response.status}`);
  }
  return response.json();
}

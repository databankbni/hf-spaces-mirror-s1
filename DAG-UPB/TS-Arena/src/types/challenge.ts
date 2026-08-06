export interface Challenge {
  challenge_id: number;
  name: string | null;
  status: string;
  start_time: string | null;
  end_time: string | null;
  description: string | null;
  n_time_series: number;
  registration_start?: string | null;
  registration_end?: string | null;
  context_length?: any;
  horizon?: string | null;
  created_at?: string | null;
  model_count?: number | null;
  forecast_count?: number | null;
  domains?: string[] | null;
  categories?: string[] | null;
  subcategories?: string[] | null;
  frequency?: string | null;
}

export interface ChallengeSeries {
  series_id: number;
  name: string | null;
  description: string | null;
  frequency: string | null;
  horizon: any;
  unit: string | null;
  endpoint_prefix: string | null;
  start_time: string | null;
  end_time: string | null;
  registration_start: string | null;
  registration_end: string | null;
  context_start_time: string | null;
  context_end_time: string | null;
  domain: string | null;
  category: string | null;
  subcategory: string | null;
}

export interface TimeSeriesDataPoint {
  ts: string;
  value: number;
}

export interface TimeSeriesData {
  data: TimeSeriesDataPoint[];
}

export interface ChallengeFilters {
  status?: 'active' | 'completed' | 'all';
  searchTerm?: string;
  domains?: string[];
  categories?: string[];
  frequencies?: string[];
  horizons?: string[];
  endDateFrom?: string;
  endDateTo?: string;
  challengeId?: string;
}

export interface ForecastDataPoint {
  ts: string;
  y: number;
  ci?: any;
}

export interface ForecastData {
  data: ForecastDataPoint[];
  label: string;
  current_mase?: number;
  model_id?: string;
  model_size?: number;
  architecture?: string;
}

export interface ForecastsResponse {
  forecasts: {
    [modelName: string]: ForecastData;
  };
}

export interface Model {
  readable_id: string;
  name: string;
  model_size?: number;
  architecture?: string;
  description?: string;
  created_at?: string;
}

export interface ModelsResponse {
  models: Model[];
}

export interface ChallengeDefinition {
  schedule_id: string;
  name: string;
  description: string;
  display_text?: string | null;
  domain: string | null;
  subdomain: string | null;
  context_length: number;
  horizon: string;
  frequency: string;
  id: number;
  next_registration_start?: string | null;
  next_registration_end?: string | null;
}

export interface DefinitionSeries {
  series_id: number;
  name: string | null;
  description: string | null;
  display_text: string | null;
  frequency: string | null;
  unique_id: string | null;
  domain: string | null;
  category: string | null;
  subcategory: string | null;
}

export interface ModelSeriesForecastPoint {
  ts: string;
  y: number;
  ci?: {
    "0.025"?: number;
    "0.975"?: number;
    [key: string]: number | undefined;
  };
}

export interface ModelSeriesRound {
  round_id: number;
  round_name: string;
  start_time: string;
  end_time: string;
  series_in_round: boolean;
  forecast_exists: boolean;
  forecasts: ModelSeriesForecastPoint[] | null;
}

export interface GroundTruthPoint {
  ts: string;
  value: number;
}

export interface ModelSeriesForecastsResponse {
  model_id: number;
  model_readable_id: string;
  model_name: string;
  definition_id: number;
  definition_name: string;
  series_id: number;
  series_name: string;
  series_unit: string | null;
  rounds: ModelSeriesRound[];
  ground_truth?: GroundTruthPoint[];
}

export interface DefinitionRound {
  id: number;
  round_name: string;
  name: string;
  description: string;
  status: string;
  registration_start: string;
  registration_end: string;
  start_time: string;
  end_time: string;
  context_length: number;
  horizon: string;
  frequency: string;
  model_count?: number;
  forecast_count?: number;
  domains: string[] | null;
  categories: string[] | null;
  subcategories: string[] | null;
}

export interface PaginationInfo {
  page: number;
  page_size: number;
  total_items: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}

export interface DefinitionRoundsResponse {
  items: DefinitionRound[];
  pagination: PaginationInfo;
}

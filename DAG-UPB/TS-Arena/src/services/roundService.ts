import type { Challenge, ChallengeSeries, TimeSeriesData, ForecastsResponse, ModelsResponse } from '@/src/types/challenge';

export interface ChallengeApiFilters {
  domains?: string[];
  categories?: string[];
  frequencies?: string[];
  horizons?: string[];
  endDateFrom?: string;
  endDateTo?: string;
  status?: string;
  searchTerm?: string;
}

export async function getChallenges(filters?: ChallengeApiFilters): Promise<Challenge[]> {
  const params = new URLSearchParams();
  
  if (filters) {
    // Add array filters
    filters.domains?.forEach(d => params.append('domain', d));
    filters.categories?.forEach(c => params.append('category', c));
    filters.frequencies?.forEach(f => params.append('frequency', f));
    filters.horizons?.forEach(h => params.append('horizon', h));
    
    // Add date filters - convert to ISO format
    if (filters.endDateFrom) {
      const fromDate = new Date(filters.endDateFrom);
      params.append('from', fromDate.toISOString());
    }
    if (filters.endDateTo) {
      const toDate = new Date(filters.endDateTo);
      // Set to end of day for 'to' date
      toDate.setHours(23, 59, 59, 999);
      params.append('to', toDate.toISOString());
    }
    
    // Add status filter
    if (filters.status && filters.status !== 'all') params.append('status', filters.status);
    
    // Add search term
    if (filters.searchTerm) params.append('search', filters.searchTerm);
  }
  
  const queryString = params.toString();
  const url = `/api/v1/rounds${queryString ? '?' + queryString : ''}`;
  
  console.log('Fetching challenges with filters:', url);
  
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error('Failed to fetch challenges');
  }
  return response.json();
}

export async function getRoundsMetadata(): Promise<{
  domains: string[];
  categories: string[];
  frequencies: string[];
  horizons: string[];
  statuses: string[];
  subcategories: string[];
}> {
  const response = await fetch('/api/v1/rounds/metadata');
  if (!response.ok) {
    throw new Error('Failed to fetch rounds metadata');
  }
  return response.json();
}

export async function getChallengeSeries(roundId: number): Promise<ChallengeSeries[]> {
  const response = await fetch(`/api/v1/rounds/${roundId}/series`);
  if (!response.ok) {
    throw new Error('Failed to fetch round series');
  }
  return response.json();
}

export async function getSeriesData(
  roundId: number,
  seriesId: number,
  startTime: string,
  endTime: string
): Promise<TimeSeriesData> {
  const params = new URLSearchParams({
    start_time: startTime,
    end_time: endTime,
  });
  const url = `/api/v1/rounds/${roundId}/series/${seriesId}/data?${params.toString()}`;
  console.log('getSeriesData calling:', url);
  const response = await fetch(url);
  if (!response.ok) {
    const errorText = await response.text();
    console.error('getSeriesData failed:', response.status, errorText);
    throw new Error('Failed to fetch series data');
  }
  return response.json();
}

export async function getSeriesForecasts(
  roundId: number,
  seriesId: number
): Promise<ForecastsResponse> {
  const url = `/api/v1/rounds/${roundId}/series/${seriesId}/forecasts`;
  console.log('getSeriesForecasts calling:', url);
  const response = await fetch(url);
  if (!response.ok) {
    const errorText = await response.text();
    console.error('getSeriesForecasts failed:', response.status, errorText);
    throw new Error('Failed to fetch forecasts');
  }
  return response.json();
}

export async function getRoundModels(
  roundId: number
): Promise<ModelsResponse> {
  const url = `/api/v1/rounds/${roundId}/models`;
  const response = await fetch(url);
  if (!response.ok) {
    const errorText = await response.text();
    console.error('getRoundModels failed:', response.status, errorText);
    throw new Error('Failed to fetch models');
  }
  return response.json();
}

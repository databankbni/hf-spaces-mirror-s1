import { NextResponse } from 'next/server';

import { createLogger } from '@/src/lib/logger';

const API_BASE_URL = process.env.NEXT_PUBLIC_DASH_BOARD_API_URL || '';
const API_KEY = process.env.NEXT_PUBLIC_DASH_BOARD_API_KEY || '';

const log = createLogger('/api/v1/rounds/[roundId]/series/[seriesId]/data');

export async function GET(
  request: Request,
  { params }: { params: Promise<{ roundId: string; seriesId: string }> }
) {
  const { roundId, seriesId } = await params;
  const { searchParams } = new URL(request.url);
  const startTime = searchParams.get('start_time');
  const endTime = searchParams.get('end_time');

  if (!startTime || !endTime) {
    return NextResponse.json(
      { error: 'start_time and end_time query parameters are required' },
      { status: 400 }
    );
  }
  
  const queryParams = new URLSearchParams({
    start_time: startTime,
    end_time: endTime,
  });
  
  const path = `/api/v1/rounds/${roundId}/series/${seriesId}/data?${queryParams.toString()}`;
  const url = `${API_BASE_URL}${path}`;

  log.debug(`upstream GET ${path}`);

  try {
    const response = await fetch(url, {
      headers: {
        'X-API-Key': API_KEY,
      }
    });

    if (!response.ok) {
      const errorText = await response.text();
      log.error(`upstream ${response.status} for ${path}`, errorText);
      return NextResponse.json(
        { error: 'Failed to fetch series data', details: errorText, externalStatus: response.status },
        { status: response.status }
      );
    }
    
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    log.error('failed to fetch series data', error);
    return NextResponse.json(
      { error: 'Internal server error', details: error instanceof Error ? error.message : String(error) },
      { status: 500 }
    );
  }
}

import { NextResponse } from 'next/server';

const API_BASE_URL = process.env.NEXT_PUBLIC_DASH_BOARD_API_URL || '';
const API_KEY = process.env.NEXT_PUBLIC_DASH_BOARD_API_KEY || '';

export async function GET(
  request: Request,
  { params }: { params: Promise<{ roundId: string; seriesId: string }> }
) {
  const { roundId, seriesId } = await params;
  const { searchParams } = new URL(request.url);
  const startTime = searchParams.get('start_time');
  const endTime = searchParams.get('end_time');
  
  console.log('Data API route - params:', { roundId, seriesId, startTime, endTime });
  
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
  
  const url = `${API_BASE_URL}/api/v1/rounds/${roundId}/series/${seriesId}/data?${queryParams.toString()}`;
  
  try {
    const response = await fetch(url, {
      headers: {
        'X-API-Key': API_KEY,
      }
    });
    
    console.log('Data API response status:', response.status);
    
    if (!response.ok) {
      const errorText = await response.text();
      console.error('Data API error response:', response.status, errorText);
      return NextResponse.json(
        { error: 'Failed to fetch series data', details: errorText, externalStatus: response.status },
        { status: response.status }
      );
    }
    
    const data = await response.json();
    console.log('Data API success');
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error fetching series data:', error);
    return NextResponse.json(
      { error: 'Internal server error', details: error instanceof Error ? error.message : String(error) },
      { status: 500 }
    );
  }
}

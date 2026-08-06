import { NextResponse } from 'next/server';

const API_BASE_URL = process.env.NEXT_PUBLIC_DASH_BOARD_API_URL || '';
const API_KEY = process.env.NEXT_PUBLIC_DASH_BOARD_API_KEY || '';

export async function GET(
  request: Request,
  { params }: { params: Promise<{ roundId: string; seriesId: string }> }
) {
  const { roundId, seriesId } = await params;
  const url = `${API_BASE_URL}/api/v1/rounds/${roundId}/series/${seriesId}/forecasts`;
  
  console.log('Forecasts API route - params:', { roundId, seriesId });
  
  try {
    const response = await fetch(url, {
      headers: {
        'X-API-Key': API_KEY,
      }
    });
    
    console.log('Forecasts API response status:', response.status);
    
    if (!response.ok) {
      const errorText = await response.text();
      console.error('Forecasts API error response:', response.status, errorText);
      return NextResponse.json(
        { error: 'Failed to fetch forecasts', details: errorText, externalStatus: response.status },
        { status: response.status }
      );
    }
    
    const data = await response.json();
    console.log('Forecasts API success, data keys:', Object.keys(data));
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error fetching forecasts:', error);
    return NextResponse.json(
      { error: 'Internal server error', details: error instanceof Error ? error.message : String(error) },
      { status: 500 }
    );
  }
}

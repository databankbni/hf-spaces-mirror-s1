import { NextRequest, NextResponse } from 'next/server';

const API_BASE_URL = process.env.NEXT_PUBLIC_DASH_BOARD_API_URL || '';
const API_KEY = process.env.NEXT_PUBLIC_DASH_BOARD_API_KEY || '';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ modelId: string; definitionId: string; seriesId: string }> }
) {
  const { modelId, definitionId, seriesId } = await params;
  
  // Parse IDs as numbers for the external API
  const modelIdNum = parseInt(modelId, 10);
  const definitionIdNum = parseInt(definitionId, 10);
  const seriesIdNum = parseInt(seriesId, 10);
  
  if (isNaN(modelIdNum) || isNaN(definitionIdNum) || isNaN(seriesIdNum)) {
    return NextResponse.json({ error: 'Invalid model ID, definition ID, or series ID' }, { status: 400 });
  }
  
  // Get query parameters for date filtering
  const searchParams = request.nextUrl.searchParams;
  const startDate = searchParams.get('start_date');
  const endDate = searchParams.get('end_date');
  
  // Build URL with query parameters
  const urlParams = new URLSearchParams();
  if (startDate) urlParams.append('start_time', startDate);
  if (endDate) urlParams.append('end_time', endDate);
  
  const queryString = urlParams.toString();
  const url = `${API_BASE_URL}/api/v1/models/${modelIdNum}/definitions/${definitionIdNum}/series/${seriesIdNum}/forecasts${queryString ? '?' + queryString : ''}`;
  
  try {
    const response = await fetch(url, {
      headers: {
        'X-API-Key': API_KEY,
      }
    });
    
    const data = await response.json();
    
    if (!response.ok) {
      console.error('API returned error:', data);
      return NextResponse.json(data, { status: response.status });
    }
    
    return NextResponse.json(data);
  } catch (error) {
    console.error('Fetch error:', error);
    return NextResponse.json({ error: 'Failed to fetch forecasts' }, { status: 500 });
  }
}

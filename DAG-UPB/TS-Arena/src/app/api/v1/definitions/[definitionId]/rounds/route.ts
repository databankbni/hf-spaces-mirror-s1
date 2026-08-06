import { NextRequest, NextResponse } from 'next/server';

const API_BASE_URL = process.env.NEXT_PUBLIC_DASH_BOARD_API_URL || '';
const API_KEY = process.env.NEXT_PUBLIC_DASH_BOARD_API_KEY || '';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ definitionId: string }> | { definitionId: string } }
) {
  const resolvedParams = await Promise.resolve(params);
  const { definitionId } = resolvedParams;
  
  if (!definitionId || definitionId === 'undefined') {
    return NextResponse.json(
      { error: 'Invalid definition ID' },
      { status: 400 }
    );
  }
  
  // Forward query params to backend
  const searchParams = request.nextUrl.searchParams;
  const queryString = searchParams.toString();
  const url = `${API_BASE_URL}/api/v1/definitions/${definitionId}/rounds${queryString ? '?' + queryString : ''}`;
  
  console.log('Calling definition rounds API:', url);
  
  try {
    const response = await fetch(url, {
      headers: {
        'X-API-Key': API_KEY,
      }
    });
    
    if (!response.ok) {
      return NextResponse.json(
        { error: 'Failed to fetch rounds for definition' },
        { status: response.status }
      );
    }
    
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error fetching rounds for definition:', error);
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}

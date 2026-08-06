import { NextRequest, NextResponse } from 'next/server';

const API_BASE_URL = process.env.NEXT_PUBLIC_DASH_BOARD_API_URL || '';
const API_KEY = process.env.NEXT_PUBLIC_DASH_BOARD_API_KEY || '';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ roundId: string }> | { roundId: string } }
) {
  const resolvedParams = await Promise.resolve(params);
  const { roundId } = resolvedParams;
  
  if (!roundId || roundId === 'undefined') {
    return NextResponse.json(
      { error: 'Invalid round ID' },
      { status: 400 }
    );
  }
  
  const url = `${API_BASE_URL}/api/v1/rounds/${roundId}/models`;
  
  console.log('Calling round models API:', url);
  
  try {
    const response = await fetch(url, {
      headers: {
        'X-API-Key': API_KEY,
      }
    });
    
    if (!response.ok) {
      return NextResponse.json(
        { error: 'Failed to fetch models for round' },
        { status: response.status }
      );
    }
    
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error fetching models for round:', error);
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}

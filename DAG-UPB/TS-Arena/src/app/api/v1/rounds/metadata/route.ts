import { NextResponse } from 'next/server';

const API_BASE_URL = process.env.NEXT_PUBLIC_DASH_BOARD_API_URL || '';
const API_KEY = process.env.NEXT_PUBLIC_DASH_BOARD_API_KEY || '';

export async function GET() {
  const url = `${API_BASE_URL}/api/v1/rounds/metadata`;
  
  console.log('Calling rounds metadata API:', url);
  console.log('API_BASE_URL:', API_BASE_URL);
  
  try {
    const response = await fetch(url, {
      headers: {
        'X-API-Key': API_KEY,
      }
    });
    
    if (!response.ok) {
      return NextResponse.json(
        { error: 'Failed to fetch rounds metadata' },
        { status: response.status }
      );
    }
    
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error fetching rounds metadata:', error);
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}

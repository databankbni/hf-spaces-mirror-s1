import { NextRequest, NextResponse } from 'next/server';

const API_BASE_URL = process.env.NEXT_PUBLIC_DASH_BOARD_API_URL || '';
const API_KEY = process.env.NEXT_PUBLIC_DASH_BOARD_API_KEY || '';

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  
  const params = new URLSearchParams();
  searchParams.forEach((value, key) => {
    params.append(key, value);
  });
  
  const url = `${API_BASE_URL}/api/v1/models/rankings${params.toString() ? '?' + params.toString() : ''}`;
  
  console.log('Calling external API:', url);
  console.log('API_BASE_URL:', API_BASE_URL);
  
  const response = await fetch(url, {
    headers: {
      'X-API-Key': API_KEY,
    }
  });
  
  const data = await response.json();
  return NextResponse.json(data);
}

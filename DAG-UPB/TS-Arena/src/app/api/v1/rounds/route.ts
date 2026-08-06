import { NextRequest, NextResponse } from 'next/server';

const API_BASE_URL = process.env.NEXT_PUBLIC_DASH_BOARD_API_URL || '';
const API_KEY = process.env.NEXT_PUBLIC_DASH_BOARD_API_KEY || '';

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  
  // Build query parameters from the request
  const queryParams = new URLSearchParams();
  
  // Add filter parameters if they exist
  const domains = searchParams.getAll('domain');
  const categories = searchParams.getAll('category');
  const frequencies = searchParams.getAll('frequency');
  const horizons = searchParams.getAll('horizon');
  const from = searchParams.get('from');
  const to = searchParams.get('to');
  const status = searchParams.get('status');
  const searchTerm = searchParams.get('search');
  
  domains.forEach(d => queryParams.append('domain', d));
  categories.forEach(c => queryParams.append('category', c));
  frequencies.forEach(f => queryParams.append('frequency', f));
  horizons.forEach(h => queryParams.append('horizon', h));
  if (from) queryParams.append('from', from);
  if (to) queryParams.append('to', to);
  if (status && status !== 'all') queryParams.append('status', status);
  if (searchTerm) queryParams.append('search', searchTerm);
  
  const queryString = queryParams.toString();
  const url = `${API_BASE_URL}/api/v1/rounds${queryString ? '?' + queryString : ''}`;
  
  try {
    const response = await fetch(url, {
      headers: {
        'X-API-Key': API_KEY,
      }
    });
    
    if (!response.ok) {
      return NextResponse.json(
        { error: 'Failed to fetch rounds' },
        { status: response.status }
      );
    }
    
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error fetching rounds:', error);
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}

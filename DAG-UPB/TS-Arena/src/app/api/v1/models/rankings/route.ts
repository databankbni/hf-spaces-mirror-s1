import { NextRequest, NextResponse } from 'next/server';

import { createLogger } from '@/src/lib/logger';

const API_BASE_URL = process.env.NEXT_PUBLIC_DASH_BOARD_API_URL || '';
const API_KEY = process.env.NEXT_PUBLIC_DASH_BOARD_API_KEY || '';

const log = createLogger('/api/v1/models/rankings');

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;

  const params = new URLSearchParams();
  searchParams.forEach((value, key) => {
    params.append(key, value);
  });

  const path = `/api/v1/models/rankings${params.toString() ? '?' + params.toString() : ''}`;
  const url = `${API_BASE_URL}${path}`;

  log.debug(`upstream GET ${path}`);

  const response = await fetch(url, {
    headers: {
      'X-API-Key': API_KEY,
    }
  });
  
  const data = await response.json();
  return NextResponse.json(data);
}

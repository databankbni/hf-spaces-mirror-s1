import { NextResponse } from 'next/server';

import { createLogger } from '@/src/lib/logger';

const API_BASE_URL = process.env.NEXT_PUBLIC_DASH_BOARD_API_URL || '';
const API_KEY = process.env.NEXT_PUBLIC_DASH_BOARD_API_KEY || '';

const log = createLogger('/api/v1/models');

/**
 * Proxy for `GET /api/v1/models` on the dashboard-api. Returns the flat
 * list of every registered model with discovery metadata (paper_url,
 * repo_url, website_url, arxiv_id, …). Backs the frontend Models tab so it
 * no longer has to derive `readable_id → model_id` from the rankings
 * endpoint. See ticket frontend #33.
 */
export async function GET() {
  const path = '/api/v1/models';
  const url = `${API_BASE_URL}${path}`;

  log.debug(`upstream GET ${path}`);

  try {
    const response = await fetch(url, {
      headers: { 'X-API-Key': API_KEY },
    });
    const data = await response.json();
    if (!response.ok) {
      return NextResponse.json(data, { status: response.status });
    }
    return NextResponse.json(data);
  } catch (error) {
    log.error('failed to fetch models list', error);
    return NextResponse.json(
      { error: 'Failed to fetch models list' },
      { status: 500 },
    );
  }
}

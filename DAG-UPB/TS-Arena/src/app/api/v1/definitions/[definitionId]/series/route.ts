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

  const url = `${API_BASE_URL}/api/v1/definitions/${definitionId}/series`;

  try {
    const response = await fetch(url, {
      headers: {
        'X-API-Key': API_KEY,
      }
    });

    if (!response.ok) {
      return NextResponse.json(
        { error: 'Failed to fetch series for definition' },
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error fetching series for definition:', error);
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}

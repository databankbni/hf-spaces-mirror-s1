import { NextRequest, NextResponse } from 'next/server';

const API_BASE_URL = process.env.NEXT_PUBLIC_DASH_BOARD_API_URL || '';
const API_KEY = process.env.NEXT_PUBLIC_DASH_BOARD_API_KEY || '';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ modelId: string }> }
) {
  const { modelId } = await params;
  
  // Parse modelId as number for the external API
  const modelIdNum = parseInt(modelId, 10);
  
  if (isNaN(modelIdNum)) {
    return NextResponse.json({ error: 'Invalid model ID' }, { status: 400 });
  }
  
  const url = `${API_BASE_URL}/api/v1/models/${modelIdNum}/series-by-definition`;
  
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
    return NextResponse.json({ error: 'Failed to fetch series by definition' }, { status: 500 });
  }
}

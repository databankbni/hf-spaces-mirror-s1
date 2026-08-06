import { NextResponse } from 'next/server';

/**
 * OSIRIS — Utility Usage API (power / gas)
 * US grid + natural gas signals from the EIA Open Data v2 API.
 * Requires a free EIA_API_KEY (https://www.eia.gov/opendata/register.php).
 * Without a key the route still returns 200 with configured:false so the
 * UI can degrade gracefully. Water has no national live-usage feed — see
 * docs/DATA_SOURCING.md for the USGS Water Services per-site option.
 */

const EIA_BASE = 'https://api.eia.gov/v2';

async function eiaFetch(path: string, key: string): Promise<any | null> {
  try {
    const sep = path.includes('?') ? '&' : '?';
    const res = await fetch(`${EIA_BASE}${path}${sep}api_key=${key}`, { signal: AbortSignal.timeout(10000) });
    if (!res.ok) return null;
    const data = await res.json();
    return data.response?.data || null;
  } catch { return null; }
}

export async function GET() {
  const key = process.env.EIA_API_KEY;
  if (!key) {
    return NextResponse.json({
      configured: false,
      message: 'Set EIA_API_KEY to enable live US electricity demand and natural gas data. Free key: https://www.eia.gov/opendata/register.php',
      timestamp: new Date().toISOString(),
    }, { headers: { 'Cache-Control': 'no-store' } });
  }

  const [demand, gasStorage] = await Promise.all([
    // Hourly US Lower-48 electricity demand, last 24 hours
    eiaFetch('/electricity/rto/region-data/data/?frequency=hourly&data[0]=value&facets[respondent][]=US48&facets[type][]=D&sort[0][column]=period&sort[0][direction]=desc&length=24', key),
    // Weekly working natural gas in underground storage, Lower 48
    eiaFetch('/natural-gas/stor/wkly/data/?frequency=weekly&data[0]=value&facets[series][]=NW2_EPG0_SWO_R48_BCF&sort[0][column]=period&sort[0][direction]=desc&length=4', key),
  ]);

  const electricity = demand ? {
    label: 'US Lower-48 hourly electricity demand (MWh)',
    latest: demand[0] ? { period: demand[0].period, value: demand[0].value } : null,
    last_24h: demand.map((d: any) => ({ period: d.period, value: d.value })),
  } : null;

  const natural_gas = gasStorage ? {
    label: 'US working natural gas in storage (Bcf, weekly)',
    latest: gasStorage[0] ? { period: gasStorage[0].period, value: gasStorage[0].value } : null,
    recent_weeks: gasStorage.map((d: any) => ({ period: d.period, value: d.value })),
  } : null;

  return NextResponse.json({
    configured: true,
    electricity,
    natural_gas,
    timestamp: new Date().toISOString(),
  }, {
    headers: { 'Cache-Control': 'public, max-age=900' },
  });
}

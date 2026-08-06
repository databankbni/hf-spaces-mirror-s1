import { NextResponse } from 'next/server';

/**
 * OSIRIS — Macro Signals API
 * VIX, US Treasury yields and the Fed funds rate for the resource/AI-market
 * intelligence layer. Keyless sources:
 *   - Yahoo Finance chart API (^VIX, ^IRX, ^FVX, ^TNX, ^TYX) — same pattern as /api/markets
 *   - FRED public CSV endpoint (fredgraph.csv) for the effective Fed funds rate (DFF)
 * An optional FRED_API_KEY upgrades the Fed-rate fetch to the official JSON API.
 */

const YAHOO_SERIES: { symbol: string; key: string; label: string }[] = [
  { symbol: '^VIX', key: 'vix', label: 'CBOE Volatility Index' },
  { symbol: '^IRX', key: 'us_13w', label: 'US 13-Week T-Bill Yield' },
  { symbol: '^FVX', key: 'us_5y', label: 'US 5-Year Treasury Yield' },
  { symbol: '^TNX', key: 'us_10y', label: 'US 10-Year Treasury Yield' },
  { symbol: '^TYX', key: 'us_30y', label: 'US 30-Year Treasury Yield' },
];

async function fetchYahoo(symbol: string): Promise<any | null> {
  try {
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?interval=1d&range=2d`;
    const res = await fetch(url, {
      signal: AbortSignal.timeout(8000),
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json',
      },
    });
    if (!res.ok) return null;
    const data = await res.json();
    const result = data.chart?.result?.[0];
    if (!result) return null;
    const meta = result.meta;
    const closes = result.indicators?.quote?.[0]?.close || [];
    const currentPrice = meta.regularMarketPrice || closes[closes.length - 1];
    const prevClose = meta.chartPreviousClose || closes[0];
    if (!currentPrice || !prevClose) return null;
    const changePercent = ((currentPrice - prevClose) / prevClose) * 100;
    return {
      value: Math.round(currentPrice * 100) / 100,
      change_percent: Math.round(changePercent * 100) / 100,
      up: changePercent >= 0,
    };
  } catch { return null; }
}

// Fed funds rate. With FRED_API_KEY: official JSON API. Without: public fredgraph CSV.
async function fetchFedFunds(): Promise<any | null> {
  const key = process.env.FRED_API_KEY;
  try {
    if (key) {
      const url = `https://api.stlouisfed.org/fred/series/observations?series_id=DFF&api_key=${key}&file_type=json&sort_order=desc&limit=1`;
      const res = await fetch(url, { signal: AbortSignal.timeout(8000) });
      if (res.ok) {
        const data = await res.json();
        const obs = data.observations?.[0];
        if (obs) return { value: parseFloat(obs.value), date: obs.date, source: 'FRED API (DFF)' };
      }
    }
    const res = await fetch('https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFF', { signal: AbortSignal.timeout(8000) });
    if (!res.ok) return null;
    const csv = await res.text();
    const lines = csv.trim().split('\n');
    for (let i = lines.length - 1; i > 0; i--) {
      const [date, value] = lines[i].split(',');
      const v = parseFloat(value);
      if (!isNaN(v)) return { value: v, date, source: 'FRED public CSV (DFF)' };
    }
    return null;
  } catch { return null; }
}

export async function GET() {
  const [yahooResults, fedFunds] = await Promise.all([
    Promise.all(YAHOO_SERIES.map(s => fetchYahoo(s.symbol))),
    fetchFedFunds(),
  ]);

  const series: Record<string, any> = {};
  YAHOO_SERIES.forEach((s, i) => {
    if (yahooResults[i]) series[s.key] = { label: s.label, symbol: s.symbol, ...yahooResults[i] };
  });
  if (fedFunds) series.fed_funds = { label: 'Effective Fed Funds Rate', ...fedFunds };

  // 10Y-13W spread as a quick curve-inversion signal
  if (series.us_10y && series.us_13w) {
    const spread = Math.round((series.us_10y.value - series.us_13w.value) * 100) / 100;
    series.curve_spread = { label: '10Y minus 13W spread', value: spread, inverted: spread < 0 };
  }

  return NextResponse.json({
    series,
    available: Object.keys(series).length,
    timestamp: new Date().toISOString(),
  }, {
    headers: { 'Cache-Control': 'public, max-age=300' },
  });
}

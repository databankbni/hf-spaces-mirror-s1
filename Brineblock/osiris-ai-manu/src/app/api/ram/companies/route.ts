import { NextRequest, NextResponse } from 'next/server';
import seed from '@/data/ram-companies.json';

/**
 * OSIRIS — Resource Intelligence: Memory / RAM Ecosystem
 * DRAM/HBM makers plus the NAND, controller/IP, module, packaging and
 * equipment companies the AI memory supply chain depends on.
 *
 * Query params:
 *   ?category=dram_hbm|nand|controller_ip|module_maker|packaging_test|equipment
 *   ?country=<substring match against site or HQ country>
 */

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const category = searchParams.get('category')?.toLowerCase();
  const country = searchParams.get('country')?.toLowerCase();

  let companies = seed.companies;
  if (category) companies = companies.filter(c => c.category === category);
  if (country) companies = companies.filter(c =>
    c.hq_country.toLowerCase().includes(country) ||
    c.sites.some(s => s.country.toLowerCase().includes(country))
  );

  const sites = companies.flatMap(c => c.sites.map(s => ({
    id: `${c.id}::${s.name}`,
    company: c.name,
    company_id: c.id,
    ticker: c.ticker,
    exchange: c.exchange,
    category: c.category,
    commodities: c.commodities,
    site: s.name,
    site_type: s.type,
    country: s.country,
    hq: `${c.hq_city}, ${c.hq_country}`,
    lat: s.lat,
    lng: s.lng,
    notes: c.notes,
  })));

  const by_category: Record<string, number> = {};
  for (const c of companies) by_category[c.category] = (by_category[c.category] || 0) + 1;

  return NextResponse.json({
    companies,
    sites,
    total_companies: companies.length,
    total_sites: sites.length,
    by_category,
    meta: seed.meta,
    timestamp: new Date().toISOString(),
  }, {
    headers: { 'Cache-Control': 'public, max-age=3600' },
  });
}

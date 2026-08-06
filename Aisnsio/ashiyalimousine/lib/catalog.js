// Server-authoritative pricing. The booking route computes totals from THIS table,
// never from the client — a tampered client price is ignored. Mirrors public/index.html
// PLANS + ADDONS. Verified against the seeded demo totals (e.g. p90+bday = 47,300).

const PLANS = {
  p60:    { price: 38500, max: 11, veh: 'limo', bookable: true,  name_en: 'Limousine Party · 60 min' },
  p90:    { price: 44000, max: 11, veh: 'limo', bookable: true,  name_en: 'Limousine Party · 90 min' },
  half:   { price: 110000, max: 11, veh: 'limo', bookable: true,  name_en: 'Half-Day Charter · 6 h' },
  bridal: { price: 35200, max: 2,  veh: 'any',  bookable: true,  name_en: 'Bridal Scene Shoot · 60 min' },
  night:  { price: 55000, max: 8,  veh: 'limo', bookable: true,  name_en: 'Night Cruise Kobe · 120 min' },
  tkz:    { price: 38500, max: 8,  veh: 'limo', bookable: true,  name_en: 'Takarazuka Theater Tour' },
  twin:   { price: 78000, max: 18, veh: 'twin', bookable: true,  name_en: 'Twin Limousine Convoy · 2 h' },
  kix:    { price: 55000, max: 8,  veh: 'limo', bookable: true,  name_en: 'KIX Inbound Cruise' },
  chx:    { price: 33000, max: 4,  veh: 'icon', bookable: true,  name_en: 'Chauffeur Icons · 60 min' },
  crz:    { price: 110000, max: 16, veh: 'none', bookable: false, name_en: 'Cruiser Plans A / B' },
  ill:    { price: 33000, max: 8,  veh: 'limo', bookable: false, name_en: 'Midosuji Illumination · 60 min' },
};

const ADDONS = {
  ext:  { price: 8250, per: 'flat', name_en: '+30 min extension' },
  cat:  { price: 4000, per: 'pax',  name_en: 'Partner catering' },
  flor: { price: 8800, per: 'flat', name_en: 'FLORIST HIROKO arrangement' },
  bday: { price: 3300, per: 'flat', name_en: 'Birthday number balloon' },
  // premium upsells (Wave A #4)
  champagne: { price: 22000, per: 'flat', name_en: 'Premium champagne bottle' },
  redcarpet: { price: 6600, per: 'flat', name_en: 'Red-carpet arrival' },
  photog:    { price: 33000, per: 'flat', name_en: 'Professional photographer' },
  cake:      { price: 5500, per: 'flat', name_en: 'Celebration cake' },
  decor:     { price: 8800, per: 'flat', name_en: 'Premium cabin decoration' },
};

// Tiered experience bundles (Wave A #5) — a plan + preset add-ons at a headline price.
const BUNDLES = {
  bronze: { name_en: 'Bronze Celebration', plan: 'p60', addons: ['bday'], badge: '' },
  silver: { name_en: 'Silver Celebration', plan: 'p90', addons: ['bday', 'champagne', 'cake'], badge: 'Popular' },
  gold:   { name_en: 'Gold VIP Night', plan: 'half', addons: ['champagne', 'photog', 'redcarpet', 'decor'], badge: 'Premium' },
};

const VALID_VEH = ['exc3', 'exc4', 'dts', 'c300', 'mas', 'ssk', 'twin'];

// total = plan price + Σ addons (per:'pax' multiplies by guest count)
function priceFor(planId, addonIds, pax) {
  const plan = PLANS[planId];
  if (!plan) return null;
  const n = Math.max(1, parseInt(pax, 10) || 1);
  let total = plan.price;
  for (const id of addonIds || []) {
    const a = ADDONS[id];
    if (!a) continue;
    total += a.per === 'pax' ? a.price * n : a.price;
  }
  return total;
}

const depositFor = (total) => Math.round(total * 0.3);

module.exports = { PLANS, ADDONS, BUNDLES, VALID_VEH, priceFor, depositFor };

/**
 * iFreight Jamaica - Master Logistics & Rates Dataset
 */

const IFREIGHT_DATA = {
  company: {
    name: "iFreightJa",
    tagline: "Fast, Smart, and Seamless to Jamaica.",
    email: "information.ifreight@ifreightja.com",
    phone: "+1 (876) 879-9026",
    whatsapp: "18768799026",
    instagram: "https://www.instagram.com/ifreightja?igsh=MWo5eGhrZzJ3Ymtieg==",
    portalLogin: "https://ifj.egmcourier.com/login",
    oldDashboard: "https://ifj.shiptojm.com/",
    hours: "Mon – Sat: 9:00 AM – 5:00 PM",
    locations: [
      {
        city: "Kingston",
        address: "7 Lady Musgrave Road, Suite 4, Kingston 5, Jamaica",
        phone: "+1 (876) 879-9026",
        hours: "Mon-Fri: 9am-5pm | Sat: 10am-3pm"
      },
      {
        city: "Montego Bay",
        address: "Fairview Shopping Centre, Unit B12, Montego Bay, Jamaica",
        phone: "+1 (876) 879-9026",
        hours: "Mon-Fri: 9am-5pm | Sat: 10am-3pm"
      }
    ],
    usWarehouse: {
      addressLine1: "10800 NW 21st St",
      addressLine2: "Suite 100 / IFJ-MEMBER_CODE",
      city: "Doral",
      state: "FL",
      zipCode: "33172",
      country: "United States",
      phone: "+1 (786) 558-8902"
    }
  },

  rates: [
    { weight: 1, unit: 'lb', priceJMD: 974.58, priceUSD: 6.25 },
    { weight: 2, unit: 'lbs', priceJMD: 1389.69, priceUSD: 8.90 },
    { weight: 3, unit: 'lbs', priceJMD: 1784.18, priceUSD: 11.45 },
    { weight: 4, unit: 'lbs', priceJMD: 2118.33, priceUSD: 13.60 },
    { weight: 5, unit: 'lbs', priceJMD: 2468.66, priceUSD: 15.80 },
    { weight: 6, unit: 'lbs', priceJMD: 3142.84, priceUSD: 20.15 },
    { weight: 7, unit: 'lbs', priceJMD: 3447.54, priceUSD: 22.10 },
    { weight: 8, unit: 'lbs', priceJMD: 3762.67, priceUSD: 24.10 },
    { weight: 9, unit: 'lbs', priceJMD: 4114.36, priceUSD: 26.35 },
    { weight: 10, unit: 'lbs', priceJMD: 4427.90, priceUSD: 28.35 },
    { weight: 15, unit: 'lbs', priceJMD: 6150.00, priceUSD: 39.40 },
    { weight: 20, unit: 'lbs', priceJMD: 7920.00, priceUSD: 50.75 },
    { weight: 30, unit: 'lbs', priceJMD: 11400.00, priceUSD: 73.00 },
    { weight: 50, unit: 'lbs', priceJMD: 18250.00, priceUSD: 117.00 },
    { weight: 100, unit: 'lbs', priceJMD: 34500.00, priceUSD: 221.00 }
  ],

  oceanFreight: {
    barrelStandard: { name: "Standard Food & Dry Goods Barrel", priceUSD: 85.00, priceJMD: 13260.00, deliveryDays: "10-14 days" },
    barrelJumbo: { name: "Jumbo Plastic Drum Barrel", priceUSD: 105.00, priceJMD: 16380.00, deliveryDays: "10-14 days" },
    palletRate: { name: "Commercial Wooden Pallet (Up to 1,500 lbs)", priceUSD: 320.00, priceJMD: 49920.00, deliveryDays: "14-21 days" },
    cftRateUSD: 6.50 // per cubic foot for LCL loose cargo
  },

  services: [
    {
      id: "air-freight",
      title: "Air Freight",
      desc: "Fast delivery by air to Jamaica for time-sensitive cargo. Regular 2–5 business day turnaround from our Florida hub.",
      tag: "2-5 Days",
      icon: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M3 17l18-7-7 11-2-5-9 1z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M3 7h5" stroke="#13A69C" stroke-width="2" stroke-linecap="round"/></svg>`
    },
    {
      id: "ocean-freight",
      title: "Ocean Freight",
      desc: "Cost-effective sea freight for barrels, heavy equipment, furniture, and commercial bulk inventory.",
      tag: "Best for Heavy Cargo",
      icon: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M4 10l8-3 8 3-1 7H5z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M3 21c1.5 1 3 1 4.5 0s3-1 4.5 0 3 1 4.5 0 3-1 4.5 0" stroke="#13A69C" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`
    },
    {
      id: "express-shipping",
      title: "Express Shipping",
      desc: "Priority fast-track processing for your most urgent documents, electronics, and time-critical orders.",
      tag: "Priority Expedited",
      icon: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M13 3L5 13h6l-1 8 8-10h-6z" stroke="#13A69C" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`
    },
    {
      id: "commercial-freight",
      title: "Commercial Freight",
      desc: "Scalable B2B logistics, container consolidation, and tailored enterprise solutions for growing Jamaican businesses.",
      tag: "B2B & Wholesale",
      icon: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none"><rect x="5" y="4" width="14" height="16" rx="1.6" stroke="currentColor" stroke-width="2"/><path d="M9 9h2M13 9h2M9 13h2M13 13h2" stroke="#13A69C" stroke-width="2" stroke-linecap="round"/><path d="M10 20v-3h4v3" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`
    },
    {
      id: "customs-clearance",
      title: "Customs Clearance",
      desc: "We handle all Jamaica Customs Agency (JCA) declarations, tariff classification, GCT, and duties end-to-end.",
      tag: "Hassle-Free",
      icon: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M12 3l7 3v5c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M9 12l2 2 4-4" stroke="#13A69C" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`
    },
    {
      id: "door-to-door",
      title: "Door-to-Door Delivery",
      desc: "Islandwide courier delivery direct to your home or office across all 14 Jamaican parishes.",
      tag: "Islandwide",
      icon: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M12 21c4-4 6-7 6-10a6 6 0 10-12 0c0 3 2 6 6 10z" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="11" r="2.2" stroke="#13A69C" stroke-width="2"/></svg>`
    },
    {
      id: "business-shipping",
      title: "Business Shipping",
      desc: "Dedicated corporate accounts, pre-alert bulk upload, and discounted rates for Jamaican e-commerce retailers.",
      tag: "Corporate Perks",
      icon: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M4 20h16" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><rect x="5" y="12" width="3" height="6" rx="1" stroke="currentColor" stroke-width="2"/><rect x="10.5" y="8" width="3" height="10" rx="1" stroke="#13A69C" stroke-width="2"/><rect x="16" y="5" width="3" height="13" rx="1" stroke="currentColor" stroke-width="2"/></svg>`
    },
    {
      id: "assisted-shopping",
      title: "Personal Shopper & Procurement",
      desc: "Don't have a US credit card? We will purchase your items from Amazon, eBay, Walmart, or Shein on your behalf.",
      tag: "Card-Free Shopping",
      icon: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none"><circle cx="9" cy="21" r="1" stroke="currentColor" stroke-width="2"/><circle cx="20" cy="21" r="1" stroke="currentColor" stroke-width="2"/><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6" stroke="#13A69C" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`
    }
  ],

  steps: [
    { n: '1', title: 'Create an Account', desc: 'Sign up free in 60 seconds to get your personal U.S. mailbox address and member ID.' },
    { n: '2', title: 'Shop Online', desc: 'Shop your favorite U.S. stores including Amazon, eBay, Fashion Nova, Shein, and Best Buy.' },
    { n: '3', title: 'Ship to U.S. Hub', desc: 'Enter your designated Florida warehouse address and suite code at checkout.' },
    { n: '4', title: 'Warehouse Intake', desc: 'Your packages are inspected, weighed, photographed, and logged into your dashboard.' },
    { n: '5', title: 'Air or Ocean Transit', desc: 'We transport your packages across the Caribbean with live flight/vessel tracking.' },
    { n: '6', title: 'Pickup or Delivery', desc: 'Collect at our Kingston/MoBay branch or enjoy door-to-door islandwide courier delivery.' }
  ],

  testimonials: [
    {
      quote: 'IfreightJa completely changed how I import for my boutique. My U.S. address was ready in minutes and the rates cut my shipping bill almost in half.',
      name: 'Shanice Brown',
      location: 'Kingston, Jamaica',
      initials: 'SB',
      role: 'Fashion Boutique Owner'
    },
    {
      quote: 'Tracking is genuinely real-time. I always know exactly where my barrels and air packages are, and customs clearance was handled without me lifting a finger.',
      name: 'Marcus Reid',
      location: 'Montego Bay, Jamaica',
      initials: 'MR',
      role: 'Commercial Importer'
    },
    {
      quote: 'As an e-commerce seller, fast and predictable delivery is everything. IfreightJa feels like having a dedicated logistics team built right into my business.',
      name: 'Tanya Campbell',
      location: 'Mandeville, Jamaica',
      initials: 'TC',
      role: 'E-commerce Entrepreneur'
    }
  ],

  faqs: [
    {
      q: 'How do I track my shipment?',
      a: 'Every package gets a unique tracking number the moment it reaches your free U.S. address. Enter it in the tracking terminal on this page or inside your member portal to see live transit status, customs milestone, and estimated arrival.'
    },
    {
      q: 'How much does shipping cost?',
      a: 'Air rates start at $974.58 JMD ($6.25 USD) for the first pound, with transparent weight-based brackets. Use our interactive shipping calculator to estimate air vs ocean costs plus Jamaica Customs Agency (JCA) duty estimates before purchasing.'
    },
    {
      q: 'How long does delivery take?',
      a: 'Express Air Freight lands in Jamaica within 2–5 business days after warehouse arrival. Ocean Sea Freight for barrels and bulk cargo typically takes 10–14 days. You will always see an estimated delivery window before dispatch.'
    },
    {
      q: 'What is the $100 USD Customs Duty threshold in Jamaica?',
      a: 'In Jamaica, personal import packages valued under $100 USD (Cost + Insurance + Freight) enter duty-free without standard GCT / customs tariffs! For packages over $100 USD, our automated customs team handles the JCA declaration and invoice processing.'
    },
    {
      q: 'Are there restricted or hazardous items?',
      a: 'Hazardous materials (flammable aerosols, explosives, firearms, live ammunition, illegal substances, perishable meats) are restricted by international aviation law. Our intake team flags restricted goods immediately.'
    },
    {
      q: 'Is my shipment insured door-to-door?',
      a: 'Standard baseline loss/damage coverage is included on every package. Additional declared-value coverage is available at checkout for high-value electronics and luxury goods for total peace of mind.'
    }
  ],

  mockTracking: {
    "IFJ-84920-AIR": {
      trackingNumber: "IFJ-84920-AIR",
      status: "IN_TRANSIT",
      statusLabel: "In Flight to Kingston",
      type: "Express Air Freight",
      weight: "3.5 lbs",
      shipper: "Amazon.com (Seattle, WA)",
      destination: "Kingston Hub (Lady Musgrave)",
      estimatedDelivery: "Tomorrow, 2:00 PM",
      timeline: [
        { time: "Today, 09:30 AM", title: "Departed Miami Air Cargo Terminal", location: "Miami (MIA) -> Kingston (KIN)", completed: true },
        { time: "Yesterday, 04:15 PM", title: "Customs Export Manifest Approved", location: "Doral Hub, FL", completed: true },
        { time: "Aug 15, 11:20 AM", title: "Package Received & Weighed at US Warehouse", location: "10800 NW 21st St, Doral, FL", completed: true },
        { time: "Pending", title: "Jamaica Customs Agency Clearance", location: "Norman Manley Int'l Airport (KIN)", completed: false },
        { time: "Pending", title: "Ready for Branch Pickup / Delivery", location: "7 Lady Musgrave Rd, Kingston", completed: false }
      ]
    },
    "IFJ-11048-SEA": {
      trackingNumber: "IFJ-11048-SEA",
      status: "AT_PORT",
      statusLabel: "Docked at Kingston Container Terminal",
      type: "Ocean Sea Freight (Barrel)",
      weight: "185 lbs",
      shipper: "Walmart Logistics (Orlando, FL)",
      destination: "Montego Bay Hub",
      estimatedDelivery: "In 2 Days",
      timeline: [
        { time: "Today, 07:00 AM", title: "Vessel Berthed at Kingston Container Terminal", location: "Port of Kingston, Jamaica", completed: true },
        { time: "Aug 12, 02:00 PM", title: "Container Vessel Sailing Caribbean Sea", location: "Port Everglades, FL", completed: true },
        { time: "Aug 10, 09:00 AM", title: "Barrel Received & Sealed at Miami Depot", location: "Doral Warehouse, FL", completed: true },
        { time: "Pending", title: "JCA Customs Inspection & Unstuffing", location: "Kingston Wharf", completed: false },
        { time: "Pending", title: "Dispatched to Montego Bay Fairview Branch", location: "Montego Bay, Jamaica", completed: false }
      ]
    },
    "IFJ-99214-EXP": {
      trackingNumber: "IFJ-99214-EXP",
      status: "READY_FOR_PICKUP",
      statusLabel: "Ready for Pickup",
      type: "Priority Air Express",
      weight: "1.2 lbs",
      shipper: "Apple Inc. (Cupertino, CA)",
      destination: "Kingston Hub",
      estimatedDelivery: "Ready Now",
      timeline: [
        { time: "Today, 10:15 AM", title: "Sorted & Ready for Customer Pickup", location: "7 Lady Musgrave Rd, Kingston", completed: true },
        { time: "Today, 08:00 AM", title: "Cleared Jamaica Customs (JCA)", location: "KIN Airport", completed: true },
        { time: "Yesterday, 06:40 PM", title: "Landed at Norman Manley Airport", location: "Kingston, Jamaica", completed: true },
        { time: "Aug 14, 02:10 PM", title: "Intake & Air Cargo Dispatch", location: "Doral, FL", completed: true }
      ]
    }
  }
};

if (typeof module !== 'undefined' && module.exports) {
  module.exports = IFREIGHT_DATA;
}

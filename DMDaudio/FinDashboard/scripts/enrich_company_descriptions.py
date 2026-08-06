"""Seed the `companies.Description` and `companies.Sector` columns with
hand-curated, web-sourced 2-3 sentence summaries + a sector bucket for
each company. Surfaces in the Single Company view header so financials
read with context, not just numbers.

Description sources are stored as a JSON list of URLs in
`companies.DescriptionSources`, and an ISO timestamp in
`companies.DescriptionUpdatedAt`, so we can show "as of date" and
audit-trail the source.

Sector is a flat ~26-bucket GCAP taxonomy (see SECTORS below).

This is a *seed* file — covers ~top-100 companies by 2024 revenue. Extend
by adding new entries to DESCRIPTIONS and re-running. Idempotent; existing
rows are overwritten on each run.

Schema (added to `companies` table):
  Description           TEXT  — the 2-3 sentence English summary
  DescriptionSources    TEXT  — JSON list of source URLs
  DescriptionUpdatedAt  TEXT  — ISO datetime when last enriched
  Sector                TEXT  — one of SECTORS (GCAP taxonomy, top level)
  SubSector             TEXT  — finer-grained label within a Sector (free-form
                                 for now — when a sub-sector pattern recurs, add
                                 it to SUB_SECTORS for consistency).

Usage:
  python scripts/enrich_company_descriptions.py
  python scripts/enrich_company_descriptions.py path/to.db

Ranking source: SUM(Value) WHERE Category IN ('IS_Revenue','IS_InterestIncome')
AND ItemType='TOTAL' AND FVYear=2024, taking the max of the two per company
so banks (which report no IS_Revenue) rank alongside non-fin companies.

Excluded from this batch:
  - 404557644 (შპს სასტუმრო სიღნაღში): GEL 1.2bn "revenue" with -6.4bn
    net loss and no employees in 2024 only. Clear data error / mislabel;
    flagged for upstream cleanup, not seeded.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "georgian-financials-v2.db"

SEED_BATCH_DATE = "2026-06-03"

# Bulk-generated descriptions for the Cat-I/II/PIE long tail. Lives in a
# sidecar JSON so this .py file stays readable (the hand-curated top entries
# are still the inline DESCRIPTIONS dict below). Hand-curated entries WIN on
# key collisions — the merge skips any idcode already present in DESCRIPTIONS.
EXTRA_JSON = Path(__file__).resolve().parent / "enrich_extra_descriptions.json"

# GCAP sector taxonomy. Flat list (~26 buckets). Treat as a closed set —
# every Sector value below must be one of these. Gambling added on top of
# the original 25 because Georgia's top-100 has 6+ licensed operators.
SECTORS = {
    "Banks",
    "Insurance",
    "Non-bank Credit (MFO/Leasing)",
    "Asset Management",
    "Pharma & Healthcare",
    "Food & Beverage (FMCG)",
    "Wine & Spirits",
    "Tobacco",
    "Retail - Grocery",
    "Retail - Apparel & Specialty",
    "Restaurants & QSR",
    "Hospitality",
    "Oil & Gas",
    "Power & Utilities",
    "Mining & Metals",
    "Real Estate Development",
    "Construction",
    "Auto & Auto Parts",
    "Telecom",
    "Tech & IT",
    "Media",
    "Logistics & Transport",
    "Agriculture",
    "Industrial Goods",
    "Education",
    "Gambling",
    "Conglomerate",
    "Other",
}

# Known sub-sector labels, organised under the parent Sector. The script
# accepts ANY string in an entry's `sub_sector` field — this dict is the
# canonical list we *intend* to use, so reviewers can spot drift. Extend as
# new sub-sectors become useful; the validator only warns on novel values.
SUB_SECTORS: dict[str, set[str]] = {
    "Pharma & Healthcare": {
        "Pharmacy Retail",
        "Pharma Distribution",
        "Pharma Manufacturing",
        "Hospitals & Clinics",
        "Healthcare Services",
    },
    # Add more as we classify deeper. Empty parents are fine.
}

# Each entry: idcode -> {description, sources, sector}.
DESCRIPTIONS: dict[str, dict] = {
    # ===== Existing 9 seeds (descriptions unchanged; sector added) =====
    "202177205": {
        "description": (
            "Tegeta Motors / Tegeta Holding is the largest automotive group in "
            "the Caucasus and Central Asia, operating since 1995. It is the "
            "exclusive Georgian dealer for Porsche, Volvo, Toyota, Mazda, MAN "
            "trucks, and JCB, and imports 300+ auto brands. The holding spans "
            "~40 subsidiaries, 26 service centers nationwide, 3,000+ employees, "
            "and 35K corporate + 500K retail customers."
        ),
        "sources": [
            "https://tegetamotors.ge/en/about-tegeta",
            "https://tegeta.ge/en/holding",
            "https://en.wikipedia.org/wiki/Tegeta_Holding",
        ],
        "sector": "Auto & Auto Parts",
    },
    "204571668": {
        "description": (
            "Ori Nabiji (\"Two Steps\") is one of the largest grocery supermarket "
            "chains in Georgia, founded in 2010, pioneering the neighborhood "
            "store format. It operates 400+ stores across Tbilisi, Batumi, "
            "Kutaisi and smaller towns, employs ~4,000 people, and runs an "
            "online ordering and home-delivery platform."
        ),
        "sources": [
            "https://2nabiji.ge/en",
            "https://ge.linkedin.com/company/2-%E1%83%9C%E1%83%90%E1%83%91%E1%83%98%E1%83%AF%E1%83%98-2-nabiji",
            "https://kompas.ge/en/chain/ori-nabiji",
        ],
        "sector": "Retail - Grocery",
    },
    "202349440": {
        "description": (
            "SOCAR Energy Georgia, established in 2006 as SOCAR's first foreign "
            "subsidiary, is a wholesale and retail oil & gas operator. It runs "
            "Georgia's largest petrol-station network (with the WayMart "
            "convenience-store chain) and imports / supplies / distributes "
            "natural gas — including 31,200km of pipelines serving 944K+ "
            "customers."
        ),
        "sources": [
            "https://www.socar.ge/en/socar-georgia",
            "https://ge.linkedin.com/company/socar-energy-georgia-ltd-",
            "https://sgp.ge/en",
        ],
        "sector": "Oil & Gas",
    },
    "206237491": {
        "description": (
            "Georgian Oil and Gas Corporation (GOGC) is the 100% state-owned "
            "National Oil Company, managed by the Ministry of Economy. Three "
            "core lines: natural-gas transit (operator of the South Caucasus "
            "Pipeline and the North-South Main Gas Pipeline), oil & gas "
            "exploration / production on PSA acreage, and power generation "
            "via the Gardabani I and II thermal plants."
        ),
        "sources": [
            "https://www.gogc.ge/en/about-overview",
            "https://en.wikipedia.org/wiki/Georgian_Oil_and_Gas_Corporation",
        ],
        "sector": "Oil & Gas",
    },
    "200050675": {
        "description": (
            "JSC Nikora (Nikora Group) is one of Georgia's largest food "
            "producers, founded in 1998 — ~35% share of the meat-products "
            "market. Produces meat, dairy, fish, bakery, soft drinks and wine "
            "under Nikora / Nugeshi / Libre brands across ~500 SKUs, alongside "
            "an importer arm for alcohol, food and raw materials. The group "
            "employs 10,000+ people."
        ),
        "sources": [
            "https://nikoraholding.ge/english/about-us",
            "https://ge.linkedin.com/company/jsc-nikora",
        ],
        "sector": "Food & Beverage (FMCG)",
    },
    "206255808": {
        "description": (
            "JSC Nikora Trade is the retail arm of the Nikora Group — Georgia's "
            "leading organised food retailer. Operates 307+ supermarket "
            "branches with 10,000+ SKUs and ~4,500 employees, selling Nikora "
            "Group own-label meat, dairy and bakery products alongside a wide "
            "third-party assortment."
        ),
        "sources": [
            "https://nikoraholding.ge/english/about-us",
            "https://www.scoperatings.com/ScopeRatingsApi/api/downloadanalysis?id=3746c6be-29ff-405f-bea1-659daabb9739",
        ],
        "sector": "Retail - Grocery",
    },
    "236089273": {
        "description": (
            "Toyota Caucasus LLC is the official Toyota distributor for the "
            "Caucasus region, headquartered on Al. Kazbegi Ave., Tbilisi. "
            "Sells the full Toyota new-vehicle range (Corolla, Camry, RAV4, "
            "Land Cruiser etc.) plus Toyota-branded insurance (Casco) and "
            "after-sales programs (T-MATE)."
        ),
        "sources": [
            "http://www.toyota-caucasus.com/",
            "https://www.dnb.com/business-directory/company-profiles.toyota_caucasus_llc.2351d467587333baa33a1be8b5de3461.html",
        ],
        "sector": "Auto & Auto Parts",
    },
    "211386695": {
        "description": (
            "Aversi-Pharma is Georgia's leading pharmacy chain, founded 1994 "
            "as a family-run pharmaceutical distributor. Operates 332 stores "
            "and the largest pharmaceutical factory in Georgia, employs "
            "10,000+ people, and since 2007 runs Aversi Clinic — a "
            "multi-profile medical-diagnostic chain across the Caucasus."
        ),
        "sources": [
            "https://www.aversi.ge/en/about",
            "https://fintecc.ebrd.com/case-study/cs-aversi",
        ],
        "sector": "Pharma & Healthcare",
        "sub_sector": "Pharmacy Retail",
    },
    "405103034": {
        "description": (
            "JSC BGEO Group (\"BiJeo Group\") is the Georgian-registered "
            "holding entity of Bank of Georgia and its parent group — now "
            "Lion Finance Group PLC (LSE: BGEO), the UK-listed financial-"
            "services group with corporate HQ in Tbilisi. Holds Georgia's "
            "largest commercial bank (~35% market share, ROAE consistently "
            ">25%) plus Armenia's Ameriabank (acquired May 2024 for $304M)."
        ),
        "sources": [
            "https://en.wikipedia.org/wiki/Lion_Finance_Group",
            "https://finance.yahoo.com/quote/BGEO.L/profile/",
            "https://www.bloomberg.com/profile/company/BGEO:LN",
        ],
        "sector": "Banks",
    },

    # ===== Banks (new) =====
    "204378869": {
        "description": (
            "JSC Bank of Georgia is the largest commercial bank in Georgia by "
            "assets, with ~35% market share and an LSE-listed parent (Lion "
            "Finance Group, ex-BGEO). Provides full retail, SME and corporate "
            "banking nationwide, plus payments, leasing and brokerage; "
            "consistently delivers ROAE in the high-20s%."
        ),
        "sources": [
            "https://bankofgeorgiagroup.com/",
            "https://en.wikipedia.org/wiki/Bank_of_Georgia",
            "https://bog.ge/en",
        ],
        "sector": "Banks",
    },
    "204854595": {
        "description": (
            "JSC TBC Bank is Georgia's second-largest universal bank by assets "
            "and the operating subsidiary of LSE-listed TBC Bank Group PLC. "
            "Combined with Bank of Georgia it forms a duopoly controlling "
            "~75% of system loans; runs the leading digital bank in the "
            "country and operates TBC Uzbekistan, the region's largest "
            "digital-only bank."
        ),
        "sources": [
            "https://tbcbankgroup.com/",
            "https://en.wikipedia.org/wiki/TBC_Bank",
            "https://www.tbcbank.ge/web/en",
        ],
        "sector": "Banks",
    },
    "203828304": {
        "description": (
            "JSC Liberty Bank is Georgia's third-largest bank, focused on "
            "mass-retail banking and the country's largest physical branch "
            "network (especially across regional and rural areas). Holds the "
            "exclusive contract to distribute state pensions and social "
            "benefits to ~1m Georgian beneficiaries."
        ),
        "sources": [
            "https://libertybank.ge/en",
            "https://en.wikipedia.org/wiki/Liberty_Bank_(Georgia)",
        ],
        "sector": "Banks",
    },
    "205232238": {
        "description": (
            "JSC Credo Bank is a Georgian microfinance-bank specialising in "
            "rural, agri and micro-SME lending. Founded as an MFI by World "
            "Vision and converted to a bank in 2017; majority-owned by ACCESS "
            "Microfinance Holding with EBRD, FMO and Triodos as IFI co-"
            "investors. ~80% of borrowers are outside Tbilisi."
        ),
        "sources": [
            "https://credobank.ge/en",
            "https://www.ebrd.com/work-with-us/projects/psd/53221.html",
        ],
        "sector": "Banks",
    },
    "203841833": {
        "description": (
            "JSC Basisbank is a mid-sized Georgian commercial bank focused on "
            "corporate and SME banking, controlled by Chinese conglomerate "
            "Hualing Group (90%+) since 2012. Operates a Tbilisi-centric "
            "branch network with a strong RMB-clearing and trade-finance "
            "franchise."
        ),
        "sources": [
            "https://www.basisbank.ge/en",
            "https://en.wikipedia.org/wiki/Basisbank",
        ],
        "sector": "Banks",
    },
    "204546045": {
        "description": (
            "JSC Terabank is a mid-sized Georgian commercial bank, majority-"
            "owned by Bahraini Al Salam Bank since 2016. Focuses on retail "
            "and SME banking via ~30 branches across Georgia, with growing "
            "premium-banking and Sharia-compliant product lines."
        ),
        "sources": [
            "https://terabank.ge/en",
            "https://en.wikipedia.org/wiki/Terabank",
        ],
        "sector": "Banks",
    },

    # ===== Oil & Gas (new) =====
    "202403121": {
        "description": (
            "SOCAR Georgia Gas LLC is the natural-gas distribution arm of "
            "SOCAR Energy Georgia (Azerbaijan's state oil company). Operates "
            "31,200km of low- and medium-pressure pipelines and supplies "
            "~944K residential and commercial customers across most of "
            "Georgia outside Tbilisi."
        ),
        "sources": [
            "https://sgp.ge/en",
            "https://www.socar.ge/en/socar-georgia",
        ],
        "sector": "Oil & Gas",
    },
    "406060471": {
        "description": (
            "SOCAR Gas Export-Import LLC handles cross-border natural-gas "
            "trading for the SOCAR Georgia group — imports gas from Azerbaijan "
            "via the South Caucasus Pipeline and on-sells to the domestic "
            "distribution arms and large industrial off-takers."
        ),
        "sources": [
            "https://www.socar.ge/en/socar-georgia",
        ],
        "sector": "Oil & Gas",
    },
    "202161098": {
        "description": (
            "JSC Wissol Petroleum Georgia is the country's second-largest fuel "
            "retailer (after SOCAR), running the Wissol-branded petrol-station "
            "network with ~140 stations. Part of the Wissol Group, also "
            "active in convenience retail (Smart) and quick-service catering."
        ),
        "sources": [
            "https://www.wissol.ge/en",
            "https://en.wikipedia.org/wiki/Wissol_Group",
        ],
        "sector": "Oil & Gas",
    },
    "204976302": {
        "description": (
            "LLC Lukoil-Georgia is the Georgian subsidiary of Russian oil "
            "major Lukoil, operating a network of ~80 Lukoil-branded petrol "
            "stations across the country. Part of Lukoil's broader fuel-"
            "retail footprint in the South Caucasus."
        ),
        "sources": [
            "https://lukoil.ge/",
            "https://en.wikipedia.org/wiki/Lukoil",
        ],
        "sector": "Oil & Gas",
    },
    "204493002": {
        "description": (
            "Rompetrol Georgia LLC is the Georgian fuel-retail arm of "
            "Romanian-Kazakh group KMG International (Rompetrol, parent: "
            "KazMunayGas). Operates the Rompetrol-branded petrol-station "
            "network including its 'Fill&Go' loyalty program."
        ),
        "sources": [
            "https://www.rompetrol.com.ge/",
            "https://en.wikipedia.org/wiki/Rompetrol",
        ],
        "sector": "Oil & Gas",
    },
    "202352514": {
        "description": (
            "SOCAR Georgia Petroleum LLC is the wholesale petroleum-products "
            "arm of SOCAR Energy Georgia, supplying gasoline, diesel and jet "
            "fuel into Georgia. Runs the country's largest fuel-retail "
            "network (~119 stations under the SOCAR / OPTIMA brands)."
        ),
        "sources": [
            "https://www.socar.ge/en/socar-georgia",
            "https://www.socarpetroleum.ge/",
        ],
        "sector": "Oil & Gas",
    },
    "208213119": {
        "description": (
            "Georgian Petroleum LLC is a domestic wholesale and retail fuel "
            "distributor active in gasoline, diesel and LPG, with petrol "
            "stations across multiple regions. A mid-tier player in the "
            "Georgian fuel-retail market dominated by SOCAR, Wissol, "
            "Rompetrol and Lukoil."
        ),
        "sources": [
            "https://reportal.ge/ka/Reports/Report?q=208213119",
        ],
        "sector": "Oil & Gas",
    },

    # ===== Power & Utilities (new) =====
    "405456082": {
        "description": (
            "JSC Energo-Pro Georgia Holding is the Georgian holding entity "
            "of Czech utility group Energo-Pro, owning the country's largest "
            "private electricity-distribution business (Energo-Pro Georgia, "
            "serving ~1m customers across all of Georgia outside Tbilisi) "
            "plus hydropower generation assets."
        ),
        "sources": [
            "https://www.energo-pro.com/en/about-us",
            "https://en.wikipedia.org/wiki/Energo-Pro",
        ],
        "sector": "Power & Utilities",
    },
    "405460594": {
        "description": (
            "EP Georgia Supply LLC is the licensed electricity-retail arm of "
            "the Energo-Pro Georgia group, contracting power purchases and "
            "billing end-customers under Georgia's unbundled electricity "
            "market reform."
        ),
        "sources": [
            "https://www.energo-pro.ge/",
        ],
        "sector": "Power & Utilities",
    },
    "205170036": {
        "description": (
            "JSC Electricity System Commercial Operator (ESCO) is Georgia's "
            "state-owned electricity-market operator, founded 2006. Acts as "
            "the central counterparty for the wholesale electricity market — "
            "balancing, settlements, cross-border trade — and operates the "
            "guaranteed-buyer scheme for renewable-energy PPAs."
        ),
        "sources": [
            "https://esco.ge/en",
            "https://www.gnerc.org/en/about-us/electricity-sector",
        ],
        "sector": "Power & Utilities",
    },
    "205169066": {
        "description": (
            "JSC Energo-Pro Georgia is the operating electricity-distribution "
            "subsidiary of Czech Energo-Pro group — the second-largest DSO in "
            "Georgia after Telasi, serving ~1m customers across the country "
            "outside Tbilisi via ~35,000km of distribution lines."
        ),
        "sources": [
            "https://www.energo-pro.ge/",
            "https://www.energo-pro.com/en/about-us",
        ],
        "sector": "Power & Utilities",
    },
    "204995176": {
        "description": (
            "JSC Georgian State Electrosystem (GSE) is the state-owned "
            "national electricity transmission system operator (TSO). Owns "
            "and operates Georgia's high-voltage grid (500/400/220/110 kV "
            "lines) and the country's cross-border interconnections to "
            "Russia, Turkey, Armenia and Azerbaijan."
        ),
        "sources": [
            "https://gse.com.ge/en",
            "https://en.wikipedia.org/wiki/Georgian_State_Electrosystem",
        ],
        "sector": "Power & Utilities",
    },
    "203826002": {
        "description": (
            "Georgian Water and Power LLC (GWP) is the regulated water-supply "
            "and wastewater utility serving greater Tbilisi (~1.4m people). "
            "Part of Georgia Global Utilities — a Georgia Capital portfolio "
            "company — and also operates small-hydro generation assets."
        ),
        "sources": [
            "https://gwp.ge/en",
            "https://georgiacapital.ge/our-business/water-utility",
        ],
        "sector": "Power & Utilities",
    },
    "404591599": {
        "description": (
            "JSC Georgia Global Utilities (GGU) is the holding for the water-"
            "supply and renewable-power businesses controlled by Georgia "
            "Capital. Includes Georgian Water and Power (Tbilisi water "
            "utility) and ~150MW of renewable-power generation (hydro + "
            "wind)."
        ),
        "sources": [
            "https://georgiacapital.ge/our-business/water-utility",
            "https://gse.ge/upload/eng_ggu_prospectus_4b1a4dcd.pdf",
        ],
        "sector": "Power & Utilities",
    },
    "404428071": {
        "description": (
            "Gardabani Thermal Power Plant LLC operates the Gardabani-1 (230 "
            "MW) and Gardabani-2 (272 MW) combined-cycle gas-turbine plants "
            "near Tbilisi — Georgia's largest base-load thermal capacity. "
            "Wholly owned by state operator GOGC."
        ),
        "sources": [
            "https://www.gogc.ge/en/power-generation",
            "https://www.power-technology.com/projects/gardabani-thermal-power-plant/",
        ],
        "sector": "Power & Utilities",
    },
    "202052580": {
        "description": (
            "JSC Telasi is the regulated electricity-distribution utility for "
            "the city of Tbilisi (~520K customers), majority-owned by "
            "Russia's Inter RAO. Operates ~7,500km of urban distribution "
            "network and the metering / billing infrastructure for the "
            "capital."
        ),
        "sources": [
            "https://telasi.ge/en",
            "https://en.wikipedia.org/wiki/Telasi",
        ],
        "sector": "Power & Utilities",
    },
    "405182626": {
        "description": (
            "JSC Energo-Pro Georgia Generation is the hydropower generation "
            "arm of Czech Energo-Pro group in Georgia, operating 16 cascade "
            "hydro plants (~480MW combined) on the Rioni, Adjaristsqali and "
            "other rivers — the largest private hydro fleet in the country."
        ),
        "sources": [
            "https://www.energo-pro.com/en/where-we-are/georgia",
            "https://www.energo-pro.ge/en/about-us",
        ],
        "sector": "Power & Utilities",
    },
    "205129617": {
        "description": (
            "Tbilisi Energy LLC is the sole natural-gas distribution operator "
            "for the city of Tbilisi (former KazTransGas-Tbilisi, sold to "
            "Georgian-owned Wartbay/Waltbay in 2019). Serves ~1.5m residents "
            "and ~18K commercial customers with ~1,300 employees."
        ),
        "sources": [
            "https://georgiatoday.ge/tbilisi-energy-we-are-trying-to-provide-gas-to-all-subscribers-by-2300/",
            "https://ge.linkedin.com/company/tbilisi-energy",
        ],
        "sector": "Power & Utilities",
    },
    "406312690": {
        "description": (
            "Telmico (Tbilisi Electricity Supply Company) LLC is the "
            "licensed electricity-retail arm serving Tbilisi end-customers, "
            "split out from Telasi under Georgia's electricity-market "
            "unbundling. Handles subscriber registration, billing and supply "
            "alongside Telasi's wires-only DSO role."
        ),
        "sources": [
            "https://www.telmico.ge/en",
            "https://tbcpay.ge/en/services/komunaluri-gadasaxadebi/telmico",
        ],
        "sector": "Power & Utilities",
    },
    "206267494": {
        "description": (
            "Tbilservice Group LLC is the 100%-municipally-owned operator "
            "providing Tbilisi's street cleaning, solid-waste collection, "
            "transport and recycling services, plus maintenance of "
            "underground crossings, fountains, parks and outdoor lighting. "
            "EBRD is financing the city's first waste-treatment plant via "
            "Tbilservice."
        ),
        "sources": [
            "https://tbilisi.gov.ge/news/4307?lang=en",
            "https://www.ebrd.com/home/news-and-events/news/2024/ebrd-finances-tbilisis-solid-waste-management-system.html",
        ],
        "sector": "Power & Utilities",
    },

    # ===== Pharma & Healthcare (new) =====
    "201991229": {
        "description": (
            "JSC GEPHA (Georgian Pharmaceutical Company) is one of Georgia's "
            "largest pharmaceutical groups, combining the GEPHA wholesale "
            "import/distribution business with the GPC pharmacy retail chain "
            "(formed via the 2019 GEPHA + Aversi-Rationali merger). Operates "
            "300+ pharmacy stores under multiple banners."
        ),
        "sources": [
            "https://gepha.com/en",
            "https://www.scoperatings.com/ratings-and-research/research/EN/172999",
        ],
        "sector": "Pharma & Healthcare",
        "sub_sector": "Pharmacy Retail",
    },
    "405098399": {
        "description": (
            "JSC Georgia Healthcare Group (GHG) is the largest healthcare "
            "services provider in Georgia, a Georgia Capital portfolio "
            "company (formerly LSE-listed). Operates ~40 hospitals, 20+ "
            "polyclinics, the largest pharma retail chain (Pharmadepot + "
            "GPC) and a medical-insurance arm — combined ~3,400 hospital "
            "beds and ~17,000 employees."
        ),
        "sources": [
            "https://georgiacapital.ge/our-business/healthcare-services",
            "https://en.wikipedia.org/wiki/Georgia_Healthcare_Group",
        ],
        "sector": "Pharma & Healthcare",
    },
    "405746634": {
        "description": (
            "JSC Georgia Healthcare Group (second filing entity) — part of "
            "the GHG group within Georgia Capital, covering the medical-"
            "services holding line. GHG's broader portfolio includes ~40 "
            "hospitals, 20+ polyclinics, pharma retail and medical insurance "
            "(see also idcode 405098399)."
        ),
        "sources": [
            "https://georgiacapital.ge/our-business/healthcare-services",
            "https://reportal.ge/ka/Reports/Report?q=405746634",
        ],
        "sector": "Pharma & Healthcare",
    },
    "202203123": {
        "description": (
            "PSP Pharma LLC is one of Georgia's largest pharmacy chains and "
            "pharmaceutical wholesalers, part of PSP Holding (founded 1993). "
            "Operates 250+ PSP-branded pharmacies nationwide and an "
            "in-house insurance arm (PSP Insurance)."
        ),
        "sources": [
            "https://www.psp.ge/en",
            "https://www.eu-neighbours.eu/sites/default/files/publications/2020-10/case-study-psp-pharmacies-en.pdf",
        ],
        "sector": "Pharma & Healthcare",
        "sub_sector": "Pharmacy Retail",
    },
    "211385268": {
        "description": (
            "GM Pharmaceuticals LLC (GMP) is Georgia's largest pharmaceutical "
            "manufacturer, producing ~140 brands across 230+ dosage forms at "
            "its Ponichala (Tbilisi) plant — the largest pharma facility in "
            "the South Caucasus. Exports across the CIS with 600+ employees."
        ),
        "sources": [
            "https://gmpharma.com/",
            "https://www.yell.ge/company.php?lan=eng&id=71149",
        ],
        "sector": "Pharma & Healthcare",
    },
    "204557121": {
        "description": (
            "Diplomat-Georgia LLC is a leading Georgian pharmaceutical "
            "wholesaler and distributor, part of Israel-based Diplomat "
            "Holdings — distributes branded pharma and OTC products to "
            "pharmacies and hospitals across Georgia, with a strong "
            "originator-drug franchise."
        ),
        "sources": [
            "https://diplomat.ge/en",
            "https://www.bia.ge/EN/Company/2167",
        ],
        "sector": "Pharma & Healthcare",
    },
    "400354629": {
        "description": (
            "Abulpharm LLC is a Tbilisi-based pharmaceutical distributor and "
            "wholesaler set up with Turkish investment (~USD 2m), operating "
            "a pharmaceutical warehouse in the Gldani industrial zone with "
            "regional export activity, particularly to Russia."
        ),
        "sources": [
            "https://bm.ge/en/news/2-pharmaceutical-warehouses-with-azerbaijan-and-turkish-investment-start-operating-in-tbilisi",
            "https://www.trademo.com/companies/abulpharm-llc/44449033",
        ],
        "sector": "Pharma & Healthcare",
    },
    "400354727": {
        "description": (
            "Shotapharm LLC is a Tbilisi-based pharmaceutical company "
            "operating in the Gldani / Tbilisi Technology Park free industrial "
            "zone, engaged in pharmaceutical manufacturing and distribution "
            "alongside other Turkish-linked pharma investments in Georgia."
        ),
        "sources": [
            "https://shotapharm.ge/ru.html",
            "https://reportal.ge/ka/Reports/Report?q=400354727",
        ],
        "sector": "Pharma & Healthcare",
    },

    # ===== Telecom (new) =====
    "204876606": {
        "description": (
            "Magticom LLC is the largest mobile network operator in Georgia "
            "by subscribers and revenue, founded 1996. Provides 4G/5G mobile, "
            "fixed broadband (via the MagtiNET FTTH network), pay-TV and "
            "data-centre services; majority-owned by the Bokeria/Jokhtaberidze "
            "family with Metromedia as minority shareholder."
        ),
        "sources": [
            "https://www.magticom.ge/en",
            "https://en.wikipedia.org/wiki/MagtiCom",
        ],
        "sector": "Telecom",
    },
    "204566978": {
        "description": (
            "JSC Silknet is Georgia's largest fixed-line telecom and "
            "second-largest mobile operator. Provides FTTH broadband, IPTV "
            "and fixed voice nationwide, plus mobile services after the 2018 "
            "acquisition of Geocell. Controlled by Silk Road Group / "
            "Ramishvili family."
        ),
        "sources": [
            "https://silknet.com/en",
            "https://en.wikipedia.org/wiki/Silknet",
        ],
        "sector": "Telecom",
    },
    "404569285": {
        "description": (
            "Silknet Holding LLC is the immediate holding entity above JSC "
            "Silknet — Georgia's largest fixed-line telecom operator (FTTH "
            "broadband + IPTV + post-Geocell mobile). Controlled by Silk "
            "Road Group; financials largely mirror the operating company."
        ),
        "sources": [
            "https://silknet.com/en",
            "https://reportal.ge/ka/Reports/Report?q=404569285",
        ],
        "sector": "Telecom",
    },
    "204450584": {
        "description": (
            "Cellfie Mobile LLC (Georgian-language brand 'Selfi Mobile', "
            "formerly Beeline Georgia) is Georgia's third-largest mobile "
            "network operator with ~1.3m subscribers. Rebranded from Beeline "
            "to Cellfie in 2023; sole winner of Georgia's 5G spectrum "
            "auction and first to launch commercial 5G in Tbilisi."
        ),
        "sources": [
            "https://cellfie.ge/en",
            "https://www.bia.ge/en/Company/1246",
        ],
        "sector": "Telecom",
    },

    # ===== Auto & Auto Parts (new) =====
    "200119923": {
        "description": (
            "GT Group LLC is a Georgian diversified holding (founded 1999, "
            "restructured 2005) operating across Georgia, Armenia, Uzbekistan "
            "and Turkmenistan. Sub-sectors: auto distribution (passenger cars "
            "and commercial vehicles, including BMW / MINI / Rolls-Royce via "
            "GT Motors), construction and agricultural machinery, lubricants "
            "and tyres, and food products (via Europroduct and Kolkhi Group)."
        ),
        "sources": [
            "https://gtgroup.ge/en/chvens-shesaxeb",
            "https://www.bia.ge/en/Company/400",
        ],
        "sector": "Conglomerate",
    },
    "206276340": {
        "description": (
            "GT Motors LLC is the automotive arm of GT Group — the official "
            "Georgian dealer for BMW, MINI and Rolls-Royce, plus commercial-"
            "vehicle brands. Operates flagship 3S (sales / service / parts) "
            "dealerships in Tbilisi alongside related-brand showrooms across "
            "the country."
        ),
        "sources": [
            "https://gtmotors.ge/en",
            "https://gtgroup.ge/en/chvens-shesaxeb",
        ],
        "sector": "Auto & Auto Parts",
    },
    "405408811": {
        "description": (
            "Tegeta Retail LLC is the retail-distribution arm of Tegeta "
            "Holding, operating multi-brand spare-parts, accessories and "
            "tyres outlets across Georgia (including the Tegeta Parts and "
            "Tegeta-branded retail formats) supplying both retail customers "
            "and B2B fleet operators."
        ),
        "sources": [
            "https://tegeta.ge/en/holding",
            "https://tegetamotors.ge/en",
        ],
        "sector": "Auto & Auto Parts",
    },
    "405006461": {
        "description": (
            "Toyota Center Tegeta LLC is the Toyota-brand 3S dealership "
            "operated by Tegeta Holding (separate from Toyota Caucasus, the "
            "Caucasus distributor). Sells new Toyota vehicles, runs after-"
            "sales service and supplies Toyota-original spare parts."
        ),
        "sources": [
            "https://tegetamotors.ge/en/toyota",
            "https://tegeta.ge/en/holding",
        ],
        "sector": "Auto & Auto Parts",
    },
    "206239729": {
        "description": (
            "Tegeta Truck and Bus LLC is the commercial-vehicle arm of "
            "Tegeta Holding — Georgia's exclusive MAN trucks dealer, plus "
            "buses and trailers. Supplies fleet customers across Georgia "
            "with sales, financing and aftermarket service via dedicated "
            "service centres."
        ),
        "sources": [
            "https://tegetamotors.ge/en",
            "https://tegeta.ge/en/holding",
        ],
        "sector": "Auto & Auto Parts",
    },
    "401950938": {
        "description": (
            "Tegeta Premium Vehicles LLC is the premium / luxury-brand arm "
            "of Tegeta Holding — Georgia's exclusive Porsche dealer (Porsche "
            "Centre Tbilisi) plus Bentley and other premium franchises. "
            "Operates Porsche-standard 3S facilities in Tbilisi."
        ),
        "sources": [
            "https://www.porsche.com/georgia/en/",
            "https://tegeta.ge/en/holding",
        ],
        "sector": "Auto & Auto Parts",
    },
    "211346220": {
        "description": (
            "Toyota Center Tbilisi LLC is one of the official Toyota-brand "
            "3S (sales / service / parts) dealerships in Tbilisi within the "
            "Toyota Caucasus distribution network — sells new Toyota and "
            "Lexus vehicles and runs Toyota-warrantied after-sales service."
        ),
        "sources": [
            "http://www.toyota-caucasus.com/",
            "https://reportal.ge/ka/Reports/Report?q=211346220",
        ],
        "sector": "Auto & Auto Parts",
    },
    "405660235": {
        "description": (
            "Sarda Georgia LLC is the Georgian arm of Sarda Group (HQ "
            "Azerbaijan), a diversified holding with automotive, hospitality, "
            "real-estate and logistics interests. In Georgia best known as "
            "the official Peugeot importer/dealer (Peugeot Georgia) since "
            "2023."
        ),
        "sources": [
            "https://www.sarda-group.com/peugeot-georgia",
            "https://www.sarda-group.com/about",
        ],
        "sector": "Auto & Auto Parts",
    },

    # ===== Retail - Grocery (new) =====
    "404923749": {
        "description": (
            "Majid Al Futtaim Hypermarkets Georgia LLC is the Carrefour "
            "franchise operator for Georgia, owned by Dubai-based Majid Al "
            "Futtaim. Runs Carrefour hypermarkets, supermarkets and "
            "convenience stores in Tbilisi, Batumi and Kutaisi — the only "
            "international hypermarket banner in the country."
        ),
        "sources": [
            "https://www.carrefour.ge/en",
            "https://www.majidalfuttaim.com/en/our-businesses/retail/carrefour",
        ],
        "sector": "Retail - Grocery",
    },
    "206335223": {
        "description": (
            "Jibe LLC is a Georgian cash & carry wholesale-retail chain "
            "operating the 'Jibe' shopping centres and the jibe.ge online "
            "hypermarket. Multiple branches in Tbilisi and the regions; "
            "positioned for SMB and HORECA customers alongside retail "
            "shoppers."
        ),
        "sources": [
            "https://jibe.ge/",
            "https://www.yell.ge/company.php?lan=eng&id=119199",
        ],
        "sector": "Retail - Grocery",
    },
    "405536317": {
        "description": (
            "Gvirila Retail LLC operates the 'Gvirila' Georgian discount "
            "grocery chain, with 350+ branches across nearly every region of "
            "Georgia — positioned squarely on price/affordability. Integrated "
            "with Liberty Bank's social-card benefits program."
        ),
        "sources": [
            "https://www.08.ge/organizations/view/323914/shps-gvirila",
            "https://libertybank.ge/ka/produqtebi/chemtvis/sotsialuri-baratis-benefitebi/gvirila",
        ],
        "sector": "Retail - Grocery",
    },
    "404502098": {
        "description": (
            "AgroHub LLC is Georgia's first natural-products hypermarket "
            "chain (founded 2016), operating 24/7 stores in Tbilisi "
            "(Vashlijvari, Vake, Saburtalo, Mtatsminda) and Batumi. "
            "Vertically integrated with an ISO22000-certified milk plant, "
            "own farms and bakery / confectionery production."
        ),
        "sources": [
            "https://agrohub.ge/en/topic/about",
            "https://www.bia.ge/en/Company/70592",
        ],
        "sector": "Retail - Grocery",
    },

    # ===== Retail - Apparel & Specialty (new) =====
    "202268928": {
        "description": (
            "JSC Elit Electronics is one of Georgia's largest consumer-"
            "electronics and home-appliance retailers. Operates a chain of "
            "stores across Tbilisi and major regional cities, plus an "
            "online channel; sells phones, computers, TVs and white-goods "
            "from major global brands."
        ),
        "sources": [
            "https://ee.ge/",
            "https://www.bia.ge/en/Company/484",
        ],
        "sector": "Retail - Apparel & Specialty",
    },
    "404399236": {
        "description": (
            "Retail Group Georgia LLC is the Georgian franchisee of Inditex "
            "and other international fashion brands — operates Zara, "
            "Bershka, Stradivarius, Pull&Bear, Massimo Dutti and Oysho "
            "stores in Tbilisi (Galleria, East Point, Tbilisi Mall) and "
            "Batumi."
        ),
        "sources": [
            "https://www.galleriatbilisi.ge/en/",
            "https://reportal.ge/ka/Reports/Report?q=404399236",
        ],
        "sector": "Retail - Apparel & Specialty",
    },
    "211380691": {
        "description": (
            "Alta LLC is a leading Georgian consumer-electronics and home-"
            "appliances retailer founded in 1997. Sells Apple, Samsung, "
            "Sony, AEG, Whirlpool, Philips and similar brands through 11+ "
            "stores plus an authorised service centre."
        ),
        "sources": [
            "https://alta.ge/",
            "https://www.bia.ge/en/Company/468",
        ],
        "sector": "Retail - Apparel & Specialty",
    },
    "402033312": {
        "description": (
            "AltaOkay LLC is the sister retail arm of Alta, operating the "
            "'Altaokay' branded mobile-phone, electronics and home-appliance "
            "stores across Tbilisi and the regions. Now broadly consolidated "
            "under the Alta consumer-electronics brand."
        ),
        "sources": [
            "https://www.interpressnews.ge/en/article/103327-altaokay-to-be-represented-on-the-market-under-the-name-of-alta/",
            "https://www.facebook.com/altaok.ge/",
        ],
        "sector": "Retail - Apparel & Specialty",
    },
    "202462717": {
        "description": (
            "Zoommer Georgia LLC is the largest consumer-electronics and "
            "digital-hardware retailer in Georgia, selling phones, "
            "accessories, computers and home electronics through stores "
            "and the zoomer.ge online channel. Multiple Tbilisi locations "
            "plus Wolt and Glovo delivery integration."
        ),
        "sources": [
            "https://zoomer.ge/",
            "https://wolt.com/en/geo/tbilisi/tbilisi-zoomer",
        ],
        "sector": "Retail - Apparel & Specialty",
    },
    "436041659": {
        "description": (
            "Retail Group LLC is a Tbilisi-based fashion retailer in the "
            "apparel / piece-goods wholesale and retail segment, "
            "headquartered on Telavi Street. Member of the UN Global Compact "
            "and part of Georgia's organised apparel-retail sector."
        ),
        "sources": [
            "https://unglobalcompact.org/what-is-gc/participants/165873-Retail-Group-LLC",
            "https://www.dnb.com/business-directory/company-profiles.retail_group_georgia_llc.45659240a41be0f2c8be301cc440910d.html",
        ],
        "sector": "Retail - Apparel & Specialty",
    },
    "406119178": {
        "description": (
            "Terminal West Trading LLC is a Tbilisi-based importer / "
            "exporter operating the domino.com.ge retail / e-commerce "
            "platform; trade footprint covers thousands of import shipments "
            "from Ukraine, Russia and Mexico and exports to Spain, Poland "
            "and Turkey."
        ),
        "sources": [
            "https://www.dnb.com/business-directory/company-profiles.terminal_west_trading_llc.b83cb5de19b29fee7132d3d4e67d1b31.html",
            "https://www.domino.com.ge/en/privacy-policy/",
        ],
        "sector": "Retail - Apparel & Specialty",
    },

    # ===== Food & Beverage (FMCG) (new) =====
    "201948063": {
        "description": (
            "JSC Coca-Cola Bottlers Georgia is the exclusive Coca-Cola "
            "system bottler for Georgia, part of the Coca-Cola HBC franchise "
            "network. Produces and distributes Coca-Cola, Fanta, Sprite, "
            "Schweppes, Powerade and the local Natakhtari soft-drinks "
            "range across the country."
        ),
        "sources": [
            "https://ru-ge.coca-colahellenic.com/en/",
            "https://reportal.ge/ka/Reports/Report?q=201948063",
        ],
        "sector": "Food & Beverage (FMCG)",
    },
    "404898973": {
        "description": (
            "Lactalis Georgia LLC is the Georgian subsidiary of French dairy "
            "major Groupe Lactalis (President, Galbani, Parmalat). Acquired "
            "local dairy producer Sante in 2018 and operates milk-collection, "
            "processing and packaging — leading positions in Georgia's "
            "drinking-milk, yogurt and cheese categories."
        ),
        "sources": [
            "https://www.lactalis.fr/en/group/our-presence/",
            "https://www.dairyglobal.net/industry-and-markets/market-trends/lactalis-takes-over-georgian-sante/",
        ],
        "sector": "Food & Beverage (FMCG)",
    },
    "204546553": {
        "description": (
            "Wimm-Bill-Dann Georgia LLC is the local arm of Russian dairy "
            "and juice major Wimm-Bill-Dann (owned by PepsiCo since 2011). "
            "Produces and distributes drinking milk, kefir, yogurt, juice "
            "and infant nutrition under brands including 'Domik v Derevne' "
            "and 'J7'."
        ),
        "sources": [
            "https://www.pepsico.com/our-brands",
            "https://en.wikipedia.org/wiki/Wimm-Bill-Dann_Foods",
        ],
        "sector": "Food & Beverage (FMCG)",
    },
    "223236013": {
        "description": (
            "JSC Lomisi is Georgia's leading brewer, owner of the Natakhtari "
            "beer brand (~55% domestic beer market share) plus a range of "
            "lemonades and natural soft drinks. Founded 1995 in Natakhtari "
            "village and a member of the Castel Group since 2008."
        ),
        "sources": [
            "https://en.wikipedia.org/wiki/Lomisi",
            "https://natakhtari.ge/en",
        ],
        "sector": "Food & Beverage (FMCG)",
    },
    "400132192": {
        "description": (
            "Partniori LLC is a Tbilisi-based wholesale food distributor "
            "(founded 2014) covering frozen fish, distilled alcoholic "
            "beverages, semi-finished products, bakery items, dairy and "
            "snacks. Operates as a B2B distribution partner to retailers "
            "and HORECA."
        ),
        "sources": [
            "https://www.bia.ge/company/36756",
            "https://www.companyinfo.ge/ka/people/300869",
        ],
        "sector": "Food & Beverage (FMCG)",
    },

    # ===== Wine & Spirits (new) =====
    "415099967": {
        "description": (
            "K and Georgian Spirits LLC is a Georgian alcoholic-beverages "
            "import-export company founded in 2017 in the Kutaisi / Imereti "
            "region. Trades distilled spirits and related alcohol products "
            "across the domestic wholesale channel."
        ),
        "sources": [
            "https://www.08.ge/organizations/view/270333",
            "https://tendermonitor.ge/ge/organization/175081",
        ],
        "sector": "Wine & Spirits",
    },

    # ===== Tobacco (new) =====
    "404387374": {
        "description": (
            "Philip Morris Sales and Marketing Georgia LLC is the Georgian "
            "subsidiary of Philip Morris International — marketer and "
            "distributor of Marlboro, Parliament, L&M, Chesterfield, "
            "Bond Street and IQOS heated-tobacco products in Georgia."
        ),
        "sources": [
            "https://www.pmi.com/markets/georgia/en/about-us/overview",
            "https://en.wikipedia.org/wiki/Philip_Morris_International",
        ],
        "sector": "Tobacco",
    },
    "404906731": {
        "description": (
            "JTI Caucasus LLC is the Georgian subsidiary of Japan Tobacco "
            "International (set up in Tbilisi in 2011) and the regional hub "
            "covering Armenia, Azerbaijan and Georgia. ~108 employees; "
            "distributes Winston, Camel, Sobranie, LD, Mevius and other JTI "
            "Global Flagship Brands."
        ),
        "sources": [
            "https://www.jti.com/en/our-company/where-we-operate/georgia",
            "https://tobaccoreporter.com/2023/07/09/tabaterra-to-produce-jti-brands-for-georgia/",
        ],
        "sector": "Tobacco",
    },
    "204920381": {
        "description": (
            "Elizi Group LLC is a Tbilisi-based importer of tobacco products, "
            "headquartered at 30 G. Svanidze St. Operates in Georgia's "
            "tobacco-distribution channel alongside the multinational "
            "incumbents."
        ),
        "sources": [
            "https://www.yell.ge/company.php?lan=eng&id=108835",
            "https://www.companyinfo.ge/ka/corporations/421817",
        ],
        "sector": "Tobacco",
    },

    # ===== Construction & Industrial Goods (new) =====
    "245416401": {
        "description": (
            "Anagi LLC is Georgia's largest general construction company "
            "(founded 1989), active in full-spectrum civil and industrial "
            "construction from design through commissioning. ISO 9001:2015 "
            "certified with 1,500+ employees; HQ on Kostava Street, Tbilisi."
        ),
        "sources": [
            "https://anagi.ge/en/",
            "https://www.bia.ge/EN/Company/1777",
        ],
        "sector": "Construction",
    },
    "404916114": {
        "description": (
            "Elsivaikiki GE LLC is the Georgian arm of a Chinese state-owned "
            "infrastructure contractor active in roads and highways "
            "construction (part of the CRCC / CR23-related cluster executing "
            "East-West Highway and Kvesheti-Kobi-type projects). Exact "
            "Chinese parent identification uncertain."
        ),
        "sources": [
            "https://civicidea.ge/wp-content/uploads/2025/01/CHINESE-COMPANY-CRTG-SECURITY-RISKS-AND-INFRASTRUCTURE-FAILURES.pdf",
            "https://transparency.ge/en/post/increasing-chinese-influence-georgia",
        ],
        "sector": "Construction",
    },
    "202358126": {
        "description": (
            "Nova LLC is the largest manufacturer and retailer of "
            "construction and repair materials in the South Caucasus, "
            "founded 2006 in Batumi. Produces 400+ items (roofing, "
            "plasterboard, polyethylene tanks, plastic profiles, traffic "
            "barriers) and runs three 'Nova' mega-centres in Tbilisi, "
            "Batumi and Kutaisi with 50,000+ SKUs."
        ),
        "sources": [
            "https://nova.ge/en/about-us",
            "https://eu4georgia.eu/construction-and-repair-materials-company-nova-prepares-for-entering-the-eu-market/",
        ],
        "sector": "Industrial Goods",
    },
    "404924285": {
        "description": (
            "Citadeli LLC is a Georgian construction-materials importer and "
            "distributor (founded 2011), supplying formwork, insulation, "
            "adhesives, tools and construction equipment from Rockwool, "
            "Peri, Liebherr, Sveza, Isover, Comansa and others. HQ at "
            "Agladze 32, Tbilisi."
        ),
        "sources": [
            "https://ge.linkedin.com/company/citadeli-%E1%83%AA%E1%83%98%E1%83%A2%E1%83%90%E1%83%93%E1%83%94%E1%83%9A%E1%83%98",
            "https://panjiva.com/Llc-Tsitadeli-Id-404924285-Building-Materials/178372994",
        ],
        "sector": "Industrial Goods",
    },
    "245619898": {
        "description": (
            "Adjara Textile LLC is a Turkish-investment apparel manufacturer "
            "(set up 2008) operating three sewing plants in Batumi, "
            "Kobuleti and Poti with ~7,000 employees, producing 10m+ units "
            "a year for Nike, Adidas, Puma and other global brands."
        ),
        "sources": [
            "https://www.fibre2fashion.com/news/apparel-news/georgia-s-ajara-textile-to-set-up-new-apparel-factory-268643-newsdetails.htm",
            "https://commersant.ge/en/news/business/adjara-textiles-income-soared-to-gel-3336-million",
        ],
        "sector": "Industrial Goods",
    },
    "205017578": {
        "description": (
            "GRC LLC is a major Georgian importer, manufacturer and "
            "wholesaler of construction and building materials, operating "
            "since 2003. Exclusive Georgian distributor of BASF, Firestone, "
            "Ursa, Technonicol, SSAB and VELUX, serving contractors and "
            "retail nationwide."
        ),
        "sources": [
            "https://grc.ge/about-us/",
            "https://ge.linkedin.com/company/grc-construction-materials",
        ],
        "sector": "Industrial Goods",
    },

    # ===== Mining & Metals (new) =====
    "216454646": {
        "description": (
            "Geoferrometal LLC is a Georgian ferro-alloys producer "
            "(ferromanganese / silicomanganese) operating smelting capacity "
            "based on regional manganese ore. Part of Georgia's broader "
            "Chiatura-area manganese / ferro-alloy industrial cluster."
        ),
        "sources": [
            "https://reportal.ge/ka/Reports/Report?q=216454646",
            "https://www.bia.ge/EN/Company/8050",
        ],
        "sector": "Mining & Metals",
    },
    "216425919": {
        "description": (
            "Geosteel LLC operates the largest rebar / construction-steel "
            "mini-mill in Georgia (Rustavi), producing reinforcing bars and "
            "billets for the domestic construction market and exports. "
            "Indian Steel Authority / Pramod Group joint-venture origin."
        ),
        "sources": [
            "https://geosteel.com.ge/en",
            "https://www.bia.ge/EN/Company/6420",
        ],
        "sector": "Mining & Metals",
    },
    "405336925": {
        "description": (
            "PM Metal LLC is a Georgian rebar and reinforcing-steel importer "
            "and processor based in Tbilisi, marketed as one of the leading "
            "suppliers of high-quality rebar in the local construction "
            "market with European-technology processing."
        ),
        "sources": [
            "https://pmmetal.ge/en/",
            "https://www.facebook.com/pmmetal1/",
        ],
        "sector": "Mining & Metals",
    },

    # ===== Logistics & Transport (new) =====
    "202886010": {
        "description": (
            "JSC Georgian Railway is the 100% state-owned vertically-"
            "integrated national rail operator, running ~1,326km of network "
            "linking the Black Sea ports (Poti, Batumi) to Azerbaijan and "
            "Armenia. Core business is freight transit — particularly "
            "Caspian oil — alongside long-distance passenger and Tbilisi "
            "suburban services."
        ),
        "sources": [
            "https://railway.ge/en/",
            "https://en.wikipedia.org/wiki/Georgian_Railway",
        ],
        "sector": "Logistics & Transport",
    },
    "206203491": {
        "description": (
            "TAV Urban Georgia LLC is the long-term concessionaire (until "
            "2027, with extension under negotiation) operating Tbilisi "
            "International Airport and Batumi International Airport. "
            "Wholly-owned subsidiary of Turkish airport-operator TAV "
            "Airports."
        ),
        "sources": [
            "https://www.tav.aero/en/airports/tbilisi",
            "https://en.wikipedia.org/wiki/TAV_Airports",
        ],
        "sector": "Logistics & Transport",
    },
    "215080999": {
        "description": (
            "JSC Corporation Poti Sea Port is Georgia's largest seaport "
            "(owned by APM Terminals / A.P. Moller-Maersk), handling ~80% "
            "of national container traffic plus liquids, dry bulk and "
            "ferries. 15 berths, 2,900m of quay, with a ~USD 200m expansion "
            "announced."
        ),
        "sources": [
            "https://www.apmterminals.com/en/poti",
            "https://www.ship-technology.com/projects/poti-sea-port-expansion/",
        ],
        "sector": "Logistics & Transport",
    },
    "202886788": {
        "description": (
            "Tbilisi Transport Company LLC is the wholly-municipal operator "
            "of public transport in Tbilisi — runs the two-line Tbilisi "
            "Metro (23 stations), city bus and minibus network, four "
            "aerial cable cars and one funicular. Flat 1 GEL fare; "
            "consolidated under SARAS as a state-owned PIE."
        ),
        "sources": [
            "https://ttc.com.ge/en/about-us",
            "https://en.wikipedia.org/wiki/Tbilisi_Metro",
        ],
        "sector": "Logistics & Transport",
    },
    "208144051": {
        "description": (
            "Sakaeronavigatsia LLC is Georgia's state-owned air navigation "
            "service provider (ANSP), founded 1999 — responsible for all "
            "air traffic control across Georgian airspace and the approach "
            "zones of Tbilisi, Kutaisi, Batumi and Mestia airports. "
            "Overflight traffic doubled between 2019 and 2023."
        ),
        "sources": [
            "https://airnav.ge/en/sahaero-modzraobis-martva",
            "https://canso.org/member/sakaeronavigatsia/",
        ],
        "sector": "Logistics & Transport",
    },
    "205116088": {
        "description": (
            "Georgian Distribution and Logistics LLC (GDL) is a diversified "
            "Georgian distributor with regional coverage since 2010 — full "
            "alcoholic-beverages portfolio since 2011, 3PL services since "
            "2018 and water distribution since 2019. ~12,000 active "
            "clients, 7 branches, 165 vehicles and 600 staff."
        ),
        "sources": [
            "http://gdl.ge/en/what-we-do",
            "https://ge.linkedin.com/company/gdlgeorgia",
        ],
        "sector": "Logistics & Transport",
    },
    "202282369": {
        "description": (
            "Georgian Distribution and Marketing Company LLC (GDMC) is one "
            "of Georgia's largest FMCG distributors (founded 2005), focused "
            "on import / wholesale of alcoholic beverages, food fats and "
            "food products. Operates five branches with warehouses in "
            "Tbilisi, Kutaisi, Batumi, Gurjaani and Akhaltsikhe."
        ),
        "sources": [
            "http://www.gdmco.ge/",
            "https://yp.com.ge/ka/organizations/org-70039-ge",
        ],
        "sector": "Logistics & Transport",
    },
    "454412387": {
        "description": (
            "US Trans LLC is a Georgian road-freight / trucking operator "
            "providing cargo transport and forwarding services under the "
            "ustrans.ge brand. Limited public information beyond the "
            "company website."
        ),
        "sources": [
            "https://www.ustrans.ge/",
            "https://reportal.ge/ka/Reports/Report?q=454412387",
        ],
        "sector": "Logistics & Transport",
    },
    "405208216": {
        "description": (
            "Petrocas Fuel Services Georgia LLC is part of Petrocas Energy "
            "Group (HQ Cyprus) — one of the country's largest jet-fuel "
            "suppliers and the FBO / handler at Tbilisi International "
            "Airport, providing into-plane fueling, aircraft and pilot "
            "services."
        ),
        "sources": [
            "https://www.iata.org/en/about/sp/partners-directory/petrocas-fuel-services-ltd/815/",
            "https://www.petrocasenergy.com/",
        ],
        "sector": "Oil & Gas",
    },

    # ===== Tech & IT (new) =====
    "405419961": {
        "description": (
            "EPAM Systems (Georgia) LLC is the Georgian delivery centre of "
            "NYSE-listed software-engineering services group EPAM Systems. "
            "Provides software engineering, consulting and product design "
            "for EPAM's global enterprise client base; one of the largest "
            "tech employers in Georgia (1,500+ engineers)."
        ),
        "sources": [
            "https://www.epam.com/about/who-we-are/locations/georgia",
            "https://en.wikipedia.org/wiki/EPAM_Systems",
        ],
        "sector": "Tech & IT",
    },
    "204892964": {
        "description": (
            "UGT LLC is Georgia's leading system integrator and IT "
            "solutions provider (founded 1997 — the only tech company on "
            "Forbes Georgia's Top 100 list). Sells computer hardware, "
            "security and video-surveillance systems, banking / cash-"
            "processing equipment, smart-building solutions and solar PV "
            "to corporates and government."
        ),
        "sources": [
            "https://ugt.ge/en",
            "https://www.bia.ge/en/Company/96",
        ],
        "sector": "Tech & IT",
    },
    "404891541": {
        "description": (
            "UGT Group LLC is the holding entity for the UGT family of "
            "technology businesses — eight subsidiaries including UGT "
            "(system integration), UGT Cloudforce (data centre), EnSol "
            "(energy solutions), Deline (IT distribution), PCShop.ge "
            "(retail), IT-Knowledge (training), Euro Marine Group "
            "(Ferretti yachts) and Lit.ge. ~300 employees group-wide."
        ),
        "sources": [
            "https://ugt.group/en",
            "https://ge.linkedin.com/company/ugt-group1",
        ],
        "sector": "Tech & IT",
    },

    # ===== Restaurants & QSR (new) =====
    "204909180": {
        "description": (
            "T & K Restaurants LLC is the master franchisee of McDonald's "
            "in Georgia, owned by Temur Chkonia and Tengiz Kapanadze. "
            "Operates the country's McDonald's restaurants across Tbilisi, "
            "Kutaisi and Batumi."
        ),
        "sources": [
            "https://www.info-clipper.com/en/company/georgia/t-k-restaurants-llc.ged9cp2gm.html",
            "https://ewsdata.rightsindevelopment.org/files/documents/TS/BNDES-TKRESTAURANTS.pdf",
        ],
        "sector": "Restaurants & QSR",
    },

    # ===== Real Estate Development (new) =====
    "204517399": {
        "description": (
            "JSC m2 Real Estate is Georgia's largest residential real estate "
            "developer, originally spun off from Bank of Georgia and now a "
            "Georgia Capital portfolio company. Develops mass-market and "
            "mid-tier apartment projects across Tbilisi and other cities "
            "and issues USD-denominated bonds listed on the GSE."
        ),
        "sources": [
            "https://m2.ge/en",
            "https://gse.ge/upload/final_prospectus_m2_usd25mn_oct_2016_eng_6_efa8b948.pdf",
        ],
        "sector": "Real Estate Development",
    },
    "404535240": {
        "description": (
            "SRG Real Estate LLC is the real-estate-development arm of "
            "Silk Road Group, focused on commercial and mixed-use property "
            "in Tbilisi. Projects within the SRG portfolio include Radisson "
            "Blu Iveria-adjacent assets and several Tbilisi office / "
            "hospitality developments."
        ),
        "sources": [
            "https://silkroadgroup.net/",
            "https://reportal.ge/ka/Reports/Report?q=404535240",
        ],
        "sector": "Real Estate Development",
    },
    "204875082": {
        "description": (
            "AKA LLC is a Tbilisi residential real-estate development "
            "business associated with the AKA Development / AKA Holding "
            "cluster of apartment-building projects in the capital. Exact "
            "legal-entity scope behind this ID is partially documented; "
            "sector inferred from related-brand activity."
        ),
        "sources": [
            "https://www.facebook.com/AKADevelopment/",
            "https://korter.ge/en/aka-development",
        ],
        "sector": "Real Estate Development",
    },

    # ===== Gambling (new) =====
    "405435596": {
        "description": (
            "Entain Georgia LLC is the local operating company of "
            "Crystalbet, the leading gaming and betting brand in Georgia, "
            "owned by LSE-listed Entain plc (acquired in two steps in "
            "2018 and 2021). Entain recently flagged Crystalbet as 'non-"
            "core' and earmarked for sale."
        ),
        "sources": [
            "https://igamingbusiness.com/strategy/ma/entain-considers-crystalbet-sale/",
            "https://www.proactiveinvestors.co.uk/companies/news/192593/gvc-has-georgia-on-its-mind-as-it-acquires-controlling-stake-in-crystalbet-192593.html",
        ],
        "sector": "Gambling",
    },
    "405099058": {
        "description": (
            "Mars LLC is a Tbilisi-based limited liability company wholly "
            "owned by Entain Georgia (Crystalbet group) and operating as "
            "part of the Crystalbet gambling / betting business — legal "
            "contact uses the crystalbet.com domain."
        ),
        "sources": [
            "https://www.companyinfo.ge/ka/corporations/277862",
            "https://compania.ge/405099058/marsi",
        ],
        "sector": "Gambling",
    },
    "405076304": {
        "description": (
            "Aviator LLC is a Tbilisi gambling / totalizator operator "
            "founded in 2023, associated with the well-known 'Aviator' "
            "crash-game brand and an Evolution Dual Play Roulette "
            "partnership at Casino Aviator Tbilisi."
        ),
        "sources": [
            "https://www.evolution.com/news/casino-aviator-tbilisi-chooses-evolution-dual-play-roulette/",
            "https://compania.ge/405076304/aviatori",
        ],
        "sector": "Gambling",
    },
    "405143303": {
        "description": (
            "Full House LLC is the operator of Crocobet, one of Georgia's "
            "leading licensed online sportsbook and casino brands (founded "
            "2017, gambling license 19-06/233). Runs crocobet.com plus a "
            "network of physical betting points."
        ),
        "sources": [
            "https://crocobetcasino.ge/",
            "https://www.dnb.com/business-directory/company-profiles.full_house_llc.63a3f0c82bae1b9b38366ffef4798f0e.html",
        ],
        "sector": "Gambling",
    },
    "404983238": {
        "description": (
            "Betlive LLC is a licensed Georgian online sportsbook and "
            "casino (launched 2017), one of the top three Georgian "
            "operators (~680k monthly visits). Offers sports betting, "
            "live casino and slots in GEL with content partnerships "
            "including BGaming and Beter."
        ),
        "sources": [
            "https://www.gambl.com/betting/betlive",
            "https://igamingbusiness.com/company-news/beter-partners-with-betlive-to-significantly-expand-georgia-presence/",
        ],
        "sector": "Gambling",
    },

    # ===== Other / Conglomerate / UNKNOWN (new) =====
    "404579354": {
        "description": (
            "Silk Road Group Holding LLC is one of Georgia's largest "
            "privately-held diversified investment groups (founded 1997 by "
            "George Ramishvili), with cumulative investments of ~USD 1bn "
            "and 5,000+ employees. Sub-sectors: telecom (historical Silknet "
            "and Geocell stakes), hospitality (Radisson Blu Tbilisi / Batumi "
            "/ Tsinandali, Park Hotel), real estate (Silk Real Estate), "
            "logistics (Caspian rail and Black Sea cargo), hydropower, "
            "banking (Silk Bank) and media franchises."
        ),
        "sources": [
            "https://silkroadgroup.net/",
            "https://en.wikipedia.org/wiki/Silk_Road_Group",
        ],
        "sector": "Conglomerate",
    },
    "404572789": {
        "description": (
            "Atlas Holdings LLC is a Georgian privately-held investment / "
            "holding company that ranks in the top tier of Georgian "
            "corporates by 2024 revenue. Sub-sectors not fully verified "
            "from publicly indexed sources — appears to be a diversified "
            "holding spanning multiple operating segments."
        ),
        "sources": [
            "https://reportal.ge/ka/Reports/Report?q=404572789",
        ],
        "sector": "Conglomerate",
    },
    "406181616": {
        "description": (
            "JIDIAI LLC (Georgian: ჯიდიაი) is a Georgian limited liability "
            "company founded in 2016, headquartered in Tbilisi, with a 20% "
            "stake held by Corinaria Management. Specific business activity "
            "is not disclosed in public registries; sector could not be "
            "confirmed."
        ),
        "sources": [
            "https://www.companyinfo.ge/en/corporations/255316",
            "https://reportal.ge/ka/Reports/Report?q=406181616",
        ],
        "sector": "Other",
    },
    "405221950": {
        "description": (
            "GEIG LLC is a Georgian limited liability company registered "
            "with the Service for Accounting Reporting that ranks in the "
            "top-100 Georgian corporates by 2024 revenue. Specific "
            "business activity and sector are not disclosed in publicly "
            "indexed sources."
        ),
        "sources": [
            "https://reportal.ge/ka/Reports/Report?q=405221950",
        ],
        "sector": "Other",
    },
    "402049617": {
        "description": (
            "EL TI LLC is a Georgian limited liability company registered "
            "with the Service for Accounting Reporting that ranks in the "
            "top-100 Georgian corporates by 2024 revenue. Identity and "
            "business activity are not publicly indexed; sector could not "
            "be confirmed."
        ),
        "sources": [
            "https://reportal.ge/ka/Reports/Report?q=402049617",
        ],
        "sector": "Other",
    },

    # ===== Oil & Gas tail (extra fuel retail) =====
    "405074128": {
        "description": (
            "Repsoli LLC operates the 'Connect' Georgian fuel-retail network "
            "(~35+ petrol stations) across Tbilisi, Batumi, Kutaisi and "
            "regional cities. Sells gasoline and diesel and operates a "
            "petroleum-product storage terminal in Gardabani."
        ),
        "sources": [
            "https://connect.com.ge/contact-us/",
            "https://www.bia.ge/Company/87930",
        ],
        "sector": "Oil & Gas",
    },

    # ===== Banks tail (top-15 by 2024 Total Assets; the big two and Credo,
    #       Liberty, Basisbank, Tera are already covered above) =====
    "204891652": {
        "description": (
            "JSC Cartu Bank is a Georgian commercial bank founded in 1996 by "
            "Bidzina Ivanishvili and historically tied to the Cartu Group "
            "family of companies. It focuses on corporate and SME lending, "
            "trade finance and high-net-worth private banking, with a small "
            "branch network compared to BoG/TBC but a sizeable corporate "
            "loan book."
        ),
        "sources": [
            "https://cartubank.ge/en",
            "https://en.wikipedia.org/wiki/Cartu_Bank",
        ],
        "sector": "Banks",
    },
    "204851197": {
        "description": (
            "JSC ProCredit Bank (Georgia) is the local subsidiary of "
            "Frankfurt-listed ProCredit Holding, a development-oriented "
            "banking group focused on responsible SME lending in transition "
            "economies. The Georgian unit is one of the country's larger "
            "SME-specialist banks, with a digital-first service model and "
            "an emphasis on green-finance products."
        ),
        "sources": [
            "https://www.procreditbank.ge/en",
            "https://www.procredit-holding.com/group/procredit-bank-georgia/",
        ],
        "sector": "Banks",
    },
    "205236537": {
        "description": (
            "JSC Halyk Bank Georgia is the Georgian subsidiary of Kazakhstan's "
            "Halyk Bank (Halyk Savings Bank of Kazakhstan), the largest "
            "bank in Central Asia. It operates as a universal commercial bank "
            "in Georgia with retail, SME and corporate banking lines."
        ),
        "sources": [
            "https://www.halykbank.ge/en",
            "https://halykbank.com/about-bank",
        ],
        "sector": "Banks",
    },
    "205034639": {
        "description": (
            "Rico Express LLC is one of Georgia's largest microfinance "
            "organisations, operating under NBG MFO licence rather than a "
            "bank licence. It provides consumer loans, pawn-shop lending "
            "(gold-backed) and money-transfer services across a broad branch "
            "network."
        ),
        "sources": [
            "https://rico.ge/en",
            "https://nbg.gov.ge/en/page/microfinance-organizations",
        ],
        "sector": "Non-bank Credit (MFO/Leasing)",
    },
    "404433671": {
        "description": (
            "JSC PASHA Bank Georgia is the Georgian subsidiary of "
            "Azerbaijan's PASHA Bank, part of PASHA Holding. It positions as "
            "a corporate / investment bank serving large Georgian corporates "
            "and Azerbaijani-Georgian cross-border trade and investment "
            "flows."
        ),
        "sources": [
            "https://www.pashabank.ge/en",
            "https://en.wikipedia.org/wiki/PASHA_Bank",
        ],
        "sector": "Banks",
    },
    "205016560": {
        "description": (
            "JSC TBC Leasing is the leasing subsidiary of TBC Bank Group "
            "(LSE: TBCG) and the largest leasing company in Georgia. It "
            "offers operating and financial leases for vehicles, "
            "construction and industrial equipment, and is regulated as a "
            "non-bank financial institution by the NBG."
        ),
        "sources": [
            "https://www.tbcleasing.ge/en",
            "https://www.tbcbankgroup.com/about-us/our-business/",
        ],
        "sector": "Non-bank Credit (MFO/Leasing)",
    },
    "212896570": {
        "description": (
            "JSC MFO Crystal is one of Georgia's largest microfinance "
            "organisations, founded in 1998 as an EU/USAID-funded MFI in "
            "Kutaisi. It serves micro and SME borrowers (predominantly "
            "outside Tbilisi) and has issued GEL-denominated bonds on the "
            "Georgian Stock Exchange."
        ),
        "sources": [
            "https://crystal.ge/en",
            "https://www.ebrd.com/work-with-us/projects/psd/crystal.html",
        ],
        "sector": "Non-bank Credit (MFO/Leasing)",
    },
    "404496611": {
        "description": (
            "JSC Isbank Georgia is the Georgian subsidiary of Türkiye İş "
            "Bankası, Turkey's oldest and one of its largest private banks. "
            "It focuses on corporate banking, trade finance and Turkish-"
            "Georgian cross-border business."
        ),
        "sources": [
            "https://www.isbank.ge/en",
            "https://en.wikipedia.org/wiki/T%C3%BCrkiye_%C4%B0%C5%9F_Bankas%C4%B1",
        ],
        "sector": "Banks",
    },
    "202906427": {
        "description": (
            "JSC VTB Bank Georgia is the Georgian subsidiary of Russia's "
            "VTB Group. It operates as a universal commercial bank in "
            "Georgia with retail and corporate banking lines; activity has "
            "been constrained since 2022 by international sanctions on the "
            "Russian parent."
        ),
        "sources": [
            "https://www.vtb.com.ge/en",
            "https://en.wikipedia.org/wiki/VTB_Bank",
        ],
        "sector": "Banks",
    },

    # ===== Insurers top-5 by 2024 Total Assets =====
    "404476189": {
        "description": (
            "JSC Insurance Company Aldagi is Georgia's largest insurer by "
            "premiums and assets, a wholly-owned subsidiary of Lion Finance "
            "Group (LSE: BGEO, formerly Bank of Georgia Group). It writes "
            "P&C, health, motor and corporate lines and is the market "
            "leader in medical insurance."
        ),
        "sources": [
            "https://www.aldagi.ge/en",
            "https://lionfinancegroup.uk/about-us/",
        ],
        "sector": "Insurance",
    },
    "405042804": {
        "description": (
            "JSC TBC Insurance is the insurance arm of TBC Bank Group "
            "(LSE: TBCG), launched in 2016 to bancassure TBC's retail and "
            "SME clients. Underwrites motor, health, property and travel "
            "lines distributed primarily through TBC Bank's branch network "
            "and mobile app."
        ),
        "sources": [
            "https://www.tbcinsurance.ge/en",
            "https://www.tbcbankgroup.com/about-us/our-business/",
        ],
        "sector": "Insurance",
    },
    "204426674": {
        "description": (
            "JSC Insurance Company GPI Holding is one of Georgia's three "
            "largest insurers, majority-owned by Vienna Insurance Group "
            "(VIG, Austria's largest insurer). It writes the full mix of "
            "P&C, motor, health and life lines through Georgia's largest "
            "agent network."
        ),
        "sources": [
            "https://www.gpih.ge/en",
            "https://www.vig.com/en/about-vig/companies/",
        ],
        "sector": "Insurance",
    },
    "204919008": {
        "description": (
            "JSC Insurance Company Imedi L is one of Georgia's oldest "
            "insurers (founded 1996). It writes motor, health, property "
            "and travel insurance, with traditional strength in motor "
            "third-party liability (compulsory MTPL) and SME corporate "
            "policies."
        ),
        "sources": [
            "https://www.imedil.ge/en",
            "https://insurance.gov.ge/en",
        ],
        "sector": "Insurance",
    },
    "205023856": {
        "description": (
            "JSC IRAO (International Reinsurance and Insurance Company) is a "
            "long-standing Georgian general insurer founded in 1996, "
            "writing P&C, motor, health and travel lines and offering "
            "reinsurance capacity. Family-owned, mid-sized by premiums."
        ),
        "sources": [
            "https://www.irao.ge/en",
            "https://insurance.gov.ge/en",
        ],
        "sector": "Insurance",
    },
}


def _validate_sectors() -> None:
    """Fail fast if any merged entry uses a sector outside SECTORS — guards
    against typos that would let a stray bucket leak into the dashboard.
    Warns (but does not fail) on sub-sectors not yet in SUB_SECTORS, since
    sub-sectors are still being curated and we want novel values surfaced
    rather than blocked."""
    merged = dict(DESCRIPTIONS)
    for idc, payload in _load_extra_descriptions().items():
        merged.setdefault(idc, payload)

    bad = []
    novel_sub: list[tuple[str, str, str]] = []
    for idc, payload in merged.items():
        sec = payload.get("sector")
        if sec not in SECTORS:
            bad.append((idc, sec))
        sub = payload.get("sub_sector")
        if sub:
            known = SUB_SECTORS.get(sec, set())
            if sub not in known:
                novel_sub.append((idc, sec, sub))
    if bad:
        raise ValueError(
            f"Invalid sector(s) in merged DESCRIPTIONS (not in SECTORS): "
            f"{len(bad)} bad. First few: {bad[:5]}"
        )
    if novel_sub:
        print(f"Novel sub-sector labels: {len(novel_sub)} (first 10 shown)")
        for idc, sec, sub in novel_sub[:10]:
            print(f"  {idc}  {sec} -> {sub}")


def _load_extra_descriptions() -> dict:
    """Read the sidecar JSON of agent-generated entries. Empty if missing
    (lets the script still run if you've only got the inline dict)."""
    if not EXTRA_JSON.exists():
        return {}
    with EXTRA_JSON.open(encoding="utf-8") as f:
        return json.load(f)


def _merged_descriptions() -> dict:
    """Hand-curated DESCRIPTIONS take priority; sidecar JSON fills the tail.
    Returns a fresh dict so callers can mutate without touching the module."""
    merged: dict = dict(DESCRIPTIONS)
    for idc, payload in _load_extra_descriptions().items():
        if idc in merged:
            continue  # hand-curated wins
        merged[idc] = payload
    return merged


def apply(db_path: Path) -> dict:
    _validate_sectors()
    all_descriptions = _merged_descriptions()
    conn = sqlite3.connect(str(db_path))
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(companies)").fetchall()]
        added = []
        if "Description" not in cols:
            conn.execute("ALTER TABLE companies ADD COLUMN Description TEXT")
            added.append("Description")
        if "DescriptionSources" not in cols:
            conn.execute("ALTER TABLE companies ADD COLUMN DescriptionSources TEXT")
            added.append("DescriptionSources")
        if "DescriptionUpdatedAt" not in cols:
            conn.execute("ALTER TABLE companies ADD COLUMN DescriptionUpdatedAt TEXT")
            added.append("DescriptionUpdatedAt")
        if "Sector" not in cols:
            conn.execute("ALTER TABLE companies ADD COLUMN Sector TEXT")
            added.append("Sector")
        if "SubSector" not in cols:
            conn.execute("ALTER TABLE companies ADD COLUMN SubSector TEXT")
            added.append("SubSector")
        if added:
            conn.commit()

        updated = 0
        not_found = []
        for idc, payload in all_descriptions.items():
            row = conn.execute(
                "SELECT 1 FROM companies WHERE IdCode = ?", (idc,)
            ).fetchone()
            if not row:
                not_found.append(idc)
                continue
            conn.execute(
                "UPDATE companies SET "
                "Description = ?, DescriptionSources = ?, DescriptionUpdatedAt = ?, "
                "Sector = ?, SubSector = ? "
                "WHERE IdCode = ?",
                (
                    payload["description"],
                    json.dumps(payload["sources"], ensure_ascii=False),
                    SEED_BATCH_DATE,
                    payload["sector"],
                    payload.get("sub_sector"),  # None when not yet classified
                    idc,
                ),
            )
            updated += 1
        conn.commit()

        # Sector/sub-sector histograms for sanity-checking after a run.
        sector_counts: dict[str, int] = {}
        sub_sector_counts: dict[str, int] = {}
        for payload in all_descriptions.values():
            sec = payload.get("sector", "Other")
            sector_counts[sec] = sector_counts.get(sec, 0) + 1
            sub = payload.get("sub_sector")
            if sub:
                key = f"{sec} / {sub}"
                sub_sector_counts[key] = sub_sector_counts.get(key, 0) + 1

        return {
            "db_path": str(db_path),
            "columns_added": added,
            "hand_curated_entries": len(DESCRIPTIONS),
            "extra_json_entries": len(_load_extra_descriptions()),
            "merged_total": len(all_descriptions),
            "rows_updated": updated,
            "idcodes_not_found_in_companies": len(not_found),
            "batch_date": SEED_BATCH_DATE,
            "sector_counts": dict(sorted(sector_counts.items(), key=lambda x: -x[1])),
            "sub_sector_counts": dict(sorted(sub_sector_counts.items(), key=lambda x: -x[1])),
            "entries_with_sub_sector": sum(1 for p in all_descriptions.values() if p.get("sub_sector")),
        }
    finally:
        conn.close()


def main(argv: list[str]) -> int:
    db = Path(argv[1]).resolve() if len(argv) > 1 else DEFAULT_DB
    if not db.exists():
        print(f"ERROR: DB not found at {db}", file=sys.stderr)
        return 2
    print(f"Seeding {len(DESCRIPTIONS)} company descriptions into {db} ...")
    result = apply(db)
    for k, v in result.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

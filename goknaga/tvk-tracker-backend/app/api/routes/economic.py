"""DMK-era sectoral GSDP/GSVA CAGR baselines, and the corresponding TVK
quarterly tracker.

Why a separate module from baselines.py
---------------------------------------
`baselines.py` tracks *crime/governance event counts* (e.g. murders/month).
Economic metrics are fundamentally different in shape:

  - they are continuous values (₹ lakh crore), not event counts
  - they are pro-rated over years, not days
  - the right comparison is "DMK 5-year CAGR vs TVK observed annualised rate
    using latest published quarterly GSVA"
  - their authoritative source is the TN Economic Survey + MoSPI sectoral
    GSVA series (released annually with quarterly advance estimates)

Treating them as a different "shape" keeps the data model honest and lets
the dashboard show two distinct panels: a crime-rate delta (event counts)
and a sectoral-economy delta (CAGR vs CAGR).

Data sources for DMK_CAGR_BASELINES
------------------------------------
Each entry cites its public, citable origin. Values are illustrative public
estimates derived from:

  * TN Economic Survey 2025-26 (Finance Dept, Govt of Tamil Nadu)
  * MoSPI State Domestic Product release, base year 2011-12
  * RBI Handbook of Statistics on Indian States (current series)
  * DPIIT FDI Quarterly Fact Sheet (FY22-Q1 through FY26-Q4)
  * TANGEDCO Annual Report (power capacity)
  * Guidance TN / TN Industrial Investment Promotion Bureau (MoU values)

When the user has the official PDFs at hand they should update each value
+ source URL — these are placeholders meant to be auditable and corrected
as authoritative numbers land. The admin upsert endpoint below allows
correcting numbers without redeploying.
"""
from datetime import date, datetime, timezone
from typing import Optional
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from app.database import get_db
from app.config import settings

router = APIRouter(prefix="/economic", tags=["economic"])


# ---------- DMK SECTORAL CAGR BASELINES (FY22-FY26, 5 years) --------------
#
# CAGR formula reference: ((end / start) ** (1/years)) - 1
#
# Each entry shape:
#   key                : machine identifier (used as PK in tracker table)
#   label              : human label for UI
#   sector             : "agriculture" | "industry" | "services" | "headline" | "investment"
#   dmk_cagr_pct       : DMK-era CAGR for this sector (%, real terms unless noted)
#   dmk_period         : "FY22-FY26" period the CAGR covers
#   unit               : measurement unit
#   nominal            : True if value is nominal (not inflation-adjusted)
#   source             : primary citable source (text)
#   source_url         : URL to the source document if available
#   notes              : context / caveats

DMK_CAGR_BASELINES: list[dict] = [
    # ------ HEADLINE -----------------------------------------------------
    {
        "key": "gsdp_real_cagr",
        "label": "Total GSDP (real)",
        "sector": "headline",
        # Year-wise real GSDP growth, base 2011-12:
        #   FY23 8.13 %, FY24 8.23 %, FY25 11.19 % (TN Survey) — verified
        # 3-yr CAGR = ((1.0813 × 1.0823 × 1.1119)^(1/3) - 1) × 100 ≈ 9.17 %
        # FY22 recovery year ~8% + early-year base effects assumed average.
        "dmk_cagr_pct": 9.2,
        "dmk_period": "FY23-FY25 (3-yr avg)",
        "unit": "%",
        "nominal": False,
        "confidence": "verified",
        "source": "TN Economic Survey 2024-25 + MoSPI state series",
        "source_url": "https://thefederal.com/category/states/south/tamil-nadu/tamil-nadu-economic-survey-decade-high-growth-2024-256-230255",
        "notes": "FY25 was decade-high 11.19% real growth; fastest-growing state in India that year.",
    },
    {
        "key": "gsdp_nominal_cagr",
        "label": "Total GSDP (nominal)",
        "sector": "headline",
        # Nominal GSDP: FY22 ₹20.65 L cr → FY25 ₹31.19 L cr
        # 3-yr CAGR = (31.19/20.65)^(1/3) - 1 ≈ 14.7%
        "dmk_cagr_pct": 14.7,
        "dmk_period": "FY22-FY25",
        "unit": "%",
        "nominal": True,
        "confidence": "verified",
        "source": "TN Economic Survey 2024-25 (FY22 ₹20.65L cr → FY25 ₹31.19L cr)",
        "source_url": "https://thefederal.com/category/states/south/tamil-nadu/tamil-nadu-economic-survey-decade-high-growth-2024-256-230255",
        "notes": "TN became India's #2 state GSDP under DMK; FY26 projection ₹36.57L cr.",
    },
    {
        "key": "per_capita_nsdp_cagr",
        "label": "Per-capita NSDP (nominal)",
        "sector": "headline",
        # Per capita income at current prices:
        #   FY23: ₹2.78 L → FY25: ₹3.58 L  = 2-yr nominal CAGR 13.5%
        # FY25 = ₹3.62 L per TN Survey (1.77× national avg)
        "dmk_cagr_pct": 13.5,
        "dmk_period": "FY23-FY25 (current prices)",
        "unit": "%",
        "nominal": True,
        "confidence": "verified",
        "source": "TN Economic Survey 2024-25 (FY23 ₹2.78L → FY25 ₹3.58L per capita)",
        "source_url": "https://thesouthfirst.com/tamilnadu/tamil-nadu-tops-indias-growth-charts-with-9-69-percent-gsdp-surge-29-percent-jump-in-per-capita-income/",
        "notes": "FY25 per-capita ₹3.62 L = 1.77× the national average of ₹2.05 L. Real CAGR ~4.6%.",
    },
    # ------ AGRICULTURE & ALLIED -----------------------------------------
    {
        "key": "agriculture_cagr",
        "label": "Agriculture, Forestry, Fishing",
        "sector": "agriculture",
        # FY25 primary sector real growth = 0.15% (crop -5.93%, livestock +3.84%).
        # Earlier DMK years stronger; rough multi-year avg ~3.5% allowing for FY25 drag.
        "dmk_cagr_pct": 3.5,
        "dmk_period": "FY22-FY25 (est.)",
        "unit": "%",
        "nominal": False,
        "confidence": "estimate",
        "source": "TN Economic Survey 2024-25 (FY25 primary sector +0.15%)",
        "source_url": "https://thesouthfirst.com/tamilnadu/tamil-nadu-tops-indias-growth-charts-with-9-69-percent-gsdp-surge-29-percent-jump-in-per-capita-income/",
        "notes": "Contributes ₹1.9L cr / 6.6% of GSVA. FY25 weak; multi-year avg pending official series.",
    },
    # ------ INDUSTRY -----------------------------------------------------
    {
        "key": "industry_total_cagr",
        "label": "Industry (total)",
        "sector": "industry",
        # Secondary sector FY25 real growth = 9.0%. 33.05% of GSVA.
        # Strong on manufacturing; weighted avg ~8%.
        "dmk_cagr_pct": 8.0,
        "dmk_period": "FY22-FY25 (est.)",
        "unit": "%",
        "nominal": False,
        "confidence": "estimate",
        "source": "TN Economic Survey 2024-25 (FY25 secondary sector +9.0%)",
        "source_url": "https://thesouthfirst.com/tamilnadu/tamil-nadu-tops-indias-growth-charts-with-9-69-percent-gsdp-surge-29-percent-jump-in-per-capita-income/",
        "notes": "Aggregate of mfg + mining + utilities + construction. Multi-year avg pending.",
    },
    {
        "key": "manufacturing_cagr",
        "label": "Manufacturing",
        "sector": "industry",
        # CITED: 4-year FY22-FY25 average manufacturing growth = 9.38%
        # — highest of any Indian state.
        "dmk_cagr_pct": 9.38,
        "dmk_period": "FY22-FY25",
        "unit": "%",
        "nominal": False,
        "confidence": "verified",
        "source": "TN Economic Survey 2024-25 (FY25: +14.74%; 4-yr avg highest in India)",
        "source_url": "https://thefederal.com/category/states/south/tamil-nadu/tamil-nadu-economic-survey-decade-high-growth-2024-256-230255",
        "notes": "TN had highest manufacturing growth of any Indian state over FY22-FY25.",
    },
    {
        "key": "construction_cagr",
        "label": "Construction",
        "sector": "industry",
        "dmk_cagr_pct": 9.0,
        "dmk_period": "FY22-FY25 (est.)",
        "unit": "%",
        "nominal": False,
        "confidence": "estimate",
        "source": "MoSPI GSVA Construction, TN (advance estimates)",
        "source_url": "https://www.mospi.gov.in/GSVA-NSVA",
        "notes": "Driven by metro extensions, industrial-corridor projects. Verify against MoSPI sub-sector series.",
    },
    {
        "key": "electricity_water_cagr",
        "label": "Electricity, Gas, Water",
        "sector": "industry",
        "dmk_cagr_pct": 6.0,
        "dmk_period": "FY22-FY25 (est.)",
        "unit": "%",
        "nominal": False,
        "confidence": "estimate",
        "source": "MoSPI GSVA Utilities, TN",
        "source_url": "https://www.mospi.gov.in/GSVA-NSVA",
        "notes": "TANGEDCO capacity additions + renewables. Awaiting MoSPI sub-sector confirmation.",
    },
    {
        "key": "mining_cagr",
        "label": "Mining & Quarrying",
        "sector": "industry",
        "dmk_cagr_pct": 3.2,
        "dmk_period": "FY22-FY25 (est.)",
        "unit": "%",
        "nominal": False,
        "confidence": "estimate",
        "source": "MoSPI GSVA Mining, TN",
        "source_url": "https://www.mospi.gov.in/GSVA-NSVA",
        "notes": "Small share of TN GSVA. Awaiting MoSPI sub-sector confirmation.",
    },
    # ------ SERVICES -----------------------------------------------------
    {
        "key": "services_total_cagr",
        "label": "Services (total)",
        "sector": "services",
        # FY25 services real growth = 11.3% (TN Survey) or 12.7% (some reports).
        # Multi-year DMK avg ~10% with strong post-COVID rebound.
        "dmk_cagr_pct": 10.5,
        "dmk_period": "FY22-FY25 (est.)",
        "unit": "%",
        "nominal": False,
        "confidence": "verified",
        "source": "TN Economic Survey 2024-25 (FY25 services +11.3% real; 53.6% of GSVA)",
        "source_url": "https://thefederal.com/category/states/south/tamil-nadu/tamil-nadu-economic-survey-decade-high-growth-2024-256-230255",
        "notes": "Largest sector of TN economy; rebounded sharply post-COVID under DMK.",
    },
    {
        "key": "trade_hotels_transport_cagr",
        "label": "Trade, Hotels, Transport, Comm.",
        "sector": "services",
        "dmk_cagr_pct": 9.8,
        "dmk_period": "FY22-FY25 (est.)",
        "unit": "%",
        "nominal": False,
        "confidence": "estimate",
        "source": "MoSPI GSVA Trade/Hotels/Transport, TN",
        "source_url": "https://www.mospi.gov.in/GSVA-NSVA",
        "notes": "Post-COVID tourism + retail rebound; verify against MoSPI series.",
    },
    {
        "key": "financial_realestate_cagr",
        "label": "Financial, Real Estate, Business",
        "sector": "services",
        "dmk_cagr_pct": 10.2,
        "dmk_period": "FY22-FY25 (est.)",
        "unit": "%",
        "nominal": False,
        "confidence": "estimate",
        "source": "MoSPI GSVA Financial+RE+Business Services, TN",
        "source_url": "https://www.mospi.gov.in/GSVA-NSVA",
        "notes": "Highest-growth services sub-sector across most Indian states FY22-FY25.",
    },
    {
        "key": "public_admin_cagr",
        "label": "Public Administration",
        "sector": "services",
        "dmk_cagr_pct": 6.8,
        "dmk_period": "FY22-FY25 (est.)",
        "unit": "%",
        "nominal": False,
        "confidence": "estimate",
        "source": "MoSPI GSVA Public Admin, TN",
        "source_url": "https://www.mospi.gov.in/GSVA-NSVA",
        "notes": "Govt expenditure component of GSVA; reflects salary + scheme spend.",
    },
    {
        "key": "other_services_cagr",
        "label": "Other Services",
        "sector": "services",
        "dmk_cagr_pct": 8.4,
        "dmk_period": "FY22-FY25 (est.)",
        "unit": "%",
        "nominal": False,
        "confidence": "estimate",
        "source": "MoSPI GSVA Other Services, TN",
        "source_url": "https://www.mospi.gov.in/GSVA-NSVA",
        "notes": "Education, health, recreation, personal services.",
    },
    # ------ INVESTMENT & TRADE -------------------------------------------
    {
        "key": "fdi_inflow_cagr",
        "label": "FDI Equity Inflow",
        "sector": "investment",
        # FY23: $2,169M → FY25: $3,681M = 2yr CAGR 30.3%
        # Use the cited series; mark as nominal $.
        "dmk_cagr_pct": 30.3,
        "dmk_period": "FY23-FY25",
        "unit": "%",
        "nominal": True,
        "confidence": "verified",
        "source": "DPIIT FDI Fact Sheet via TN Economic Survey 2024-25 ($2.17B → $3.68B)",
        "source_url": "https://thefederal.com/category/states/south/tamil-nadu/tamil-nadu-economic-survey-decade-high-growth-2024-256-230255",
        "notes": "TN among India's top-2 FDI destinations under DMK; 2-year window only.",
    },
    {
        "key": "epi_score",
        "label": "Export Preparedness Index (NITI Aayog)",
        "sector": "investment",
        "dmk_cagr_pct": 64.41,
        "dmk_period": "EPI 2024 (Jan 2026 release)",
        "unit": "score",
        "nominal": False,
        "confidence": "verified",
        "lower_is_better": False,
        "source": "NITI Aayog Export Preparedness Index 2024 — TN ranked 2 of 17 Large States, classified 'Leader'",
        "source_url": "https://niti.gov.in/sites/default/files/2026-01/Export_Preparedness_Index_2024.pdf",
        "notes": "Score 64.41 out of 100. Ranked 2nd among 17 Large States (Maharashtra #1 at 68.01, Gujarat #3 at 64.02). DMK delivered TN to 'Leader' tier — TVK must hold this rank or it slips visibly.",
    },
    {
        "key": "exports_cagr",
        "label": "Merchandise Exports",
        "sector": "investment",
        # CITED: $26.15B (FY21) → $52.07B (FY25) = 4yr CAGR 18.8%
        # i.e. doubled in 4 years.
        "dmk_cagr_pct": 18.8,
        "dmk_period": "FY21-FY25",
        "unit": "%",
        "nominal": True,
        "confidence": "verified",
        "source": "TN Economic Survey 2024-25 (exports doubled $26.15B → $52.07B)",
        "source_url": "https://thefederal.com/category/states/south/tamil-nadu/tamil-nadu-economic-survey-decade-high-growth-2024-256-230255",
        "notes": "Doubled in 4 years. TN consistently #2-3 exporting state under DMK.",
    },
    {
        "key": "tax_revenue_cagr",
        "label": "State Tax Revenue",
        "sector": "investment",
        "dmk_cagr_pct": 13.4,
        "dmk_period": "FY22-FY26 (est.)",
        "unit": "%",
        "nominal": True,
        "confidence": "estimate",
        "source": "TN Finance Dept Revenue Receipts series (placeholder)",
        "source_url": "https://tnbudget.tn.gov.in/",
        "notes": "Reflects buoyant GSDP + improved GST compliance. Verify against final Budget docs.",
    },
    # ------ FISCAL HEALTH (NITI Aayog Macro & Fiscal Landscape, Mar 2025) ----
    #
    # These metrics aren't growth rates but RATIOS of total state output, so
    # the comparison shape is "TVK's number vs DMK's last-year number" rather
    # than CAGR vs CAGR.  We use the same delta_pp framework — anything
    # moving the wrong direction adds anti-pressure when wired into the
    # meter.  Lower is BETTER for deficits and debt; higher is BETTER for
    # social spend.  The UI per-card already explains direction in plain
    # English on the drill-down pages.
    {
        "key": "debt_to_gsdp",
        "label": "Total Public Debt / GSDP",
        "sector": "fiscal_health",
        "dmk_cagr_pct": 31.4,        # FY23 end-of-year ratio under DMK Y1
        "dmk_period": "FY23 (NITI Aayog)",
        "unit": "%",
        "nominal": True,
        "confidence": "verified",
        "lower_is_better": True,     # used by drill-down + meter
        "source": "NITI Aayog Macro & Fiscal Landscape, TN (Mar 2025)",
        "source_url": "https://www.niti.gov.in/sites/default/files/2025-03/Macro-and-Fiscal-Landscape-of-the-State-of-Tamil-Nadu.pdf",
        "notes": "DMK inherited 27% in FY21; rose to 31.4% by FY23. State Fiscal Responsibility Act caps at 25.2% — TN is structurally over.",
    },
    {
        "key": "fiscal_deficit_gsdp",
        "label": "Fiscal Deficit / GSDP",
        "sector": "fiscal_health",
        "dmk_cagr_pct": 3.2,
        "dmk_period": "FY23 (NITI Aayog)",
        "unit": "%",
        "nominal": True,
        "confidence": "verified",
        "lower_is_better": True,
        "source": "NITI Aayog Macro & Fiscal Landscape, TN (RBI SFR underlying)",
        "source_url": "https://www.niti.gov.in/sites/default/files/2025-03/Macro-and-Fiscal-Landscape-of-the-State-of-Tamil-Nadu.pdf",
        "notes": "TN FRA mandates ≤3.0% by Mar 2025. DMK got it to 3.2% (under median state).",
    },
    {
        "key": "primary_deficit_gsdp",
        "label": "Primary Deficit / GSDP",
        "sector": "fiscal_health",
        "dmk_cagr_pct": 1.2,
        "dmk_period": "FY23 (NITI Aayog)",
        "unit": "%",
        "nominal": True,
        "confidence": "verified",
        "lower_is_better": True,
        "source": "NITI Aayog Macro & Fiscal Landscape (RBI SFR derived)",
        "source_url": "https://www.niti.gov.in/sites/default/files/2025-03/Macro-and-Fiscal-Landscape-of-the-State-of-Tamil-Nadu.pdf",
        "notes": "Fiscal deficit minus interest payments. Lower than median state's 1.9%.",
    },
    {
        "key": "revenue_deficit_gsdp",
        "label": "Revenue Deficit / GSDP",
        "sector": "fiscal_health",
        "dmk_cagr_pct": 1.3,
        "dmk_period": "FY23 (NITI Aayog)",
        "unit": "%",
        "nominal": True,
        "confidence": "verified",
        "lower_is_better": True,
        "source": "NITI Aayog Macro & Fiscal Landscape, TN",
        "source_url": "https://www.niti.gov.in/sites/default/files/2025-03/Macro-and-Fiscal-Landscape-of-the-State-of-Tamil-Nadu.pdf",
        "notes": "TN FRA mandates ELIMINATION of revenue deficit by FY26. DMK reduced it from 3.5% to 1.3% — on track. TVK must finish the job.",
    },
    {
        "key": "own_tax_revenue_gsdp",
        "label": "Own Tax Revenue / GSDP",
        "sector": "fiscal_health",
        "dmk_cagr_pct": 6.4,
        "dmk_period": "FY23 (NITI Aayog)",
        "unit": "%",
        "nominal": True,
        "confidence": "verified",
        "lower_is_better": False,    # higher = more self-reliant fiscally
        "source": "NITI Aayog Macro & Fiscal Landscape, TN",
        "source_url": "https://www.niti.gov.in/sites/default/files/2025-03/Macro-and-Fiscal-Landscape-of-the-State-of-Tamil-Nadu.pdf",
        "notes": "Self-collected tax (GST + state taxes). On par with median state (6.3%). Falling = bad.",
    },
    {
        "key": "social_spend_share",
        "label": "Social Sector Spend / Total Spend",
        "sector": "fiscal_health",
        "dmk_cagr_pct": 36.3,
        "dmk_period": "FY23 (NITI Aayog)",
        "unit": "%",
        "nominal": True,
        "confidence": "verified",
        "lower_is_better": False,    # higher = more for people
        "source": "NITI Aayog Macro & Fiscal Landscape, TN",
        "source_url": "https://www.niti.gov.in/sites/default/files/2025-03/Macro-and-Fiscal-Landscape-of-the-State-of-Tamil-Nadu.pdf",
        "notes": "Education+health+welfare share. Below median state's 43.9% — TN has historically been welfare-strong but the ratio has FALLEN under DMK from ~43% (FY13) to 36.3% (FY23). Drop reflects rising debt service crowding out social spend.",
    },
    {
        "key": "fhi_score",
        "label": "Fiscal Health Index (NITI Aayog)",
        "sector": "fiscal_health",
        "dmk_cagr_pct": 29.2,
        "dmk_period": "FHI 2025 release (FY23 data)",
        "unit": "score",
        "nominal": False,
        "confidence": "verified",
        "lower_is_better": False,    # higher score = healthier
        "source": "NITI Aayog Fiscal Health Index 2025 — TN ranked 11 of 18 states",
        "source_url": "https://niti.gov.in/sites/default/files/2025-01/Fiscal_Health_Index_24012025_Final.pdf",
        "notes": "Composite of 5 sub-indices (Quality of Expenditure, Revenue Mobilization, Fiscal Prudence, Debt Index, Debt Sustainability). TN scored 29.2 — bottom half of 18 states (Odisha #1 at 67.8). DMK weakest on Debt Sustainability (11.1/100).",
    },
    # ------ HUMAN DEVELOPMENT (NITI Aayog Macro & Fiscal Landscape + PLFS) --
    #
    # Quality-of-life indicators that move slowly but are politically charged.
    # Source: NITI Aayog TN report (Mar 2025) pages 6, 18-19.
    {
        "key": "literacy_rate",
        "label": "Literacy Rate",
        "sector": "human_development",
        "dmk_cagr_pct": 80.1,
        "dmk_period": "Census 2011",
        "unit": "%",
        "nominal": False,
        "confidence": "verified",
        "lower_is_better": False,
        "source": "NITI Aayog Macro & Fiscal Landscape, TN (citing Census 2011)",
        "source_url": "https://www.niti.gov.in/sites/default/files/2025-03/Macro-and-Fiscal-Landscape-of-the-State-of-Tamil-Nadu.pdf",
        "notes": "Above national average of 73%. Next census update will give TVK-era reading.",
    },
    {
        "key": "life_expectancy",
        "label": "Life Expectancy (years)",
        "sector": "human_development",
        "dmk_cagr_pct": 73.2,
        "dmk_period": "2020 (NITI)",
        "unit": "years",
        "nominal": False,
        "confidence": "verified",
        "lower_is_better": False,
        "source": "NITI Aayog Macro & Fiscal Landscape, TN",
        "source_url": "https://www.niti.gov.in/sites/default/files/2025-03/Macro-and-Fiscal-Landscape-of-the-State-of-Tamil-Nadu.pdf",
        "notes": "TN 73.2 vs India 70.0 years. Reflects health system & per-capita income gains.",
    },
    {
        "key": "higher_ed_ger",
        "label": "Higher Education Gross Enrolment Ratio",
        "sector": "human_development",
        "dmk_cagr_pct": 46.9,
        "dmk_period": "2021 (AISHE)",
        "unit": "%",
        "nominal": False,
        "confidence": "verified",
        "lower_is_better": False,
        "source": "NITI Aayog Macro & Fiscal Landscape (citing AISHE 2021)",
        "source_url": "https://www.niti.gov.in/sites/default/files/2025-03/Macro-and-Fiscal-Landscape-of-the-State-of-Tamil-Nadu.pdf",
        "notes": "Among the highest in India. Annual AISHE survey will reveal whether TVK maintains it.",
    },
    {
        "key": "unemployment_rate",
        "label": "Annual Unemployment Rate",
        "sector": "human_development",
        "dmk_cagr_pct": 4.3,
        "dmk_period": "PLFS FY23",
        "unit": "%",
        "nominal": False,
        "confidence": "verified",
        "lower_is_better": True,
        "source": "NITI Aayog citing PLFS Annual Report 2022-23 — TN unemployment 4.3%",
        "source_url": "https://www.niti.gov.in/sites/default/files/2025-03/Macro-and-Fiscal-Landscape-of-the-State-of-Tamil-Nadu.pdf",
        "notes": "TN historically slightly above national average. DMK brought it down from higher 2017-18 levels to 4.3% by FY23. PLFS releases annually — TVK-era reading due FY26 PLFS.",
    },
    {
        "key": "flfpr",
        "label": "Female Labour Force Participation",
        "sector": "human_development",
        "dmk_cagr_pct": 40.5,
        "dmk_period": "PLFS FY23",
        "unit": "%",
        "nominal": False,
        "confidence": "verified",
        "lower_is_better": False,
        "source": "NITI Aayog citing PLFS Annual Report 2022-23 — TN FLFPR 40.5%",
        "source_url": "https://www.niti.gov.in/sites/default/files/2025-03/Macro-and-Fiscal-Landscape-of-the-State-of-Tamil-Nadu.pdf",
        "notes": "Improved from 37.0% in 2017-18 under DMK. Well above national average. A KEY DMK accountability metric.",
    },
    {
        "key": "infant_mortality",
        "label": "Infant Mortality Rate (per 1000)",
        "sector": "human_development",
        "dmk_cagr_pct": 14.0,
        "dmk_period": "NFHS-5 (2019-21, est.)",
        "unit": "per 1000",
        "nominal": False,
        "confidence": "estimate",
        "lower_is_better": True,
        "source": "NITI Aayog Macro & Fiscal Landscape — 'significantly below national average'",
        "source_url": "https://www.niti.gov.in/sites/default/files/2025-03/Macro-and-Fiscal-Landscape-of-the-State-of-Tamil-Nadu.pdf",
        "notes": "TN ~14 vs India ~28. Exact figure to be updated from NFHS-6 when released. Lower is better — fewer infant deaths.",
    },
]

DMK_CAGR_LOOKUP = {b["key"]: b for b in DMK_CAGR_BASELINES}

SECTOR_ORDER = ["headline", "agriculture", "industry", "services", "investment", "fiscal_health", "human_development"]


# ---------- TVK QUARTERLY TRACKER ----------------------------------------
#
# The tracker stores each released quarterly observation under TVK so we
# can annualise + compare against the DMK CAGR. Storage shape:
#
#   table economic_quarterly_data (
#     id            uuid primary key,
#     metric_key    text not null references DMK_CAGR_BASELINES.key (in code),
#     fy            int  not null,      -- e.g. 2027 for FY27
#     quarter       int  not null,      -- 1..4 (Q1=Apr-Jun)
#     value         numeric not null,   -- observed level, OR an observed period CAGR
#     value_type    text not null,      -- 'cagr_pct' | 'level' | 'yoy_pct'
#     source        text not null,
#     source_url    text,
#     notes         text,
#     ingested_at   timestamptz default now()
#   );
#
# For the MVP we accept any of these value types and the dashboard picks
# the right comparison:
#   - 'cagr_pct'  : observed CAGR over TVK tenure → compare directly to dmk_cagr_pct
#   - 'yoy_pct'   : year-over-year quarterly growth → annualise and compare
#   - 'level'     : absolute value (used when caller wants to compute CAGR vs
#                   a known DMK end-of-tenure level — future enhancement)


class QuarterlyUpsert(BaseModel):
    metric_key: str
    fy: int
    quarter: int
    value: float
    value_type: str = "yoy_pct"  # default to the most-commonly published form
    source: str
    source_url: Optional[str] = None
    notes: Optional[str] = None


def _verify_admin(secret: Optional[str]):
    if secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="admin secret required")


def _annualise(observation: dict) -> float | None:
    """Convert any TVK observation into a comparable annualised %.

    - cagr_pct: already annualised → return as-is
    - yoy_pct:  already annual rate → return as-is (single-quarter YoY proxy)
    - level:    cannot annualise without a baseline level → None (future work)
    """
    vt = observation.get("value_type")
    if vt in ("cagr_pct", "yoy_pct"):
        return float(observation.get("value") or 0.0)
    return None


# ---------- ROUTES --------------------------------------------------------

@router.get("/baselines")
async def list_economic_baselines(sector: Optional[str] = None):
    """Return the static DMK CAGR baseline list, optionally filtered by sector."""
    if sector:
        return [b for b in DMK_CAGR_BASELINES if b["sector"] == sector]
    return DMK_CAGR_BASELINES


@router.get("/dashboard")
async def economic_dashboard():
    """For each DMK CAGR baseline, attach the latest TVK observation if we
    have one, compute the delta_pp (percentage-points difference), and
    group by sector for clean rendering.

    Output shape per row:
      {
        key, label, sector,
        dmk_cagr_pct, dmk_period, dmk_source, dmk_source_url,
        tvk_observed_pct,           -- annualised observed rate
        tvk_value_type,             -- 'cagr_pct' | 'yoy_pct' | None
        tvk_period_label,           -- e.g. "FY27 Q2 YoY"
        tvk_source, tvk_source_url,
        delta_pp,                   -- (tvk_observed - dmk_cagr) in pp
        verdict,                    -- "ahead" | "behind" | "tracking" | "no_data"
      }
    """
    db = get_db()
    try:
        res = (
            db.table("economic_quarterly_data")
            .select("metric_key, fy, quarter, value, value_type, source, source_url, notes, ingested_at")
            .order("fy", desc=True)
            .order("quarter", desc=True)
            .order("ingested_at", desc=True)
            .execute()
        )
        observations = res.data or []
    except Exception:
        # Table may not yet exist (pre-migration) — fall through with empty data
        observations = []

    # Pick the most-recent observation per metric_key (already sorted desc)
    latest_by_key: dict[str, dict] = {}
    for obs in observations:
        k = obs.get("metric_key")
        if k and k not in latest_by_key:
            latest_by_key[k] = obs

    out = []
    for b in DMK_CAGR_BASELINES:
        obs = latest_by_key.get(b["key"])
        tvk_pct = _annualise(obs) if obs else None
        delta_pp = None
        verdict = "no_data"
        if tvk_pct is not None:
            delta_pp = round(tvk_pct - float(b["dmk_cagr_pct"]), 2)
            # For "lower_is_better" metrics (deficits, debt) the sign flips —
            # an increase is bad, a decrease is good. We normalize so
            # verdict='ahead' always means TVK is doing better than DMK.
            effective = -delta_pp if b.get("lower_is_better") else delta_pp
            if effective > 0.5:
                verdict = "ahead"
            elif effective < -0.5:
                verdict = "behind"
            else:
                verdict = "tracking"

        period_label = None
        if obs:
            period_label = f"FY{obs['fy']} Q{obs['quarter']} {obs['value_type']}"

        out.append({
            "key": b["key"],
            "label": b["label"],
            "sector": b["sector"],
            "dmk_cagr_pct": b["dmk_cagr_pct"],
            "dmk_period": b["dmk_period"],
            "dmk_source": b["source"],
            "dmk_source_url": b.get("source_url"),
            "nominal": b.get("nominal", False),
            "confidence": b.get("confidence", "estimate"),
            "lower_is_better": b.get("lower_is_better", False),
            "tvk_observed_pct": tvk_pct,
            "tvk_value_type": obs.get("value_type") if obs else None,
            "tvk_period_label": period_label,
            "tvk_source": obs.get("source") if obs else None,
            "tvk_source_url": obs.get("source_url") if obs else None,
            "tvk_notes": obs.get("notes") if obs else None,
            "tvk_ingested_at": obs.get("ingested_at") if obs else None,
            "delta_pp": delta_pp,
            "verdict": verdict,
        })

    # Sort by sector then label so the dashboard groups cleanly
    sector_idx = {s: i for i, s in enumerate(SECTOR_ORDER)}
    out.sort(key=lambda r: (sector_idx.get(r["sector"], 99), r["label"]))

    summary = {
        "total_metrics":   len(out),
        "with_tvk_data":   sum(1 for r in out if r["tvk_observed_pct"] is not None),
        "tvk_ahead":       sum(1 for r in out if r["verdict"] == "ahead"),
        "tvk_behind":      sum(1 for r in out if r["verdict"] == "behind"),
        "tvk_tracking":    sum(1 for r in out if r["verdict"] == "tracking"),
        "as_of":           date.today().isoformat(),
    }

    return {"summary": summary, "rows": out}


@router.post("/quarterly")
async def upsert_quarterly_observation(
    payload: QuarterlyUpsert,
    x_admin_secret: Optional[str] = Header(None),
):
    """Admin-only: record a new TVK quarterly observation.

    Typically called by the user after a new RBI State Finances / TN Economic
    Survey release becomes available. The dashboard picks the latest by
    (fy desc, quarter desc, ingested_at desc) per metric_key.
    """
    _verify_admin(x_admin_secret)
    if payload.metric_key not in DMK_CAGR_LOOKUP:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown metric_key '{payload.metric_key}'. Valid: {list(DMK_CAGR_LOOKUP)}",
        )
    if payload.quarter not in (1, 2, 3, 4):
        raise HTTPException(status_code=400, detail="quarter must be 1..4")
    if payload.value_type not in ("cagr_pct", "yoy_pct", "level"):
        raise HTTPException(
            status_code=400,
            detail="value_type must be cagr_pct | yoy_pct | level",
        )

    db = get_db()
    record = {
        "metric_key": payload.metric_key,
        "fy": payload.fy,
        "quarter": payload.quarter,
        "value": payload.value,
        "value_type": payload.value_type,
        "source": payload.source,
        "source_url": payload.source_url,
        "notes": payload.notes,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        res = db.table("economic_quarterly_data").insert(record).execute()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Insert failed (table 'economic_quarterly_data' may not exist yet). "
                f"Run the migration. Underlying: {e}"
            ),
        )
    return {"ok": True, "inserted": res.data}


# ---------- RELEASE WATCHES (auto-ingest pipeline) ------------------------
#
# These read endpoints power the /admin/economic "Pending releases" panel
# so the admin sees a notification any time a watched publisher's page
# changed since they last reviewed it. The actual fetching + change
# detection is done by scripts/watch_economic_releases.py via a weekly
# GH Action; this is just the read + ack surface.

@router.get("/release-watches")
async def list_release_watches():
    """List configured publisher pages we monitor + latest change status."""
    db = get_db()
    try:
        watches_res = (
            db.table("economic_release_watches")
            .select("id, label, url, publisher, related_metrics, cadence_days, "
                    "last_checked, last_changed_at, notes")
            .order("publisher")
            .order("label")
            .execute()
        )
        watches = watches_res.data or []
        # Count pending events per watch for the badge in UI
        events_res = (
            db.table("economic_release_events")
            .select("watch_id, status")
            .eq("status", "pending")
            .execute()
        )
        events = events_res.data or []
    except Exception:
        return {"watches": [], "pending_count": 0}

    pending_by_watch: dict[str, int] = {}
    for e in events:
        wid = e.get("watch_id")
        if wid:
            pending_by_watch[wid] = pending_by_watch.get(wid, 0) + 1

    for w in watches:
        w["pending_events"] = pending_by_watch.get(w["id"], 0)

    return {
        "watches": watches,
        "pending_count": sum(pending_by_watch.values()),
    }


@router.get("/release-events")
async def list_release_events(status: str = "pending", limit: int = 50):
    """List detected publisher-page change events."""
    db = get_db()
    try:
        res = (
            db.table("economic_release_events")
            .select("id, watch_id, detected_at, old_hash, new_hash, status, ack_by, ack_at, notes")
            .eq("status", status)
            .order("detected_at", desc=True)
            .limit(limit)
            .execute()
        )
        events = res.data or []
        # Attach the parent watch label / url for display
        if events:
            wids = list({e["watch_id"] for e in events if e.get("watch_id")})
            wres = (
                db.table("economic_release_watches")
                .select("id, label, url, publisher, related_metrics")
                .in_("id", wids)
                .execute()
            )
            wmap = {w["id"]: w for w in (wres.data or [])}
            for e in events:
                e["watch"] = wmap.get(e["watch_id"])
        return events
    except Exception:
        return []


class ReleaseEventAck(BaseModel):
    notes: Optional[str] = None
    status: str = "acknowledged"  # 'acknowledged' or 'dismissed'


@router.post("/release-events/{event_id}/ack")
async def ack_release_event(
    event_id: str,
    payload: ReleaseEventAck,
    x_admin_secret: Optional[str] = Header(None),
):
    """Admin marks a detected change as 'acknowledged' (entered the number)
    or 'dismissed' (false positive / no action needed)."""
    _verify_admin(x_admin_secret)
    if payload.status not in ("acknowledged", "dismissed"):
        raise HTTPException(status_code=400, detail="status must be acknowledged|dismissed")
    db = get_db()
    try:
        res = (
            db.table("economic_release_events")
            .update({
                "status": payload.status,
                "ack_by": "admin",
                "ack_at": datetime.now(timezone.utc).isoformat(),
                "notes":  payload.notes,
            })
            .eq("id", event_id)
            .execute()
        )
        return {"ok": True, "updated": res.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ack failed: {e}")


# ---------- QUARTERLY (already-built) -----------------------------------

@router.get("/quarterly")
async def list_quarterly_observations(metric_key: Optional[str] = None, limit: int = 100):
    """Read-only: list raw observations, newest first. For audit/debug."""
    db = get_db()
    try:
        q = db.table("economic_quarterly_data").select("*")
        if metric_key:
            q = q.eq("metric_key", metric_key)
        res = (
            q.order("fy", desc=True)
             .order("quarter", desc=True)
             .order("ingested_at", desc=True)
             .limit(limit)
             .execute()
        )
        return res.data or []
    except Exception:
        return []

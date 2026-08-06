# OSIRIS Fork — Resource Intelligence Data Sourcing

This fork adds a **resource-intelligence layer** on top of upstream OSIRIS:
mining companies, the AI memory (RAM/HBM) supply chain, macro market signals,
and utility usage. This document explains what each piece is, where the data
comes from, and how to extend it.

## 1. Static seed datasets (in-repo)

| File | Contents | API route | Map layer |
|---|---|---|---|
| `src/data/mining-companies.json` | ~70 major producers of copper, gold, silver, PGMs, rare earths and AI-chip-critical specialty materials (tin, tungsten, gallium/germanium, high-purity quartz), with flagship mine/plant coordinates | `/api/mining/companies` | RESOURCE → Mining Companies |
| `src/data/ram-companies.json` | ~30 memory-ecosystem companies: the 3 DRAM/HBM makers (Samsung, SK Hynix, Micron ≈95% of the market) plus CXMT/Nanya/Winbond, NAND makers, controller/IP vendors, module makers, OSAT/packaging and HBM-critical equipment | `/api/ram/companies` | RESOURCE → Memory / RAM Fabs |

Honest count note: there are not 50 distinct major companies in every one of
these categories in the real world — silver has ~10 legitimate majors, DRAM
has 3. The seed lists include all the real major players rather than padding
with obscure juniors.

**Filters:** both routes accept `?category=`, `?country=`, and (mining only)
`?commodity=`. Example: `/api/mining/companies?category=copper&country=chile`.

**Coordinates are approximate (±0.1°)** — good enough for global map pins,
not for engineering use. To extend, append to the `companies` array; each
company needs at least one entry in `sites` to appear on the map.

## 2. Live feeds

### Macro — `/api/macro` (works without any key)
- **VIX, US Treasury yields** (13-week, 5Y, 10Y, 30Y): Yahoo Finance chart
  API — the same keyless pattern upstream `/api/markets` already uses.
- **Effective Fed funds rate (DFF)**: FRED's public `fredgraph.csv` endpoint,
  no key required. Setting `FRED_API_KEY` (free:
  https://fred.stlouisfed.org/docs/api/api_key.html) upgrades this to the
  official JSON API and unlocks any other FRED series (e.g. `T10Y2Y` spread,
  `DGS10`, `FEDFUNDS`).
- Also computes a 10Y-13W curve-inversion flag.
- Commodity futures (gold `GC=F`, silver `SI=F`, **copper `HG=F`**, nat gas
  `NG=F`) and crypto were already live in upstream `/api/markets` — no
  duplication here.

### Utilities — `/api/utilities` (requires free EIA key)
- **US Lower-48 hourly electricity demand** and **weekly natural gas storage**
  from the EIA Open Data v2 API. Register (free, instant):
  https://www.eia.gov/opendata/register.php → set `EIA_API_KEY`.
- Without the key the route returns `{ configured: false }` with instructions
  so the UI can degrade gracefully.
- **Water**: there is no national live water-usage API. Closest options:
  USGS Water Services (https://waterservices.usgs.gov/) for per-site
  instantaneous streamflow/levels, and USGS 5-year water-use census data.
  Wire per-site if/when a specific basin matters (e.g. fab or mine water risk).

### News (already in upstream)
- `/api/news`, `/api/gdelt`, `/api/live-news` cover global + resource news.
  For mining-specific filtering, the GDELT DOC API supports theme queries
  (e.g. `theme:ECON_MINING`) — extend `/api/gdelt` rather than adding a new
  pipeline.

## 3. Map integration (how the layers work)

Follows the standard OSIRIS layer pattern:
1. `page.tsx` — `mining` / `ram_fabs` keys in `activeLayers`; data fetched
   once on first toggle via `layerFetchedRef` → stored as
   `data.mining_companies` / `data.ram_companies` (flattened site points).
2. `LayerPanel.tsx` — RESOURCE group (Mountain icon) with the two toggles.
3. `OsirisMap.tsx` — `mining-sites` / `ram-sites` GeoJSON sources, glow/dot/
   label layers colored by category, click popups with company details,
   `setVis` visibility toggles.

Mining pin colors: copper coral, gold amber, silver grey, PGM teal,
rare-earth purple, specialty orange. RAM pin colors by ecosystem role
(DRAM/HBM blue, NAND green, controllers yellow, modules grey, packaging pink,
equipment violet).

## 4. Suggested next steps
- Overlay risk intersection (earthquakes/fires/conflicts near mine sites) —
  the pattern already exists in `/api/scm-suppliers`.
- A "Resource Intel" HUD panel (like `ScmPanel`) summarizing macro + top
  mover mining tickers via `/api/macro` + `/api/markets`.
- OpenRouter evaluation calls against the combined feeds.

# Reproducing CRIA

**CRIA — Colorado River Integrated Assessment.** How to run the tool, verify its
computations, and understand its data pipeline, sources, and assumptions.

Python 3.11. No system/GDAL libraries are required — every dependency installs from a
wheel (`requirements.txt`).

---

## 1. Run the app

**Option A — Docker (matches the deployed Hugging Face Space exactly):**

```bash
docker build -t cria .
docker run -p 7860:7860 cria
# open http://localhost:7860
```

**Option B — Local Python:**

```bash
pip install -r requirements.txt
python app.py                 # dev server → http://localhost:8050
# production entry point:
# gunicorn app:server --bind 0.0.0.0:7860 --workers 2 --timeout 120
```

---

## 2. Verify the computations

```bash
pip install pytest
pytest -q
```

The suite (`tests/test_app.py`, `tests/test_integrity.py`) is an integrity + consistency
check, not decoration. It verifies, among ~27 tests:

- **Every view renders** and every sidebar route maps to a real layout (no dead links).
- **Statistical parity:** the scenario elasticity fit is cross-checked against
  `statsmodels` (`test_scenario_matches_statsmodels`), and confidence-interval ordering
  is enforced.
- **Physical sanity:** the water balance closes; a warmer **and** drier climate must
  lower basin runoff; Budyko coordinates stay physically valid.
- **Data integrity:** loaders return non-empty tables with the expected schema, VIC
  annual coverage spans the record, ≥ 100 SNOTEL stations load, and the governance
  allocations sum to the compact totals (16.5 / 7.5 MAF).

---

## 3. Data sources, resolution & cadence

All sources are documented in-app under **Methods & Data** and **References & Validation**:

| Source | What | Resolution |
|---|---|---|
| VIC 5.0 (PRISM-calibrated) | hydrologic reanalysis | ~6 km (1/16°), 224×176 grid, **WY 1984–2024** |
| NASA GRACE / GRACE-FO | terrestrial water storage | ~300 km (larger basins only) |
| NASA SMAP L4 | root-zone soil moisture | ~9 km, daily |
| NRCS SNOTEL (103 stations) | snow water equivalent | point stations |
| USBR policy | Lake Mead shortage tiers, capacities | — |

The app reads a compact **Parquet cache** (`data/cache/*`, ~200–400 MB) once into memory
(`functools.lru_cache`); the large spatial grids are left uncached to protect memory.
The cache is built **offline** from the raw NetCDF (~58 GB) by aggregating, quality-
checking and gridding into 11 basin tables + 19 spatial-grid tables. *(The offline
prep scripts are not shipped with the runtime, to keep the deployment build fast; the
committed cache is the reproducible input the tests and app run against.)*

**Cadence:** CRIA is a **retrospective diagnostic + scenario tool** over the fixed
WY 1984–2024 record — **not a real-time operational feed.** It complements, and does not
replace, CBRFC / the USBR 24-Month Study / CRSS.

---

## 4. Validation (independent, out-of-sample)

The VIC reanalysis is validated against observations it **never saw during calibration**:

- **SMAP** root-zone soil moisture — R² 0.71–0.81
- **GRACE** terrestrial water storage — R² 0.66–0.86
- Upper-Basin **streamflow — NSE ≈ 0.96**

Every published result is shown **beside the tool's own value**, with an honest verdict,
on the **References & Validation** page.

---

## 5. Key methods & assumptions (all stated in-app)

- **Scenario engine:** log-linear hydrologic elasticity `ln(Q) = a + b·ln(P) + c·T` per
  basin, fitted on WY 1984–2024; 95% bounds via the OLS covariance matrix propagated
  through the delta method (Student-t, n−3 df).
- **Trends:** Mann–Kendall + Sen's slope (distribution-free), reproduced by a
  2000-iteration bootstrap.
- **Stationarity is assumed** for projections — the historical P–T–Q relationship is
  taken to hold forward. This is weakest in an aridifying basin, and is disclosed as such.
- **"Projections to 2100"** is a **single downscaled VIC realization — illustrative, not
  a multi-model ensemble** (labeled in-app). For ensemble ranges see the CMIP tab.
- The **GRACE − VIC residual** conflates groundwater **+** surface-reservoir change; it is
  not claimed as pure groundwater.

---

*Data: NASA GRACE/GRACE-FO, SMAP L4, NRCS SNOTEL; VIC 5.0 PRISM-calibrated reanalysis
(Wang et al. 2026, Scientific Reports 16:15890). Built at the Vivoni Hydrologic Systems
Lab, Arizona State University · NASA Applied Sciences Award 80NSSC22K0925.*

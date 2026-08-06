---
title: Georgian Financials Dashboard
emoji: 📊
colorFrom: blue
colorTo: indigo
sdk: streamlit
sdk_version: 1.56.0
python_version: "3.12"
app_file: app.py
pinned: false
short_description: Browse Georgian companies' IS / BS / Ratios, compare, screen
license: mit
---

# Georgian Financials Dashboard

Browse financial statements (Income Statement, Balance Sheet, Ratios) for ~9,000 Georgian companies (FY 2017–2024), with comparison, sector aggregation, and screening features.

Data is sourced from publicly-reported filings on [reportal.ge](https://reportal.ge) and rebuilt into a single SQLite database with unit-normalization, restated comparatives, and IFRS 16 lease reclassification.

## Modes

- **Single Company** — full IS / BS / Ratios with tie-out checks, sense-check ratios, Revenue+margins chart, and an IFRS 16 lease-reversal toggle.
- **Compare** — pick multiple companies + one year, see line items side-by-side.
- **Sector View** — pick a basket of companies, see aggregate Revenue / EBITDA / Net Profit across years as a chart.
- **Screener** — filter all companies by line-item size, growth, or ratio criteria with AND/OR logic.

## Tech

Streamlit · Pandas · Plotly · SQLite. Data prep pipeline in `scripts/rebuild_db.py` (raw Excel exports not deployed with the app).

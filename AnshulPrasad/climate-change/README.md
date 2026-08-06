---
title: Climate Change Dashboard
emoji: 🌍
colorFrom: green
colorTo: red
sdk: docker
app_port: 7860
---

# Climate Change Dashboard

Interactive Django dashboard for exploring climate signals across:
- Forest cover, gain, and loss (Google Earth Engine Hansen dataset)
- Temperature trends (global/country/state/city)
- CO2 trends (global concentration and country emissions)

The web UI is served by Django, while most graphs are pre-generated from notebooks and served from the `output/` folder.

## What This Repository Contains

- `app/`: Django app with dashboard template and API endpoints.
- `config/`: Django project config (`settings.py`, `urls.py`, `wsgi.py`).
- `notebooks/`: Analysis notebooks used to generate charts and HTML map artifacts.
- `src/`: Reusable utilities for Earth Engine initialization and forest-loss plotting.
- `dataset/`: Raw climate datasets used by notebooks (large and commonly local-only).
- `output/`: Generated `.png`/`.html` assets displayed in the dashboard.
- `Dockerfile`: Production container entrypoint (Gunicorn on port `7860`).
- `.github/workflows/`: Sync and keepalive workflows for Hugging Face Spaces.
- `.gitattributes`: Routes `output/**` and `.html` artifacts through Git LFS.

## Dashboard Features

- Forest tab:
  - Interactive Leaflet map with draw tools.
  - GEE raster overlays: `treecover`, `loss`, `lossyear`, `gain`.
  - ROI-based forest statistics and yearly loss chart.
- Temperature tab:
  - Loads pre-rendered graph images from `output/*_temp_graph`.
- Emissions tab:
  - Loads global CO2 concentration graphs and country CO2 emission graphs from `output/`.
- About tab:
  - Lists data sources and high-level project scope.

## Runtime Architecture

1. Browser loads `/` and renders `app/templates/dashboard/index.html`.
2. Frontend calls:
   - `GET /api/forest-tiles/` for GEE map tile URLs.
   - `POST /api/forest-stats/` for ROI/year-range forest stats.
   - `GET /api/graphs/` for graph file inventories.
3. Django serves media from `output/` via `/output/...`.

If Earth Engine is not configured, forest APIs return `503` and temperature/emissions tabs still work with existing assets.

## Local Development

### Prerequisites

- Python `3.12` recommended for local development.
- A Google Earth Engine project/service account if you need Forest APIs.

### Setup

```bash
cd /home/anshul/PycharmProjects/climate-change
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:7860
```

Open: `http://127.0.0.1:7860/`

### Configure Google Earth Engine

The app expects a JSON service-account credential string in `GEE_SERVICE_KEY`.

```bash
export GEE_SERVICE_KEY="$(cat /path/to/service-account.json)"
```

Without this variable, forest tile/stat endpoints may fail depending on local Earth Engine auth state.

## Docker

```bash
cd /home/anshul/PycharmProjects/climate-change
docker build -t climate-change-dashboard .
docker run --rm -p 7860:7860 \
  -e GEE_SERVICE_KEY="$(cat /path/to/service-account.json)" \
  climate-change-dashboard
```

Container startup runs:
1. `python manage.py migrate`
2. `gunicorn config.wsgi:application --bind 0.0.0.0:7860`

## API Reference

### `GET /api/forest-tiles/`

Query param:
- `layers` (comma-separated): `treecover,loss,gain,lossyear`

Returns tile URLs for selected GEE layers.

### `POST /api/forest-stats/`

JSON body:
```json
{
  "start_year": 2010,
  "end_year": 2015,
  "geojson": null
}
```

`geojson` can be a Feature, FeatureCollection, or list of features from the map drawing tool.

Response includes:
- `forest_area_ha`
- `loss_area_ha`
- `gain_area_ha`
- `yearly_loss`
- `chart_b64` (base64 PNG)

### `GET /api/graphs/`

Returns discovered graph files from:
- `output/global_temp_graph`
- `output/countries_temp_graph`
- `output/states_temp_graph`
- `output/cities_temp_graph`
- `output/major_cities_temp_graph`
- `output/global_co2_concentration_graph`
- `output/countries_co2_emission_graph`
- root `output/*.html`

## Notebooks and Data Generation

- `notebooks/main.ipynb`:
  - Temperature analysis and map HTML generation.
- `notebooks/carbon_dioxide.ipynb`:
  - CO2 analysis and country/global emission plots.
- `notebooks/forest_loss_analysis.ipynb`:
  - Forest-loss exploration with Earth Engine and geemap.
- `notebooks/initial.ipynb`:
  - ERA5 exploratory notebook.

Generated assets are expected under `output/` and consumed directly by the dashboard.

## Deployment and Automation

- `.github/workflows/main.yml`: syncs `main` to Hugging Face Space `AnshulPrasad/climate-change`.
- `.github/workflows/space-keepalive.yml`: pings the Space every 12 hours.
- `.github/workflows/check.yml`: warns on large files in pull requests.

## Current Caveats

- Dependency manifests differ:
  - `pyproject.toml` pins Django `6.0.3` and Python `>=3.12`.
  - `requirements.txt` pins Django `<5.0` and is used by `Dockerfile`.
- `notebooks/main.ipynb` currently references `./dataset/*.csv` paths, while this repository stores temperature CSVs in `dataset/temperature: Berkeley Earth/`.
- Security defaults are development-oriented (`DEBUG=True`, wildcard `ALLOWED_HOSTS`, placeholder `SECRET_KEY`).
- Test suite currently has no real tests (`manage.py test` finds 0 tests).

## Quick Verification

```bash
cd /home/anshul/PycharmProjects/climate-change
.venv/bin/python manage.py check
.venv/bin/python manage.py test
```

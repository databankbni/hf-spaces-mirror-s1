# CRB DST — Setup Guide

## 1. Install Python dependencies

```bash
cd crb-dst/
conda create -n crb-dst python=3.11
conda activate crb-dst
pip install -r requirements.txt
```

## 2. Run data preprocessing (ONE TIME — local only)

```bash
cd preprocessing/

# Step 1: VIC basin aggregation (~10-20 min)
# Raw NetCDF is read from the repo's raw_data/ by default.
# (Optional) point elsewhere:  export CRB_DATA_ROOT="../raw_data"
python 01_basin_aggregation.py

# Step 2: SNOTEL + GRACE + SMAP (~2-5 min)
python 02_snotel_grace_cache.py
```

Outputs saved to `data/cache/` (~200-400 MB total).

## 3. Run the app locally

```bash
cd crb-dst/
python app.py
# Open: http://localhost:8050
```

## 4. Deploy to HuggingFace Spaces (FREE)

### 4a. Install git-lfs (required for parquet files >10 MB)
```bash
# macOS
brew install git-lfs
git lfs install
```

### 4b. Create a new Space
1. Go to https://huggingface.co/spaces
2. Click **Create new Space**
3. Choose **Docker** as the SDK (NOT Gradio/Streamlit)
4. Set visibility to Public (for free tier)
5. Note your Space URL: `huggingface.co/spaces/YOUR_USERNAME/crb-dst`

### 4c. Push the repo (NO raw NetCDF data — parquets only)
```bash
cd crb-dst/

git init
git lfs track "*.parquet"    # track large parquets via LFS
git add .gitattributes

git add app.py requirements.txt Dockerfile README.md
git add assets/ modules/ utils/
git add data/cache/*.parquet
git add data/cache/spatial/*.parquet   # if spatial parquets exist

git commit -m "CRB DST initial deploy"

git remote add origin https://huggingface.co/spaces/YOUR_USERNAME/crb-dst
git push origin main
```

HuggingFace will auto-build the Docker container. Build takes ~5 min.

Your app will be live at:
`https://huggingface.co/spaces/YOUR_USERNAME/crb-dst`

### 4d. Update after changes
```bash
git add -A
git commit -m "update"
git push origin main
# HuggingFace rebuilds automatically
```

## Project Structure

```
crb-dst/
├── app.py                        ← Main Dash app + routing
├── requirements.txt
├── assets/
│   ├── style.css                 ← Same theme as CRB-WRDST
│   └── img/                      ← NASA, ASU, CAP logos
├── modules/
│   ├── home.py                   ← Home / Executive Summary
│   ├── snowpack.py               ← Module 1: Snowpack & Runoff
│   ├── watbal.py                 ← Module 2: Water Balance
│   ├── tws.py                    ← Module 3: GRACE + SMAP
│   ├── drought.py                ← Module 4: Drought & Risk
│   ├── future.py                 ← Module 5: Future Scenarios
│   ├── spatial.py                ← Module 6: Spatial Maps
│   └── methods.py                ← Methods & Data Citations
├── utils/
│   ├── data_loader.py            ← Centralised data access
│   └── components.py             ← Shared UI components
├── preprocessing/
│   ├── 01_basin_aggregation.py   ← VIC NetCDF → parquet
│   └── 02_snotel_grace_cache.py  ← SNOTEL + GRACE + SMAP
└── data/
    └── cache/                    ← Pre-processed parquet files
        ├── vic_annual_basin.parquet
        ├── vic_monthly_basin.parquet
        ├── vic_future_basin.parquet
        ├── snotel_annual.parquet
        ├── snotel_monthly.parquet
        ├── grace_basin.parquet
        ├── smap_basin.parquet
        └── spatial/
            ├── spatial_OUT_PREC.parquet
            ├── spatial_OUT_RUNOFF.parquet
            └── ...
```

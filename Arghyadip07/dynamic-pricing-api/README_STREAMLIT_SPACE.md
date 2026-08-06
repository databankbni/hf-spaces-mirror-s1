---
title: Dynamic Pricing AI Dashboard
emoji: 📈
colorFrom: indigo
colorTo: blue
sdk: streamlit
app_file: streamlit_app.py
pinned: false
---

# Dynamic Pricing AI Dashboard

This is the Streamlit front end for the Dynamic Pricing AI project.

## What it does

- Lets you enter market context for a product
- Calls the FastAPI backend for optimal pricing
- Shows elasticity curves and RL recommendations
- Monitors the autonomous pricing agent

## Deploying on Hugging Face Spaces

Create a new Space and use this repo layout or copy these files into a dashboard-only repository:

- `streamlit_app.py`
- `apps/dashboard/streamlit_app.py`
- `src/core/settings.py`
- `requirements.txt`

Set the Space metadata to:

```yaml
sdk: streamlit
app_file: streamlit_app.py
```

## Backend requirement

The dashboard expects the FastAPI backend to be reachable. Set:

```bash
DASHBOARD_API_URL=https://your-backend-url
```

If you deploy only the UI, point it at your running API server.

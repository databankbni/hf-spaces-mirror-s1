---
title: The Beast
emoji: 🐕
colorFrom: green
colorTo: blue
sdk: docker
app_port: 8080
pinned: false
license: mit
short_description: MLB Monte Carlo game simulator with betting edges
---

# The Beast — MLB Monte Carlo Predictor

A Monte Carlo MLB game simulator. Player rates (built from Statcast) drive a
24-state Markov simulation of each plate appearance; thousands of simulated
games aggregate into win probability, projected score, run-distribution
histograms, and betting edges.

Implementation of `SPEC.md`, following spec-driven development.

## Architecture

```
data (Statcast/MLB API) → matchup (Bayesian Log5 + DNA) → simulator (Monte
Carlo) → betting (Kelly edges)
```

- **Library** (`thebeast/`) — the engine, usable directly in Python.
- **CLI** (`thebeast …`) — `simulate`, `bet`, `fetch`, `run`.
- **API** (`thebeast.api.main:app`) — FastAPI under `/api/*`.
- **UI** (`web/`) — SvelteKit SPA, co-served by the API.

## Run the UI locally

The API serves both the JSON endpoints and the compiled SPA on one port.

```bash
# 1. build the frontend bundle (needs Node)
cd web && npm install && npm run build && cd ..

# 2. point the API at a populated DB and serve
THEBEAST_DB_PATH=local_data/thebeast.db \
  uv run uvicorn thebeast.api.main:app --port 8080
# open http://localhost:8080
```

During frontend development, run the API on :8000 and `npm run dev` in `web/`
(Vite proxies `/api` → :8000).

## Run with Docker (same image HF Spaces builds)

```bash
cp local_data/thebeast.db data/thebeast.db   # bundle real data (optional)
docker build -t thebeast .
docker run -p 8080:8080 thebeast
# open http://localhost:8080
```

Without a bundled DB the simulator falls back to league-average synthetic
players, so the app still runs (every matchup ≈ 50/50).

## Data

`data/thebeast.db` is a prebuilt SQLite DB of statlines + schedules. Rebuild it
with `scripts/calibration_run.py` (ingests Statcast) or the `thebeast fetch`
CLI.

## Deploy to Hugging Face Spaces

`.github/workflows/deploy-hf.yml` mirrors `main` to a HF Docker Space on every
push. One-time setup:

1. Create a write token at <https://huggingface.co/settings/tokens>.
2. In the GitHub repo → **Settings → Secrets and variables → Actions**:
   - Secret **`HF_TOKEN`** = the write token
   - Variable **`HF_USERNAME`** = your HF username/org
   - Variable **`HF_SPACE`** = the Space name (e.g. `thebeast`)
3. Create a **Docker** Space at <https://huggingface.co/new-space> named
   `HF_USERNAME/HF_SPACE` (or let the first push create it if your token allows).
4. Push to `main` (or run the workflow manually). HF reads this README's
   frontmatter (`sdk: docker`, `app_port: 8080`), builds the Dockerfile, and
   serves the app at `https://huggingface.co/spaces/HF_USERNAME/HF_SPACE`.

Until `HF_TOKEN` is set the workflow no-ops, so it never fails the build.

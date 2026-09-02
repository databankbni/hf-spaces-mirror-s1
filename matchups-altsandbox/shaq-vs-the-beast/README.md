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

# 2. point the API at the bundled DB and serve
THEBEAST_DB_PATH=data/thebeast.db \
  uvicorn thebeast.api.main:app --port 8080
# open http://localhost:8080
```

During frontend development, run the API on :8000 and `npm run dev` in `web/`
(Vite proxies `/api` → :8000).

## Run with Docker (same image HF Spaces builds)

```bash
docker build -t thebeast .   # data/thebeast.db is bundled into the image
docker run -p 8080:8080 thebeast
# open http://localhost:8080
```

Without a bundled DB the simulator falls back to league-average synthetic
players, so the app still runs (every matchup ≈ 50/50).

## Data

`data/thebeast.db` is a prebuilt SQLite DB of statlines + schedules. Rebuild it
with `scripts/calibration_run.py` (ingests Statcast) or the `thebeast fetch`
CLI.

## Player props

**PrizePicks is the only prop source.** The Best bets board prices every prop it
serves against the per-player distributions the simulator produces. The NFL test
page browses their NFL board, unmapped and unpriced, because there is no NFL
simulator to compare anything against.

| Variable | Default | Effect |
| --- | --- | --- |
| `PRIZEPICKS_INCLUDE_SPECIALS` | unset | Include demons, goblins and promos on the MLB board. Dropped by default because they move the line without saying what the leg now pays — and a goblin priced at the standard break-even reads as free money. |

**PrizePicks posts no odds.** It is DFS pick'em: a projection is a line and a
side, and the payout lives on the slip rather than the pick. So the "needs"
percentage on every card is the break-even a 2-pick power play requires —
`(1/3)^(1/2)` = **57.7%** — applied to both sides, since they charge the same
for MORE and LESS. That is an assumption, it is stated on the board and on every
probe, and it is the single number on the page that isn't a measurement.

It is not a documented API either — it is the endpoint their own app calls, so
every field name the parser reads is defensive. Three probes report what
actually arrived rather than what was hoped for:

- `GET /api/props-probe` — MLB: reachability, the market vocabulary the feed
  carries, and where every prop that didn't become a card was lost.
- `GET /api/nfl/props/probe` — the same for NFL.
- `GET /api/props-probe/leagues` — PrizePicks' league list. The parser asks for
  ids by name and only falls back to a constant, because a stale league id looks
  exactly like an empty slate.

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

---
title: Stratelm GUI
emoji: 🏎️
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

<!-- The YAML block above configures the Hugging Face Space (Docker SDK, single
     container on port 7860 built from the root Dockerfile). See
     .github/workflows/deploy_hf.yml for the auto-deploy setup. -->

# Stratelm-GUI

Telemetry + strategy dashboard (FastAPI backend, React/Vite frontend) for the
SEM 2027 Urban Concept H2 digital twin.

## One repo

The dashboard (`Stratelm-GUI/`) and the physics package (`digital_twin/`)
both live in this single repo — there is no separate clone/sibling-folder
step needed. `digital_twin` has its own `pyproject.toml` at the project root
and is installed editable so `import digital_twin` resolves from anywhere.

## Prerequisites
- Python 3.10+
- Node 20+

## Setup

From the project root:

```
pip install -e .
pip install -r Stratelm-GUI/backend/requirements.txt
```

Frontend:

```
cd Stratelm-GUI/frontend
npm install
```

## Run (two terminals)

**Backend** — from the project root:
```
cd Stratelm-GUI/backend
python -m uvicorn main:app --reload --port 8000
```
Confirm with `curl http://localhost:8000/api/health` → should show
`"digital_twin_loaded": true`. If it shows `false`, the editable install
above didn't resolve — re-run `pip install -e .` from the project root.

**Frontend** — separate terminal:
```
cd Stratelm-GUI/frontend
npm run dev
```

Open the URL Vite prints (typically http://localhost:5173).

## Notes

- First run auto-seeds `data/vehicles.json`, `data/tracks.json`,
  `data/attempts.json` from the original SEM 2027 / Lusail defaults.
- Live Telemetry connects to `broker.hivemq.com` (no credentials needed) — it
  shows OFFLINE/DISCONNECTED until a real or simulated publisher is on the
  same topics. Press **Start Simulator** in that tab to publish synthetic
  car+GPS data and watch it go LIVE — this is expected behavior, not a bug.
- GA/PSO/CMA-ES optimizer runs take tens of minutes (real physics search) —
  the Sandbox tab runs them as background jobs so the UI stays responsive.

## Troubleshooting: backend "hangs" / dashboard never loads data

If `/api/vehicles` (or any endpoint) hangs forever with no response and the
uvicorn terminal never logs the request at all, it's almost always a
leftover Python process from an earlier run still squatting on port 8000 —
not an actual code bug. Check and clear it before anything else:

```
netstat -ano | findstr :8000
taskkill /F /PID <pid>
```

Then restart the backend. `Test-NetConnection -ComputerName 127.0.0.1 -Port
8000` succeeding while HTTP requests still hang is a strong signal for
exactly this — the TCP handshake completes against a wedged/orphaned
listener, but nothing ever answers.

## Docker

`docker-compose.yml` / `Dockerfile.backend` / `prepare_docker_context.ps1`
still assume the old two-repo layout (staging `digital_twin` from a sibling
checkout) and have **not** been updated for this single-repo layout — treat
the Docker path as stale until it's revisited. Use the manual setup above for
now.

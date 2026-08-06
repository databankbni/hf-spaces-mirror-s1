---
title: Robotaxi SUMO Backend
emoji: 🚕
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
---

# Robotaxi SUMO Backend

Docker Hugging Face Space for the robotaxis-in-berlin prototype.

This backend serves the current SUMO/TraCI robotaxi dispatch runtime:

- installs SUMO inside the container
- exposes a FastAPI service
- serves the current `18:00-19:00` Charlottenburg, Moabit, and Tiergarten scenario bundle
- streams the packaged public replay cache (1 frame per sim-second) for fast user runs
- streams SUMO frames over WebSocket
- runs the robotaxi dispatch controller against MATSim person-demand requests
- keeps legacy SUMO-trip replacement mode available for comparison/debugging

## Endpoints

- `GET /health`
- `GET /sumo/version`
- `GET /sumo/charlottenburg-moabit-tiergarten/summary`
- `GET /sumo/charlottenburg-moabit-tiergarten/network`
- `GET /sumo/charlottenburg-moabit-tiergarten/validate`
- `WS /ws/sumo/charlottenburg-moabit-tiergarten`
- `WS /ws/sumo/charlottenburg-moabit-tiergarten/playback?speed=1000&demand=matsim&engine=taxi&detail=public&cache=auto`

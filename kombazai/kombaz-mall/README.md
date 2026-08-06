---
title: KOMBAZ Mars 2045
emoji: 🚀
colorFrom: blue
colorTo: gray
sdk: docker
app_file: app.py
pinned: false
---

# 🚀 KOMBAZ.ME — Mars 2045

Interactive 3D space monitoring system with real-time data integration.

## Features

- **🌍 3D Solar System** — Seven planets, 20,000 stars, realistic physics
- **🔴 Mars & Earth** — Detailed planetary visualization
- **📡 Voyager Live** — Real-time distance from Earth (calculated)
- **🚀 SpaceX Launches** — Next 5 upcoming missions
- **💰 Portfolio Tracking** — Investment monitoring
- **♿ Accessibility** — Full WCAG 2.1 AA compliance
- **📱 Mobile Responsive** — Works on all devices
- **⚡ Web Worker** — Voyager calculations off main thread
- **🎮 InstancedMesh** — 36 Starlink satellites with 1 draw call
- **💡 Lens Flare** — Realistic sun effects

## Tech Stack

- **Frontend:** Three.js r128, HTML5, CSS3, JavaScript
- **Backend:** Flask
- **3D Graphics:** WebGL, GLSL shaders
- **APIs:** SpaceX (public), Voyager (calculated)

## Local Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Run
python app.py
```

Visit `http://localhost:7860`

## Deployment

Deployed on Hugging Face Spaces with Docker.

## Project Structure

```
kombaz-mall/
├── index.html           # Main frontend
├── app.py              # Flask backend
├── requirements.txt    # Dependencies
├── static/
│   ├── js/
│   │   ├── voyager-worker.js
│   │   ├── starlink-instanced.js
│   │   └── lens-flare.js
│   └── data/
│       └── missions.json
├── Dockerfile
└── README.md
```

## APIs

- `GET /` — Main HTML
- `GET /api/voyager` — Voyager 1 & 2 telemetry
- `GET /api/spacex/launches` — Next SpaceX launches
- `GET /api/missions` — Mission data
- `GET /api/portfolio` — Portfolio data
- `GET /api/health` — Health check

## Optimizations

- **Web Worker:** Voyager calculations don't block UI
- **InstancedMesh:** 36 satellites = 1 draw call (vs 36)
- **Lens Flare:** GPU-accelerated shader effects
- **Frustum Culling:** Three.js auto-optimized
- **Responsive:** CSS Grid, mobile-first design

## Performance

- **FPS:** 60+ on modern devices
- **Load Time:** <2 seconds
- **Bundle Size:** ~300KB (optimized)

## Author

Shai Kombaz
- https://kombaz.co
- https://kombaz.net
- https://kombaz.me

## License

MIT

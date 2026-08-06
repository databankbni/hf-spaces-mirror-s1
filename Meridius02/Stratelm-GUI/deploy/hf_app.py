"""HuggingFace Space entrypoint.

Wraps the existing FastAPI backend (Stratelm-GUI/backend/main.py) and, in the SAME
process/port, serves the pre-built React frontend as static files with SPA fallback.
This lets the whole dashboard run in ONE HF Docker container on a single port (7860),
with no nginx -- the frontend calls relative `/api` + `/ws`, which this same app serves.

Nothing in the teammate's main.py is modified: we import its `app` and just add the
static mount + catch-all AFTER all the existing /api and /ws routes are registered, so
those keep matching first.
"""
import os
import sys

# main.py lives in the backend dir; import it as a top-level module.
BACKEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "Stratelm-GUI", "backend")
sys.path.insert(0, BACKEND_DIR)

from main import app  # noqa: E402  the teammate's FastAPI app (all /api + /ws routes)

from fastapi.staticfiles import StaticFiles  # noqa: E402
from starlette.responses import FileResponse  # noqa: E402

FRONTEND_DIST = os.environ.get("FRONTEND_DIST", "/app/frontend_dist")

# Hashed build assets (JS/CSS/img) under /assets — mounted directly for correct MIME types.
_assets = os.path.join(FRONTEND_DIST, "assets")
if os.path.isdir(_assets):
    app.mount("/assets", StaticFiles(directory=_assets), name="assets")


@app.get("/{full_path:path}")
async def _spa(full_path: str):
    """Serve a real file if it exists (favicon, etc.), else the SPA index for client routes.
    Registered last, so it never shadows the API/WS routes above."""
    candidate = os.path.join(FRONTEND_DIST, full_path)
    if full_path and os.path.isfile(candidate):
        return FileResponse(candidate)
    return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))

"""Per-mode view renderers (Sprint 4.5 decomposition of app.py).

Each mode (Home / Single Company / Compare / Sector View / Screener) lives in
its own module exposing ``render(ctx)``. ``app.py`` builds a ``ViewContext``
and dispatches to the right view, so the top-level script stays a thin shell.
"""
from views.shared import ViewContext

__all__ = ["ViewContext"]

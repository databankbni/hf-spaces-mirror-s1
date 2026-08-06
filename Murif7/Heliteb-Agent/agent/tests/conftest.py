"""Test fixtures and module mocking for agent tests."""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

# ── Set env vars BEFORE any test imports main ───────────────────────────────
# Tests in agent/tests/ import ``main`` and ``graph`` at module level.
# ``main`` reads env vars at import time.  Set them here so every test
# gets consistent values regardless of import order.
os.environ.setdefault("MISTRAL_API_KEY", "test-mistral-key")
os.environ.setdefault("GOOGLE_API_KEY", "test-google-key")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-supabase-key")
os.environ.setdefault("BREVO_API_KEY", "xkeysib-test")

# ── Mock heavy tools modules (they load BGE-M3 at import) ──────────────────
# Do NOT mock llm / llm.client — test_llm_client.py needs the real module.
_tool_modules = [
    "tools",
    "tools.catalog",
    "tools.stock",
    "tools.competition",
    "tools.calculator",
    "tools.cross_sell",
    "tools.quotations",
]
for name in _tool_modules:
    if name not in sys.modules:
        sys.modules[name] = MagicMock()

# ── Mock prompts.system with required string attributes ────────────────────
_prompt_modules = ["prompts", "prompts.system"]
for name in _prompt_modules:
    if name not in sys.modules:
        sys.modules[name] = MagicMock()

import prompts.system  # noqa: E402
prompts.system.SYSTEM_PROMPT = "mock system prompt"
prompts.system.INTENT_CLASSIFICATION_PROMPT = "mock intent prompt"

# ── fpdf2 bullet-character compatibility ───────────────────────────────────
# main.py uses ``\u2022`` (bullet) with Helvetica core font which only
# supports latin-1.  Patch the cell() method to replace bullets with
# ASCII hyphens so PDF generation works under test.
_original_cell = None


def _patch_fpdf_bullet() -> None:
    """Replace bullet/em-dash chars in fpdf2 ``cell()`` text to avoid encoding errors."""
    global _original_cell
    try:
        import fpdf  # noqa: F811
    except ImportError:
        return
    if _original_cell is not None:
        return  # already patched

    # Disable PDF content-stream compression so tests can grep raw bytes.
    _orig_fpdf_init = fpdf.FPDF.__init__

    def _patched_fpdf_init(self, *args, **kwargs):
        _orig_fpdf_init(self, *args, **kwargs)
        self.compress = False

    fpdf.FPDF.__init__ = _patched_fpdf_init

    # Replace non-latin-1 characters that main.py uses with Helvetica core font
    _original_cell = fpdf.FPDF.cell

    _REPLACE_MAP = {"\u2022": "-", "\u2014": "--", "\u2192": "->"}

    def _safe_cell(self, w=None, h=None, txt="", border=0, **kwargs):
        if isinstance(txt, str):
            for bad, good in _REPLACE_MAP.items():
                txt = txt.replace(bad, good)
        return _original_cell(self, w, h, txt, border, **kwargs)

    fpdf.FPDF.cell = _safe_cell


_patch_fpdf_bullet()

# ── Disable rate limiting in tests ─────────────────────────────────────────
# The RateLimitMiddleware uses in-memory IP-based counting.  TestClient
# requests all originate from 'testclient' and quickly exhaust the 30/min
# budget, causing 429s on later tests.  Replace the dispatch method with
# a pass-through that never counts or rejects requests.
async def _rate_limit_noop(self, request, call_next):
    return await call_next(request)


try:
    from middleware import RateLimitMiddleware  # noqa: E402

    RateLimitMiddleware.dispatch = _rate_limit_noop
except ImportError:
    pass

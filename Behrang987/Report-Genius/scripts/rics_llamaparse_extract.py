#!/usr/bin/env python3
"""CLI for LlamaParse RICS PDF extract.

Implementation lives in ``backend.ingest.llamaparse_extract``. This script stays
under ``scripts/`` for offline use and for siblings that load it by path
(e.g. ``rics_pdf_to_chunks.py``).

Usage (from repo root)::

  set LLAMA_CLOUD_API_KEY=llx-...
  python scripts/rics_llamaparse_extract.py report.pdf -o ./out --rics
  python scripts/rics_llamaparse_extract.py report.pdf --tier agentic_plus
"""

from __future__ import annotations

# Re-export library API so path-loaded callers keep working.
from backend.ingest.llamaparse_extract import (  # noqa: F401
    main,
    parse_rics_pdf,
    parse_with_llama_cloud,
    parse_with_llama_parse,
    parse_with_rest,
    resolve_api_key,
    segment_rics,
    write_outputs,
)

if __name__ == "__main__":
    raise SystemExit(main())

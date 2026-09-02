"""Content-based (topic-first) report mode.

Parallel to the RICS Level 3 structure-first pipeline: this package understands
messy notes, past reports, and standard paragraphs by *meaning* (a fixed
property-surveying topic taxonomy) rather than by RICS section structure, and
generates a topic-structured report.

Public surface is intentionally small; import the submodules directly:

- :mod:`backend.content_based.taxonomy` — fixed topic/sub-topic taxonomy + priors
- :mod:`backend.content_based.classifier` — content-first topic classification
- :mod:`backend.content_based.router` — route note lines into topic buckets
- :mod:`backend.content_based.orchestrator` — topic-driven report generation
"""

from __future__ import annotations

"""Shared pytest fixtures.

The cross-encoder is disabled here (RERANK=0) so the matcher tests stay fast
and don't need to download the cross-encoder model.
"""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("RERANK", "0")  # must be set before importing matcher
os.environ.setdefault("VERSEO_DB", "/tmp/verseo_test.db")  # isolate the test DB
os.environ.setdefault("ADMIN_PASSWORD", "testpass")  # enable admin in tests
os.environ.pop("DATABASE_URL", None)  # tests always run on the SQLite fallback

# Make the package importable when running `pytest` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_index import EMB_FILE  # noqa: E402
from corpus import VERSIONS_DIR  # noqa: E402

_HAVE_INDEX = EMB_FILE.exists()
_HAVE_VERSIONS = VERSIONS_DIR.exists() and any(VERSIONS_DIR.glob("*.json"))

needs_index = pytest.mark.skipif(not _HAVE_INDEX, reason="run build_index.py first")
needs_versions = pytest.mark.skipif(
    not _HAVE_VERSIONS, reason="run download_versions.py first"
)


@pytest.fixture(scope="session")
def matcher():
    from matcher import VerseMatcher

    if not _HAVE_INDEX:
        pytest.skip("embedding index not built")
    return VerseMatcher()

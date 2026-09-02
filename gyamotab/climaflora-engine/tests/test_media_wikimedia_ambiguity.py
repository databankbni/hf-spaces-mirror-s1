from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_ingester_module():
    path = Path(__file__).resolve().parents[1] / ".github" / "tools" / "media_ingest_wikimedia.py"
    spec = importlib.util.spec_from_file_location("media_ingest_wikimedia_ambiguity", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_ambiguous_commons_labels_are_rejected_conservatively():
    ingester = _load_ingester_module()

    assert ingester.media_label_is_ambiguous("Aa_maderoi_or_paleacea_123.jpg")
    assert ingester.media_label_is_ambiguous("Plant_cf._species.jpg")
    assert ingester.media_label_is_ambiguous("Possibly_Akebia_trifoliata.jpg")
    assert ingester.media_label_is_ambiguous("Akebia_trifoliata?.jpg")

    assert not ingester.media_label_is_ambiguous("Akebia_trifoliata_SZ78.png")
    assert not ingester.media_label_is_ambiguous("Akebia_trifoliata_2024.jpg")

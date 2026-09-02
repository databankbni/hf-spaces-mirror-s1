from __future__ import annotations

import importlib.util
from pathlib import Path


TOOLS = Path(__file__).resolve().parents[1] / ".github" / "tools"
MODULE_PATH = TOOLS / "collect_wikimedia_media_v2.py"
spec = importlib.util.spec_from_file_location("collect_wikimedia_media_v2", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_wikimedia_species_scope_is_conservative():
    assert module.is_binomial_species("Acer nigrum") is True
    assert module.is_binomial_species("Acer saccharum") is True
    assert module.is_binomial_species("Acer saccharum var. schneckii") is False
    assert module.is_binomial_species("Acer × martinii") is False
    assert module.is_binomial_species("Acer") is False


def test_wikimedia_candidate_maps_to_media_v2_gap_asset():
    selected = {
        "asset_id": "commons-example",
        "filename": "Acer nigrum example.JPG",
        "thumbnail_url": "https://upload.wikimedia.org/thumb/a/example.jpg",
        "image_url": "https://upload.wikimedia.org/thumb/a/example-960px.jpg",
        "source_page_url": "https://commons.wikimedia.org/wiki/File:Acer_nigrum_example.JPG",
        "license": "CC0 1.0",
        "author": "Example author",
        "quality_rank": 130,
    }
    asset = module.media_v2_asset("wfo-test", "Acer nigrum", selected)
    assert asset["taxon_id"] == "wfo-test"
    assert asset["verified_taxon_name"] == "Acer nigrum"
    assert asset["source"] == "wikimedia_commons"
    assert asset["source_dataset_id"] == "Wikidata:P225+P18/Wikimedia-Commons"
    assert asset["license"] == "CC0 1.0"
    assert asset["is_primary"] == 1
    assert asset["materialized"] == 0

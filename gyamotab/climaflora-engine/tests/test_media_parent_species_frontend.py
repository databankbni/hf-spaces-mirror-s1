from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / 'frontend' / 'static'


def test_media_frontend_labels_parent_species_fallback():
    media = (STATIC / 'media-v2.js').read_text(encoding='utf-8')
    config = (STATIC / 'config.js').read_text(encoding='utf-8')
    assert 'taxonomic_fallback' in media
    assert 'illustrated_taxon_name' in media
    assert 'Photo de l’espèce de référence' in media
    assert 'photo illustre l’espèce parente et non le taxon infraspécifique exact' in media
    assert 'media-v2-3-wikimedia-p18-20260825' in config

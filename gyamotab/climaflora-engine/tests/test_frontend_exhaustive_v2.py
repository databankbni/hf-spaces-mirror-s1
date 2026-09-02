from pathlib import Path


FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
STATIC = FRONTEND / "static"


def test_frontend_uses_canonical_stylesheet_plus_versioned_ui_overlay():
    stylesheets = sorted(path.name for path in STATIC.glob("*.css"))
    assert stylesheets == [
        "auth.css",
        "billing.css",
        "climaflora.css",
        "media-v2.css",
        "ui-v101-refinements.css",
    ]


def test_frontend_auth_uses_publishable_key_and_exposes_session_token():
    config = (STATIC / "config.js").read_text(encoding="utf-8")
    auth = (STATIC / "auth.js").read_text(encoding="utf-8")
    index = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert "sb_publishable_" in config
    assert "service_role" not in config.lower()
    assert "onAuthStateChange" in auth
    assert "get accessToken()" in auth
    assert "auth/sostagora/exchange" in auth
    assert "subscription_management" in auth
    assert ".from('climaflora_profiles')" in auth
    assert "client.rpc('climaflora_admin_users')" in auth
    assert "client.rpc('climaflora_admin_set_plan'" in auth
    assert "emailRedirectTo:confirmationRedirect()" in auth
    assert "climaflora_my_entitlements" in auth
    assert "get isAdmin()" in auth
    assert "get entitlements()" in auth
    assert "data-auth-open" in index
    assert "data-workspace-nav=\"projects\"" in index
    assert "static/workspace.js?v=" in index
    assert 'id="new-search"' in index


def test_all_pages_use_canonical_stylesheet():
    for name in ("index.html", "a-propos.html", "methodologie.html"):
        html = (FRONTEND / name).read_text(encoding="utf-8")
        assert "static/climaflora.css?v=" in html
        assert "app.css" not in html
        assert "ui-v4.css" not in html
        assert "media-v1.css" not in html
        assert "search-v1.css" not in html


def test_index_loads_exhaustive_search_module():
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert "static/app.js?v=" in html
    assert "static/search-v2.js?v=" in html
    assert "static/search-progress.js?v=" in html
    assert "static/search-ui-v101.js?v=" in html
    assert "static/ui-v101-refinements.css?v=" in html


def test_media_v2_bootstrap_and_sources_are_explicit():
    config = (STATIC / "config.js").read_text(encoding="utf-8")
    media = (STATIC / "media-v2.js").read_text(encoding="utf-8")
    assert "media-v2.css" in config
    assert "media-v2.js" in config
    assert "media-v2-3-wikimedia-p18-20260825" in config
    assert "plantnet_gbif" in media
    assert "atlas_living_australia_apii" in media
    assert "dryades_flora_italia" in media
    assert "world_flora_online" in media
    assert "wikimedia_commons" in media
    assert "Wikimedia Commons" in media


def test_search_v2_uses_exhaustive_server_endpoint():
    js = (STATIC / "search-v2.js").read_text(encoding="utf-8")
    assert "recommendations/search" in js
    assert "recommendations/pool" not in js
    assert "Compteurs calculés sur toute la population évaluée" in js
    assert "PAGE_CACHE_MAX = 60" in js
    assert "fetchCompleteSet" not in js
    assert "pageCache" in js


def test_search_progress_tracks_exhaustive_requests():
    js = (STATIC / "search-progress.js").read_text(encoding="utf-8")
    assert "/recommendations\\/search" in js
    assert "role=\"progressbar\"" in js
    assert "Analyse exhaustive du catalogue" in js
    assert "Application des filtres" in js
    assert "Chargement de la page" in js
    assert "aria-valuenow" in js


def test_frontend_reference_tree_is_complete():
    expected_root = {".htaccess", "a-propos.html", "index.html", "methodologie.html", "tarifs.html"}
    actual_root = {path.name for path in FRONTEND.iterdir() if path.is_file()}
    assert actual_root == expected_root

    expected_static = {
        "app.js", "climaflora.css", "config.js", "enrichment-v1.js", "funnel-v1.js",
        "map-guard.js", "media-v1.js", "media-v2.css", "media-v2.js",
        "search-progress.js", "search-ui-v101.js",
        "auth.css", "auth.js", "billing.css", "billing.js", "search-v1.js", "search-v2.js",
        "ui-v101-refinements.css", "ui-v4.js", "workspace.js",
    }
    actual_static = {path.name for path in STATIC.iterdir() if path.is_file()}
    assert actual_static == expected_static

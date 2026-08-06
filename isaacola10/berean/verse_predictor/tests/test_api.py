"""API surface via FastAPI TestClient. We inject the matcher into app state
directly (and skip the background loader) so the endpoints are testable."""
import pytest
from fastapi.testclient import TestClient

import server


@pytest.fixture(scope="module")
def client(matcher):
    import os
    import store

    if os.path.exists(os.environ["VERSEO_DB"]):
        os.remove(os.environ["VERSEO_DB"])
    store.init_db()
    server.state["matcher"] = matcher
    server.state["ready"] = True
    server.state["error"] = None
    # Don't use the context manager — that would fire the background loader.
    return TestClient(server.app)


@pytest.fixture
def admin_headers(client):
    tok = client.post("/api/admin/login", json={"password": "testpass"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def test_health(client):
    body = client.get("/api/health").json()
    assert body["ready"] is True


def test_versions_lists_languages(client):
    body = client.get("/api/versions").json()
    codes = {v["code"] for v in body["versions"]}
    assert "KJV" in codes
    assert any(lang["code"] == "en" for lang in body["languages"])


def test_search_groups_and_flags_confidence(client):
    body = client.post(
        "/api/search", json={"text": "for God so loved the world", "top_k": 3}
    ).json()
    assert body["confident"] is True
    assert body["results"][0]["ref"] == "John 3:16"
    assert "translations" in body["results"][0]


def test_search_no_confident_match(client):
    body = client.post("/api/search", json={"text": "qwerty asdf zxcv nonsense"}).json()
    assert body["confident"] is False


def test_chapter_endpoint(client):
    body = client.get("/api/chapter", params={"book_no": 19, "chapter": 23}).json()
    assert body["chapter"] == 23
    assert len(body["verses"]) == 6


def _sse_events(text: str):
    import json
    return [json.loads(b[6:]) for b in text.strip().split("\n\n") if b.startswith("data: ")]


def test_ask_streams_verses_without_key(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.post("/api/ask", json={"question": "what about love?"})
    events = _sse_events(r.text)
    types = [e["type"] for e in events]
    # No key -> graceful: verses event + error note + done, no answer deltas.
    assert types[0] == "verses" and "done" in types
    assert len(events[0]["verses"]) > 0


def test_crossrefs_endpoint(client):
    refs = client.get(
        "/api/crossrefs", params={"book_no": 43, "chapter": 3, "verse": 16}
    ).json()["refs"]
    assert any(r["ref"] == "Romans 5:8" for r in refs)


def test_similar_endpoint(client):
    res = client.get(
        "/api/similar", params={"book_no": 43, "chapter": 3, "verse": 16}
    ).json()["results"]
    assert res and all("ref" in r for r in res)


def test_topics_and_scope(client):
    assert len(client.get("/api/topics").json()["topics"]) > 0
    body = client.post(
        "/api/search", json={"text": "love your enemies", "scope": "nt", "top_k": 3}
    ).json()
    # NT scope -> all results in books 40-66.
    assert all(r["book_no"] >= 40 for r in body["results"])


# -- admin / persistence -----------------------------------------------------
def test_admin_login_and_auth(client, admin_headers):
    assert client.post("/api/admin/login", json={"password": "wrong"}).status_code == 401
    assert client.get("/api/admin/stats").status_code == 401  # no token
    assert client.get("/api/admin/stats", headers=admin_headers).status_code == 200


def test_analytics_persist_and_zero_results(client, admin_headers):
    client.post("/api/search", json={"text": "for God so loved the world", "mode": "type"})
    client.post("/api/search", json={"text": "zxcv qwer nonsense gibberish", "mode": "type"})
    stats = client.get("/api/admin/stats", headers=admin_headers).json()
    assert stats["searches"] >= 2
    zr = client.get("/api/admin/zero-results", headers=admin_headers).json()["queries"]
    assert any("nonsense" in z["query"] for z in zr)


def test_topic_cms(client, admin_headers):
    before = len(client.get("/api/topics").json()["topics"])
    tid = client.post("/api/admin/topics", headers=admin_headers,
                      json={"label": "Mercy", "emoji": "🕊️", "query": "mercy compassion"}).json()["id"]
    assert len(client.get("/api/topics").json()["topics"]) == before + 1
    # disable it -> drops from public list
    client.put(f"/api/admin/topics/{tid}", headers=admin_headers, json={"enabled": 0})
    assert len(client.get("/api/topics").json()["topics"]) == before
    client.delete(f"/api/admin/topics/{tid}", headers=admin_headers)


def test_feature_flags_toggle_ask(client, admin_headers):
    client.put("/api/admin/flags", headers=admin_headers, json={"ask_enabled": "0"})
    assert client.post("/api/ask", json={"question": "what about hope?"}).status_code == 403
    assert client.get("/api/config").json()["ask_enabled"] is False
    client.put("/api/admin/flags", headers=admin_headers, json={"ask_enabled": "1"})


def test_search_lab_returns_components(client, admin_headers):
    body = {"text": "the lord is my shepherd",
            "weights": {"semantic": 0.5, "lexical": 0.5, "ce": 0.5, "ce_semantic": 0.3, "ce_lexical": 0.2}}
    res = client.post("/api/admin/search-preview", headers=admin_headers, json=body).json()["results"]
    assert res
    assert {"semantic", "lexical", "ce", "score"} <= res[0].keys()
    # Psalm 23 should still surface for this query (rank may vary with weights).
    assert any(r["ref"] == "Psalms 23:1" for r in res)


def test_listen_detects_scripture_and_filters_noise(client):
    quote = client.post("/api/listen", json={"text": "for God so loved the world that he gave his only son"}).json()
    assert quote["matched"] and quote["result"]["ref"] == "John 3:16"
    ref = client.post("/api/listen", json={"text": "turn to john chapter 3 verse 16"}).json()
    assert ref["matched"]
    noise = client.post("/api/listen", json={"text": "hey how are you doing today nice weather"}).json()
    assert noise["matched"] is False
    short = client.post("/api/listen", json={"text": "okay so"}).json()
    assert short["matched"] is False


def test_kill_switch_disables_actions(client, admin_headers):
    client.put("/api/admin/flags", headers=admin_headers, json={"disabled": "1"})
    assert client.get("/api/config").json()["disabled"] is True
    assert client.post("/api/search", json={"text": "love"}).status_code == 503
    assert client.post("/api/listen", json={"text": "for God so loved the world"}).status_code == 503
    # admin endpoints stay reachable so it can be turned back on
    assert client.get("/api/admin/flags", headers=admin_headers).status_code == 200
    client.put("/api/admin/flags", headers=admin_headers, json={"disabled": "0"})


def test_listen_context_driven_cues(client):
    r = client.post("/api/listen", json={"text": "in the book of Romans chapter 8 verse 28"}).json()
    assert r["matched"] and r["result"]["ref"] == "Romans 8:28"
    assert r["normalized_ref"] == "Romans 8:28"

    r = client.post("/api/listen", json={"text": "when Jesus said in matthew chapter five verse eight"}).json()
    assert r["matched"] and r["result"]["ref"] == "Matthew 5:8"

    # ref_style toggle produces 'v' form
    r = client.post("/api/listen", json={"text": "matthew 5 verse 2", "ref_style": "v"}).json()
    assert r["matched"] and r["normalized_ref"] == "Matthew 5v2"


# -- accounts / billing / key vault --------------------------------------------
def test_me_anonymous_and_checkout_requires_auth(client):
    body = client.get("/api/me").json()
    assert body["user"] is None
    assert client.post("/api/billing/checkout", json={"plan": "plus"}).status_code == 401


def test_app_key_vault_masked(client, admin_headers):
    import store
    client.put("/api/admin/app-keys", headers=admin_headers,
               json={"name": "stripe_secret_key", "value": "sk_test_vault12345"})
    keys = {k["name"]: k for k in client.get("/api/admin/app-keys", headers=admin_headers).json()["keys"]}
    k = keys["stripe_secret_key"]
    assert k["set"] and k["source"] == "db"
    assert "sk_test_vault12345" not in str(k)          # raw value never returned
    assert store.get_app_key("stripe_secret_key") == "sk_test_vault12345"
    client.delete("/api/admin/app-keys/stripe_secret_key", headers=admin_headers)


def test_stripe_webhook_lifecycle_updates_plan_and_payments(client, admin_headers):
    import billing, store
    store.upsert_user("u-test-1", "pay@test.com", "Payer")
    billing.apply_event({"type": "checkout.session.completed", "data": {"object": {
        "id": "cs_t1", "metadata": {"user_id": "u-test-1", "plan": "speaker"},
        "customer": "cus_t1", "customer_details": {"email": "pay@test.com"},
        "amount_total": 1900, "currency": "usd"}}})
    assert store.get_user("u-test-1")["plan"] == "speaker"
    # duplicate invoice events are idempotent
    ev = {"type": "invoice.paid", "data": {"object": {
        "id": "in_t1", "customer": "cus_t1", "customer_email": "pay@test.com",
        "amount_paid": 1900, "currency": "usd"}}}
    billing.apply_event(ev); billing.apply_event(ev)
    ids = [p["stripe_id"] for p in store.list_payments()]
    assert ids.count("in_t1") == 1
    billing.apply_event({"type": "customer.subscription.deleted",
                         "data": {"object": {"customer": "cus_t1"}}})
    assert store.get_user("u-test-1")["plan"] == "free"
    # admin surfaces
    users = client.get("/api/admin/users", headers=admin_headers).json()["users"]
    assert any(u["email"] == "pay@test.com" for u in users)
    stats = client.get("/api/admin/billing-stats", headers=admin_headers).json()
    assert stats["revenue_cents"] >= 3800 and stats["users"] >= 1


def test_clerk_jwt_dependency(client, monkeypatch):
    import time as _t
    import types
    import jwt as pyjwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    import clerkauth

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    tok = pyjwt.encode(
        {"sub": "u-jwt-1", "iss": "https://test.clerk.accounts.dev",
         "exp": int(_t.time()) + 600},
        private_key, algorithm="RS256",
    )

    class _FakeSigningKey:
        key = private_key.public_key()

    class _FakeJwksClient:
        def get_signing_key_from_jwt(self, token):
            return _FakeSigningKey()

    monkeypatch.setattr(clerkauth, "CLERK_ISSUER", "https://test.clerk.accounts.dev")
    monkeypatch.setattr(clerkauth, "_get_jwks_client", lambda: _FakeJwksClient())
    monkeypatch.setattr(clerkauth, "_fetch_profile",
                        lambda user_id: {"email": "jwt@test.com", "name": "JWT Tester"})

    body = client.get("/api/me", headers={"Authorization": f"Bearer {tok}"}).json()
    assert body["user"] and body["user"]["email"] == "jwt@test.com"
    assert body["user"]["name"] == "JWT Tester"
    assert body["user"]["plan"] == "free"


_CLERK_TEST_KEYS: dict[str, object] = {}
_CLERK_TEST_PROFILES: dict[str, dict] = {}


def _clerk_auth_headers(monkeypatch, user_id, email="sermon@test.com", name="Sermon Tester"):
    """Mint a fake-but-valid Clerk session token for `user_id` (see
    test_clerk_jwt_dependency for the full explanation of this pattern).

    Backed by a shared key/profile registry so multiple users' tokens can be
    verified within the same test (each call only patches the lookup tables
    once — a second, per-user monkeypatch would just clobber the first)."""
    import time as _t
    import jwt as pyjwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    import clerkauth

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _CLERK_TEST_KEYS[user_id] = private_key.public_key()
    _CLERK_TEST_PROFILES[user_id] = {"email": email, "name": name}
    tok = pyjwt.encode(
        {"sub": user_id, "iss": "https://test.clerk.accounts.dev", "exp": int(_t.time()) + 600},
        private_key, algorithm="RS256",
    )

    class _FakeSigningKey:
        def __init__(self, key):
            self.key = key

    class _FakeJwksClient:
        def get_signing_key_from_jwt(self, token):
            sub = pyjwt.decode(token, options={"verify_signature": False}).get("sub")
            return _FakeSigningKey(_CLERK_TEST_KEYS[sub])

    monkeypatch.setattr(clerkauth, "CLERK_ISSUER", "https://test.clerk.accounts.dev")
    monkeypatch.setattr(clerkauth, "_get_jwks_client", lambda: _FakeJwksClient())
    monkeypatch.setattr(clerkauth, "_fetch_profile", lambda uid: _CLERK_TEST_PROFILES[uid])
    return {"Authorization": f"Bearer {tok}"}


def test_sermon_studio_requires_speaker_plan(client, monkeypatch):
    headers = _clerk_auth_headers(monkeypatch, "u-sermon-free")
    r = client.post("/api/sermons", json={"title": "My Sermon"}, headers=headers)
    assert r.status_code == 402


def test_sermon_studio_crud_and_soft_delete(client, monkeypatch):
    import store

    headers = _clerk_auth_headers(monkeypatch, "u-sermon-1")
    store.upsert_user("u-sermon-1", "sermon@test.com", "Sermon Tester")
    store.set_user_billing("u-sermon-1", plan="speaker")

    create = client.post(
        "/api/sermons",
        json={
            "title": "The Prodigal Son",
            "description": "A story of grace",
            "points": [
                {"beat": "Hook", "title": "Everyone runs from something",
                 "verse_refs": [{"ref": "Luke 15:13", "version": "kjv", "text": "..."}]},
                {"beat": "Application", "title": "The Father is waiting", "verse_refs": []},
            ],
        },
        headers=headers,
    ).json()
    sermon = create["sermon"]
    assert sermon["title"] == "The Prodigal Son"
    assert len(sermon["points"]) == 2
    assert sermon["points"][0]["verse_refs"][0]["ref"] == "Luke 15:13"
    sermon_id = sermon["id"]

    listed = client.get("/api/sermons", headers=headers).json()["sermons"]
    assert any(s["id"] == sermon_id for s in listed)

    fetched = client.get(f"/api/sermons/{sermon_id}", headers=headers).json()["sermon"]
    assert fetched["description"] == "A story of grace"

    updated = client.put(
        f"/api/sermons/{sermon_id}",
        json={"title": "The Prodigal Son (Revised)",
              "points": [{"beat": "Hook", "title": "New opening", "verse_refs": []}]},
        headers=headers,
    ).json()["sermon"]
    assert updated["title"] == "The Prodigal Son (Revised)"
    assert len(updated["points"]) == 1

    # Another user can't see or touch it.
    other_headers = _clerk_auth_headers(monkeypatch, "u-sermon-2")
    store.upsert_user("u-sermon-2", "other@test.com", "Other")
    store.set_user_billing("u-sermon-2", plan="speaker")
    assert client.get(f"/api/sermons/{sermon_id}", headers=other_headers).status_code == 404
    assert client.delete(f"/api/sermons/{sermon_id}", headers=other_headers).status_code == 404

    # Archiving is a soft delete — the row survives with status='archived'.
    assert client.delete(f"/api/sermons/{sermon_id}", headers=headers).json()["ok"] is True
    assert not any(s["id"] == sermon_id for s in client.get("/api/sermons", headers=headers).json()["sermons"])
    assert store.get_sermon("u-sermon-1", sermon_id)["status"] == "archived"

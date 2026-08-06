from fastapi.testclient import TestClient
from hf_football_data_hub.api import app

client = TestClient(app)

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True

def test_packet_missing():
    r = client.get("/match-packet", params={"match_id": "missing"})
    assert r.status_code == 200
    assert r.json()["ok"] is False

def test_crow_screener_missing_is_data_only_nonblocking():
    r = client.get("/crow-screener", params={"match_id": "missing"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["blocking"] is False
    assert body["reason"] == "crow_artifact_not_found_dataset_only"

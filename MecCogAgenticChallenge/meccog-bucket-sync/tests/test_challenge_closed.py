from fakes import seed_agent


def test_registration_blocked_when_closed(make_env):
    env = make_env(CHALLENGE_CLOSED=True)
    bucket = "test-org/test-agent-9"
    env.hub.buckets[bucket] = {}
    env.hub.seed(".bucket-sync-handshake", "test-user", bucket=bucket)
    r = env.client.post(
        "/v1/agents/register",
        json={"agent_id": "agent-9", "model": "m", "harness": "h", "tools": []},
        headers={"authorization": "Bearer hf_dummy"},
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "CHALLENGE_CLOSED"


def test_writes_blocked_but_reads_still_work_when_closed(make_env):
    env = make_env(CHALLENGE_CLOSED=True)
    seed_agent(env.hub, "agent-1")

    r = env.client.post("/v1/messages", json={"agent_id": "agent-1", "body": "hi"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "CHALLENGE_CLOSED"

    assert env.client.get("/v1/agents").status_code == 200
    assert env.client.get("/v1/messages").status_code == 200


def test_root_reports_closed_status(make_env):
    env = make_env(CHALLENGE_CLOSED=True, CHALLENGE_ENDED_AT="2026-08-28")
    data = env.client.get("/v1").json()
    assert data["challenge_closed"] is True
    assert data["challenge_ended_at"] == "2026-08-28"


def test_open_by_default(env):
    data = env.client.get("/v1").json()
    assert data["challenge_closed"] is False
    assert data["challenge_ended_at"] is None

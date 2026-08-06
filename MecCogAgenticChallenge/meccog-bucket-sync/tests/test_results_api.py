import json

from fakes import seed_agent, seed_result


def seed_results(hub):
    seed_agent(hub, "agent-1")
    seed_agent(hub, "agent-2")
    a = seed_result(hub, "20260601-100000-000", "agent-1", 100.0)
    b = seed_result(hub, "20260601-110000-000", "agent-2", 120.0)
    c = seed_result(hub, "20260602-090000-000", "agent-1", 80.0, status="negative")
    hub.seed("results/verification_status.json", json.dumps({a: "valid", b: "invalid"}))
    return a, b, c


def test_list_backward_compatible_shape(env):
    a, b, c = seed_results(env.hub)
    data = env.client.get("/v1/results").json()
    assert data["count"] == 3 and data["matched"] == 3
    assert data["items"] == [c, b, a]


def test_status_and_verification_filters(env):
    a, b, c = seed_results(env.hub)
    assert env.client.get("/v1/results?status=negative").json()["items"] == [c]
    assert env.client.get("/v1/results?verification=valid").json()["items"] == [a]
    # c has no index entry → reads as pending
    assert env.client.get("/v1/results?verification=pending").json()["items"] == [c]
    assert env.client.get("/v1/results?verification=valid,invalid").json()["matched"] == 2


def test_bad_verification_param_is_400(env):
    r = env.client.get("/v1/results?verification=bogus")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_QUERY"


def test_expand_inlines_verification(env):
    a, b, _c = seed_results(env.hub)
    items = env.client.get("/v1/results?expand=true&order=asc").json()["items"]
    by_name = {i["filename"]: i for i in items}
    assert by_name[a]["verification"] == "valid"
    assert by_name[b]["verification"] == "invalid"
    assert by_name[a]["frontmatter"]["score"] == 100.0


def test_single_get_carries_verification_and_404s(env):
    a, _b, _c = seed_results(env.hub)
    r = env.client.get(f"/v1/results/{a}")
    assert r.status_code == 200
    assert r.json()["verification"] == "valid"
    assert env.client.get("/v1/results/nope.md").status_code == 404


def seed_trace(hub, agent, session, share="full"):
    hub.seed(
        f"traces/{agent}/{session}/manifest.md",
        f"---\nschema_version: 1\nharness: claude-code\nsession_id: {session}\n"
        f"agent: {agent}\nvia: bucket\nshare: {share}\ncompleteness: partial\n---\n",
    )


def seed_artifact(hub, name="submission.xlsx", content="fake spreadsheet bytes"):
    hub.seed(f"results/{name}", content, bucket="test-org/test-agent-1")
    return f"hf://buckets/test-org/test-agent-1/results/{name}"


def test_post_result_visible_immediately(env):
    seed_agent(env.hub, "agent-1")
    seed_trace(env.hub, "agent-1", "sess-1")
    source = seed_artifact(env.hub)
    r = env.client.post(
        "/v1/results",
        json={
            "source": source,
            "fields": {
                "score": 142.7,
                "method": "vllm-fp8",
                "status": "agent-run",
                "description": "fast",
                "session_id": "sess-1",
            },
        },
    )
    assert r.status_code == 201
    filename = r.json()["filename"]
    artifact_path = r.json()["artifact_path"]
    assert artifact_path == f"results/{filename.removesuffix('.md')}.xlsx"
    data = env.client.get("/v1/results?expand=true&limit=1").json()
    assert data["items"][0]["filename"] == filename
    assert data["items"][0]["verification"] == "pending"
    assert data["items"][0]["frontmatter"]["session_id"] == "sess-1"
    # the spreadsheet itself was promoted into central storage untouched
    central = env.hub.buckets[env.settings.central_bucket]
    assert central[artifact_path].decode() == "fake spreadsheet bytes"
    assert data["items"][0]["frontmatter"]["spreadsheet"] == artifact_path
    # no insights were given, so the auto-generated .md has an empty body
    assert data["items"][0]["body"] == ""
    # the verification index tracked the promotion
    index = json.loads(
        env.hub.buckets[env.settings.central_bucket]["results/verification_status.json"]
    )
    assert index[filename] == "pending"


def test_post_result_insights_become_the_body(env):
    seed_agent(env.hub, "agent-1")
    seed_trace(env.hub, "agent-1", "sess-1")
    source = seed_artifact(env.hub)
    r = env.client.post(
        "/v1/results",
        json={
            "source": source,
            "fields": {
                "score": 142.7,
                "method": "vllm-fp8",
                "status": "agent-run",
                "description": "fast",
                "session_id": "sess-1",
            },
            "insights": "M1H1 and M3H2 findings appear to contradict each other.",
        },
    )
    assert r.status_code == 201
    filename = r.json()["filename"]
    rec = env.client.get(f"/v1/results/{filename}").json()
    assert rec["body"] == "M1H1 and M3H2 findings appear to contradict each other."


def test_post_result_requires_session_id(env):
    seed_agent(env.hub, "agent-1")
    source = seed_artifact(env.hub)
    r = env.client.post(
        "/v1/results",
        json={
            "source": source,
            "fields": {
                "score": 142.7,
                "method": "vllm-fp8",
                "status": "agent-run",
                "description": "fast",
            },
        },
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_FRONTMATTER"


def test_post_result_requires_matching_trace(env):
    seed_agent(env.hub, "agent-1")
    source = seed_artifact(env.hub)
    r = env.client.post(
        "/v1/results",
        json={
            "source": source,
            "fields": {
                "score": 142.7,
                "method": "vllm-fp8",
                "status": "agent-run",
                "description": "fast",
                "session_id": "sess-missing",
            },
        },
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "TRACE_REQUIRED"


def test_post_result_rejects_stats_only_trace_when_full_required(env):
    seed_agent(env.hub, "agent-1")
    seed_trace(env.hub, "agent-1", "sess-1", share="stats")
    source = seed_artifact(env.hub)
    r = env.client.post(
        "/v1/results",
        json={
            "source": source,
            "fields": {
                "score": 142.7,
                "method": "vllm-fp8",
                "status": "agent-run",
                "description": "fast",
                "session_id": "sess-1",
            },
        },
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "TRACE_REQUIRED"


def test_post_result_full_trace_requirement_can_be_disabled(make_env):
    env = make_env(REQUIRE_FULL_TRACE_FOR_RESULTS="false")
    seed_agent(env.hub, "agent-1")
    seed_trace(env.hub, "agent-1", "sess-1", share="stats")
    source = seed_artifact(env.hub)
    r = env.client.post(
        "/v1/results",
        json={
            "source": source,
            "fields": {
                "score": 142.7,
                "method": "vllm-fp8",
                "status": "agent-run",
                "description": "fast",
                "session_id": "sess-1",
            },
        },
    )
    assert r.status_code == 201


def test_post_result_trace_requirement_can_be_disabled(make_env):
    env = make_env(REQUIRE_TRACE_FOR_RESULTS="false")
    seed_agent(env.hub, "agent-1")
    source = seed_artifact(env.hub)
    r = env.client.post(
        "/v1/results",
        json={
            "source": source,
            "fields": {
                "score": 142.7,
                "method": "vllm-fp8",
                "status": "agent-run",
                "description": "fast",
            },
        },
    )
    assert r.status_code == 201


def test_post_result_requires_source_extension(make_env):
    env = make_env(REQUIRE_TRACE_FOR_RESULTS="false")
    seed_agent(env.hub, "agent-1")
    source = seed_artifact(env.hub, name="no-extension")
    r = env.client.post(
        "/v1/results",
        json={
            "source": source,
            "fields": {
                "score": 142.7,
                "method": "vllm-fp8",
                "status": "agent-run",
                "description": "fast",
            },
        },
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_PATH"

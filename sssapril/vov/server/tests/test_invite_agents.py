import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_global_agents(client: AsyncClient, global_agents: list[dict]):
    resp = await client.get("/api/v1/agents")
    assert resp.status_code == 200

    body = resp.json()
    items = body["data"]["items"]
    assert len(items) >= len(global_agents)

    returned_ids = {item["id"] for item in items}
    for agent in global_agents:
        assert agent["id"] in returned_ids, f"Agent {agent['id']} not found in listing"


@pytest.mark.asyncio
async def test_list_global_agents_fields(client: AsyncClient, global_agents: list[dict]):
    resp = await client.get("/api/v1/agents")
    assert resp.status_code == 200

    items = resp.json()["data"]["items"]
    for item in items:
        assert "id" in item
        assert "name" in item
        assert "role" in item
        assert "is_active" in item


@pytest.mark.asyncio
async def test_list_project_agents(
    client: AsyncClient, project_with_agent: dict
):
    project_id = project_with_agent["project"]["id"]
    agent_id = project_with_agent["agent"]["id"]

    resp = await client.get(f"/api/v1/projects/{project_id}/agents")
    assert resp.status_code == 200

    body = resp.json()
    items = body["data"]["items"]
    assert len(items) >= 1

    project_agent_ids = {item["agent_id"] for item in items}
    assert agent_id in project_agent_ids


@pytest.mark.asyncio
async def test_project_agent_contains_agent_detail(
    client: AsyncClient, project_with_agent: dict
):
    project_id = project_with_agent["project"]["id"]

    resp = await client.get(f"/api/v1/projects/{project_id}/agents")
    assert resp.status_code == 200

    items = resp.json()["data"]["items"]
    assert len(items) >= 1

    pa = items[0]
    assert pa["agent"] is not None, "ProjectAgent should include nested agent detail"
    assert "name" in pa["agent"]
    assert "role" in pa["agent"]


@pytest.mark.asyncio
async def test_add_agent_to_project(client: AsyncClient):
    project_resp = await client.post(
        "/api/v1/projects",
        json={"name": "Invite Test Project"},
    )
    assert project_resp.status_code == 201
    project_id = project_resp.json()["data"]["id"]

    agent_resp = await client.post(
        "/api/v1/agents",
        json={
            "name": "Invitable Agent",
            "role": "researcher",
            "system_prompt": "You are a researcher",
        },
    )
    assert agent_resp.status_code == 201
    agent_id = agent_resp.json()["data"]["id"]

    add_resp = await client.post(
        f"/api/v1/projects/{project_id}/agents",
        json={"agent_id": agent_id, "override_config": {}},
    )
    assert add_resp.status_code == 201
    pa = add_resp.json()["data"]
    assert pa["agent_id"] == agent_id
    assert pa["project_id"] == project_id


@pytest.mark.asyncio
async def test_add_agent_to_project_reflected_in_list(client: AsyncClient):
    project_resp = await client.post(
        "/api/v1/projects",
        json={"name": "List After Add Project"},
    )
    project_id = project_resp.json()["data"]["id"]

    agent_resp = await client.post(
        "/api/v1/agents",
        json={
            "name": "Listed Agent",
            "role": "coder",
            "system_prompt": "You are a coder",
        },
    )
    agent_id = agent_resp.json()["data"]["id"]

    await client.post(
        f"/api/v1/projects/{project_id}/agents",
        json={"agent_id": agent_id, "override_config": {}},
    )

    list_resp = await client.get(f"/api/v1/projects/{project_id}/agents")
    assert list_resp.status_code == 200

    items = list_resp.json()["data"]["items"]
    found = any(item["agent_id"] == agent_id for item in items)
    assert found, f"Agent {agent_id} not found in project agent list after adding"


@pytest.mark.asyncio
async def test_global_agents_distinct_from_project_agents(
    client: AsyncClient, global_agents: list[dict]
):
    project_resp = await client.post(
        "/api/v1/projects",
        json={"name": "Distinct Test Project"},
    )
    project_id = project_resp.json()["data"]["id"]

    global_resp = await client.get("/api/v1/agents")
    global_count = global_resp.json()["data"]["total"]

    project_resp = await client.get(f"/api/v1/projects/{project_id}/agents")
    project_count = project_resp.json()["data"]["total"]

    assert project_count == 0, "New project should have 0 agents"
    assert global_count >= len(global_agents), "Global agent list should include seeded agents"

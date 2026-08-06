import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_add_member_default_role_participant(
    client: AsyncClient, project_with_group_and_members: dict
):
    group_id = project_with_group_and_members["group"]["id"]
    project = project_with_group_and_members["project"]

    agent = await _create_agent_helper(client, "New Agent", "planner")
    pa = await _add_agent_to_project_helper(client, project["id"], agent["id"])

    resp = await client.post(
        f"/api/v1/groups/{group_id}/members",
        json={"project_agent_id": pa["id"]},
    )
    assert resp.status_code == 201
    member = resp.json()["data"]
    assert member["role"] == "participant", (
        f"Default role should be 'participant', got '{member['role']}'"
    )


@pytest.mark.asyncio
async def test_add_member_with_explicit_lead_role(
    client: AsyncClient, project_with_group_and_members: dict
):
    group_id = project_with_group_and_members["group"]["id"]
    project = project_with_group_and_members["project"]

    agent = await _create_agent_helper(client, "Lead Agent", "editor")
    pa = await _add_agent_to_project_helper(client, project["id"], agent["id"])

    resp = await client.post(
        f"/api/v1/groups/{group_id}/members",
        json={"project_agent_id": pa["id"], "role": "lead"},
    )
    assert resp.status_code == 201
    member = resp.json()["data"]
    assert member["role"] == "lead"


@pytest.mark.asyncio
async def test_update_member_role_lead_to_participant(
    client: AsyncClient, project_with_group_and_members: dict
):
    group_id = project_with_group_and_members["group"]["id"]
    project_agents = project_with_group_and_members["project_agents"]

    agent_id = project_agents[0]["id"]

    resp = await client.put(
        f"/api/v1/groups/{group_id}/members/{agent_id}/role",
        json={"role": "lead"},
    )
    assert resp.status_code == 200
    updated = resp.json()["data"]
    assert updated["role"] == "lead"

    resp = await client.put(
        f"/api/v1/groups/{group_id}/members/{agent_id}/role",
        json={"role": "participant"},
    )
    assert resp.status_code == 200
    updated = resp.json()["data"]
    assert updated["role"] == "participant"


@pytest.mark.asyncio
async def test_update_member_role_participant_to_lead(
    client: AsyncClient, project_with_group_and_members: dict
):
    group_id = project_with_group_and_members["group"]["id"]
    project_agents = project_with_group_and_members["project_agents"]

    agent_id = project_agents[1]["id"]

    resp = await client.put(
        f"/api/v1/groups/{group_id}/members/{agent_id}/role",
        json={"role": "lead"},
    )
    assert resp.status_code == 200
    updated = resp.json()["data"]
    assert updated["role"] == "lead"


@pytest.mark.asyncio
async def test_role_change_reflected_in_member_list(
    client: AsyncClient, project_with_group_and_members: dict
):
    group_id = project_with_group_and_members["group"]["id"]
    project_agents = project_with_group_and_members["project_agents"]

    target_pa_id = project_agents[0]["id"]

    await client.put(
        f"/api/v1/groups/{group_id}/members/{target_pa_id}/role",
        json={"role": "lead"},
    )

    resp = await client.get(f"/api/v1/groups/{group_id}/members")
    assert resp.status_code == 200
    members = resp.json()["data"]["items"]

    target_member = next(
        (m for m in members if m["project_agent_id"] == target_pa_id), None
    )
    assert target_member is not None, "Target member not found in member list"
    assert target_member["role"] == "lead", (
        f"Expected role 'lead' after update, got '{target_member['role']}'"
    )


async def _create_agent_helper(client: AsyncClient, name: str, role: str) -> dict:
    resp = await client.post(
        "/api/v1/agents",
        json={"name": name, "role": role, "system_prompt": f"You are {name}"},
    )
    assert resp.status_code == 201
    return resp.json()["data"]


async def _add_agent_to_project_helper(
    client: AsyncClient, project_id: str, agent_id: str
) -> dict:
    resp = await client.post(
        f"/api/v1/projects/{project_id}/agents",
        json={"agent_id": agent_id, "override_config": {}},
    )
    assert resp.status_code == 201
    return resp.json()["data"]

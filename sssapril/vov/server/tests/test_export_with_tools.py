import io
import json
import zipfile

import pytest
from httpx import AsyncClient


EXPECTED_TOOL_FIELDS = {"id", "name", "tool_type", "description", "config"}


def _assert_agent_has_tools(agent: dict):
    assert "tools" in agent, f"Agent '{agent.get('agent_name', agent.get('name'))}' missing 'tools' field"
    tools = agent["tools"]
    assert isinstance(tools, list), f"Agent tools should be a list, got {type(tools)}"
    for tool in tools:
        missing = EXPECTED_TOOL_FIELDS - set(tool.keys())
        assert not missing, f"Tool missing fields: {missing}, got keys: {set(tool.keys())}"


@pytest.mark.asyncio
async def test_export_manifest_contains_agent_tools(
    client: AsyncClient, project_with_agent: dict
):
    project_id = project_with_agent["project"]["id"]

    resp = await client.get(f"/api/v1/projects/{project_id}/export")
    assert resp.status_code == 200

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        assert "manifest.json" in zf.namelist()
        manifest = json.loads(zf.read("manifest.json"))

    agents = manifest.get("structure", {}).get("agents", [])
    assert len(agents) > 0, "manifest.json should contain at least one agent"

    for agent in agents:
        _assert_agent_has_tools(agent)

    agent = agents[0]
    assert len(agent["tools"]) == 2, f"Expected 2 tools, got {len(agent['tools'])}"
    tool_names = {t["name"] for t in agent["tools"]}
    assert tool_names == {"web_search", "code_runner"}


@pytest.mark.asyncio
async def test_export_bundle_agents_json_contains_agent_tools(
    client: AsyncClient, project_with_agent: dict
):
    project_id = project_with_agent["project"]["id"]

    resp = await client.post(
        f"/api/v1/projects/{project_id}/export/bundle",
        json={"mode": "backup"},
    )
    assert resp.status_code == 200

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        assert "data/agents.json" in zf.namelist()
        agents = json.loads(zf.read("data/agents.json"))

    assert len(agents) > 0, "data/agents.json should contain at least one agent"

    for agent in agents:
        _assert_agent_has_tools(agent)

    agent = agents[0]
    assert len(agent["tools"]) == 2
    for tool in agent["tools"]:
        assert tool["tool_type"] in {"builtin", "function"}
        assert isinstance(tool["config"], dict)


@pytest.mark.asyncio
async def test_export_agent_tool_fields_complete(
    client: AsyncClient, project_with_agent: dict
):
    project_id = project_with_agent["project"]["id"]

    resp = await client.get(f"/api/v1/projects/{project_id}/export")
    assert resp.status_code == 200

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        manifest = json.loads(zf.read("manifest.json"))

    agents = manifest["structure"]["agents"]
    assert len(agents) > 0
    agent = agents[0]

    for tool in agent["tools"]:
        assert "id" in tool and tool["id"], "Tool must have a non-empty 'id'"
        assert "name" in tool and tool["name"], "Tool must have a non-empty 'name'"
        assert "tool_type" in tool and tool["tool_type"], "Tool must have a non-empty 'tool_type'"
        assert "description" in tool, "Tool must have 'description' field"
        assert "config" in tool, "Tool must have 'config' field"
        assert isinstance(tool["config"], dict), "Tool config must be a dict"

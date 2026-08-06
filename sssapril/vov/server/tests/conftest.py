import asyncio
import json
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.main import create_app
from app.api.deps import get_db
from app.models import (
    Project,
    Agent,
    AgentTool,
    AgentSkill,
    Skill,
    ProjectAgent,
    Group,
    GroupMember,
    Task,
    TaskAssignee,
    Chain,
    Message,
    Deliverable,
    Resource,
    Memory,
    Tag,
)

TEST_DB_URL = "sqlite+aiosqlite:///./test_vov.db"

test_engine = create_async_engine(
    TEST_DB_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)

TestSessionLocal = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


app = create_app()
app.dependency_overrides[get_db] = override_get_db


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionLocal() as session:
        yield session


async def _create_project(client: AsyncClient, name: str = "Test Project") -> dict:
    resp = await client.post(
        "/api/v1/projects",
        json={"name": name, "description": "A test project"},
    )
    assert resp.status_code == 201
    return resp.json()["data"]


async def _create_agent(
    client: AsyncClient,
    name: str = "Test Agent",
    role: str = "writer",
    tools: list | None = None,
) -> dict:
    payload = {
        "name": name,
        "role": role,
        "system_prompt": f"You are {name}",
        "tools": tools or [],
    }
    resp = await client.post("/api/v1/agents", json=payload)
    assert resp.status_code == 201
    return resp.json()["data"]


async def _add_agent_to_project(
    client: AsyncClient, project_id: str, agent_id: str
) -> dict:
    resp = await client.post(
        f"/api/v1/projects/{project_id}/agents",
        json={"agent_id": agent_id, "override_config": {}},
    )
    assert resp.status_code == 201
    return resp.json()["data"]


async def _create_group(
    client: AsyncClient,
    project_id: str,
    name: str = "Test Group",
    member_agent_ids: list | None = None,
) -> dict:
    payload = {
        "name": name,
        "description": "A test group",
        "member_agent_ids": member_agent_ids or [],
    }
    resp = await client.post(
        f"/api/v1/projects/{project_id}/groups",
        json=payload,
    )
    assert resp.status_code == 201
    return resp.json()["data"]


@pytest_asyncio.fixture
async def project_with_agent(client: AsyncClient) -> dict:
    project = await _create_project(client)
    agent = await _create_agent(
        client,
        name="Agent With Tools",
        role="writer",
        tools=[
            {
                "name": "web_search",
                "tool_type": "builtin",
                "description": "Search the web",
                "config": {"engine": "google"},
            },
            {
                "name": "code_runner",
                "tool_type": "function",
                "description": "Run code snippets",
                "config": {"timeout": 30},
            },
        ],
    )
    project_agent = await _add_agent_to_project(client, project["id"], agent["id"])
    return {
        "project": project,
        "agent": agent,
        "project_agent": project_agent,
    }


@pytest_asyncio.fixture
async def project_with_group_and_members(client: AsyncClient) -> dict:
    project = await _create_project(client, name="Role Test Project")
    agent_a = await _create_agent(client, name="Agent A", role="writer")
    agent_b = await _create_agent(client, name="Agent B", role="critic")
    pa_a = await _add_agent_to_project(client, project["id"], agent_a["id"])
    pa_b = await _add_agent_to_project(client, project["id"], agent_b["id"])
    group = await _create_group(
        client,
        project["id"],
        name="Role Test Group",
        member_agent_ids=[pa_a["id"], pa_b["id"]],
    )
    return {
        "project": project,
        "agents": [agent_a, agent_b],
        "project_agents": [pa_a, pa_b],
        "group": group,
    }


@pytest_asyncio.fixture
async def global_agents(client: AsyncClient) -> list[dict]:
    agents = []
    for i, role in enumerate(["writer", "critic", "researcher"]):
        agent = await _create_agent(
            client,
            name=f"Global Agent {i}",
            role=role,
        )
        agents.append(agent)
    return agents

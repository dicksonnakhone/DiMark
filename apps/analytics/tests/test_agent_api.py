import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.async_db import get_async_db
from app.db import Base
from app.main import app
from tests.conftest import MockLLMClient, setup_async_test_db


# ---------------------------------------------------------------------------
# Fixture: async HTTP client backed by in-memory SQLite
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_client():
    engine, SessionFactory = setup_async_test_db()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_get_async_db():
        async with SessionFactory() as session:
            yield session

    app.dependency_overrides[get_async_db] = override_get_async_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.pop(get_async_db, None)
    await engine.dispose()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tools(async_client: AsyncClient):
    response = await async_client.get("/api/agents/tools")
    assert response.status_code == 200
    tools = response.json()
    assert isinstance(tools, list)
    assert len(tools) >= 7
    names = {t["name"] for t in tools}
    assert "search_web" in names
    assert "query_past_campaigns" in names
    assert "create_campaign" in names
    assert "post_to_chat" in names
    assert "request_user_approval" in names


@pytest.mark.asyncio
async def test_list_tools_filter_by_category(async_client: AsyncClient):
    response = await async_client.get("/api/agents/tools?category=data")
    assert response.status_code == 200
    tools = response.json()
    assert all(t["category"] == "data" for t in tools)
    assert len(tools) >= 1


@pytest.mark.asyncio
async def test_start_session(async_client: AsyncClient):
    mock_llm = MockLLMClient(
        responses=[
            MockLLMClient.make_text_response(
                "I recommend a Google Ads campaign targeting ecommerce."
            )
        ]
    )

    with patch("app.agent_api.AnthropicLLMClient", return_value=mock_llm):
        response = await async_client.post(
            "/api/agents/sessions/start",
            json={
                "goal": "Plan a Q1 campaign for ecommerce",
                "agent_type": "planner",
            },
        )

    assert response.status_code == 200
    session = response.json()
    assert session["status"] == "completed"
    assert session["goal"] == "Plan a Q1 campaign for ecommerce"
    assert session["result_json"] is not None
    assert len(session["decisions"]) >= 1


@pytest.mark.asyncio
async def test_get_session(async_client: AsyncClient):
    mock_llm = MockLLMClient(
        responses=[MockLLMClient.make_text_response("Done.")]
    )

    with patch("app.agent_api.AnthropicLLMClient", return_value=mock_llm):
        create_resp = await async_client.post(
            "/api/agents/sessions/start",
            json={"goal": "Test session"},
        )

    session_id = create_resp.json()["id"]

    get_resp = await async_client.get(f"/api/agents/sessions/{session_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == session_id
    assert get_resp.json()["goal"] == "Test session"


@pytest.mark.asyncio
async def test_get_session_not_found(async_client: AsyncClient):
    response = await async_client.get(f"/api/agents/sessions/{uuid.uuid4()}")
    assert response.status_code == 404

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
    assert len(tools) >= 11
    names = {t["name"] for t in tools}
    assert "search_web" in names
    assert "query_past_campaigns" in names
    assert "create_campaign" in names
    assert "post_to_chat" in names
    assert "request_user_approval" in names
    assert "execute_campaign_on_platform" in names
    assert "pause_platform_campaign" in names
    assert "resume_platform_campaign" in names
    assert "update_platform_budget" in names


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


@pytest.mark.asyncio
async def test_continue_session(async_client: AsyncClient):
    """Test continuing a conversation with the agent."""
    mock_llm = MockLLMClient(
        responses=[
            # First response: agent completes initial task
            MockLLMClient.make_text_response(
                "I've created a campaign plan with a $10,000 budget."
            ),
            # Second response: agent responds to follow-up
            MockLLMClient.make_text_response(
                "I've updated the budget to $5,000 as requested."
            ),
        ]
    )

    with patch("app.agent_api.AnthropicLLMClient", return_value=mock_llm):
        # Start initial session
        create_resp = await async_client.post(
            "/api/agents/sessions/start",
            json={
                "goal": "Create a marketing campaign",
                "agent_type": "planner",
            },
        )

    assert create_resp.status_code == 200
    session = create_resp.json()
    assert session["status"] == "completed"
    session_id = session["id"]

    with patch("app.agent_api.AnthropicLLMClient", return_value=mock_llm):
        # Continue the session with a new message
        continue_resp = await async_client.post(
            f"/api/agents/sessions/{session_id}/continue",
            json={"message": "Change the budget to $5,000"},
        )

    assert continue_resp.status_code == 200
    continued_session = continue_resp.json()
    assert continued_session["id"] == session_id
    assert continued_session["status"] == "completed"
    # Should have more decisions after continuation
    assert len(continued_session["decisions"]) > len(session["decisions"])


@pytest.mark.asyncio
async def test_continue_session_not_found(async_client: AsyncClient):
    """Test continuing a non-existent session."""
    response = await async_client.post(
        f"/api/agents/sessions/{uuid.uuid4()}/continue",
        json={"message": "Hello"},
    )
    assert response.status_code == 422
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_continue_session_wrong_status(async_client: AsyncClient):
    """Test that you cannot continue a session that's awaiting approval."""
    mock_llm = MockLLMClient(
        responses=[
            # Response with a tool call that requires approval
            MockLLMClient.make_tool_call_response(
                "create_campaign",
                {"name": "Test Campaign", "objective": "conversions", "total_budget": 1000, "channels": ["meta"]},
            ),
        ]
    )

    with patch("app.agent_api.AnthropicLLMClient", return_value=mock_llm):
        create_resp = await async_client.post(
            "/api/agents/sessions/start",
            json={"goal": "Create a campaign"},
        )

    session_id = create_resp.json()["id"]
    status = create_resp.json()["status"]

    # If awaiting approval, trying to continue should fail
    if status == "awaiting_approval":
        response = await async_client.post(
            f"/api/agents/sessions/{session_id}/continue",
            json={"message": "Change something"},
        )
        assert response.status_code == 422
        assert "can only continue completed or failed sessions" in response.json()["detail"].lower()

"""Tests for the ExecutorAgent and orchestrator routing."""

import pytest

from app.db import Base
from app.models import AgentSession
from app.services.agents.executor_agent import ExecutorAgent
from app.services.agents.orchestrator import Orchestrator, build_default_registry
from app.services.agents.tool_registry import ToolRegistry, ToolSpec
from tests.conftest import MockLLMClient, setup_async_test_db


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_db():
    engine, SessionFactory = setup_async_test_db()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionFactory() as session:
        yield session
    await engine.dispose()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_simple_text_response(async_db):
    """ExecutorAgent receives a goal, LLM returns text -> session completes."""
    mock_llm = MockLLMClient(
        responses=[
            MockLLMClient.make_text_response(
                "Campaign has been deployed on Meta. External ID: dry-run-abc123."
            )
        ]
    )
    registry = build_default_registry()
    agent = ExecutorAgent(llm=mock_llm, registry=registry)

    session = AgentSession(
        goal="Execute Q1 campaign on Meta",
        status="pending",
        agent_type="executor",
        context_json={},
    )
    async_db.add(session)
    await async_db.flush()

    result = await agent.run(goal="Execute Q1 campaign on Meta", session=session, db=async_db)

    assert result.status == "completed"
    assert result.result_json is not None
    assert "deployed" in result.result_json["final_answer"]
    assert len(mock_llm.calls) == 1
    # Verify the system prompt contains execution-related instructions
    assert "execute" in mock_llm.calls[0]["system"].lower()


@pytest.mark.asyncio
async def test_executor_approval_tool_pauses(async_db):
    """ExecutorAgent calling a requires_approval tool pauses the session."""
    mock_llm = MockLLMClient(
        responses=[
            MockLLMClient.make_tool_call_response(
                tool_name="execute_campaign_on_platform",
                tool_input={
                    "campaign_id": "00000000-0000-0000-0000-000000000001",
                    "platform": "meta",
                    "campaign_name": "Q1 Test",
                    "objective": "conversions",
                    "total_budget": 1000.0,
                },
                reasoning="I will now execute the campaign on Meta.",
                tool_use_id="toolu_exec123",
            ),
        ]
    )
    registry = build_default_registry()
    agent = ExecutorAgent(llm=mock_llm, registry=registry)

    session = AgentSession(
        goal="Execute campaign",
        status="pending",
        agent_type="executor",
        context_json={},
    )
    async_db.add(session)
    await async_db.flush()

    result = await agent.run(goal="Execute campaign", session=session, db=async_db)

    assert result.status == "awaiting_approval"
    assert "_pending_tool_call" in result.context_json
    assert result.context_json["_pending_tool_call"]["tool_name"] == "execute_campaign_on_platform"


@pytest.mark.asyncio
async def test_orchestrator_routes_executor(async_db):
    """Orchestrator correctly routes 'executor' agent_type."""
    mock_llm = MockLLMClient(
        responses=[
            MockLLMClient.make_text_response("Execution complete.")
        ]
    )
    registry = build_default_registry()
    orchestrator = Orchestrator(llm=mock_llm, registry=registry)

    session = await orchestrator.start_session(
        goal="Deploy Q1 campaign",
        db=async_db,
        agent_type="executor",
    )

    assert session.status == "completed"
    assert session.agent_type == "executor"

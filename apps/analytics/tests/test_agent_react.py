import pytest
from sqlalchemy import select

from app.db import Base
from app.models import AgentDecision, AgentSession
from app.services.agents.base_agent import BaseAgent
from app.services.agents.tool_registry import ToolRegistry, ToolSpec
from tests.conftest import MockLLMClient, setup_async_test_db


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


async def dummy_benchmark(industry: str, **_kwargs) -> dict:
    return {"industry": industry, "avg_cac": 45.0}


def _build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    spec = ToolSpec(
        name="get_benchmarks",
        description="Get benchmarks",
        category="data",
        parameters_schema={
            "type": "object",
            "properties": {"industry": {"type": "string"}},
            "required": ["industry"],
        },
    )
    reg.register(spec, dummy_benchmark)
    return reg


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
async def test_simple_text_response(async_db):
    """Agent receives a goal, LLM returns text only -> session completes."""
    mock_llm = MockLLMClient(
        responses=[
            MockLLMClient.make_text_response(
                "Based on my analysis, I recommend focusing on Google Ads."
            )
        ]
    )
    registry = _build_registry()
    agent = BaseAgent(llm=mock_llm, registry=registry, system_prompt="You are a helper.")

    session = AgentSession(goal="Plan a campaign", status="pending", context_json={})
    async_db.add(session)
    await async_db.flush()

    result = await agent.run(goal="Plan a campaign", session=session, db=async_db)

    assert result.status == "completed"
    assert result.result_json is not None
    assert "recommend" in result.result_json["final_answer"]
    assert len(mock_llm.calls) == 1


@pytest.mark.asyncio
async def test_tool_call_then_answer(async_db):
    """Agent calls a tool, observes result, then gives final answer."""
    mock_llm = MockLLMClient(
        responses=[
            MockLLMClient.make_tool_call_response(
                tool_name="get_benchmarks",
                tool_input={"industry": "ecommerce"},
                reasoning="I need to check industry benchmarks first.",
            ),
            MockLLMClient.make_text_response(
                "Based on ecommerce benchmarks (CAC $45), I recommend a multi-channel approach."
            ),
        ]
    )
    registry = _build_registry()
    agent = BaseAgent(llm=mock_llm, registry=registry, system_prompt="You are a helper.")

    session = AgentSession(goal="Analyze benchmarks", status="pending", context_json={})
    async_db.add(session)
    await async_db.flush()

    result = await agent.run(goal="Analyze benchmarks", session=session, db=async_db)

    assert result.status == "completed"
    assert len(mock_llm.calls) == 2

    # Verify decisions were persisted
    decisions_result = await async_db.execute(
        select(AgentDecision)
        .where(AgentDecision.session_id == session.id)
        .order_by(AgentDecision.step_number, AgentDecision.created_at)
    )
    decisions = decisions_result.scalars().all()

    think_decisions = [d for d in decisions if d.phase == "think"]
    act_decisions = [d for d in decisions if d.phase == "act"]
    observe_decisions = [d for d in decisions if d.phase == "observe"]

    assert len(think_decisions) >= 1
    assert len(act_decisions) == 1
    assert act_decisions[0].tool_name == "get_benchmarks"
    assert act_decisions[0].tool_output is not None
    assert len(observe_decisions) == 1


@pytest.mark.asyncio
async def test_max_steps_limit(async_db):
    """Agent stops when max steps is reached."""
    # LLM always calls a tool (never gives final answer)
    mock_llm = MockLLMClient(
        responses=[
            MockLLMClient.make_tool_call_response(
                "get_benchmarks", {"industry": "saas"}, reasoning="Checking..."
            )
            for _ in range(20)
        ]
    )
    registry = _build_registry()
    agent = BaseAgent(
        llm=mock_llm, registry=registry, system_prompt="You are a helper.", max_steps=3
    )

    session = AgentSession(
        goal="Infinite loop test", status="pending", context_json={}, max_steps=3
    )
    async_db.add(session)
    await async_db.flush()

    result = await agent.run(goal="Infinite loop test", session=session, db=async_db)

    assert result.status == "completed"
    assert result.result_json.get("note") == "max_steps_reached"
    assert result.current_step == 3


@pytest.mark.asyncio
async def test_approval_pauses_agent(async_db):
    """Agent pauses when a tool requires approval."""
    registry = ToolRegistry()
    approval_spec = ToolSpec(
        name="create_something",
        description="Creates something",
        category="action",
        parameters_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
        },
        requires_approval=True,
    )

    async def create_something(name: str, **_kwargs) -> dict:
        return {"created": name}

    registry.register(approval_spec, create_something)

    mock_llm = MockLLMClient(
        responses=[
            MockLLMClient.make_tool_call_response(
                "create_something",
                {"name": "test"},
                reasoning="I will create something.",
                tool_use_id="toolu_test123",
            ),
        ]
    )
    agent = BaseAgent(llm=mock_llm, registry=registry, system_prompt="You are a helper.")

    session = AgentSession(goal="Create something", status="pending", context_json={})
    async_db.add(session)
    await async_db.flush()

    result = await agent.run(goal="Create something", session=session, db=async_db)

    assert result.status == "awaiting_approval"
    assert "_pending_tool_call" in result.context_json
    assert result.context_json["_pending_tool_call"]["tool_name"] == "create_something"

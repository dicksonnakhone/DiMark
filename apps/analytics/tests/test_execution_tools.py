"""Tests for execution tools (execute_campaign, pause, resume, update_budget)."""

import uuid

import pytest
from sqlalchemy import select

from app.db import Base
from app.models import Campaign, Execution, ExecutionAction
from tests.conftest import setup_async_test_db


# ---------------------------------------------------------------------------
# Fixture: async DB with a campaign pre-inserted
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_db():
    engine, SessionFactory = setup_async_test_db()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionFactory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def campaign(async_db):
    """Create a campaign in the DB for testing."""
    c = Campaign(
        name="Test Campaign",
        objective="conversions",
    )
    async_db.add(c)
    await async_db.flush()
    return c


@pytest.fixture
async def execution(async_db, campaign):
    """Create an execution in the DB for testing manage tools."""
    e = Execution(
        campaign_id=campaign.id,
        platform="meta",
        status="active",
        execution_plan={"campaign_name": "Test", "total_budget": 1000},
        external_campaign_id="ext-test-123",
        idempotency_key=f"test-idem-{uuid.uuid4().hex[:8]}",
    )
    async_db.add(e)
    await async_db.flush()
    return e


# ---------------------------------------------------------------------------
# Execute campaign tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_campaign_success(async_db, campaign):
    from app.services.agents.tools.execute_campaign import execute_campaign_on_platform

    result = await execute_campaign_on_platform(
        campaign_id=str(campaign.id),
        platform="meta",
        campaign_name="Test Launch",
        objective="conversions",
        total_budget=1000.0,
        ad_sets=[{"name": "Ad Set 1", "daily_budget": 50.0}],
        _db_session=async_db,
    )

    assert result["status"] == "completed"
    assert result["external_campaign_id"] is not None
    assert result["dry_run"] is True

    # Verify DB records were created
    exec_result = await async_db.execute(
        select(Execution).where(Execution.campaign_id == campaign.id)
    )
    executions = exec_result.scalars().all()
    assert len(executions) == 1
    assert executions[0].status == "completed"

    actions_result = await async_db.execute(
        select(ExecutionAction).where(
            ExecutionAction.execution_id == executions[0].id
        )
    )
    actions = actions_result.scalars().all()
    assert len(actions) == 1
    assert actions[0].action_type == "create_campaign"
    assert actions[0].status == "success"


@pytest.mark.asyncio
async def test_execute_campaign_missing_campaign(async_db):
    from app.services.agents.tools.execute_campaign import execute_campaign_on_platform

    result = await execute_campaign_on_platform(
        campaign_id=str(uuid.uuid4()),
        platform="meta",
        campaign_name="Ghost",
        objective="conversions",
        total_budget=500.0,
        _db_session=async_db,
    )

    assert "error" in result
    assert "not found" in result["error"]


@pytest.mark.asyncio
async def test_execute_campaign_no_db_session():
    from app.services.agents.tools.execute_campaign import execute_campaign_on_platform

    result = await execute_campaign_on_platform(
        campaign_id=str(uuid.uuid4()),
        platform="meta",
        campaign_name="No DB",
        objective="conversions",
        total_budget=500.0,
    )

    assert result == {"error": "No database session available"}


# ---------------------------------------------------------------------------
# Manage campaign tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pause_campaign(async_db, execution):
    from app.services.agents.tools.manage_campaign import pause_platform_campaign

    result = await pause_platform_campaign(
        execution_id=str(execution.id),
        _db_session=async_db,
    )

    assert result["success"] is True
    assert result["status"] == "paused"

    # Verify action recorded
    actions_result = await async_db.execute(
        select(ExecutionAction).where(
            ExecutionAction.execution_id == execution.id
        )
    )
    actions = actions_result.scalars().all()
    assert len(actions) == 1
    assert actions[0].action_type == "pause_campaign"


@pytest.mark.asyncio
async def test_resume_campaign(async_db, execution):
    from app.services.agents.tools.manage_campaign import resume_platform_campaign

    result = await resume_platform_campaign(
        execution_id=str(execution.id),
        _db_session=async_db,
    )

    assert result["success"] is True
    assert result["status"] == "active"


@pytest.mark.asyncio
async def test_update_budget(async_db, execution):
    from app.services.agents.tools.manage_campaign import update_platform_budget

    result = await update_platform_budget(
        execution_id=str(execution.id),
        new_budget=2000.0,
        _db_session=async_db,
    )

    assert result["success"] is True
    assert result["new_budget"] == 2000.0


@pytest.mark.asyncio
async def test_pause_campaign_not_found(async_db):
    from app.services.agents.tools.manage_campaign import pause_platform_campaign

    result = await pause_platform_campaign(
        execution_id=str(uuid.uuid4()),
        _db_session=async_db,
    )

    assert "error" in result
    assert "not found" in result["error"]

from __future__ import annotations

import time
import uuid
from typing import Any

from app.services.agents.tool_registry import ToolSpec

EXECUTE_CAMPAIGN_SPEC = ToolSpec(
    name="execute_campaign_on_platform",
    description=(
        "Execute an approved campaign plan on an ad platform (Meta, Google, LinkedIn). "
        "Creates the campaign, ad sets, and ads on the target platform. "
        "Returns external campaign IDs and links. Requires user approval."
    ),
    category="action",
    parameters_schema={
        "type": "object",
        "properties": {
            "campaign_id": {
                "type": "string",
                "description": "UUID of the campaign to execute",
            },
            "platform": {
                "type": "string",
                "enum": ["meta", "google", "linkedin"],
                "description": "Target ad platform",
            },
            "campaign_name": {
                "type": "string",
                "description": "Name for the campaign on the platform",
            },
            "objective": {
                "type": "string",
                "description": "Campaign objective (e.g. conversions, traffic, leads)",
            },
            "total_budget": {
                "type": "number",
                "description": "Total budget in USD",
            },
            "ad_sets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "daily_budget": {"type": "number"},
                        "targeting": {"type": "object"},
                        "creative": {"type": "object"},
                        "bid_strategy": {"type": "string"},
                    },
                    "required": ["name", "daily_budget"],
                },
                "description": "Ad sets to create",
            },
        },
        "required": [
            "campaign_id",
            "platform",
            "campaign_name",
            "objective",
            "total_budget",
        ],
    },
    requires_approval=True,
)


async def execute_campaign_on_platform(
    campaign_id: str,
    platform: str,
    campaign_name: str,
    objective: str,
    total_budget: float,
    ad_sets: list[dict[str, Any]] | None = None,
    *,
    _db_session: Any = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Execute a campaign on an ad platform via the platform adapter."""
    if _db_session is None:
        return {"error": "No database session available"}

    from sqlalchemy import select

    from app.models import Campaign, Execution, ExecutionAction
    from app.platforms.base import AdSetSpec, ExecutionPlan, Platform
    from app.platforms.factory import get_platform_adapter
    from app.settings import settings

    # Verify campaign exists
    result = await _db_session.execute(
        select(Campaign).where(Campaign.id == uuid.UUID(campaign_id))
    )
    campaign = result.scalars().first()
    if campaign is None:
        return {"error": f"Campaign {campaign_id} not found"}

    # Build execution plan
    plan = ExecutionPlan(
        platform=Platform(platform),
        campaign_name=campaign_name,
        objective=objective,
        total_budget=total_budget,
        ad_sets=[AdSetSpec(**a) for a in (ad_sets or [])],
    )

    # Generate idempotency key
    idempotency_key = f"exec-{campaign_id}-{platform}-{uuid.uuid4().hex[:8]}"

    # Create execution record
    execution = Execution(
        campaign_id=uuid.UUID(campaign_id),
        platform=platform,
        status="executing",
        execution_plan=plan.model_dump(mode="json"),
        idempotency_key=idempotency_key,
    )
    _db_session.add(execution)
    await _db_session.flush()

    # Get adapter and execute
    adapter = get_platform_adapter(platform, dry_run=settings.USE_DRY_RUN_EXECUTION)

    start = time.monotonic()
    exec_result = await adapter.create_campaign(plan, idempotency_key=idempotency_key)
    duration_ms = int((time.monotonic() - start) * 1000)

    # Record action
    action = ExecutionAction(
        execution_id=execution.id,
        action_type="create_campaign",
        idempotency_key=idempotency_key,
        request_json=plan.model_dump(mode="json"),
        response_json=exec_result.model_dump(mode="json"),
        status="success" if exec_result.success else "error",
        error_message=exec_result.error,
        duration_ms=duration_ms,
    )
    _db_session.add(action)

    # Update execution
    if exec_result.success:
        execution.status = "completed"
        execution.external_campaign_id = exec_result.external_campaign_id
        execution.external_ids = exec_result.external_ids
        execution.links = exec_result.links
    else:
        execution.status = "failed"
        execution.error_message = exec_result.error

    await _db_session.flush()

    return {
        "execution_id": str(execution.id),
        "status": execution.status,
        "platform": platform,
        "external_campaign_id": exec_result.external_campaign_id,
        "external_ids": exec_result.external_ids,
        "links": exec_result.links,
        "dry_run": settings.USE_DRY_RUN_EXECUTION,
    }

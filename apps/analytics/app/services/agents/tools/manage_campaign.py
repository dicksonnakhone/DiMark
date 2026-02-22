from __future__ import annotations

import time
import uuid
from typing import Any

from app.services.agents.tool_registry import ToolSpec

PAUSE_CAMPAIGN_SPEC = ToolSpec(
    name="pause_platform_campaign",
    description=(
        "Pause a running campaign on an ad platform. "
        "Requires user approval before execution."
    ),
    category="action",
    parameters_schema={
        "type": "object",
        "properties": {
            "execution_id": {
                "type": "string",
                "description": "UUID of the execution record",
            },
        },
        "required": ["execution_id"],
    },
    requires_approval=True,
)

RESUME_CAMPAIGN_SPEC = ToolSpec(
    name="resume_platform_campaign",
    description=(
        "Resume a paused campaign on an ad platform. "
        "Requires user approval before execution."
    ),
    category="action",
    parameters_schema={
        "type": "object",
        "properties": {
            "execution_id": {
                "type": "string",
                "description": "UUID of the execution record",
            },
        },
        "required": ["execution_id"],
    },
    requires_approval=True,
)

UPDATE_BUDGET_SPEC = ToolSpec(
    name="update_platform_budget",
    description=(
        "Update the budget of a live campaign on an ad platform. "
        "Requires user approval before execution."
    ),
    category="action",
    parameters_schema={
        "type": "object",
        "properties": {
            "execution_id": {
                "type": "string",
                "description": "UUID of the execution record",
            },
            "new_budget": {
                "type": "number",
                "description": "New total budget in USD",
            },
        },
        "required": ["execution_id", "new_budget"],
    },
    requires_approval=True,
)


async def _get_execution(execution_id: str, db_session: Any) -> Any:
    """Shared helper: load Execution by ID."""
    from sqlalchemy import select

    from app.models import Execution

    result = await db_session.execute(
        select(Execution).where(Execution.id == uuid.UUID(execution_id))
    )
    return result.scalars().first()


async def pause_platform_campaign(
    execution_id: str,
    *,
    _db_session: Any = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Pause a campaign on its ad platform."""
    if _db_session is None:
        return {"error": "No database session available"}

    from app.models import ExecutionAction
    from app.platforms.base import Platform
    from app.platforms.factory import get_platform_adapter
    from app.settings import settings

    execution = await _get_execution(execution_id, _db_session)
    if execution is None:
        return {"error": f"Execution {execution_id} not found"}
    if not execution.external_campaign_id:
        return {"error": "No external campaign ID -- campaign may not have been created yet"}

    adapter = get_platform_adapter(execution.platform, dry_run=settings.USE_DRY_RUN_EXECUTION)
    idem_key = f"pause-{execution_id}-{uuid.uuid4().hex[:8]}"

    start = time.monotonic()
    result = await adapter.pause_campaign(
        execution.external_campaign_id, platform=Platform(execution.platform)
    )
    duration_ms = int((time.monotonic() - start) * 1000)

    action = ExecutionAction(
        execution_id=execution.id,
        action_type="pause_campaign",
        idempotency_key=idem_key,
        request_json={"external_campaign_id": execution.external_campaign_id},
        response_json=result.model_dump(mode="json"),
        status="success" if result.success else "error",
        error_message=result.error,
        duration_ms=duration_ms,
    )
    _db_session.add(action)

    if result.success:
        execution.status = "paused"
    await _db_session.flush()

    return {
        "execution_id": execution_id,
        "status": execution.status,
        "success": result.success,
        "error": result.error,
    }


async def resume_platform_campaign(
    execution_id: str,
    *,
    _db_session: Any = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Resume a paused campaign on its ad platform."""
    if _db_session is None:
        return {"error": "No database session available"}

    from app.models import ExecutionAction
    from app.platforms.base import Platform
    from app.platforms.factory import get_platform_adapter
    from app.settings import settings

    execution = await _get_execution(execution_id, _db_session)
    if execution is None:
        return {"error": f"Execution {execution_id} not found"}
    if not execution.external_campaign_id:
        return {"error": "No external campaign ID"}

    adapter = get_platform_adapter(execution.platform, dry_run=settings.USE_DRY_RUN_EXECUTION)
    idem_key = f"resume-{execution_id}-{uuid.uuid4().hex[:8]}"

    start = time.monotonic()
    result = await adapter.resume_campaign(
        execution.external_campaign_id, platform=Platform(execution.platform)
    )
    duration_ms = int((time.monotonic() - start) * 1000)

    action = ExecutionAction(
        execution_id=execution.id,
        action_type="resume_campaign",
        idempotency_key=idem_key,
        request_json={"external_campaign_id": execution.external_campaign_id},
        response_json=result.model_dump(mode="json"),
        status="success" if result.success else "error",
        error_message=result.error,
        duration_ms=duration_ms,
    )
    _db_session.add(action)

    if result.success:
        execution.status = "active"
    await _db_session.flush()

    return {
        "execution_id": execution_id,
        "status": execution.status,
        "success": result.success,
        "error": result.error,
    }


async def update_platform_budget(
    execution_id: str,
    new_budget: float,
    *,
    _db_session: Any = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Update the budget for a live campaign."""
    if _db_session is None:
        return {"error": "No database session available"}

    from app.models import ExecutionAction
    from app.platforms.base import Platform
    from app.platforms.factory import get_platform_adapter
    from app.settings import settings

    execution = await _get_execution(execution_id, _db_session)
    if execution is None:
        return {"error": f"Execution {execution_id} not found"}
    if not execution.external_campaign_id:
        return {"error": "No external campaign ID"}

    adapter = get_platform_adapter(execution.platform, dry_run=settings.USE_DRY_RUN_EXECUTION)
    idem_key = f"budget-{execution_id}-{uuid.uuid4().hex[:8]}"

    start = time.monotonic()
    result = await adapter.update_budget(
        execution.external_campaign_id,
        new_budget,
        platform=Platform(execution.platform),
    )
    duration_ms = int((time.monotonic() - start) * 1000)

    action = ExecutionAction(
        execution_id=execution.id,
        action_type="update_budget",
        idempotency_key=idem_key,
        request_json={
            "external_campaign_id": execution.external_campaign_id,
            "new_budget": new_budget,
        },
        response_json=result.model_dump(mode="json"),
        status="success" if result.success else "error",
        error_message=result.error,
        duration_ms=duration_ms,
    )
    _db_session.add(action)
    await _db_session.flush()

    return {
        "execution_id": execution_id,
        "new_budget": new_budget,
        "success": result.success,
        "error": result.error,
    }

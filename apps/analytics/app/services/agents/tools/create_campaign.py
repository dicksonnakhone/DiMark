from __future__ import annotations

from typing import Any

from app.services.agents.tool_registry import ToolSpec

CREATE_CAMPAIGN_SPEC = ToolSpec(
    name="create_campaign",
    description=(
        "Create a new marketing campaign with specified parameters. "
        "Requires user approval before execution."
    ),
    category="action",
    parameters_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Campaign name"},
            "objective": {"type": "string", "description": "Campaign objective"},
            "total_budget": {"type": "number", "description": "Total budget in USD"},
            "channels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Channels to advertise on",
            },
            "start_date": {"type": "string", "format": "date"},
            "end_date": {"type": "string", "format": "date"},
        },
        "required": ["name", "objective", "total_budget", "channels"],
    },
    requires_approval=True,
)


async def create_campaign_tool(
    name: str,
    objective: str,
    total_budget: float,
    channels: list[str],
    start_date: str | None = None,
    end_date: str | None = None,
    *,
    _db_session: Any = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Create campaign using existing Campaign model. Requires approval gate."""
    if _db_session is None:
        return {"error": "No database session available"}

    from datetime import date as date_type

    from app.models import Campaign

    campaign = Campaign(
        name=name,
        objective=objective,
        start_date=date_type.fromisoformat(start_date) if start_date else None,
        end_date=date_type.fromisoformat(end_date) if end_date else None,
    )
    _db_session.add(campaign)
    await _db_session.flush()

    return {
        "campaign_id": str(campaign.id),
        "name": campaign.name,
        "objective": campaign.objective,
        "status": "created",
    }

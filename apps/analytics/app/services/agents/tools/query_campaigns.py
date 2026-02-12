from __future__ import annotations

from typing import Any

from app.services.agents.tool_registry import ToolSpec

QUERY_CAMPAIGNS_SPEC = ToolSpec(
    name="query_past_campaigns",
    description=(
        "Query historical campaign data including performance metrics, spend, and "
        "conversions. Returns campaign summaries with KPIs."
    ),
    category="data",
    parameters_schema={
        "type": "object",
        "properties": {
            "objective": {
                "type": "string",
                "description": "Filter by campaign objective",
            },
            "limit": {
                "type": "integer",
                "description": "Max number of campaigns to return",
                "default": 10,
            },
        },
        "required": [],
    },
)


async def query_past_campaigns(
    objective: str | None = None,
    limit: int = 10,
    *,
    _db_session: Any = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Query past campaign data. _db_session is injected by the agent executor."""
    if _db_session is None:
        return {"campaigns": [], "note": "No database session available"}

    from sqlalchemy import select

    from app.models import Campaign, MeasurementReport

    query = select(Campaign).order_by(Campaign.created_at.desc()).limit(limit)
    if objective:
        query = query.where(Campaign.objective == objective)

    result = await _db_session.execute(query)
    campaigns = result.scalars().all()

    campaign_data = []
    for campaign in campaigns:
        reports_result = await _db_session.execute(
            select(MeasurementReport)
            .where(MeasurementReport.campaign_id == campaign.id)
            .order_by(MeasurementReport.created_at.desc())
            .limit(1)
        )
        latest_report = reports_result.scalars().first()

        campaign_data.append(
            {
                "id": str(campaign.id),
                "name": campaign.name,
                "objective": campaign.objective,
                "target_cac": float(campaign.target_cac) if campaign.target_cac else None,
                "latest_metrics": latest_report.metrics_json if latest_report else None,
            }
        )

    return {"campaigns": campaign_data, "count": len(campaign_data)}

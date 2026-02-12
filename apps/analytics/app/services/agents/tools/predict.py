from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.services.agents.tool_registry import ToolSpec

PREDICT_SPEC = ToolSpec(
    name="predict_campaign_performance",
    description=(
        "Predict campaign performance based on budget allocation, channels, "
        "and historical data. Uses channel-specific simulation models."
    ),
    category="data",
    parameters_schema={
        "type": "object",
        "properties": {
            "channels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Marketing channels (e.g. ['google', 'meta'])",
            },
            "total_budget": {
                "type": "number",
                "description": "Total budget in USD",
            },
            "objective": {
                "type": "string",
                "description": "Campaign objective",
            },
        },
        "required": ["channels", "total_budget", "objective"],
    },
)


async def predict_campaign_performance(
    channels: list[str],
    total_budget: float,
    objective: str,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Simple prediction using existing channel model parameters."""
    from app.services.execution.channel_models import DEFAULT_CHANNEL_PARAMS

    per_channel = Decimal(str(total_budget)) / max(len(channels), 1)
    predictions: dict[str, Any] = {}
    for ch in channels:
        params = DEFAULT_CHANNEL_PARAMS.get(ch)
        if params is None:
            predictions[ch] = {"note": f"No model data for channel '{ch}'"}
            continue
        impressions = float((per_channel / params.base_cpm) * Decimal("1000"))
        clicks = impressions * float(params.base_ctr)
        conversions = clicks * float(params.base_cvr)
        cac = float(per_channel) / max(conversions, 1)
        predictions[ch] = {
            "estimated_impressions": int(impressions),
            "estimated_clicks": int(clicks),
            "estimated_conversions": int(conversions),
            "estimated_cac": round(cac, 2),
        }
    return {"predictions": predictions, "total_budget": total_budget, "objective": objective}

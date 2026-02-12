from __future__ import annotations

from typing import Any

from app.services.agents.tool_registry import ToolSpec

BENCHMARKS_SPEC = ToolSpec(
    name="get_industry_benchmarks",
    description=(
        "Get industry benchmark data for marketing channels including average CTR, CVR, "
        "CPC, and ROAS by industry vertical."
    ),
    category="data",
    parameters_schema={
        "type": "object",
        "properties": {
            "industry": {
                "type": "string",
                "description": "Industry vertical (e.g. 'ecommerce', 'saas', 'fintech')",
            },
            "channel": {
                "type": "string",
                "description": "Marketing channel (e.g. 'google', 'meta', 'linkedin')",
            },
        },
        "required": ["industry"],
    },
)

_BENCHMARKS: dict[str, dict[str, dict[str, float]]] = {
    "ecommerce": {
        "google": {"avg_ctr": 0.02, "avg_cvr": 0.03, "avg_cpc": 1.50, "avg_roas": 4.0},
        "meta": {"avg_ctr": 0.015, "avg_cvr": 0.02, "avg_cpc": 1.20, "avg_roas": 3.5},
        "tiktok": {"avg_ctr": 0.018, "avg_cvr": 0.015, "avg_cpc": 0.80, "avg_roas": 3.0},
    },
    "saas": {
        "google": {"avg_ctr": 0.018, "avg_cvr": 0.025, "avg_cpc": 3.50, "avg_roas": 5.0},
        "linkedin": {"avg_ctr": 0.008, "avg_cvr": 0.015, "avg_cpc": 5.00, "avg_roas": 6.0},
        "meta": {"avg_ctr": 0.012, "avg_cvr": 0.018, "avg_cpc": 2.80, "avg_roas": 3.8},
    },
    "fintech": {
        "google": {"avg_ctr": 0.015, "avg_cvr": 0.02, "avg_cpc": 4.00, "avg_roas": 4.5},
        "linkedin": {"avg_ctr": 0.006, "avg_cvr": 0.012, "avg_cpc": 6.00, "avg_roas": 5.0},
    },
}


async def get_industry_benchmarks(
    industry: str, channel: str | None = None, **_kwargs: Any
) -> dict[str, Any]:
    """Return static benchmark data. In production, this could call an external API."""
    industry_data = _BENCHMARKS.get(industry.lower(), {})
    if channel:
        return {
            "industry": industry,
            "channel": channel,
            "benchmarks": industry_data.get(channel.lower(), {}),
        }
    return {"industry": industry, "benchmarks": industry_data}

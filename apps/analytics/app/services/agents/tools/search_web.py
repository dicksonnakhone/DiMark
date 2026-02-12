from __future__ import annotations

from typing import Any

from app.services.agents.tool_registry import ToolSpec

SEARCH_WEB_SPEC = ToolSpec(
    name="search_web",
    description=(
        "Search the web for marketing industry information, competitor data, and trends."
    ),
    category="data",
    parameters_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
        },
        "required": ["query"],
    },
)


async def search_web(query: str, **_kwargs: Any) -> dict[str, Any]:
    """Stub: Returns placeholder results. Replace with real web search API."""
    return {
        "results": [
            {
                "title": f"Result for: {query}",
                "snippet": "Placeholder search result",
                "url": "https://example.com",
            }
        ],
        "query": query,
        "note": "Stub implementation - integrate with a search API for production use",
    }

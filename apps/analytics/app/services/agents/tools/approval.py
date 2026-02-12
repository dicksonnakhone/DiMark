from __future__ import annotations

from typing import Any

from app.services.agents.tool_registry import ToolSpec

APPROVAL_SPEC = ToolSpec(
    name="request_user_approval",
    description=(
        "Request explicit user approval before taking a significant action. "
        "Pauses the agent until approval is received."
    ),
    category="communication",
    parameters_schema={
        "type": "object",
        "properties": {
            "action_description": {
                "type": "string",
                "description": "What action needs approval",
            },
            "details": {
                "type": "object",
                "description": "Details about the action",
            },
        },
        "required": ["action_description"],
    },
    requires_approval=True,
)


async def request_user_approval(
    action_description: str,
    details: dict[str, Any] | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """This tool signals the agent loop to pause and wait for approval."""
    return {
        "approval_requested": True,
        "action": action_description,
        "details": details or {},
        "status": "awaiting_approval",
    }

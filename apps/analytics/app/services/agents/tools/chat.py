from __future__ import annotations

from typing import Any

from app.services.agents.tool_registry import ToolSpec

CHAT_SPEC = ToolSpec(
    name="post_to_chat",
    description="Send a message to the user chat interface.",
    category="communication",
    parameters_schema={
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Message to display to user",
            },
            "message_type": {
                "type": "string",
                "enum": ["info", "warning", "success", "question"],
                "default": "info",
            },
        },
        "required": ["message"],
    },
)


async def post_to_chat(
    message: str, message_type: str = "info", **_kwargs: Any
) -> dict[str, Any]:
    """Post message to the user. The API layer reads this from tool output."""
    return {"message": message, "type": message_type, "delivered": True}

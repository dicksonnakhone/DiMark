from __future__ import annotations

from typing import Any, Protocol


class LLMClient(Protocol):
    """Protocol for LLM clients to enable mock injection in tests."""

    async def create_message(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """Send a message and get a response.

        Returns a normalised dict:
            {
                "content": [{"type": "text", "text": "..."} | {"type": "tool_use", ...}],
                "stop_reason": "end_turn" | "tool_use",
                "usage": {"input_tokens": int, "output_tokens": int},
            }
        """
        ...


class AnthropicLLMClient:
    """Real Anthropic API client (async)."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        from anthropic import AsyncAnthropic

        from app.settings import settings

        self._client = AsyncAnthropic(api_key=api_key or settings.ANTHROPIC_API_KEY)
        self._model = model or settings.ANTHROPIC_MODEL

    async def create_message(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        response = await self._client.messages.create(**kwargs)

        return {
            "content": [self._normalize_block(block) for block in response.content],
            "stop_reason": response.stop_reason,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        }

    @staticmethod
    def _normalize_block(block: Any) -> dict[str, Any]:
        if block.type == "text":
            return {"type": "text", "text": block.text}
        elif block.type == "tool_use":
            return {
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            }
        return {"type": block.type}

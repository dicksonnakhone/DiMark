from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401  -- ensure all models are registered
from app.db import Base


# ---------------------------------------------------------------------------
# Mock LLM Client
# ---------------------------------------------------------------------------


class MockLLMClient:
    """Deterministic mock LLM client for tests.

    Accepts a list of responses to return in sequence. Each call to
    ``create_message`` pops the next response. If the list is exhausted a
    simple text-only response is returned (which causes the agent to stop).
    """

    def __init__(self, responses: list[dict[str, Any]] | None = None):
        self.responses: list[dict[str, Any]] = list(responses or [])
        self._call_index = 0
        self.calls: list[dict[str, Any]] = []

    async def create_message(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "system": system,
                "messages": messages,
                "tools": tools,
                "max_tokens": max_tokens,
            }
        )

        if self._call_index < len(self.responses):
            response = self.responses[self._call_index]
            self._call_index += 1
            return response

        # Default: return a simple text response so the agent stops
        return {
            "content": [{"type": "text", "text": "No more mock responses configured."}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }

    # ------------------------------------------------------------------
    # Helpers for building deterministic responses
    # ------------------------------------------------------------------

    @staticmethod
    def make_text_response(text: str) -> dict[str, Any]:
        """Create a text-only response (agent finishes)."""
        return {
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }

    @staticmethod
    def make_tool_call_response(
        tool_name: str,
        tool_input: dict[str, Any],
        reasoning: str = "",
        tool_use_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a response with a tool call."""
        content: list[dict[str, Any]] = []
        if reasoning:
            content.append({"type": "text", "text": reasoning})
        content.append(
            {
                "type": "tool_use",
                "id": tool_use_id or f"toolu_{uuid.uuid4().hex[:12]}",
                "name": tool_name,
                "input": tool_input,
            }
        )
        return {
            "content": content,
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }


# ---------------------------------------------------------------------------
# Sync test DB (unchanged — for existing test files)
# ---------------------------------------------------------------------------


def setup_test_db():
    """Create an in-memory SQLite engine and session factory for sync tests."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    return engine, TestingSessionLocal


# ---------------------------------------------------------------------------
# Async test DB (for agent tests)
# ---------------------------------------------------------------------------


def setup_async_test_db():
    """Create an in-memory async SQLite engine and session factory."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingAsyncSession = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    return engine, TestingAsyncSession

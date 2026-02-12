from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class ToolSpec:
    """Metadata for a registered tool."""

    name: str
    description: str
    category: str  # "data", "action", "communication"
    parameters_schema: dict[str, Any]  # JSON Schema for tool parameters
    requires_approval: bool = False
    version: str = "1.0.0"


@dataclass
class ToolResult:
    """Result of executing a tool."""

    success: bool
    output: dict[str, Any]
    error: str | None = None
    duration_ms: int = 0


class ToolRegistry:
    """Registry for agent tools. Tools are async callables."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._handlers: dict[str, Callable[..., Awaitable[dict[str, Any]]]] = {}

    def register(
        self,
        spec: ToolSpec,
        handler: Callable[..., Awaitable[dict[str, Any]]],
    ) -> None:
        """Register a tool with its handler function."""
        self._tools[spec.name] = spec
        self._handlers[spec.name] = handler

    def get(self, name: str) -> ToolSpec | None:
        """Get a tool spec by name."""
        return self._tools.get(name)

    def list_tools(self, category: str | None = None) -> list[ToolSpec]:
        """List all registered tools, optionally filtered by category."""
        tools = list(self._tools.values())
        if category:
            tools = [t for t in tools if t.category == category]
        return tools

    def search(self, query: str) -> list[ToolSpec]:
        """Search tools by name or description substring (case-insensitive)."""
        query_lower = query.lower()
        return [
            t
            for t in self._tools.values()
            if query_lower in t.name.lower() or query_lower in t.description.lower()
        ]

    def get_tool_schemas_for_anthropic(
        self, tool_names: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Return tool definitions in Anthropic API format for the tools use feature."""
        if tool_names is not None:
            specs = [self._tools[n] for n in tool_names if n in self._tools]
        else:
            specs = list(self._tools.values())
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "input_schema": spec.parameters_schema,
            }
            for spec in specs
        ]

    async def execute(
        self,
        name: str,
        params: dict[str, Any],
        *,
        session_id: uuid.UUID | None = None,
        decision_id: uuid.UUID | None = None,
        db: AsyncSession | None = None,
    ) -> ToolResult:
        """Execute a tool by name with given parameters."""
        spec = self._tools.get(name)
        if spec is None:
            return ToolResult(success=False, output={}, error=f"Tool '{name}' not found")

        handler = self._handlers[name]
        start = time.monotonic()
        try:
            output = await handler(**params)
            duration_ms = int((time.monotonic() - start) * 1000)
            result = ToolResult(success=True, output=output, duration_ms=duration_ms)
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            result = ToolResult(
                success=False,
                output={},
                error=str(exc),
                duration_ms=duration_ms,
            )

        # Persist execution record if DB session available
        if db is not None and session_id is not None:
            await self._log_execution(db, spec, params, result, session_id, decision_id)

        return result

    async def _log_execution(
        self,
        db: AsyncSession,
        spec: ToolSpec,
        params: dict[str, Any],
        result: ToolResult,
        session_id: uuid.UUID,
        decision_id: uuid.UUID | None,
    ) -> None:
        """Persist a ToolExecution record."""
        from app.models import Tool, ToolExecution

        tool_row = await self._ensure_tool_row(db, spec)
        # Strip internal params like _db_session before logging
        logged_params = {k: v for k, v in params.items() if not k.startswith("_")}
        execution = ToolExecution(
            session_id=session_id,
            tool_id=tool_row.id,
            decision_id=decision_id,
            input_json=logged_params,
            output_json=result.output if result.success else {"error": result.error},
            status="success" if result.success else "error",
            error_message=result.error,
            duration_ms=result.duration_ms,
        )
        db.add(execution)
        await db.flush()

    async def _ensure_tool_row(self, db: AsyncSession, spec: ToolSpec) -> Any:
        """Get or create the Tool row for persisting execution records."""
        from sqlalchemy import select

        from app.models import Tool

        stmt = select(Tool).where(Tool.name == spec.name, Tool.version == spec.version)
        result = await db.execute(stmt)
        tool = result.scalars().first()
        if tool is None:
            tool = Tool(
                name=spec.name,
                version=spec.version,
                description=spec.description,
                category=spec.category,
                parameters_schema=spec.parameters_schema,
                requires_approval=spec.requires_approval,
            )
            db.add(tool)
            await db.flush()
        return tool

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentSession
from app.services.agents.base_agent import BaseAgent
from app.services.agents.llm_client import LLMClient
from app.services.agents.planner_agent import PlannerAgent
from app.services.agents.tool_registry import ToolRegistry
from app.services.agents.tools import ALL_TOOL_HANDLERS, ALL_TOOL_SPECS


def build_default_registry() -> ToolRegistry:
    """Build a ToolRegistry with all default tools registered."""
    registry = ToolRegistry()
    for spec in ALL_TOOL_SPECS:
        handler = ALL_TOOL_HANDLERS[spec.name]
        registry.register(spec, handler)
    return registry


class Orchestrator:
    """Receives user goals, creates agent sessions, and delegates to specialist agents."""

    def __init__(self, *, llm: LLMClient, registry: ToolRegistry | None = None):
        self.llm = llm
        self.registry = registry or build_default_registry()

    def _get_agent(self, agent_type: str) -> BaseAgent:
        if agent_type == "planner":
            return PlannerAgent(llm=self.llm, registry=self.registry)
        if agent_type == "executor":
            from app.services.agents.executor_agent import ExecutorAgent

            return ExecutorAgent(llm=self.llm, registry=self.registry)
        raise ValueError(f"Unknown agent type: {agent_type}")

    async def start_session(
        self,
        *,
        goal: str,
        db: AsyncSession,
        agent_type: str = "planner",
        context: dict[str, Any] | None = None,
        max_steps: int = 15,
    ) -> AgentSession:
        """Create a new agent session and run the agent."""
        session = AgentSession(
            goal=goal,
            status="pending",
            agent_type=agent_type,
            context_json=context or {},
            max_steps=max_steps,
        )
        db.add(session)
        await db.flush()

        agent = self._get_agent(agent_type)
        agent.max_steps = max_steps

        session = await agent.run(
            goal=goal,
            session=session,
            db=db,
            context=context,
        )

        await db.commit()
        return session

    async def get_session(
        self, *, session_id: uuid.UUID, db: AsyncSession
    ) -> AgentSession | None:
        return await db.get(AgentSession, session_id)

    async def approve_decision(
        self,
        *,
        session_id: uuid.UUID,
        decision_id: uuid.UUID,
        approved: bool,
        db: AsyncSession,
    ) -> AgentSession:
        """Approve or reject a pending decision and resume the agent."""
        session = await db.get(AgentSession, session_id)
        if session is None:
            raise ValueError("Session not found")
        if session.status != "awaiting_approval":
            raise ValueError(f"Session is not awaiting approval (status: {session.status})")

        agent = self._get_agent(session.agent_type)
        session = await agent.resume_after_approval(
            session=session,
            db=db,
            decision_id=decision_id,
            approved=approved,
        )

        await db.commit()
        return session

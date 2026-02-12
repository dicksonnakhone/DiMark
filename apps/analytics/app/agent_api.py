import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent_schemas import (
    AgentSessionOut,
    ApproveDecisionRequest,
    StartSessionRequest,
    ToolOut,
)
from app.async_db import get_async_db
from app.models import AgentSession
from app.services.agents.llm_client import AnthropicLLMClient
from app.services.agents.orchestrator import Orchestrator, build_default_registry

agent_router = APIRouter(prefix="/api/agents", tags=["agents"])


def _get_orchestrator() -> Orchestrator:
    """Build orchestrator with real LLM client. Patched in tests."""
    llm = AnthropicLLMClient()
    registry = build_default_registry()
    return Orchestrator(llm=llm, registry=registry)


@agent_router.post("/sessions/start", response_model=AgentSessionOut)
async def start_session(
    payload: StartSessionRequest,
    db: AsyncSession = Depends(get_async_db),
):
    orchestrator = _get_orchestrator()
    try:
        session = await orchestrator.start_session(
            goal=payload.goal,
            db=db,
            agent_type=payload.agent_type,
            context=payload.context,
            max_steps=payload.max_steps,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Reload with decisions
    result = await db.execute(
        select(AgentSession)
        .where(AgentSession.id == session.id)
        .options(selectinload(AgentSession.decisions))
    )
    session = result.scalars().first()
    return session


@agent_router.get("/sessions/{session_id}", response_model=AgentSessionOut)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(
        select(AgentSession)
        .where(AgentSession.id == session_id)
        .options(selectinload(AgentSession.decisions))
    )
    session = result.scalars().first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@agent_router.post(
    "/sessions/{session_id}/decisions/{decision_id}/approve",
    response_model=AgentSessionOut,
)
async def approve_decision(
    session_id: uuid.UUID,
    decision_id: uuid.UUID,
    payload: ApproveDecisionRequest,
    db: AsyncSession = Depends(get_async_db),
):
    orchestrator = _get_orchestrator()
    try:
        session = await orchestrator.approve_decision(
            session_id=session_id,
            decision_id=decision_id,
            approved=payload.approved,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    result = await db.execute(
        select(AgentSession)
        .where(AgentSession.id == session.id)
        .options(selectinload(AgentSession.decisions))
    )
    session = result.scalars().first()
    return session


@agent_router.get("/tools", response_model=list[ToolOut])
async def list_tools(category: str | None = None):
    registry = build_default_registry()
    tools = registry.list_tools(category=category)
    return [
        ToolOut(
            name=t.name,
            description=t.description,
            category=t.category,
            parameters_schema=t.parameters_schema,
            requires_approval=t.requires_approval,
        )
        for t in tools
    ]

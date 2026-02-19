import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent_schemas import (
    ExecutionActionOut,
    ExecutionDetailOut,
    ExecutionOut,
    PlatformConnectorOut,
)
from app.async_db import get_async_db
from app.models import Execution, ExecutionAction, PlatformConnector

execution_router = APIRouter(prefix="/api/executions", tags=["executions"])


@execution_router.get("/connectors", response_model=list[PlatformConnectorOut])
async def list_connectors(
    db: AsyncSession = Depends(get_async_db),
):
    """List all configured platform connectors."""
    result = await db.execute(
        select(PlatformConnector).order_by(PlatformConnector.created_at.desc())
    )
    return result.scalars().all()


@execution_router.get("/campaign/{campaign_id}", response_model=list[ExecutionOut])
async def list_campaign_executions(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
):
    """List all executions for a specific campaign."""
    result = await db.execute(
        select(Execution)
        .where(Execution.campaign_id == campaign_id)
        .order_by(Execution.created_at.desc())
    )
    return result.scalars().all()


@execution_router.get("/{execution_id}", response_model=ExecutionDetailOut)
async def get_execution(
    execution_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
):
    """Get execution details including all recorded actions."""
    result = await db.execute(
        select(Execution)
        .where(Execution.id == execution_id)
        .options(selectinload(Execution.actions))
    )
    execution = result.scalars().first()
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return execution


@execution_router.get(
    "/{execution_id}/actions",
    response_model=list[ExecutionActionOut],
)
async def list_execution_actions(
    execution_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
):
    """List all actions for a specific execution."""
    result = await db.execute(
        select(ExecutionAction)
        .where(ExecutionAction.execution_id == execution_id)
        .order_by(ExecutionAction.created_at.desc())
    )
    return result.scalars().all()

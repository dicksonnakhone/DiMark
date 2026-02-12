import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StartSessionRequest(BaseModel):
    goal: str
    agent_type: str = "planner"
    context: dict[str, Any] = Field(default_factory=dict)
    max_steps: int = Field(default=15, ge=1, le=50)


class AgentDecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    step_number: int
    phase: str
    reasoning: str | None = None
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_output: dict[str, Any] | None = None
    requires_approval: bool
    approval_status: str | None = None
    created_at: datetime


class AgentSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    goal: str
    status: str
    agent_type: str
    current_step: int
    max_steps: int
    result_json: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    decisions: list[AgentDecisionOut] = []


class ApproveDecisionRequest(BaseModel):
    approved: bool


class ToolOut(BaseModel):
    name: str
    description: str
    category: str
    parameters_schema: dict[str, Any]
    requires_approval: bool

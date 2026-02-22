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
    context_json: dict[str, Any] = {}  # Contains _messages for debugging


class ApproveDecisionRequest(BaseModel):
    approved: bool


class ContinueSessionRequest(BaseModel):
    message: str


class ToolOut(BaseModel):
    name: str
    description: str
    category: str
    parameters_schema: dict[str, Any]
    requires_approval: bool


class ExecutionActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    execution_id: uuid.UUID
    action_type: str
    idempotency_key: str
    request_json: dict[str, Any]
    response_json: dict[str, Any] | None = None
    status: str
    error_message: str | None = None
    duration_ms: int | None = None
    created_at: datetime


class ExecutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    campaign_id: uuid.UUID
    platform: str
    status: str
    external_campaign_id: str | None = None
    external_ids: dict[str, str] | None = None
    links: dict[str, str] | None = None
    idempotency_key: str
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class ExecutionDetailOut(ExecutionOut):
    actions: list[ExecutionActionOut] = []


class PlatformConnectorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    platform: str
    account_id: str
    account_name: str | None = None
    status: str
    config_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime

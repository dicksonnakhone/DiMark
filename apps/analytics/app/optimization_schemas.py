"""Pydantic schemas for optimization API endpoints."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class RawMetricOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    campaign_id: uuid.UUID
    channel: str
    metric_name: str
    metric_value: float
    metric_unit: str
    source: str
    collected_at: datetime
    window_start: date | None = None
    window_end: date | None = None
    metadata_json: dict[str, Any] = {}
    created_at: datetime


class DerivedKPIOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    campaign_id: uuid.UUID
    channel: str | None = None
    kpi_name: str
    kpi_value: float
    window_start: date | None = None
    window_end: date | None = None
    input_metrics_json: dict[str, Any] = {}
    computed_at: datetime


class TrendIndicatorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    campaign_id: uuid.UUID
    channel: str | None = None
    kpi_name: str
    direction: str
    magnitude: float
    period_days: int
    current_value: float
    previous_value: float
    confidence: float
    analysis_json: dict[str, Any] = {}
    computed_at: datetime


class OptimizationMethodOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    method_type: str
    trigger_conditions: dict[str, Any] = {}
    config_json: dict[str, Any] = {}
    is_active: bool
    cooldown_minutes: int
    stats_json: dict[str, Any] = {}
    created_at: datetime
    updated_at: datetime


class OptimizationProposalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    campaign_id: uuid.UUID
    method_id: uuid.UUID
    status: str
    confidence: float
    priority: int
    action_type: str
    action_payload: dict[str, Any]
    reasoning: str
    trigger_data_json: dict[str, Any] = {}
    guardrail_checks_json: dict[str, Any] = {}
    execution_result_json: dict[str, Any] | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    executed_at: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime


class EngineRunResultOut(BaseModel):
    """Response from running the optimization engine."""

    success: bool
    campaign_id: str
    proposals_created: int
    proposals_auto_approved: int
    proposals_queued: int
    guardrail_rejections: int
    method_evaluations: int
    errors: list[str] = []
    details: dict[str, Any] = {}


class CampaignMetricsSnapshotOut(BaseModel):
    """Aggregated metrics snapshot for a campaign."""

    campaign_id: str
    kpis: dict[str, float] = {}
    channel_data: list[dict[str, Any]] = []
    raw_metrics_count: int = 0
    kpi_count: int = 0
    trend_count: int = 0


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class ApproveProposalRequest(BaseModel):
    """Approve or reject a proposal."""

    action: str  # "approve" or "reject"
    approved_by: str = "user"


class UpdateMethodConfigRequest(BaseModel):
    """Update method configuration."""

    is_active: bool | None = None
    cooldown_minutes: int | None = None
    config_json: dict[str, Any] | None = None


class ExecuteProposalRequest(BaseModel):
    """Request to execute a proposal."""

    force: bool = False  # Execute even if not approved (for testing)


# ---------------------------------------------------------------------------
# Executor response schemas
# ---------------------------------------------------------------------------


class ExecutionRecordOut(BaseModel):
    """Single execution result."""

    success: bool
    proposal_id: str
    execution_id: str | None = None
    error: str | None = None
    platform_result: dict[str, Any] | None = None


class BatchExecutionResultOut(BaseModel):
    """Batch execution results."""

    total: int
    succeeded: int
    failed: int
    records: list[ExecutionRecordOut]


# ---------------------------------------------------------------------------
# Verifier response schemas
# ---------------------------------------------------------------------------


class VerificationResultOut(BaseModel):
    """Single verification result."""

    success: bool
    proposal_id: str
    learning_id: str | None = None
    accuracy_score: float | None = None
    error: str | None = None
    details: dict[str, Any] = {}


class BatchVerificationResultOut(BaseModel):
    """Batch verification results."""

    total: int
    verified: int
    pending: int
    failed: int
    records: list[VerificationResultOut]


class OptimizationLearningOut(BaseModel):
    """Learning record response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    campaign_id: uuid.UUID
    proposal_id: uuid.UUID
    method_id: uuid.UUID
    predicted_impact: dict[str, Any]
    actual_impact: dict[str, Any] | None = None
    accuracy_score: float | None = None
    verification_status: str
    verified_at: datetime | None = None
    details_json: dict[str, Any] = {}
    created_at: datetime


# ---------------------------------------------------------------------------
# Monitor response schemas
# ---------------------------------------------------------------------------


class MonitorRunResultOut(BaseModel):
    """Full monitor cycle result."""

    campaign_id: str
    monitor_run_id: str | None = None
    engine_result: EngineRunResultOut | None = None
    execution_result: BatchExecutionResultOut | None = None
    verification_result: BatchVerificationResultOut | None = None
    success: bool = True
    errors: list[str] = []


class MonitorRunOut(BaseModel):
    """Monitor run record."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    campaign_id: uuid.UUID
    status: str
    engine_summary_json: dict[str, Any] = {}
    execution_summary_json: dict[str, Any] = {}
    verification_summary_json: dict[str, Any] = {}
    created_at: datetime

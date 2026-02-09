import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class CampaignCreate(BaseModel):
    name: str
    objective: str
    start_date: date | None = None
    end_date: date | None = None
    target_cac: float | None = None


class CampaignOut(BaseModel):
    id: uuid.UUID
    name: str
    objective: str
    start_date: date | None = None
    end_date: date | None = None
    target_cac: float | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class SnapshotCreate(BaseModel):
    channel: str
    window_start: date | None = None
    window_end: date | None = None
    spend: float = Field(default=0, ge=0)
    impressions: int = Field(default=0, ge=0)
    clicks: int = Field(default=0, ge=0)
    conversions: int = Field(default=0, ge=0)
    revenue: float = Field(default=0, ge=0)


class SnapshotOut(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    channel: str
    window_start: date | None = None
    window_end: date | None = None
    spend: float
    impressions: int
    clicks: int
    conversions: int
    revenue: float
    created_at: datetime

    class Config:
        from_attributes = True


class MeasureRequest(BaseModel):
    window_start: date | None = None
    window_end: date | None = None


class ReportMeta(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    window_start: date | None = None
    window_end: date | None = None
    total_spend: float
    total_impressions: int
    total_clicks: int
    total_conversions: int
    total_revenue: float
    created_at: datetime

    class Config:
        from_attributes = True


class ReportOut(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    window_start: date | None = None
    window_end: date | None = None
    total_spend: float
    total_impressions: int
    total_clicks: int
    total_conversions: int
    total_revenue: float
    metrics_json: dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True


class MeasureResponse(BaseModel):
    report_id: uuid.UUID
    report: dict[str, Any]


class BriefCreate(BaseModel):
    brief: dict[str, Any]


class BriefOut(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    brief_json: dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True


class PlanCreate(BaseModel):
    brief: dict[str, Any]
    total_budget: float = Field(ge=0)
    currency: str = "USD"
    start_date: date | None = None
    end_date: date | None = None


class PlanResponse(BaseModel):
    campaign_plan_id: uuid.UUID
    budget_plan_id: uuid.UUID
    allocations: dict[str, float]
    plan: dict[str, Any]


class OptimizeRequest(BaseModel):
    report_id: uuid.UUID
    budget_plan_id: uuid.UUID


class DecisionResponse(BaseModel):
    decision_id: uuid.UUID
    decision_type: str
    from_allocations: dict[str, float]
    to_allocations: dict[str, float]
    rationale: dict[str, Any]


class CampaignPlanOut(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    budget_plan_id: uuid.UUID
    plan_json: dict[str, Any]
    created_at: datetime
    allocations: dict[str, float] | None = None

    class Config:
        from_attributes = True


class DecisionMeta(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    report_id: uuid.UUID | None = None
    decision_type: str
    created_at: datetime

    class Config:
        from_attributes = True


class DecisionOut(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    report_id: uuid.UUID | None = None
    budget_plan_id: uuid.UUID
    decision_type: str
    from_allocations_json: dict[str, Any]
    to_allocations_json: dict[str, Any]
    rationale_json: dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True


class RunCycleRequest(BaseModel):
    budget_plan_id: uuid.UUID
    window_start: date
    window_end: date
    seed: int


class RunCycleResponse(BaseModel):
    snapshots: list[dict[str, Any]]
    report_id: uuid.UUID
    decision_id: uuid.UUID
    decision_type: str
    allocations_after: dict[str, float]
    metrics_summary: dict[str, Any]


class RunCyclesRequest(BaseModel):
    budget_plan_id: uuid.UUID
    n: int = Field(ge=1, le=52)
    start_date: date
    window_days: int = Field(ge=1, le=31)
    seed: int


class RunCyclesResponse(BaseModel):
    cycles: list[RunCycleResponse]
    final_allocations: dict[str, float]

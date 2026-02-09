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

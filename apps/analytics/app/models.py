import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db import Base


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    target_cac: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    snapshots: Mapped[list["ChannelSnapshot"]] = relationship(back_populates="campaign")
    reports: Mapped[list["MeasurementReport"]] = relationship(back_populates="campaign")
    briefs: Mapped[list["CampaignBrief"]] = relationship(back_populates="campaign")
    budget_plans: Mapped[list["BudgetPlan"]] = relationship(back_populates="campaign")
    campaign_plans: Mapped[list["CampaignPlan"]] = relationship(back_populates="campaign")
    allocation_decisions: Mapped[list["AllocationDecision"]] = relationship(
        back_populates="campaign"
    )


class ChannelSnapshot(Base):
    __tablename__ = "channel_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("campaigns.id"), nullable=False
    )
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    window_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    window_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    spend: Mapped[float] = mapped_column(Numeric, nullable=False, default=0)
    impressions: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    clicks: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    conversions: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    revenue: Mapped[float] = mapped_column(Numeric, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    campaign: Mapped[Campaign] = relationship(back_populates="snapshots")


class MeasurementReport(Base):
    __tablename__ = "measurement_reports"
    __table_args__ = (
        Index("ix_measurement_reports_campaign_created", "campaign_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("campaigns.id"), nullable=False
    )
    window_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    window_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_spend: Mapped[float] = mapped_column(Numeric, nullable=False, default=0)
    total_impressions: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_clicks: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_conversions: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_revenue: Mapped[float] = mapped_column(Numeric, nullable=False, default=0)
    metrics_json: Mapped[dict] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    campaign: Mapped[Campaign] = relationship(back_populates="reports")


class CampaignBrief(Base):
    __tablename__ = "campaign_briefs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    brief_json: Mapped[dict] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    campaign: Mapped[Campaign] = relationship(back_populates="briefs")


class BudgetPlan(Base):
    __tablename__ = "budget_plans"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    total_budget: Mapped[float] = mapped_column(Numeric, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="USD")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    campaign: Mapped[Campaign] = relationship(back_populates="budget_plans")
    channel_budgets: Mapped[list["ChannelBudget"]] = relationship(
        back_populates="budget_plan", cascade="all, delete-orphan"
    )
    campaign_plans: Mapped[list["CampaignPlan"]] = relationship(back_populates="budget_plan")


class ChannelBudget(Base):
    __tablename__ = "channel_budgets"
    __table_args__ = (UniqueConstraint("budget_plan_id", "channel"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    budget_plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("budget_plans.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    allocated_budget: Mapped[float] = mapped_column(Numeric, nullable=False)

    budget_plan: Mapped[BudgetPlan] = relationship(back_populates="channel_budgets")


class CampaignPlan(Base):
    __tablename__ = "campaign_plans"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    budget_plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("budget_plans.id", ondelete="CASCADE"), nullable=False
    )
    plan_json: Mapped[dict] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    campaign: Mapped[Campaign] = relationship(back_populates="campaign_plans")
    budget_plan: Mapped[BudgetPlan] = relationship(back_populates="campaign_plans")


class AllocationDecision(Base):
    __tablename__ = "allocation_decisions"
    __table_args__ = (
        Index("ix_allocation_decisions_campaign_created", "campaign_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    report_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("measurement_reports.id"), nullable=True
    )
    budget_plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("budget_plans.id", ondelete="CASCADE"), nullable=False
    )
    decision_type: Mapped[str] = mapped_column(Text, nullable=False)
    from_allocations_json: Mapped[dict] = mapped_column(
        JSONB().with_variant(JSON, "sqlite"), nullable=False
    )
    to_allocations_json: Mapped[dict] = mapped_column(
        JSONB().with_variant(JSON, "sqlite"), nullable=False
    )
    rationale_json: Mapped[dict] = mapped_column(
        JSONB().with_variant(JSON, "sqlite"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    campaign: Mapped[Campaign] = relationship(back_populates="allocation_decisions")
    report: Mapped["MeasurementReport | None"] = relationship()
    budget_plan: Mapped[BudgetPlan] = relationship()

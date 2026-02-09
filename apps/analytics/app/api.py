import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    AllocationDecision,
    Campaign,
    CampaignBrief,
    CampaignPlan,
    ChannelBudget,
    ChannelSnapshot,
    MeasurementReport,
)
from app.schemas import (
    BriefCreate,
    BriefOut,
    CampaignCreate,
    CampaignOut,
    CampaignPlanOut,
    DecisionMeta,
    DecisionOut,
    DecisionResponse,
    MeasureRequest,
    MeasureResponse,
    OptimizeRequest,
    PlanCreate,
    PlanResponse,
    ReportMeta,
    ReportOut,
    SnapshotCreate,
    SnapshotOut,
)
from app.services.measurement import compute_report
from app.services.strategist import create_plan_from_brief, optimize_from_report

router = APIRouter(tags=["measurement"])


@router.post("/campaigns", response_model=CampaignOut, tags=["campaigns"])
def create_campaign(payload: CampaignCreate, db: Session = Depends(get_db)):
    campaign = Campaign(
        name=payload.name,
        objective=payload.objective,
        start_date=payload.start_date,
        end_date=payload.end_date,
        target_cac=payload.target_cac,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


@router.post(
    "/campaigns/{campaign_id}/snapshots",
    response_model=SnapshotOut,
    tags=["snapshots"],
)
def create_snapshot(campaign_id: uuid.UUID, payload: SnapshotCreate, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    snapshot = ChannelSnapshot(
        campaign_id=campaign_id,
        channel=payload.channel,
        window_start=payload.window_start,
        window_end=payload.window_end,
        spend=payload.spend,
        impressions=payload.impressions,
        clicks=payload.clicks,
        conversions=payload.conversions,
        revenue=payload.revenue,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


@router.post(
    "/campaigns/{campaign_id}/measure",
    response_model=MeasureResponse,
    tags=["reports"],
)
def measure_campaign(
    campaign_id: uuid.UUID, payload: MeasureRequest, db: Session = Depends(get_db)
):
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    report = compute_report(
        db,
        campaign_id=campaign_id,
        window_start=payload.window_start,
        window_end=payload.window_end,
    )
    return MeasureResponse(report_id=report.id, report=report.metrics_json)


@router.get(
    "/campaigns/{campaign_id}/reports",
    response_model=list[ReportMeta],
    tags=["reports"],
)
def list_reports(campaign_id: uuid.UUID, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    reports = (
        db.execute(
            select(MeasurementReport)
            .where(MeasurementReport.campaign_id == campaign_id)
            .order_by(MeasurementReport.created_at.desc())
        )
        .scalars()
        .all()
    )
    return reports


@router.get("/reports/{report_id}", response_model=ReportOut, tags=["reports"])
def get_report(report_id: uuid.UUID, db: Session = Depends(get_db)):
    report = db.get(MeasurementReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.post("/campaigns/{campaign_id}/briefs", response_model=BriefOut, tags=["strategist"])
def create_brief(campaign_id: uuid.UUID, payload: BriefCreate, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if not isinstance(payload.brief, dict):
        raise HTTPException(status_code=422, detail="Brief must be a JSON object")

    brief = CampaignBrief(campaign_id=campaign_id, brief_json=payload.brief)
    db.add(brief)
    db.commit()
    db.refresh(brief)
    return brief


@router.post("/campaigns/{campaign_id}/plan", response_model=PlanResponse, tags=["strategist"])
def create_plan(campaign_id: uuid.UUID, payload: PlanCreate, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if not isinstance(payload.brief, dict):
        raise HTTPException(status_code=422, detail="Brief must be a JSON object")

    result = create_plan_from_brief(
        db=db,
        campaign=campaign,
        brief_json=payload.brief,
        total_budget=Decimal(str(payload.total_budget)),
        currency=payload.currency,
        start_date=payload.start_date,
        end_date=payload.end_date,
    )
    return PlanResponse(
        campaign_plan_id=result.campaign_plan.id,
        budget_plan_id=result.budget_plan.id,
        allocations={k: float(v) for k, v in result.allocations.items()},
        plan=result.campaign_plan.plan_json,
    )


@router.post(
    "/campaigns/{campaign_id}/optimize",
    response_model=DecisionResponse,
    tags=["strategist"],
)
def optimize_campaign(
    campaign_id: uuid.UUID, payload: OptimizeRequest, db: Session = Depends(get_db)
):
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    try:
        result = optimize_from_report(
            db=db,
            campaign_id=campaign_id,
            report_id=payload.report_id,
            budget_plan_id=payload.budget_plan_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return DecisionResponse(
        decision_id=result.decision.id,
        decision_type=result.decision.decision_type,
        from_allocations={k: float(v) for k, v in result.from_allocations.items()},
        to_allocations={k: float(v) for k, v in result.to_allocations.items()},
        rationale=result.decision.rationale_json,
    )


@router.get("/campaigns/{campaign_id}/plan", response_model=CampaignPlanOut, tags=["strategist"])
def get_latest_plan(campaign_id: uuid.UUID, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    plan = (
        db.execute(
            select(CampaignPlan)
            .where(CampaignPlan.campaign_id == campaign_id)
            .order_by(CampaignPlan.created_at.desc())
        )
        .scalars()
        .first()
    )
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")

    allocations = (
        db.execute(select(ChannelBudget).where(ChannelBudget.budget_plan_id == plan.budget_plan_id))
        .scalars()
        .all()
    )
    allocation_map = {entry.channel: float(entry.allocated_budget) for entry in allocations}

    return CampaignPlanOut(
        id=plan.id,
        campaign_id=plan.campaign_id,
        budget_plan_id=plan.budget_plan_id,
        plan_json=plan.plan_json,
        created_at=plan.created_at,
        allocations=allocation_map,
    )


@router.get(
    "/campaigns/{campaign_id}/decisions",
    response_model=list[DecisionMeta],
    tags=["strategist"],
)
def list_decisions(campaign_id: uuid.UUID, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    decisions = (
        db.execute(
            select(AllocationDecision)
            .where(AllocationDecision.campaign_id == campaign_id)
            .order_by(AllocationDecision.created_at.desc())
        )
        .scalars()
        .all()
    )
    return decisions


@router.get("/decisions/{decision_id}", response_model=DecisionOut, tags=["strategist"])
def get_decision(decision_id: uuid.UUID, db: Session = Depends(get_db)):
    decision = db.get(AllocationDecision, decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    return decision

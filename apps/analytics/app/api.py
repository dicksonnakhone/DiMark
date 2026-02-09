import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Campaign, ChannelSnapshot, MeasurementReport
from app.schemas import (
    CampaignCreate,
    CampaignOut,
    MeasureRequest,
    MeasureResponse,
    ReportMeta,
    ReportOut,
    SnapshotCreate,
    SnapshotOut,
)
from app.services.measurement import compute_report

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

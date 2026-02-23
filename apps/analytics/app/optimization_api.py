"""FastAPI router for performance monitoring and optimization endpoints.

Uses sync endpoints with ``get_db`` — matches the existing ``app/api.py`` pattern.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    Campaign,
    DerivedKPI,
    MonitorRun,
    OptimizationLearning,
    OptimizationMethod,
    OptimizationProposal,
    RawMetric,
    TrendIndicator,
)
from app.optimization_schemas import (
    ApproveProposalRequest,
    BatchVerificationResultOut,
    CampaignMetricsSnapshotOut,
    DerivedKPIOut,
    EngineRunResultOut,
    ExecuteProposalRequest,
    ExecutionRecordOut,
    MonitorRunOut,
    MonitorRunResultOut,
    OptimizationLearningOut,
    OptimizationMethodOut,
    OptimizationProposalOut,
    TrendIndicatorOut,
    UpdateMethodConfigRequest,
    VerificationResultOut,
)
from app.services.optimization.engine import DecisionEngine
from app.services.optimization.executor import ActionExecutor
from app.services.optimization.methods import build_default_registry
from app.settings import settings

optimization_router = APIRouter(
    prefix="/api/optimization",
    tags=["optimization"],
)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


@optimization_router.post(
    "/campaigns/{campaign_id}/run",
    response_model=EngineRunResultOut,
)
def run_optimization(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """Trigger the optimization engine for a campaign."""
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    registry = build_default_registry()
    engine = DecisionEngine(registry)
    result = engine.run(db, str(campaign_id))

    return EngineRunResultOut(
        success=result.success,
        campaign_id=result.campaign_id,
        proposals_created=result.proposals_created,
        proposals_auto_approved=result.proposals_auto_approved,
        proposals_queued=result.proposals_queued,
        guardrail_rejections=result.guardrail_rejections,
        method_evaluations=result.method_evaluations,
        errors=result.errors,
        details=result.details,
    )


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@optimization_router.get(
    "/campaigns/{campaign_id}/metrics",
    response_model=CampaignMetricsSnapshotOut,
)
def get_campaign_metrics(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """Get current metrics snapshot for a campaign."""
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    raw_count = db.execute(
        select(RawMetric)
        .where(RawMetric.campaign_id == campaign_id)
    ).scalars().all()

    kpis = db.execute(
        select(DerivedKPI)
        .where(DerivedKPI.campaign_id == campaign_id, DerivedKPI.channel.is_(None))
        .order_by(DerivedKPI.computed_at.desc())
    ).scalars().all()

    trends = db.execute(
        select(TrendIndicator)
        .where(TrendIndicator.campaign_id == campaign_id)
        .order_by(TrendIndicator.computed_at.desc())
    ).scalars().all()

    # Build KPI dict from latest values
    kpi_dict: dict[str, float] = {}
    for kpi in kpis:
        if kpi.kpi_name not in kpi_dict:
            kpi_dict[kpi.kpi_name] = float(kpi.kpi_value)

    # Build per-channel data from per-channel KPIs
    channel_kpis = db.execute(
        select(DerivedKPI)
        .where(DerivedKPI.campaign_id == campaign_id, DerivedKPI.channel.is_not(None))
        .order_by(DerivedKPI.computed_at.desc())
    ).scalars().all()

    channel_data_map: dict[str, dict] = {}
    for kpi in channel_kpis:
        if kpi.channel not in channel_data_map:
            channel_data_map[kpi.channel] = {"channel": kpi.channel, "kpis": {}}
        if kpi.kpi_name not in channel_data_map[kpi.channel]["kpis"]:
            channel_data_map[kpi.channel]["kpis"][kpi.kpi_name] = float(kpi.kpi_value)

    return CampaignMetricsSnapshotOut(
        campaign_id=str(campaign_id),
        kpis=kpi_dict,
        channel_data=list(channel_data_map.values()),
        raw_metrics_count=len(raw_count),
        kpi_count=len(kpis),
        trend_count=len(trends),
    )


# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------


@optimization_router.get(
    "/campaigns/{campaign_id}/kpis",
    response_model=list[DerivedKPIOut],
)
def list_campaign_kpis(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """List derived KPIs for a campaign."""
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    rows = db.execute(
        select(DerivedKPI)
        .where(DerivedKPI.campaign_id == campaign_id)
        .order_by(DerivedKPI.computed_at.desc())
    ).scalars().all()
    return rows


# ---------------------------------------------------------------------------
# Trends
# ---------------------------------------------------------------------------


@optimization_router.get(
    "/campaigns/{campaign_id}/trends",
    response_model=list[TrendIndicatorOut],
)
def list_campaign_trends(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """List trend indicators for a campaign."""
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    rows = db.execute(
        select(TrendIndicator)
        .where(TrendIndicator.campaign_id == campaign_id)
        .order_by(TrendIndicator.computed_at.desc())
    ).scalars().all()
    return rows


# ---------------------------------------------------------------------------
# Proposals
# ---------------------------------------------------------------------------


@optimization_router.get(
    "/campaigns/{campaign_id}/proposals",
    response_model=list[OptimizationProposalOut],
)
def list_campaign_proposals(
    campaign_id: uuid.UUID,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    """List optimization proposals for a campaign, optionally filtered by status."""
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    query = select(OptimizationProposal).where(
        OptimizationProposal.campaign_id == campaign_id
    )
    if status:
        query = query.where(OptimizationProposal.status == status)
    query = query.order_by(OptimizationProposal.created_at.desc())

    rows = db.execute(query).scalars().all()
    return rows


@optimization_router.get(
    "/proposals/{proposal_id}",
    response_model=OptimizationProposalOut,
)
def get_proposal(
    proposal_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """Get a single optimization proposal."""
    proposal = db.get(OptimizationProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return proposal


@optimization_router.post(
    "/proposals/{proposal_id}/approve",
    response_model=OptimizationProposalOut,
)
def approve_proposal(
    proposal_id: uuid.UUID,
    payload: ApproveProposalRequest,
    db: Session = Depends(get_db),
):
    """Approve or reject an optimization proposal."""
    proposal = db.get(OptimizationProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")

    if payload.action == "approve":
        proposal.status = "approved"
        proposal.approved_by = payload.approved_by
        proposal.approved_at = datetime.now(tz=timezone.utc)
    elif payload.action == "reject":
        proposal.status = "rejected"
        proposal.approved_by = payload.approved_by
        proposal.approved_at = datetime.now(tz=timezone.utc)
    else:
        raise HTTPException(
            status_code=422,
            detail="action must be 'approve' or 'reject'",
        )

    db.commit()
    db.refresh(proposal)
    return proposal


# ---------------------------------------------------------------------------
# Methods
# ---------------------------------------------------------------------------


@optimization_router.get(
    "/methods",
    response_model=list[OptimizationMethodOut],
)
def list_methods(
    db: Session = Depends(get_db),
):
    """List all registered optimization methods."""
    rows = db.execute(
        select(OptimizationMethod).order_by(OptimizationMethod.created_at.desc())
    ).scalars().all()
    return rows


@optimization_router.patch(
    "/methods/{method_id}",
    response_model=OptimizationMethodOut,
)
def update_method(
    method_id: uuid.UUID,
    payload: UpdateMethodConfigRequest,
    db: Session = Depends(get_db),
):
    """Update an optimization method's configuration."""
    method = db.get(OptimizationMethod, method_id)
    if method is None:
        raise HTTPException(status_code=404, detail="Method not found")

    if payload.is_active is not None:
        method.is_active = payload.is_active
    if payload.cooldown_minutes is not None:
        method.cooldown_minutes = payload.cooldown_minutes
    if payload.config_json is not None:
        method.config_json = payload.config_json

    db.commit()
    db.refresh(method)
    return method


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------


@optimization_router.post(
    "/proposals/{proposal_id}/execute",
    response_model=ExecutionRecordOut,
)
def execute_proposal(
    proposal_id: uuid.UUID,
    payload: ExecuteProposalRequest | None = None,
    db: Session = Depends(get_db),
):
    """Execute an approved optimization proposal via platform adapters."""
    proposal = db.get(OptimizationProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")

    force = payload.force if payload else False
    if not force and proposal.status not in ("approved", "auto_approved"):
        raise HTTPException(
            status_code=400,
            detail=f"Proposal must be approved to execute (current: {proposal.status})",
        )

    executor = ActionExecutor(dry_run=settings.USE_DRY_RUN_EXECUTION)
    record = executor.execute_proposal(db, proposal_id, force=force)

    return ExecutionRecordOut(
        success=record.success,
        proposal_id=record.proposal_id,
        execution_id=record.execution_id,
        error=record.error,
        platform_result=record.platform_result,
    )


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------


@optimization_router.post(
    "/proposals/{proposal_id}/verify",
    response_model=VerificationResultOut,
)
def verify_proposal(
    proposal_id: uuid.UUID,
    verification_window_hours: int = 24,
    db: Session = Depends(get_db),
):
    """Verify outcomes of an executed proposal."""
    from app.services.optimization.verifier import OutcomeVerifier

    proposal = db.get(OptimizationProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")

    verifier = OutcomeVerifier()
    result = verifier.verify_proposal(db, proposal_id, verification_window_hours)

    return VerificationResultOut(
        success=result.success,
        proposal_id=result.proposal_id,
        learning_id=result.learning_id,
        accuracy_score=result.accuracy_score,
        error=result.error,
        details=result.details,
    )


# ---------------------------------------------------------------------------
# Learnings
# ---------------------------------------------------------------------------


@optimization_router.get(
    "/campaigns/{campaign_id}/learnings",
    response_model=list[OptimizationLearningOut],
)
def list_campaign_learnings(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """List all learning records for a campaign."""
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    rows = db.execute(
        select(OptimizationLearning)
        .where(OptimizationLearning.campaign_id == campaign_id)
        .order_by(OptimizationLearning.created_at.desc())
    ).scalars().all()
    return rows


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------


@optimization_router.post(
    "/campaigns/{campaign_id}/monitor",
    response_model=MonitorRunResultOut,
)
def run_monitor(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """Run the full optimization monitor cycle for a campaign."""
    from app.services.optimization.monitor import OptimizationMonitor

    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    monitor = OptimizationMonitor(dry_run=settings.USE_DRY_RUN_EXECUTION)
    result = monitor.run_cycle(db, campaign_id)

    engine_out = None
    if result.engine_result is not None:
        er = result.engine_result
        engine_out = {
            "success": er.success,
            "campaign_id": er.campaign_id,
            "proposals_created": er.proposals_created,
            "proposals_auto_approved": er.proposals_auto_approved,
            "proposals_queued": er.proposals_queued,
            "guardrail_rejections": er.guardrail_rejections,
            "method_evaluations": er.method_evaluations,
            "errors": er.errors,
            "details": er.details,
        }

    exec_out = None
    if result.execution_result is not None:
        bx = result.execution_result
        exec_out = {
            "total": bx.total,
            "succeeded": bx.succeeded,
            "failed": bx.failed,
            "records": [
                {
                    "success": r.success,
                    "proposal_id": r.proposal_id,
                    "execution_id": r.execution_id,
                    "error": r.error,
                    "platform_result": r.platform_result,
                }
                for r in bx.records
            ],
        }

    verif_out = None
    if result.verification_result is not None:
        bv = result.verification_result
        verif_out = {
            "total": bv.total,
            "verified": bv.verified,
            "pending": bv.pending,
            "failed": bv.failed,
            "records": [
                {
                    "success": r.success,
                    "proposal_id": r.proposal_id,
                    "learning_id": r.learning_id,
                    "accuracy_score": r.accuracy_score,
                    "error": r.error,
                    "details": r.details,
                }
                for r in bv.records
            ],
        }

    return MonitorRunResultOut(
        campaign_id=result.campaign_id,
        monitor_run_id=result.monitor_run_id,
        engine_result=engine_out,
        execution_result=exec_out,
        verification_result=verif_out,
        success=result.success,
        errors=result.errors,
    )


@optimization_router.get(
    "/campaigns/{campaign_id}/monitor-runs",
    response_model=list[MonitorRunOut],
)
def list_monitor_runs(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """List all monitor runs for a campaign."""
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    rows = db.execute(
        select(MonitorRun)
        .where(MonitorRun.campaign_id == campaign_id)
        .order_by(MonitorRun.created_at.desc())
    ).scalars().all()
    return rows

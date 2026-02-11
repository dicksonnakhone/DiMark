from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    BudgetPlan,
    Campaign,
    CampaignBrief,
    CampaignPlan,
    ChannelBudget,
    ChannelSnapshot,
)
from app.services.execution import SimulatedExecutionAgent
from app.services.experimentation import run_experiment_window
from app.services.measurement import compute_report
from app.services.strategist import optimize_from_report


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def run_cycle(
    db: Session,
    campaign_id,
    budget_plan_id,
    window_start: date,
    window_end: date,
    seed: int,
) -> dict[str, Any]:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise ValueError("Campaign not found")

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
        raise ValueError("Campaign plan not found")

    brief = (
        db.execute(
            select(CampaignBrief)
            .where(CampaignBrief.campaign_id == campaign_id)
            .order_by(CampaignBrief.created_at.desc())
        )
        .scalars()
        .first()
    )

    budget_plan = db.get(BudgetPlan, budget_plan_id)
    if budget_plan is None:
        raise ValueError("Budget plan not found")

    allocations_rows = (
        db.execute(
            select(ChannelBudget)
            .where(ChannelBudget.budget_plan_id == budget_plan_id)
            .order_by(ChannelBudget.channel)
        )
        .scalars()
        .all()
    )
    allocations = {row.channel: _to_decimal(row.allocated_budget) for row in allocations_rows}

    experiment_payload = run_experiment_window(
        db=db,
        campaign_id=campaign_id,
        budget_plan_id=budget_plan_id,
        window_start=window_start,
        window_end=window_end,
        seed=seed,
        plan_json=plan.plan_json,
        brief_json=brief.brief_json if brief else None,
    )
    if experiment_payload is not None:
        snapshots = experiment_payload["aggregated_snapshots"]
        experiment_info = {
            "experiment_id": experiment_payload["experiment"].id,
            "status": experiment_payload["experiment"].status,
            "result_id": experiment_payload["result"].id,
            "analysis": experiment_payload["analysis"],
        }
    else:
        agent = SimulatedExecutionAgent()
        snapshots = agent.run_window(
            campaign=campaign,
            plan_json=plan.plan_json,
            brief_json=brief.brief_json if brief else None,
            budget_plan=budget_plan,
            allocations=allocations,
            window_start=window_start,
            window_end=window_end,
            seed=seed,
        )
        experiment_info = None

    for snapshot in snapshots:
        db.add(
            ChannelSnapshot(
                campaign_id=campaign_id,
                channel=snapshot["channel"],
                window_start=snapshot["window_start"],
                window_end=snapshot["window_end"],
                spend=snapshot["spend"],
                impressions=snapshot["impressions"],
                clicks=snapshot["clicks"],
                conversions=snapshot["conversions"],
                revenue=snapshot["revenue"],
            )
        )
    db.commit()

    report = compute_report(
        db, campaign_id=campaign_id, window_start=window_start, window_end=window_end
    )

    decision_result = optimize_from_report(
        db,
        campaign_id=campaign_id,
        report_id=report.id,
        budget_plan_id=budget_plan_id,
    )

    totals = report.metrics_json.get("totals", {})
    metrics_summary = {
        "total_spend": totals.get("spend"),
        "total_conversions": totals.get("conversions"),
        "cac": report.metrics_json.get("kpis", {}).get("cac"),
        "roas": report.metrics_json.get("kpis", {}).get("roas"),
    }

    allocations_after = {k: float(v) for k, v in decision_result.to_allocations.items()}

    return {
        "snapshots": snapshots,
        "report_id": report.id,
        "decision_id": decision_result.decision.id,
        "decision_type": decision_result.decision.decision_type,
        "allocations_after": allocations_after,
        "metrics_summary": metrics_summary,
        "experiment": experiment_info,
    }


def run_cycles(
    db: Session,
    campaign_id,
    budget_plan_id,
    n: int,
    start_date: date,
    window_days: int,
    seed: int,
) -> dict[str, Any]:
    cycles = []
    current_start = start_date
    for i in range(n):
        current_end = current_start + timedelta(days=window_days - 1)
        cycles.append(
            run_cycle(
                db,
                campaign_id=campaign_id,
                budget_plan_id=budget_plan_id,
                window_start=current_start,
                window_end=current_end,
                seed=seed + i,
            )
        )
        current_start = current_end + timedelta(days=1)

    allocations_after = cycles[-1]["allocations_after"] if cycles else {}
    return {"cycles": cycles, "final_allocations": allocations_after}

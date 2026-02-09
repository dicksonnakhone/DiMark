from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AllocationDecision,
    BudgetPlan,
    Campaign,
    CampaignBrief,
    CampaignPlan,
    ChannelBudget,
    MeasurementReport,
)
from app.services.allocation_policy import compute_allocation_decision


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _normalize_allocations(
    allocations: dict[str, Decimal], total_budget: Decimal
) -> dict[str, Decimal]:
    if not allocations:
        return allocations
    rounded = {k: v.quantize(Decimal("0.01")) for k, v in allocations.items()}
    remainder = total_budget - sum(rounded.values())
    largest = max(rounded.items(), key=lambda item: (item[1], item[0]))[0]
    rounded[largest] = (rounded[largest] + remainder).quantize(Decimal("0.01"))
    return rounded


def _allocation_from_weights(
    total_budget: Decimal, weights: dict[str, Decimal]
) -> dict[str, Decimal]:
    total_weight = sum(weights.values())
    allocations = {
        channel: (total_budget * weight / total_weight) if total_weight else Decimal("0")
        for channel, weight in weights.items()
    }
    return _normalize_allocations(allocations, total_budget)


@dataclass(frozen=True)
class PlanResult:
    campaign_plan: CampaignPlan
    budget_plan: BudgetPlan
    allocations: dict[str, Decimal]


def create_plan_from_brief(
    db: Session,
    campaign: Campaign,
    brief_json: dict[str, Any],
    total_budget: Decimal,
    currency: str,
    start_date: date | None,
    end_date: date | None,
) -> PlanResult:
    brief = CampaignBrief(campaign_id=campaign.id, brief_json=brief_json)
    db.add(brief)

    budget_plan = BudgetPlan(
        campaign_id=campaign.id,
        total_budget=total_budget,
        currency=currency,
        start_date=start_date,
        end_date=end_date,
    )
    db.add(budget_plan)
    db.flush()

    objective = campaign.objective
    channels_allowed = brief_json.get("channels_allowed") or []
    channels_preferred = set(brief_json.get("channels_preferred") or [])

    if objective in {"paid_conversions", "leads"}:
        base_weights = {
            "google": Decimal("0.45"),
            "linkedin": Decimal("0.35"),
            "content": Decimal("0.20"),
        }
    elif objective == "installs":
        base_weights = {
            "meta": Decimal("0.45"),
            "tiktok": Decimal("0.35"),
            "influencer": Decimal("0.20"),
        }
    elif objective == "revenue":
        base_weights = {
            "google": Decimal("0.45"),
            "meta": Decimal("0.35"),
            "youtube": Decimal("0.20"),
        }
    else:
        base_weights = {"meta": Decimal("0.5"), "google": Decimal("0.5")}

    if channels_allowed:
        base_weights = {c: base_weights.get(c, Decimal("1")) for c in channels_allowed}

    weights = defaultdict(lambda: Decimal("1"), base_weights)
    for channel in list(weights.keys()):
        if channel in channels_preferred:
            weights[channel] = weights[channel] * Decimal("1.5")

    allocations = _allocation_from_weights(total_budget, dict(weights))

    for channel, allocated in allocations.items():
        db.add(
            ChannelBudget(
                budget_plan_id=budget_plan.id,
                channel=channel,
                allocated_budget=allocated,
            )
        )

    plan_json = {
        "objective": objective,
        "target_cac": str(campaign.target_cac) if campaign.target_cac else None,
        "channels": list(allocations.keys()),
        "channels_preferred": list(channels_preferred),
        "pacing": None,
    }

    if start_date and end_date and end_date >= start_date:
        days = (end_date - start_date).days + 1
        if days > 0:
            plan_json["pacing"] = {"days": days, "daily_budget": str(total_budget / days)}

    campaign_plan = CampaignPlan(
        campaign_id=campaign.id,
        budget_plan_id=budget_plan.id,
        plan_json=plan_json,
    )
    db.add(campaign_plan)
    db.commit()
    db.refresh(campaign_plan)
    db.refresh(budget_plan)
    return PlanResult(campaign_plan=campaign_plan, budget_plan=budget_plan, allocations=allocations)


@dataclass(frozen=True)
class OptimizeResult:
    decision: AllocationDecision
    from_allocations: dict[str, Decimal]
    to_allocations: dict[str, Decimal]


def optimize_from_report(
    db: Session,
    campaign_id,
    report_id,
    budget_plan_id,
) -> OptimizeResult:
    campaign = db.get(Campaign, campaign_id)
    report = db.get(MeasurementReport, report_id)
    budget_plan = db.get(BudgetPlan, budget_plan_id)
    if campaign is None or report is None or budget_plan is None:
        raise ValueError("Missing campaign, report, or budget plan")

    channel_budgets = (
        db.execute(select(ChannelBudget).where(ChannelBudget.budget_plan_id == budget_plan_id))
        .scalars()
        .all()
    )

    current_allocations = {
        entry.channel: _to_decimal(entry.allocated_budget) for entry in channel_budgets
    }

    decision = compute_allocation_decision(
        report.metrics_json,
        current_allocations,
        {
            "objective": campaign.objective,
            "target_cac": campaign.target_cac,
            "max_delta_pct_per_decision": 0.20,
            "exploration_floor_pct": 0.05,
        },
    )

    for entry in channel_budgets:
        if entry.channel in decision.new_allocations:
            entry.allocated_budget = decision.new_allocations[entry.channel]

    allocation_decision = AllocationDecision(
        campaign_id=campaign.id,
        report_id=report.id,
        budget_plan_id=budget_plan.id,
        decision_type=decision.decision_type,
        from_allocations_json={k: str(v) for k, v in current_allocations.items()},
        to_allocations_json={k: str(v) for k, v in decision.new_allocations.items()},
        rationale_json=decision.rationale,
    )
    db.add(allocation_decision)
    db.commit()
    db.refresh(allocation_decision)

    return OptimizeResult(
        decision=allocation_decision,
        from_allocations=current_allocations,
        to_allocations=decision.new_allocations,
    )

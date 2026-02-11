from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    BudgetPlan,
    Campaign,
    ChannelBudget,
    Experiment,
    ExperimentResult,
    ExperimentVariant,
)
from app.services.experimentation.evaluator import evaluate_if_ready
from app.services.experimentation.splitter import split_allocations
from app.services.execution import SimulatedExecutionAgent


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _stable_hash_int(value: str) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _safe_div(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == 0:
        return None
    return numerator / denominator


def compute_kpis(totals: dict[str, Any]) -> dict[str, Any]:
    spend = _to_decimal(totals.get("spend", 0))
    impressions = Decimal(str(totals.get("impressions", 0)))
    clicks = Decimal(str(totals.get("clicks", 0)))
    conversions = Decimal(str(totals.get("conversions", 0)))
    revenue = _to_decimal(totals.get("revenue", 0))

    return {
        "ctr": float(_safe_div(clicks, impressions)) if impressions > 0 else None,
        "cvr": float(_safe_div(conversions, clicks)) if clicks > 0 else None,
        "cpc": float(_safe_div(spend, clicks)) if clicks > 0 else None,
        "cpm": float(_safe_div(spend * Decimal("1000"), impressions))
        if impressions > 0
        else None,
        "cac": float(_safe_div(spend, conversions)) if conversions > 0 else None,
        "roas": float(_safe_div(revenue, spend)) if spend > 0 else None,
        "conversions_per_dollar": float(_safe_div(conversions, spend)) if spend > 0 else None,
    }


def create_experiment(
    db: Session,
    campaign_id,
    experiment_type: str,
    primary_metric: str,
    variants: list[dict[str, Any]],
    hypothesis: str | None = None,
    min_sample_conversions: int = 20,
    confidence: Decimal = Decimal("0.95"),
) -> Experiment:
    total_share = sum(_to_decimal(v["traffic_share"]) for v in variants)
    if abs(total_share - Decimal("1")) > Decimal("0.0001"):
        raise ValueError("Traffic shares must sum to 1.0")

    experiment = Experiment(
        campaign_id=campaign_id,
        experiment_type=experiment_type,
        status="draft",
        hypothesis=hypothesis,
        primary_metric=primary_metric,
        min_sample_conversions=min_sample_conversions,
        confidence=confidence,
    )
    db.add(experiment)
    db.flush()

    for variant in variants:
        db.add(
            ExperimentVariant(
                experiment_id=experiment.id,
                name=variant["name"],
                traffic_share=_to_decimal(variant["traffic_share"]),
                variant_json=variant["variant"],
            )
        )

    db.commit()
    db.refresh(experiment)
    return experiment


def start_experiment(db: Session, experiment_id) -> Experiment:
    experiment = db.get(Experiment, experiment_id)
    if experiment is None:
        raise ValueError("Experiment not found")

    running = (
        db.execute(
            select(Experiment)
            .where(Experiment.campaign_id == experiment.campaign_id)
            .where(Experiment.status == "running")
        )
        .scalars()
        .first()
    )
    if running is not None:
        raise RuntimeError("Experiment already running")

    experiment.status = "running"
    db.commit()
    db.refresh(experiment)
    return experiment


def stop_experiment(db: Session, experiment_id, reason: str | None = None) -> Experiment:
    experiment = db.get(Experiment, experiment_id)
    if experiment is None:
        raise ValueError("Experiment not found")

    experiment.status = "stopped"
    db.commit()
    if reason:
        result = (
            db.execute(
                select(ExperimentResult)
                .where(ExperimentResult.experiment_id == experiment_id)
                .order_by(ExperimentResult.window_start.desc())
            )
            .scalars()
            .first()
        )
        if result is not None:
            analysis = result.analysis_json or {}
            analysis["stop_reason"] = reason
            result.analysis_json = analysis
            db.commit()
    return experiment


def run_experiment_window(
    db: Session,
    campaign_id,
    budget_plan_id,
    window_start: date,
    window_end: date,
    seed: int,
    plan_json: dict[str, Any] | None = None,
    brief_json: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    experiment = (
        db.execute(
            select(Experiment)
            .where(Experiment.campaign_id == campaign_id)
            .where(Experiment.status == "running")
        )
        .scalars()
        .first()
    )
    if experiment is None:
        return None

    campaign = db.get(Campaign, campaign_id)
    budget_plan = db.get(BudgetPlan, budget_plan_id)
    if campaign is None or budget_plan is None:
        raise ValueError("Campaign or budget plan not found")

    variants = (
        db.execute(
            select(ExperimentVariant).where(ExperimentVariant.experiment_id == experiment.id)
        )
        .scalars()
        .all()
    )
    variant_shares = {variant.name: _to_decimal(variant.traffic_share) for variant in variants}

    channel_budgets = {
        row.channel: _to_decimal(row.allocated_budget)
        for row in db.execute(
            select(ChannelBudget).where(ChannelBudget.budget_plan_id == budget_plan_id)
        ).scalars()
    }

    per_variant_allocations = split_allocations(channel_budgets, variant_shares)

    agent = SimulatedExecutionAgent()
    variant_results: dict[str, Any] = {}
    aggregated: dict[str, dict[str, Decimal]] = {}

    for variant in variants:
        variant_payload = variant.variant_json or {}
        overrides = variant_payload.get("sim_overrides", {})
        variant_seed = seed + _stable_hash_int(variant.name) * 1000
        snapshots = agent.run_window(
            campaign=campaign,
            plan_json=plan_json,
            brief_json=brief_json,
            budget_plan=budget_plan,
            allocations=per_variant_allocations[variant.name],
            window_start=window_start,
            window_end=window_end,
            seed=variant_seed,
            variant_name=variant.name,
            sim_overrides=overrides,
        )

        totals = {
            "spend": Decimal("0"),
            "impressions": 0,
            "clicks": 0,
            "conversions": 0,
            "revenue": Decimal("0"),
        }
        for snapshot in snapshots:
            totals["spend"] += _to_decimal(snapshot["spend"])
            totals["impressions"] += int(snapshot["impressions"])
            totals["clicks"] += int(snapshot["clicks"])
            totals["conversions"] += int(snapshot["conversions"])
            totals["revenue"] += _to_decimal(snapshot["revenue"])

            channel = snapshot["channel"]
            bucket = aggregated.setdefault(
                channel,
                {
                    "spend": Decimal("0"),
                    "impressions": 0,
                    "clicks": 0,
                    "conversions": 0,
                    "revenue": Decimal("0"),
                },
            )
            bucket["spend"] += _to_decimal(snapshot["spend"])
            bucket["impressions"] += int(snapshot["impressions"])
            bucket["clicks"] += int(snapshot["clicks"])
            bucket["conversions"] += int(snapshot["conversions"])
            bucket["revenue"] += _to_decimal(snapshot["revenue"])

        variant_results[variant.name] = {
            "totals": {
                "spend": float(totals["spend"]),
                "impressions": totals["impressions"],
                "clicks": totals["clicks"],
                "conversions": totals["conversions"],
                "revenue": float(totals["revenue"]),
            },
            "kpis": compute_kpis(totals),
        }

    aggregated_snapshots = [
        {
            "channel": channel,
            "window_start": window_start,
            "window_end": window_end,
            "spend": values["spend"].quantize(Decimal("0.01")),
            "impressions": values["impressions"],
            "clicks": values["clicks"],
            "conversions": values["conversions"],
            "revenue": values["revenue"].quantize(Decimal("0.01")),
        }
        for channel, values in sorted(aggregated.items())
    ]

    result = ExperimentResult(
        experiment_id=experiment.id,
        window_start=window_start,
        window_end=window_end,
        results_json={
            "variants": variant_results,
            "allocations": {
                name: {channel: str(value) for channel, value in alloc.items()}
                for name, alloc in per_variant_allocations.items()
            },
        },
    )
    db.add(result)
    db.commit()
    db.refresh(result)

    analysis = evaluate_if_ready(db, experiment.id)
    db.refresh(experiment)

    return {
        "experiment": experiment,
        "result": result,
        "analysis": analysis,
        "aggregated_snapshots": aggregated_snapshots,
    }

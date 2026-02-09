from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _safe_div(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _normalize_allocations(
    allocations: dict[str, Decimal], total_budget: Decimal
) -> dict[str, Decimal]:
    rounded = {k: _quantize(v) for k, v in allocations.items()}
    current_total = sum(rounded.values())
    remainder = total_budget - current_total
    if rounded:
        largest = max(rounded.items(), key=lambda item: (item[1], item[0]))[0]
        rounded[largest] = _quantize(rounded[largest] + remainder)
    return rounded


@dataclass(frozen=True)
class AllocationDecisionResult:
    decision_type: str
    new_allocations: dict[str, Decimal]
    rationale: dict[str, Any]


def compute_allocation_decision(
    report: dict[str, Any],
    current_allocations: dict[str, Decimal],
    config: dict[str, Any],
) -> AllocationDecisionResult:
    total_budget = sum(current_allocations.values())
    max_delta_pct = Decimal(str(config.get("max_delta_pct_per_decision", 0.20)))
    exploration_floor_pct = Decimal(str(config.get("exploration_floor_pct", 0.05)))
    objective = config.get("objective", "paid_conversions")
    target_cac = config.get("target_cac")

    totals = report.get("totals", {})
    total_spend = _to_decimal(totals.get("spend", 0))
    total_conversions = _to_decimal(totals.get("conversions", 0))

    if total_spend == 0 or total_conversions < Decimal("5"):
        rationale = {
            "rule": "insufficient_data",
            "total_spend": str(total_spend),
            "total_conversions": str(total_conversions),
        }
        return AllocationDecisionResult("hold", current_allocations, rationale)

    by_channel = report.get("by_channel", [])
    channel_metrics: dict[str, dict[str, Any]] = {}
    for entry in by_channel:
        channel = entry.get("channel")
        if channel is None:
            continue
        totals_entry = entry.get("totals", {})
        kpis_entry = entry.get("kpis", {})
        channel_metrics[channel] = {
            "spend": _to_decimal(totals_entry.get("spend", 0)),
            "conversions": _to_decimal(totals_entry.get("conversions", 0)),
            "cac": kpis_entry.get("cac"),
            "roas": kpis_entry.get("roas"),
            "efficiency_index": kpis_entry.get("efficiency_index"),
        }

    metrics_snapshot = {
        channel: {
            "spend": str(metrics["spend"]),
            "conversions": str(metrics["conversions"]),
            "cac": metrics["cac"],
            "roas": metrics["roas"],
            "efficiency_index": metrics["efficiency_index"],
        }
        for channel, metrics in channel_metrics.items()
    }

    active_channels = [
        channel
        for channel, budget in current_allocations.items()
        if budget > 0 and channel in channel_metrics
    ]

    min_pause_spend = max(total_budget * Decimal("0.10"), Decimal("200"))
    pause_candidates = [
        channel
        for channel in active_channels
        if channel_metrics[channel]["spend"] >= min_pause_spend
        and channel_metrics[channel]["conversions"] == 0
    ]

    pause_channels: set[str] = set()
    if pause_candidates and len(active_channels) - len(pause_candidates) >= 2:
        pause_channels = set(pause_candidates)

    def score_channel(channel: str) -> Decimal:
        metrics = channel_metrics[channel]
        efficiency = metrics["efficiency_index"]
        efficiency_score = Decimal(str(efficiency)) if efficiency is not None else Decimal("0")
        if objective == "revenue":
            roas = metrics["roas"]
            roas_score = Decimal(str(roas)) if roas is not None else Decimal("0")
            return roas_score + efficiency_score
        cac = metrics["cac"]
        if cac is None or cac == 0:
            return efficiency_score
        return efficiency_score + (Decimal("1") / Decimal(str(cac)))

    ranked_channels = sorted(
        active_channels,
        key=lambda c: (score_channel(c), c),
        reverse=True,
    )

    if not ranked_channels:
        return AllocationDecisionResult("hold", current_allocations, {"rule": "no_active"})

    tier_size = max(1, len(ranked_channels) // 4)
    top_tier = ranked_channels[:tier_size]
    bottom_tier = ranked_channels[-tier_size:]

    allocations = {k: v for k, v in current_allocations.items()}
    for channel in pause_channels:
        allocations[channel] = Decimal("0")

    exploration_floor = total_budget * exploration_floor_pct
    reducible: dict[str, Decimal] = {}
    for channel in bottom_tier:
        if channel in pause_channels:
            continue
        current = allocations[channel]
        floor = exploration_floor if current > 0 else Decimal("0")
        max_reduce = current * max_delta_pct
        reducible[channel] = max(Decimal("0"), min(max_reduce, current - floor))

    increasable: dict[str, Decimal] = {}
    for channel in top_tier:
        current = allocations[channel]
        max_increase = current * max_delta_pct
        increasable[channel] = max_increase

    total_reducible = sum(reducible.values())
    total_increasable = sum(increasable.values())
    move_amount = min(total_budget * Decimal("0.10"), total_reducible, total_increasable)

    rationale = {
        "objective": objective,
        "target_cac": str(target_cac) if target_cac is not None else None,
        "totals": {"spend": str(total_spend), "conversions": str(total_conversions)},
        "metrics_snapshot": metrics_snapshot,
        "ranked_channels": ranked_channels,
        "top_tier": top_tier,
        "bottom_tier": bottom_tier,
        "pause_rule_triggered": list(pause_channels),
        "move_amount": str(move_amount),
    }

    if move_amount == 0 and not pause_channels:
        return AllocationDecisionResult("hold", current_allocations, rationale)

    if total_reducible > 0:
        for channel, reducible_amount in reducible.items():
            delta = (reducible_amount / total_reducible) * move_amount
            allocations[channel] -= delta

    if total_increasable > 0:
        for channel, increase_amount in increasable.items():
            delta = (increase_amount / total_increasable) * move_amount
            allocations[channel] += delta

    if pause_channels:
        decision_type = "pause_channel"
    else:
        decision_type = "rebalance"

    normalized = _normalize_allocations(allocations, total_budget)
    rationale["final_allocations"] = {k: str(v) for k, v in normalized.items()}

    return AllocationDecisionResult(decision_type, normalized, rationale)

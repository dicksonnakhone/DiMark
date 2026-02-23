"""Budget reallocation method.

Proactively shifts budget from low-performing channels to high-performing
channels when the efficiency spread exceeds a threshold.
"""

from __future__ import annotations

from app.services.optimization.methods.base import (
    BaseOptimizationMethod,
    MethodContext,
    MethodEvaluation,
)

# Defaults
DEFAULT_EFFICIENCY_SPREAD_THRESHOLD = 0.20  # 20 % spread between best/worst
DEFAULT_MIN_CHANNELS = 2  # Need at least 2 channels to rebalance


class BudgetReallocationMethod(BaseOptimizationMethod):
    """Proactive method that shifts budget based on efficiency index spread."""

    name = "budget_reallocation"
    description = "Shift budget from underperforming to top-performing channels"
    method_type = "proactive"

    def __init__(
        self,
        *,
        efficiency_spread_threshold: float = DEFAULT_EFFICIENCY_SPREAD_THRESHOLD,
        min_channels: int = DEFAULT_MIN_CHANNELS,
    ) -> None:
        self.efficiency_spread_threshold = efficiency_spread_threshold
        self.min_channels = min_channels

    # ------------------------------------------------------------------

    def check_preconditions(self, ctx: MethodContext) -> tuple[bool, str]:
        if len(ctx.channel_data) < self.min_channels:
            return False, (
                f"Need at least {self.min_channels} channels, "
                f"got {len(ctx.channel_data)}"
            )
        if not ctx.current_allocations:
            return False, "No current budget allocations available"
        return True, ""

    def evaluate(self, ctx: MethodContext) -> MethodEvaluation | None:
        # Score each channel using efficiency_index (mirrors allocation_policy.py)
        scored: list[dict] = []
        for ch in ctx.channel_data:
            channel_name = ch.get("channel", "")
            kpis = ch.get("kpis", {})
            efficiency = kpis.get("efficiency_index")
            if efficiency is None:
                continue
            scored.append(
                {
                    "channel": channel_name,
                    "efficiency_index": float(efficiency),
                    "cac": kpis.get("cac") or kpis.get("cpa"),
                    "roas": kpis.get("roas"),
                }
            )

        if len(scored) < self.min_channels:
            return None

        scored.sort(key=lambda x: x["efficiency_index"], reverse=True)
        best = scored[0]
        worst = scored[-1]

        spread = best["efficiency_index"] - worst["efficiency_index"]
        if best["efficiency_index"] > 0:
            relative_spread = spread / best["efficiency_index"]
        else:
            relative_spread = 0.0

        if relative_spread < self.efficiency_spread_threshold:
            return None

        # Determine top-tier and bottom-tier (quartile split, min 1 each)
        tier_size = max(1, len(scored) // 4)
        top_tier = [s["channel"] for s in scored[:tier_size]]
        bottom_tier = [s["channel"] for s in scored[-tier_size:]]

        total_budget = sum(ctx.current_allocations.values())
        if total_budget <= 0:
            return None

        # Move up to 10 % of total budget from bottom to top
        max_move_pct = 0.10
        move_amount = round(total_budget * max_move_pct, 2)

        new_allocations: dict[str, float] = dict(ctx.current_allocations)
        reduction_per_channel = round(move_amount / len(bottom_tier), 2) if bottom_tier else 0
        increase_per_channel = round(move_amount / len(top_tier), 2) if top_tier else 0

        for ch_name in bottom_tier:
            current = new_allocations.get(ch_name, 0.0)
            new_allocations[ch_name] = round(max(0, current - reduction_per_channel), 2)

        for ch_name in top_tier:
            current = new_allocations.get(ch_name, 0.0)
            new_allocations[ch_name] = round(current + increase_per_channel, 2)

        # Confidence scales with spread magnitude
        confidence = min(0.90, 0.5 + relative_spread)

        return MethodEvaluation(
            should_fire=True,
            confidence=round(confidence, 4),
            priority=5,
            action_type="budget_reallocation",
            action_payload={
                "new_allocations": new_allocations,
                "top_tier": top_tier,
                "bottom_tier": bottom_tier,
                "move_amount": move_amount,
            },
            reasoning=(
                f"Efficiency spread of {relative_spread:.0%} between best "
                f"({best['channel']}) and worst ({worst['channel']}) channels "
                f"exceeds {self.efficiency_spread_threshold:.0%} threshold. "
                f"Proposing to shift ${move_amount:.2f} from bottom to top tier."
            ),
            trigger_data={
                "scored_channels": scored,
                "relative_spread": round(relative_spread, 4),
                "best_channel": best,
                "worst_channel": worst,
            },
        )

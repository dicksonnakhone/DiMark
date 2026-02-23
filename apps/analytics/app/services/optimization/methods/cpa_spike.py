"""CPA Spike detection method.

Fires when a channel's CPA increases significantly vs its baseline,
proposing a budget reduction on the affected channel.
"""

from __future__ import annotations

from app.services.optimization.methods.base import (
    BaseOptimizationMethod,
    MethodContext,
    MethodEvaluation,
)

# Defaults (can be overridden via method config)
DEFAULT_CPA_SPIKE_THRESHOLD = 0.30  # 30 % increase
DEFAULT_MIN_CHANNEL_SPEND = 100.0  # $100 minimum spend to qualify
DEFAULT_BUDGET_REDUCTION_PCT = 0.20  # reduce by 20 %


class CPASpikeMethod(BaseOptimizationMethod):
    """Reactive method that detects CPA spikes and proposes budget cuts."""

    name = "cpa_spike"
    description = "Detect CPA spikes and reduce budget on affected channels"
    method_type = "reactive"

    def __init__(
        self,
        *,
        spike_threshold: float = DEFAULT_CPA_SPIKE_THRESHOLD,
        min_channel_spend: float = DEFAULT_MIN_CHANNEL_SPEND,
        budget_reduction_pct: float = DEFAULT_BUDGET_REDUCTION_PCT,
    ) -> None:
        self.spike_threshold = spike_threshold
        self.min_channel_spend = min_channel_spend
        self.budget_reduction_pct = budget_reduction_pct

    # ------------------------------------------------------------------

    def check_preconditions(self, ctx: MethodContext) -> tuple[bool, str]:
        if not ctx.channel_data:
            return False, "No channel data available"
        if not ctx.kpis.get("cpa"):
            return False, "Campaign-level CPA not available"
        return True, ""

    def evaluate(self, ctx: MethodContext) -> MethodEvaluation | None:
        campaign_cpa = ctx.kpis.get("cpa", 0.0)
        if campaign_cpa <= 0:
            return None

        affected_channels: list[dict] = []
        for ch in ctx.channel_data:
            channel_name = ch.get("channel", "")
            channel_cpa = ch.get("kpis", {}).get("cpa") or ch.get("kpis", {}).get("cac")
            channel_spend = ch.get("totals", {}).get("spend", 0.0)

            if channel_cpa is None or channel_spend < self.min_channel_spend:
                continue

            # Look at trend data for the channel's CPA
            previous_cpa = self._get_previous_cpa(ctx, channel_name)
            if previous_cpa is None or previous_cpa <= 0:
                # Fall back to campaign-level comparison
                previous_cpa = campaign_cpa

            pct_change = (channel_cpa - previous_cpa) / previous_cpa
            if pct_change >= self.spike_threshold:
                affected_channels.append(
                    {
                        "channel": channel_name,
                        "current_cpa": channel_cpa,
                        "previous_cpa": previous_cpa,
                        "pct_change": round(pct_change, 4),
                        "spend": channel_spend,
                    }
                )

        if not affected_channels:
            return None

        # Build payload — reduce budget on all affected channels
        reductions: dict[str, float] = {}
        for ch_info in affected_channels:
            channel_name = ch_info["channel"]
            current_alloc = ctx.current_allocations.get(channel_name, 0.0)
            if current_alloc > 0:
                reductions[channel_name] = round(
                    current_alloc * self.budget_reduction_pct, 2
                )

        if not reductions:
            return None

        # Confidence is higher when the spike is larger
        max_change = max(ch["pct_change"] for ch in affected_channels)
        confidence = min(0.95, 0.6 + max_change)

        return MethodEvaluation(
            should_fire=True,
            confidence=round(confidence, 4),
            priority=2,
            action_type="budget_reallocation",
            action_payload={
                "reductions": reductions,
                "affected_channels": affected_channels,
                "reduction_pct": self.budget_reduction_pct,
            },
            reasoning=(
                f"CPA spike detected on {len(affected_channels)} channel(s). "
                f"Largest increase: {max_change:.0%}. "
                f"Proposing {self.budget_reduction_pct:.0%} budget reduction."
            ),
            trigger_data={
                "campaign_cpa": campaign_cpa,
                "affected_channels": affected_channels,
            },
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _get_previous_cpa(ctx: MethodContext, channel: str) -> float | None:
        """Retrieve the previous CPA for *channel* from trend data."""
        for trend in ctx.trends:
            if (
                trend.get("channel") == channel
                and trend.get("kpi_name") in ("cpa", "cac")
            ):
                return trend.get("previous_value")
        return None

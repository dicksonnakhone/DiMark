"""Creative fatigue detection method.

Flags channels where click-through rate is declining over time while
impressions remain high, suggesting the audience is losing interest
in the current creative.
"""

from __future__ import annotations

from app.services.optimization.methods.base import (
    BaseOptimizationMethod,
    MethodContext,
    MethodEvaluation,
)

# Defaults
DEFAULT_CTR_DECLINE_THRESHOLD = 0.15  # 15 % decline over the period
DEFAULT_MIN_IMPRESSIONS = 10_000
DEFAULT_PERIOD_DAYS = 7


class CreativeFatigueMethod(BaseOptimizationMethod):
    """Advisory method that detects creative fatigue via CTR decline."""

    name = "creative_fatigue"
    description = "Detect creative fatigue from declining CTR and flag for creative rotation"
    method_type = "proactive"

    def __init__(
        self,
        *,
        ctr_decline_threshold: float = DEFAULT_CTR_DECLINE_THRESHOLD,
        min_impressions: int = DEFAULT_MIN_IMPRESSIONS,
        period_days: int = DEFAULT_PERIOD_DAYS,
    ) -> None:
        self.ctr_decline_threshold = ctr_decline_threshold
        self.min_impressions = min_impressions
        self.period_days = period_days

    # ------------------------------------------------------------------

    def check_preconditions(self, ctx: MethodContext) -> tuple[bool, str]:
        if not ctx.trends:
            return False, "No trend data available"
        if not ctx.channel_data:
            return False, "No channel data available"
        return True, ""

    def evaluate(self, ctx: MethodContext) -> MethodEvaluation | None:
        fatigued_channels: list[dict] = []

        for trend in ctx.trends:
            if trend.get("kpi_name") != "ctr":
                continue
            if trend.get("direction") != "declining":
                continue

            channel = trend.get("channel")
            magnitude = abs(trend.get("magnitude", 0.0))

            if magnitude < self.ctr_decline_threshold:
                continue

            # Check the channel has enough impressions
            channel_impressions = self._get_channel_impressions(ctx, channel)
            if channel_impressions < self.min_impressions:
                continue

            fatigued_channels.append(
                {
                    "channel": channel,
                    "ctr_decline": round(magnitude, 4),
                    "current_ctr": trend.get("current_value", 0.0),
                    "previous_ctr": trend.get("previous_value", 0.0),
                    "impressions": channel_impressions,
                    "period_days": trend.get("period_days", self.period_days),
                }
            )

        if not fatigued_channels:
            return None

        # Confidence: higher when the decline is steeper
        max_decline = max(ch["ctr_decline"] for ch in fatigued_channels)
        confidence = min(0.85, 0.4 + max_decline)

        channel_names = [ch["channel"] for ch in fatigued_channels]

        return MethodEvaluation(
            should_fire=True,
            confidence=round(confidence, 4),
            priority=6,
            action_type="creative_refresh",
            action_payload={
                "channels": channel_names,
                "fatigued_channels": fatigued_channels,
            },
            reasoning=(
                f"Creative fatigue detected on {len(fatigued_channels)} channel(s). "
                f"CTR declining up to {max_decline:.0%} over "
                f"{fatigued_channels[0]['period_days']} days with sufficient impressions. "
                f"Recommend creative rotation."
            ),
            trigger_data={
                "fatigued_channels": fatigued_channels,
            },
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _get_channel_impressions(ctx: MethodContext, channel: str | None) -> int:
        """Sum impressions for *channel* from channel_data."""
        for ch in ctx.channel_data:
            if ch.get("channel") == channel:
                return int(ch.get("totals", {}).get("impressions", 0))
        return 0

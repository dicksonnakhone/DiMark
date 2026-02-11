from __future__ import annotations

import random
from datetime import date
from decimal import Decimal
from typing import Any

from app.services.execution.base import ExecutionAgent
from app.services.execution.channel_models import DEFAULT_CHANNEL_PARAMS, ChannelParams


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _clamp(value: Decimal, minimum: Decimal) -> Decimal:
    if value < minimum:
        return minimum
    return value


def _effective_rate(base: Decimal, spend: Decimal, params: ChannelParams) -> Decimal:
    scale = params.spend_scale if params.spend_scale > 0 else Decimal("1")
    factor = Decimal("1") / (Decimal("1") + params.diminishing_k * (spend / scale))
    return base * factor


def _apply_noise(rng: random.Random, value: Decimal, sigma: Decimal) -> Decimal:
    if sigma <= 0:
        return value
    noise = Decimal(str(rng.normalvariate(0, float(sigma))))
    return _clamp(value * (Decimal("1") + noise), Decimal("0"))


class SimulatedExecutionAgent(ExecutionAgent):
    def run_window(
        self,
        *,
        campaign: Any,
        plan_json: dict[str, Any] | None,
        brief_json: dict[str, Any] | None,
        budget_plan: Any,
        allocations: dict[str, Any],
        window_start: date,
        window_end: date,
        seed: int,
        variant_name: str | None = None,
        sim_overrides: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        rng = random.Random(seed)
        objective = getattr(campaign, "objective", "paid_conversions")
        plan_start = getattr(budget_plan, "start_date", None)
        plan_end = getattr(budget_plan, "end_date", None)
        plan_days = None
        if plan_start and plan_end and plan_end >= plan_start:
            plan_days = (plan_end - plan_start).days + 1

        window_days = (window_end - window_start).days + 1
        if window_days <= 0:
            window_days = 1

        snapshots: list[dict[str, Any]] = []
        for channel, allocation in allocations.items():
            params = DEFAULT_CHANNEL_PARAMS.get(channel)
            if params is None:
                params = ChannelParams(
                    base_cpm=Decimal("15"),
                    base_ctr=Decimal("0.01"),
                    base_cvr=Decimal("0.02"),
                    base_aov=Decimal("65"),
                    diminishing_k=Decimal("0.4"),
                    spend_scale=Decimal("8000"),
                    noise_sigma=Decimal("0.08"),
                )

            allocated = _to_decimal(allocation)
            if plan_days:
                spend = allocated * Decimal(window_days) / Decimal(plan_days)
            else:
                spend = allocated

            spend = _clamp(spend, Decimal("0"))
            overrides = (sim_overrides or {}).get(channel, {})
            ctr_mult = _to_decimal(overrides.get("ctr_mult", 1))
            cvr_mult = _to_decimal(overrides.get("cvr_mult", 1))
            aov_mult = _to_decimal(overrides.get("aov_mult", 1))

            base_ctr = params.base_ctr * ctr_mult
            base_cvr = params.base_cvr * cvr_mult

            effective_ctr = _effective_rate(base_ctr, spend, params)
            effective_cvr = _effective_rate(base_cvr, spend, params)

            effective_ctr = _apply_noise(rng, effective_ctr, params.noise_sigma)
            effective_cvr = _apply_noise(rng, effective_cvr, params.noise_sigma)

            impressions = Decimal("0")
            if params.base_cpm > 0:
                impressions = (spend / params.base_cpm) * Decimal("1000")
            impressions = max(Decimal("0"), impressions)

            clicks = impressions * effective_ctr
            conversions = clicks * effective_cvr

            if params.influencer_hit_rate is not None:
                hit = rng.random() < float(params.influencer_hit_rate)
                if hit and params.influencer_multiplier is not None:
                    conversions = conversions * params.influencer_multiplier
                if not hit:
                    conversions = Decimal("0")

            if objective == "revenue" or (brief_json and brief_json.get("revenue_tracking")):
                aov = _apply_noise(rng, params.base_aov * aov_mult, Decimal("0.05"))
                revenue = conversions * aov
            else:
                revenue = Decimal("0")

            snapshots.append(
                {
                    "channel": channel,
                    "window_start": window_start,
                    "window_end": window_end,
                    "spend": spend.quantize(Decimal("0.01")),
                    "impressions": int(impressions.to_integral_value()),
                    "clicks": int(clicks.to_integral_value()),
                    "conversions": int(conversions.to_integral_value()),
                    "revenue": revenue.quantize(Decimal("0.01")),
                }
            )

        return snapshots

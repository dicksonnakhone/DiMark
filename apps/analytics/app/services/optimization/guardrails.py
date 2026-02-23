"""Guardrail checks for the optimization decision engine.

Four standalone pure-logic functions, each returning a
``GuardrailCheckResult``.  Easily testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True)
class GuardrailCheckResult:
    """Outcome of a single guardrail check."""

    passed: bool
    rule_name: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 1. Budget change limit
# ---------------------------------------------------------------------------


def check_budget_change_limit(
    current_allocations: dict[str, float],
    proposed_allocations: dict[str, float] | None,
    *,
    max_change_pct: float = 0.20,
) -> GuardrailCheckResult:
    """No single channel budget may change by more than *max_change_pct* (20 %)."""
    if proposed_allocations is None:
        return GuardrailCheckResult(
            passed=True,
            rule_name="budget_change_limit",
            message="No allocation changes proposed",
        )

    violations: list[dict[str, Any]] = []
    for channel, current in current_allocations.items():
        proposed = proposed_allocations.get(channel, current)
        if current == 0:
            continue
        change_pct = abs(proposed - current) / current
        if change_pct > max_change_pct:
            violations.append(
                {
                    "channel": channel,
                    "current": current,
                    "proposed": proposed,
                    "change_pct": round(change_pct, 4),
                }
            )

    if violations:
        return GuardrailCheckResult(
            passed=False,
            rule_name="budget_change_limit",
            message=(
                f"Budget change exceeds {max_change_pct:.0%} limit on "
                f"{len(violations)} channel(s)"
            ),
            details={"violations": violations, "max_change_pct": max_change_pct},
        )

    return GuardrailCheckResult(
        passed=True,
        rule_name="budget_change_limit",
        message="All budget changes within limit",
    )


# ---------------------------------------------------------------------------
# 2. Minimum channel floor
# ---------------------------------------------------------------------------


def check_minimum_channel_floor(
    proposed_allocations: dict[str, float] | None,
    *,
    min_floor_pct: float = 0.05,
) -> GuardrailCheckResult:
    """No channel may drop below *min_floor_pct* (5 %) of total budget."""
    if proposed_allocations is None:
        return GuardrailCheckResult(
            passed=True,
            rule_name="minimum_channel_floor",
            message="No allocation changes proposed",
        )

    total = sum(proposed_allocations.values())
    if total <= 0:
        return GuardrailCheckResult(
            passed=True,
            rule_name="minimum_channel_floor",
            message="Total budget is zero",
        )

    violations: list[dict[str, Any]] = []
    for channel, amount in proposed_allocations.items():
        if amount <= 0:
            # Channels at zero are assumed to be intentionally paused
            continue
        share = amount / total
        if share < min_floor_pct:
            violations.append(
                {
                    "channel": channel,
                    "amount": amount,
                    "share": round(share, 4),
                }
            )

    if violations:
        return GuardrailCheckResult(
            passed=False,
            rule_name="minimum_channel_floor",
            message=(
                f"{len(violations)} channel(s) below {min_floor_pct:.0%} floor"
            ),
            details={"violations": violations, "min_floor_pct": min_floor_pct},
        )

    return GuardrailCheckResult(
        passed=True,
        rule_name="minimum_channel_floor",
        message="All channels above minimum floor",
    )


# ---------------------------------------------------------------------------
# 3. Rate limit
# ---------------------------------------------------------------------------


def check_rate_limit(
    recent_proposal_times: list[datetime],
    *,
    max_per_hour: int = 3,
) -> GuardrailCheckResult:
    """Max *max_per_hour* proposals per campaign per hour."""
    now = datetime.now(tz=timezone.utc)
    one_hour_ago = now - timedelta(hours=1)

    recent_count = sum(1 for t in recent_proposal_times if t >= one_hour_ago)

    if recent_count >= max_per_hour:
        return GuardrailCheckResult(
            passed=False,
            rule_name="rate_limit",
            message=(
                f"Rate limit reached: {recent_count} proposals in the last hour "
                f"(max {max_per_hour})"
            ),
            details={
                "recent_count": recent_count,
                "max_per_hour": max_per_hour,
            },
        )

    return GuardrailCheckResult(
        passed=True,
        rule_name="rate_limit",
        message=f"{recent_count}/{max_per_hour} proposals in last hour",
        details={"recent_count": recent_count, "max_per_hour": max_per_hour},
    )


# ---------------------------------------------------------------------------
# 4. Cooldown
# ---------------------------------------------------------------------------


def check_cooldown(
    method_name: str,
    last_fired_at: datetime | None,
    *,
    cooldown_minutes: int = 60,
) -> GuardrailCheckResult:
    """A method cannot fire again within its cooldown window."""
    if last_fired_at is None:
        return GuardrailCheckResult(
            passed=True,
            rule_name="cooldown",
            message=f"Method '{method_name}' has not fired before",
        )

    now = datetime.now(tz=timezone.utc)
    # Make last_fired_at timezone-aware if it isn't
    if last_fired_at.tzinfo is None:
        last_fired_at = last_fired_at.replace(tzinfo=timezone.utc)

    elapsed = now - last_fired_at
    cooldown = timedelta(minutes=cooldown_minutes)

    if elapsed < cooldown:
        remaining = cooldown - elapsed
        return GuardrailCheckResult(
            passed=False,
            rule_name="cooldown",
            message=(
                f"Method '{method_name}' is in cooldown. "
                f"{remaining.total_seconds() / 60:.0f} minutes remaining."
            ),
            details={
                "method_name": method_name,
                "last_fired_at": last_fired_at.isoformat(),
                "cooldown_minutes": cooldown_minutes,
                "remaining_seconds": remaining.total_seconds(),
            },
        )

    return GuardrailCheckResult(
        passed=True,
        rule_name="cooldown",
        message=f"Method '{method_name}' cooldown has elapsed",
        details={
            "method_name": method_name,
            "cooldown_minutes": cooldown_minutes,
            "elapsed_minutes": round(elapsed.total_seconds() / 60, 1),
        },
    )

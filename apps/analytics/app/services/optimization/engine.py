"""Decision engine — 8-step pipeline for automated optimization.

Pipeline:
  1. Preconditions  — campaign exists, has snapshots
  2. Data collection — collect raw metrics + compute KPIs + analyse trends
  3. Method evaluation — run all registered methods
  4. Guardrails      — filter evaluations through 4 guardrail checks
  5. Proposal creation — persist OptimizationProposal rows
  6. Confidence adjustment — lower confidence if data is sparse
  7. Execution decision — auto-approve high confidence, queue the rest
  8. Commit          — save all to DB
"""

from __future__ import annotations

import uuid as uuid_mod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Campaign,
    ChannelSnapshot,
    OptimizationMethod as OptimizationMethodModel,
    OptimizationProposal,
)
from app.services.optimization.guardrails import (
    GuardrailCheckResult,
    check_budget_change_limit,
    check_cooldown,
    check_minimum_channel_floor,
    check_rate_limit,
)
from app.services.optimization.methods.base import (
    MethodContext,
    MethodEvaluation,
    MethodRegistry,
)
from app.services.optimization.metrics import (
    KPICalculator,
    MetricsCollector,
    TrendAnalyzer,
)
from app.settings import settings


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class EngineResult:
    """Outcome of a single engine run."""

    success: bool
    campaign_id: str
    proposals_created: int = 0
    proposals_auto_approved: int = 0
    proposals_queued: int = 0
    guardrail_rejections: int = 0
    method_evaluations: int = 0
    errors: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# DecisionEngine
# ---------------------------------------------------------------------------


class DecisionEngine:
    """Runs the 8-step optimization pipeline for a campaign."""

    def __init__(self, registry: MethodRegistry) -> None:
        self.registry = registry
        self.collector = MetricsCollector()
        self.kpi_calculator = KPICalculator()
        self.trend_analyzer = TrendAnalyzer()

    def run(self, db: Session, campaign_id: str) -> EngineResult:
        """Execute the full pipeline. Returns :class:`EngineResult`."""
        result = EngineResult(success=False, campaign_id=campaign_id)

        # Normalise campaign_id to UUID for DB queries
        try:
            cid = uuid_mod.UUID(campaign_id) if isinstance(campaign_id, str) else campaign_id
        except ValueError:
            result.errors.append(f"Invalid campaign ID: {campaign_id}")
            return result

        # ------------------------------------------------------------------
        # Step 1: Preconditions
        # ------------------------------------------------------------------
        campaign = db.execute(
            select(Campaign).where(Campaign.id == cid)
        ).scalar_one_or_none()

        if campaign is None:
            result.errors.append(f"Campaign {campaign_id} not found")
            return result

        snapshot_count = db.execute(
            select(func.count())
            .select_from(ChannelSnapshot)
            .where(ChannelSnapshot.campaign_id == cid)
        ).scalar() or 0

        if snapshot_count == 0:
            result.errors.append("No channel snapshots available for this campaign")
            return result

        # ------------------------------------------------------------------
        # Step 2: Data collection
        # ------------------------------------------------------------------
        raw_metrics = self.collector.collect(db, cid)
        kpi_rows = self.kpi_calculator.compute(db, cid, raw_metrics)
        trends = self.trend_analyzer.analyze(db, cid)

        # Build MethodContext
        kpis_dict: dict[str, float] = {}
        for kpi in kpi_rows:
            if kpi.channel is None:  # campaign-level
                kpis_dict[kpi.kpi_name] = float(kpi.kpi_value)

        trend_dicts = [
            {
                "channel": t.channel,
                "kpi_name": t.kpi_name,
                "direction": t.direction,
                "magnitude": float(t.magnitude),
                "current_value": float(t.current_value),
                "previous_value": float(t.previous_value),
                "period_days": t.period_days,
                "confidence": float(t.confidence),
            }
            for t in trends
        ]

        # Build channel_data from per-channel KPIs
        channel_kpis: dict[str, dict[str, float]] = {}
        channel_raw: dict[str, dict[str, float]] = {}
        for kpi in kpi_rows:
            if kpi.channel is not None:
                channel_kpis.setdefault(kpi.channel, {})[kpi.kpi_name] = float(
                    kpi.kpi_value
                )
        for rm in raw_metrics:
            channel_raw.setdefault(rm.channel, {})[rm.metric_name] = float(
                rm.metric_value
            )

        channel_data: list[dict[str, Any]] = []
        for channel_name in channel_kpis:
            raw = channel_raw.get(channel_name, {})
            channel_data.append(
                {
                    "channel": channel_name,
                    "kpis": channel_kpis[channel_name],
                    "totals": {
                        "spend": raw.get("spend", 0.0),
                        "impressions": raw.get("impressions", 0),
                        "clicks": raw.get("clicks", 0),
                        "conversions": raw.get("conversions", 0),
                        "revenue": raw.get("revenue", 0.0),
                    },
                }
            )

        # Current allocations (latest snapshot spend as proxy)
        current_allocations: dict[str, float] = {
            ch: channel_raw.get(ch, {}).get("spend", 0.0) for ch in channel_kpis
        }

        ctx = MethodContext(
            campaign_id=campaign_id,
            kpis=kpis_dict,
            trends=trend_dicts,
            raw_metrics={k: float(v) for k, v in channel_raw.get(next(iter(channel_raw), ""), {}).items()}
            if channel_raw
            else {},
            channel_data=channel_data,
            current_allocations=current_allocations,
            campaign_config={
                "objective": campaign.objective,
                "target_cac": float(campaign.target_cac) if campaign.target_cac else None,
            },
        )

        # ------------------------------------------------------------------
        # Step 3: Method evaluation
        # ------------------------------------------------------------------
        evaluations = self.registry.evaluate_all(ctx)
        result.method_evaluations = len(evaluations)

        if not evaluations:
            result.success = True
            result.details["message"] = "No optimizations triggered"
            db.commit()
            return result

        # ------------------------------------------------------------------
        # Step 4: Guardrails
        # ------------------------------------------------------------------
        # Load recent proposals for rate limit
        one_hour_ago = datetime.now(tz=timezone.utc) - timedelta(hours=1)
        recent_proposals = db.execute(
            select(OptimizationProposal.created_at).where(
                OptimizationProposal.campaign_id == cid,
                OptimizationProposal.created_at >= one_hour_ago,
            )
        ).scalars().all()
        recent_times = [t for t in recent_proposals if t is not None]

        passing_evaluations: list[tuple[MethodEvaluation, list[GuardrailCheckResult]]] = []

        for evaluation in evaluations:
            checks: list[GuardrailCheckResult] = []

            # Rate limit
            rate_check = check_rate_limit(
                recent_times,
                max_per_hour=settings.OPTIMIZATION_MAX_PROPOSALS_PER_HOUR,
            )
            checks.append(rate_check)

            # Cooldown
            last_fired = self._get_last_fired(db, evaluation.action_type, cid)
            cooldown_check = check_cooldown(
                evaluation.action_type,
                last_fired,
                cooldown_minutes=settings.OPTIMIZATION_DEFAULT_COOLDOWN_MINUTES,
            )
            checks.append(cooldown_check)

            # Budget change limit (only for budget_reallocation actions)
            if evaluation.action_type == "budget_reallocation":
                proposed = evaluation.action_payload.get("new_allocations")
                budget_check = check_budget_change_limit(
                    current_allocations,
                    proposed,
                    max_change_pct=settings.OPTIMIZATION_MAX_BUDGET_CHANGE_PCT,
                )
                checks.append(budget_check)

                floor_check = check_minimum_channel_floor(
                    proposed,
                    min_floor_pct=settings.OPTIMIZATION_MIN_CHANNEL_FLOOR_PCT,
                )
                checks.append(floor_check)

            if all(c.passed for c in checks):
                passing_evaluations.append((evaluation, checks))
            else:
                result.guardrail_rejections += 1

        # ------------------------------------------------------------------
        # Step 5: Proposal creation
        # ------------------------------------------------------------------
        proposals: list[OptimizationProposal] = []
        for evaluation, checks in passing_evaluations:
            method_row = self._ensure_method_row(db, evaluation)

            proposal = OptimizationProposal(
                campaign_id=cid,
                method_id=method_row.id,
                status="pending",
                confidence=evaluation.confidence,
                priority=evaluation.priority,
                action_type=evaluation.action_type,
                action_payload=evaluation.action_payload,
                reasoning=evaluation.reasoning,
                trigger_data_json=evaluation.trigger_data,
                guardrail_checks_json={
                    "checks": [
                        {
                            "rule_name": c.rule_name,
                            "passed": c.passed,
                            "message": c.message,
                        }
                        for c in checks
                    ]
                },
                expires_at=datetime.now(tz=timezone.utc) + timedelta(hours=24),
            )
            db.add(proposal)
            proposals.append(proposal)

        db.flush()  # Assign IDs
        result.proposals_created = len(proposals)

        # ------------------------------------------------------------------
        # Step 6: Confidence adjustment
        # ------------------------------------------------------------------
        for proposal in proposals:
            adjusted = self._adjust_confidence(
                proposal.confidence, snapshot_count, len(raw_metrics)
            )
            proposal.confidence = adjusted

        # ------------------------------------------------------------------
        # Step 7: Execution decision
        # ------------------------------------------------------------------
        threshold = settings.OPTIMIZATION_AUTO_APPROVE_THRESHOLD
        for proposal in proposals:
            if float(proposal.confidence) >= threshold:
                proposal.status = "auto_approved"
                proposal.approved_by = "engine"
                proposal.approved_at = datetime.now(tz=timezone.utc)
                result.proposals_auto_approved += 1
            else:
                proposal.status = "pending"
                result.proposals_queued += 1

        # ------------------------------------------------------------------
        # Step 8: Commit
        # ------------------------------------------------------------------
        db.commit()
        result.success = True
        result.details["message"] = (
            f"Created {result.proposals_created} proposal(s): "
            f"{result.proposals_auto_approved} auto-approved, "
            f"{result.proposals_queued} queued"
        )
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_last_fired(
        db: Session, action_type: str, campaign_id: Any
    ) -> datetime | None:
        """Find the most recent proposal of this action_type for the campaign."""
        row = db.execute(
            select(OptimizationProposal.created_at)
            .where(
                OptimizationProposal.campaign_id == campaign_id,
                OptimizationProposal.action_type == action_type,
            )
            .order_by(OptimizationProposal.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        return row

    @staticmethod
    def _ensure_method_row(
        db: Session, evaluation: MethodEvaluation
    ) -> OptimizationMethodModel:
        """Get or create the OptimizationMethod DB row for this evaluation."""
        row = db.execute(
            select(OptimizationMethodModel).where(
                OptimizationMethodModel.name == evaluation.action_type
            )
        ).scalar_one_or_none()

        if row is None:
            row = OptimizationMethodModel(
                name=evaluation.action_type,
                description=f"Auto-registered method for {evaluation.action_type}",
                method_type="reactive",
                trigger_conditions={},
                config_json={},
                is_active=True,
                cooldown_minutes=settings.OPTIMIZATION_DEFAULT_COOLDOWN_MINUTES,
                stats_json={},
            )
            db.add(row)
            db.flush()

        return row

    @staticmethod
    def _adjust_confidence(
        confidence: float,
        snapshot_count: int,
        raw_metric_count: int,
    ) -> float:
        """Lower confidence when data is sparse."""
        # If very few snapshots, reduce confidence
        if snapshot_count < 5:
            confidence *= 0.8
        elif snapshot_count < 10:
            confidence *= 0.9

        # If very few raw metrics, further reduce
        if raw_metric_count < 10:
            confidence *= 0.85

        return round(min(1.0, max(0.0, confidence)), 4)

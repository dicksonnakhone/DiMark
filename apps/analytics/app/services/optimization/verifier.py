"""Outcome verifier — post-execution verification and learning loop.

Compares predicted outcomes (from proposal action_payload) against actual
KPI changes measured after execution, computes accuracy scores, and
updates OptimizationMethod.stats_json to improve future confidence
calibration.
"""

from __future__ import annotations

import uuid as uuid_mod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ChannelSnapshot,
    OptimizationLearning,
    OptimizationMethod as OptimizationMethodModel,
    OptimizationProposal,
)
from app.services.optimization.metrics import KPICalculator, MetricsCollector
from app.settings import settings


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class VerificationResult:
    """Outcome of verifying a single executed proposal."""

    success: bool
    proposal_id: str
    learning_id: str | None = None
    accuracy_score: float | None = None
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class BatchVerificationResult:
    """Aggregated result of verifying multiple proposals."""

    total: int = 0
    verified: int = 0
    pending: int = 0
    failed: int = 0
    records: list[VerificationResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# OutcomeVerifier
# ---------------------------------------------------------------------------


class OutcomeVerifier:
    """Verifies optimization outcomes and updates method learning stats."""

    def __init__(self) -> None:
        self.collector = MetricsCollector()
        self.kpi_calculator = KPICalculator()

    def verify_proposal(
        self,
        db: Session,
        proposal_id: uuid_mod.UUID,
        verification_window_hours: int | None = None,
    ) -> VerificationResult:
        """Verify a single executed proposal.

        Parameters
        ----------
        db : Session
            Active database session.
        proposal_id : UUID
            The proposal to verify.
        verification_window_hours : int | None
            Hours to wait after execution before verifying.
            Defaults to ``settings.OPTIMIZATION_VERIFICATION_DELAY_HOURS``.

        Returns
        -------
        VerificationResult
        """
        if verification_window_hours is None:
            verification_window_hours = settings.OPTIMIZATION_VERIFICATION_DELAY_HOURS

        proposal = db.get(OptimizationProposal, proposal_id)
        if proposal is None:
            return VerificationResult(
                success=False,
                proposal_id=str(proposal_id),
                error="Proposal not found",
            )

        # --- Must be executed ---
        if proposal.status != "executed" or proposal.executed_at is None:
            return VerificationResult(
                success=False,
                proposal_id=str(proposal_id),
                error=f"Proposal must be executed to verify (status: {proposal.status})",
            )

        # --- Check timing: is it too soon? ---
        now = datetime.now(tz=timezone.utc)
        executed_at = proposal.executed_at
        if executed_at.tzinfo is None:
            executed_at = executed_at.replace(tzinfo=timezone.utc)

        elapsed = now - executed_at
        if elapsed < timedelta(hours=verification_window_hours):
            remaining = timedelta(hours=verification_window_hours) - elapsed
            return VerificationResult(
                success=False,
                proposal_id=str(proposal_id),
                error="pending",
                details={
                    "status": "pending",
                    "message": f"Verification window not reached. {remaining} remaining.",
                    "executed_at": executed_at.isoformat(),
                    "earliest_verification": (
                        executed_at + timedelta(hours=verification_window_hours)
                    ).isoformat(),
                },
            )

        # --- Check for existing learning record (idempotency) ---
        existing = db.execute(
            select(OptimizationLearning).where(
                OptimizationLearning.proposal_id == proposal_id,
                OptimizationLearning.verification_status == "verified",
            )
        ).scalar_one_or_none()
        if existing is not None:
            return VerificationResult(
                success=True,
                proposal_id=str(proposal_id),
                learning_id=str(existing.id),
                accuracy_score=float(existing.accuracy_score) if existing.accuracy_score else None,
                details={"idempotent": True, "already_verified": True},
            )

        # --- Extract predicted impact ---
        predicted_impact = self._extract_predicted_impact(proposal)

        # --- Collect actual metrics ---
        actual_impact = self._collect_actual_impact(db, proposal)

        # --- Compute accuracy score ---
        accuracy = self._compute_accuracy_score(predicted_impact, actual_impact)

        # --- Create learning record ---
        learning = OptimizationLearning(
            campaign_id=proposal.campaign_id,
            proposal_id=proposal.id,
            method_id=proposal.method_id,
            predicted_impact=predicted_impact,
            actual_impact=actual_impact,
            accuracy_score=accuracy,
            verification_status="verified",
            verified_at=now,
            details_json={
                "action_type": proposal.action_type,
                "confidence": float(proposal.confidence),
                "verification_window_hours": verification_window_hours,
            },
        )
        db.add(learning)
        db.flush()

        # --- Update method stats ---
        method = db.get(OptimizationMethodModel, proposal.method_id)
        if method is not None:
            self._update_method_stats(
                db, method, accuracy, success=accuracy >= 0.5
            )

        db.commit()

        return VerificationResult(
            success=True,
            proposal_id=str(proposal_id),
            learning_id=str(learning.id),
            accuracy_score=accuracy,
            details={
                "predicted_impact": predicted_impact,
                "actual_impact": actual_impact,
            },
        )

    def verify_batch(
        self,
        db: Session,
        campaign_id: uuid_mod.UUID,
        max_age_hours: int = 48,
    ) -> BatchVerificationResult:
        """Verify all executed proposals for a campaign within the age window.

        Parameters
        ----------
        db : Session
        campaign_id : UUID
        max_age_hours : int
            Only consider proposals executed within this many hours.

        Returns
        -------
        BatchVerificationResult
        """
        cid = (
            uuid_mod.UUID(str(campaign_id))
            if isinstance(campaign_id, str)
            else campaign_id
        )

        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=max_age_hours)
        proposals = db.execute(
            select(OptimizationProposal).where(
                OptimizationProposal.campaign_id == cid,
                OptimizationProposal.status == "executed",
                OptimizationProposal.executed_at.is_not(None),
            )
        ).scalars().all()

        result = BatchVerificationResult(total=len(proposals))

        for proposal in proposals:
            # Skip proposals that are too old
            executed_at = proposal.executed_at
            if executed_at.tzinfo is None:
                executed_at = executed_at.replace(tzinfo=timezone.utc)
            if executed_at < cutoff:
                continue

            vr = self.verify_proposal(db, proposal.id)
            result.records.append(vr)

            if vr.error == "pending":
                result.pending += 1
            elif vr.success:
                result.verified += 1
            else:
                result.failed += 1

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_predicted_impact(proposal: OptimizationProposal) -> dict[str, Any]:
        """Extract predicted impact from proposal action_payload."""
        payload = proposal.action_payload or {}
        predicted: dict[str, Any] = {
            "action_type": proposal.action_type,
        }

        if proposal.action_type == "budget_reallocation":
            predicted["new_allocations"] = payload.get("new_allocations", {})
            predicted["reductions"] = payload.get("reductions", {})
            predicted["expected_improvement"] = payload.get("expected_improvement", "efficiency")
        elif proposal.action_type == "creative_refresh":
            predicted["channels"] = payload.get("channels", [])
            predicted["fatigued_channels"] = payload.get("fatigued_channels", [])
            predicted["expected_improvement"] = "ctr"
        else:
            predicted["payload"] = payload

        return predicted

    def _collect_actual_impact(
        self,
        db: Session,
        proposal: OptimizationProposal,
    ) -> dict[str, Any]:
        """Collect actual KPI changes since proposal execution."""
        cid = proposal.campaign_id
        executed_at = proposal.executed_at

        # Get the latest snapshots to measure post-execution state
        from sqlalchemy import func

        snapshot_count = db.execute(
            select(func.count())
            .select_from(ChannelSnapshot)
            .where(ChannelSnapshot.campaign_id == cid)
        ).scalar() or 0

        if snapshot_count == 0:
            return {"error": "no_snapshots", "message": "No snapshot data available"}

        # Collect raw metrics and compute current KPIs
        raw_metrics = self.collector.collect(db, cid)
        kpi_rows = self.kpi_calculator.compute(db, cid, raw_metrics)

        # Build actual state
        actual: dict[str, Any] = {
            "snapshot_count": snapshot_count,
            "raw_metrics_count": len(raw_metrics),
        }

        # Campaign-level KPIs
        campaign_kpis: dict[str, float] = {}
        channel_kpis: dict[str, dict[str, float]] = {}
        for kpi in kpi_rows:
            if kpi.channel is None:
                campaign_kpis[kpi.kpi_name] = float(kpi.kpi_value)
            else:
                channel_kpis.setdefault(kpi.channel, {})[kpi.kpi_name] = float(
                    kpi.kpi_value
                )

        actual["campaign_kpis"] = campaign_kpis
        actual["channel_kpis"] = channel_kpis
        return actual

    @staticmethod
    def _compute_accuracy_score(
        predicted: dict[str, Any],
        actual: dict[str, Any],
    ) -> float:
        """Compute accuracy score between predicted and actual impacts.

        For budget_reallocation: checks if efficiency improved.
        For creative_refresh: checks if CTR improved.
        Falls back to a base score of 0.5 if comparison data is insufficient.
        """
        if "error" in actual:
            return 0.5  # Neutral score when we can't measure

        campaign_kpis = actual.get("campaign_kpis", {})
        action_type = predicted.get("action_type", "")

        if action_type == "budget_reallocation":
            # Did ROAS or CPA improve?
            roas = campaign_kpis.get("roas")
            cpa = campaign_kpis.get("cpa")

            if roas is not None and roas > 0:
                # Higher ROAS is better — score based on having reasonable ROAS
                score = min(1.0, roas / 3.0)  # 3.0 ROAS → perfect score
                return round(max(0.0, score), 4)
            elif cpa is not None and cpa > 0:
                # Lower CPA is better
                score = min(1.0, 30.0 / max(cpa, 1.0))  # CPA of 30 → perfect
                return round(max(0.0, score), 4)

        elif action_type == "creative_refresh":
            ctr = campaign_kpis.get("ctr")
            if ctr is not None and ctr > 0:
                # Higher CTR is better
                score = min(1.0, ctr / 0.02)  # 2% CTR → perfect
                return round(max(0.0, score), 4)

        # Default: neutral score
        return 0.5

    @staticmethod
    def _update_method_stats(
        db: Session,
        method: OptimizationMethodModel,
        accuracy: float,
        success: bool,
    ) -> None:
        """Update method.stats_json with new learning data."""
        stats = dict(method.stats_json or {})

        total = stats.get("total_executions", 0) + 1
        successful = stats.get("successful_executions", 0) + (1 if success else 0)
        prev_avg = stats.get("avg_accuracy", 0.0)

        # Running average
        new_avg = ((prev_avg * (total - 1)) + accuracy) / total

        stats["total_executions"] = total
        stats["successful_executions"] = successful
        stats["avg_accuracy"] = round(new_avg, 4)
        stats["last_verified_at"] = datetime.now(tz=timezone.utc).isoformat()

        method.stats_json = stats

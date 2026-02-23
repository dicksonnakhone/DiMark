"""Optimization monitor — full-cycle orchestrator.

Runs the complete observe → decide → act → verify loop for a campaign
in a single call. Creates a ``MonitorRun`` audit record for each cycle.
"""

from __future__ import annotations

import uuid as uuid_mod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MonitorRun, OptimizationProposal
from app.services.optimization.engine import DecisionEngine, EngineResult
from app.services.optimization.executor import (
    ActionExecutor,
    BatchExecutionResult,
)
from app.services.optimization.methods import build_default_registry
from app.services.optimization.verifier import (
    BatchVerificationResult,
    OutcomeVerifier,
)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class MonitorRunResult:
    """Outcome of a full monitor cycle."""

    campaign_id: str
    monitor_run_id: str | None = None
    engine_result: EngineResult | None = None
    execution_result: BatchExecutionResult | None = None
    verification_result: BatchVerificationResult | None = None
    success: bool = True
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# OptimizationMonitor
# ---------------------------------------------------------------------------


class OptimizationMonitor:
    """Orchestrates the full optimization lifecycle for a campaign.

    Pipeline:
      1. **OBSERVE & DECIDE** — Run ``DecisionEngine`` to collect metrics,
         evaluate methods, and create proposals.
      2. **ACT** — Execute any auto-approved proposals that haven't been
         executed yet.
      3. **VERIFY** — Verify recently executed proposals that are past the
         verification window.
    """

    def __init__(self, dry_run: bool = True) -> None:
        self.registry = build_default_registry()
        self.engine = DecisionEngine(self.registry)
        self.executor = ActionExecutor(dry_run=dry_run)
        self.verifier = OutcomeVerifier()

    def run_cycle(
        self,
        db: Session,
        campaign_id: uuid_mod.UUID,
    ) -> MonitorRunResult:
        """Execute the full optimization cycle.

        Parameters
        ----------
        db : Session
            Active database session.
        campaign_id : UUID
            The campaign to optimise.

        Returns
        -------
        MonitorRunResult
            Aggregated results from all three phases.
        """
        cid = (
            uuid_mod.UUID(str(campaign_id))
            if isinstance(campaign_id, str)
            else campaign_id
        )
        result = MonitorRunResult(campaign_id=str(cid))

        # ------------------------------------------------------------------
        # Phase 1: OBSERVE & DECIDE
        # ------------------------------------------------------------------
        try:
            engine_result = self.engine.run(db, str(cid))
            result.engine_result = engine_result
        except Exception as exc:
            result.errors.append(f"Engine phase failed: {exc}")
            result.success = False
            engine_result = None

        # ------------------------------------------------------------------
        # Phase 2: ACT — execute auto-approved proposals
        # ------------------------------------------------------------------
        try:
            auto_approved_ids = db.execute(
                select(OptimizationProposal.id).where(
                    OptimizationProposal.campaign_id == cid,
                    OptimizationProposal.status == "auto_approved",
                    OptimizationProposal.executed_at.is_(None),
                )
            ).scalars().all()

            if auto_approved_ids:
                batch_result = self.executor.execute_batch(
                    db, list(auto_approved_ids)
                )
                result.execution_result = batch_result

                if batch_result.failed > 0:
                    result.errors.append(
                        f"Execution phase: {batch_result.failed}/{batch_result.total} failed"
                    )
        except Exception as exc:
            result.errors.append(f"Execution phase failed: {exc}")

        # ------------------------------------------------------------------
        # Phase 3: VERIFY — verify recently executed proposals
        # ------------------------------------------------------------------
        try:
            verification_result = self.verifier.verify_batch(
                db, cid, max_age_hours=48
            )
            result.verification_result = verification_result
        except Exception as exc:
            result.errors.append(f"Verification phase failed: {exc}")

        # ------------------------------------------------------------------
        # Create MonitorRun record
        # ------------------------------------------------------------------
        status = "completed"
        if result.errors:
            status = "partial" if result.engine_result and result.engine_result.success else "failed"

        engine_summary = {}
        if result.engine_result:
            er = result.engine_result
            engine_summary = {
                "success": er.success,
                "proposals_created": er.proposals_created,
                "proposals_auto_approved": er.proposals_auto_approved,
                "proposals_queued": er.proposals_queued,
                "guardrail_rejections": er.guardrail_rejections,
                "method_evaluations": er.method_evaluations,
            }

        execution_summary = {}
        if result.execution_result:
            bx = result.execution_result
            execution_summary = {
                "total": bx.total,
                "succeeded": bx.succeeded,
                "failed": bx.failed,
            }

        verification_summary = {}
        if result.verification_result:
            bv = result.verification_result
            verification_summary = {
                "total": bv.total,
                "verified": bv.verified,
                "pending": bv.pending,
                "failed": bv.failed,
            }

        monitor_run = MonitorRun(
            campaign_id=cid,
            status=status,
            engine_summary_json=engine_summary,
            execution_summary_json=execution_summary,
            verification_summary_json=verification_summary,
        )
        db.add(monitor_run)
        db.commit()
        db.refresh(monitor_run)

        result.monitor_run_id = str(monitor_run.id)
        return result

"""Action executor — bridges approved proposals to platform execution.

Maps optimization action types (budget_reallocation, pause_channel,
creative_refresh) to concrete platform adapter calls, creates audit-trail
Execution/ExecutionAction records, and updates proposal status.
"""

from __future__ import annotations

import asyncio
import uuid as uuid_mod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Execution,
    ExecutionAction,
    OptimizationProposal,
)
from app.platforms.base import Platform
from app.platforms.factory import get_platform_adapter
from app.settings import settings


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ExecutionRecord:
    """Outcome of executing a single proposal."""

    success: bool
    proposal_id: str
    execution_id: str | None = None
    error: str | None = None
    platform_result: dict[str, Any] | None = None


@dataclass
class BatchExecutionResult:
    """Aggregated result of executing multiple proposals."""

    total: int = 0
    succeeded: int = 0
    failed: int = 0
    records: list[ExecutionRecord] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ActionExecutor
# ---------------------------------------------------------------------------


class ActionExecutor:
    """Executes approved optimization proposals via platform adapters."""

    # Action types that require actual platform calls
    PLATFORM_ACTIONS = {"budget_reallocation", "pause_channel", "resume_channel"}
    # Advisory-only actions — mark as executed but no platform call
    ADVISORY_ACTIONS = {"creative_refresh"}

    def __init__(self, dry_run: bool = True) -> None:
        self.dry_run = dry_run

    def execute_proposal(
        self,
        db: Session,
        proposal_id: uuid_mod.UUID,
        *,
        force: bool = False,
    ) -> ExecutionRecord:
        """Execute a single approved/auto_approved proposal.

        Parameters
        ----------
        db : Session
            Active database session.
        proposal_id : UUID
            The proposal to execute.
        force : bool
            If True, skip status validation (for testing).

        Returns
        -------
        ExecutionRecord
            Success/failure details.
        """
        proposal = db.get(OptimizationProposal, proposal_id)
        if proposal is None:
            return ExecutionRecord(
                success=False,
                proposal_id=str(proposal_id),
                error="Proposal not found",
            )

        # --- Status validation ---
        if not force and proposal.status not in ("approved", "auto_approved"):
            return ExecutionRecord(
                success=False,
                proposal_id=str(proposal_id),
                error=f"Proposal status must be approved or auto_approved, got '{proposal.status}'",
            )

        # --- Idempotency check ---
        idempotency_key = f"opt-proposal-{proposal.id}"
        existing = db.execute(
            select(Execution).where(Execution.idempotency_key == idempotency_key)
        ).scalar_one_or_none()

        if existing is not None:
            return ExecutionRecord(
                success=True,
                proposal_id=str(proposal_id),
                execution_id=str(existing.id),
                error=None,
                platform_result=existing.execution_plan,
            )

        # --- Execute ---
        try:
            if proposal.action_type in self.ADVISORY_ACTIONS:
                record = self._execute_advisory(db, proposal, idempotency_key)
            elif proposal.action_type in self.PLATFORM_ACTIONS:
                record = self._execute_platform_action(db, proposal, idempotency_key)
            else:
                record = ExecutionRecord(
                    success=False,
                    proposal_id=str(proposal_id),
                    error=f"Unknown action_type: {proposal.action_type}",
                )
                proposal.status = "failed"
                proposal.execution_result_json = {"error": record.error}
                db.commit()
                return record

            db.commit()
            return record

        except Exception as exc:
            db.rollback()
            proposal = db.get(OptimizationProposal, proposal_id)
            if proposal is not None:
                proposal.status = "failed"
                proposal.execution_result_json = {
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                }
                db.commit()

            return ExecutionRecord(
                success=False,
                proposal_id=str(proposal_id),
                error=str(exc),
            )

    def execute_batch(
        self,
        db: Session,
        proposal_ids: list[uuid_mod.UUID],
    ) -> BatchExecutionResult:
        """Execute multiple proposals. Returns aggregated results."""
        result = BatchExecutionResult(total=len(proposal_ids))
        for pid in proposal_ids:
            record = self.execute_proposal(db, pid)
            result.records.append(record)
            if record.success:
                result.succeeded += 1
            else:
                result.failed += 1
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _execute_advisory(
        self,
        db: Session,
        proposal: OptimizationProposal,
        idempotency_key: str,
    ) -> ExecutionRecord:
        """Handle advisory-only actions (no platform call needed)."""
        now = datetime.now(tz=timezone.utc)

        execution_plan = {
            "action_type": proposal.action_type,
            "advisory": True,
            "reasoning": proposal.reasoning,
            "payload": proposal.action_payload,
        }

        execution = Execution(
            campaign_id=proposal.campaign_id,
            platform="advisory",
            status="completed",
            execution_plan=execution_plan,
            idempotency_key=idempotency_key,
        )
        db.add(execution)
        db.flush()

        action = ExecutionAction(
            execution_id=execution.id,
            action_type=proposal.action_type,
            idempotency_key=f"{idempotency_key}-advisory",
            request_json={"advisory": True, "payload": proposal.action_payload},
            response_json={"status": "noted", "message": "Advisory action recorded"},
            status="completed",
            duration_ms=0,
        )
        db.add(action)

        proposal.status = "executed"
        proposal.executed_at = now
        proposal.execution_result_json = {
            "advisory": True,
            "execution_id": str(execution.id),
            "message": "Advisory action recorded — no platform changes made",
        }

        return ExecutionRecord(
            success=True,
            proposal_id=str(proposal.id),
            execution_id=str(execution.id),
            platform_result=execution_plan,
        )

    def _execute_platform_action(
        self,
        db: Session,
        proposal: OptimizationProposal,
        idempotency_key: str,
    ) -> ExecutionRecord:
        """Execute an action that requires platform adapter calls."""
        now = datetime.now(tz=timezone.utc)
        payload = proposal.action_payload or {}

        # Determine platform from payload or default to meta
        platform_str = payload.get("platform", "meta")
        try:
            platform = Platform(platform_str)
        except ValueError:
            platform = Platform.META

        adapter = get_platform_adapter(platform, dry_run=self.dry_run)

        # Build execution plan
        execution_plan = {
            "action_type": proposal.action_type,
            "platform": platform.value,
            "payload": payload,
        }

        execution = Execution(
            campaign_id=proposal.campaign_id,
            platform=platform.value,
            status="running",
            execution_plan=execution_plan,
            idempotency_key=idempotency_key,
        )
        db.add(execution)
        db.flush()

        # --- Dispatch by action type ---
        all_results: list[dict[str, Any]] = []
        all_actions: list[ExecutionAction] = []
        overall_success = True

        if proposal.action_type == "budget_reallocation":
            all_results, all_actions, overall_success = self._execute_budget_reallocation(
                adapter, platform, execution, payload
            )
        elif proposal.action_type == "pause_channel":
            all_results, all_actions, overall_success = self._execute_pause(
                adapter, platform, execution, payload
            )
        elif proposal.action_type == "resume_channel":
            all_results, all_actions, overall_success = self._execute_resume(
                adapter, platform, execution, payload
            )

        # Persist execution actions
        for action in all_actions:
            db.add(action)

        # Update execution status
        execution.status = "completed" if overall_success else "failed"

        # Update proposal
        proposal.status = "executed" if overall_success else "failed"
        proposal.executed_at = now
        proposal.execution_result_json = {
            "execution_id": str(execution.id),
            "success": overall_success,
            "results": all_results,
        }

        return ExecutionRecord(
            success=overall_success,
            proposal_id=str(proposal.id),
            execution_id=str(execution.id),
            platform_result={"results": all_results},
            error=None if overall_success else "One or more platform operations failed",
        )

    def _execute_budget_reallocation(
        self,
        adapter: Any,
        platform: Platform,
        execution: Execution,
        payload: dict[str, Any],
    ) -> tuple[list[dict], list[ExecutionAction], bool]:
        """Execute budget reallocation via update_budget calls."""
        new_allocations = payload.get("new_allocations", {})
        results: list[dict[str, Any]] = []
        actions: list[ExecutionAction] = []
        overall_success = True

        for channel, new_budget in new_allocations.items():
            # Use a dummy external ID for now (in real usage this would come
            # from the campaign's existing platform execution records)
            ext_id = payload.get("external_campaign_ids", {}).get(
                channel, f"campaign-{channel}"
            )

            request_json = {
                "channel": channel,
                "external_campaign_id": ext_id,
                "new_budget": new_budget,
            }

            try:
                platform_result = asyncio.run(
                    adapter.update_budget(
                        ext_id,
                        new_budget,
                        platform=platform,
                    )
                )
                result_dict = platform_result.model_dump()
                success = platform_result.success
            except Exception as exc:
                result_dict = {"error": str(exc), "error_type": type(exc).__name__}
                success = False

            if not success:
                overall_success = False

            results.append({"channel": channel, "success": success, **result_dict})

            action = ExecutionAction(
                execution_id=execution.id,
                action_type="update_budget",
                idempotency_key=f"{execution.idempotency_key}-budget-{channel}",
                request_json=request_json,
                response_json=result_dict,
                status="completed" if success else "failed",
                error_message=result_dict.get("error") if not success else None,
            )
            actions.append(action)

        return results, actions, overall_success

    def _execute_pause(
        self,
        adapter: Any,
        platform: Platform,
        execution: Execution,
        payload: dict[str, Any],
    ) -> tuple[list[dict], list[ExecutionAction], bool]:
        """Execute pause_campaign for affected channels."""
        affected = payload.get("affected_channels", [])
        results: list[dict[str, Any]] = []
        actions: list[ExecutionAction] = []
        overall_success = True

        for channel in affected:
            ext_id = payload.get("external_campaign_ids", {}).get(
                channel, f"campaign-{channel}"
            )

            try:
                platform_result = asyncio.run(
                    adapter.pause_campaign(ext_id, platform=platform)
                )
                result_dict = platform_result.model_dump()
                success = platform_result.success
            except Exception as exc:
                result_dict = {"error": str(exc)}
                success = False

            if not success:
                overall_success = False

            results.append({"channel": channel, "success": success, **result_dict})

            action = ExecutionAction(
                execution_id=execution.id,
                action_type="pause_campaign",
                idempotency_key=f"{execution.idempotency_key}-pause-{channel}",
                request_json={"channel": channel, "external_campaign_id": ext_id},
                response_json=result_dict,
                status="completed" if success else "failed",
            )
            actions.append(action)

        return results, actions, overall_success

    def _execute_resume(
        self,
        adapter: Any,
        platform: Platform,
        execution: Execution,
        payload: dict[str, Any],
    ) -> tuple[list[dict], list[ExecutionAction], bool]:
        """Execute resume_campaign for affected channels."""
        affected = payload.get("affected_channels", [])
        results: list[dict[str, Any]] = []
        actions: list[ExecutionAction] = []
        overall_success = True

        for channel in affected:
            ext_id = payload.get("external_campaign_ids", {}).get(
                channel, f"campaign-{channel}"
            )

            try:
                platform_result = asyncio.run(
                    adapter.resume_campaign(ext_id, platform=platform)
                )
                result_dict = platform_result.model_dump()
                success = platform_result.success
            except Exception as exc:
                result_dict = {"error": str(exc)}
                success = False

            if not success:
                overall_success = False

            results.append({"channel": channel, "success": success, **result_dict})

            action = ExecutionAction(
                execution_id=execution.id,
                action_type="resume_campaign",
                idempotency_key=f"{execution.idempotency_key}-resume-{channel}",
                request_json={"channel": channel, "external_campaign_id": ext_id},
                response_json=result_dict,
                status="completed" if success else "failed",
            )
            actions.append(action)

        return results, actions, overall_success

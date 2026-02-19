from __future__ import annotations

import uuid
from typing import Any

from app.platforms.base import (
    AdPlatformAdapter,
    ExecutionPlan,
    ExecutionResult,
    Platform,
    ValidationIssue,
)


class DryRunExecutor(AdPlatformAdapter):
    """Simulates platform API calls with realistic fake responses.

    Used for development, testing, and dry-run validation of execution plans
    before connecting real platform APIs.
    """

    def __init__(self) -> None:
        self._created: dict[str, ExecutionPlan] = {}  # idempotency cache

    async def validate_plan(self, plan: ExecutionPlan) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []

        if plan.total_budget <= 0:
            issues.append(
                ValidationIssue(
                    field="total_budget",
                    message="Budget must be positive",
                    severity="error",
                )
            )
        if not plan.campaign_name:
            issues.append(
                ValidationIssue(
                    field="campaign_name",
                    message="Campaign name is required",
                    severity="error",
                )
            )
        if not plan.ad_sets:
            issues.append(
                ValidationIssue(
                    field="ad_sets",
                    message="At least one ad set is required",
                    severity="warning",
                )
            )
        return issues

    async def create_campaign(
        self, plan: ExecutionPlan, *, idempotency_key: str
    ) -> ExecutionResult:
        # Idempotency: return cached result for duplicate key
        if idempotency_key in self._created:
            return ExecutionResult(
                success=True,
                platform=plan.platform,
                external_campaign_id=f"dry-run-{idempotency_key[:8]}",
                external_ids={"campaign": f"dry-run-{idempotency_key[:8]}"},
                links={},
                raw_response={"note": "idempotent_replay"},
            )

        # Validate first
        issues = await self.validate_plan(plan)
        errors = [i for i in issues if i.severity == "error"]
        if errors:
            return ExecutionResult(
                success=False,
                platform=plan.platform,
                validation_issues=issues,
                error="Validation failed",
            )

        ext_id = f"dry-run-{uuid.uuid4().hex[:8]}"
        self._created[idempotency_key] = plan

        ad_set_ids = {
            ad_set.name: f"dry-run-adset-{uuid.uuid4().hex[:6]}"
            for ad_set in plan.ad_sets
        }

        return ExecutionResult(
            success=True,
            platform=plan.platform,
            external_campaign_id=ext_id,
            external_ids={"campaign": ext_id, **ad_set_ids},
            links={
                "campaign_url": f"https://dry-run.example.com/campaigns/{ext_id}"
            },
            raw_response={
                "dry_run": True,
                "plan_summary": {
                    "name": plan.campaign_name,
                    "budget": plan.total_budget,
                    "ad_sets": len(plan.ad_sets),
                },
            },
        )

    async def pause_campaign(
        self, external_campaign_id: str, *, platform: Platform
    ) -> ExecutionResult:
        return ExecutionResult(
            success=True,
            platform=platform,
            external_campaign_id=external_campaign_id,
            raw_response={"status": "paused", "dry_run": True},
        )

    async def resume_campaign(
        self, external_campaign_id: str, *, platform: Platform
    ) -> ExecutionResult:
        return ExecutionResult(
            success=True,
            platform=platform,
            external_campaign_id=external_campaign_id,
            raw_response={"status": "active", "dry_run": True},
        )

    async def update_budget(
        self,
        external_campaign_id: str,
        new_budget: float,
        *,
        platform: Platform,
    ) -> ExecutionResult:
        if new_budget <= 0:
            return ExecutionResult(
                success=False,
                platform=platform,
                external_campaign_id=external_campaign_id,
                error="Budget must be positive",
            )
        return ExecutionResult(
            success=True,
            platform=platform,
            external_campaign_id=external_campaign_id,
            raw_response={
                "new_budget": new_budget,
                "status": "budget_updated",
                "dry_run": True,
            },
        )

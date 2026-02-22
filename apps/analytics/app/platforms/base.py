from __future__ import annotations

import enum
from typing import Any

from pydantic import BaseModel, Field


class Platform(str, enum.Enum):
    META = "meta"
    GOOGLE = "google"
    LINKEDIN = "linkedin"


class ExecutionStatus(str, enum.Enum):
    PENDING = "pending"
    VALIDATING = "validating"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class ValidationIssue(BaseModel):
    field: str
    message: str
    severity: str = "error"  # "error" | "warning"


class AdSetSpec(BaseModel):
    """Specification for a single ad set to create on a platform."""

    name: str
    daily_budget: float
    targeting: dict[str, Any] = Field(default_factory=dict)
    creative: dict[str, Any] = Field(default_factory=dict)
    bid_strategy: str = "auto"


class ExecutionPlan(BaseModel):
    """Normalised execution payload — what gets sent to a platform adapter."""

    platform: Platform
    campaign_name: str
    objective: str
    total_budget: float
    currency: str = "USD"
    ad_sets: list[AdSetSpec] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionResult(BaseModel):
    """Standardised result returned after any platform interaction."""

    success: bool
    platform: Platform
    external_campaign_id: str | None = None
    external_ids: dict[str, str] = Field(default_factory=dict)
    links: dict[str, str] = Field(default_factory=dict)
    validation_issues: list[ValidationIssue] = Field(default_factory=list)
    error: str | None = None
    raw_response: dict[str, Any] = Field(default_factory=dict)


class AdPlatformAdapter:
    """Base class for all advertising platform integrations.

    Every platform (Meta, Google, LinkedIn, etc.) must implement these methods.
    The Executor Agent uses this interface without knowing which platform.
    """

    async def validate_plan(self, plan: ExecutionPlan) -> list[ValidationIssue]:
        raise NotImplementedError

    async def create_campaign(
        self, plan: ExecutionPlan, *, idempotency_key: str
    ) -> ExecutionResult:
        raise NotImplementedError

    async def pause_campaign(
        self, external_campaign_id: str, *, platform: Platform
    ) -> ExecutionResult:
        raise NotImplementedError

    async def resume_campaign(
        self, external_campaign_id: str, *, platform: Platform
    ) -> ExecutionResult:
        raise NotImplementedError

    async def update_budget(
        self,
        external_campaign_id: str,
        new_budget: float,
        *,
        platform: Platform,
    ) -> ExecutionResult:
        raise NotImplementedError

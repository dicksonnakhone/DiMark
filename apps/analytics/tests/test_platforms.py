"""Tests for the platform adapter interface, dry-run executor, and factory."""

import pytest

from app.platforms.base import (
    AdPlatformAdapter,
    AdSetSpec,
    ExecutionPlan,
    ExecutionResult,
    Platform,
    ValidationIssue,
)
from app.platforms.dry_run import DryRunExecutor
from app.platforms.factory import get_platform_adapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_plan(**overrides) -> ExecutionPlan:
    defaults = {
        "platform": Platform.META,
        "campaign_name": "Test Campaign",
        "objective": "conversions",
        "total_budget": 1000.0,
        "ad_sets": [
            AdSetSpec(name="Ad Set 1", daily_budget=50.0),
        ],
    }
    defaults.update(overrides)
    return ExecutionPlan(**defaults)


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_valid_plan():
    executor = DryRunExecutor()
    issues = await executor.validate_plan(_valid_plan())
    errors = [i for i in issues if i.severity == "error"]
    assert len(errors) == 0


@pytest.mark.asyncio
async def test_validate_zero_budget():
    executor = DryRunExecutor()
    issues = await executor.validate_plan(_valid_plan(total_budget=0))
    errors = [i for i in issues if i.severity == "error"]
    assert len(errors) == 1
    assert errors[0].field == "total_budget"


@pytest.mark.asyncio
async def test_validate_empty_name():
    executor = DryRunExecutor()
    issues = await executor.validate_plan(_valid_plan(campaign_name=""))
    errors = [i for i in issues if i.severity == "error"]
    assert len(errors) == 1
    assert errors[0].field == "campaign_name"


@pytest.mark.asyncio
async def test_validate_no_ad_sets_warns():
    executor = DryRunExecutor()
    issues = await executor.validate_plan(_valid_plan(ad_sets=[]))
    warnings = [i for i in issues if i.severity == "warning"]
    assert len(warnings) == 1
    assert warnings[0].field == "ad_sets"


# ---------------------------------------------------------------------------
# Create campaign tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_campaign_success():
    executor = DryRunExecutor()
    plan = _valid_plan()
    result = await executor.create_campaign(plan, idempotency_key="test-key-1")

    assert result.success is True
    assert result.platform == Platform.META
    assert result.external_campaign_id is not None
    assert "campaign" in result.external_ids
    assert "campaign_url" in result.links


@pytest.mark.asyncio
async def test_create_campaign_idempotency():
    executor = DryRunExecutor()
    plan = _valid_plan()

    result1 = await executor.create_campaign(plan, idempotency_key="idem-key-1")
    result2 = await executor.create_campaign(plan, idempotency_key="idem-key-1")

    assert result1.success is True
    assert result2.success is True
    # Idempotent replay should return same campaign ID prefix
    assert result2.external_campaign_id == f"dry-run-idem-key"


@pytest.mark.asyncio
async def test_create_campaign_validation_failure():
    executor = DryRunExecutor()
    plan = _valid_plan(total_budget=-100)
    result = await executor.create_campaign(plan, idempotency_key="fail-key")

    assert result.success is False
    assert result.error == "Validation failed"
    assert len(result.validation_issues) > 0


# ---------------------------------------------------------------------------
# Pause / resume / budget tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pause_campaign():
    executor = DryRunExecutor()
    result = await executor.pause_campaign("ext-123", platform=Platform.META)

    assert result.success is True
    assert result.external_campaign_id == "ext-123"


@pytest.mark.asyncio
async def test_resume_campaign():
    executor = DryRunExecutor()
    result = await executor.resume_campaign("ext-123", platform=Platform.GOOGLE)

    assert result.success is True
    assert result.platform == Platform.GOOGLE


@pytest.mark.asyncio
async def test_update_budget_success():
    executor = DryRunExecutor()
    result = await executor.update_budget("ext-123", 2000.0, platform=Platform.LINKEDIN)

    assert result.success is True
    assert result.raw_response["new_budget"] == 2000.0


@pytest.mark.asyncio
async def test_update_budget_invalid():
    executor = DryRunExecutor()
    result = await executor.update_budget("ext-123", -500.0, platform=Platform.META)

    assert result.success is False
    assert result.error is not None


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------


def test_factory_returns_dry_run():
    adapter = get_platform_adapter("meta", dry_run=True)
    assert isinstance(adapter, DryRunExecutor)


def test_factory_raises_for_unimplemented_adapter():
    with pytest.raises(NotImplementedError):
        get_platform_adapter("google", dry_run=False)


def test_factory_returns_meta_adapter():
    from unittest.mock import patch

    with patch("app.platforms.meta_ads.FacebookAdsApi"), patch(
        "app.platforms.meta_ads.AdAccount"
    ):
        from app.platforms.meta_ads import MetaAdsAdapter

        adapter = get_platform_adapter("meta", dry_run=False)
        assert isinstance(adapter, MetaAdsAdapter)

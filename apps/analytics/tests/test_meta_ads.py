"""Tests for the Meta Ads platform adapter with mocked SDK."""

from unittest.mock import MagicMock, patch

import pytest

from app.platforms.base import (
    AdSetSpec,
    ExecutionPlan,
    Platform,
)


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
# Fixture: MetaAdsAdapter with mocked SDK
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_sdk():
    """Patch the facebook_business SDK so no real API calls are made."""
    with (
        patch("app.platforms.meta_ads.FacebookAdsApi") as mock_api_cls,
        patch("app.platforms.meta_ads.AdAccount") as mock_account_cls,
        patch("app.platforms.meta_ads.Campaign") as mock_campaign_cls,
        patch("app.platforms.meta_ads.AdImage") as mock_adimage_cls,
        patch("app.platforms.meta_ads.AdCreative") as mock_adcreative_cls,
        patch("app.platforms.meta_ads.Ad") as mock_ad_cls,
    ):
        mock_account = MagicMock()
        mock_account_cls.return_value = mock_account

        # Default: create_campaign returns a dict with an id
        mock_campaign_obj = MagicMock()
        mock_campaign_obj.__getitem__ = MagicMock(return_value="123456789")
        mock_account.create_campaign.return_value = mock_campaign_obj

        # Default: create_ad_set returns a dict with an id
        mock_adset_obj = MagicMock()
        mock_adset_obj.__getitem__ = MagicMock(return_value="987654321")
        mock_account.create_ad_set.return_value = mock_adset_obj

        # Default: create_ad_creative returns a dict with an id
        mock_creative_obj = MagicMock()
        mock_creative_obj.__getitem__ = MagicMock(return_value="creative_001")
        mock_account.create_ad_creative.return_value = mock_creative_obj

        # Default: create_ad returns a dict with an id
        mock_ad_obj = MagicMock()
        mock_ad_obj.__getitem__ = MagicMock(return_value="ad_001")
        mock_account.create_ad.return_value = mock_ad_obj

        # Default: AdImage mock
        mock_adimage_instance = MagicMock()
        mock_adimage_instance.__getitem__ = MagicMock(return_value="abc123hash")
        mock_adimage_cls.return_value = mock_adimage_instance

        yield {
            "api_cls": mock_api_cls,
            "account_cls": mock_account_cls,
            "account": mock_account,
            "campaign_cls": mock_campaign_cls,
            "campaign_obj": mock_campaign_obj,
            "adset_obj": mock_adset_obj,
            "adimage_cls": mock_adimage_cls,
            "adimage_instance": mock_adimage_instance,
            "adcreative_cls": mock_adcreative_cls,
            "creative_obj": mock_creative_obj,
            "ad_cls": mock_ad_cls,
            "ad_obj": mock_ad_obj,
        }


@pytest.fixture
def adapter(mock_sdk):
    """Create a MetaAdsAdapter with mocked SDK."""
    from app.platforms.meta_ads import MetaAdsAdapter

    return MetaAdsAdapter(
        access_token="test-token",
        app_secret="test-secret",
        ad_account_id="act_test123",
        page_id="page_test456",
    )


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_valid_plan(adapter):
    issues = await adapter.validate_plan(_valid_plan())
    errors = [i for i in issues if i.severity == "error"]
    assert len(errors) == 0


@pytest.mark.asyncio
async def test_validate_bad_objective(adapter):
    issues = await adapter.validate_plan(_valid_plan(objective="unknown_objective"))
    errors = [i for i in issues if i.severity == "error"]
    assert len(errors) == 1
    assert errors[0].field == "objective"
    assert "unknown_objective" in errors[0].message


@pytest.mark.asyncio
async def test_validate_low_adset_budget(adapter):
    plan = _valid_plan(
        ad_sets=[AdSetSpec(name="Cheap Set", daily_budget=0.50)]
    )
    issues = await adapter.validate_plan(plan)
    errors = [i for i in issues if i.severity == "error"]
    assert len(errors) == 1
    assert "daily_budget" in errors[0].field
    assert "minimum" in errors[0].message.lower()


@pytest.mark.asyncio
async def test_validate_zero_budget(adapter):
    issues = await adapter.validate_plan(_valid_plan(total_budget=0))
    errors = [i for i in issues if i.severity == "error"]
    assert any(e.field == "total_budget" for e in errors)


@pytest.mark.asyncio
async def test_validate_invalid_image_url(adapter):
    """Creative with a non-http image URL should produce a validation error."""
    plan = _valid_plan(
        ad_sets=[
            AdSetSpec(
                name="Bad URL Set",
                daily_budget=50.0,
                creative={"image_url": "not-a-url"},
            ),
        ]
    )
    issues = await adapter.validate_plan(plan)
    errors = [i for i in issues if i.severity == "error"]
    assert any("image_url" in e.field for e in errors)


@pytest.mark.asyncio
async def test_validate_creative_without_image_warns(adapter):
    """Creative dict with no image_url or image_hash should produce a warning."""
    plan = _valid_plan(
        ad_sets=[
            AdSetSpec(
                name="No Image Set",
                daily_budget=50.0,
                creative={"message": "Buy now!"},
            ),
        ]
    )
    issues = await adapter.validate_plan(plan)
    warnings = [i for i in issues if i.severity == "warning"]
    assert any("creative" in w.field for w in warnings)


# ---------------------------------------------------------------------------
# Create campaign tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_campaign_success(adapter, mock_sdk):
    plan = _valid_plan()
    result = await adapter.create_campaign(plan, idempotency_key="test-key-1")

    assert result.success is True
    assert result.platform == Platform.META
    assert result.external_campaign_id == "123456789"
    assert "campaign" in result.external_ids
    assert result.external_ids["campaign"] == "123456789"
    assert "campaign_url" in result.links
    assert "adsmanager" in result.links["campaign_url"]

    # New: verify creatives/ads counters
    assert result.raw_response["creatives_created"] == 0
    assert result.raw_response["ads_created"] == 0

    # Verify SDK was called correctly
    mock_sdk["account"].create_campaign.assert_called_once()
    mock_sdk["account"].create_ad_set.assert_called_once()


@pytest.mark.asyncio
async def test_create_campaign_with_multiple_adsets(adapter, mock_sdk):
    # Each create_ad_set call returns a different ID
    adset_ids = iter(["adset_001", "adset_002", "adset_003"])
    mock_adset = MagicMock()
    mock_adset.__getitem__ = MagicMock(side_effect=lambda key: next(adset_ids))
    mock_sdk["account"].create_ad_set.return_value = mock_adset

    plan = _valid_plan(
        ad_sets=[
            AdSetSpec(name="Set A", daily_budget=10.0),
            AdSetSpec(name="Set B", daily_budget=20.0),
            AdSetSpec(name="Set C", daily_budget=30.0),
        ]
    )
    result = await adapter.create_campaign(plan, idempotency_key="multi-key")

    assert result.success is True
    assert mock_sdk["account"].create_ad_set.call_count == 3
    assert "Set A" in result.external_ids
    assert "Set B" in result.external_ids
    assert "Set C" in result.external_ids


@pytest.mark.asyncio
async def test_create_campaign_validation_failure(adapter):
    plan = _valid_plan(total_budget=-100)
    result = await adapter.create_campaign(plan, idempotency_key="fail-key")

    assert result.success is False
    assert result.error == "Validation failed"
    assert len(result.validation_issues) > 0


@pytest.mark.asyncio
async def test_create_campaign_api_error(adapter, mock_sdk):
    from facebook_business.exceptions import FacebookRequestError

    error = FacebookRequestError(
        message="Rate limit exceeded",
        request_context={"method": "POST"},
        http_status=429,
        http_headers={},
        body='{"error": {"message": "Rate limit exceeded", "code": 32}}',
    )
    mock_sdk["account"].create_campaign.side_effect = error

    plan = _valid_plan()
    result = await adapter.create_campaign(plan, idempotency_key="error-key")

    assert result.success is False
    assert result.error is not None
    assert "error_code" in result.raw_response


# ---------------------------------------------------------------------------
# Pause / resume / budget tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pause_campaign(adapter, mock_sdk):
    mock_campaign_instance = MagicMock()
    mock_sdk["campaign_cls"].return_value = mock_campaign_instance

    result = await adapter.pause_campaign("ext-123", platform=Platform.META)

    assert result.success is True
    assert result.external_campaign_id == "ext-123"
    assert result.raw_response["status"] == "paused"
    mock_campaign_instance.api_update.assert_called_once()


@pytest.mark.asyncio
async def test_resume_campaign(adapter, mock_sdk):
    mock_campaign_instance = MagicMock()
    mock_sdk["campaign_cls"].return_value = mock_campaign_instance

    result = await adapter.resume_campaign("ext-456", platform=Platform.META)

    assert result.success is True
    assert result.external_campaign_id == "ext-456"
    assert result.raw_response["status"] == "active"
    mock_campaign_instance.api_update.assert_called_once()


@pytest.mark.asyncio
async def test_update_budget_success(adapter, mock_sdk):
    mock_campaign_instance = MagicMock()
    mock_sdk["campaign_cls"].return_value = mock_campaign_instance

    result = await adapter.update_budget("ext-789", 1000.0, platform=Platform.META)

    assert result.success is True
    assert result.raw_response["new_budget"] == 1000.0
    assert result.raw_response["new_budget_cents"] == 100000
    mock_campaign_instance.api_update.assert_called_once()


@pytest.mark.asyncio
async def test_update_budget_negative(adapter):
    result = await adapter.update_budget("ext-789", -500.0, platform=Platform.META)

    assert result.success is False
    assert result.error is not None


# ---------------------------------------------------------------------------
# Objective mapping test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_objective_mapping_coverage(adapter):
    from app.platforms.meta_ads import OBJECTIVE_MAP

    for objective_key in OBJECTIVE_MAP:
        plan = _valid_plan(objective=objective_key)
        issues = await adapter.validate_plan(plan)
        errors = [i for i in issues if i.severity == "error"]
        assert len(errors) == 0, f"Objective '{objective_key}' should be valid but got errors: {errors}"

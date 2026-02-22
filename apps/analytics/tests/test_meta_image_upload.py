"""Tests for Meta Ads creative upload flow (image upload, AdCreative, Ad).

All SDK interactions are mocked — no real API calls are made.
"""

import io
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from app.platforms.base import (
    AdSetSpec,
    ExecutionPlan,
    Platform,
)
from app.platforms.exceptions import ImageDownloadError, ImageValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_image(
    width: int = 800,
    height: int = 800,
    fmt: str = "PNG",
    mode: str = "RGB",
) -> bytes:
    """Create a synthetic image and return it as bytes."""
    img = Image.new(mode, (width, height), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


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
# Fixture: MetaAdsAdapter with fully mocked SDK + image support
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

        # Campaign mock
        mock_campaign_obj = MagicMock()
        mock_campaign_obj.__getitem__ = MagicMock(return_value="campaign_001")
        mock_account.create_campaign.return_value = mock_campaign_obj

        # AdSet mock
        mock_adset_obj = MagicMock()
        mock_adset_obj.__getitem__ = MagicMock(return_value="adset_001")
        mock_account.create_ad_set.return_value = mock_adset_obj

        # AdCreative mock
        mock_creative_obj = MagicMock()
        mock_creative_obj.__getitem__ = MagicMock(return_value="creative_001")
        mock_account.create_ad_creative.return_value = mock_creative_obj

        # Ad mock
        mock_ad_obj = MagicMock()
        mock_ad_obj.__getitem__ = MagicMock(return_value="ad_001")
        mock_account.create_ad.return_value = mock_ad_obj

        # AdImage mock
        mock_adimage_instance = MagicMock()
        mock_adimage_instance.__getitem__ = MagicMock(return_value="img_hash_abc")
        mock_adimage_cls.return_value = mock_adimage_instance

        yield {
            "api_cls": mock_api_cls,
            "account_cls": mock_account_cls,
            "account": mock_account,
            "campaign_cls": mock_campaign_cls,
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
# Image upload unit tests
# ---------------------------------------------------------------------------


def test_upload_image_from_bytes(adapter, mock_sdk):
    """_upload_image_from_bytes should validate, optimise, upload, and cache."""
    image_data = _make_image()
    result = adapter._upload_image_from_bytes(image_data)

    assert result == "img_hash_abc"
    mock_sdk["adimage_instance"].remote_create.assert_called_once()


def test_upload_image_caching(adapter, mock_sdk):
    """Same bytes uploaded twice should only call remote_create once."""
    image_data = _make_image()

    hash1 = adapter._upload_image_from_bytes(image_data)
    hash2 = adapter._upload_image_from_bytes(image_data)

    assert hash1 == hash2
    assert mock_sdk["adimage_instance"].remote_create.call_count == 1


def test_upload_image_from_url(adapter, mock_sdk):
    """_upload_image_from_url should download then upload."""
    image_data = _make_image()

    with patch.object(adapter._image_processor, "download_image_sync", return_value=image_data):
        result = adapter._upload_image_from_url("https://example.com/img.png")

    assert result == "img_hash_abc"
    mock_sdk["adimage_instance"].remote_create.assert_called_once()


def test_upload_invalid_image(adapter):
    """Small images that fail validation should raise ImageValidationError."""
    tiny_image = _make_image(width=50, height=50)

    with pytest.raises(ImageValidationError, match="validation failed"):
        adapter._upload_image_from_bytes(tiny_image)


# ---------------------------------------------------------------------------
# Creative / Ad creation unit tests
# ---------------------------------------------------------------------------


def test_create_ad_creative(adapter, mock_sdk):
    """_create_ad_creative should call account.create_ad_creative."""
    creative_id = adapter._create_ad_creative(
        name="Test Creative",
        image_hash="abc123",
        page_id="page_test456",
        link_url="https://example.com",
        message="Buy now!",
    )

    assert creative_id == "creative_001"
    mock_sdk["account"].create_ad_creative.assert_called_once()


def test_create_ad(adapter, mock_sdk):
    """_create_ad should call account.create_ad."""
    ad_id = adapter._create_ad(
        name="Test Ad",
        adset_id="adset_001",
        creative_id="creative_001",
    )

    assert ad_id == "ad_001"
    mock_sdk["account"].create_ad.assert_called_once()


# ---------------------------------------------------------------------------
# Full campaign with creative (integration-level)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_campaign_with_creative(adapter, mock_sdk):
    """Campaign with creative data should create Campaign + AdSet + Creative + Ad."""
    image_data = _make_image()

    with patch.object(adapter._image_processor, "download_image_sync", return_value=image_data):
        plan = _valid_plan(
            ad_sets=[
                AdSetSpec(
                    name="Creative Set",
                    daily_budget=50.0,
                    creative={
                        "image_url": "https://example.com/hero.png",
                        "link_url": "https://example.com/landing",
                        "message": "Check it out!",
                    },
                ),
            ]
        )
        result = await adapter.create_campaign(plan, idempotency_key="creative-key")

    assert result.success is True
    assert result.raw_response["creatives_created"] == 1
    assert result.raw_response["ads_created"] == 1
    assert "Creative Set_creative" in result.external_ids
    assert "Creative Set_ad" in result.external_ids

    # Verify SDK calls
    mock_sdk["account"].create_campaign.assert_called_once()
    mock_sdk["account"].create_ad_set.assert_called_once()
    mock_sdk["account"].create_ad_creative.assert_called_once()
    mock_sdk["account"].create_ad.assert_called_once()


@pytest.mark.asyncio
async def test_campaign_without_creative(adapter, mock_sdk):
    """Campaign without creative data should work — backward compatible."""
    plan = _valid_plan()
    result = await adapter.create_campaign(plan, idempotency_key="no-creative-key")

    assert result.success is True
    assert result.raw_response["creatives_created"] == 0
    assert result.raw_response["ads_created"] == 0

    # No creative/ad SDK calls
    mock_sdk["account"].create_ad_creative.assert_not_called()
    mock_sdk["account"].create_ad.assert_not_called()


@pytest.mark.asyncio
async def test_image_download_failure_fails_campaign(adapter, mock_sdk):
    """If image download fails, the campaign creation should fail gracefully."""
    with patch.object(
        adapter._image_processor,
        "download_image_sync",
        side_effect=ImageDownloadError("Network error", details={"url": "bad"}),
    ):
        plan = _valid_plan(
            ad_sets=[
                AdSetSpec(
                    name="Fail Set",
                    daily_budget=50.0,
                    creative={"image_url": "https://example.com/bad.png"},
                ),
            ]
        )
        result = await adapter.create_campaign(plan, idempotency_key="download-fail")

    assert result.success is False
    assert "Network error" in result.error


@pytest.mark.asyncio
async def test_image_hash_caching_across_adsets(adapter, mock_sdk):
    """Two ad sets with the same image URL should only upload the image once."""
    image_data = _make_image()

    with patch.object(adapter._image_processor, "download_image_sync", return_value=image_data):
        # Need different adset IDs for each call
        adset_ids = iter(["adset_001", "adset_002"])
        mock_adset = MagicMock()
        mock_adset.__getitem__ = MagicMock(side_effect=lambda key: next(adset_ids))
        mock_sdk["account"].create_ad_set.return_value = mock_adset

        plan = _valid_plan(
            ad_sets=[
                AdSetSpec(
                    name="Set A",
                    daily_budget=50.0,
                    creative={"image_url": "https://example.com/same.png"},
                ),
                AdSetSpec(
                    name="Set B",
                    daily_budget=50.0,
                    creative={"image_url": "https://example.com/same.png"},
                ),
            ]
        )
        result = await adapter.create_campaign(plan, idempotency_key="cache-key")

    assert result.success is True
    assert result.raw_response["creatives_created"] == 2
    assert result.raw_response["ads_created"] == 2

    # Image uploaded only once (cached), but download called twice (URL-level)
    assert mock_sdk["adimage_instance"].remote_create.call_count == 1

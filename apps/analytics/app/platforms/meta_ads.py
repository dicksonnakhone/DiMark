"""Meta Ads (Facebook/Instagram) platform adapter.

Uses the official facebook-business Python SDK to create, manage, and
monitor campaigns on the Meta Marketing API.  Supports the full object
hierarchy: Campaign → AdSet → AdCreative → Ad.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from facebook_business.adobjects.ad import Ad
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.adcreative import AdCreative
from facebook_business.adobjects.adimage import AdImage
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.campaign import Campaign
from facebook_business.api import FacebookAdsApi
from facebook_business.exceptions import FacebookRequestError

from app.platforms.base import (
    AdPlatformAdapter,
    AdSetSpec,
    ExecutionPlan,
    ExecutionResult,
    Platform,
    ValidationIssue,
)
from app.platforms.exceptions import (
    CreativeCreationError,
    ImageDownloadError,
    ImageUploadError,
    ImageValidationError,
    PlatformError,
)
from app.utils.image_utils import ImageProcessor

# ---------------------------------------------------------------------------
# Objective mapping: internal name → Meta Marketing API objective
# Uses the v21.0+ OUTCOME_* objectives
# ---------------------------------------------------------------------------

OBJECTIVE_MAP: dict[str, str] = {
    "conversions": "OUTCOME_SALES",
    "sales": "OUTCOME_SALES",
    "traffic": "OUTCOME_TRAFFIC",
    "lead_generation": "OUTCOME_LEADS",
    "leads": "OUTCOME_LEADS",
    "awareness": "OUTCOME_AWARENESS",
    "brand_awareness": "OUTCOME_AWARENESS",
    "reach": "OUTCOME_AWARENESS",
    "engagement": "OUTCOME_ENGAGEMENT",
    "video_views": "OUTCOME_ENGAGEMENT",
    "app_installs": "OUTCOME_APP_PROMOTION",
}

# Meta minimum ad set daily budget in dollars
META_MIN_ADSET_DAILY_BUDGET = 1.0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dollars_to_cents(dollars: float) -> int:
    """Convert dollar amount to cents (Meta API budget unit)."""
    return int(round(dollars * 100))


def _ads_manager_url(campaign_id: str, ad_account_id: str) -> str:
    """Build a direct link to the campaign in Meta Ads Manager."""
    account_num = ad_account_id.replace("act_", "")
    return f"https://www.facebook.com/adsmanager/manage/campaigns?act={account_num}&campaign_ids={campaign_id}"


def _map_bid_strategy(bid_strategy: str) -> str:
    """Map internal bid strategy to Meta API bid strategy."""
    mapping = {
        "auto": "LOWEST_COST_WITHOUT_CAP",
        "lowest_cost": "LOWEST_COST_WITHOUT_CAP",
        "cost_cap": "COST_CAP",
        "bid_cap": "BID_CAP",
        "target_cost": "COST_CAP",
    }
    return mapping.get(bid_strategy, "LOWEST_COST_WITHOUT_CAP")


def _map_optimization_goal(objective: str) -> str:
    """Map Meta objective to a default optimization goal for ad sets."""
    mapping = {
        "OUTCOME_SALES": "OFFSITE_CONVERSIONS",
        "OUTCOME_TRAFFIC": "LINK_CLICKS",
        "OUTCOME_LEADS": "LEAD_GENERATION",
        "OUTCOME_AWARENESS": "REACH",
        "OUTCOME_ENGAGEMENT": "POST_ENGAGEMENT",
        "OUTCOME_APP_PROMOTION": "APP_INSTALLS",
    }
    return mapping.get(objective, "LINK_CLICKS")


# ---------------------------------------------------------------------------
# MetaAdsAdapter
# ---------------------------------------------------------------------------


class MetaAdsAdapter(AdPlatformAdapter):
    """Real Meta Marketing API adapter using the facebook-business SDK.

    All SDK calls are synchronous, so they are wrapped with
    ``asyncio.to_thread()`` to avoid blocking the event loop.
    """

    def __init__(
        self,
        access_token: str,
        app_secret: str,
        ad_account_id: str,
        page_id: str = "",
    ) -> None:
        self._access_token = access_token
        self._app_secret = app_secret
        self._ad_account_id = ad_account_id
        self._page_id = page_id

        # Initialise the SDK
        FacebookAdsApi.init(
            app_secret=app_secret,
            access_token=access_token,
        )
        self._account = AdAccount(ad_account_id)

        # In-memory cache: SHA-256 content hash → Meta image_hash
        self._image_hash_cache: dict[str, str] = {}
        self._image_processor = ImageProcessor()

    # ------------------------------------------------------------------
    # validate_plan
    # ------------------------------------------------------------------

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

        objective_key = plan.objective.lower()
        if objective_key not in OBJECTIVE_MAP:
            issues.append(
                ValidationIssue(
                    field="objective",
                    message=(
                        f"Unknown objective '{plan.objective}'. "
                        f"Supported: {', '.join(sorted(OBJECTIVE_MAP.keys()))}"
                    ),
                    severity="error",
                )
            )

        for i, ad_set in enumerate(plan.ad_sets):
            if ad_set.daily_budget < META_MIN_ADSET_DAILY_BUDGET:
                issues.append(
                    ValidationIssue(
                        field=f"ad_sets[{i}].daily_budget",
                        message=(
                            f"Ad set '{ad_set.name}' daily budget ${ad_set.daily_budget:.2f} "
                            f"is below Meta minimum of ${META_MIN_ADSET_DAILY_BUDGET:.2f}"
                        ),
                        severity="error",
                    )
                )

            # Validate creative image URL if provided
            creative = ad_set.creative
            if creative:
                image_url = creative.get("image_url", "")
                image_hash = creative.get("image_hash", "")
                if image_url and not (
                    image_url.startswith("http://") or image_url.startswith("https://")
                ):
                    issues.append(
                        ValidationIssue(
                            field=f"ad_sets[{i}].creative.image_url",
                            message=(
                                f"Invalid image URL '{image_url}'. "
                                "Must start with http:// or https://"
                            ),
                            severity="error",
                        )
                    )
                elif not image_url and not image_hash:
                    issues.append(
                        ValidationIssue(
                            field=f"ad_sets[{i}].creative",
                            message=(
                                f"Ad set '{ad_set.name}' has creative data but no "
                                "image_url or image_hash"
                            ),
                            severity="warning",
                        )
                    )

        return issues

    # ------------------------------------------------------------------
    # Image upload helpers (all sync — run via asyncio.to_thread)
    # ------------------------------------------------------------------

    def _upload_image_from_url(self, image_url: str) -> str:
        """Download image from URL and upload to Meta. Returns image_hash."""
        try:
            image_data = self._image_processor.download_image_sync(image_url)
        except ImageDownloadError:
            raise
        except Exception as exc:
            raise ImageDownloadError(
                f"Failed to download image from {image_url}: {exc}",
                details={"url": image_url, "error": str(exc)},
            ) from exc

        return self._upload_image_from_bytes(image_data)

    def _upload_image_from_bytes(self, image_data: bytes) -> str:
        """Validate, optimise, upload image bytes. Returns Meta image_hash.

        Uses an in-memory SHA-256 cache to avoid duplicate uploads.
        """
        content_hash = self._image_processor.compute_hash(image_data)

        # Check cache
        if content_hash in self._image_hash_cache:
            return self._image_hash_cache[content_hash]

        # Validate
        info = self._image_processor.validate_image(image_data)
        if not info["is_valid"]:
            raise ImageValidationError(
                f"Image validation failed: {'; '.join(info['issues'])}",
                details=info,
            )

        # Optimise (ensure reasonable size)
        optimised = self._image_processor.optimize_image(image_data)

        # Write to temp file for SDK upload
        suffix = ".png" if info["format"] == "PNG" else ".jpg"
        tmp_path = self._image_processor.save_to_tempfile(optimised, suffix=suffix)
        try:
            meta_hash = self._upload_image_to_meta(tmp_path)
        finally:
            os.unlink(tmp_path)

        # Cache result
        self._image_hash_cache[content_hash] = meta_hash
        return meta_hash

    def _upload_image_to_meta(self, file_path: str) -> str:
        """Upload a local image file to Meta and return the image hash."""
        try:
            image = AdImage(parent_id=self._ad_account_id)
            image[AdImage.Field.filename] = file_path
            image.remote_create()
            return image[AdImage.Field.hash]
        except FacebookRequestError as exc:
            raise ImageUploadError(
                f"Meta image upload failed: {exc}",
                details={
                    "file_path": file_path,
                    "error_code": exc.api_error_code(),
                    "error_message": exc.api_error_message(),
                },
            ) from exc
        except Exception as exc:
            raise ImageUploadError(
                f"Meta image upload failed: {exc}",
                details={"file_path": file_path, "error": str(exc)},
            ) from exc

    # ------------------------------------------------------------------
    # Creative / Ad creation helpers (sync)
    # ------------------------------------------------------------------

    def _create_ad_creative(
        self,
        name: str,
        image_hash: str,
        page_id: str,
        link_url: str = "",
        message: str = "",
        call_to_action_type: str = "LEARN_MORE",
    ) -> str:
        """Create an AdCreative on Meta. Returns the creative ID."""
        link_data: dict[str, Any] = {
            "image_hash": image_hash,
            "call_to_action": {"type": call_to_action_type},
        }
        if link_url:
            link_data["link"] = link_url
        if message:
            link_data["message"] = message

        creative_params: dict[str, Any] = {
            AdCreative.Field.name: name,
            AdCreative.Field.object_story_spec: {
                "page_id": page_id,
                "link_data": link_data,
            },
        }

        try:
            creative = self._account.create_ad_creative(params=creative_params)
            return creative["id"]
        except FacebookRequestError as exc:
            raise CreativeCreationError(
                f"Failed to create ad creative '{name}': {exc}",
                details={
                    "name": name,
                    "error_code": exc.api_error_code(),
                    "error_message": exc.api_error_message(),
                },
            ) from exc
        except Exception as exc:
            raise CreativeCreationError(
                f"Failed to create ad creative '{name}': {exc}",
                details={"name": name, "error": str(exc)},
            ) from exc

    def _create_ad(
        self,
        name: str,
        adset_id: str,
        creative_id: str,
        status: str = "PAUSED",
    ) -> str:
        """Create an Ad object on Meta. Returns the ad ID."""
        ad_params: dict[str, Any] = {
            Ad.Field.name: name,
            Ad.Field.adset_id: adset_id,
            Ad.Field.creative: {"creative_id": creative_id},
            Ad.Field.status: status,
        }

        try:
            ad = self._account.create_ad(params=ad_params)
            return ad["id"]
        except FacebookRequestError as exc:
            raise CreativeCreationError(
                f"Failed to create ad '{name}': {exc}",
                details={
                    "name": name,
                    "adset_id": adset_id,
                    "error_code": exc.api_error_code(),
                    "error_message": exc.api_error_message(),
                },
            ) from exc
        except Exception as exc:
            raise CreativeCreationError(
                f"Failed to create ad '{name}': {exc}",
                details={"name": name, "adset_id": adset_id, "error": str(exc)},
            ) from exc

    # ------------------------------------------------------------------
    # create_campaign
    # ------------------------------------------------------------------

    def _sync_create_campaign(
        self, plan: ExecutionPlan, idempotency_key: str
    ) -> ExecutionResult:
        """Synchronous campaign creation (called via asyncio.to_thread)."""
        meta_objective = OBJECTIVE_MAP[plan.objective.lower()]
        optimization_goal = _map_optimization_goal(meta_objective)

        # Step 1: Create the campaign
        campaign_params = {
            Campaign.Field.name: plan.campaign_name,
            Campaign.Field.objective: meta_objective,
            Campaign.Field.status: Campaign.Status.paused,
            Campaign.Field.special_ad_categories: [],
        }
        if plan.metadata.get("special_ad_categories"):
            campaign_params[Campaign.Field.special_ad_categories] = plan.metadata[
                "special_ad_categories"
            ]

        campaign = self._account.create_campaign(params=campaign_params)
        campaign_id = campaign["id"]

        # Step 2: Create ad sets
        external_ids: dict[str, str] = {"campaign": campaign_id}
        adset_id_map: dict[str, str] = {}  # ad_set_spec.name → adset_id

        for ad_set_spec in plan.ad_sets:
            adset_params: dict[str, Any] = {
                AdSet.Field.name: ad_set_spec.name,
                AdSet.Field.campaign_id: campaign_id,
                AdSet.Field.daily_budget: _dollars_to_cents(ad_set_spec.daily_budget),
                AdSet.Field.billing_event: "IMPRESSIONS",
                AdSet.Field.optimization_goal: optimization_goal,
                AdSet.Field.bid_strategy: _map_bid_strategy(ad_set_spec.bid_strategy),
                AdSet.Field.status: AdSet.Status.paused,
            }

            # Apply targeting if provided
            if ad_set_spec.targeting:
                adset_params[AdSet.Field.targeting] = ad_set_spec.targeting
            else:
                # Meta requires targeting; provide a minimal default
                adset_params[AdSet.Field.targeting] = {
                    "geo_locations": {"countries": ["US"]},
                }

            adset = self._account.create_ad_set(params=adset_params)
            adset_id = adset["id"]
            external_ids[ad_set_spec.name] = adset_id
            adset_id_map[ad_set_spec.name] = adset_id

        # Step 3: Create creatives and ads for ad sets that have creative data
        creatives_created = 0
        ads_created = 0
        page_id = self._page_id

        for ad_set_spec in plan.ad_sets:
            creative = ad_set_spec.creative
            image_url = creative.get("image_url", "")
            image_hash = creative.get("image_hash", "")

            if not image_url and not image_hash:
                continue  # No creative data — skip (backward compatible)

            # 3a: Get image hash (upload if needed)
            if image_url and not image_hash:
                image_hash = self._upload_image_from_url(image_url)

            # 3b: Create AdCreative
            creative_name = f"{ad_set_spec.name} - Creative"
            creative_page_id = creative.get("page_id", page_id)
            link_url = creative.get("link_url", "")
            message = creative.get("message", "")
            cta = creative.get("call_to_action_type", "LEARN_MORE")

            creative_id = self._create_ad_creative(
                name=creative_name,
                image_hash=image_hash,
                page_id=creative_page_id,
                link_url=link_url,
                message=message,
                call_to_action_type=cta,
            )
            external_ids[f"{ad_set_spec.name}_creative"] = creative_id
            creatives_created += 1

            # 3c: Create Ad
            ad_name = f"{ad_set_spec.name} - Ad"
            adset_id = adset_id_map[ad_set_spec.name]
            ad_id = self._create_ad(
                name=ad_name,
                adset_id=adset_id,
                creative_id=creative_id,
            )
            external_ids[f"{ad_set_spec.name}_ad"] = ad_id
            ads_created += 1

        # Build links
        links = {
            "campaign_url": _ads_manager_url(campaign_id, self._ad_account_id),
        }

        return ExecutionResult(
            success=True,
            platform=Platform.META,
            external_campaign_id=campaign_id,
            external_ids=external_ids,
            links=links,
            raw_response={
                "campaign_id": campaign_id,
                "objective": meta_objective,
                "ad_sets_created": len(plan.ad_sets),
                "creatives_created": creatives_created,
                "ads_created": ads_created,
            },
        )

    async def create_campaign(
        self, plan: ExecutionPlan, *, idempotency_key: str
    ) -> ExecutionResult:
        # Validate first
        issues = await self.validate_plan(plan)
        errors = [i for i in issues if i.severity == "error"]
        if errors:
            return ExecutionResult(
                success=False,
                platform=Platform.META,
                validation_issues=issues,
                error="Validation failed",
            )

        try:
            return await asyncio.to_thread(
                self._sync_create_campaign, plan, idempotency_key
            )
        except FacebookRequestError as e:
            return ExecutionResult(
                success=False,
                platform=Platform.META,
                error=str(e),
                raw_response={
                    "error_code": e.api_error_code(),
                    "error_message": e.api_error_message(),
                },
            )
        except PlatformError as e:
            return ExecutionResult(
                success=False,
                platform=Platform.META,
                error=str(e),
                raw_response=e.details,
            )

    # ------------------------------------------------------------------
    # pause_campaign
    # ------------------------------------------------------------------

    def _sync_pause_campaign(self, external_campaign_id: str) -> ExecutionResult:
        campaign = Campaign(external_campaign_id)
        campaign.api_update(params={Campaign.Field.status: Campaign.Status.paused})
        return ExecutionResult(
            success=True,
            platform=Platform.META,
            external_campaign_id=external_campaign_id,
            raw_response={"status": "paused"},
        )

    async def pause_campaign(
        self, external_campaign_id: str, *, platform: Platform
    ) -> ExecutionResult:
        try:
            return await asyncio.to_thread(
                self._sync_pause_campaign, external_campaign_id
            )
        except FacebookRequestError as e:
            return ExecutionResult(
                success=False,
                platform=Platform.META,
                external_campaign_id=external_campaign_id,
                error=str(e),
                raw_response={
                    "error_code": e.api_error_code(),
                    "error_message": e.api_error_message(),
                },
            )

    # ------------------------------------------------------------------
    # resume_campaign
    # ------------------------------------------------------------------

    def _sync_resume_campaign(self, external_campaign_id: str) -> ExecutionResult:
        campaign = Campaign(external_campaign_id)
        campaign.api_update(params={Campaign.Field.status: Campaign.Status.active})
        return ExecutionResult(
            success=True,
            platform=Platform.META,
            external_campaign_id=external_campaign_id,
            raw_response={"status": "active"},
        )

    async def resume_campaign(
        self, external_campaign_id: str, *, platform: Platform
    ) -> ExecutionResult:
        try:
            return await asyncio.to_thread(
                self._sync_resume_campaign, external_campaign_id
            )
        except FacebookRequestError as e:
            return ExecutionResult(
                success=False,
                platform=Platform.META,
                external_campaign_id=external_campaign_id,
                error=str(e),
                raw_response={
                    "error_code": e.api_error_code(),
                    "error_message": e.api_error_message(),
                },
            )

    # ------------------------------------------------------------------
    # update_budget
    # ------------------------------------------------------------------

    def _sync_update_budget(
        self, external_campaign_id: str, new_budget: float
    ) -> ExecutionResult:
        campaign = Campaign(external_campaign_id)
        campaign.api_update(
            params={Campaign.Field.daily_budget: _dollars_to_cents(new_budget)}
        )
        return ExecutionResult(
            success=True,
            platform=Platform.META,
            external_campaign_id=external_campaign_id,
            raw_response={
                "new_budget": new_budget,
                "new_budget_cents": _dollars_to_cents(new_budget),
                "status": "budget_updated",
            },
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
                platform=Platform.META,
                external_campaign_id=external_campaign_id,
                error="Budget must be positive",
            )

        try:
            return await asyncio.to_thread(
                self._sync_update_budget, external_campaign_id, new_budget
            )
        except FacebookRequestError as e:
            return ExecutionResult(
                success=False,
                platform=Platform.META,
                external_campaign_id=external_campaign_id,
                error=str(e),
                raw_response={
                    "error_code": e.api_error_code(),
                    "error_message": e.api_error_message(),
                },
            )

#!/usr/bin/env python3
"""Live integration test for Meta Ads campaign creation.

Creates a PAUSED test campaign on your real Meta Ads account to verify
that credentials and the adapter are working end-to-end.

Usage:
    # Create campaign and keep it (verify in Ads Manager)
    python3 scripts/test_meta_live.py

    # Create campaign and auto-delete it after verification
    python3 scripts/test_meta_live.py --cleanup

    # Custom campaign name
    python3 scripts/test_meta_live.py --name "My Test Campaign"

Environment variables required (set in infra/.env):
    META_ACCESS_TOKEN     - Meta Marketing API access token
    META_AD_ACCOUNT_ID    - Ad account ID (format: act_123456789)
    META_PAGE_ID          - Facebook Page ID (needed for creative uploads)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import os

# Ensure app is importable when running from any directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.settings import settings
from app.platforms.meta_ads import MetaAdsAdapter
from app.platforms.base import AdSetSpec, ExecutionPlan, Platform


def check_credentials() -> bool:
    """Verify that required Meta credentials are set."""
    ok = True
    for name, value in [
        ("META_ACCESS_TOKEN", settings.META_ACCESS_TOKEN),
        ("META_AD_ACCOUNT_ID", settings.META_AD_ACCOUNT_ID),
    ]:
        if not value:
            print(f"  ERROR: {name} is not set in infra/.env")
            ok = False
        else:
            display = "***" + value[-10:] if len(value) > 10 else value
            print(f"  {name}: {display}")

    # Optional but recommended
    page_id = settings.META_PAGE_ID
    print(f"  META_PAGE_ID: {page_id or '(not set — creative uploads will fail)'}")

    return ok


async def run_test(campaign_name: str, cleanup: bool) -> bool:
    """Run the live integration test. Returns True on success."""

    print("\n1. Checking credentials...")
    if not check_credentials():
        return False

    print("\n2. Creating MetaAdsAdapter...")
    adapter = MetaAdsAdapter(
        access_token=settings.META_ACCESS_TOKEN,
        app_secret=settings.META_APP_SECRET,
        ad_account_id=settings.META_AD_ACCOUNT_ID,
        page_id=settings.META_PAGE_ID,
    )
    print("   OK")

    print("\n3. Building execution plan...")
    plan = ExecutionPlan(
        platform=Platform.META,
        campaign_name=campaign_name,
        objective="traffic",
        total_budget=10.0,
        currency="USD",
        ad_sets=[
            AdSetSpec(
                name="Test Ad Set - US Traffic",
                daily_budget=5.0,
                targeting={"geo_locations": {"countries": ["US"]}},
            ),
        ],
    )
    print(f"   Campaign: {plan.campaign_name}")
    print(f"   Objective: traffic -> OUTCOME_TRAFFIC")
    print(f"   Ad sets: {len(plan.ad_sets)}")

    print("\n4. Validating plan...")
    issues = await adapter.validate_plan(plan)
    if issues:
        for issue in issues:
            print(f"   [{issue.severity}] {issue.field}: {issue.message}")
        if any(i.severity == "error" for i in issues):
            print("   Validation failed. Aborting.")
            return False
    else:
        print("   No issues.")

    print("\n5. Creating campaign (PAUSED)...")
    result = await adapter.create_campaign(plan, idempotency_key="live-test")

    if not result.success:
        print(f"   FAILED: {result.error}")
        print(f"   Details: {result.raw_response}")
        return False

    campaign_id = result.external_campaign_id
    adset_id = result.external_ids.get("Test Ad Set - US Traffic", "?")
    url = result.links.get("campaign_url", "")

    print(f"   Campaign ID: {campaign_id}")
    print(f"   Ad Set ID:   {adset_id}")
    print(f"   Status:      PAUSED (will NOT spend money)")
    print(f"   Ads Manager: {url}")

    print("\n6. Testing pause API...")
    pause_result = await adapter.pause_campaign(campaign_id, platform=Platform.META)
    print(f"   Pause: {'OK' if pause_result.success else 'FAILED — ' + str(pause_result.error)}")

    if cleanup:
        print(f"\n7. Deleting test campaign {campaign_id}...")
        try:
            from facebook_business.adobjects.campaign import Campaign as FBCampaign
            fb_campaign = FBCampaign(campaign_id)
            fb_campaign.remote_delete()
            print("   Deleted.")
        except Exception as e:
            print(f"   WARNING: Could not delete: {e}")
            print(f"   Delete manually from Ads Manager.")
    else:
        print(f"\n7. Campaign kept — verify at:")
        print(f"   {url}")
        print(f"   Delete it from Ads Manager when you're done.")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Live integration test for Meta Ads campaign creation"
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete the test campaign after creation (default: keep it)",
    )
    parser.add_argument(
        "--name",
        default="[TEST] DiMark Live Integration Test",
        help="Campaign name (default: '[TEST] DiMark Live Integration Test')",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("META ADS — LIVE INTEGRATION TEST")
    print("=" * 60)

    success = asyncio.run(run_test(args.name, args.cleanup))

    print("\n" + "=" * 60)
    if success:
        print("RESULT: PASSED")
    else:
        print("RESULT: FAILED")
    print("=" * 60)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

from __future__ import annotations

from app.platforms.base import AdPlatformAdapter, Platform
from app.platforms.dry_run import DryRunExecutor


def get_platform_adapter(
    platform: Platform | str, *, dry_run: bool = True
) -> AdPlatformAdapter:
    """Return the appropriate platform adapter.

    When dry_run=True, all platforms use the DryRunExecutor.
    Otherwise, routes to the real platform adapter (Meta supported).
    """
    if dry_run:
        return DryRunExecutor()

    # Route to real adapters
    if platform in (Platform.META, "meta"):
        from app.platforms.meta_ads import MetaAdsAdapter
        from app.settings import settings

        return MetaAdsAdapter(
            access_token=settings.META_ACCESS_TOKEN,
            app_secret=settings.META_APP_SECRET,
            ad_account_id=settings.META_AD_ACCOUNT_ID,
            page_id=settings.META_PAGE_ID,
        )

    raise NotImplementedError(
        f"Real adapter for {platform} not yet implemented. Use dry_run=True."
    )

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ChannelParams:
    base_cpm: Decimal
    base_ctr: Decimal
    base_cvr: Decimal
    base_aov: Decimal
    diminishing_k: Decimal
    spend_scale: Decimal
    noise_sigma: Decimal
    influencer_hit_rate: Decimal | None = None
    influencer_multiplier: Decimal | None = None


DEFAULT_CHANNEL_PARAMS: dict[str, ChannelParams] = {
    "meta": ChannelParams(
        base_cpm=Decimal("12"),
        base_ctr=Decimal("0.012"),
        base_cvr=Decimal("0.018"),
        base_aov=Decimal("60"),
        diminishing_k=Decimal("0.4"),
        spend_scale=Decimal("10000"),
        noise_sigma=Decimal("0.08"),
    ),
    "google": ChannelParams(
        base_cpm=Decimal("14"),
        base_ctr=Decimal("0.018"),
        base_cvr=Decimal("0.028"),
        base_aov=Decimal("75"),
        diminishing_k=Decimal("0.35"),
        spend_scale=Decimal("12000"),
        noise_sigma=Decimal("0.06"),
    ),
    "x": ChannelParams(
        base_cpm=Decimal("9"),
        base_ctr=Decimal("0.008"),
        base_cvr=Decimal("0.012"),
        base_aov=Decimal("55"),
        diminishing_k=Decimal("0.5"),
        spend_scale=Decimal("6000"),
        noise_sigma=Decimal("0.1"),
    ),
    "influencer": ChannelParams(
        base_cpm=Decimal("20"),
        base_ctr=Decimal("0.02"),
        base_cvr=Decimal("0.03"),
        base_aov=Decimal("80"),
        diminishing_k=Decimal("0.6"),
        spend_scale=Decimal("8000"),
        noise_sigma=Decimal("0.12"),
        influencer_hit_rate=Decimal("0.35"),
        influencer_multiplier=Decimal("2.5"),
    ),
    "linkedin": ChannelParams(
        base_cpm=Decimal("25"),
        base_ctr=Decimal("0.006"),
        base_cvr=Decimal("0.02"),
        base_aov=Decimal("90"),
        diminishing_k=Decimal("0.4"),
        spend_scale=Decimal("7000"),
        noise_sigma=Decimal("0.08"),
    ),
    "youtube": ChannelParams(
        base_cpm=Decimal("18"),
        base_ctr=Decimal("0.007"),
        base_cvr=Decimal("0.015"),
        base_aov=Decimal("70"),
        diminishing_k=Decimal("0.45"),
        spend_scale=Decimal("9000"),
        noise_sigma=Decimal("0.09"),
    ),
    "tiktok": ChannelParams(
        base_cpm=Decimal("10"),
        base_ctr=Decimal("0.015"),
        base_cvr=Decimal("0.02"),
        base_aov=Decimal("55"),
        diminishing_k=Decimal("0.5"),
        spend_scale=Decimal("9000"),
        noise_sigma=Decimal("0.1"),
    ),
}

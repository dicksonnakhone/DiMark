from __future__ import annotations

from typing import TypedDict


class VariantTotals(TypedDict):
    spend: float
    impressions: int
    clicks: int
    conversions: int
    revenue: float


class VariantResult(TypedDict):
    totals: VariantTotals
    kpis: dict[str, float | None]


class ExperimentResultsPayload(TypedDict):
    variants: dict[str, VariantResult]
    allocations: dict[str, dict[str, str]]

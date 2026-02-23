"""Metrics collection, KPI computation, and trend analysis services.

Follows patterns from ``app.services.measurement`` — safe division,
Decimal-based arithmetic, ChannelSnapshot queries.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ChannelSnapshot,
    DerivedKPI,
    RawMetric,
    TrendIndicator,
)

# ---------------------------------------------------------------------------
# Helpers (same as measurement.py for consistency)
# ---------------------------------------------------------------------------

_METRIC_DIMENSIONS = ("spend", "impressions", "clicks", "conversions", "revenue")

_METRIC_UNITS = {
    "spend": "currency",
    "impressions": "count",
    "clicks": "count",
    "conversions": "count",
    "revenue": "currency",
}


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _safe_div(numerator: Decimal, denominator: Decimal) -> float | None:
    if denominator == 0:
        return None
    return float(numerator / denominator)


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


# ---------------------------------------------------------------------------
# MetricsCollector
# ---------------------------------------------------------------------------


class MetricsCollector:
    """Queries ChannelSnapshot rows and creates RawMetric entries."""

    def collect(
        self,
        db: Session,
        campaign_id: Any,
        *,
        window_start: date | None = None,
        window_end: date | None = None,
    ) -> list[RawMetric]:
        """Collect raw metrics from snapshots for *campaign_id*."""
        query = select(ChannelSnapshot).where(
            ChannelSnapshot.campaign_id == campaign_id
        )
        if window_start is not None:
            query = query.where(ChannelSnapshot.window_start >= window_start)
        if window_end is not None:
            query = query.where(ChannelSnapshot.window_end <= window_end)

        snapshots = db.execute(query).scalars().all()

        now = datetime.now(tz=timezone.utc)
        raw_metrics: list[RawMetric] = []

        for snap in snapshots:
            for dim in _METRIC_DIMENSIONS:
                value = getattr(snap, dim, None)
                if value is None:
                    continue
                metric = RawMetric(
                    campaign_id=campaign_id,
                    channel=snap.channel,
                    metric_name=dim,
                    metric_value=float(value),
                    metric_unit=_METRIC_UNITS[dim],
                    source="snapshot",
                    collected_at=now,
                    window_start=snap.window_start,
                    window_end=snap.window_end,
                    metadata_json={},
                )
                raw_metrics.append(metric)
                db.add(metric)

        db.flush()
        return raw_metrics


# ---------------------------------------------------------------------------
# KPICalculator
# ---------------------------------------------------------------------------


class KPICalculator:
    """Computes derived KPIs from raw metrics.

    KPIs: CPA (= CAC), ROAS, CTR, CVR, CPM, CPC — per-channel and
    campaign-level.
    """

    def compute(
        self,
        db: Session,
        campaign_id: Any,
        raw_metrics: list[RawMetric] | None = None,
        *,
        window_start: date | None = None,
        window_end: date | None = None,
    ) -> list[DerivedKPI]:
        """Compute KPIs and persist ``DerivedKPI`` rows."""
        if raw_metrics is None:
            query = select(RawMetric).where(RawMetric.campaign_id == campaign_id)
            if window_start is not None:
                query = query.where(RawMetric.window_start >= window_start)
            if window_end is not None:
                query = query.where(RawMetric.window_end <= window_end)
            raw_metrics = list(db.execute(query).scalars().all())

        # Aggregate by channel
        channel_totals: dict[str, dict[str, Decimal]] = defaultdict(
            lambda: {d: Decimal("0") for d in _METRIC_DIMENSIONS}
        )
        for m in raw_metrics:
            channel_totals[m.channel][m.metric_name] += _to_decimal(m.metric_value)

        # Also compute campaign-level totals
        campaign_totals: dict[str, Decimal] = {d: Decimal("0") for d in _METRIC_DIMENSIONS}
        for bucket in channel_totals.values():
            for dim in _METRIC_DIMENSIONS:
                campaign_totals[dim] += bucket[dim]

        kpi_rows: list[DerivedKPI] = []

        # Per-channel KPIs
        for channel, totals in channel_totals.items():
            kpis = self._calculate_kpis(totals)
            for kpi_name, kpi_value in kpis.items():
                if kpi_value is None:
                    continue
                row = DerivedKPI(
                    campaign_id=campaign_id,
                    channel=channel,
                    kpi_name=kpi_name,
                    kpi_value=kpi_value,
                    window_start=window_start,
                    window_end=window_end,
                    input_metrics_json={k: float(v) for k, v in totals.items()},
                )
                kpi_rows.append(row)
                db.add(row)

        # Campaign-level KPIs (channel = None)
        campaign_kpis = self._calculate_kpis(campaign_totals)
        for kpi_name, kpi_value in campaign_kpis.items():
            if kpi_value is None:
                continue
            row = DerivedKPI(
                campaign_id=campaign_id,
                channel=None,
                kpi_name=kpi_name,
                kpi_value=kpi_value,
                window_start=window_start,
                window_end=window_end,
                input_metrics_json={k: float(v) for k, v in campaign_totals.items()},
            )
            kpi_rows.append(row)
            db.add(row)

        db.flush()
        return kpi_rows

    @staticmethod
    def _calculate_kpis(totals: dict[str, Decimal]) -> dict[str, float | None]:
        spend = totals.get("spend", Decimal("0"))
        impressions = totals.get("impressions", Decimal("0"))
        clicks = totals.get("clicks", Decimal("0"))
        conversions = totals.get("conversions", Decimal("0"))
        revenue = totals.get("revenue", Decimal("0"))

        return {
            "ctr": _safe_div(clicks, impressions),
            "cvr": _safe_div(conversions, clicks),
            "cpc": _safe_div(spend, clicks),
            "cpm": _safe_div(spend * Decimal("1000"), impressions),
            "cpa": _safe_div(spend, conversions),
            "roas": _safe_div(revenue, spend),
        }


# ---------------------------------------------------------------------------
# TrendAnalyzer
# ---------------------------------------------------------------------------


class TrendAnalyzer:
    """Compares current-period KPIs to prior-period KPIs.

    Stores ``TrendIndicator`` rows with direction / magnitude / confidence.
    """

    def analyze(
        self,
        db: Session,
        campaign_id: Any,
        *,
        period_days: int = 7,
    ) -> list[TrendIndicator]:
        """Compute trends by comparing the two most recent KPI batches."""
        now = datetime.now(tz=timezone.utc).date()
        current_end = now
        current_start = now - timedelta(days=period_days)
        previous_end = current_start
        previous_start = previous_end - timedelta(days=period_days)

        current_kpis = self._load_kpis(db, campaign_id, current_start, current_end)
        previous_kpis = self._load_kpis(db, campaign_id, previous_start, previous_end)

        trends: list[TrendIndicator] = []

        # Compare by (channel, kpi_name)
        all_keys = set(current_kpis.keys()) & set(previous_kpis.keys())
        for key in all_keys:
            channel, kpi_name = key
            current_val = current_kpis[key]
            previous_val = previous_kpis[key]

            if previous_val == 0:
                continue

            change = (current_val - previous_val) / abs(previous_val)

            if change > 0.02:
                direction = "improving"
            elif change < -0.02:
                direction = "declining"
            else:
                direction = "stable"

            # Simple confidence heuristic: higher with more data points
            confidence = min(0.9, 0.5 + abs(change))

            trend = TrendIndicator(
                campaign_id=campaign_id,
                channel=channel,
                kpi_name=kpi_name,
                direction=direction,
                magnitude=round(abs(change), 4),
                period_days=period_days,
                current_value=round(current_val, 6),
                previous_value=round(previous_val, 6),
                confidence=round(confidence, 4),
                analysis_json={
                    "change_pct": round(change, 4),
                    "period_start": current_start.isoformat(),
                    "period_end": current_end.isoformat(),
                    "prev_start": previous_start.isoformat(),
                    "prev_end": previous_end.isoformat(),
                },
            )
            trends.append(trend)
            db.add(trend)

        db.flush()
        return trends

    @staticmethod
    def _load_kpis(
        db: Session,
        campaign_id: Any,
        start: date,
        end: date,
    ) -> dict[tuple[str | None, str], float]:
        """Load KPIs grouped by (channel, kpi_name) for a date window."""
        query = select(DerivedKPI).where(
            DerivedKPI.campaign_id == campaign_id,
        )
        # Filter by window overlap
        query = query.where(
            DerivedKPI.window_start >= start,
            DerivedKPI.window_end <= end,
        )
        rows = db.execute(query).scalars().all()

        # Average KPI values when multiple rows exist per (channel, kpi_name)
        sums: dict[tuple[str | None, str], float] = defaultdict(float)
        counts: dict[tuple[str | None, str], int] = defaultdict(int)

        for row in rows:
            key = (row.channel, row.kpi_name)
            sums[key] += _to_float(row.kpi_value)
            counts[key] += 1

        return {k: sums[k] / counts[k] for k in sums}

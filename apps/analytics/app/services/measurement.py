from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ChannelSnapshot, MeasurementReport


def _to_decimal(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _safe_div(numerator: Decimal, denominator: Decimal) -> float | None:
    if denominator == 0:
        return None
    return float(numerator / denominator)


def _to_float(value: Decimal | int | None) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def compute_report(
    db: Session,
    campaign_id,
    window_start: date | None = None,
    window_end: date | None = None,
) -> MeasurementReport:
    query = select(ChannelSnapshot).where(ChannelSnapshot.campaign_id == campaign_id)
    if window_start is not None:
        query = query.where(ChannelSnapshot.window_start >= window_start)
    if window_end is not None:
        query = query.where(ChannelSnapshot.window_end <= window_end)

    snapshots = db.execute(query).scalars().all()

    totals = {
        "spend": Decimal("0"),
        "impressions": 0,
        "clicks": 0,
        "conversions": 0,
        "revenue": Decimal("0"),
    }

    channel_totals: dict[str, dict] = defaultdict(
        lambda: {
            "spend": Decimal("0"),
            "impressions": 0,
            "clicks": 0,
            "conversions": 0,
            "revenue": Decimal("0"),
        }
    )

    for snapshot in snapshots:
        spend = _to_decimal(snapshot.spend)
        revenue = _to_decimal(snapshot.revenue)

        totals["spend"] += spend
        totals["impressions"] += int(snapshot.impressions or 0)
        totals["clicks"] += int(snapshot.clicks or 0)
        totals["conversions"] += int(snapshot.conversions or 0)
        totals["revenue"] += revenue

        bucket = channel_totals[snapshot.channel]
        bucket["spend"] += spend
        bucket["impressions"] += int(snapshot.impressions or 0)
        bucket["clicks"] += int(snapshot.clicks or 0)
        bucket["conversions"] += int(snapshot.conversions or 0)
        bucket["revenue"] += revenue

    total_spend = totals["spend"]
    total_impressions = Decimal(str(totals["impressions"]))
    total_clicks = Decimal(str(totals["clicks"]))
    total_conversions = Decimal(str(totals["conversions"]))
    total_revenue = totals["revenue"]

    kpis = {
        "ctr": _safe_div(total_clicks, total_impressions),
        "cvr": _safe_div(total_conversions, total_clicks),
        "cpc": _safe_div(total_spend, total_clicks),
        "cpm": _safe_div(total_spend * Decimal("1000"), total_impressions),
        "cac": _safe_div(total_spend, total_conversions),
        "roas": _safe_div(total_revenue, total_spend),
    }

    by_channel = []
    for channel, bucket in channel_totals.items():
        spend = bucket["spend"]
        impressions = Decimal(str(bucket["impressions"]))
        clicks = Decimal(str(bucket["clicks"]))
        conversions = Decimal(str(bucket["conversions"]))
        revenue = bucket["revenue"]

        spend_share = _safe_div(spend, total_spend) if total_spend != 0 else None
        conv_share = _safe_div(conversions, total_conversions) if total_conversions != 0 else None
        efficiency_index = (
            _safe_div(Decimal(str(conv_share)), Decimal(str(spend_share)))
            if spend_share not in (None, 0) and conv_share is not None
            else None
        )

        by_channel.append(
            {
                "channel": channel,
                "totals": {
                    "spend": _to_float(spend),
                    "impressions": int(bucket["impressions"]),
                    "clicks": int(bucket["clicks"]),
                    "conversions": int(bucket["conversions"]),
                    "revenue": _to_float(revenue),
                },
                "kpis": {
                    "ctr": _safe_div(clicks, impressions),
                    "cvr": _safe_div(conversions, clicks),
                    "cpc": _safe_div(spend, clicks),
                    "cpm": _safe_div(spend * Decimal("1000"), impressions),
                    "cac": _safe_div(spend, conversions),
                    "roas": _safe_div(revenue, spend),
                    "spend_share": spend_share,
                    "conversion_share": conv_share,
                    "efficiency_index": efficiency_index,
                },
            }
        )

    report_json = {
        "campaign_id": str(campaign_id),
        "window": {
            "start": window_start.isoformat() if window_start else None,
            "end": window_end.isoformat() if window_end else None,
        },
        "totals": {
            "spend": _to_float(total_spend),
            "impressions": int(totals["impressions"]),
            "clicks": int(totals["clicks"]),
            "conversions": int(totals["conversions"]),
            "revenue": _to_float(total_revenue),
        },
        "kpis": kpis,
        "by_channel": by_channel,
    }

    report = MeasurementReport(
        campaign_id=campaign_id,
        window_start=window_start,
        window_end=window_end,
        total_spend=_to_float(total_spend),
        total_impressions=int(totals["impressions"]),
        total_clicks=int(totals["clicks"]),
        total_conversions=int(totals["conversions"]),
        total_revenue=_to_float(total_revenue),
        metrics_json=report_json,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report

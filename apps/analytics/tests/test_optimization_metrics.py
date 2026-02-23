"""Tests for metrics collection, KPI computation, and trend analysis (~18 tests)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db import Base
from app.models import Campaign, ChannelSnapshot, DerivedKPI, RawMetric
from app.services.optimization.metrics import (
    KPICalculator,
    MetricsCollector,
    TrendAnalyzer,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_db() -> tuple:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    return engine, TestingSession


def _make_campaign(db: Session, **kwargs) -> Campaign:
    defaults = dict(name="Test Campaign", objective="paid_conversions")
    defaults.update(kwargs)
    campaign = Campaign(**defaults)
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


def _add_snapshot(
    db: Session,
    campaign_id,
    channel: str = "meta",
    spend: float = 1000.0,
    impressions: int = 100_000,
    clicks: int = 1000,
    conversions: int = 50,
    revenue: float = 5000.0,
    window_start: date | None = None,
    window_end: date | None = None,
) -> ChannelSnapshot:
    snap = ChannelSnapshot(
        campaign_id=campaign_id,
        channel=channel,
        spend=spend,
        impressions=impressions,
        clicks=clicks,
        conversions=conversions,
        revenue=revenue,
        window_start=window_start,
        window_end=window_end,
    )
    db.add(snap)
    db.commit()
    db.refresh(snap)
    return snap


# ---------------------------------------------------------------------------
# MetricsCollector tests
# ---------------------------------------------------------------------------


class TestMetricsCollector:
    def test_collect_basic(self):
        _, Session = _make_db()
        db = Session()
        campaign = _make_campaign(db)
        _add_snapshot(db, campaign.id)

        collector = MetricsCollector()
        metrics = collector.collect(db, campaign.id)

        assert len(metrics) == 5  # spend, impressions, clicks, conversions, revenue
        names = {m.metric_name for m in metrics}
        assert names == {"spend", "impressions", "clicks", "conversions", "revenue"}
        db.close()

    def test_collect_empty(self):
        _, Session = _make_db()
        db = Session()
        campaign = _make_campaign(db)

        collector = MetricsCollector()
        metrics = collector.collect(db, campaign.id)
        assert len(metrics) == 0
        db.close()

    def test_collect_windowed(self):
        _, Session = _make_db()
        db = Session()
        campaign = _make_campaign(db)
        _add_snapshot(
            db, campaign.id, channel="meta",
            window_start=date(2025, 1, 1), window_end=date(2025, 1, 7),
        )
        _add_snapshot(
            db, campaign.id, channel="meta",
            window_start=date(2025, 1, 8), window_end=date(2025, 1, 14),
        )

        collector = MetricsCollector()
        # Collect only second week
        metrics = collector.collect(
            db, campaign.id,
            window_start=date(2025, 1, 8),
            window_end=date(2025, 1, 14),
        )
        assert len(metrics) == 5  # only second snapshot
        db.close()

    def test_metrics_valid_values(self):
        _, Session = _make_db()
        db = Session()
        campaign = _make_campaign(db)
        _add_snapshot(db, campaign.id, spend=500.0, clicks=200)

        collector = MetricsCollector()
        metrics = collector.collect(db, campaign.id)

        spend_metric = next(m for m in metrics if m.metric_name == "spend")
        assert float(spend_metric.metric_value) == 500.0
        assert spend_metric.metric_unit == "currency"

        clicks_metric = next(m for m in metrics if m.metric_name == "clicks")
        assert float(clicks_metric.metric_value) == 200.0
        assert clicks_metric.metric_unit == "count"
        db.close()

    def test_metrics_extreme_values(self):
        _, Session = _make_db()
        db = Session()
        campaign = _make_campaign(db)
        _add_snapshot(db, campaign.id, spend=0.0, impressions=0, clicks=0, conversions=0, revenue=0.0)

        collector = MetricsCollector()
        metrics = collector.collect(db, campaign.id)
        # All zero values should still be collected
        assert len(metrics) == 5
        for m in metrics:
            assert float(m.metric_value) == 0.0
        db.close()


# ---------------------------------------------------------------------------
# KPICalculator tests
# ---------------------------------------------------------------------------


class TestKPICalculator:
    def test_basic_kpi_computation(self):
        _, Session = _make_db()
        db = Session()
        campaign = _make_campaign(db)
        _add_snapshot(db, campaign.id, spend=1000.0, impressions=100_000, clicks=1000, conversions=50, revenue=5000.0)

        collector = MetricsCollector()
        raw = collector.collect(db, campaign.id)

        calculator = KPICalculator()
        kpis = calculator.compute(db, campaign.id, raw)

        # Should have per-channel + campaign-level KPIs
        assert len(kpis) > 0

        # Find campaign-level CPA
        campaign_cpa = next((k for k in kpis if k.channel is None and k.kpi_name == "cpa"), None)
        assert campaign_cpa is not None
        assert abs(float(campaign_cpa.kpi_value) - 20.0) < 0.01  # 1000/50

        # Find campaign-level ROAS
        campaign_roas = next((k for k in kpis if k.channel is None and k.kpi_name == "roas"), None)
        assert campaign_roas is not None
        assert abs(float(campaign_roas.kpi_value) - 5.0) < 0.01  # 5000/1000
        db.close()

    def test_zero_denominators(self):
        _, Session = _make_db()
        db = Session()
        campaign = _make_campaign(db)
        _add_snapshot(db, campaign.id, spend=0.0, impressions=0, clicks=0, conversions=0, revenue=0.0)

        collector = MetricsCollector()
        raw = collector.collect(db, campaign.id)

        calculator = KPICalculator()
        kpis = calculator.compute(db, campaign.id, raw)

        # All KPIs with zero denominators should produce None (not be created)
        # Only KPIs with valid values should exist
        for kpi in kpis:
            # All should have valid non-None values since None KPIs are skipped
            assert kpi.kpi_value is not None
        db.close()

    def test_per_channel_kpis(self):
        _, Session = _make_db()
        db = Session()
        campaign = _make_campaign(db)
        _add_snapshot(db, campaign.id, channel="meta", spend=1000.0, clicks=500, conversions=25)
        _add_snapshot(db, campaign.id, channel="google", spend=500.0, clicks=100, conversions=10)

        collector = MetricsCollector()
        raw = collector.collect(db, campaign.id)

        calculator = KPICalculator()
        kpis = calculator.compute(db, campaign.id, raw)

        meta_cpa = next(
            (k for k in kpis if k.channel == "meta" and k.kpi_name == "cpa"), None
        )
        google_cpa = next(
            (k for k in kpis if k.channel == "google" and k.kpi_name == "cpa"), None
        )
        assert meta_cpa is not None
        assert google_cpa is not None
        assert abs(float(meta_cpa.kpi_value) - 40.0) < 0.01  # 1000/25
        assert abs(float(google_cpa.kpi_value) - 50.0) < 0.01  # 500/10
        db.close()

    def test_campaign_level_kpis(self):
        _, Session = _make_db()
        db = Session()
        campaign = _make_campaign(db)
        _add_snapshot(db, campaign.id, channel="meta", spend=1000.0, impressions=50_000)
        _add_snapshot(db, campaign.id, channel="google", spend=500.0, impressions=25_000)

        collector = MetricsCollector()
        raw = collector.collect(db, campaign.id)

        calculator = KPICalculator()
        kpis = calculator.compute(db, campaign.id, raw)

        # Campaign-level CPM = (1500 * 1000) / 75000 = 20.0
        campaign_cpm = next(
            (k for k in kpis if k.channel is None and k.kpi_name == "cpm"), None
        )
        assert campaign_cpm is not None
        assert abs(float(campaign_cpm.kpi_value) - 20.0) < 0.01
        db.close()

    def test_all_six_kpis(self):
        _, Session = _make_db()
        db = Session()
        campaign = _make_campaign(db)
        _add_snapshot(
            db, campaign.id,
            spend=1000.0, impressions=100_000, clicks=1000,
            conversions=50, revenue=5000.0,
        )

        collector = MetricsCollector()
        raw = collector.collect(db, campaign.id)

        calculator = KPICalculator()
        kpis = calculator.compute(db, campaign.id, raw)

        campaign_kpi_names = {k.kpi_name for k in kpis if k.channel is None}
        assert "ctr" in campaign_kpi_names
        assert "cvr" in campaign_kpi_names
        assert "cpc" in campaign_kpi_names
        assert "cpm" in campaign_kpi_names
        assert "cpa" in campaign_kpi_names
        assert "roas" in campaign_kpi_names
        db.close()


# ---------------------------------------------------------------------------
# TrendAnalyzer tests
# ---------------------------------------------------------------------------


class TestTrendAnalyzer:
    def _seed_kpis(self, db: Session, campaign_id, channel, kpi_name, current_val, prev_val):
        """Seed DerivedKPI rows for current and previous periods."""
        today = datetime.now(tz=timezone.utc).date()
        current_start = today - timedelta(days=7)
        previous_start = today - timedelta(days=14)
        previous_end = current_start

        # Previous period KPI
        kpi_prev = DerivedKPI(
            campaign_id=campaign_id,
            channel=channel,
            kpi_name=kpi_name,
            kpi_value=prev_val,
            window_start=previous_start,
            window_end=previous_end,
            input_metrics_json={},
        )
        db.add(kpi_prev)

        # Current period KPI
        kpi_curr = DerivedKPI(
            campaign_id=campaign_id,
            channel=channel,
            kpi_name=kpi_name,
            kpi_value=current_val,
            window_start=current_start,
            window_end=today,
            input_metrics_json={},
        )
        db.add(kpi_curr)
        db.commit()

    def test_improving_trend(self):
        _, Session = _make_db()
        db = Session()
        campaign = _make_campaign(db)
        self._seed_kpis(db, campaign.id, "meta", "roas", current_val=3.0, prev_val=2.0)

        analyzer = TrendAnalyzer()
        trends = analyzer.analyze(db, campaign.id, period_days=7)

        assert len(trends) >= 1
        roas_trend = next((t for t in trends if t.kpi_name == "roas"), None)
        assert roas_trend is not None
        assert roas_trend.direction == "improving"
        assert float(roas_trend.magnitude) > 0
        db.close()

    def test_declining_trend(self):
        _, Session = _make_db()
        db = Session()
        campaign = _make_campaign(db)
        self._seed_kpis(db, campaign.id, "meta", "ctr", current_val=0.005, prev_val=0.01)

        analyzer = TrendAnalyzer()
        trends = analyzer.analyze(db, campaign.id, period_days=7)

        ctr_trend = next((t for t in trends if t.kpi_name == "ctr"), None)
        assert ctr_trend is not None
        assert ctr_trend.direction == "declining"
        db.close()

    def test_stable_trend(self):
        _, Session = _make_db()
        db = Session()
        campaign = _make_campaign(db)
        self._seed_kpis(db, campaign.id, "meta", "cpa", current_val=25.1, prev_val=25.0)

        analyzer = TrendAnalyzer()
        trends = analyzer.analyze(db, campaign.id, period_days=7)

        cpa_trend = next((t for t in trends if t.kpi_name == "cpa"), None)
        assert cpa_trend is not None
        assert cpa_trend.direction == "stable"
        db.close()

    def test_insufficient_data(self):
        _, Session = _make_db()
        db = Session()
        campaign = _make_campaign(db)
        # No KPIs seeded → no trends

        analyzer = TrendAnalyzer()
        trends = analyzer.analyze(db, campaign.id, period_days=7)
        assert len(trends) == 0
        db.close()

    def test_confidence_scales(self):
        _, Session = _make_db()
        db = Session()
        campaign = _make_campaign(db)
        # Large change should yield higher confidence
        self._seed_kpis(db, campaign.id, "meta", "cpa", current_val=50.0, prev_val=25.0)

        analyzer = TrendAnalyzer()
        trends = analyzer.analyze(db, campaign.id, period_days=7)

        cpa_trend = next((t for t in trends if t.kpi_name == "cpa"), None)
        assert cpa_trend is not None
        # confidence = min(0.9, 0.5 + 1.0) = 0.9
        assert float(cpa_trend.confidence) > 0.5
        db.close()

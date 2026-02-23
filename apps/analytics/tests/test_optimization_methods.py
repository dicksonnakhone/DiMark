"""Tests for optimization methods and registry (~15 tests)."""

from __future__ import annotations

import pytest

from app.services.optimization.methods.base import (
    BaseOptimizationMethod,
    MethodContext,
    MethodEvaluation,
    MethodRegistry,
)
from app.services.optimization.methods.budget_reallocation import (
    BudgetReallocationMethod,
)
from app.services.optimization.methods.cpa_spike import CPASpikeMethod
from app.services.optimization.methods.creative_fatigue import (
    CreativeFatigueMethod,
)
from app.services.optimization.methods import build_default_registry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(**overrides) -> MethodContext:
    """Build a MethodContext with sensible defaults, overridable per-test."""
    defaults = dict(
        campaign_id="test-campaign-123",
        kpis={"cpa": 25.0, "roas": 2.0, "ctr": 0.01, "cvr": 0.05, "cpc": 2.5, "cpm": 10.0},
        trends=[],
        raw_metrics={"spend": 5000, "impressions": 500000, "clicks": 5000, "conversions": 200, "revenue": 10000},
        channel_data=[
            {
                "channel": "meta",
                "kpis": {"cpa": 20.0, "cac": 20.0, "roas": 2.5, "ctr": 0.012, "efficiency_index": 1.2},
                "totals": {"spend": 3000, "impressions": 300000, "clicks": 3600, "conversions": 150, "revenue": 7500},
            },
            {
                "channel": "google",
                "kpis": {"cpa": 40.0, "cac": 40.0, "roas": 1.25, "ctr": 0.007, "efficiency_index": 0.6},
                "totals": {"spend": 2000, "impressions": 200000, "clicks": 1400, "conversions": 50, "revenue": 2500},
            },
        ],
        current_allocations={"meta": 3000.0, "google": 2000.0},
        campaign_config={"objective": "paid_conversions", "target_cac": 30.0},
    )
    defaults.update(overrides)
    return MethodContext(**defaults)


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


class TestMethodRegistry:
    def test_register_and_list(self):
        registry = MethodRegistry()
        method = CPASpikeMethod()
        registry.register(method)
        assert len(registry.list_methods()) == 1
        assert registry.get("cpa_spike") is method

    def test_list_methods_empty(self):
        registry = MethodRegistry()
        assert registry.list_methods() == []

    def test_evaluate_all_returns_firing_methods(self):
        registry = build_default_registry()
        assert len(registry.list_methods()) == 3

        # With big CPA spike → cpa_spike should fire
        ctx = _make_ctx(
            channel_data=[
                {
                    "channel": "meta",
                    "kpis": {"cpa": 50.0, "cac": 50.0, "roas": 1.0, "ctr": 0.01, "efficiency_index": 1.2},
                    "totals": {"spend": 3000, "impressions": 300000, "clicks": 3000, "conversions": 60, "revenue": 3000},
                },
                {
                    "channel": "google",
                    "kpis": {"cpa": 15.0, "cac": 15.0, "roas": 3.0, "ctr": 0.01, "efficiency_index": 0.4},
                    "totals": {"spend": 2000, "impressions": 200000, "clicks": 2000, "conversions": 133, "revenue": 6000},
                },
            ],
            trends=[
                {
                    "channel": "meta",
                    "kpi_name": "cpa",
                    "direction": "improving",
                    "magnitude": 0.5,
                    "current_value": 50.0,
                    "previous_value": 25.0,
                    "period_days": 7,
                },
            ],
        )
        evaluations = registry.evaluate_all(ctx)
        assert len(evaluations) >= 1

    def test_evaluate_all_empty_when_nothing_fires(self):
        registry = build_default_registry()
        # Stable ctx — nothing should fire
        ctx = _make_ctx(
            channel_data=[
                {
                    "channel": "meta",
                    "kpis": {"cpa": 25.0, "cac": 25.0, "roas": 2.0, "ctr": 0.01, "efficiency_index": 1.0},
                    "totals": {"spend": 3000, "impressions": 300000, "clicks": 3000, "conversions": 120, "revenue": 6000},
                },
                {
                    "channel": "google",
                    "kpis": {"cpa": 26.0, "cac": 26.0, "roas": 1.9, "ctr": 0.009, "efficiency_index": 0.98},
                    "totals": {"spend": 2000, "impressions": 200000, "clicks": 1800, "conversions": 77, "revenue": 3800},
                },
            ],
            trends=[],
        )
        evaluations = registry.evaluate_all(ctx)
        assert len(evaluations) == 0


# ---------------------------------------------------------------------------
# CPA Spike tests
# ---------------------------------------------------------------------------


class TestCPASpikeMethod:
    def test_detects_spike(self):
        method = CPASpikeMethod()
        ctx = _make_ctx(
            trends=[
                {
                    "channel": "meta",
                    "kpi_name": "cpa",
                    "direction": "declining",
                    "magnitude": 0.5,
                    "current_value": 50.0,
                    "previous_value": 25.0,
                    "period_days": 7,
                },
            ],
            channel_data=[
                {
                    "channel": "meta",
                    "kpis": {"cpa": 50.0, "cac": 50.0},
                    "totals": {"spend": 3000, "impressions": 300000, "clicks": 3000, "conversions": 60, "revenue": 3000},
                },
            ],
        )
        result = method.evaluate(ctx)
        assert result is not None
        assert result.should_fire is True
        assert result.action_type == "budget_reallocation"
        assert result.priority == 2

    def test_ignores_small_change(self):
        method = CPASpikeMethod()
        ctx = _make_ctx(
            trends=[
                {
                    "channel": "meta",
                    "kpi_name": "cpa",
                    "direction": "declining",
                    "magnitude": 0.05,
                    "current_value": 26.25,
                    "previous_value": 25.0,
                    "period_days": 7,
                },
            ],
            channel_data=[
                {
                    "channel": "meta",
                    "kpis": {"cpa": 26.25, "cac": 26.25},
                    "totals": {"spend": 3000, "impressions": 300000, "clicks": 3000, "conversions": 114, "revenue": 6000},
                },
            ],
        )
        result = method.evaluate(ctx)
        assert result is None

    def test_precondition_no_channel_data(self):
        method = CPASpikeMethod()
        ctx = _make_ctx(channel_data=[])
        ok, reason = method.check_preconditions(ctx)
        assert ok is False
        assert "channel data" in reason.lower()

    def test_payload_structure(self):
        method = CPASpikeMethod()
        ctx = _make_ctx(
            trends=[
                {
                    "channel": "meta",
                    "kpi_name": "cpa",
                    "direction": "declining",
                    "magnitude": 0.6,
                    "current_value": 40.0,
                    "previous_value": 25.0,
                    "period_days": 7,
                },
            ],
            channel_data=[
                {
                    "channel": "meta",
                    "kpis": {"cpa": 40.0, "cac": 40.0},
                    "totals": {"spend": 3000, "impressions": 300000, "clicks": 3000, "conversions": 75, "revenue": 3000},
                },
            ],
        )
        result = method.evaluate(ctx)
        assert result is not None
        assert "reductions" in result.action_payload
        assert "affected_channels" in result.action_payload


# ---------------------------------------------------------------------------
# Budget Reallocation tests
# ---------------------------------------------------------------------------


class TestBudgetReallocationMethod:
    def test_detects_imbalance(self):
        method = BudgetReallocationMethod()
        ctx = _make_ctx(
            channel_data=[
                {
                    "channel": "meta",
                    "kpis": {"efficiency_index": 1.8, "cac": 15.0, "roas": 3.0},
                    "totals": {"spend": 3000, "impressions": 300000, "clicks": 3000, "conversions": 200, "revenue": 9000},
                },
                {
                    "channel": "google",
                    "kpis": {"efficiency_index": 0.3, "cac": 80.0, "roas": 0.5},
                    "totals": {"spend": 2000, "impressions": 200000, "clicks": 1000, "conversions": 25, "revenue": 1000},
                },
            ],
        )
        result = method.evaluate(ctx)
        assert result is not None
        assert result.should_fire is True
        assert result.action_type == "budget_reallocation"
        assert result.priority == 5

    def test_stable_channels_no_fire(self):
        method = BudgetReallocationMethod()
        ctx = _make_ctx(
            channel_data=[
                {
                    "channel": "meta",
                    "kpis": {"efficiency_index": 1.0, "cac": 25.0},
                    "totals": {"spend": 3000},
                },
                {
                    "channel": "google",
                    "kpis": {"efficiency_index": 0.95, "cac": 26.0},
                    "totals": {"spend": 2000},
                },
            ],
        )
        result = method.evaluate(ctx)
        assert result is None

    def test_precondition_too_few_channels(self):
        method = BudgetReallocationMethod()
        ctx = _make_ctx(
            channel_data=[
                {"channel": "meta", "kpis": {"efficiency_index": 1.0}, "totals": {"spend": 3000}},
            ],
        )
        ok, reason = method.check_preconditions(ctx)
        assert ok is False

    def test_payload_structure(self):
        method = BudgetReallocationMethod()
        ctx = _make_ctx(
            channel_data=[
                {"channel": "meta", "kpis": {"efficiency_index": 2.0, "cac": 10.0}, "totals": {"spend": 3000}},
                {"channel": "google", "kpis": {"efficiency_index": 0.3, "cac": 80.0}, "totals": {"spend": 2000}},
            ],
        )
        result = method.evaluate(ctx)
        assert result is not None
        assert "new_allocations" in result.action_payload
        assert "top_tier" in result.action_payload
        assert "bottom_tier" in result.action_payload


# ---------------------------------------------------------------------------
# Creative Fatigue tests
# ---------------------------------------------------------------------------


class TestCreativeFatigueMethod:
    def test_detects_ctr_decline(self):
        method = CreativeFatigueMethod()
        ctx = _make_ctx(
            trends=[
                {
                    "channel": "meta",
                    "kpi_name": "ctr",
                    "direction": "declining",
                    "magnitude": 0.25,
                    "current_value": 0.0075,
                    "previous_value": 0.01,
                    "period_days": 7,
                },
            ],
            channel_data=[
                {
                    "channel": "meta",
                    "kpis": {"ctr": 0.0075},
                    "totals": {"spend": 3000, "impressions": 400000, "clicks": 3000, "conversions": 100, "revenue": 5000},
                },
            ],
        )
        result = method.evaluate(ctx)
        assert result is not None
        assert result.should_fire is True
        assert result.action_type == "creative_refresh"
        assert result.priority == 6

    def test_stable_ctr_no_fire(self):
        method = CreativeFatigueMethod()
        ctx = _make_ctx(
            trends=[
                {
                    "channel": "meta",
                    "kpi_name": "ctr",
                    "direction": "stable",
                    "magnitude": 0.02,
                    "current_value": 0.0098,
                    "previous_value": 0.01,
                    "period_days": 7,
                },
            ],
            channel_data=[
                {
                    "channel": "meta",
                    "kpis": {"ctr": 0.0098},
                    "totals": {"spend": 3000, "impressions": 400000, "clicks": 3920, "conversions": 100, "revenue": 5000},
                },
            ],
        )
        result = method.evaluate(ctx)
        assert result is None

    def test_precondition_no_trends(self):
        method = CreativeFatigueMethod()
        ctx = _make_ctx(trends=[])
        ok, reason = method.check_preconditions(ctx)
        assert ok is False

    def test_payload_structure(self):
        method = CreativeFatigueMethod()
        ctx = _make_ctx(
            trends=[
                {
                    "channel": "meta",
                    "kpi_name": "ctr",
                    "direction": "declining",
                    "magnitude": 0.30,
                    "current_value": 0.007,
                    "previous_value": 0.01,
                    "period_days": 7,
                },
            ],
            channel_data=[
                {
                    "channel": "meta",
                    "kpis": {"ctr": 0.007},
                    "totals": {"impressions": 500000, "spend": 3000, "clicks": 3500, "conversions": 100, "revenue": 5000},
                },
            ],
        )
        result = method.evaluate(ctx)
        assert result is not None
        assert "channels" in result.action_payload
        assert "fatigued_channels" in result.action_payload

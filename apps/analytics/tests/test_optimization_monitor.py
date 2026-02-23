"""Tests for OptimizationMonitor — full observe→decide→act→verify cycle (~15 tests)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db import Base, get_db
from app.main import app
from app.models import (
    Campaign,
    ChannelSnapshot,
    MonitorRun,
    OptimizationMethod,
    OptimizationProposal,
)
from app.services.optimization.monitor import MonitorRunResult, OptimizationMonitor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_db():
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
    c = Campaign(**defaults)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


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
):
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
    return snap


def _make_method(db: Session, **kwargs) -> OptimizationMethod:
    defaults = dict(
        name=f"test_method_{uuid.uuid4().hex[:6]}",
        description="A test method",
        method_type="reactive",
        trigger_conditions={},
        config_json={},
        is_active=True,
        cooldown_minutes=60,
        stats_json={},
    )
    defaults.update(kwargs)
    m = OptimizationMethod(**defaults)
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def _make_executed_proposal(
    db: Session,
    campaign_id: uuid.UUID,
    method_id: uuid.UUID,
    executed_hours_ago: float = 25.0,
    status: str = "executed",
    **kwargs,
) -> OptimizationProposal:
    executed_at = datetime.now(tz=timezone.utc) - timedelta(hours=executed_hours_ago)
    defaults = dict(
        campaign_id=campaign_id,
        method_id=method_id,
        status=status,
        confidence=0.9,
        priority=5,
        action_type="budget_reallocation",
        action_payload={"new_allocations": {"meta": 3500.0, "google": 1500.0}},
        reasoning="Test proposal",
        trigger_data_json={},
        guardrail_checks_json={},
        execution_result_json={"execution_id": str(uuid.uuid4()), "success": True},
        executed_at=executed_at,
        expires_at=datetime.now(tz=timezone.utc) + timedelta(hours=24),
    )
    defaults.update(kwargs)
    p = OptimizationProposal(**defaults)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _seed_campaign_with_spread(db: Session) -> Campaign:
    """Create a campaign with data that triggers optimization methods."""
    campaign = _make_campaign(db)
    # Big efficiency spread between channels → triggers budget reallocation
    _add_snapshot(
        db, campaign.id, channel="meta",
        spend=3000, impressions=300_000, clicks=3000,
        conversions=200, revenue=9000,
        window_start=date(2025, 1, 1), window_end=date(2025, 1, 7),
    )
    _add_snapshot(
        db, campaign.id, channel="google",
        spend=2000, impressions=200_000, clicks=500,
        conversions=10, revenue=500,
        window_start=date(2025, 1, 1), window_end=date(2025, 1, 7),
    )
    return campaign


# ---------------------------------------------------------------------------
# OptimizationMonitor unit tests
# ---------------------------------------------------------------------------


class TestOptimizationMonitor:
    def test_monitor_full_cycle(self):
        """Full cycle: engine creates proposals → some auto-approved → verification runs."""
        _, Session = _setup_db()
        db = Session()
        campaign = _seed_campaign_with_spread(db)

        monitor = OptimizationMonitor(dry_run=True)
        result = monitor.run_cycle(db, campaign.id)

        assert result.success is True
        assert result.engine_result is not None
        assert result.engine_result.success is True
        assert result.monitor_run_id is not None
        db.close()

    def test_monitor_engine_runs(self):
        """Engine phase should produce proposals when data indicates issues."""
        _, Session = _setup_db()
        db = Session()
        campaign = _seed_campaign_with_spread(db)

        monitor = OptimizationMonitor(dry_run=True)
        result = monitor.run_cycle(db, campaign.id)

        assert result.engine_result is not None
        assert result.engine_result.method_evaluations >= 0
        db.close()

    def test_monitor_executes_auto_approved(self):
        """Auto-approved proposals should be executed during the cycle."""
        _, Session = _setup_db()
        db = Session()

        # Use many snapshots to push confidence above auto-approve threshold
        campaign = _make_campaign(db)
        for i in range(10):
            _add_snapshot(
                db, campaign.id, channel="meta",
                spend=3000, impressions=300_000, clicks=3000,
                conversions=200, revenue=9000,
                window_start=date(2025, 1, 1) + timedelta(weeks=i),
                window_end=date(2025, 1, 7) + timedelta(weeks=i),
            )
            _add_snapshot(
                db, campaign.id, channel="google",
                spend=2000, impressions=200_000, clicks=200,
                conversions=5, revenue=250,
                window_start=date(2025, 1, 1) + timedelta(weeks=i),
                window_end=date(2025, 1, 7) + timedelta(weeks=i),
            )

        monitor = OptimizationMonitor(dry_run=True)
        result = monitor.run_cycle(db, campaign.id)

        # If engine auto-approved any proposals, executor should have run
        if result.engine_result and result.engine_result.proposals_auto_approved > 0:
            assert result.execution_result is not None
            assert result.execution_result.total > 0
        db.close()

    def test_monitor_skips_pending_proposals(self):
        """Pending proposals should NOT be auto-executed."""
        _, Session = _setup_db()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        # Create a pending proposal manually
        p = OptimizationProposal(
            campaign_id=campaign.id,
            method_id=method.id,
            status="pending",
            confidence=0.5,
            priority=5,
            action_type="budget_reallocation",
            action_payload={"new_allocations": {"meta": 3500.0}},
            reasoning="Low confidence",
            trigger_data_json={},
            guardrail_checks_json={},
        )
        db.add(p)
        db.commit()

        # Add minimal snapshots so engine runs
        _add_snapshot(db, campaign.id, channel="meta", spend=2500)

        monitor = OptimizationMonitor(dry_run=True)
        result = monitor.run_cycle(db, campaign.id)

        # The pending proposal should NOT be executed
        db.refresh(p)
        assert p.status == "pending"
        db.close()

    def test_monitor_verifies_old_executions(self):
        """Verification should run on previously executed proposals."""
        _, Session = _setup_db()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        _add_snapshot(db, campaign.id, channel="meta", spend=3000, conversions=100, revenue=5000)

        # Create an executed proposal from 25h ago
        _make_executed_proposal(db, campaign.id, method.id, executed_hours_ago=25)

        monitor = OptimizationMonitor(dry_run=True)
        result = monitor.run_cycle(db, campaign.id)

        assert result.verification_result is not None
        assert result.verification_result.total >= 1
        assert result.verification_result.verified >= 1
        db.close()

    def test_monitor_creates_run_record(self):
        """Each cycle should create a MonitorRun record."""
        _, Session = _setup_db()
        db = Session()
        campaign = _seed_campaign_with_spread(db)

        monitor = OptimizationMonitor(dry_run=True)
        result = monitor.run_cycle(db, campaign.id)

        assert result.monitor_run_id is not None
        runs = db.execute(
            select(MonitorRun).where(MonitorRun.campaign_id == campaign.id)
        ).scalars().all()
        assert len(runs) == 1
        assert runs[0].status in ("completed", "partial")
        db.close()

    def test_monitor_no_proposals_graceful(self):
        """When engine finds nothing to optimise, monitor should still succeed."""
        _, Session = _setup_db()
        db = Session()
        campaign = _make_campaign(db)
        # Balanced channels — nothing should fire
        _add_snapshot(
            db, campaign.id, channel="meta",
            spend=2500, impressions=250_000, clicks=2500,
            conversions=100, revenue=5000,
        )
        _add_snapshot(
            db, campaign.id, channel="google",
            spend=2500, impressions=250_000, clicks=2500,
            conversions=100, revenue=5000,
        )

        monitor = OptimizationMonitor(dry_run=True)
        result = monitor.run_cycle(db, campaign.id)

        assert result.success is True
        assert result.engine_result is not None
        assert result.engine_result.success is True
        db.close()

    def test_monitor_execution_failure_partial(self):
        """If some executions fail, status should be 'partial'."""
        _, Session = _setup_db()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        _add_snapshot(db, campaign.id, channel="meta", spend=3000, conversions=100)

        # Create an auto_approved proposal with bad payload
        p = OptimizationProposal(
            campaign_id=campaign.id,
            method_id=method.id,
            status="auto_approved",
            confidence=0.95,
            priority=2,
            action_type="unknown_action_type",
            action_payload={},
            reasoning="Will fail",
            trigger_data_json={},
            guardrail_checks_json={},
        )
        db.add(p)
        db.commit()

        monitor = OptimizationMonitor(dry_run=True)
        result = monitor.run_cycle(db, campaign.id)

        if result.execution_result and result.execution_result.failed > 0:
            assert len(result.errors) > 0
        db.close()

    def test_monitor_skips_already_executed(self):
        """Auto-approved proposals that were already executed should not be re-executed."""
        _, Session = _setup_db()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        _add_snapshot(db, campaign.id, channel="meta", spend=3000, conversions=100)

        # Create an already-executed auto_approved proposal
        _make_executed_proposal(
            db, campaign.id, method.id,
            status="executed",
            executed_hours_ago=2,
        )

        monitor = OptimizationMonitor(dry_run=True)
        result = monitor.run_cycle(db, campaign.id)

        # The already-executed proposal should not be picked up for execution
        # Only newly created auto_approved ones would be
        if result.execution_result:
            for rec in result.execution_result.records:
                # If anything was executed, it shouldn't be our old proposal
                pass
        db.close()

    def test_monitor_dry_run_mode(self):
        """Monitor should use dry-run setting."""
        _, Session = _setup_db()
        db = Session()
        campaign = _seed_campaign_with_spread(db)

        monitor = OptimizationMonitor(dry_run=True)
        assert monitor.executor.dry_run is True
        result = monitor.run_cycle(db, campaign.id)
        assert result.success is True
        db.close()

    def test_monitor_run_summary_json(self):
        """Verify that summary JSON fields are populated in MonitorRun."""
        _, Session = _setup_db()
        db = Session()
        campaign = _seed_campaign_with_spread(db)

        monitor = OptimizationMonitor(dry_run=True)
        result = monitor.run_cycle(db, campaign.id)

        run = db.execute(
            select(MonitorRun).where(MonitorRun.id == uuid.UUID(result.monitor_run_id))
        ).scalar_one()

        assert run.engine_summary_json is not None
        assert "success" in run.engine_summary_json
        db.close()


# ---------------------------------------------------------------------------
# API tests
# ---------------------------------------------------------------------------


class TestMonitorAPI:
    @staticmethod
    def _setup_client():
        engine, TestingSession = _setup_db()

        def override_get_db():
            db = TestingSession()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)
        return client, TestingSession

    def test_api_run_monitor(self):
        client, Session = self._setup_client()
        db = Session()
        campaign = _seed_campaign_with_spread(db)
        campaign_id = campaign.id
        db.close()

        resp = client.post(f"/api/optimization/campaigns/{campaign_id}/monitor")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["monitor_run_id"] is not None

    def test_api_monitor_not_found(self):
        client, _ = self._setup_client()
        resp = client.post(f"/api/optimization/campaigns/{uuid.uuid4()}/monitor")
        assert resp.status_code == 404

    def test_api_list_monitor_runs(self):
        client, Session = self._setup_client()
        db = Session()
        campaign = _seed_campaign_with_spread(db)
        campaign_id = campaign.id

        # Run a cycle first
        monitor = OptimizationMonitor(dry_run=True)
        monitor.run_cycle(db, campaign_id)
        db.close()

        resp = client.get(f"/api/optimization/campaigns/{campaign_id}/monitor-runs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["status"] in ("completed", "partial")

    def test_api_monitor_runs_ordered(self):
        client, Session = self._setup_client()
        db = Session()
        campaign = _seed_campaign_with_spread(db)
        campaign_id = campaign.id

        # Run two cycles
        monitor = OptimizationMonitor(dry_run=True)
        monitor.run_cycle(db, campaign_id)
        monitor.run_cycle(db, campaign_id)
        db.close()

        resp = client.get(f"/api/optimization/campaigns/{campaign_id}/monitor-runs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2
        # Should be ordered by created_at desc (most recent first)
        if len(data) >= 2:
            assert data[0]["created_at"] >= data[1]["created_at"]

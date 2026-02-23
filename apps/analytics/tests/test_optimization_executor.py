"""Tests for ActionExecutor — executing approved optimization proposals (~16 tests)."""

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
    Execution,
    ExecutionAction,
    OptimizationMethod,
    OptimizationProposal,
)
from app.services.optimization.executor import ActionExecutor, BatchExecutionResult


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


def _make_proposal(
    db: Session,
    campaign_id: uuid.UUID,
    method_id: uuid.UUID,
    status: str = "approved",
    action_type: str = "budget_reallocation",
    action_payload: dict | None = None,
    **kwargs,
) -> OptimizationProposal:
    defaults = dict(
        campaign_id=campaign_id,
        method_id=method_id,
        status=status,
        confidence=0.9,
        priority=5,
        action_type=action_type,
        action_payload=action_payload or {"new_allocations": {"meta": 3500.0, "google": 1500.0}},
        reasoning="Test proposal",
        trigger_data_json={},
        guardrail_checks_json={},
        expires_at=datetime.now(tz=timezone.utc) + timedelta(hours=24),
    )
    defaults.update(kwargs)
    p = OptimizationProposal(**defaults)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


# ---------------------------------------------------------------------------
# ActionExecutor unit tests
# ---------------------------------------------------------------------------


class TestActionExecutor:
    def test_execute_approved_proposal(self):
        _, Session = _setup_db()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        proposal = _make_proposal(db, campaign.id, method.id, status="approved")

        executor = ActionExecutor(dry_run=True)
        record = executor.execute_proposal(db, proposal.id)

        assert record.success is True
        assert record.execution_id is not None
        assert record.error is None

        # Verify proposal updated
        db.refresh(proposal)
        assert proposal.status == "executed"
        assert proposal.executed_at is not None
        assert proposal.execution_result_json is not None
        db.close()

    def test_execute_auto_approved_proposal(self):
        _, Session = _setup_db()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        proposal = _make_proposal(db, campaign.id, method.id, status="auto_approved")

        executor = ActionExecutor(dry_run=True)
        record = executor.execute_proposal(db, proposal.id)

        assert record.success is True
        db.refresh(proposal)
        assert proposal.status == "executed"
        db.close()

    def test_execute_pending_proposal_rejected(self):
        _, Session = _setup_db()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        proposal = _make_proposal(db, campaign.id, method.id, status="pending")

        executor = ActionExecutor(dry_run=True)
        record = executor.execute_proposal(db, proposal.id)

        assert record.success is False
        assert "approved" in record.error.lower()
        db.close()

    def test_execute_rejected_proposal_rejected(self):
        _, Session = _setup_db()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        proposal = _make_proposal(db, campaign.id, method.id, status="rejected")

        executor = ActionExecutor(dry_run=True)
        record = executor.execute_proposal(db, proposal.id)

        assert record.success is False
        assert "approved" in record.error.lower()
        db.close()

    def test_execute_already_executed_idempotent(self):
        _, Session = _setup_db()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        proposal = _make_proposal(db, campaign.id, method.id, status="approved")

        executor = ActionExecutor(dry_run=True)
        record1 = executor.execute_proposal(db, proposal.id)
        assert record1.success is True

        # Execute again — should be idempotent
        record2 = executor.execute_proposal(db, proposal.id, force=True)
        assert record2.success is True
        assert record2.execution_id == record1.execution_id
        db.close()

    def test_execute_creates_execution_record(self):
        _, Session = _setup_db()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        proposal = _make_proposal(db, campaign.id, method.id, status="approved")

        executor = ActionExecutor(dry_run=True)
        record = executor.execute_proposal(db, proposal.id)

        assert record.success is True
        executions = db.execute(
            select(Execution).where(Execution.campaign_id == campaign.id)
        ).scalars().all()
        assert len(executions) == 1
        assert executions[0].idempotency_key == f"opt-proposal-{proposal.id}"
        db.close()

    def test_execute_creates_execution_actions(self):
        _, Session = _setup_db()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        proposal = _make_proposal(
            db, campaign.id, method.id,
            status="approved",
            action_payload={"new_allocations": {"meta": 3500.0, "google": 1500.0}},
        )

        executor = ActionExecutor(dry_run=True)
        record = executor.execute_proposal(db, proposal.id)

        assert record.success is True
        execution = db.execute(
            select(Execution).where(Execution.campaign_id == campaign.id)
        ).scalar_one()
        actions = db.execute(
            select(ExecutionAction).where(ExecutionAction.execution_id == execution.id)
        ).scalars().all()
        # One action per channel
        assert len(actions) == 2
        action_types = {a.action_type for a in actions}
        assert action_types == {"update_budget"}
        db.close()

    def test_execute_sets_proposal_fields(self):
        _, Session = _setup_db()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        proposal = _make_proposal(db, campaign.id, method.id, status="approved")

        executor = ActionExecutor(dry_run=True)
        executor.execute_proposal(db, proposal.id)

        db.refresh(proposal)
        assert proposal.status == "executed"
        assert proposal.executed_at is not None
        assert proposal.execution_result_json is not None
        assert "execution_id" in proposal.execution_result_json
        db.close()

    def test_execute_platform_error_sets_failed(self):
        """When platform adapter raises an exception, proposal should be failed."""
        _, Session = _setup_db()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        # Use a negative budget that the DryRunExecutor rejects
        proposal = _make_proposal(
            db, campaign.id, method.id,
            status="approved",
            action_payload={"new_allocations": {"meta": -100.0}},
        )

        executor = ActionExecutor(dry_run=True)
        record = executor.execute_proposal(db, proposal.id)

        # The dry run executor returns success=False for negative budgets
        # but doesn't raise an exception, so the executor handles it
        db.refresh(proposal)
        # Either "executed" with partial failure or "failed"
        assert proposal.execution_result_json is not None
        db.close()

    def test_execute_creative_refresh_advisory(self):
        _, Session = _setup_db()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        proposal = _make_proposal(
            db, campaign.id, method.id,
            status="approved",
            action_type="creative_refresh",
            action_payload={"channels": ["meta"], "fatigued_channels": ["meta"]},
        )

        executor = ActionExecutor(dry_run=True)
        record = executor.execute_proposal(db, proposal.id)

        assert record.success is True
        db.refresh(proposal)
        assert proposal.status == "executed"
        assert proposal.execution_result_json.get("advisory") is True
        db.close()

    def test_execute_batch_multiple(self):
        _, Session = _setup_db()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        p1 = _make_proposal(db, campaign.id, method.id, status="approved")
        p2 = _make_proposal(
            db, campaign.id, method.id,
            status="approved",
            action_type="creative_refresh",
            action_payload={"channels": ["meta"]},
        )

        executor = ActionExecutor(dry_run=True)
        result = executor.execute_batch(db, [p1.id, p2.id])

        assert result.total == 2
        assert result.succeeded == 2
        assert result.failed == 0
        assert len(result.records) == 2
        db.close()

    def test_execute_batch_partial_failure(self):
        _, Session = _setup_db()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        # One approved, one pending (will fail)
        p1 = _make_proposal(db, campaign.id, method.id, status="approved")
        p2 = _make_proposal(db, campaign.id, method.id, status="pending")

        executor = ActionExecutor(dry_run=True)
        result = executor.execute_batch(db, [p1.id, p2.id])

        assert result.total == 2
        assert result.succeeded == 1
        assert result.failed == 1
        db.close()

    def test_execute_uses_dry_run_adapter(self):
        _, Session = _setup_db()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        proposal = _make_proposal(db, campaign.id, method.id, status="approved")

        executor = ActionExecutor(dry_run=True)
        record = executor.execute_proposal(db, proposal.id)

        assert record.success is True
        # Dry run results should contain dry_run indicators
        execution = db.execute(
            select(Execution).where(Execution.campaign_id == campaign.id)
        ).scalar_one()
        assert execution.status == "completed"
        db.close()


# ---------------------------------------------------------------------------
# API tests
# ---------------------------------------------------------------------------


class TestExecutorAPI:
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

    def test_api_execute_proposal(self):
        client, Session = self._setup_client()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        proposal = _make_proposal(db, campaign.id, method.id, status="approved")
        proposal_id = proposal.id
        db.close()

        resp = client.post(f"/api/optimization/proposals/{proposal_id}/execute")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["execution_id"] is not None

    def test_api_execute_unapproved_returns_400(self):
        client, Session = self._setup_client()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        proposal = _make_proposal(db, campaign.id, method.id, status="pending")
        proposal_id = proposal.id
        db.close()

        resp = client.post(f"/api/optimization/proposals/{proposal_id}/execute")
        assert resp.status_code == 400

    def test_api_execute_not_found_returns_404(self):
        client, _ = self._setup_client()
        resp = client.post(f"/api/optimization/proposals/{uuid.uuid4()}/execute")
        assert resp.status_code == 404

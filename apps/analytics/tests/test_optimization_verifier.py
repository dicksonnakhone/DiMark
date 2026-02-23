"""Tests for OutcomeVerifier — post-execution verification and learning (~16 tests)."""

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
    OptimizationLearning,
    OptimizationMethod,
    OptimizationProposal,
)
from app.services.optimization.verifier import (
    BatchVerificationResult,
    OutcomeVerifier,
    VerificationResult,
)


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


def _make_executed_proposal(
    db: Session,
    campaign_id: uuid.UUID,
    method_id: uuid.UUID,
    executed_hours_ago: float = 25.0,
    action_type: str = "budget_reallocation",
    action_payload: dict | None = None,
    **kwargs,
) -> OptimizationProposal:
    """Create a proposal that has already been executed."""
    executed_at = datetime.now(tz=timezone.utc) - timedelta(hours=executed_hours_ago)
    defaults = dict(
        campaign_id=campaign_id,
        method_id=method_id,
        status="executed",
        confidence=0.9,
        priority=5,
        action_type=action_type,
        action_payload=action_payload or {"new_allocations": {"meta": 3500.0, "google": 1500.0}},
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


# ---------------------------------------------------------------------------
# OutcomeVerifier unit tests
# ---------------------------------------------------------------------------


class TestOutcomeVerifier:
    def test_verify_executed_proposal(self):
        """Happy path: verify a proposal that was executed > 24h ago."""
        _, Session = _setup_db()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        proposal = _make_executed_proposal(db, campaign.id, method.id, executed_hours_ago=25)
        _add_snapshot(db, campaign.id, channel="meta", spend=3500, conversions=200, revenue=9000)
        _add_snapshot(db, campaign.id, channel="google", spend=1500, conversions=80, revenue=4000)

        verifier = OutcomeVerifier()
        result = verifier.verify_proposal(db, proposal.id)

        assert result.success is True
        assert result.learning_id is not None
        assert result.accuracy_score is not None
        assert 0.0 <= result.accuracy_score <= 1.0
        db.close()

    def test_verify_too_soon_returns_pending(self):
        """Proposals executed < 24h ago should return pending."""
        _, Session = _setup_db()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        proposal = _make_executed_proposal(db, campaign.id, method.id, executed_hours_ago=1)

        verifier = OutcomeVerifier()
        result = verifier.verify_proposal(db, proposal.id)

        assert result.success is False
        assert result.error == "pending"
        assert "pending" in result.details.get("status", "")
        db.close()

    def test_verify_creates_learning_record(self):
        """Verification should create an OptimizationLearning record."""
        _, Session = _setup_db()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        proposal = _make_executed_proposal(db, campaign.id, method.id)
        _add_snapshot(db, campaign.id, channel="meta", spend=3000, conversions=100, revenue=5000)

        verifier = OutcomeVerifier()
        result = verifier.verify_proposal(db, proposal.id)

        assert result.success is True
        learnings = db.execute(
            select(OptimizationLearning).where(
                OptimizationLearning.proposal_id == proposal.id
            )
        ).scalars().all()
        assert len(learnings) == 1
        learning = learnings[0]
        assert learning.verification_status == "verified"
        assert learning.verified_at is not None
        assert learning.predicted_impact is not None
        db.close()

    def test_verify_computes_accuracy_score(self):
        """Accuracy score should be between 0 and 1."""
        _, Session = _setup_db()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        proposal = _make_executed_proposal(db, campaign.id, method.id)
        _add_snapshot(db, campaign.id, channel="meta", spend=3000, conversions=100, revenue=6000)

        verifier = OutcomeVerifier()
        result = verifier.verify_proposal(db, proposal.id)

        assert result.success is True
        assert result.accuracy_score is not None
        assert 0.0 <= result.accuracy_score <= 1.0
        db.close()

    def test_accuracy_perfect_match(self):
        """Static test: perfect ROAS gives accuracy of 1.0."""
        verifier = OutcomeVerifier()
        predicted = {"action_type": "budget_reallocation"}
        actual = {"campaign_kpis": {"roas": 5.0}}

        score = verifier._compute_accuracy_score(predicted, actual)
        assert score == 1.0  # roas of 5.0 → min(1.0, 5.0/3.0) = 1.0

    def test_accuracy_complete_miss(self):
        """Static test: very low ROAS gives accuracy near 0."""
        verifier = OutcomeVerifier()
        predicted = {"action_type": "budget_reallocation"}
        actual = {"campaign_kpis": {"roas": 0.01}}

        score = verifier._compute_accuracy_score(predicted, actual)
        assert score < 0.1  # Very low ROAS → low accuracy

    def test_verify_updates_method_stats(self):
        """Verification should update method.stats_json."""
        _, Session = _setup_db()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        proposal = _make_executed_proposal(db, campaign.id, method.id)
        _add_snapshot(db, campaign.id, channel="meta", spend=3000, conversions=100, revenue=5000)

        verifier = OutcomeVerifier()
        result = verifier.verify_proposal(db, proposal.id)

        assert result.success is True
        db.refresh(method)
        stats = method.stats_json
        assert stats["total_executions"] == 1
        assert "avg_accuracy" in stats
        assert "last_verified_at" in stats
        db.close()

    def test_verify_unexecuted_proposal_fails(self):
        """Proposals with executed_at=None should fail."""
        _, Session = _setup_db()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        proposal = OptimizationProposal(
            campaign_id=campaign.id,
            method_id=method.id,
            status="approved",
            confidence=0.9,
            priority=5,
            action_type="budget_reallocation",
            action_payload={},
            reasoning="Test",
            trigger_data_json={},
            guardrail_checks_json={},
        )
        db.add(proposal)
        db.commit()
        db.refresh(proposal)

        verifier = OutcomeVerifier()
        result = verifier.verify_proposal(db, proposal.id)

        assert result.success is False
        assert "executed" in result.error.lower()
        db.close()

    def test_verify_batch(self):
        """Batch verification should verify all eligible proposals."""
        _, Session = _setup_db()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        _add_snapshot(db, campaign.id, channel="meta", spend=3000, conversions=100, revenue=5000)
        p1 = _make_executed_proposal(db, campaign.id, method.id, executed_hours_ago=25)
        p2 = _make_executed_proposal(db, campaign.id, method.id, executed_hours_ago=26)

        verifier = OutcomeVerifier()
        result = verifier.verify_batch(db, campaign.id)

        assert result.total == 2
        assert result.verified == 2
        assert len(result.records) == 2
        db.close()

    def test_verify_batch_mixed_readiness(self):
        """Batch with some ready and some too soon."""
        _, Session = _setup_db()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        _add_snapshot(db, campaign.id, channel="meta", spend=3000, conversions=100, revenue=5000)
        p1 = _make_executed_proposal(db, campaign.id, method.id, executed_hours_ago=25)
        p2 = _make_executed_proposal(db, campaign.id, method.id, executed_hours_ago=1)

        verifier = OutcomeVerifier()
        result = verifier.verify_batch(db, campaign.id)

        assert result.total == 2
        assert result.verified == 1
        assert result.pending == 1
        db.close()

    def test_method_stats_accumulate(self):
        """Multiple verifications should accumulate stats."""
        _, Session = _setup_db()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        _add_snapshot(db, campaign.id, channel="meta", spend=3000, conversions=100, revenue=5000)

        verifier = OutcomeVerifier()

        # First verification
        p1 = _make_executed_proposal(db, campaign.id, method.id, executed_hours_ago=25)
        verifier.verify_proposal(db, p1.id)

        # Second verification
        p2 = _make_executed_proposal(db, campaign.id, method.id, executed_hours_ago=26)
        verifier.verify_proposal(db, p2.id)

        db.refresh(method)
        stats = method.stats_json
        assert stats["total_executions"] == 2
        db.close()

    def test_verification_status_transitions(self):
        """Learning record should have status 'verified' after verification."""
        _, Session = _setup_db()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        proposal = _make_executed_proposal(db, campaign.id, method.id)
        _add_snapshot(db, campaign.id, channel="meta", spend=3000, conversions=100, revenue=5000)

        verifier = OutcomeVerifier()
        result = verifier.verify_proposal(db, proposal.id)

        learning = db.get(OptimizationLearning, uuid.UUID(result.learning_id))
        assert learning.verification_status == "verified"
        db.close()

    def test_verify_with_no_post_metrics(self):
        """Verification with no snapshots should still create a learning record."""
        _, Session = _setup_db()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        proposal = _make_executed_proposal(db, campaign.id, method.id)
        # No snapshots added — metrics collection will find nothing

        verifier = OutcomeVerifier()
        result = verifier.verify_proposal(db, proposal.id)

        # Should still succeed but with a neutral accuracy score
        assert result.success is True
        assert result.accuracy_score == 0.5  # Neutral when no data
        db.close()


# ---------------------------------------------------------------------------
# API tests
# ---------------------------------------------------------------------------


class TestVerifierAPI:
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

    def test_api_verify_proposal(self):
        client, Session = self._setup_client()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        proposal = _make_executed_proposal(db, campaign.id, method.id, executed_hours_ago=25)
        _add_snapshot(db, campaign.id, channel="meta", spend=3000, conversions=100, revenue=5000)
        proposal_id = proposal.id
        db.close()

        resp = client.post(f"/api/optimization/proposals/{proposal_id}/verify")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["learning_id"] is not None

    def test_api_list_learnings(self):
        client, Session = self._setup_client()
        db = Session()
        campaign = _make_campaign(db)
        method = _make_method(db)
        proposal = _make_executed_proposal(db, campaign.id, method.id, executed_hours_ago=25)
        _add_snapshot(db, campaign.id, channel="meta", spend=3000, conversions=100, revenue=5000)

        # Verify to create a learning record
        verifier = OutcomeVerifier()
        verifier.verify_proposal(db, proposal.id)
        campaign_id = campaign.id
        db.close()

        resp = client.get(f"/api/optimization/campaigns/{campaign_id}/learnings")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["verification_status"] == "verified"

    def test_api_learnings_campaign_not_found(self):
        client, _ = self._setup_client()
        resp = client.get(f"/api/optimization/campaigns/{uuid.uuid4()}/learnings")
        assert resp.status_code == 404

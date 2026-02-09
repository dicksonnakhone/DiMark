from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db import Base, get_db
from app.main import app


def setup_test_db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return engine


def test_strategist_end_to_end():
    setup_test_db()
    client = TestClient(app)

    campaign_resp = client.post(
        "/campaigns",
        json={"name": "Q2 Growth", "objective": "paid_conversions", "target_cac": 50},
    )
    campaign = campaign_resp.json()

    plan_resp = client.post(
        f"/campaigns/{campaign['id']}/plan",
        json={
            "brief": {
                "channels_allowed": ["google", "meta"],
                "channels_preferred": ["google"],
            },
            "total_budget": 1000,
            "currency": "USD",
        },
    )
    assert plan_resp.status_code == 200
    plan_payload = plan_resp.json()
    allocations = plan_payload["allocations"]
    assert round(sum(allocations.values()), 2) == 1000

    client.post(
        f"/campaigns/{campaign['id']}/snapshots",
        json={
            "channel": "google",
            "spend": 400,
            "impressions": 10000,
            "clicks": 500,
            "conversions": 20,
            "revenue": 0,
        },
    )
    client.post(
        f"/campaigns/{campaign['id']}/snapshots",
        json={
            "channel": "meta",
            "spend": 600,
            "impressions": 15000,
            "clicks": 400,
            "conversions": 5,
            "revenue": 0,
        },
    )

    measure_resp = client.post(f"/campaigns/{campaign['id']}/measure", json={})
    report_id = measure_resp.json()["report_id"]

    optimize_resp = client.post(
        f"/campaigns/{campaign['id']}/optimize",
        json={"report_id": report_id, "budget_plan_id": plan_payload["budget_plan_id"]},
    )
    assert optimize_resp.status_code == 200
    decision = optimize_resp.json()
    assert decision["decision_type"] in {"rebalance", "pause_channel"}
    assert decision["to_allocations"]["google"] > decision["from_allocations"]["google"]
    assert round(sum(decision["to_allocations"].values()), 2) == 1000
    assert "ranked_channels" in decision["rationale"]

    decision_detail = client.get(f"/decisions/{decision['decision_id']}")
    assert decision_detail.status_code == 200
    assert "rationale_json" in decision_detail.json()


def test_optimize_hold_on_low_conversions():
    setup_test_db()
    client = TestClient(app)

    campaign_resp = client.post(
        "/campaigns",
        json={"name": "Low Data", "objective": "paid_conversions"},
    )
    campaign = campaign_resp.json()

    plan_resp = client.post(
        f"/campaigns/{campaign['id']}/plan",
        json={
            "brief": {"channels_allowed": ["google", "meta"]},
            "total_budget": 500,
        },
    )
    plan_payload = plan_resp.json()

    client.post(
        f"/campaigns/{campaign['id']}/snapshots",
        json={
            "channel": "google",
            "spend": 200,
            "impressions": 2000,
            "clicks": 50,
            "conversions": 2,
            "revenue": 0,
        },
    )

    measure_resp = client.post(f"/campaigns/{campaign['id']}/measure", json={})
    report_id = measure_resp.json()["report_id"]

    optimize_resp = client.post(
        f"/campaigns/{campaign['id']}/optimize",
        json={"report_id": report_id, "budget_plan_id": plan_payload["budget_plan_id"]},
    )
    decision = optimize_resp.json()
    assert decision["decision_type"] == "hold"
    assert decision["from_allocations"] == decision["to_allocations"]

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


def _create_campaign_and_plan(client: TestClient, name: str):
    campaign_resp = client.post(
        "/campaigns",
        json={"name": name, "objective": "paid_conversions", "target_cac": 50},
    )
    campaign = campaign_resp.json()

    plan_resp = client.post(
        f"/campaigns/{campaign['id']}/plan",
        json={
            "brief": {"channels_allowed": ["google", "meta"]},
            "total_budget": 1000,
            "currency": "USD",
        },
    )
    plan_payload = plan_resp.json()
    return campaign, plan_payload


def test_run_cycle_end_to_end_deterministic():
    setup_test_db()
    client = TestClient(app)

    campaign_a, plan_a = _create_campaign_and_plan(client, "Cycle A")
    payload = {
        "budget_plan_id": plan_a["budget_plan_id"],
        "window_start": "2025-02-01",
        "window_end": "2025-02-07",
        "seed": 123,
    }
    result_a = client.post(f"/campaigns/{campaign_a['id']}/run-cycle", json=payload)
    assert result_a.status_code == 200
    body_a = result_a.json()

    campaign_b, plan_b = _create_campaign_and_plan(client, "Cycle B")
    payload_b = {
        **payload,
        "budget_plan_id": plan_b["budget_plan_id"],
    }
    result_b = client.post(f"/campaigns/{campaign_b['id']}/run-cycle", json=payload_b)
    assert result_b.status_code == 200
    body_b = result_b.json()

    assert body_a["snapshots"] == body_b["snapshots"]
    assert body_a["metrics_summary"] == body_b["metrics_summary"]

    allocations_after = body_a["allocations_after"]
    assert round(sum(allocations_after.values()), 2) == 1000


def test_run_cycles_converges():
    setup_test_db()
    client = TestClient(app)

    campaign, plan = _create_campaign_and_plan(client, "Multi Cycle")
    response = client.post(
        f"/campaigns/{campaign['id']}/run-cycles",
        json={
            "budget_plan_id": plan["budget_plan_id"],
            "n": 5,
            "start_date": "2025-02-01",
            "window_days": 7,
            "seed": 42,
        },
    )
    assert response.status_code == 200
    payload = response.json()

    assert len(payload["cycles"]) == 5
    final_allocations = payload["final_allocations"]
    assert round(sum(final_allocations.values()), 2) == 1000
    assert final_allocations["google"] >= final_allocations["meta"]

    decisions = client.get(f"/campaigns/{campaign['id']}/decisions").json()
    assert len(decisions) == 5
    assert all(
        decision["decision_type"] in {"hold", "rebalance", "pause_channel"}
        for decision in decisions
    )

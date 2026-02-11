from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
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
    return engine, TestingSessionLocal


def _create_campaign_and_plan(client: TestClient, name: str, total_budget: int = 1200):
    campaign_resp = client.post(
        "/campaigns",
        json={"name": name, "objective": "paid_conversions", "target_cac": 50},
    )
    campaign = campaign_resp.json()

    plan_resp = client.post(
        f"/campaigns/{campaign['id']}/plan",
        json={
            "brief": {"channels_allowed": ["google", "meta"]},
            "total_budget": total_budget,
            "currency": "USD",
        },
    )
    plan_payload = plan_resp.json()
    return campaign, plan_payload


def test_experiment_discovers_winner():
    setup_test_db()
    client = TestClient(app)

    campaign, plan = _create_campaign_and_plan(client, "Experiment A", total_budget=8000)

    experiment_resp = client.post(
        f"/campaigns/{campaign['id']}/experiments",
        json={
            "experiment_type": "creative",
            "primary_metric": "cvr",
            "hypothesis": "B improves CVR",
            "min_sample_conversions": 5,
            "confidence": 0.8,
            "variants": [
                {
                    "name": "A",
                    "traffic_share": 0.5,
                    "variant": {
                        "description": "control",
                        "sim_overrides": {
                            "meta": {"cvr_mult": 1.0},
                            "google": {"cvr_mult": 1.0},
                        },
                    },
                },
                {
                    "name": "B",
                    "traffic_share": 0.5,
                    "variant": {
                        "description": "treatment",
                        "sim_overrides": {
                            "meta": {"cvr_mult": 1.5},
                            "google": {"cvr_mult": 1.4},
                        },
                    },
                },
            ],
        },
    )
    assert experiment_resp.status_code == 200
    experiment = experiment_resp.json()

    start_resp = client.post(f"/experiments/{experiment['id']}/start")
    assert start_resp.status_code == 200

    cycles_resp = client.post(
        f"/campaigns/{campaign['id']}/run-cycles",
        json={
            "budget_plan_id": plan["budget_plan_id"],
            "n": 6,
            "start_date": "2025-03-01",
            "window_days": 7,
            "seed": 77,
        },
    )
    assert cycles_resp.status_code == 200

    results_resp = client.get(f"/experiments/{experiment['id']}/results")
    assert results_resp.status_code == 200
    assert len(results_resp.json()) >= 1

    detail_resp = client.get(f"/experiments/{experiment['id']}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()

    assert detail["status"] == "completed"
    analysis = detail.get("latest_analysis") or {}
    assert analysis.get("winner") == "B"
    assert "p_value" in analysis
    assert "effect_size" in analysis

    cycle_payload = cycles_resp.json()
    assert cycle_payload["cycles"]
    assert all("report_id" in cycle for cycle in cycle_payload["cycles"])
    assert all("decision_id" in cycle for cycle in cycle_payload["cycles"])


def test_only_one_running_experiment():
    setup_test_db()
    client = TestClient(app)

    campaign, _plan = _create_campaign_and_plan(client, "Experiment B")

    payload = {
        "experiment_type": "creative",
        "primary_metric": "cvr",
        "hypothesis": "test",
        "variants": [
            {"name": "A", "traffic_share": 0.5, "variant": {"description": "A"}},
            {"name": "B", "traffic_share": 0.5, "variant": {"description": "B"}},
        ],
    }

    exp1 = client.post(f"/campaigns/{campaign['id']}/experiments", json=payload).json()
    exp2 = client.post(f"/campaigns/{campaign['id']}/experiments", json=payload).json()

    start1 = client.post(f"/experiments/{exp1['id']}/start")
    assert start1.status_code == 200

    start2 = client.post(f"/experiments/{exp2['id']}/start")
    assert start2.status_code == 409


def test_experiment_aggregation_does_not_pollute_channel_names():
    engine, TestingSessionLocal = setup_test_db()
    client = TestClient(app)

    campaign, plan = _create_campaign_and_plan(client, "Experiment C")

    experiment_resp = client.post(
        f"/campaigns/{campaign['id']}/experiments",
        json={
            "experiment_type": "creative",
            "primary_metric": "cvr",
            "variants": [
                {"name": "A", "traffic_share": 0.5, "variant": {"description": "A"}},
                {"name": "B", "traffic_share": 0.5, "variant": {"description": "B"}},
            ],
        },
    )
    experiment = experiment_resp.json()
    client.post(f"/experiments/{experiment['id']}/start")

    run_resp = client.post(
        f"/campaigns/{campaign['id']}/run-cycle",
        json={
            "budget_plan_id": plan["budget_plan_id"],
            "window_start": "2025-03-01",
            "window_end": "2025-03-07",
            "seed": 101,
        },
    )
    assert run_resp.status_code == 200

    with TestingSessionLocal() as session:
        snapshots = session.execute(select(models.ChannelSnapshot)).scalars().all()
        channels = {snapshot.channel for snapshot in snapshots}
        assert all("|" not in channel for channel in channels)

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


def test_measurement_flow():
    setup_test_db()
    client = TestClient(app)

    campaign_resp = client.post(
        "/campaigns",
        json={
            "name": "Q1 Paid Growth",
            "objective": "paid_conversions",
            "start_date": "2025-01-01",
            "end_date": "2025-01-31",
            "target_cac": 120,
        },
    )
    assert campaign_resp.status_code == 200
    campaign = campaign_resp.json()

    meta_resp = client.post(
        f"/campaigns/{campaign['id']}/snapshots",
        json={
            "channel": "meta",
            "window_start": "2025-01-01",
            "window_end": "2025-01-31",
            "spend": 1000.0,
            "impressions": 100000,
            "clicks": 900,
            "conversions": 12,
            "revenue": 2400.0,
        },
    )
    assert meta_resp.status_code == 200

    google_resp = client.post(
        f"/campaigns/{campaign['id']}/snapshots",
        json={
            "channel": "google",
            "window_start": "2025-01-01",
            "window_end": "2025-01-31",
            "spend": 500.0,
            "impressions": 0,
            "clicks": 100,
            "conversions": 5,
            "revenue": 1000.0,
        },
    )
    assert google_resp.status_code == 200

    measure_resp = client.post(
        f"/campaigns/{campaign['id']}/measure",
        json={"window_start": "2025-01-01", "window_end": "2025-01-31"},
    )
    assert measure_resp.status_code == 200
    payload = measure_resp.json()

    report = payload["report"]
    totals = report["totals"]
    assert totals["spend"] == 1500.0
    assert totals["impressions"] == 100000
    assert totals["clicks"] == 1000
    assert totals["conversions"] == 17
    assert totals["revenue"] == 3400.0

    kpis = report["kpis"]
    assert round(kpis["cac"], 6) == round(1500.0 / 17.0, 6)
    assert round(kpis["roas"], 6) == round(3400.0 / 1500.0, 6)

    channels = {item["channel"]: item for item in report["by_channel"]}
    assert "meta" in channels and "google" in channels
    assert channels["google"]["kpis"]["ctr"] is None

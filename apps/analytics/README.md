# Analytics Service

Measurement, strategist, simulation, and experimentation agents built with FastAPI.

Run locally from repo root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ./apps/analytics
uvicorn apps.analytics.app.main:app --reload
```

Strategist, simulation, and experimentation endpoints are available at `http://localhost:8000/docs`.

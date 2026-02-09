# Analytics Service

Measurement Agent (Attribution-lite v1) built with FastAPI.

Run locally from repo root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ./apps/analytics
uvicorn apps.analytics.app.main:app --reload
```

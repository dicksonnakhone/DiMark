from fastapi import FastAPI

from app.agent_api import agent_router
from app.api import router

app = FastAPI(title="Measurement Agent", version="0.1.0")
app.include_router(router)
app.include_router(agent_router)

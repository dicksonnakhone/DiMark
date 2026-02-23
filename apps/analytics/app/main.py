from fastapi import FastAPI

from app.agent_api import agent_router
from app.api import router
from app.execution_api import execution_router
from app.optimization_api import optimization_router

app = FastAPI(title="Measurement Agent", version="0.1.0")
app.include_router(router)
app.include_router(agent_router)
app.include_router(execution_router)
app.include_router(optimization_router)

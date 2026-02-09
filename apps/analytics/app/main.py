from fastapi import FastAPI

from app.api import router

app = FastAPI(title="Measurement Agent", version="0.1.0")
app.include_router(router)

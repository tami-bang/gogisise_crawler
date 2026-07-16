import os
from fastapi import FastAPI
from app.router import router
from app.logger import configure_logging
import structlog

configure_logging()
log = structlog.get_logger()

app = FastAPI(
    title="Geumcheon Crawler Service",
    description="FastAPI-wrapped Python crawler (peek + crawl)",
    version="1.0.0",
)

app.include_router(router)

@app.on_event("startup")
async def on_startup():
    log.info("fastapi_startup", env=os.getenv("ENV", "dev"))

@app.get("/health")
async def health():
    return {"status": "ok"}

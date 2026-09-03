"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    routes_benchmark, routes_chat, routes_datasets, routes_exceptions,
    routes_health, routes_runs,
)
from app.config import settings
from app.logging_setup import configure_logging
from app.store.db import init_db

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    init_db()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    log.info("%s starting (env=%s, data_dir=%s)", settings.app_name, settings.env, settings.data_dir)
    yield
    log.info("shutting down")


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "A deterministic reconciliation engine that closes the books at scale, "
        "with an AI controller that investigates only what the rules cannot."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (
    routes_health.router,
    routes_datasets.router,
    routes_runs.router,
    routes_exceptions.router,
    routes_chat.router,
    routes_benchmark.router,
):
    app.include_router(router, prefix=settings.api_prefix)


@app.exception_handler(FileNotFoundError)
async def not_found_handler(_request, exc: FileNotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.get("/")
def root() -> dict:
    return {
        "service": settings.app_name,
        "docs": "/docs",
        "api": settings.api_prefix,
    }

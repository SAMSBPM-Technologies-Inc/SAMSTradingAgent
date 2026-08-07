"""
FastAPI Application Entry Point
────────────────────────────────
Wires together:
  - MongoDB connection (lifespan)
  - APScheduler background jobs (lifespan)
  - Route registration
  - Structured logging
  - Global exception handler
"""
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import close_db, connect_db
from app.jobs.scheduler import start_scheduler, stop_scheduler
from app.routes import analysis, health, report, signals
from app.utils.logger import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown sequence."""
    # ── Startup ───────────────────────────────────────────────────────────────
    logger.info("app_starting")
    await connect_db()
    start_scheduler()
    logger.info("app_ready")

    yield  # ← app is running here

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("app_stopping")
    stop_scheduler()
    await close_db()
    logger.info("app_stopped")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="TradingAgent AI – Stock Analysis API",
        description=(
            "AI-powered stock analysis and trading decision support system. "
            "Ingests market data, computes technical indicators, generates "
            "risk scores, and produces BUY/SELL/HOLD signals."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ── CORS (open for internal/dev use; restrict in prod) ────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    # ── Global exception handler ──────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.error(
            "unhandled_exception",
            path=str(request.url),
            error=str(exc),
            exc_info=exc,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "error": str(exc)},
        )

    # ── Routes ────────────────────────────────────────────────────────────────
    app.include_router(health.router)
    app.include_router(analysis.router)
    app.include_router(signals.router)
    app.include_router(report.router)

    return app


app = create_app()


# ── Dev entrypoint ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_env == "development",
        log_level=settings.log_level.lower(),
    )

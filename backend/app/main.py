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
from app.db import COLL_USERS, close_db, connect_db, get_db  # COLL_USERS used by _check_owner_account
from app.jobs.scheduler import start_scheduler, stop_scheduler
from app.routes import alerts, analysis, auth, chart, health, performance, report, signals, trading, watchlist
from app.utils.logger import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


def _check_jwt_secret() -> bool:
    """
    Refuse to let a placeholder token-signing key pass unnoticed.

    `JWT_SECRET_KEY` is not injected by the deploy workflow, and
    `.env.production` persists on the server — so it is set by hand or not at
    all, and "not at all" silently works. Anyone who reads the repo can then
    forge a token for any user id and reach every endpoint, order placement
    included.

    Deliberately not fatal. Killing startup over this would take the API down
    for a config problem, and an outage caused by a safety check is still an
    outage. It is logged as critical and surfaced on /health instead, so it is
    visible without being weaponised — and `scripts/` deploys fail the check
    before it ever ships.

    Returns True when the secret is the placeholder.
    """
    from app.config import DEFAULT_JWT_SECRET

    settings = get_settings()
    if settings.jwt_secret_key != DEFAULT_JWT_SECRET:
        return False

    logger.critical(
        "jwt_secret_is_default",
        impact="tokens can be forged by anyone with the source — every endpoint, "
               "including order placement, is reachable without credentials",
        fix="set JWT_SECRET_KEY in .env.production to a strong random value "
            "(openssl rand -hex 32) and restart the api container",
        note="existing sessions are invalidated when it changes; sign in again",
    )
    return True


async def _check_owner_account() -> None:
    """Log a warning on startup if no user accounts exist yet.
    Run scripts/create_user.py to create the first account.
    """
    db = await get_db()
    count = await db[COLL_USERS].count_documents({})
    if count == 0:
        logger.warning("no_users_found", hint="Run: python scripts/create_user.py --email you@example.com --password secret --name 'Your Name'")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown sequence."""
    # ── Startup ───────────────────────────────────────────────────────────────
    logger.info("app_starting")
    _check_jwt_secret()
    await connect_db()
    await _check_owner_account()
    start_scheduler()

    # Connect to the broker if auto-trading is enabled
    from app.config import get_settings
    from app.services import broker as ibkr
    _settings = get_settings()
    if _settings.auto_trade_enabled:
        connected = await ibkr.connect(
            host=_settings.ibkr_host,
            port=_settings.ibkr_port,
            client_id=_settings.ibkr_client_id,
        )
        # Not fatal — the reconnect loop keeps trying (IB Gateway needs ~2min
        # to finish IBC login, so a miss on the first attempt is normal).
        if not connected:
            logger.warning(
                "broker_initial_connect_failed",
                provider=ibkr.provider_name(),
                host=_settings.ibkr_host,
                port=_settings.ibkr_port,
                hint="retrying in background; check ibgateway container logs",
            )
        ibkr.start_reconnect_loop()
    else:
        # Log loudly: this flag silently disables the entire trading path,
        # including any connection attempt, and is easy to overlook.
        logger.warning(
            "auto_trade_disabled",
            hint="AUTO_TRADE_ENABLED=false — no broker connection, no orders placed",
        )

    logger.info("app_ready")

    yield  # ← app is running here

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("app_stopping")
    stop_scheduler()
    from app.services import broker as ibkr
    ibkr.stop_reconnect_loop()
    await ibkr.disconnect()
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
        version="1.7.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ── CORS — controlled by CORS_ORIGINS env var ─────────────────────────────
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
        allow_credentials=True,
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
    app.include_router(auth.router)
    app.include_router(analysis.router)
    app.include_router(signals.router)
    app.include_router(report.router)
    app.include_router(chart.router)
    app.include_router(watchlist.router)
    app.include_router(performance.router)
    app.include_router(alerts.router)
    app.include_router(trading.router)

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

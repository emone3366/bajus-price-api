"""
FastAPI application entry point.

Handles:
    - Application lifespan (startup/shutdown)
    - Database table creation
    - Redis connection management
    - Background scraper scheduling via APScheduler
    - API router registration
"""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import desc, select

from src.api.v1.router import router as v1_router
from src.config import settings
from src.constants.copy import API_DESCRIPTION, API_TITLE, API_VERSION
from src.db.models import Base, PriceSnapshot
from src.db.session import async_session_factory, engine
from src.services.cache import cache_price, close_redis, init_redis
from src.services.scraper import scrape_prices, validate_price_change
from src.utils.alerts import send_alert

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)



@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    On startup:
        1. Create database tables.
        2. Initialize Redis connection.
        3. Start the background scraper scheduler.

    On shutdown:
        1. Cancel the scraper task.
        2. Close Redis.
        3. Dispose the database engine.
    """
    logger.info("Starting %s...", settings.app_name)

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ensured.")

    # Init Redis
    await init_redis()

    yield

    # Shutdown
    logger.info("Shutting down...")

    await close_redis()
    await engine.dispose()
    logger.info("Shutdown complete.")


app = FastAPI(
    title=API_TITLE,
    description=API_DESCRIPTION,
    version=API_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — allow all origins in dev, restrict in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.debug else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes
app.include_router(v1_router)


@app.get("/", tags=["Health"])
async def health_check() -> dict:
    """Simple health check endpoint."""
    return {
        "service": settings.app_name,
        "status": "healthy",
        "version": API_VERSION,
    }

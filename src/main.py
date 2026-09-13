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

# Track consecutive scraper failures
_consecutive_failures = 0


async def run_scraper_job() -> None:
    """
    Execute a single scraper cycle.

    1. Scrape prices from bajushub.com via Playwright.
    2. Validate each price against the last known value.
    3. Write new/changed prices to PostgreSQL.
    4. Update Redis cache.
    5. Alert on failures or anomalies.
    """
    global _consecutive_failures

    try:
        records = await scrape_prices()
        _consecutive_failures = 0  # Reset on success

        async with async_session_factory() as db:
            for record in records:
                # Get the last known price for this metal+karat
                result = await db.execute(
                    select(PriceSnapshot)
                    .where(
                        PriceSnapshot.metal == record.metal,
                        PriceSnapshot.karat_label == record.karat_label,
                    )
                    .order_by(desc(PriceSnapshot.fetched_at))
                    .limit(1)
                )
                last_snapshot = result.scalar_one_or_none()

                old_price = Decimal(str(last_snapshot.price_per_gram)) if last_snapshot and last_snapshot.price_per_gram is not None else None
                is_valid = validate_price_change(record.price_per_gram, old_price)

                if not is_valid:
                    await send_alert(
                        "Price Anomaly Detected",
                        f"Price change exceeds threshold for {record.metal} {record.karat_label}: "
                        f"{old_price} → {record.price_per_gram} BDT/gram. Held for review.",
                    )
                    continue  # Skip this record — held for manual review

                # Check if price actually changed
                is_changed = old_price is None or old_price != record.price_per_gram
                now = datetime.now(timezone.utc)

                if is_changed:
                    # SQLite-safe insert: avoid duplicate on same day when source_ts is NULL
                    # (SQLite treats NULLs as distinct so the UniqueConstraint won't fire)
                    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                    existing = await db.execute(
                        select(PriceSnapshot)
                        .where(
                            PriceSnapshot.metal == record.metal,
                            PriceSnapshot.karat_label == record.karat_label,
                            PriceSnapshot.fetched_at >= today_start,
                            PriceSnapshot.price_per_gram == record.price_per_gram,
                        )
                        .limit(1)
                    )
                    if existing.scalar_one_or_none() is not None:
                        logger.debug(
                            "Skipping duplicate: %s %s = %s (already recorded today)",
                            record.metal,
                            record.karat_label,
                            record.price_per_gram,
                        )
                    else:
                        snapshot = PriceSnapshot(
                            metal=record.metal,
                            karat_label=record.karat_label,
                            price_per_gram=record.price_per_gram,
                            source_ts=record.source_ts,
                            fetched_at=now,
                            is_changed=True,
                        )
                        db.add(snapshot)
                        logger.info(
                            "New price: %s %s = %s BDT/gram",
                            record.metal,
                            record.karat_label,
                            record.price_per_gram,
                        )
                else:
                    logger.debug(
                        "No change: %s %s = %s BDT/gram",
                        record.metal,
                        record.karat_label,
                        record.price_per_gram,
                    )

                # Always update cache (even if unchanged, to refresh the timestamp)
                await cache_price(
                    metal=record.metal,
                    karat=record.karat_label,
                    price_per_gram=record.price_per_gram,
                    source_ts=record.source_ts,
                    fetched_at=now,
                )

            await db.commit()

        logger.info(
            "Scraper job completed successfully. %d records processed.", len(records)
        )

    except Exception as exc:
        _consecutive_failures += 1
        logger.error("Scraper job failed (attempt #%d): %s", _consecutive_failures, exc)

        if _consecutive_failures >= settings.max_consecutive_failures:
            await send_alert(
                "Scraper Failure",
                f"Scraper has failed {_consecutive_failures} consecutive times.\n"
                f"Last error: {exc}",
            )


async def _scheduler_loop() -> None:
    """Run the scraper on a fixed interval using asyncio."""
    interval = settings.scrape_interval_minutes * 60
    logger.info(
        "Scraper scheduler started (interval: %d min).",
        settings.scrape_interval_minutes,
    )

    # Run once immediately on startup
    await run_scraper_job()

    while True:
        await asyncio.sleep(interval)
        await run_scraper_job()


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

    # Start scraper in background
    scraper_task = asyncio.create_task(_scheduler_loop())

    yield

    # Shutdown
    logger.info("Shutting down...")
    scraper_task.cancel()
    try:
        await scraper_task
    except asyncio.CancelledError:
        pass

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

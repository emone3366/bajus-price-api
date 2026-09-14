"""
Background tasks and orchestrators.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import desc, select

from src.config import settings
from src.db.models import PriceSnapshot
from src.db.session import async_session_factory
from src.services.cache import cache_price
from src.services.scraper import scrape_prices, validate_price_change
from src.utils.alerts import send_alert

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

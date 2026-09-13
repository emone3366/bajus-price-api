"""
Price API endpoints.

Provides latest prices, historical data, and unit conversion
for BAJUS gold and silver prices.
"""

import logging
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import PriceSnapshot
from src.db.session import get_db
from src.schemas.responses import (
    AllLatestPricesResponse,
    ConvertResponse,
    HistoryEntry,
    HistoryResponse,
    LatestPriceResponse,
)
from src.services.auth import log_usage, security_scheme, verify_api_key
from src.services.cache import get_all_cached_prices, get_cached_price, is_cache_stale

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/prices", tags=["Prices"])

# Unit conversion factors (relative to gram)
UNIT_FACTORS: dict[str, Decimal] = {
    "gram": Decimal(1),
    "vori": Decimal("11.664"),
    "bhori": Decimal("11.664"),
    "ana": Decimal("0.7290"),
    "ounce": Decimal("31.1035"),
    "oz": Decimal("31.1035"),
    "tola": Decimal("11.664"),
    "kg": Decimal(1000),
}


@router.get(
    "/gold/latest",
    response_model=LatestPriceResponse,
    summary="Latest gold prices",
    description="Get the latest BAJUS gold buy/base price per gram for all karats.",
)
async def get_gold_latest(
    karat: str | None = Query(
        None, description="Filter by karat: 22k, 21k, 18k, sanaton"
    ),
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> LatestPriceResponse:
    """Return latest gold prices from cache."""
    api_key = await verify_api_key(credentials, db)
    await log_usage(db, api_key, "/v1/prices/gold/latest", 200)

    return await _build_latest_response("gold", karat)


@router.get(
    "/silver/latest",
    response_model=LatestPriceResponse,
    summary="Latest silver prices",
    description="Get the latest BAJUS silver buy/base price per gram for all karats.",
)
async def get_silver_latest(
    karat: str | None = Query(
        None, description="Filter by karat: 22k, 21k, 18k, sanaton"
    ),
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> LatestPriceResponse:
    """Return latest silver prices from cache."""
    api_key = await verify_api_key(credentials, db)
    await log_usage(db, api_key, "/v1/prices/silver/latest", 200)

    return await _build_latest_response("silver", karat)


async def _build_latest_response(
    metal: str, karat_filter: str | None
) -> LatestPriceResponse:
    """Build a LatestPriceResponse from cached data."""
    stale = await is_cache_stale(metal)

    if karat_filter:
        data = await get_cached_price(metal, karat_filter)
        if not data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No cached price found for {metal} {karat_filter}.",
            )
        prices = {data["karat"]: Decimal(data["price_per_gram"])}
        as_of = (
            datetime.fromisoformat(data["source_ts"]) if data.get("source_ts") else None
        )
    else:
        all_data = await get_all_cached_prices(metal)
        if not all_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No cached prices found for {metal}. Scraper may not have run yet.",
            )
        prices = {d["karat"]: Decimal(d["price_per_gram"]) for d in all_data}
        as_of_str = all_data[0].get("source_ts") if all_data else None
        as_of = datetime.fromisoformat(as_of_str) if as_of_str else None

    return LatestPriceResponse(
        metal=metal,
        as_of=as_of,
        prices=prices,
        cached=True,
        stale=stale,
    )


@router.get(
    "/history",
    response_model=HistoryResponse,
    summary="Price history",
    description="Get historical price data. Requires 'starter' plan or above.",
)
async def get_price_history(
    metal: str = Query(..., description="Metal: 'gold' or 'silver'"),
    karat: str = Query(..., description="Karat: '22k', '21k', '18k', 'sanaton'"),
    from_date: datetime | None = Query(
        None, alias="from", description="Start date (ISO 8601)"
    ),
    to_date: datetime | None = Query(
        None, alias="to", description="End date (ISO 8601)"
    ),
    limit: int = Query(100, ge=1, le=1000, description="Max records to return"),
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> HistoryResponse:
    """Return historical price data from PostgreSQL."""
    api_key = await verify_api_key(credentials, db)

    # History is paid-tier only
    if api_key.plan == "free":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="History endpoint requires 'starter' plan or above.",
        )

    await log_usage(db, api_key, "/v1/prices/history", 200)

    query = (
        select(PriceSnapshot)
        .where(PriceSnapshot.metal == metal, PriceSnapshot.karat_label == karat)
        .order_by(desc(PriceSnapshot.fetched_at))
        .limit(limit)
    )

    if from_date:
        query = query.where(PriceSnapshot.fetched_at >= from_date)
    if to_date:
        query = query.where(PriceSnapshot.fetched_at <= to_date)

    result = await db.execute(query)
    snapshots = result.scalars().all()

    data = [
        HistoryEntry(
            date=s.fetched_at,
            price_per_gram=Decimal(str(s.price_per_gram)),
            is_changed=s.is_changed,
        )
        for s in snapshots
    ]

    return HistoryResponse(metal=metal, karat=karat, data=data)


@router.get(
    "/convert",
    response_model=ConvertResponse,
    summary="Unit conversion",
    description="Convert a price from per-gram to another unit (vori, ounce, etc.).",
)
async def convert_price(
    metal: str = Query(..., description="Metal: 'gold' or 'silver'"),
    karat: str = Query(..., description="Karat: '22k', '21k', '18k', 'sanaton'"),
    unit: str = Query(
        ..., description="Target unit: vori, bhori, ana, ounce, oz, tola, kg"
    ),
    qty: Decimal = Query(Decimal(1), description="Quantity of the target unit"),
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> ConvertResponse:
    """Convert a cached per-gram price to another unit."""
    api_key = await verify_api_key(credentials, db)

    if api_key.plan == "free":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Convert endpoint requires 'starter' plan or above.",
        )

    await log_usage(db, api_key, "/v1/prices/convert", 200)

    unit_lower = unit.lower()
    factor = UNIT_FACTORS.get(unit_lower)
    if factor is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown unit '{unit}'. Supported: {', '.join(UNIT_FACTORS.keys())}",
        )

    data = await get_cached_price(metal, karat)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No cached price found for {metal} {karat}.",
        )

    price_per_gram = Decimal(data["price_per_gram"])
    total_price = price_per_gram * factor * qty

    return ConvertResponse(
        metal=metal,
        karat=karat,
        to_unit=unit_lower,
        quantity=qty,
        price_per_from_unit=price_per_gram,
        total_price=total_price.quantize(Decimal("0.01")),
    )


@router.get(
    "/latest",
    response_model=AllLatestPricesResponse,
    summary="Latest gold & silver prices (combined)",
    description=(
        "Get the latest BAJUS gold and silver buy/base prices in a single call. "
        "Ideal for jewellery website widgets that need to display both metals at once."
    ),
)
async def get_all_latest(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> AllLatestPricesResponse:
    """Return both gold and silver latest prices from cache in one response."""
    api_key = await verify_api_key(credentials, db)
    await log_usage(db, api_key, "/v1/prices/latest", 200)

    gold_stale = await is_cache_stale("gold")
    silver_stale = await is_cache_stale("silver")
    stale = gold_stale or silver_stale

    gold_data = await get_all_cached_prices("gold")
    silver_data = await get_all_cached_prices("silver")

    if not gold_data and not silver_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No cached prices found. Scraper may not have run yet.",
        )

    gold_prices = {d["karat"]: Decimal(d["price_per_gram"]) for d in gold_data}
    silver_prices = {d["karat"]: Decimal(d["price_per_gram"]) for d in silver_data}

    # Use the most recent source_ts across both metals
    all_data = gold_data + silver_data
    as_of_str = all_data[0].get("source_ts") if all_data else None
    as_of = datetime.fromisoformat(as_of_str) if as_of_str else None

    return AllLatestPricesResponse(
        as_of=as_of,
        gold=gold_prices,
        silver=silver_prices,
        cached=True,
        stale=stale,
    )

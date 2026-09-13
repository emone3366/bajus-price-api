"""
Meta API endpoints.

Provides usage statistics and account information for API consumers.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db
from src.schemas.responses import UsageResponse
from src.services.auth import log_usage, security_scheme, verify_api_key
from src.services.cache import get_monthly_usage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/meta", tags=["Meta"])


@router.get(
    "/usage",
    response_model=UsageResponse,
    summary="API usage stats",
    description="Get your current month's usage against your plan quota.",
)
async def get_usage(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> UsageResponse:
    """Return the caller's current-month usage statistics."""
    api_key = await verify_api_key(credentials, db)
    await log_usage(db, api_key, "/v1/meta/usage", 200)

    used = await get_monthly_usage(api_key.id)
    remaining = max(0, api_key.monthly_quota - used)

    # Calculate reset date (first of next month)
    now = datetime.now(timezone.utc)
    if now.month == 12:
        resets_on = f"{now.year + 1}-01-01"
    else:
        resets_on = f"{now.year}-{now.month + 1:02d}-01"

    return UsageResponse(
        plan=api_key.plan,
        monthly_quota=api_key.monthly_quota,
        used_this_month=used,
        remaining=remaining,
        resets_on=resets_on,
    )

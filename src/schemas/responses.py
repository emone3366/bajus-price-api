"""
Pydantic response models for the API.

These define the shape of all API responses, ensuring consistent
serialization and automatic OpenAPI documentation.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class PriceEntry(BaseModel):
    """A single price point for a metal+karat combination."""

    karat: str = Field(description="Karat label, e.g. '22k', '21k', '18k', 'sanaton'")
    price_per_gram: Decimal = Field(description="Price per gram in BDT")


class LatestPriceResponse(BaseModel):
    """Response for /prices/{metal}/latest endpoints."""

    metal: str = Field(description="Metal type: 'gold' or 'silver'")
    as_of: datetime | None = Field(description="Source timestamp from bajushub.com")
    currency: str = Field(default="BDT", description="Currency code")
    unit: str = Field(default="gram", description="Weight unit")
    prices: dict[str, Decimal] = Field(
        description="Price per gram by karat, e.g. {'22k': 19970.00}"
    )
    source: str = Field(
        default="BAJUS via bajushub.com", description="Data source attribution"
    )
    cached: bool = Field(description="Whether this was served from cache")
    stale: bool = Field(
        default=False,
        description="True if cache is older than the configured threshold",
    )


class AllLatestPricesResponse(BaseModel):
    """Response for /prices/latest endpoint containing both gold and silver."""

    as_of: datetime | None = Field(description="Source timestamp from bajushub.com")
    currency: str = Field(default="BDT", description="Currency code")
    unit: str = Field(default="gram", description="Weight unit")
    gold: dict[str, Decimal] = Field(description="Gold price per gram by karat")
    silver: dict[str, Decimal] = Field(description="Silver price per gram by karat")
    source: str = Field(
        default="BAJUS via bajushub.com", description="Data source attribution"
    )
    cached: bool = Field(description="Whether this was served from cache")
    stale: bool = Field(default=False)


class HistoryEntry(BaseModel):
    """A single historical price data point."""

    date: datetime = Field(description="When this price was recorded")
    price_per_gram: Decimal = Field(description="Price per gram in BDT")
    is_changed: bool = Field(description="Whether this differs from the prior snapshot")


class HistoryResponse(BaseModel):
    """Response for /prices/history endpoint."""

    metal: str
    karat: str
    currency: str = "BDT"
    unit: str = "gram"
    data: list[HistoryEntry]
    source: str = "BAJUS via bajushub.com"


class ConvertResponse(BaseModel):
    """Response for /prices/convert endpoint."""

    metal: str
    karat: str
    from_unit: str = "gram"
    to_unit: str
    quantity: Decimal
    price_per_from_unit: Decimal
    total_price: Decimal
    currency: str = "BDT"
    source: str = "BAJUS via bajushub.com"


class UsageResponse(BaseModel):
    """Response for /meta/usage endpoint."""

    plan: str
    monthly_quota: int
    used_this_month: int
    remaining: int
    resets_on: str = Field(description="First day of next month in YYYY-MM-DD format")


class KeyCreateRequest(BaseModel):
    """Request body for creating a new API key."""

    owner_email: str
    plan: str = Field(
        default="free",
        description="Subscription tier: 'free', 'starter', 'pro', 'enterprise'",
    )
    billing_cycle: str | None = Field(
        default=None,
        description="Optional duration: 'monthly' or 'annual'. Automatically sets expiration date.",
    )


class KeyCreateResponse(BaseModel):
    """Response after creating a new API key — shows raw key once."""

    raw_key: str = Field(description="Full API key — shown ONCE, save it now")
    key_prefix: str = Field(description="Visible prefix for identification")
    plan: str
    monthly_quota: int
    expires_at: datetime | None = None
    message: str = "Save this key now. It cannot be retrieved again."


class KeyInfoResponse(BaseModel):
    """Public info about an API key (no hash exposed)."""

    id: int
    key_prefix: str
    owner_email: str
    plan: str
    monthly_quota: int
    is_active: bool
    created_at: datetime
    expires_at: datetime | None
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None


class KeyUpdatePlanRequest(BaseModel):
    """Request body for updating an API key's plan tier."""

    plan: str = Field(
        description="New subscription tier: 'free', 'starter', 'pro', 'enterprise'"
    )


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str

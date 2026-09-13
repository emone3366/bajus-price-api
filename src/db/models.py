"""
SQLAlchemy ORM models for the price API database.

Tables:
    - price_snapshots: Normalized gold/silver price history
    - api_keys: Hashed API keys with plan tiers and quotas
    - api_usage_log: Per-request usage tracking for metering
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from src.config import settings

# SQLite does not support BigInteger autoincrement with RETURNING;
# use Integer on SQLite and BigInteger on PostgreSQL.
_is_sqlite = settings.database_url.startswith("sqlite")
_PkType = Integer if _is_sqlite else BigInteger


class Base(DeclarativeBase):
    """Base class for all ORM models."""


class PriceSnapshot(Base):
    """
    A single price observation for a metal+karat combination.

    Stores the BAJUS buy/base price per gram in BDT.
    Only the buy price is captured — sell price is derivable.
    """

    __tablename__ = "price_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "metal", "karat_label", "source_ts", name="uq_metal_karat_source_ts"
        ),
        Index("idx_price_latest", "metal", "karat_label", "fetched_at"),
    )

    id: Mapped[int] = mapped_column(_PkType, primary_key=True, autoincrement=True)
    metal: Mapped[str] = mapped_column(
        String(10),
        CheckConstraint("metal IN ('gold', 'silver')", name="ck_metal"),
        nullable=False,
    )
    karat_label: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="e.g. '22k', '21k', '18k', 'sanaton'",
    )
    price_per_gram: Mapped[float] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        comment="BAJUS base price per gram in BDT",
    )
    currency: Mapped[str] = mapped_column(String(5), nullable=False, default="BDT")
    source_url: Mapped[str] = mapped_column(
        Text, nullable=False, default="https://bajushub.com/"
    )
    source_ts: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp shown on the source page",
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    is_changed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        comment="True if this price differs from the prior snapshot",
    )


class ApiKey(Base):
    """
    An issued API key for a subscriber.

    The raw key is shown once at creation; only the SHA-256 hash is stored.
    """

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(_PkType, primary_key=True, autoincrement=True)
    key_hash: Mapped[str] = mapped_column(
        Text,
        unique=True,
        nullable=False,
        comment="SHA-256 hash of the raw API key",
    )
    key_prefix: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Visible prefix for identification, e.g. 'gsp_live_ab12'",
    )
    owner_email: Mapped[str] = mapped_column(Text, nullable=False)
    plan: Mapped[str] = mapped_column(
        String(20),
        CheckConstraint(
            "plan IN ('free', 'starter', 'pro', 'enterprise')",
            name="ck_plan",
        ),
        nullable=False,
    )
    monthly_quota: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # Stripe billing linkage — populated when key is issued via Stripe checkout
    stripe_customer_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="Stripe customer ID (cus_...) for subscription lifecycle events",
    )
    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="Stripe subscription ID (sub_...) for plan change tracking",
    )

    usage_logs: Mapped[list["ApiUsageLog"]] = relationship(back_populates="api_key")


class ApiUsageLog(Base):
    """Per-request log entry for metering and analytics."""

    __tablename__ = "api_usage_log"

    id: Mapped[int] = mapped_column(_PkType, primary_key=True, autoincrement=True)
    api_key_id: Mapped[int] = mapped_column(
        _PkType,
        ForeignKey("api_keys.id"),
        nullable=False,
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    called_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)

    api_key: Mapped["ApiKey"] = relationship(back_populates="usage_logs")

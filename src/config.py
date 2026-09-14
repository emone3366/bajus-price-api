"""
Application configuration loaded from environment variables.

Uses pydantic-settings for type-safe, validated config with sensible defaults.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings sourced from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # --- Application ---
    app_name: str = "bajus-price-api"
    app_env: str = "development"
    debug: bool = True
    api_version: str = "v1"
    host: str = "0.0.0.0"
    port: int = 8000

    # --- Database ---
    postgres_host: str = "db"
    postgres_port: int = 5432
    postgres_user: str = "priceapi"
    postgres_password: str = "change_me_in_production"
    postgres_db: str = "bajus_prices"
    database_url_override: str | None = None

    @property
    def database_url(self) -> str:
        """Async connection string (PostgreSQL or SQLite fallback)."""
        if self.database_url_override:
            # SQLAlchemy asyncpg needs postgresql+asyncpg://
            if self.database_url_override.startswith("postgres://"):
                return self.database_url_override.replace("postgres://", "postgresql+asyncpg://", 1)
            elif self.database_url_override.startswith("postgresql://"):
                return self.database_url_override.replace("postgresql://", "postgresql+asyncpg://", 1)
            return self.database_url_override

        if self.postgres_host.lower() == "sqlite":
            return f"sqlite+aiosqlite:///{self.postgres_db}.sqlite3"

        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}?ssl=require"
        )

    @property
    def database_url_sync(self) -> str:
        """Sync connection string for Alembic migrations."""
        if self.database_url_override:
            if self.database_url_override.startswith("postgres://"):
                return self.database_url_override.replace("postgres://", "postgresql://", 1)
            return self.database_url_override

        if self.postgres_host.lower() == "sqlite":
            return f"sqlite:///{self.postgres_db}.sqlite3"

        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}?sslmode=require"
        )

    # --- Redis ---
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db: int = 0

    @property
    def redis_url(self) -> str:
        """Redis connection string."""
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    # --- Scraper ---
    scrape_interval_minutes: int = 10
    scrape_source_url: str = "https://bajushub.com/"
    price_change_threshold_pct: int = 15
    stale_cache_minutes: int = 60
    max_consecutive_failures: int = 3

    # --- API Keys ---
    api_key_prefix: str = "gsp_live_"
    admin_secret: str = "change_me_admin_secret"

    # --- Rate Limiting (per minute) ---
    rate_limit_free_per_minute: int = 5
    rate_limit_starter_per_minute: int = 30
    rate_limit_pro_per_minute: int = 120
    rate_limit_enterprise_per_minute: int = 300

    # --- Plan Quotas (monthly) ---
    # free     = trial tier (no payment required)
    # starter  = $6/month or $60/year — the primary sellable plan
    # pro      = premium tier (future expansion)
    # enterprise = custom / high-volume
    quota_free: int = 200
    quota_starter: int = 10_000
    quota_pro: int = 100_000
    quota_enterprise: int = 1_000_000

    # --- Stripe Pricing ---
    # Set these to your Stripe Price IDs (from the Stripe dashboard)
    stripe_monthly_price_id: str = ""  # e.g. price_1ABC... ($6/month)
    stripe_annual_price_id: str = ""  # e.g. price_1XYZ... ($60/year)

    # --- Alerts ---
    alert_slack_webhook_url: str = ""
    alert_email_to: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""

    # --- Stripe ---
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    def get_rate_limit(self, plan: str) -> int:
        """Return the per-minute rate limit for a given plan tier."""
        limits = {
            "free": self.rate_limit_free_per_minute,
            "starter": self.rate_limit_starter_per_minute,
            "pro": self.rate_limit_pro_per_minute,
            "enterprise": self.rate_limit_enterprise_per_minute,
        }
        return limits.get(plan, self.rate_limit_free_per_minute)

    def get_monthly_quota(self, plan: str) -> int:
        """Return the monthly request quota for a given plan tier."""
        quotas = {
            "free": self.quota_free,
            "starter": self.quota_starter,
            "pro": self.quota_pro,
            "enterprise": self.quota_enterprise,
        }
        return quotas.get(plan, self.quota_free)


settings = Settings()

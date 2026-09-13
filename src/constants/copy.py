"""
User-facing strings — all text that appears in API responses or logs.

Centralised here for future i18n support.
"""

# API metadata
API_TITLE = "Bangladesh Gold & Silver Price API"
API_DESCRIPTION = (
    "A metered REST API providing real-time BAJUS gold and silver prices "
    "from bajushub.com, normalized into clean JSON with historical tracking."
)
API_VERSION = "1.0.0"

# Data source
SOURCE_ATTRIBUTION = "BAJUS via bajushub.com"
SOURCE_URL = "https://bajushub.com/"

# Error messages
ERR_INVALID_KEY = "Invalid API key."
ERR_KEY_DEACTIVATED = "API key has been deactivated."
ERR_KEY_EXPIRED = "API key has expired."
ERR_RATE_LIMITED = "Rate limit exceeded. Please try again later."
ERR_QUOTA_EXCEEDED = "Monthly quota exceeded. Upgrade your plan for more requests."
ERR_HISTORY_PAID = "History endpoint requires 'starter' plan or above."
ERR_CONVERT_PAID = "Convert endpoint requires 'starter' plan or above."
ERR_NO_CACHED_PRICE = "No cached prices found. Scraper may not have run yet."
ERR_UNKNOWN_UNIT = (
    "Unknown unit. Supported: gram, vori, bhori, ana, ounce, oz, tola, kg"
)

# Success messages
MSG_KEY_CREATED = "Save this key now. It cannot be retrieved again."

# Alert messages
ALERT_SCRAPER_FAILURE = "Scraper has failed {count} consecutive times."
ALERT_PRICE_ANOMALY = (
    "Price change of {pct:.1f}% detected for {metal} {karat}: "
    "{old} → {new} BDT/gram. Held for review."
)

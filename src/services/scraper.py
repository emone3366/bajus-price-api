"""
Price scraper service using Playwright headless browser.

Extracts BAJUS gold and silver buy/base prices from bajushub.com.
The site renders prices client-side via a WordPress plugin ('goldr'),
so we must use a headless browser to capture the rendered DOM.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from playwright.async_api import Page, async_playwright

from src.config import settings
from src.utils.bangla import bn_digits_to_en, parse_price

logger = logging.getLogger(__name__)


@dataclass
class PriceRecord:
    """A single extracted price data point."""

    metal: str
    karat_label: str
    price_per_gram: Decimal
    source_ts: datetime | None


async def _extract_prices_from_page(page: Page) -> list[PriceRecord]:
    """
    Parse the rendered DOM of bajushub.com to extract price data.

    Looks for the price table rendered by the 'goldr' plugin inside
    the #priceTable container.

    Args:
        page: A Playwright page with bajushub.com fully loaded.

    Returns:
        List of PriceRecord objects for all metals and karats found.
    """
    records: list[PriceRecord] = []

    # Wait for the price table to be populated by client-side JS
    try:
        await page.wait_for_selector(
            "#priceTable table, .goldr-price-container table", timeout=15000
        )
    except Exception:
        logger.warning("Price table selector not found, trying broader search...")

    # Try to extract the source timestamp from the page
    source_ts: datetime | None = None
    try:
        ts_elements = await page.query_selector_all(
            ".goldr-update-time, .update-time, .price-date"
        )
        for el in ts_elements:
            text = await el.inner_text()
            if text.strip():
                en_text = bn_digits_to_en(text.strip())
                logger.info("Found source timestamp: %s", en_text)
                # Try to parse common formats
                for fmt in ["%d-%m-%Y %I:%M:%S %p", "%d-%m-%Y", "%Y-%m-%d %H:%M:%S"]:
                    try:
                        source_ts = datetime.strptime(en_text, fmt).replace(
                            tzinfo=timezone.utc
                        )
                        break
                    except ValueError:
                        continue
                break
    except Exception as exc:
        logger.debug("Could not extract source timestamp: %s", exc)

    # Extract all price tables on the page
    tables = await page.query_selector_all(
        "#priceTable table, .goldr-price-container table"
    )

    if not tables:
        # Fallback: try to find any table with price-like content
        tables = await page.query_selector_all("table")
        logger.warning(
            "No goldr tables found, falling back to scanning %d generic tables",
            len(tables),
        )

    for table in tables:
        rows = await table.query_selector_all("tr")

        # Determine which metal this table is for by checking headers
        header_text = ""
        if rows:
            header_el = await rows[0].query_selector("th, td")
            if header_el:
                header_text = (await header_el.inner_text()).strip().lower()

        metal = "gold"
        if "রুপা" in header_text or "silver" in header_text or "রূপা" in header_text:
            metal = "silver"
        elif "সোনা" in header_text or "gold" in header_text or "স্বর্ণ" in header_text:
            metal = "gold"

        # Parse data rows (skip header row)
        for row in rows[1:]:
            cells = await row.query_selector_all("td")
            if len(cells) < 2:
                continue

            # First cell: karat label, second cell: buy/base price per gram
            karat_text = (await cells[0].inner_text()).strip()
            price_text = (await cells[1].inner_text()).strip()

            if not price_text or not karat_text:
                continue

            # Normalize karat label
            karat_label = _normalize_karat(karat_text)
            if not karat_label:
                continue

            try:
                price_per_gram = parse_price(price_text)
                records.append(
                    PriceRecord(
                        metal=metal,
                        karat_label=karat_label,
                        price_per_gram=price_per_gram,
                        source_ts=source_ts,
                    )
                )
                logger.info(
                    "Extracted: %s %s = %s BDT/gram",
                    metal,
                    karat_label,
                    price_per_gram,
                )
            except ValueError as exc:
                logger.warning(
                    "Could not parse price for %s %s: %s", metal, karat_text, exc
                )

    return records


def _normalize_karat(raw: str) -> str | None:
    """
    Normalize a karat label from Bangla/English to a canonical form.

    Args:
        raw: Raw karat text like '২২ ক্যারেট' or '22k'.

    Returns:
        Canonical label like '22k', '21k', '18k', 'sanaton', or None if unrecognized.
    """
    en = bn_digits_to_en(raw).lower().strip()

    if "22" in en or "২২" in raw:
        return "22k"
    if "21" in en or "২১" in raw:
        return "21k"
    if "18" in en or "১৮" in raw:
        return "18k"
    if "সনাতন" in raw or "sanaton" in en or "traditional" in en:
        return "sanaton"

    logger.debug("Unrecognized karat label: '%s'", raw)
    return None


async def scrape_prices() -> list[PriceRecord]:
    """
    Scrape current gold and silver prices from bajushub.com.

    Uses Playwright to render the page and extract the dynamically-loaded
    price tables.

    Returns:
        List of PriceRecord objects.

    Raises:
        RuntimeError: If the scraper fails to extract any prices.
    """
    logger.info("Starting price scrape from %s", settings.scrape_source_url)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            context = await browser.new_context(
                user_agent=(
                    "BajusPriceAPI/1.0 "
                    "(+https://github.com/your-repo; polite scraper; 10-min interval)"
                ),
                viewport={"width": 1280, "height": 800},
            )
            page = await context.new_page()

            # Navigate and wait for network to settle
            await page.goto(
                settings.scrape_source_url,
                wait_until="networkidle",
                timeout=30000,
            )

            # Give extra time for JS to render the price tables
            await page.wait_for_timeout(3000)

            records = await _extract_prices_from_page(page)

            if not records:
                raise RuntimeError(
                    "No prices extracted from the page. "
                    "The site structure may have changed."
                )

            logger.info("Scrape complete: extracted %d price records.", len(records))
            return records

        finally:
            await browser.close()


def validate_price_change(
    new_price: Decimal,
    old_price: Decimal | None,
) -> bool:
    """
    Check if a new price is within the acceptable change threshold.

    Args:
        new_price: The newly scraped price.
        old_price: The previously stored price (None if first scrape).

    Returns:
        True if the price change is within bounds, False if anomalous.
    """
    if old_price is None or old_price == 0:
        return True

    change_pct = abs((new_price - old_price) / old_price * 100)
    threshold = settings.price_change_threshold_pct

    if change_pct > threshold:
        logger.warning(
            "Price change of %.1f%% exceeds threshold of %d%% (old=%s, new=%s)",
            change_pct,
            threshold,
            old_price,
            new_price,
        )
        return False

    return True

"""
Unit tests for the scraper's price validation logic.
"""

from decimal import Decimal

from src.services.scraper import _normalize_karat, validate_price_change


class TestValidatePriceChange:
    """Tests for the price change threshold validator."""

    def test_first_scrape_always_valid(self):
        """First-ever scrape (no old price) should always pass."""
        assert validate_price_change(Decimal(19970), None) is True

    def test_no_change(self):
        """Same price should pass."""
        assert validate_price_change(Decimal(19970), Decimal(19970)) is True

    def test_small_change_within_threshold(self):
        """A 5% change should pass (threshold is 15%)."""
        old = Decimal(20000)
        new = Decimal(21000)  # 5% increase
        assert validate_price_change(new, old) is True

    def test_large_change_exceeds_threshold(self):
        """A 20% change should fail (threshold is 15%)."""
        old = Decimal(20000)
        new = Decimal(24000)  # 20% increase
        assert validate_price_change(new, old) is False

    def test_large_decrease_exceeds_threshold(self):
        """A 20% decrease should also fail."""
        old = Decimal(20000)
        new = Decimal(16000)  # 20% decrease
        assert validate_price_change(new, old) is False

    def test_boundary_at_threshold(self):
        """Exactly at 15% should pass (threshold is >, not >=)."""
        old = Decimal(20000)
        new = Decimal(23000)  # 15% increase
        assert validate_price_change(new, old) is True

    def test_zero_old_price(self):
        """Zero old price should not cause division errors."""
        assert validate_price_change(Decimal(19970), Decimal(0)) is True


class TestNormalizeKarat:
    """Tests for karat label normalization."""

    def test_english_22k(self):
        assert _normalize_karat("22k") == "22k"

    def test_bangla_22_karat(self):
        assert _normalize_karat("২২ ক্যারেট") == "22k"

    def test_english_21k(self):
        assert _normalize_karat("21k") == "21k"

    def test_english_18k(self):
        assert _normalize_karat("18k") == "18k"

    def test_sanaton_bangla(self):
        assert _normalize_karat("সনাতন") == "sanaton"

    def test_sanaton_english(self):
        assert _normalize_karat("Sanaton") == "sanaton"

    def test_traditional_english(self):
        assert _normalize_karat("Traditional") == "sanaton"

    def test_unrecognized_returns_none(self):
        assert _normalize_karat("unknown") is None

    def test_mixed_bangla_english(self):
        assert _normalize_karat("২২ Karat Gold") == "22k"

"""
Unit tests for the Bangla numeral and currency parsing utilities.
"""

from decimal import Decimal

import pytest

from src.utils.bangla import (
    bn_digits_to_en,
    parse_bangla_datetime,
    parse_price,
    strip_currency,
)


class TestBnDigitsToEn:
    """Tests for Bangla-to-English digit conversion."""

    def test_full_conversion(self):
        assert bn_digits_to_en("০১২৩৪৫৬৭৮৯") == "0123456789"

    def test_mixed_text(self):
        assert bn_digits_to_en("১৯,৯৭০") == "19,970"

    def test_already_english(self):
        assert bn_digits_to_en("19970") == "19970"

    def test_empty_string(self):
        assert bn_digits_to_en("") == ""

    def test_no_digits(self):
        assert bn_digits_to_en("সোনার দাম") == "সোনার দাম"

    def test_bangla_datetime(self):
        result = bn_digits_to_en("১৩-০৯-২০২৬ ৬:৩৪:৫৮ PM")
        assert result == "13-09-2026 6:34:58 PM"


class TestStripCurrency:
    """Tests for currency symbol and comma removal."""

    def test_bdt_symbol(self):
        assert strip_currency("৳ 19,970") == "19970"

    def test_commas_only(self):
        assert strip_currency("19,970.00") == "19970.00"

    def test_no_formatting(self):
        assert strip_currency("19970") == "19970"

    def test_spaces(self):
        assert strip_currency(" ৳ 19,970 ") == "19970"


class TestParsePrice:
    """Tests for the full Bangla price parsing pipeline."""

    def test_bangla_with_currency(self):
        result = parse_price("৳ ১৯,৯৭০")
        assert result == Decimal(19970)

    def test_bangla_without_currency(self):
        result = parse_price("১৯,৯৭০")
        assert result == Decimal(19970)

    def test_english_formatted(self):
        result = parse_price("19,970.00")
        assert result == Decimal("19970.00")

    def test_plain_number(self):
        result = parse_price("19970")
        assert result == Decimal(19970)

    def test_decimal_value(self):
        result = parse_price("১৯,৯৭০.৫০")
        assert result == Decimal("19970.50")

    def test_invalid_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_price("abc")

    def test_empty_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_price("")

    def test_silver_price(self):
        """Silver prices are typically lower — ensure no min-value assumptions."""
        result = parse_price("৳ ১৮৫")
        assert result == Decimal(185)


class TestParseBanglaDatetime:
    """Tests for Bangla datetime conversion."""

    def test_standard_format(self):
        result = parse_bangla_datetime("১৩-০৯-২০২৬ ৬:৮৪:৬৮ PM")
        assert result == "13-09-2026 6:84:68 PM"

    def test_date_only(self):
        result = parse_bangla_datetime("১৩-০৯-২০২৬")
        assert result == "13-09-2026"

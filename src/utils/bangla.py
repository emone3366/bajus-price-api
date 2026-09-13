"""
Bangla numeral and currency conversion utilities.

Handles conversion of Bangla digits (০-৯) to English (0-9),
stripping of BDT currency symbols (৳) and comma separators.
"""

from decimal import Decimal, InvalidOperation

# Bangla digit → English digit mapping
_BN_DIGITS = {
    "০": "0",
    "১": "1",
    "২": "2",
    "৩": "3",
    "৪": "4",
    "৫": "5",
    "৬": "6",
    "৭": "7",
    "৮": "8",
    "৯": "9",
}

# Translation table for str.translate()
_BN_TO_EN_TABLE = str.maketrans(_BN_DIGITS)


def bn_digits_to_en(text: str) -> str:
    """
    Convert all Bangla numerals (০-৯) in a string to English (0-9).

    Args:
        text: Input string potentially containing Bangla digits.

    Returns:
        String with all Bangla digits replaced by their English equivalents.

    Example:
        >>> bn_digits_to_en("১৯,৯৭০")
        '19,970'
    """
    return text.translate(_BN_TO_EN_TABLE)


def strip_currency(text: str) -> str:
    """
    Remove BDT currency symbols (৳) and comma separators from a price string.

    Args:
        text: Raw price string like '৳ ১৯,৯৭০' or '19,970.00'.

    Returns:
        Clean numeric string like '19970' or '19970.00'.
    """
    return text.replace("৳", "").replace(",", "").replace(" ", "").strip()


def parse_price(raw: str) -> Decimal:
    """
    Parse a raw Bangla-formatted price string into a Decimal.

    Handles Bangla digits, currency symbols, and comma separators.

    Args:
        raw: Raw price string, e.g. '৳ ১৯,৯৭০' or '19,970.00'.

    Returns:
        Decimal value of the price.

    Raises:
        ValueError: If the string cannot be parsed into a valid Decimal.

    Example:
        >>> parse_price("৳ ১৯,৯৭০")
        Decimal('19970')
    """
    cleaned = strip_currency(bn_digits_to_en(raw))
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(
            f"Cannot parse price from '{raw}' (cleaned: '{cleaned}')"
        ) from exc


def parse_bangla_datetime(text: str) -> str:
    """
    Convert a Bangla-formatted datetime string to English.

    Args:
        text: Bangla datetime like '১৩-০৯-২০২৬ ৬:৮৪:৬৮ PM'.

    Returns:
        English datetime string like '13-09-2026 6:84:68 PM'.
    """
    return bn_digits_to_en(text)

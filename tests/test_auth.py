"""
Tests for API key generation and hashing.
"""

from src.config import settings
from src.services.auth import generate_api_key, hash_api_key


class TestApiKeyGeneration:
    """Tests for API key generation."""

    def test_key_has_correct_prefix(self):
        raw_key, prefix, key_hash = generate_api_key()
        assert raw_key.startswith(settings.api_key_prefix)

    def test_key_length(self):
        raw_key, prefix, key_hash = generate_api_key()
        # prefix (8 chars) + 32 random hex chars
        expected_len = len(settings.api_key_prefix) + 32
        assert len(raw_key) == expected_len

    def test_prefix_is_first_16_chars(self):
        raw_key, prefix, key_hash = generate_api_key()
        assert prefix == raw_key[:16]

    def test_hash_is_sha256_hex(self):
        raw_key, prefix, key_hash = generate_api_key()
        assert len(key_hash) == 64  # SHA-256 hex digest length

    def test_hash_is_deterministic(self):
        raw_key, prefix, key_hash = generate_api_key()
        assert hash_api_key(raw_key) == key_hash

    def test_unique_keys(self):
        keys = [generate_api_key()[0] for _ in range(10)]
        assert len(set(keys)) == 10  # All unique

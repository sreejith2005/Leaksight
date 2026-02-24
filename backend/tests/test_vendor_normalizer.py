"""
Tests for the Vendor Normalization Service.

Source: docs/RULES_ENGINE.md (vendor normalization section)

Covers:
  - "Tata Steel Pvt Ltd" → "tata steel", blocking key "tata"
  - "TATA STEEL LIMITED" → "tata steel", blocking key "tata"
  - "Reliance Industries Ltd." → "reliance industries", blocking key "reliance"
  - "L&T Construction Pvt. Ltd." → "lt construction", blocking key "lt"
  - Empty string input → handled without crash
  - String with only legal suffixes → handled without crash
"""

import pytest

from backend.app.matching.vendor_normalizer import (
    generate_blocking_key,
    normalize_vendor_name,
)


class TestNormalizeVendorName:
    """Test vendor name normalization."""

    def test_tata_steel_pvt_ltd(self) -> None:
        """Standard Indian legal suffix stripping."""
        result = normalize_vendor_name("Tata Steel Pvt Ltd")
        assert result == "tata steel"

    def test_tata_steel_limited(self) -> None:
        """All-caps input with 'LIMITED' suffix."""
        result = normalize_vendor_name("TATA STEEL LIMITED")
        assert result == "tata steel"

    def test_reliance_industries_ltd_dot(self) -> None:
        """Legal suffix with trailing dot."""
        result = normalize_vendor_name("Reliance Industries Ltd.")
        assert result == "reliance industries"

    def test_lt_construction_pvt_ltd_dot(self) -> None:
        """Ampersand in name + 'Pvt. Ltd.' suffix."""
        result = normalize_vendor_name("L&T Construction Pvt. Ltd.")
        assert result == "lt construction"

    def test_empty_string(self) -> None:
        """Empty string input should return empty string without crash."""
        result = normalize_vendor_name("")
        assert result == ""

    def test_only_legal_suffixes(self) -> None:
        """String with only legal suffixes should return empty string."""
        result = normalize_vendor_name("Pvt Ltd")
        assert result == ""

    def test_private_limited(self) -> None:
        """Compound suffix 'Private Limited'."""
        result = normalize_vendor_name("Acme Solutions Private Limited")
        assert result == "acme solutions"

    def test_llc(self) -> None:
        """International LLC suffix."""
        result = normalize_vendor_name("Global Corp LLC")
        assert result == "global"

    def test_inc(self) -> None:
        """Inc suffix stripping."""
        result = normalize_vendor_name("Tech Corp Inc")
        assert result == "tech"

    def test_p_ltd(self) -> None:
        """P. Ltd. variant."""
        result = normalize_vendor_name("Bharat Forge P. Ltd.")
        assert result == "bharat forge"


class TestGenerateBlockingKey:
    """Test blocking key generation."""

    def test_tata_steel_key(self) -> None:
        """First significant token of 'tata steel' is 'tata'."""
        assert generate_blocking_key("tata steel") == "tata"

    def test_reliance_industries_key(self) -> None:
        """First significant token of 'reliance industries' is 'reliance'."""
        assert generate_blocking_key("reliance industries") == "reliance"

    def test_lt_construction_key(self) -> None:
        """First significant token of 'lt construction' is 'lt'."""
        assert generate_blocking_key("lt construction") == "lt"

    def test_empty_string(self) -> None:
        """Empty input returns empty string."""
        assert generate_blocking_key("") == ""

    def test_stopword_prefix(self) -> None:
        """Stopword at start should be skipped."""
        assert generate_blocking_key("the steel authority") == "steel"

    def test_all_stopwords(self) -> None:
        """If all tokens are stopwords, return the first one."""
        assert generate_blocking_key("the and of") == "the"

    def test_same_blocking_key_for_variants(self) -> None:
        """Both normalized forms of 'Tata Steel' produce the same key."""
        key1 = generate_blocking_key(normalize_vendor_name("Tata Steel Pvt Ltd"))
        key2 = generate_blocking_key(normalize_vendor_name("TATA STEEL LIMITED"))
        assert key1 == key2 == "tata"

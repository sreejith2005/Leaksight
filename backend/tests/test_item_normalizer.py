"""
Tests for the Item Normalization Service.

Source: docs/RULES_ENGINE.md (item normalization section),
       docs/DATABASE_SCHEMA.md (abbreviation_dictionary section)

Covers:
  - Known abbreviation "MT" → "metric_ton" (case-insensitive)
  - Known abbreviation "NOS" → "nos"
  - "MT" inside "AMOUNT" → not substituted (whole word matching)
  - Unknown abbreviation passes through unchanged
  - Empty string → empty string, no crash
  - Custom tenant abbreviation overrides system default
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.matching.item_normalizer import ItemNormalizer, create_item_normalizer
from backend.app.models.tenant import DEFAULT_ABBREVIATION_DICTIONARY


class TestItemNormalizerWithDefaults:
    """Test ItemNormalizer with the default abbreviation dictionary."""

    def setup_method(self) -> None:
        """Create normalizer with default dictionary."""
        self.normalizer = ItemNormalizer(DEFAULT_ABBREVIATION_DICTIONARY)

    def test_mt_resolves_to_metric_ton(self) -> None:
        """Known abbreviation 'MT' resolves to 'metric_ton'."""
        result = self.normalizer.normalize_item_desc("Steel 10 MT")
        assert "metric_ton" in result
        assert "mt" not in result.split()  # "mt" should not appear as standalone

    def test_mt_case_insensitive(self) -> None:
        """Abbreviation substitution is case-insensitive."""
        result = self.normalizer.normalize_item_desc("Steel 10 mt")
        assert "metric_ton" in result

    def test_nos_resolves(self) -> None:
        """Known abbreviation 'NOS' resolves to 'nos'."""
        result = self.normalizer.normalize_item_desc("Bolts 50 NOS")
        assert "nos" in result

    def test_mt_inside_amount_not_substituted(self) -> None:
        """'MT' inside 'AMOUNT' must NOT be substituted (whole word matching)."""
        result = self.normalizer.normalize_item_desc("TOTAL AMOUNT DUE")
        assert "metric_ton" not in result
        assert "amount" in result

    def test_unknown_abbreviation_passes_through(self) -> None:
        """Unknown abbreviations pass through unchanged."""
        result = self.normalizer.normalize_item_desc("XYZ Widget 100")
        assert "xyz" in result
        assert "widget" in result

    def test_empty_string(self) -> None:
        """Empty string returns empty string without crash."""
        result = self.normalizer.normalize_item_desc("")
        assert result == ""

    def test_whitespace_collapsed(self) -> None:
        """Extra whitespace is collapsed to single spaces."""
        result = self.normalizer.normalize_item_desc("Steel   Bar   10   MT")
        assert "  " not in result

    def test_result_is_lowercase(self) -> None:
        """Result is always lowercase."""
        result = self.normalizer.normalize_item_desc("TMT STEEL BAR")
        assert result == result.lower()

    def test_kgs_resolves_to_kilogram(self) -> None:
        """'KGS' resolves to 'kilogram'."""
        result = self.normalizer.normalize_item_desc("Cement 50 KGS")
        assert "kilogram" in result

    def test_sqft_resolves_to_square_foot(self) -> None:
        """'SQFT' resolves to 'square_foot'."""
        result = self.normalizer.normalize_item_desc("Tiles 200 SQFT")
        assert "square_foot" in result


class TestItemNormalizerCustomDictionary:
    """Test ItemNormalizer with a custom tenant dictionary."""

    def test_custom_abbreviation_overrides(self) -> None:
        """Custom tenant abbreviation overrides system default."""
        custom_dict = {
            "MT": "tonnes",  # Override system default
            "SPEC": "special_grade",  # Tenant-specific entry
        }
        normalizer = ItemNormalizer(custom_dict)

        result = normalizer.normalize_item_desc("Steel 10 MT SPEC")
        assert "tonnes" in result
        assert "special_grade" in result
        assert "metric_ton" not in result  # System default NOT used


class TestCreateItemNormalizerFactory:
    """Test the factory function that loads from DB."""

    async def test_loads_from_tenant_settings(self) -> None:
        """Factory loads abbreviation_dictionary from tenant_settings."""
        tenant_id = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        mock_db = AsyncMock()

        custom_dict = {"CUST": "custom_value"}
        settings = MagicMock()
        settings.abbreviation_dictionary = custom_dict

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = settings
        mock_db.execute.return_value = mock_result

        normalizer = await create_item_normalizer(tenant_id, mock_db)

        result = normalizer.normalize_item_desc("Item CUST grade")
        assert "custom_value" in result

    async def test_falls_back_to_default_when_no_settings(self) -> None:
        """Factory falls back to DEFAULT_ABBREVIATION_DICTIONARY when no tenant settings."""
        tenant_id = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        mock_db = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        normalizer = await create_item_normalizer(tenant_id, mock_db)

        result = normalizer.normalize_item_desc("Steel 10 MT")
        assert "metric_ton" in result

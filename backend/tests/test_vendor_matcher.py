"""
Tests for the Vendor Matching Service.

Source: docs/RULES_ENGINE.md (matching engine section)

Covers all five match paths:
  - GST exact match returns immediately with 1.0 confidence
  - Alias match returns immediately with 1.0 confidence
  - Fuzzy match above threshold returns correct vendor
  - Fuzzy match below threshold returns NO_MATCH with needs_manual_review
  - No candidates after blocking key filter returns NO_MATCH
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.matching.vendor_matcher import (
    MatchMethod,
    VendorMatchResult,
    match_vendor,
)


TENANT_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
VENDOR_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")


def _make_vendor(
    vendor_id: uuid.UUID = VENDOR_ID,
    normalized_name: str = "tata steel",
    gst_id: str | None = "29AAACT2727Q1Z0",
) -> MagicMock:
    """Create a mock Vendor object."""
    vendor = MagicMock()
    vendor.id = vendor_id
    vendor.tenant_id = TENANT_ID
    vendor.normalized_name = normalized_name
    vendor.gst_id = gst_id
    return vendor


def _make_alias(
    vendor_id: uuid.UUID = VENDOR_ID,
    alias_name: str = "tata steel",
) -> MagicMock:
    """Create a mock VendorAlias object."""
    alias = MagicMock()
    alias.vendor_id = vendor_id
    alias.alias_name = alias_name
    alias.is_active = True
    return alias


def _make_tenant_settings(fuzzy_threshold: float = 0.85) -> MagicMock:
    """Create a mock TenantSettings object."""
    settings = MagicMock()
    settings.fuzzy_threshold = fuzzy_threshold
    return settings


class TestVendorMatcherGSTExact:
    """Step 1: GST exact match."""

    async def test_gst_exact_match_returns_immediately(self) -> None:
        """When GST ID matches, return immediately with confidence 1.0."""
        mock_db = AsyncMock()
        vendor = _make_vendor()

        # First query (GST lookup) returns the vendor
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = vendor
        mock_db.execute.return_value = mock_result

        result = await match_vendor(
            raw_name="Tata Steel Pvt Ltd",
            gst_id="29AAACT2727Q1Z0",
            tenant_id=TENANT_ID,
            db=mock_db,
        )

        assert result.matched_vendor_id == VENDOR_ID
        assert result.confidence == 1.0
        assert result.match_method == MatchMethod.GST_EXACT
        assert result.needs_manual_review is False
        # Only one DB call (GST lookup) — did not proceed to step 2
        assert mock_db.execute.call_count == 1


class TestVendorMatcherAlias:
    """Step 2: Alias lookup."""

    async def test_alias_match_returns_immediately(self) -> None:
        """When alias matches, return immediately with confidence 1.0."""
        mock_db = AsyncMock()
        alias = _make_alias()

        # First call: GST lookup (no GST provided → skipped)
        # Second call: Alias lookup → returns match
        mock_result_alias = MagicMock()
        mock_result_alias.scalar_one_or_none.return_value = alias
        mock_db.execute.return_value = mock_result_alias

        result = await match_vendor(
            raw_name="Tata Steel Pvt Ltd",
            gst_id=None,  # No GST → skip step 1
            tenant_id=TENANT_ID,
            db=mock_db,
        )

        assert result.matched_vendor_id == VENDOR_ID
        assert result.confidence == 1.0
        assert result.match_method == MatchMethod.ALIAS
        assert result.needs_manual_review is False


class TestVendorMatcherFuzzyAboveThreshold:
    """Steps 3-5: Blocking key + RapidFuzz + threshold check above threshold."""

    async def test_fuzzy_match_above_threshold(self) -> None:
        """Fuzzy match above threshold returns correct vendor."""
        mock_db = AsyncMock()
        vendor = _make_vendor(normalized_name="tata steel")
        settings = _make_tenant_settings(fuzzy_threshold=0.85)

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # Alias lookup → no match
                result.scalar_one_or_none.return_value = None
            elif call_count == 2:
                # Blocking key filter → candidates found
                scalars = MagicMock()
                scalars.all.return_value = [vendor]
                result.scalars.return_value = scalars
            elif call_count == 3:
                # Tenant settings lookup
                result.scalar_one_or_none.return_value = settings
            return result

        mock_db.execute = side_effect

        result = await match_vendor(
            raw_name="Tata Steel Ltd",  # Normalizes to "tata steel"
            gst_id=None,
            tenant_id=TENANT_ID,
            db=mock_db,
        )

        assert result.matched_vendor_id == VENDOR_ID
        assert result.confidence > 0.85
        assert result.match_method == MatchMethod.FUZZY
        assert result.needs_manual_review is False


class TestVendorMatcherFuzzyBelowThreshold:
    """Step 5: Score below threshold → NO_MATCH with manual review."""

    async def test_fuzzy_match_below_threshold(self) -> None:
        """Fuzzy match below threshold returns NO_MATCH."""
        mock_db = AsyncMock()
        # Vendor name is very different to produce low score
        vendor = _make_vendor(normalized_name="reliance industries")
        settings = _make_tenant_settings(fuzzy_threshold=0.85)

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # Alias lookup → no match
                result.scalar_one_or_none.return_value = None
            elif call_count == 2:
                # Blocking key filter → candidates
                # Note: in reality blocking key might not match, but we're
                # testing the threshold check specifically
                scalars = MagicMock()
                scalars.all.return_value = [vendor]
                result.scalars.return_value = scalars
            elif call_count == 3:
                # Tenant settings
                result.scalar_one_or_none.return_value = settings
            return result

        mock_db.execute = side_effect

        result = await match_vendor(
            raw_name="Tata Steel Ltd",
            gst_id=None,
            tenant_id=TENANT_ID,
            db=mock_db,
        )

        assert result.matched_vendor_id is None
        assert result.confidence < 0.85
        assert result.match_method == MatchMethod.NO_MATCH
        assert result.needs_manual_review is True


class TestVendorMatcherNoCandidates:
    """Step 3: No candidates after blocking key filter."""

    async def test_no_candidates_returns_no_match(self) -> None:
        """When blocking key filter returns no candidates, return NO_MATCH."""
        mock_db = AsyncMock()

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # Alias lookup → no match
                result.scalar_one_or_none.return_value = None
            elif call_count == 2:
                # Blocking key filter → no candidates
                scalars = MagicMock()
                scalars.all.return_value = []
                result.scalars.return_value = scalars
            return result

        mock_db.execute = side_effect

        result = await match_vendor(
            raw_name="Tata Steel Pvt Ltd",
            gst_id=None,
            tenant_id=TENANT_ID,
            db=mock_db,
        )

        assert result.matched_vendor_id is None
        assert result.confidence == 0.0
        assert result.match_method == MatchMethod.NO_MATCH
        assert result.needs_manual_review is True

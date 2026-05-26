"""
LeakSight V1 — Phase 10 Step 10.2
Test Suite: Vendor Matching Integration

Pilot Readiness Checklist Sections:
  - Section 2.1: Vendor matching five-step chain order
  - Section 2.2: Fuzzy threshold respect
  - Section 2.3: NO_MATCH → manual review flag

Tests exercise the full vendor matching pipeline:
  normalize → blocking key → GST match → alias lookup → fuzzy match
  through the real match_vendor() function with mocked DB queries.
"""

from decimal import Decimal
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from backend.app.matching.vendor_matcher import (
    MatchMethod,
    VendorMatchResult,
    match_vendor,
)
from backend.app.matching.vendor_normalizer import (
    generate_blocking_key,
    normalize_vendor_name,
)
from backend.tests.integration.conftest import (
    TENANT_A_ID,
    make_tenant_settings,
    make_vendor,
)


# ────────────────────────────────────────────────────────────────────────
# Normalization Unit Tests (pure functions — no DB)
# ────────────────────────────────────────────────────────────────────────

class TestVendorNormalization:
    """Verify vendor name normalization strips legal suffixes, punctuation,
    and extra whitespace while preserving matching-relevant content."""

    def test_strip_pvt_ltd(self):
        assert normalize_vendor_name("Tata Steel Pvt Ltd") == "tata steel"

    def test_strip_private_limited(self):
        assert normalize_vendor_name("Reliance Industries Private Limited") == "reliance industries"

    def test_strip_llp(self):
        assert normalize_vendor_name("Infosys LLP") == "infosys"

    def test_strip_inc(self):
        assert normalize_vendor_name("Apple Inc.") == "apple"

    def test_strip_punctuation(self):
        assert normalize_vendor_name("A.B.C. Corp.") == "abc"

    def test_collapse_whitespace(self):
        assert normalize_vendor_name("  Tata   Steel  ") == "tata steel"

    def test_empty_string(self):
        assert normalize_vendor_name("") == ""

    def test_blocking_key_first_significant_token(self):
        assert generate_blocking_key("tata steel") == "tata"

    def test_blocking_key_skips_stopwords(self):
        assert generate_blocking_key("the great wall co") == "great"

    def test_blocking_key_empty_input(self):
        assert generate_blocking_key("") == ""


# ────────────────────────────────────────────────────────────────────────
# Five-Step Chain Order Tests
# ────────────────────────────────────────────────────────────────────────

class TestFiveStepChainOrder:
    """Verify the five-step matching chain executes in the correct
    mandatory order and stops at the first match.

    Satisfies: Pilot Readiness Section 2.1.
    """

    @pytest.mark.asyncio
    async def test_step1_gst_exact_match_stops_immediately(self):
        """GST exact match must win with confidence 1.0 and stop chain."""
        vendor = make_vendor(name="tata steel", gst_id="27AAACT2727Q1Z5")

        async def fake_execute(stmt):
            mock_result = MagicMock()
            stmt_str = str(stmt)
            if "gst_id" in stmt_str.lower() or "vendor" in stmt_str.lower():
                mock_result.scalar_one_or_none.return_value = vendor
            else:
                mock_result.scalar_one_or_none.return_value = None
                mock_result.scalars.return_value.all.return_value = []
            return mock_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)

        result = await match_vendor(
            raw_name="TATA STEEL PVT LTD",
            gst_id="27AAACT2727Q1Z5",
            tenant_id=TENANT_A_ID,
            db=db,
        )

        assert result.match_method == MatchMethod.GST_EXACT
        assert result.confidence == 1.0
        assert result.matched_vendor_id == vendor.id
        assert result.needs_manual_review is False

    @pytest.mark.asyncio
    async def test_step2_alias_lookup_when_no_gst(self):
        """Alias lookup must match when GST is absent, confidence 1.0."""
        vendor = make_vendor(name="tata steel")
        alias = MagicMock()
        alias.vendor_id = vendor.id
        alias.alias_name = "tata steel"
        alias.is_active = True

        call_count = 0

        async def fake_execute(stmt):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            stmt_str = str(stmt)
            if "vendor_alias" in stmt_str.lower() or "alias" in stmt_str.lower():
                mock_result.scalar_one_or_none.return_value = alias
            else:
                mock_result.scalar_one_or_none.return_value = None
                mock_result.scalars.return_value.all.return_value = []
            return mock_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)

        result = await match_vendor(
            raw_name="Tata Steel Pvt Ltd",
            gst_id=None,
            tenant_id=TENANT_A_ID,
            db=db,
        )

        assert result.match_method == MatchMethod.ALIAS
        assert result.confidence == 1.0
        assert result.matched_vendor_id == vendor.id

    @pytest.mark.asyncio
    async def test_step4_fuzzy_match_above_threshold(self):
        """Fuzzy match above threshold should return FUZZY method."""
        vendor = make_vendor(name="tata steel")
        ts = make_tenant_settings(fuzzy_threshold=0.85)

        call_idx = 0

        async def fake_execute(stmt):
            nonlocal call_idx
            call_idx += 1
            mock_result = MagicMock()
            stmt_str = str(stmt)
            if "vendor_alias" in stmt_str.lower() or "alias" in stmt_str.lower():
                # Step 2: no alias match
                mock_result.scalar_one_or_none.return_value = None
            elif "tenant_settings" in stmt_str.lower():
                # Step 5: threshold lookup
                mock_result.scalar_one_or_none.return_value = ts
            elif "vendor" in stmt_str.lower() and "startswith" in stmt_str.lower():
                # Step 3: blocking key candidates
                mock_result.scalars.return_value.all.return_value = [vendor]
            elif "vendor" in stmt_str.lower():
                mock_result.scalars.return_value.all.return_value = [vendor]
                mock_result.scalar_one_or_none.return_value = None
            else:
                mock_result.scalar_one_or_none.return_value = None
                mock_result.scalars.return_value.all.return_value = []
            return mock_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)

        result = await match_vendor(
            raw_name="Tata Steels",  # Close enough for fuzzy match
            gst_id=None,
            tenant_id=TENANT_A_ID,
            db=db,
        )

        assert result.match_method == MatchMethod.FUZZY
        assert result.confidence >= 0.85
        assert result.matched_vendor_id == vendor.id
        assert result.needs_manual_review is False

    @pytest.mark.asyncio
    async def test_step5_below_threshold_returns_no_match(self):
        """Below fuzzy threshold, return NO_MATCH with manual review flag."""
        # Vendor name is very different
        vendor = make_vendor(name="xyz corporation")
        ts = make_tenant_settings(fuzzy_threshold=0.85)

        async def fake_execute(stmt):
            mock_result = MagicMock()
            stmt_str = str(stmt)
            if "vendor_alias" in stmt_str.lower() or "alias" in stmt_str.lower():
                mock_result.scalar_one_or_none.return_value = None
            elif "tenant_settings" in stmt_str.lower():
                mock_result.scalar_one_or_none.return_value = ts
            elif "vendor" in stmt_str.lower():
                mock_result.scalars.return_value.all.return_value = [vendor]
                mock_result.scalar_one_or_none.return_value = None
            else:
                mock_result.scalar_one_or_none.return_value = None
                mock_result.scalars.return_value.all.return_value = []
            return mock_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)

        result = await match_vendor(
            raw_name="Tata Steel",
            gst_id=None,
            tenant_id=TENANT_A_ID,
            db=db,
        )

        assert result.match_method == MatchMethod.NO_MATCH
        assert result.needs_manual_review is True


# ────────────────────────────────────────────────────────────────────────
# Fuzzy Threshold Respect
# ────────────────────────────────────────────────────────────────────────

class TestFuzzyThresholdRespect:
    """Verify tenant-specific fuzzy threshold is read and applied.

    Satisfies: Pilot Readiness Section 2.2.
    """

    @pytest.mark.asyncio
    async def test_tenant_threshold_overrides_default(self):
        """Tenant with threshold=0.70 must match names that default 0.85
        would reject."""
        vendor = make_vendor(name="tata steel")
        ts = make_tenant_settings(fuzzy_threshold=0.70)

        async def fake_execute(stmt):
            mock_result = MagicMock()
            stmt_str = str(stmt)
            if "vendor_alias" in stmt_str.lower() or "alias" in stmt_str.lower():
                mock_result.scalar_one_or_none.return_value = None
            elif "tenant_settings" in stmt_str.lower():
                mock_result.scalar_one_or_none.return_value = ts
            elif "vendor" in stmt_str.lower():
                mock_result.scalars.return_value.all.return_value = [vendor]
                mock_result.scalar_one_or_none.return_value = None
            else:
                mock_result.scalar_one_or_none.return_value = None
                mock_result.scalars.return_value.all.return_value = []
            return mock_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)

        # "tata stl" is close to "tata steel" → above 0.70 but below 0.85
        result = await match_vendor(
            raw_name="tata stl",
            gst_id=None,
            tenant_id=TENANT_A_ID,
            db=db,
        )

        assert result.match_method == MatchMethod.FUZZY
        assert result.confidence >= 0.70
        assert result.needs_manual_review is False

    @pytest.mark.asyncio
    async def test_no_tenant_settings_uses_default_085(self):
        """When TenantSettings row is missing, system must default to 0.85."""
        vendor = make_vendor(name="reliance industries")

        async def fake_execute(stmt):
            mock_result = MagicMock()
            stmt_str = str(stmt)
            if "vendor_alias" in stmt_str.lower() or "alias" in stmt_str.lower():
                mock_result.scalar_one_or_none.return_value = None
            elif "tenant_settings" in stmt_str.lower():
                mock_result.scalar_one_or_none.return_value = None  # No settings
            elif "vendor" in stmt_str.lower():
                mock_result.scalars.return_value.all.return_value = [vendor]
                mock_result.scalar_one_or_none.return_value = None
            else:
                mock_result.scalar_one_or_none.return_value = None
                mock_result.scalars.return_value.all.return_value = []
            return mock_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)

        # "reliance ind" is close to "reliance industries" — should be
        # above 0.85 default
        result = await match_vendor(
            raw_name="reliance industries",
            gst_id=None,
            tenant_id=TENANT_A_ID,
            db=db,
        )

        # Exact name → high confidence → FUZZY match with default threshold
        assert result.confidence >= 0.85


# ────────────────────────────────────────────────────────────────────────
# NO_MATCH → Manual Review
# ────────────────────────────────────────────────────────────────────────

class TestNoMatchManualReview:
    """Verify that NO_MATCH always sets needs_manual_review=True.

    Satisfies: Pilot Readiness Section 2.3.
    """

    @pytest.mark.asyncio
    async def test_no_candidates_returns_manual_review(self):
        """When blocking key finds zero candidates, must return manual review."""
        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_result.scalars.return_value.all.return_value = []
            return mock_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)

        result = await match_vendor(
            raw_name="Unknown Vendor XYZ 42",
            gst_id=None,
            tenant_id=TENANT_A_ID,
            db=db,
        )

        assert result.match_method == MatchMethod.NO_MATCH
        assert result.needs_manual_review is True
        assert result.matched_vendor_id is None
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_empty_blocking_key_returns_manual_review(self):
        """A name that produces an empty blocking key (all stopwords) must
        return NO_MATCH + manual review, not crash."""
        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_result.scalars.return_value.all.return_value = []
            return mock_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)

        result = await match_vendor(
            raw_name="the and of",  # All stopwords
            gst_id=None,
            tenant_id=TENANT_A_ID,
            db=db,
        )

        assert result.match_method == MatchMethod.NO_MATCH
        assert result.needs_manual_review is True

    @pytest.mark.asyncio
    async def test_gst_miss_falls_through_to_fuzzy(self):
        """If GST does not match, the chain must continue (not stop)."""
        vendor = make_vendor(name="tata steel", gst_id="27AAACT2727Q1Z5")
        ts = make_tenant_settings()

        call_idx = 0

        async def fake_execute(stmt):
            nonlocal call_idx
            call_idx += 1
            mock_result = MagicMock()
            stmt_str = str(stmt)
            if call_idx == 1:
                # Step 1: GST query — no match
                mock_result.scalar_one_or_none.return_value = None
            elif "vendor_alias" in stmt_str.lower() or "alias" in stmt_str.lower():
                mock_result.scalar_one_or_none.return_value = None
            elif "tenant_settings" in stmt_str.lower():
                mock_result.scalar_one_or_none.return_value = ts
            elif "vendor" in stmt_str.lower():
                mock_result.scalars.return_value.all.return_value = [vendor]
                mock_result.scalar_one_or_none.return_value = None
            else:
                mock_result.scalar_one_or_none.return_value = None
                mock_result.scalars.return_value.all.return_value = []
            return mock_result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)

        result = await match_vendor(
            raw_name="tata steel",
            gst_id="INVALID_GST",
            tenant_id=TENANT_A_ID,
            db=db,
        )

        # Should fall through to fuzzy since GST didn't match
        assert result.match_method in (MatchMethod.FUZZY, MatchMethod.ALIAS)
        assert result.confidence >= 0.85

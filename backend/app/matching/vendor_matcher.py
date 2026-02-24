"""
LeakSight V1 — Vendor Matching Service

Source: docs/RULES_ENGINE.md (matching engine section — five-step order is locked),
       docs/DATABASE_SCHEMA.md (vendor_aliases section)

Implements the five-step vendor matching chain:
  1. GST exact match → confidence 1.0, stop
  2. Alias lookup → confidence 1.0, stop
  3. Blocking key filter → reduce candidate set
  4. RapidFuzz token_sort_ratio → score candidates
  5. Threshold check → above = FUZZY match, below = NO_MATCH + manual review

This is core intellectual property. The matching order is locked and must not
be reordered.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional
from uuid import UUID

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.matching.vendor_normalizer import (
    generate_blocking_key,
    normalize_vendor_name,
)
from backend.app.models.tenant import TenantSettings
from backend.app.models.vendors import Vendor, VendorAlias


class MatchMethod(str, Enum):
    """How the vendor match was achieved."""

    GST_EXACT = "GST_EXACT"
    ALIAS = "ALIAS"
    FUZZY = "FUZZY"
    NO_MATCH = "NO_MATCH"


@dataclass
class VendorMatchResult:
    """Result of a vendor matching attempt.

    Attributes:
        matched_vendor_id: UUID of the matched vendor, or None if no match.
        confidence: Match confidence from 0.0 to 1.0.
        match_method: How the match was achieved.
        needs_manual_review: Whether manual review is required.
    """

    matched_vendor_id: Optional[UUID]
    confidence: float
    match_method: MatchMethod
    needs_manual_review: bool


async def match_vendor(
    raw_name: str,
    gst_id: Optional[str],
    tenant_id: UUID,
    db: AsyncSession,
) -> VendorMatchResult:
    """Match a raw vendor name to a canonical vendor using the five-step chain.

    Step 1: GST exact match (if GST ID present)
    Step 2: Alias lookup (normalized name against vendor_aliases)
    Step 3: Blocking key filter (reduce candidates)
    Step 4: RapidFuzz token_sort_ratio (score candidates)
    Step 5: Threshold check (fuzzy_threshold from tenant_settings)

    Args:
        raw_name: The raw vendor name from the document.
        gst_id: GST/Tax ID from the document, if available.
        tenant_id: The tenant UUID for scoping.
        db: Async database session.

    Returns:
        VendorMatchResult with match details.
    """
    # ------------------------------------------------------------------
    # Step 1 — GST exact match
    # ------------------------------------------------------------------
    if gst_id:
        stmt = select(Vendor).where(
            Vendor.tenant_id == tenant_id,
            Vendor.gst_id == gst_id,
        )
        result = await db.execute(stmt)
        vendor = result.scalar_one_or_none()
        if vendor is not None:
            return VendorMatchResult(
                matched_vendor_id=vendor.id,
                confidence=1.0,
                match_method=MatchMethod.GST_EXACT,
                needs_manual_review=False,
            )

    # ------------------------------------------------------------------
    # Step 2 — Alias lookup
    # ------------------------------------------------------------------
    normalized_name = normalize_vendor_name(raw_name)

    stmt = select(VendorAlias).where(
        VendorAlias.tenant_id == tenant_id,
        VendorAlias.alias_name == normalized_name,
        VendorAlias.is_active == True,  # noqa: E712
    )
    result = await db.execute(stmt)
    alias = result.scalar_one_or_none()
    if alias is not None:
        return VendorMatchResult(
            matched_vendor_id=alias.vendor_id,
            confidence=1.0,
            match_method=MatchMethod.ALIAS,
            needs_manual_review=False,
        )

    # ------------------------------------------------------------------
    # Step 3 — Blocking key filter
    # ------------------------------------------------------------------
    blocking_key = generate_blocking_key(normalized_name)

    if not blocking_key:
        return VendorMatchResult(
            matched_vendor_id=None,
            confidence=0.0,
            match_method=MatchMethod.NO_MATCH,
            needs_manual_review=True,
        )

    stmt = select(Vendor).where(
        Vendor.tenant_id == tenant_id,
        Vendor.normalized_name.startswith(blocking_key),
    )
    result = await db.execute(stmt)
    candidates = list(result.scalars().all())

    if not candidates:
        return VendorMatchResult(
            matched_vendor_id=None,
            confidence=0.0,
            match_method=MatchMethod.NO_MATCH,
            needs_manual_review=True,
        )

    # ------------------------------------------------------------------
    # Step 4 — RapidFuzz matching
    # ------------------------------------------------------------------
    best_score: float = 0.0
    best_vendor: Optional[Vendor] = None

    for candidate in candidates:
        score = fuzz.token_sort_ratio(normalized_name, candidate.normalized_name)
        if score > best_score:
            best_score = score
            best_vendor = candidate

    # Convert score from 0-100 to 0.0-1.0
    confidence = best_score / 100.0

    # ------------------------------------------------------------------
    # Step 5 — Threshold check
    # ------------------------------------------------------------------
    # Read fuzzy_threshold from tenant_settings
    settings_stmt = select(TenantSettings).where(
        TenantSettings.tenant_id == tenant_id,
    )
    settings_result = await db.execute(settings_stmt)
    tenant_settings = settings_result.scalar_one_or_none()

    # Fall back to system default if tenant settings do not exist
    fuzzy_threshold = 0.85
    if tenant_settings is not None:
        fuzzy_threshold = tenant_settings.fuzzy_threshold

    if confidence < fuzzy_threshold:
        return VendorMatchResult(
            matched_vendor_id=None,
            confidence=confidence,
            match_method=MatchMethod.NO_MATCH,
            needs_manual_review=True,
        )

    return VendorMatchResult(
        matched_vendor_id=best_vendor.id if best_vendor else None,
        confidence=confidence,
        match_method=MatchMethod.FUZZY,
        needs_manual_review=False,
    )

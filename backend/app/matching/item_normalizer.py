"""
LeakSight V1 — Item Description Normalization Service

Source: docs/RULES_ENGINE.md (item normalization section),
       docs/DATABASE_SCHEMA.md (abbreviation_dictionary section),
       backend/app/models/tenant.py (DEFAULT_ABBREVIATION_DICTIONARY)

Loads abbreviation_dictionary from tenant_settings at initialization, not on
every call. This is important for performance.

Abbreviation substitution is case-insensitive and matches whole words only
(e.g., "MT" inside "AMOUNT" is NOT substituted).
"""

import re
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.tenant import DEFAULT_ABBREVIATION_DICTIONARY, TenantSettings


class ItemNormalizer:
    """Normalizes item descriptions using an abbreviation dictionary.

    Loaded once at init with a tenant's abbreviation dictionary.
    Applies abbreviation substitution (case-insensitive, whole-word only),
    then lowercases, then strips extra whitespace.
    """

    def __init__(self, abbreviation_dictionary: dict[str, str]) -> None:
        """Initialize with an abbreviation dictionary.

        Args:
            abbreviation_dictionary: Mapping of abbreviations to normalized forms.
                Keys are abbreviation strings (e.g., "MT"),
                values are normalized forms (e.g., "metric_ton").
        """
        self._dictionary = abbreviation_dictionary
        # Build a compiled regex for each abbreviation for whole-word matching
        # Sort by key length descending so longer abbreviations match first
        self._patterns: list[tuple[re.Pattern[str], str]] = []
        for abbrev in sorted(abbreviation_dictionary.keys(), key=len, reverse=True):
            pattern = re.compile(
                r"\b" + re.escape(abbrev) + r"\b",
                re.IGNORECASE,
            )
            self._patterns.append((pattern, abbreviation_dictionary[abbrev]))

    def normalize_item_desc(self, raw_desc: str) -> str:
        """Normalize an item description.

        Applies abbreviation substitution first (case-insensitive, whole-word
        only), then lowercases, then strips extra whitespace.

        Args:
            raw_desc: The raw item description from a document.

        Returns:
            Normalized item description string.
        """
        if not raw_desc:
            return ""

        desc = raw_desc

        # Apply abbreviation substitution (case-insensitive, whole-word)
        for pattern, replacement in self._patterns:
            desc = pattern.sub(replacement, desc)

        # Lowercase
        desc = desc.lower()

        # Strip extra whitespace
        desc = re.sub(r"\s+", " ", desc).strip()

        return desc


async def create_item_normalizer(
    tenant_id: UUID,
    db: AsyncSession,
) -> ItemNormalizer:
    """Factory function to create an ItemNormalizer for a given tenant.

    Loads the abbreviation_dictionary from tenant_settings. Falls back to
    the system default dictionary if tenant settings are not found.

    Args:
        tenant_id: The tenant UUID.
        db: Async database session.

    Returns:
        An initialized ItemNormalizer with the tenant's abbreviation dictionary.
    """
    stmt = select(TenantSettings).where(TenantSettings.tenant_id == tenant_id)
    result = await db.execute(stmt)
    tenant_settings = result.scalar_one_or_none()

    if tenant_settings is not None and tenant_settings.abbreviation_dictionary:
        dictionary = tenant_settings.abbreviation_dictionary
    else:
        dictionary = DEFAULT_ABBREVIATION_DICTIONARY

    return ItemNormalizer(abbreviation_dictionary=dictionary)

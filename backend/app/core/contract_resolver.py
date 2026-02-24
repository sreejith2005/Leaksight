"""
LeakSight V1 — Contract Resolver

Source: docs/DATABASE_SCHEMA.md (contract version resolution logic),
       docs/RULES_ENGINE.md (Step 1 — Contract Validity Check),
       docs/ARCHITECTURE.md (Match stage)

Resolves the contract version applicable for a given vendor on a given
invoice date. The system must NEVER use the "latest" contract version
by default — it must use the version valid on the invoice date.

Date range convention: valid_from is INCLUSIVE, valid_to is EXCLUSIVE.
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.contracts import Contract, ContractVersion


class ContractResolutionStatus(str, Enum):
    """Outcome of a contract version resolution attempt.

    FOUND:   Exactly one valid version — clean match, proceed with rules.
    OVERLAP: More than one valid version — flag for manual review.
    NONE:    No valid version covers the invoice date — skip Rule 1.
    """

    FOUND = "FOUND"
    OVERLAP = "OVERLAP"
    NONE = "NONE"


@dataclass
class ContractResolutionResult:
    """Result of contract version resolution.

    Attributes:
        status: Resolution outcome.
        versions: List of matching ContractVersion rows.
                  Length 1 for FOUND, >1 for OVERLAP, 0 for NONE.
    """

    status: ContractResolutionStatus
    versions: List  # List of ContractVersion ORM instances


async def get_valid_contract_version(
    vendor_id: UUID,
    invoice_date: date,
    tenant_id: UUID,
    db: AsyncSession,
) -> ContractResolutionResult:
    """Resolve the contract version valid for a vendor on an invoice date.

    Uses a half-open interval: valid_from <= invoice_date < valid_to.
    (valid_from is inclusive, valid_to is exclusive.)

    Returns:
        ContractResolutionResult with status:
        - FOUND (1 version) → proceed with Rule 1
        - NONE  (0 versions) → skip Rule 1 entirely, no leakage record
        - OVERLAP (>1 versions) → flag for manual review, confidence = 0.5

    This function runs within an existing RLS-scoped session.
    """
    stmt = (
        select(ContractVersion)
        .join(Contract, ContractVersion.contract_id == Contract.id)
        .where(
            Contract.vendor_id == vendor_id,
            Contract.tenant_id == tenant_id,
            ContractVersion.valid_from <= invoice_date,
            ContractVersion.valid_to > invoice_date,  # exclusive upper bound
        )
    )

    result = await db.execute(stmt)
    versions = list(result.scalars().all())

    if len(versions) == 1:
        return ContractResolutionResult(
            status=ContractResolutionStatus.FOUND,
            versions=versions,
        )
    elif len(versions) > 1:
        return ContractResolutionResult(
            status=ContractResolutionStatus.OVERLAP,
            versions=versions,
        )
    else:
        return ContractResolutionResult(
            status=ContractResolutionStatus.NONE,
            versions=[],
        )
